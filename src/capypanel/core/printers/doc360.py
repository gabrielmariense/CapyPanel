"""Page counters from Doc360 MPS, the managed-print portal: one login without a browser, the
"latest counters" export (CSV, one line per printer), then a logout. Only reads: it opens the
login page, the export page and the export itself, never another link. Everything stays in
memory (cookies too), and the log gets only the outcome and the number of rows."""

import contextlib
import csv
import http.cookiejar
import io
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser

log = logging.getLogger(__name__)

BASE = "https://mps.doc360.com.br"
TIMEOUT = 30  # seconds per request; the export takes about 3
MAX_ANSWER = 5 * 1024 * 1024  # bytes: a few hundred printers is about 20 KB
# The latest-counters export's columns: the serial and the three counters.
SERIAL, LIFE, MONO, COLOR = "N/S", "Life", "Mono", "Color"


class Doc360Error(Exception):
    """Doc360 couldn't give the counters; the message says why, in a few plain words."""


class NoAnswer(Doc360Error):
    """Doc360 didn't answer: no network, or the portal is down."""


class Refused(Doc360Error):
    """Doc360 refused the login."""


class Changed(Doc360Error):
    """A page wasn't what CapyPanel expects: the portal changed."""


@dataclass(frozen=True)
class Account:
    partner: str  # the company's partner code ("parceiro") on the login page
    user: str
    password: str


@dataclass(frozen=True)
class Counter:
    life: int | None  # every page the printer has printed: Details' Total pages
    mono: int | None
    color: int | None


def key(serial: str) -> str:
    """How serials are matched: Doc360's N/S against the list's serial."""
    return serial.strip().casefold()


class _Forms(HTMLParser):
    """Every form on a page: its action and its fields, (name, type, value)."""

    def __init__(self) -> None:
        super().__init__()
        self.forms: list[tuple[str, list[tuple[str, str, str]]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "form":
            self.forms.append((a.get("action", ""), []))
        elif tag in ("input", "select", "button") and self.forms and a.get("name"):
            self.forms[-1][1].append((a["name"], a.get("type", tag).lower(), a.get("value", "")))


def _forms(page: str) -> list[tuple[str, list[tuple[str, str, str]]]]:
    parser = _Forms()
    parser.feed(page)
    return parser.forms


def _is_login(page: str) -> bool:
    return any(name == "senha" for _action, fields in _forms(page) for name, *_ in fields)


class _Session:
    def __init__(self, base: str, timeout: float) -> None:
        self.base, self.timeout = base.rstrip("/"), timeout
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())  # memory only
        )

    def ask(self, path: str, fields: list[tuple[str, str]] | None = None, referer: str = "") -> str:
        url = f"{self.base}/{path}"
        data = urllib.parse.urlencode(fields).encode() if fields is not None else None
        headers = {"User-Agent": "CapyPanel", "Accept-Language": "pt-BR,pt;q=0.9"}
        if data is not None:
            headers |= {"Content-Type": "application/x-www-form-urlencoded", "Origin": self.base}
            if referer:
                headers["Referer"] = f"{self.base}/{referer}"
        request = urllib.request.Request(url, data=data, headers=headers)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                body = response.read(MAX_ANSWER + 1)
                charset = response.headers.get_content_charset() or ""
        except urllib.error.HTTPError as e:
            raise Doc360Error(f"Doc360 answered with an error (HTTP {e.code}).") from None
        except (urllib.error.URLError, OSError) as e:
            reason = getattr(e, "reason", e)
            raise NoAnswer(f"Doc360 didn't answer ({reason}).") from None
        if len(body) > MAX_ANSWER:
            raise Changed("Doc360's answer was far bigger than expected.")
        if body.startswith(b"\xef\xbb\xbf"):
            return body[3:].decode("utf-8", errors="replace")
        try:
            return body.decode(charset or "utf-8")
        except (UnicodeDecodeError, LookupError):
            return body.decode("cp1252", errors="replace")


LOGIN_PAGE = "login/index.php"
LOGIN_ACTION = "login/acao.php"
EXPORT_PAGE = "docmps/index.php?menu=fechamento&secao=fechamento&modulo=porperiodo"
EXPORT_ACTION = "docmps/acao.php"
LOGOUT = "docmps/index.php?secao=logoff"


def read_counters(
    account: Account,
    *,
    base: str = BASE,
    timeout: float = TIMEOUT,
    today: Callable[[], date] = date.today,
) -> dict[str, Counter]:
    """Every printer's latest counters, by serial (see key()). Raises Doc360Error: Refused
    for a refused login (no retry), NoAnswer, or Changed when a page isn't as expected."""
    session = _Session(base, timeout)
    _log_in(session, account)
    try:
        page = session.ask(EXPORT_PAGE)
        if _is_login(page):
            raise Changed("Doc360 asked for the login again.")
        form = next((f for action, f in _forms(page) if action == "acao.php"), None)
        if form is None:
            raise Changed("Doc360's export page changed.")
        hidden = [(name, value) for name, kind, value in form if kind == "hidden"]
        clients = [value for name, _kind, value in form if name == "clientes[]"]
        now = today()  # last month, as the portal's own page offers; this export ignores it
        month, year = (12, now.year - 1) if now.month == 1 else (now.month - 1, now.year)
        fields = [
            *hidden,
            ("mes", str(month)),
            ("ano", str(year)),
            ("inicio", ""),
            ("fim", ""),
            ("retroativo", "1"),
            *(("clientes[]", client) for client in clients),
            ("botao", "csv_contadores"),
            ("envio", "enviar"),
        ]
        answer = session.ask(EXPORT_ACTION, fields, referer=EXPORT_PAGE)
        counters = parse_counters(answer)
        log.info("Doc360: latest counters for %d printers", len(counters))
        return counters
    finally:
        with contextlib.suppress(Doc360Error):  # the session also ends on its own there
            session.ask(LOGOUT)


def _log_in(session: _Session, account: Account) -> None:
    page = session.ask(LOGIN_PAGE)
    form = next((f for _action, f in _forms(page) if any(n == "senha" for n, *_ in f)), None)
    if form is None:
        raise Changed("Doc360's login page changed.")
    typed = {"parceiro": account.partner, "login": account.user, "senha": account.password}
    fields = []
    for name, kind, value in form:
        if name in typed:
            value = typed[name]
        elif name == "dispositivo" and not value:
            value = "desktop"
        if kind in ("hidden", "text", "password", "email", "button", "submit"):
            fields.append((name, value))
    if _is_login(session.ask(LOGIN_ACTION, fields, referer=LOGIN_PAGE)):
        log.info("Doc360: the login was refused")
        raise Refused("Doc360 refused the login.")


def parse_counters(text: str) -> dict[str, Counter]:
    """The latest-counters CSV: ";" between cells, a header line first. Raises Changed when
    it isn't that file (a web page, or its columns changed)."""
    text = text.removeprefix("﻿")
    start = text.lstrip()[:200].lower()
    if start.startswith(("<!doctype", "<html")) or "<form" in start:
        raise Changed("Doc360 sent a web page instead of the counters.")
    rows = csv.DictReader(io.StringIO(text), delimiter=";")
    columns = {(name or "").strip() for name in rows.fieldnames or ()}
    if not {SERIAL, LIFE} <= columns:
        raise Changed("Doc360's counters file changed: no N/S or Life column.")
    found: dict[str, Counter] = {}
    for row in rows:
        cells = {(k or "").strip(): (v or "").strip() for k, v in row.items() if isinstance(v, str)}
        serial = key(cells.get(SERIAL, ""))
        if not serial:
            continue
        counter = Counter(*(_number(cells.get(name, "")) for name in (LIFE, MONO, COLOR)))
        old = found.get(serial)
        if old is None or (counter.life or 0) >= (old.life or 0):  # listed twice: the newer
            found[serial] = counter
    return found


def _number(cell: str) -> int | None:
    digits = re.sub(r"[.\s ]", "", cell)  # "12.345" or "12 345", in case it changes
    return int(digits) if digits.isdigit() else None

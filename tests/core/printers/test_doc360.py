"""Doc360 MPS counters against a small fake portal on this PC, with invented data."""

import logging
import threading
import urllib.parse
from collections.abc import Iterator
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from capypanel.core.printers import doc360
from capypanel.core.printers.doc360 import Account, Counter

PASSWORD = "sample-password"
CSV = (
    "Cliente;Site;Patr.;Modelo;IP;N/S;Life;Mono;Color\n"
    "Example Co;Front desk;A-1;SAMPLE M4070;192.0.2.10;SAMPLE0011;12345;12345;0\n"
    "Example Co;Lab;A-2;SAMPLE C480;192.0.2.11; sample0012 ;20500;15000;5500\n"
    "Example Co;Lab;A-3;SAMPLE C480;192.0.2.12;;99;99;0\n"
)
LOGIN_FORM = """<!doctype html><html><body>
<form method="post" action="acao.php">
<input type="hidden" name="token" value="t-1"><input type="hidden" name="secao" value="login">
<input type="text" name="parceiro"><input type="text" name="login">
<input type="password" name="senha"><input type="hidden" name="dispositivo" value="">
<button type="submit" name="entrar" value="1">Entrar</button>
</form></body></html>"""
EXPORT_FORM = """<!doctype html><html><body>
<a href="index.php?acao=alteracontrato&id=1">contract</a>
<form method="post" action="acao.php">
<input type="hidden" name="secao" value="fechamento">
<input type="hidden" name="modulo" value="porperiodo">
<input type="checkbox" name="clientes[]" value="7" checked>
<input type="checkbox" name="clientes[]" value="9" checked>
<select name="mes"></select><select name="ano"></select>
</form></body></html>"""


class Portal:
    """What the fake portal answers, and what it was asked."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str]] = []  # (method, path with query)
        self.posted: dict[str, list[tuple[str, str]]] = {}
        self.counters = CSV
        self.empty_months: set[tuple[str, str]] = set()  # (mes, ano) with no counters yet
        self.exports: list[tuple[str, str]] = []  # (mes, ano) of each export asked for
        self.login_page = LOGIN_FORM
        self.export_page = EXPORT_FORM


@pytest.fixture
def portal() -> Iterator[tuple[Portal, str]]:
    state = Portal()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

        def _send(self, body: str, kind: str = "text/html", cookie: str = "") -> None:
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", f"{kind}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(data)

        def _signed_in(self) -> bool:
            return "PHPSESSID=ok" in (self.headers.get("Cookie") or "")

        def do_GET(self) -> None:
            state.asked.append(("GET", self.path))
            if self.path == "/login/index.php":
                self._send(state.login_page)
            elif self.path.startswith("/docmps/index.php?menu=fechamento"):
                self._send(state.export_page if self._signed_in() else state.login_page)
            elif self.path == "/docmps/index.php":
                self._send("<html>home</html>")
            elif self.path == "/docmps/index.php?secao=logoff":
                self._send(state.login_page, cookie="PHPSESSID=gone; Path=/")
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            state.asked.append(("POST", self.path))
            length = int(self.headers.get("Content-Length") or 0)
            fields = urllib.parse.parse_qsl(self.rfile.read(length).decode(), True)
            state.posted[self.path] = fields
            if self.path == "/login/acao.php":
                if ("senha", PASSWORD) in fields:
                    self.send_response(302)
                    self.send_header("Location", "/docmps/index.php")
                    self.send_header("Set-Cookie", "PHPSESSID=ok; Path=/")
                    self.end_headers()
                else:
                    self._send(state.login_page)
            elif self.path == "/docmps/acao.php" and self._signed_in():
                asked = dict(fields)
                month = (asked.get("mes", ""), asked.get("ano", ""))
                state.exports.append(month)
                empty = "Cliente;Site;Patr.;Modelo;IP;N/S;Life;Mono;Color\n"
                body = empty if month in state.empty_months else state.counters
                self._send(body, kind="text/csv")
            else:
                self._send(state.login_page)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield state, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def account(password: str = PASSWORD) -> Account:
    return Account("SAMPLE-PARTNER", "EXAMPLE\\user", password)


def test_reads_the_latest_counters_by_serial(portal: tuple[Portal, str]) -> None:
    state, base = portal
    found = doc360.read_counters(account(), base=base, today=lambda: date(2026, 1, 15))
    assert found == {
        "sample0011": Counter(12345, 12345, 0),
        "sample0012": Counter(20500, 15000, 5500),
    }
    login = dict(state.posted["/login/acao.php"])
    assert login["parceiro"] == "SAMPLE-PARTNER" and login["login"] == "EXAMPLE\\user"
    assert login["token"] == "t-1" and login["dispositivo"] == "desktop"
    export = state.posted["/docmps/acao.php"]
    assert ("botao", "csv_contadores") in export
    assert state.exports == [("1", "2026")]  # this month's counters: the newest
    assert [v for k, v in export if k == "clientes[]"] == ["7", "9"]
    assert ("secao", "fechamento") in export and ("modulo", "porperiodo") in export


def test_early_in_a_month_with_none_yet_it_takes_last_month_s(
    portal: tuple[Portal, str],
) -> None:
    state, base = portal
    state.empty_months = {("1", "2026")}
    found = doc360.read_counters(account(), base=base, today=lambda: date(2026, 1, 2))
    assert state.exports == [("1", "2026"), ("12", "2025")]
    assert len(found) == 2


def test_asks_only_for_its_own_pages_and_logs_out(portal: tuple[Portal, str]) -> None:
    state, base = portal
    doc360.read_counters(account(), base=base)
    assert state.asked == [
        ("GET", "/login/index.php"),
        ("POST", "/login/acao.php"),
        ("GET", "/docmps/index.php"),  # where the login leads
        ("GET", "/docmps/index.php?menu=fechamento&secao=fechamento&modulo=porperiodo"),
        ("POST", "/docmps/acao.php"),
        ("GET", "/docmps/index.php?secao=logoff"),
    ]
    assert not any("alteracontrato" in path for _method, path in state.asked)


def test_a_refused_login_stops_at_once(portal: tuple[Portal, str]) -> None:
    state, base = portal
    with pytest.raises(doc360.Refused):
        doc360.read_counters(account("wrong"), base=base)
    assert [path for _m, path in state.asked] == ["/login/index.php", "/login/acao.php"]


def test_a_changed_login_page(portal: tuple[Portal, str]) -> None:
    state, base = portal
    state.login_page = "<html><body>Maintenance</body></html>"
    with pytest.raises(doc360.Changed, match="login page changed"):
        doc360.read_counters(account(), base=base)


def test_a_changed_export_page(portal: tuple[Portal, str]) -> None:
    state, base = portal
    state.export_page = "<html><body>New look</body></html>"
    with pytest.raises(doc360.Changed, match="export page changed"):
        doc360.read_counters(account(), base=base)
    assert state.asked[-1] == ("GET", "/docmps/index.php?secao=logoff")


def test_a_web_page_instead_of_the_counters(portal: tuple[Portal, str]) -> None:
    state, base = portal
    state.counters = "<!doctype html><html>Erro</html>"
    with pytest.raises(doc360.Changed, match="web page"):
        doc360.read_counters(account(), base=base)


def test_no_answer() -> None:
    with pytest.raises(doc360.NoAnswer):
        doc360.read_counters(account(), base="http://127.0.0.1:9", timeout=2)


def test_the_log_has_no_secrets(
    portal: tuple[Portal, str], caplog: pytest.LogCaptureFixture
) -> None:
    _state, base = portal
    with caplog.at_level(logging.DEBUG):
        doc360.read_counters(account(), base=base)
        with pytest.raises(doc360.Refused):
            doc360.read_counters(account("wrong-one"), base=base)
    text = caplog.text
    assert "for 2 printers" in text
    for secret in (PASSWORD, "wrong-one", "SAMPLE-PARTNER", "SAMPLE0011", "12345"):
        assert secret not in text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("N/S;Life\nX1;1.234\n", {"x1": Counter(1234, None, None)}),
        ("N/S;Life;Mono\nX1;;7\n", {"x1": Counter(None, 7, None)}),
        ("N/S;Life\nX1;10\nx1;30\nX1;20\n", {"x1": Counter(30, None, None)}),
        ("﻿N/S;Life\nX1;5\n", {"x1": Counter(5, None, None)}),
        ("N/S;Life\n", {}),
    ],
)
def test_parse_counters(text: str, expected: dict[str, Counter]) -> None:
    assert doc360.parse_counters(text) == expected


def test_parse_counters_without_its_columns() -> None:
    with pytest.raises(doc360.Changed, match="N/S or Life"):
        doc360.parse_counters("Cliente;Serial;Total\nExample;X1;5\n")

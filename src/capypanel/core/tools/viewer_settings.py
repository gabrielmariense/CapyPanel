import codecs
import logging
import os
import tempfile
import threading
from collections.abc import Collection
from pathlib import Path

from capypanel.core.i18n import _

log = logging.getLogger(__name__)
MAX_SIZE = 256 * 1024  # real ones are a few KB
KEEP_COPY_FOR = 60  # seconds; the viewer reads its settings as it starts
# A saved VNC password is DES under a key every VNC viewer knows, so anyone can read it back.
NEVER_KEPT = ("password",)


class SettingsFileError(ValueError):
    pass


def read(path: Path, clear: Collection[str]) -> bytes:
    if path.stat().st_size > MAX_SIZE:
        raise SettingsFileError(_("The file is too big to be viewer settings."))
    return clean(path.read_bytes(), clear)


def clean(raw: bytes, clear: Collection[str]) -> bytes:
    text, encoding = _decode(raw)
    cleared = {key.casefold() for key in (*clear, *NEVER_KEPT)}
    lines, settings = [], 0
    for line in text.splitlines(keepends=True):
        key = _key(line)
        if key is None:
            lines.append(line)
            continue
        settings += 1
        lines.append(_with_value(line, "") if key.casefold() in cleared else line)
    if not settings:
        raise SettingsFileError(_("The file has no settings."))
    return "".join(lines).encode(encoding)


def emptied(raw: bytes) -> bytes | None:
    try:
        text, _encoding = _decode(raw)
        saved = any(
            (key := _key(line)) is not None
            and key.casefold() in NEVER_KEPT
            and line.partition("=")[2].strip()
            for line in text.splitlines()
        )
        return clean(raw, ()) if saved else None
    except SettingsFileError:
        return None


def temp_copy(content: bytes, extension: str) -> Path:
    handle, name = tempfile.mkstemp(prefix="capypanel-", suffix=extension)
    with os.fdopen(handle, "wb") as f:
        f.write(content)
    path = Path(name)
    timer = threading.Timer(KEEP_COPY_FOR, _delete, (path,))
    timer.daemon = True
    timer.start()
    return path


def _decode(raw: bytes) -> tuple[str, str]:
    # latin-1 maps every byte to itself, whatever the file's real code page.
    utf16 = raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
    encoding = "utf-16" if utf16 else "latin-1"
    text = raw.decode(encoding)
    if "\x00" in text:
        raise SettingsFileError(_("This isn't a text file."))
    return text, encoding


def _key(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped[0] in ";#" or (stripped[0] == "[" and stripped[-1] == "]"):
        return None
    key, sep, _value = stripped.partition("=")
    if not sep or not key.strip():
        raise SettingsFileError(
            _("This doesn't look like a viewer settings file: “{line}”.").format(line=stripped[:60])
        )
    return key.strip()


def _with_value(line: str, value: str) -> str:
    ending = line[len(line.rstrip("\r\n")) :]
    return line[: line.index("=") + 1] + value + ending


def _delete(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        log.info("Couldn't delete %s: %s", path, e)

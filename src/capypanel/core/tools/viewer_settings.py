"""Viewer settings files, such as UltraVNC's .vnc: a profile can carry one saved from the viewer,
so every viewer option is available without CapyPanel rebuilding them. The lines CapyPanel sets
itself (address, port, password, encryption plugin) are removed, so the file never holds a
secret or a host, and the profile's own choices always win.

The viewer gets a temporary copy, never the shared file: a viewer that saves its settings on
exit can't change it."""

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


class SettingsFileError(ValueError):
    """The file isn't a viewer settings file; the message says why."""


def read(path: Path, remove: Collection[str]) -> bytes:
    """The file's content without the removed settings. Raises OSError, SettingsFileError."""
    if path.stat().st_size > MAX_SIZE:
        raise SettingsFileError(_("The file is too big to be viewer settings."))
    return clean(path.read_bytes(), remove)


def clean(raw: bytes, remove: Collection[str]) -> bytes:
    """Drops every `key=value` line whose key is in `remove` (any case, any section). The rest is
    kept byte for byte, in the file's own encoding."""
    # latin-1 maps every byte to itself, whatever the file's real code page.
    utf16 = raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE))
    encoding = "utf-16" if utf16 else "latin-1"
    text = raw.decode(encoding)
    if "\x00" in text:
        raise SettingsFileError(_("This isn't a text file."))
    removed = {key.casefold() for key in remove}
    kept, settings = [], 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped or stripped[0] in ";#" or (stripped[0] == "[" and stripped[-1] == "]"):
            kept.append(line)  # blank, comment or [section]
            continue
        key, sep, _value = stripped.partition("=")
        if not sep or not key.strip():
            raise SettingsFileError(
                _("This doesn't look like a viewer settings file: “{line}”.").format(
                    line=stripped[:60]
                )
            )
        settings += 1
        if key.strip().casefold() not in removed:
            kept.append(line)
    if not settings:
        raise SettingsFileError(_("The file has no settings."))
    return "".join(kept).encode(encoding)


def temp_copy(content: bytes, extension: str) -> Path:
    """A copy in this user's own temp folder, deleted a minute later. Raises OSError."""
    handle, name = tempfile.mkstemp(prefix="capypanel-", suffix=extension)
    with os.fdopen(handle, "wb") as f:
        f.write(content)
    path = Path(name)
    timer = threading.Timer(KEEP_COPY_FOR, _delete, (path,))
    timer.daemon = True
    timer.start()
    return path


def _delete(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as e:  # the viewer still has it open
        log.info("Couldn't delete %s: %s", path, e)

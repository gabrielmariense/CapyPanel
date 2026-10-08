"""Writing the app's files safely: a new version is swapped in whole, so a crash or a second
writer never leaves half a file. Also: whether this user may create files in a folder, and
making a shared folder that other users can read but not change."""

import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from capypanel.core import winsec

log = logging.getLogger(__name__)


def write_atomic(path: Path, content: bytes) -> None:
    """Writes a temp file beside `path`, then swaps it in. Raises OSError."""
    # A unique temp name, so two people saving the same shared file never share a temp file.
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_bytes(content)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_json(path: Path, data: Any) -> None:
    write_atomic(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def can_create_files(folder: Path) -> bool:
    """Whether Windows lets this user create files in `folder`, or where it would be made."""
    while not folder.exists() and folder.parent != folder:
        folder = folder.parent  # the folder is made on the first save
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".capypanel-", suffix=".tmp"):
            pass
    except OSError:
        return False
    return True


def make_shared_folder(folder: Path) -> None:
    """Creates the folder, readable by everyone on the PC but changed only by its creator and
    administrators; ProgramData would otherwise let any user add files. Raises OSError."""
    folder.mkdir(parents=True, exist_ok=True)
    try:
        winsec.make_shared(folder, winsec.current_user_sid())
    except OSError as e:
        log.warning("Couldn't set permissions on %s: %s", folder, e)

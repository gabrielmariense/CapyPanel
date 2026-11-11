"""The app log: one small rotating file per user, attached to bug reports. Never log secrets."""

import logging
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

LINES_SIZE, LINES_KEEP = 2_000_000, 5  # a lines log (append_line): bytes per file, older kept
_LINES_LOCK = threading.Lock()  # several hosts at once write to one log


def setup_logging(log_file: Path, level: int = logging.INFO) -> Path:
    # One file per user: two users at once would corrupt a shared file when it rotates.
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    return log_file


def append_line(log_file: Path, line: str) -> None:
    """One line at the end of a log of its own (the user profiles log); a full one moves aside
    first, the oldest dropped. One writer at a time, so lines of hosts worked on together never
    mix."""
    with _LINES_LOCK:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        if log_file.exists() and log_file.stat().st_size > LINES_SIZE:
            for n in range(LINES_KEEP - 1, 0, -1):
                older = log_file.with_name(f"{log_file.name}.{n}")
                if older.exists():
                    older.replace(log_file.with_name(f"{log_file.name}.{n + 1}"))
            log_file.replace(log_file.with_name(f"{log_file.name}.1"))
        with log_file.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

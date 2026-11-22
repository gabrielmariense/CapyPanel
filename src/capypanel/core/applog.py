"""Never log a secret: the log goes with bug reports."""

import logging
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

LINES_SIZE, LINES_KEEP = 2_000_000, 5  # bytes per file, files kept
_LINES_LOCK = threading.Lock()


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

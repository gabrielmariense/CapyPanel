"""The app log: one small rotating file per user, attached to bug reports. Never log secrets."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_file: Path, level: int = logging.INFO) -> Path:
    # One file per user: two users at once would corrupt a shared file when it rotates.
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    return log_file

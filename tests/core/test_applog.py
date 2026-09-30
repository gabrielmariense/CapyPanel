import logging
from pathlib import Path

from capypanel.core import applog


def test_log_file_is_created_and_written(tmp_path: Path) -> None:
    root = logging.getLogger()
    before = list(root.handlers)
    log_file = applog.setup_logging(tmp_path / "logs")
    try:
        logging.getLogger("capypanel.test").info("hello from the test")
        for handler in root.handlers:
            handler.flush()
        assert "hello from the test" in log_file.read_text(encoding="utf-8")
    finally:
        for handler in [h for h in root.handlers if h not in before]:
            root.removeHandler(handler)
            handler.close()  # Windows can't delete the temp folder while the file is open

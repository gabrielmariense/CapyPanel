import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from capypanel import capyprinters
from capypanel.core import identity, settings
from capypanel.ui.main_window.window import MainWindow
from capypanel.ui.printers_tool.tool import PrintersTool

# Hosts' own code: CapyPrinters' copy leaves it out, so its build must never reach it.
HOSTS_ONLY = (
    "capypanel.ui.hosts_tool",
    "capypanel.ui.connect",
    "capypanel.ui.checks",
    "capypanel.ui.import_hosts",
    "capypanel.ui.settings.connections",
    "capypanel.core.remote",
    "capypanel.core.tools",
)

# Imports what starting CapyPrinters imports (its entry point, the app, the Printers tool), in a
# fresh Python, and prints every capypanel module loaded.
PROBE = """
import sys
from capypanel import capyprinters
import capypanel.ui.app, capypanel.ui.printers_tool.tool
print("\\n".join(sorted(m for m in sys.modules if m.startswith("capypanel"))))
"""


def test_capyprinters_imports_none_of_hosts_code() -> None:
    found = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True, timeout=60
    ).stdout.split()
    assert "capypanel.ui.printers_tool.tool" in found and "capypanel.ui.app" in found
    assert [m for m in found if m.startswith(HOSTS_ONLY)] == []


@pytest.fixture
def as_capyprinters(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(identity, "_current", capyprinters.IDENTITY)
    yield


def test_capyprinters_keeps_its_files_in_its_own_folder(
    as_capyprinters: None, tmp_path: Path
) -> None:
    paths = settings.resolve_paths(tmp_path, env={"PROGRAMDATA": str(tmp_path / "pd")})
    assert paths.root == tmp_path / "pd" / "CapyPrinters" and not paths.portable
    (tmp_path / "capyprinters.portable").touch()  # its own marker, not CapyPanel's
    assert settings.resolve_paths(tmp_path).portable


def test_capyprinters_window_has_printers_and_no_rail(
    as_capyprinters: None, qapp: QApplication, tmp_path: Path
) -> None:
    (tmp_path / "capyprinters.portable").touch()
    win = MainWindow(settings.resolve_paths(tmp_path), {"schema": 1}, tools=(PrintersTool,))
    try:
        assert list(win.tools) == ["printers"]
        assert win.rail.isHidden()
        assert "CapyPrinters" in win.windowTitle()
        dialog = win.settings_dialog()
        rows = [dialog.page_list.item(i).text().strip() for i in range(dialog.page_list.count())]
        assert "Hosts" not in rows and rows[-3:] == ["Printers", "General", "Printer lists"]
    finally:
        win.close()

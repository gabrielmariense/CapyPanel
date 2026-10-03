from collections.abc import Callable
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QFileDialog

from capypanel.core import settings
from capypanel.core.hosts.document import OpenList
from capypanel.core.hosts.model import HostList
from capypanel.core.tools.catalog import Catalogs
from capypanel.core.tools.profiles import ConnectionProfile
from capypanel.ui.settings import connections
from capypanel.ui.settings.connections import ConnectionsPage, ProfileDialog


@pytest.fixture
def catalogs(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Catalogs:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    monkeypatch.setattr(settings, "app_dir", lambda: tmp_path)
    found = {"ultravnc": Path(r"C:\Tools\vncviewer.exe")}  # RealVNC isn't installed here
    monkeypatch.setattr(connections.detect, "find_executable", lambda t: found.get(t.id))
    return Catalogs.for_paths(settings.resolve_paths(tmp_path))


def _answer(monkeypatch: pytest.MonkeyPatch, fill: Callable[[ProfileDialog], None]) -> None:
    def run(dialog: ProfileDialog) -> int:
        fill(dialog)
        return 1  # Accepted

    monkeypatch.setattr(ProfileDialog, "exec", run)


def _select(page: ConnectionsPage, profile_id: str) -> None:
    for row in range(page.list.count()):
        item = page.list.item(row)
        if item is not None and item.data(256) == profile_id:  # Qt.ItemDataRole.UserRole
            page.list.setCurrentItem(item)
            item.setSelected(True)


def test_add_a_shared_profile(catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch) -> None:
    page = ConnectionsPage(catalogs, None)

    def fill(dialog: ProfileDialog) -> None:
        dialog.name.setText("Clinics (SecureVNC)")
        dialog.login.setCurrentIndex(dialog.login.findData("account"))
        dialog.option_boxes["securevnc"].setChecked(True)

    _answer(monkeypatch, fill)
    page.add()
    stored = catalogs.profiles.find("clinics-securevnc")
    assert stored == ConnectionProfile(
        "clinics-securevnc", "ultravnc", "account", ("securevnc",), name="Clinics (SecureVNC)"
    )
    assert (catalogs.profiles.folder / "clinics-securevnc.json").is_file()
    assert "Clinics (SecureVNC)" in [page.list.item(r).text() for r in range(page.list.count())]


def test_the_editor_offers_only_what_the_chosen_tool_supports(catalogs: Catalogs) -> None:
    tools = [e.item for e in catalogs.tools.all()]
    dialog = ProfileDialog(None, "New", tools, {"ultravnc"})
    dialog.tool.setCurrentIndex(dialog.tool.findData("ultravnc"))
    assert list(dialog.option_boxes) == ["securevnc"]
    assert [dialog.login.itemData(i) for i in range(dialog.login.count())] == [
        "account", "password",
    ]  # fmt: skip
    assert dialog.port.text() == "Default (5900)"
    realvnc = dialog.tool.findData("realvnc")
    assert dialog.tool.itemText(realvnc) == "RealVNC Viewer (not installed on this PC)"
    dialog.tool.setCurrentIndex(realvnc)
    assert dialog.option_boxes == {}  # RealVNC has no options
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()  # a name is required
    dialog.name.setText("Pis")
    assert ok.isEnabled()


def test_starter_profiles_can_be_duplicated_edited_and_deleted(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = ConnectionsPage(catalogs, None)
    _select(page, "ultravnc")
    buttons = (page.edit_button, page.duplicate_button, page.delete_button)
    assert all(b.isEnabled() for b in buttons)
    _answer(monkeypatch, lambda dialog: None)  # keep the suggested name
    page.duplicate()
    copy = catalogs.profiles.find("ultravnc-copy")
    assert copy is not None and copy.name == "UltraVNC (copy)"
    monkeypatch.setattr(connections, "confirm", lambda *_args: True)
    _select(page, "ultravnc")
    page.delete()
    assert catalogs.profiles.find("ultravnc") is None


def test_deleting_says_how_many_hosts_use_it(
    catalogs: Catalogs, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalogs.profiles.save(ConnectionProfile("pis", "realvnc", "account", name="Pis"))
    hl, group = HostList().add_group("Pis")
    hl = hl.set_group_profile(group.id, "pis")
    hl, _a = hl.add_host("PI-1", group.id, profile="pis")
    hl, _b = hl.add_host("PI-2", group.id, profile="pis")
    document = OpenList.save_as(tmp_path / "list.json", hl)
    page = ConnectionsPage(catalogs, document)
    asked: list[str] = []
    monkeypatch.setattr(
        connections, "confirm", lambda _parent, _title, text, _action: asked.append(text) or False
    )
    _select(page, "pis")
    page.delete()
    assert "2 hosts and 1 group" in asked[0]
    assert catalogs.profiles.find("pis") is not None  # cancelled: still there
    monkeypatch.setattr(connections, "confirm", lambda *_args: True)
    page.delete()
    assert catalogs.profiles.find("pis") is None


def test_a_folder_the_user_cannot_write_is_read_only(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(catalogs.profiles, "can_edit", lambda: False)
    page = ConnectionsPage(catalogs, None)
    _select(page, "ultravnc")
    buttons = (page.add_button, page.edit_button, page.duplicate_button, page.delete_button)
    assert not any(b.isEnabled() for b in buttons) and not page.default.isEnabled()


def test_the_default_profile_waits_for_save(catalogs: Catalogs) -> None:
    page = ConnectionsPage(catalogs, None)
    assert page.default_choice() == "ultravnc"
    page.default.setCurrentIndex(page.default.findData("realvnc"))
    assert page.default_choice() == "realvnc"
    assert catalogs.profiles.default_id() == "ultravnc"  # nothing written until Save


def test_tools_show_where_they_were_found_and_can_be_located(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = ConnectionsPage(catalogs, None)
    texts = [w.text() for w in page.findChildren(connections.QLabel)]
    assert any("Not found" in t for t in texts)  # RealVNC
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *_a, **_k: (r"D:\Portable\vncviewer.exe", "")
    )
    realvnc = catalogs.tools.find("realvnc")
    assert realvnc is not None
    page.locate(realvnc.item)
    located = catalogs.tools.find("realvnc")
    assert located is not None and located.item.executable == r"D:\Portable\vncviewer.exe"
    page.automatic(located.item)
    back = catalogs.tools.find("realvnc")
    assert back is not None and not back.item.executable

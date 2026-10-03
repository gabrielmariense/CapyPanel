from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt, QUrl
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
        if item is not None and item.data(Qt.ItemDataRole.UserRole) == profile_id:
            page.list.setCurrentItem(item)
            item.setSelected(True)


def _names(page: ConnectionsPage) -> list[str]:
    return [item.text() for row in range(page.list.count()) if (item := page.list.item(row))]


def test_a_new_profile_is_written_only_on_save(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = ConnectionsPage(catalogs, None)

    def fill(dialog: ProfileDialog) -> None:
        dialog.name.setText("Clinics (SecureVNC)")
        dialog.login.setCurrentIndex(dialog.login.findData("account"))
        dialog.option_boxes["securevnc"].setChecked(True)

    _answer(monkeypatch, fill)
    page.add()
    assert "Clinics (SecureVNC)" in _names(page)
    assert catalogs.profiles.find("clinics-securevnc") is None  # nothing written yet
    connections.apply(catalogs, page.changes())  # what Save does
    assert catalogs.profiles.find("clinics-securevnc") == ConnectionProfile(
        "clinics-securevnc", "ultravnc", "account", ("securevnc",), name="Clinics (SecureVNC)"
    )


def test_cancel_drops_every_change(catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch) -> None:
    page = ConnectionsPage(catalogs, None)
    monkeypatch.setattr(connections, "confirm", lambda *_args: True)
    _select(page, "ultravnc")
    page.delete()
    assert "UltraVNC" not in _names(page)
    # Cancel: the dialog closes without apply(); the store and folder are untouched.
    assert catalogs.profiles.find("ultravnc") is not None
    assert not catalogs.profiles.folder.exists()
    assert "UltraVNC" in _names(ConnectionsPage(catalogs, None))


def test_the_editor_offers_only_what_the_chosen_tool_supports(catalogs: Catalogs) -> None:
    tools = [e.item for e in catalogs.tools.all()]
    dialog = ProfileDialog(None, "New", tools, {"ultravnc"})
    assert dialog.tool.currentData() == "ultravnc"  # starts on a tool this PC has
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
    monkeypatch.setattr(connections, "confirm", lambda *_args: True)
    _select(page, "ultravnc")
    page.delete()
    connections.apply(catalogs, page.changes())
    copy = catalogs.profiles.find("ultravnc-copy")
    assert copy is not None and copy.name == "UltraVNC (copy)"
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
    assert "Pis" in _names(page)  # answered no: still there
    monkeypatch.setattr(connections, "confirm", lambda *_args: True)
    page.delete()
    assert page.changes().deleted == ("pis",)


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
    assert catalogs.profiles.default_id() == "ultravnc"  # nothing written until Save
    connections.apply(catalogs, page.changes())
    assert catalogs.profiles.default_id() == "realvnc"


def test_tool_paths_chosen_here_also_wait_for_save(
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
    assert page.changes().tool_paths == {"realvnc": r"D:\Portable\vncviewer.exe"}
    connections.apply(catalogs, page.changes())
    located = catalogs.tools.find("realvnc")
    assert located is not None and located.item.executable == r"D:\Portable\vncviewer.exe"
    page = ConnectionsPage(catalogs, None)
    page.automatic(located.item)
    connections.apply(catalogs, page.changes())
    back = catalogs.tools.find("realvnc")
    assert back is not None and not back.item.executable


def _choose_settings_file(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args, **_kw: (str(path), ""))


def test_a_settings_file_chosen_for_a_profile_is_cleaned_and_copied_on_save(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template = tmp_path / "saved from viewer.vnc"
    template.write_bytes(b"[connection]\r\nhost=10.0.0.9\r\n[options]\r\nviewonly=1\r\n")
    _choose_settings_file(monkeypatch, template)
    page = ConnectionsPage(catalogs, None)

    def fill(dialog: ProfileDialog) -> None:
        dialog.name.setText("View only")
        assert dialog.settings_state.text() == "The viewer's defaults"
        dialog.choose_settings.click()
        assert dialog.settings_state.text() == "From “saved from viewer.vnc”"

    _answer(monkeypatch, fill)
    page.add()
    assert not catalogs.profiles.folder.exists()  # nothing written before Save
    connections.apply(catalogs, page.changes())
    profile = catalogs.profiles.find("view-only")
    assert profile is not None and profile.settings_file == "view-only.vnc"
    copied = catalogs.profiles.folder / "view-only.vnc"
    assert copied.read_bytes() == b"[connection]\r\nhost=\r\n[options]\r\nviewonly=1\r\n"

    # A duplicate gets its own copy; going back to defaults removes the file.
    page = ConnectionsPage(catalogs, None)
    _select(page, "view-only")
    _answer(monkeypatch, lambda dialog: dialog.name.setText("View only 2"))
    page.duplicate()
    _select(page, "view-only")
    _answer(monkeypatch, lambda dialog: dialog.default_settings.click())
    page.edit()
    connections.apply(catalogs, page.changes())
    assert not copied.exists()
    assert (catalogs.profiles.folder / "view-only-2.vnc").read_bytes() == (
        b"[connection]\r\nhost=\r\n[options]\r\nviewonly=1\r\n"
    )


def test_only_tools_that_read_a_settings_file_offer_one(catalogs: Catalogs) -> None:
    tools = [e.item for e in catalogs.tools.all()]
    dialog = ProfileDialog(None, "New", tools, {"ultravnc"})
    assert dialog.choose_settings.isVisibleTo(dialog)
    dialog.tool.setCurrentIndex(dialog.tool.findData("realvnc"))
    assert not dialog.choose_settings.isVisibleTo(dialog)


def test_a_file_that_isnt_viewer_settings_is_refused(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    junk = tmp_path / "notes.vnc"
    junk.write_text("just some notes", encoding="utf-8")
    _choose_settings_file(monkeypatch, junk)
    warnings: list[str] = []
    monkeypatch.setattr(
        connections.QMessageBox, "warning", lambda _parent, _title, text: warnings.append(text)
    )
    tools = [e.item for e in catalogs.tools.all()]
    dialog = ProfileDialog(None, "New", tools, {"ultravnc"})
    dialog.choose_settings.click()
    assert warnings and dialog.new_settings is None
    assert dialog.settings_state.text() == "The viewer's defaults"


def test_with_a_settings_file_the_file_decides_not_the_options(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template = tmp_path / "secure.vnc"
    template.write_bytes(b"[options]\r\nUseDSMPlugin=1\r\nDSMPlugin=SecureVNCPlugin64.dsm\r\n")
    _choose_settings_file(monkeypatch, template)
    tools = [e.item for e in catalogs.tools.all()]
    dialog = ProfileDialog(None, "New", tools, {"ultravnc"})
    dialog.name.setText("Secure")
    dialog.option_boxes["securevnc"].setChecked(True)
    dialog.choose_settings.click()
    box = dialog.option_boxes["securevnc"]
    assert not box.isEnabled() and not box.isChecked()
    assert dialog.profile("secure").options == ()  # nothing added on top of the file
    assert dialog.new_settings is not None and b"UseDSMPlugin=1" in dialog.new_settings
    dialog.default_settings.click()
    assert dialog.option_boxes["securevnc"].isEnabled()


def test_remote_tools_show_a_state_and_only_the_actions_that_fit(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = ConnectionsPage(catalogs, None)  # UltraVNC found by itself, RealVNC missing
    assert page.tool_status["ultravnc"].text() == "✓ Found"
    assert page.tool_status["ultravnc"].toolTip() == r"C:\Tools\vncviewer.exe"  # not on the page
    assert list(page.tool_buttons["ultravnc"]) == ["locate"]
    assert page.tool_buttons["ultravnc"]["locate"].text() == "Choose another…"
    assert page.tool_status["realvnc"].text() == "✗ Not found"
    assert list(page.tool_buttons["realvnc"]) == ["locate", "download"]
    opened: list[QUrl] = []
    monkeypatch.setattr(connections.QDesktopServices, "openUrl", lambda url: opened.append(url))
    page.tool_buttons["realvnc"]["download"].click()
    assert [u.toString() for u in opened] == ["https://www.realvnc.com/en/connect/download/viewer/"]

    def chosen_only(tool: Any) -> Path | None:
        return Path(tool.executable) if tool.executable else None

    monkeypatch.setattr(connections.detect, "find_executable", chosen_only)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *_a, **_k: (r"D:\Apps\vncviewer.exe", "")
    )
    page.tool_buttons["realvnc"]["locate"].click()
    assert page.tool_status["realvnc"].text() == "✓ Your choice"
    assert list(page.tool_buttons["realvnc"]) == ["locate", "automatic"]
    assert not (catalogs.tools.folder / "_paths.json").exists()  # only on Save
    connections.apply(catalogs, page.changes())
    entry = catalogs.tools.find("realvnc")
    assert entry is not None and entry.item.executable == r"D:\Apps\vncviewer.exe"

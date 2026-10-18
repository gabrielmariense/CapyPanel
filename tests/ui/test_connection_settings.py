from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QFileDialog

from capypanel.core import i18n, settings, winsec
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
    for row in range(page.list.topLevelItemCount()):
        item = page.list.topLevelItem(row)
        if item is not None and item.data(0, Qt.ItemDataRole.UserRole) == profile_id:
            page.list.setCurrentItem(item)
            item.setSelected(True)


def _names(page: ConnectionsPage) -> list[str]:
    rows = range(page.list.topLevelItemCount())
    return [item.text(0) for row in rows if (item := page.list.topLevelItem(row))]


def _tool_row(page: ConnectionsPage, tool_id: str) -> tuple[str, str]:
    """The tool's status and the tooltip on it."""
    for row in range(page.tools.topLevelItemCount()):
        item = page.tools.topLevelItem(row)
        if item is not None and item.data(0, Qt.ItemDataRole.UserRole) == tool_id:
            return item.text(1), item.toolTip(1)
    raise AssertionError(tool_id)


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
    assert catalogs.profiles.find("pis") is None


def test_a_folder_the_user_cannot_write_is_read_only(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(catalogs.profiles, "can_edit", lambda: False)
    page = ConnectionsPage(catalogs, None)
    _select(page, "ultravnc")
    buttons = (page.add_button, page.edit_button, page.duplicate_button, page.delete_button)
    assert not any(b.isEnabled() for b in buttons) and not page.default.isEnabled()


def _choose_settings_file(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args, **_kw: (str(path), ""))


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
    assert _tool_row(page, "ultravnc") == ("✓ Found", r"C:\Tools\vncviewer.exe")
    page.select_tool("ultravnc")  # the buttons act on the tool picked
    assert page.tool_actions("ultravnc") == ["locate"]
    assert page.locate_button.text() == "Change path…" and page.locate_button.isEnabled()
    assert not page.automatic_button.isEnabled() and not page.download_button.isEnabled()
    assert _tool_row(page, "realvnc")[0] == "✗ Not found"
    page.select_tool("realvnc")
    assert page.tool_actions("realvnc") == ["locate", "download"]
    assert page.locate_button.text() == "Locate…" and page.download_button.isEnabled()
    opened: list[QUrl] = []
    monkeypatch.setattr(connections.QDesktopServices, "openUrl", lambda url: opened.append(url))
    page.download_button.click()
    assert [u.toString() for u in opened] == ["https://www.realvnc.com/en/connect/download/viewer/"]

    def chosen_only(tool: Any) -> Path | None:
        return Path(tool.executable) if tool.executable else None

    monkeypatch.setattr(connections.detect, "find_executable", chosen_only)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *_a, **_k: (r"D:\Apps\vncviewer.exe", "")
    )
    page.locate_button.click()
    assert _tool_row(page, "realvnc")[0] == "✓ Your choice"
    assert page.tool_actions("realvnc") == ["locate", "automatic"]
    assert page.automatic_button.isEnabled()  # still on RealVNC after the table refilled
    entry = catalogs.tools.find("realvnc")
    assert entry is not None and entry.item.executable == r"D:\Apps\vncviewer.exe"


def test_rdp_options_show_in_the_app_s_language(catalogs: Catalogs) -> None:
    tools = [e.item for e in catalogs.tools.all()]
    i18n.set_language("pt_BR")
    try:
        dialog = ProfileDialog(None, "Novo", tools, {"mstsc"})
        dialog.tool.setCurrentIndex(dialog.tool.findData("mstsc"))
        assert [b.text() for b in dialog.option_boxes.values()] == [
            "Sessão administrativa (só servidores)", "Tela cheia", "Usar todos os meus monitores"
        ]  # fmt: skip
        dialog.tool.setCurrentIndex(dialog.tool.findData("ultravnc"))
        assert [b.text() for b in dialog.option_boxes.values()] == ["SecureVNC plugin"]
    finally:
        i18n.set_language("en")


def test_files_that_arent_used_are_named_with_the_reason(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = catalogs.profiles.folder
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "broken.json").write_text("{", encoding="utf-8")
    (folder / "planted.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(winsec, "made_by_trusted", lambda path: path.name != "planted.json")
    catalogs.profiles.reload()
    page = ConnectionsPage(catalogs, None)
    assert not page.profiles_skipped.isHidden()
    assert page.profiles_skipped.text() == (
        "• 2 files skipped: broken.json (can't be read), planted.json (made by another user)"
    )  # a note, like the others
    assert str(folder / "planted.json") in page.profiles_skipped.toolTip()  # where, for a fix
    assert page.tools_skipped.isHidden()  # nothing skipped there


def test_open_folder_waits_for_the_folder_while_the_profiles_are_built_in(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = ConnectionsPage(catalogs, None)
    assert not catalogs.profiles.folder.exists()  # the built-in profiles are shown
    assert not page.open_folder.isEnabled() and not page.builtin_note.isHidden()
    page.default.setCurrentIndex(page.default.findData("realvnc"))  # a change makes the folder
    assert page.open_folder.isEnabled() and page.builtin_note.isHidden()


def test_remote_desktop_says_it_asks_for_the_password_itself(catalogs: Catalogs) -> None:
    # "no password" read as if none were needed; Remote Desktop's own window asks for it.
    page = ConnectionsPage(catalogs, None)
    rows = range(page.list.topLevelItemCount())
    [rdp] = [i for r in rows if (i := page.list.topLevelItem(r)) and i.text(0) == "Remote Desktop"]
    assert rdp.text(2) == "asked by Remote Desktop Connection itself"
    assert "asks for the user and password itself" in rdp.toolTip(2)
    tools = [e.item for e in catalogs.tools.all()]
    dialog = ProfileDialog(None, "New", tools, {"rdp"})
    dialog.tool.setCurrentIndex(dialog.tool.findData("rdp"))
    assert dialog.login.currentText() == "Asked by Remote Desktop Connection itself"


def test_a_new_profile_is_written_at_once(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = ConnectionsPage(catalogs, None)
    told: list[bool] = []
    page.changed.connect(lambda: told.append(True))

    def fill(dialog: ProfileDialog) -> None:
        dialog.name.setText("Clinics (SecureVNC)")
        dialog.login.setCurrentIndex(dialog.login.findData("account"))
        dialog.option_boxes["securevnc"].setChecked(True)

    _answer(monkeypatch, fill)
    page.add()
    assert "Clinics (SecureVNC)" in _names(page) and told  # the main window hears of it
    assert catalogs.profiles.find("clinics-securevnc") == ConnectionProfile(
        "clinics-securevnc", "ultravnc", "account", ("securevnc",), name="Clinics (SecureVNC)"
    )


def test_saying_no_to_delete_keeps_the_profile(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = ConnectionsPage(catalogs, None)
    monkeypatch.setattr(connections, "confirm", lambda *_args: False)
    _select(page, "ultravnc")
    page.delete()
    assert "UltraVNC" in _names(page) and not catalogs.profiles.folder.exists()


def test_the_default_profile_is_written_at_once(catalogs: Catalogs) -> None:
    page = ConnectionsPage(catalogs, None)
    assert page.default_choice() == "ultravnc"
    page.default.setCurrentIndex(page.default.findData("realvnc"))
    assert catalogs.profiles.default_id() == "realvnc"


def test_tool_paths_chosen_here_are_written_at_once(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = ConnectionsPage(catalogs, None)
    assert _tool_row(page, "realvnc")[0] == "✗ Not found"
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


def test_a_settings_file_chosen_for_a_profile_is_cleaned_and_copied(
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
    profile = catalogs.profiles.find("view-only")
    assert profile is not None and profile.settings_file == "view-only.vnc"
    copied = catalogs.profiles.folder / "view-only.vnc"
    assert copied.read_bytes() == b"[connection]\r\nhost=\r\n[options]\r\nviewonly=1\r\n"

    # A duplicate gets its own copy; going back to defaults removes the file.
    _select(page, "view-only")
    _answer(monkeypatch, lambda dialog: dialog.name.setText("View only 2"))
    page.duplicate()
    _select(page, "view-only")
    _answer(monkeypatch, lambda dialog: dialog.default_settings.click())
    page.edit()
    assert not copied.exists()
    assert (catalogs.profiles.folder / "view-only-2.vnc").read_bytes() == (
        b"[connection]\r\nhost=\r\n[options]\r\nviewonly=1\r\n"
    )

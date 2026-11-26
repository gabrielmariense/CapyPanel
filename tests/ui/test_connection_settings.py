from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QPoint, QRect, Qt, QUrl
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QMenu,
    QMessageBox,
    QPushButton,
    QWidget,
)

from capypanel.core import i18n, settings, winsec
from capypanel.core.hosts.document import OpenList
from capypanel.core.hosts.model import HostList
from capypanel.core.tools import definitions
from capypanel.core.tools.catalog import Catalogs
from capypanel.core.tools.profile_store import ProfileStore
from capypanel.core.tools.profiles import ConnectionProfile
from capypanel.ui import dialogs
from capypanel.ui.dialogs import ScreenFit
from capypanel.ui.hosts_tool.tool import HostsTool
from capypanel.ui.settings import connections
from capypanel.ui.settings.connections import ProfileDialog, ProfilesSection, ToolsSection


@pytest.fixture
def catalogs(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Catalogs:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    found = {"ultravnc": Path(r"C:\Tools\vncviewer.exe")}
    monkeypatch.setattr(connections.detect, "find_executable", lambda t: found.get(t.id))
    return Catalogs.for_paths(settings.resolve_paths(tmp_path))


def _answer(monkeypatch: pytest.MonkeyPatch, fill: Callable[[ProfileDialog], None]) -> None:
    def run(dialog: ProfileDialog) -> int:
        fill(dialog)
        return 1

    monkeypatch.setattr(ProfileDialog, "exec", run)


def _select(page: ProfilesSection, profile_id: str) -> None:
    for row in range(page.list.topLevelItemCount()):
        item = page.list.topLevelItem(row)
        if item is not None and item.data(0, Qt.ItemDataRole.UserRole) == profile_id:
            page.list.setCurrentItem(item)
            item.setSelected(True)


def _names(page: ProfilesSection) -> list[str]:
    rows = range(page.list.topLevelItemCount())
    return [item.text(0) for row in rows if (item := page.list.topLevelItem(row))]


def _tool_row(page: ToolsSection, tool_id: str) -> tuple[str, str]:
    for row in range(page.tools.topLevelItemCount()):
        item = page.tools.topLevelItem(row)
        if item is not None and item.data(0, Qt.ItemDataRole.UserRole) == tool_id:
            return item.text(1), item.toolTip(1)
    raise AssertionError(tool_id)


def _menu(fill: Callable[[QMenu], None], *, enabled_only: bool = False) -> list[str]:
    menu = QMenu()
    fill(menu)
    return [a.text() for a in menu.actions() if a.text() and (a.isEnabled() or not enabled_only)]


def _trigger(fill: Callable[[QMenu], None], text: str) -> None:
    menu = QMenu()
    fill(menu)
    [action] = [a for a in menu.actions() if a.text() == text]
    action.trigger()


def test_the_editor_offers_only_what_the_chosen_tool_supports(catalogs: Catalogs) -> None:
    tools = [e.item for e in catalogs.tools.all()]
    dialog = ProfileDialog(None, "New", tools, {"ultravnc"})
    assert dialog.tool.currentData() == "ultravnc"
    assert list(dialog.option_boxes) == ["securevnc"]
    assert dialog.viewer_asks.isChecked() and dialog.capypanel_asks.isEnabled()
    assert dialog.viewer_asks.text() == "Typed in UltraVNC Viewer"
    assert dialog.capypanel_asks.text() == "Typed in CapyPanel"
    assert [dialog.login.itemText(i) for i in range(dialog.login.count())] == [
        "User and password", "Password only",
    ]  # fmt: skip
    assert not dialog.login.isEnabled()
    assert dialog.login.toolTip() == "UltraVNC Viewer asks for these when it connects."
    assert dialog.profile("new").login == "none"
    assert dialog.port.text() == "Default (5900)"
    realvnc = dialog.tool.findData("realvnc")
    assert dialog.tool.itemText(realvnc) == "RealVNC Viewer (not installed on this PC)"
    dialog.tool.setCurrentIndex(realvnc)
    assert dialog.option_boxes == {}
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    dialog.name.setText("Pis")
    assert ok.isEnabled()


def _shown(dialog: QWidget) -> None:
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    dialog.show()
    QApplication.processEvents()


def _places(dialog: QWidget, widgets: list[QWidget]) -> list[QRect]:
    return [QRect(w.mapTo(dialog, QPoint(0, 0)), w.size()) for w in widgets]


def test_each_tool_shows_only_its_own_rows_under_name_tool_and_port(
    qapp: QApplication, catalogs: Catalogs
) -> None:
    tools = [e.item for e in catalogs.tools.all()]
    names = {tool.id for tool in tools}
    fitter = ScreenFit(qapp)
    qapp.installEventFilter(fitter)
    dialog = ProfileDialog(None, "New", tools, names)
    vnc = ConnectionProfile("vnc", "ultravnc", name="VNC")
    editing = ProfileDialog(None, "Edit", tools, names, vnc)
    kept = replace(vnc, settings_file="vnc.vnc")
    with_file = ProfileDialog(None, "Edit", tools, names, kept)
    try:
        _shown(dialog)
        top: list[QWidget] = [dialog.name, dialog.tool, dialog.port]
        password: list[QWidget] = [dialog.viewer_asks, dialog.capypanel_asks, dialog.login]
        settings_row: list[QWidget] = [dialog.settings_state, dialog.default_settings]
        rows = {"ultravnc": (True, 1), "realvnc": (True, 0), "mstsc": (False, 3)}
        tops, heights = [], {}
        for tool, (asks, options) in rows.items():
            dialog.tool.setCurrentIndex(dialog.tool.findData(tool))
            QApplication.processEvents()
            assert [w.isVisible() for w in password] == [asks] * 3, tool
            assert not any(w.isVisible() for w in settings_row), tool
            shown = [box for box in dialog.findChildren(QCheckBox) if box.isVisible()]
            assert len(shown) == len(dialog.option_boxes) == options, tool
            assert dialog.height() == dialog.sizeHint().height(), tool
            tops.append(_places(dialog, top))
            heights[tool] = dialog.height()
        assert tops == [tops[0]] * len(tops)
        assert heights["realvnc"] < heights["ultravnc"]
        dialog.tool.setCurrentIndex(dialog.tool.findData("ultravnc"))
        QApplication.processEvents()
        before = _places(dialog, [*top, *password])
        dialog.resize(dialog.width(), dialog.height() + 60)
        QApplication.processEvents()
        assert _places(dialog, [*top, *password]) == before
        _shown(editing)
        assert editing.height() == heights["ultravnc"]
        _shown(with_file)
        assert all(w.isVisible() for w in (with_file.settings_state, with_file.default_settings))
        assert with_file.height() > heights["ultravnc"]
        assert _places(with_file, [with_file.name, with_file.tool, with_file.port]) == tops[0]
    finally:
        dialog.close()
        editing.close()
        with_file.close()
        qapp.removeEventFilter(fitter)


def test_the_list_under_capypanel_lines_up_with_the_other_fields(
    qapp: QApplication, catalogs: Catalogs
) -> None:
    tools = [e.item for e in catalogs.tools.all()]
    dialog = ProfileDialog(None, "New", tools, {tool.id for tool in tools})
    dialog.tool.setCurrentIndex(dialog.tool.findData("ultravnc"))
    try:
        _shown(dialog)
        name = QRect(dialog.name.mapTo(dialog, QPoint(0, 0)), dialog.name.size())
        login = QRect(dialog.login.mapTo(dialog, QPoint(0, 0)), dialog.login.size())
        assert (login.left(), login.right()) == (name.left(), name.right())
    finally:
        dialog.close()


def test_the_options_label_stays_on_the_first_option_s_line_beside_a_tall_tick_box(
    qapp: QApplication, catalogs: Catalogs
) -> None:
    tools = [e.item for e in catalogs.tools.all()]
    dialog = ProfileDialog(None, "New", tools, {tool.id for tool in tools})
    dialog.setStyleSheet("QCheckBox::indicator { height: 40px; }")  # past 7/4 of a text line
    try:
        dialog.tool.setCurrentIndex(dialog.tool.findData("mstsc"))
        _shown(dialog)
        form = dialog.findChild(QFormLayout)
        first = next(iter(dialog.option_boxes.values()))
        label = form.labelForField(first) if form else None
        assert label is not None
        assert first.mapTo(dialog, first.rect().center()).y() == label.geometry().center().y()
    finally:
        dialog.close()


def test_rows_a_tool_doesnt_use_are_left_out(catalogs: Catalogs) -> None:
    tools = [e.item for e in catalogs.tools.all()]
    dialog = ProfileDialog(None, "New", tools, {"ultravnc"})
    settings_row = (dialog.settings_state, dialog.default_settings)
    password = (dialog.asks_label, dialog.viewer_asks, dialog.capypanel_asks, dialog.login)
    assert all(w.isVisibleTo(dialog) for w in password)
    assert not any(w.isVisibleTo(dialog) for w in settings_row)
    dialog.tool.setCurrentIndex(dialog.tool.findData("realvnc"))
    assert all(w.isVisibleTo(dialog) for w in password) and dialog.option_boxes == {}
    assert not any(box.isVisibleTo(dialog) for box in dialog.findChildren(QCheckBox))
    dialog.tool.setCurrentIndex(dialog.tool.findData("mstsc"))
    assert not any(w.isVisibleTo(dialog) for w in password)
    assert dialog.viewer_asks.isChecked() and len(dialog.option_boxes) == 3
    assert dialog.profile("rdp").login == "none"
    dialog.tool.setCurrentIndex(dialog.tool.findData("ultravnc"))
    assert all(w.isVisibleTo(dialog) for w in password)


def test_a_tool_that_takes_only_a_password_says_so(qapp: QApplication) -> None:
    only = definitions.from_data(
        {
            "schema": 1, "id": "plainvnc", "name": "Plain VNC", "kind": "vnc", "port": 5900,
            "credentials": "vnc_password_file",
            "arguments": [["{address}::{port}"], ["-passwordfile", "{password_file}"]],
        }
    )  # fmt: skip
    dialog = ProfileDialog(None, "New", [only], {"plainvnc"})
    dialog.capypanel_asks.click()
    assert [dialog.login.itemText(i) for i in range(dialog.login.count())] == ["Password only"]
    assert not dialog.login.isEnabled()
    assert dialog.login.toolTip() == "Plain VNC only takes a password."


def test_only_a_profile_that_already_has_a_settings_file_shows_it(catalogs: Catalogs) -> None:
    tools = [e.item for e in catalogs.tools.all()]
    kept = ConnectionProfile("clinic", "ultravnc", name="Clinic", settings_file="clinic-x.vnc")
    new = ProfileDialog(None, "New", tools, {"ultravnc"})
    assert "C&hoose file…" not in [b.text() for b in new.findChildren(QPushButton)]
    assert new.profile("new").settings_file == ""
    assert (
        ProfileDialog(None, "Copy", tools, {"ultravnc"}, kept, new=True)
        .profile("clinic-2")
        .settings_file
        == "clinic-2.vnc"
    )
    dialog = ProfileDialog(None, "Edit", tools, {"ultravnc"}, kept)
    settings_row = (dialog.settings_state, dialog.default_settings)
    assert all(w.isVisibleTo(dialog) for w in settings_row)
    assert dialog.settings_state.text() == "Its own settings file"
    assert dialog.profile("clinic").settings_file == "clinic-x.vnc"
    dialog.default_settings.click()
    assert dialog.settings_state.text() == "The viewer's defaults"
    assert not dialog.default_settings.isEnabled()
    assert dialog.default_settings.toolTip() == "This profile already uses the viewer's defaults."
    assert all(w.isVisibleTo(dialog) for w in settings_row)
    assert dialog.profile("clinic").settings_file == ""


def test_picking_capypanel_for_a_new_ultravnc_profile_warns_once(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[QMessageBox] = []
    monkeypatch.setattr(dialogs, "run_modal", lambda box: shown.append(box) or 0)
    tools = [e.item for e in catalogs.tools.all()]
    dialog = ProfileDialog(None, "New", tools, {"ultravnc"})
    dialog.capypanel_asks.click()
    [box] = shown
    assert box.windowTitle() == "Security tools may log this password"
    assert box.text() == (
        "CapyPanel passes it to UltraVNC Viewer on the command line, where security tools and "
        "this PC's admins can see it."
    )
    keep = box.defaultButton()
    assert keep is not None and keep.text() == "Let UltraVNC Viewer ask"
    assert box.escapeButton() is keep and keep.objectName() != "quietDefault"
    assert dialog.viewer_asks.isChecked()
    dialog.capypanel_asks.click()
    assert len(shown) == 1 and dialog.capypanel_asks.isChecked() and dialog.login.isEnabled()
    assert dialog.profile("new").login == "account"


def test_a_new_profile_moved_to_ultravnc_with_capypanel_picked_warns_then(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[QMessageBox] = []
    monkeypatch.setattr(dialogs, "run_modal", lambda box: shown.append(box) or 0)
    tools = [e.item for e in catalogs.tools.all()]
    dialog = ProfileDialog(None, "New", tools, {"ultravnc"})
    dialog.tool.setCurrentIndex(dialog.tool.findData("realvnc"))
    dialog.capypanel_asks.click()
    assert not shown and dialog.capypanel_asks.isChecked()
    dialog.tool.setCurrentIndex(dialog.tool.findData("ultravnc"))
    assert len(shown) == 1 and dialog.viewer_asks.isChecked()


def test_use_capypanel_in_the_warning_keeps_capypanel(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    def use(box: QMessageBox) -> int:
        [button] = [b for b in box.buttons() if b.text() == "Use CapyPanel anyway"]
        button.click()
        return 0

    monkeypatch.setattr(dialogs, "run_modal", use)
    tools = [e.item for e in catalogs.tools.all()]
    dialog = ProfileDialog(None, "New", tools, {"ultravnc"})
    dialog.capypanel_asks.click()
    dialog.login.setCurrentIndex(dialog.login.findData("password"))
    assert dialog.profile("new").login == "password"


def test_an_existing_profile_switched_from_the_viewer_s_window_warns_once(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[QMessageBox] = []
    monkeypatch.setattr(dialogs, "run_modal", lambda box: shown.append(box) or 0)
    tools = [e.item for e in catalogs.tools.all()]
    vnc = ConnectionProfile("vnc", "ultravnc", login="none", name="VNC")
    editing = ProfileDialog(None, "Edit", tools, {"ultravnc"}, vnc)
    assert editing.viewer_asks.isChecked()
    editing.capypanel_asks.click()
    assert len(shown) == 1 and editing.viewer_asks.isChecked()
    editing.capypanel_asks.click()
    assert len(shown) == 1 and editing.profile("vnc").login == "account"


def test_an_existing_realvnc_profile_moved_to_ultravnc_warns(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[QMessageBox] = []
    monkeypatch.setattr(dialogs, "run_modal", lambda box: shown.append(box) or 0)
    tools = [e.item for e in catalogs.tools.all()]
    real = ConnectionProfile("real", "realvnc", login="account", name="Real")
    editing = ProfileDialog(None, "Edit", tools, {"ultravnc"}, real)
    assert editing.capypanel_asks.isChecked() and not shown
    editing.tool.setCurrentIndex(editing.tool.findData("ultravnc"))
    assert len(shown) == 1 and editing.viewer_asks.isChecked()


def test_a_profile_already_passing_the_password_and_one_kept_off_the_command_line_never_warn(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    def never(_box: QMessageBox) -> int:
        raise AssertionError("no warning here")

    monkeypatch.setattr(dialogs, "run_modal", never)
    tools = [e.item for e in catalogs.tools.all()]
    vnc = ConnectionProfile("vnc", "ultravnc", login="account", name="VNC")
    editing = ProfileDialog(None, "Edit", tools, {"ultravnc"}, vnc)
    editing.viewer_asks.click()
    editing.capypanel_asks.click()
    editing.tool.setCurrentIndex(editing.tool.findData("realvnc"))
    editing.tool.setCurrentIndex(editing.tool.findData("ultravnc"))
    assert editing.profile("vnc").login == "account"
    realvnc = ProfileDialog(None, "New", tools, {"ultravnc"})
    realvnc.tool.setCurrentIndex(realvnc.tool.findData("realvnc"))
    realvnc.capypanel_asks.click()
    assert realvnc.profile("r").login == "account" and realvnc.login.isEnabled()


def test_a_duplicate_is_a_new_profile_and_warns_too(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[QMessageBox] = []
    monkeypatch.setattr(dialogs, "run_modal", lambda box: shown.append(box) or 0)
    page = ProfilesSection(catalogs, None)
    _answer(monkeypatch, lambda dialog: dialog.capypanel_asks.click())
    _select(page, "ultravnc")
    page.duplicate()
    assert len(shown) == 1
    [copy] = [p for p in catalogs.profiles.all() if p.name == "UltraVNC (copy)"]
    assert copy.login == "none"


def test_starter_profiles_can_be_duplicated_edited_and_deleted(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = ProfilesSection(catalogs, None)
    _select(page, "ultravnc")
    assert page.edit_button.isEnabled() and page.delete_button.isEnabled()
    assert _menu(page.fill_row_menu) == ["&Edit…", "D&uplicate…", "&Delete…"]
    _answer(monkeypatch, lambda dialog: None)
    _trigger(page.fill_row_menu, "D&uplicate…")
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
    page = ProfilesSection(catalogs, document)
    asked: list[str] = []
    monkeypatch.setattr(
        connections, "confirm", lambda _parent, _title, text, _action: asked.append(text) or False
    )
    _select(page, "pis")
    page.delete()
    assert "2 hosts and 1 group" in asked[0]
    assert "Pis" in _names(page)
    monkeypatch.setattr(connections, "confirm", lambda *_args: True)
    page.delete()
    assert catalogs.profiles.find("pis") is None


def test_a_folder_the_user_cannot_write_is_read_only(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(catalogs.profiles, "can_edit", lambda: False)
    page = ProfilesSection(catalogs, None)
    _select(page, "ultravnc")
    buttons = (page.add_button, page.edit_button, page.delete_button)
    assert not any(b.isEnabled() for b in buttons) and not page.default.isEnabled()
    assert not any(_menu(page.fill_row_menu, enabled_only=True))


def test_with_a_settings_file_the_file_decides_not_the_options(catalogs: Catalogs) -> None:
    tools = [e.item for e in catalogs.tools.all()]
    kept = ConnectionProfile(
        "secure", "ultravnc", options=("securevnc",), name="Secure", settings_file="secure.vnc"
    )
    dialog = ProfileDialog(None, "Edit", tools, {"ultravnc"}, kept)
    box = dialog.option_boxes["securevnc"]
    assert not box.isEnabled() and not box.isChecked()
    assert dialog.profile("secure").options == ()
    dialog.default_settings.click()
    assert dialog.option_boxes["securevnc"].isEnabled()


def test_remote_tools_show_a_state_and_only_the_actions_that_fit(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = ToolsSection(catalogs)
    assert _tool_row(page, "ultravnc") == ("✓ Found", r"C:\Tools\vncviewer.exe")
    page.select_tool("ultravnc")
    assert page.tool_actions("ultravnc") == ["locate"]
    assert page.locate_button.isEnabled() and not page.download_button.isEnabled()
    assert _menu(page.fill_row_menu) == ["Change path…"]
    assert _tool_row(page, "realvnc")[0] == "✗ Not found"
    page.select_tool("realvnc")
    assert page.tool_actions("realvnc") == ["locate", "download"]
    assert page.locate_button.text() == "Change path…"
    assert page.download_button.isEnabled()
    assert _menu(page.fill_row_menu) == ["Change path…", "Download"]
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
    assert _menu(page.fill_row_menu) == ["Change path…", "Use the &automatic path"]
    entry = catalogs.tools.find("realvnc")
    assert entry is not None and entry.item.executable == r"D:\Apps\vncviewer.exe"
    _trigger(page.fill_row_menu, "Use the &automatic path")
    entry = catalogs.tools.find("realvnc")
    assert entry is not None and not entry.item.executable


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
    page = ProfilesSection(catalogs, None)
    assert not page.profiles_skipped.isHidden()
    assert page.profiles_skipped.text() == (
        "2 files skipped: broken.json (can't be read), planted.json (made by another user)"
    )
    assert str(folder / "planted.json") in page.profiles_skipped.toolTip()
    assert ToolsSection(catalogs).tools_skipped.isHidden()


def test_remote_desktop_says_it_asks_for_the_password_itself(catalogs: Catalogs) -> None:
    page = ProfilesSection(catalogs, None)
    rows = range(page.list.topLevelItemCount())
    header = page.list.headerItem()
    assert header is not None and header.text(2) == "Password typed in"
    shown = {i.text(0): i.text(2) for r in rows if (i := page.list.topLevelItem(r))}
    assert shown["Remote Desktop"] == "Remote Desktop Connection"
    assert shown["UltraVNC"] == "UltraVNC Viewer"
    tools = [e.item for e in catalogs.tools.all()]
    dialog = ProfileDialog(None, "New", tools, {"mstsc"})
    dialog.tool.setCurrentIndex(dialog.tool.findData("mstsc"))
    assert not dialog.viewer_asks.isVisibleTo(dialog)
    assert dialog.profile("rdp").login == "none"


def test_a_new_profile_is_written_at_once(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = ProfilesSection(catalogs, None)
    told: list[bool] = []
    page.changed.connect(lambda: told.append(True))

    def fill(dialog: ProfileDialog) -> None:
        dialog.name.setText("Clinics (SecureVNC)")
        dialog.capypanel_asks.setChecked(True)
        dialog.login.setCurrentIndex(dialog.login.findData("account"))
        dialog.option_boxes["securevnc"].setChecked(True)

    _answer(monkeypatch, fill)
    page.add()
    assert "Clinics (SecureVNC)" in _names(page) and told
    assert catalogs.profiles.find("clinics-securevnc") == ConnectionProfile(
        "clinics-securevnc", "ultravnc", "account", ("securevnc",), name="Clinics (SecureVNC)"
    )


def test_saying_no_to_delete_keeps_the_profile(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = ProfilesSection(catalogs, None)
    monkeypatch.setattr(connections, "confirm", lambda *_args: False)
    _select(page, "ultravnc")
    page.delete()
    assert "UltraVNC" in _names(page) and not catalogs.profiles.folder.exists()


def test_the_default_profile_is_written_at_once(catalogs: Catalogs) -> None:
    page = ProfilesSection(catalogs, None)
    assert page.default_choice() == "ultravnc"
    page.default.setCurrentIndex(page.default.findData("realvnc"))
    assert catalogs.profiles.default_id() == "realvnc"


def test_tool_paths_chosen_here_are_written_at_once(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = ToolsSection(catalogs)
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


def test_a_profile_s_settings_file_is_kept_copied_without_a_password_and_dropped(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = catalogs.profiles.folder
    saved = b"[connection]\r\nhost=\r\npassword=a1b2c3d4e5f60718\r\n[options]\r\nviewonly=1\r\n"
    emptied = b"[connection]\r\nhost=\r\npassword=\r\n[options]\r\nviewonly=1\r\n"
    view = ConnectionProfile("view-only", "ultravnc", name="View only", settings_file="v.vnc")
    catalogs.profiles.save(view, emptied)
    (folder / "v.vnc").write_bytes(saved)
    page = ProfilesSection(catalogs, None)

    _select(page, "view-only")
    _answer(monkeypatch, lambda dialog: dialog.name.setText("View only, renamed"))
    page.edit()
    edited = catalogs.profiles.find("view-only")
    assert edited is not None and edited.name == "View only, renamed"
    assert edited.settings_file == "v.vnc" and (folder / "v.vnc").read_bytes() == saved

    _select(page, "view-only")
    _answer(monkeypatch, lambda dialog: dialog.name.setText("View only 2"))
    page.duplicate()
    assert (folder / "view-only-2.vnc").read_bytes() == emptied

    _select(page, "view-only")
    _answer(monkeypatch, lambda dialog: dialog.default_settings.click())
    page.edit()
    dropped = catalogs.profiles.find("view-only")
    assert dropped is not None and dropped.settings_file == ""
    assert not (folder / "v.vnc").exists()


def test_at_start_a_password_saved_in_a_settings_file_is_emptied(tmp_path: Path) -> None:
    (tmp_path / settings.PORTABLE_MARKER).touch()
    paths = settings.resolve_paths(tmp_path)
    clinic = ConnectionProfile("clinic", "ultravnc", name="Clinic", settings_file="clinic.vnc")
    ProfileStore(paths.profiles_dir).save(clinic, b"[options]\r\nviewonly=1\r\n")
    path = paths.profiles_dir / "clinic.vnc"
    path.write_bytes(b"[connection]\r\npassword=a1b2c3d4e5f60718\r\n")
    HostsTool.prepare(paths)
    assert path.read_bytes() == b"[connection]\r\npassword=\r\n"


def test_the_built_in_note_shows_until_a_profile_changes(catalogs: Catalogs) -> None:
    page = ProfilesSection(catalogs, None)
    assert not catalogs.profiles.folder.exists()
    assert not page.builtin_note.isHidden()
    page.default.setCurrentIndex(page.default.findData("realvnc"))
    assert page.builtin_note.isHidden()


def test_a_double_click_on_a_tool_changes_its_path(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    page = ToolsSection(catalogs)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *_a, **_k: (r"D:\Portable\vncviewer.exe", "")
    )
    page.select_tool("realvnc")
    page.tools.itemDoubleClicked.emit(page.tools.currentItem(), 0)
    entry = catalogs.tools.find("realvnc")
    assert entry is not None and entry.item.executable == r"D:\Portable\vncviewer.exe"


def test_restore_built_in_brings_back_deleted_profiles_after_asking(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalogs.profiles.place_starters()
    page = ProfilesSection(catalogs, None)
    assert page.restore_button.text() == "&Restore built-in…"
    assert not page.restore_button.isEnabled()
    monkeypatch.setattr(connections, "confirm", lambda *_args: True)
    for starter in ("realvnc", "remote-desktop"):
        _select(page, starter)
        page.delete()
    assert page.restore_button.isEnabled()
    asked: list[tuple[str, str]] = []

    def answer(_parent: object, title: str, text: str, _action: str) -> bool:
        asked.append((title, text))
        return len(asked) > 1

    monkeypatch.setattr(connections, "confirm", answer)
    page.restore_button.click()
    assert asked[0] == (
        "Restore built-in profiles",
        "Bring back 2 built-in profiles: RealVNC, Remote Desktop?\n\n"
        "Profiles you changed or made yourself stay as they are.",
    )
    assert _names(page) == ["UltraVNC"]
    page.restore_button.click()
    assert _names(page) == ["RealVNC", "Remote Desktop", "UltraVNC"]
    assert not page.restore_button.isEnabled()


def test_how_pcs_are_read_is_one_line_set_for_everyone_with_the_way_in_use(
    catalogs: Catalogs, monkeypatch: pytest.MonkeyPatch
) -> None:
    from capypanel.core.remote import inventory, wmi

    monkeypatch.setattr(inventory, "transport", inventory.AUTO)
    monkeypatch.setattr(wmi, "available", lambda: True)
    page = ToolsSection(catalogs)
    assert page.reads_label.text() == "Read PC data with:"
    texts = [page.reads.itemText(i) for i in range(page.reads.count())]
    assert texts == ["Automatic (recommended)", "WMI directly", "WMI through PowerShell"]
    assert page.reads.currentData() == "auto" and page.reads_note.text() == "in use: WMI directly"
    page.reads.setCurrentIndex(page.reads.findData("powershell"))
    page.reads.activated.emit(page.reads.currentIndex())
    assert inventory.transport == inventory.POWERSHELL and catalogs.tools.reads() == "powershell"
    assert page.reads_note.text() == ""
    assert ToolsSection(catalogs).reads.currentData() == "powershell"

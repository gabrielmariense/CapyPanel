"""Themes: the native Windows look, the CapyPanel look, and extra looks shipped as data files.

Only shipped themes exist; users can't add their own. A theme changes only the look.

Two engines:
- native: Qt's windows11 style. Follows Windows (accent colour); only dark/light is picked.
- custom: Fusion + a palette + a stylesheet generated from colour tokens (QSS has no variables).

Shipped theme files (this folder, *.json) override some tokens of a base:
    {"name": "Graphite", "base": "dark", "colors": {"accent": "#14b8a6"},
     "font": {"family": "Georgia", "size": 10.5}, "radius": 6}
"""

import ctypes
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from capypanel.core.i18n import N_, _

log = logging.getLogger(__name__)

THEMES_DIR = Path(__file__).resolve().parent
DEFAULT_FONT: tuple[tuple[str, ...], float] = (("Segoe UI Variable Text", "Segoe UI"), 10.0)
TOKENS = {
    "dark": {
        "bg": "#0b0f17", "card": "#1d273d", "raised": "#232e46", "border": "#465c88",
        "chrome": "#1d2638", "text": "#e7eaf1", "text2": "#aab2c3", "text3": "#8590a1",
        "hover": "#1494a3b8", "sel_solid": "#28406d",
        "accent": "#3b82f6", "accent_hover": "#5b95f7", "danger": "#f87171",
    },
    "light": {
        "bg": "#d9dfe9", "card": "#ffffff", "raised": "#f1f4f9", "border": "#a1afc6",
        "chrome": "#c5cedc", "text": "#111827", "text2": "#4b5563", "text3": "#4d5765",
        "hover": "#0d0f172a", "sel_solid": "#cfdcf7",
        "accent": "#2563eb", "accent_hover": "#3b76ee", "danger": "#dc2626",
    },
}  # fmt: skip
# Native themes keep Windows' own widgets; this light layer only adds visible structure
# (window background, pane borders, header/footer bars), following the resolved dark/light.
NATIVE_TOKENS = {
    "light": {"bg": "#e3e3e3", "card": "#ffffff", "chrome": "#d0d0d0", "border": "#aeaeae",
              "text": "#000000", "text2": "#404040"},
    "dark": {"bg": "#1b1b1b", "card": "#2d2d2d", "chrome": "#292929", "border": "#616161",
             "text": "#ffffff", "text2": "#c8c8c8"},
}  # fmt: skip


@dataclass(frozen=True)
class Theme:
    id: str
    engine: str  # "native" or "custom"
    scheme: str  # "system", "dark" or "light"
    label: str = ""  # translatable name of a built-in theme
    name: str = ""  # literal name from a theme file
    colors: dict[str, str] = field(default_factory=dict)
    font: tuple[tuple[str, ...], float] = DEFAULT_FONT
    radius: int = 8

    def title(self) -> str:
        return _(self.label) if self.label else self.name


BUILTIN = (
    Theme("windows-system", "native", "system", N_("Windows — follow system theme")),
    Theme("windows-dark", "native", "dark", N_("Windows — dark")),
    Theme("windows-light", "native", "light", N_("Windows — light")),
    Theme("capypanel-dark", "custom", "dark", N_("CapyPanel — dark"), colors=TOKENS["dark"]),
    Theme("capypanel-light", "custom", "light", N_("CapyPanel — light"), colors=TOKENS["light"]),
)
DEFAULT_THEME = BUILTIN[0]


def load_theme_file(path: Path) -> Theme:
    """Parse and check one shipped theme file; raises ValueError with the reason."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"not valid JSON ({e})") from None
    if not isinstance(data, dict):
        raise ValueError("not an object")
    name, base = data.get("name"), data.get("base")
    if not isinstance(name, str) or not name.strip():
        raise ValueError('"name" is missing')
    if base not in TOKENS:
        raise ValueError('"base" must be "dark" or "light"')
    colors = dict(TOKENS[base])
    for key, value in (data.get("colors") or {}).items():
        if key not in colors:
            raise ValueError(f'unknown colour "{key}"')
        if not isinstance(value, str) or not QColor.isValidColorName(value):
            raise ValueError(f'"{key}": "{value}" is not a colour')
        colors[key] = value
    font = DEFAULT_FONT
    if "font" in data:
        family, size = data["font"].get("family"), data["font"].get("size", DEFAULT_FONT[1])
        if not isinstance(family, str) or not isinstance(size, int | float) or not 6 <= size <= 20:
            raise ValueError('"font" needs a family and a size between 6 and 20')
        font = ((family, *DEFAULT_FONT[0]), float(size))
    radius = data.get("radius", 8)
    if not isinstance(radius, int) or not 0 <= radius <= 20:
        raise ValueError('"radius" must be a whole number from 0 to 20')
    return Theme(
        path.stem, "custom", base, name=name.strip(), colors=colors, font=font, radius=radius
    )


class Registry:
    """Every theme the app ships: the built-in ones plus the files in this folder."""

    def __init__(self, folder: Path = THEMES_DIR) -> None:
        self.shipped: list[Theme] = []
        for path in sorted(folder.glob("*.json")):
            try:
                self.shipped.append(load_theme_file(path))
            except ValueError as e:  # a broken shipped file is our bug: log it, skip it
                log.error("Theme %s not loaded: %s", path.name, e)

    def all(self) -> list[Theme]:
        return [*BUILTIN, *self.shipped]

    def find(self, theme_id: object) -> Theme:
        return next((t for t in self.all() if t.id == theme_id), DEFAULT_THEME)


# ---- applying ----

_current: Theme = DEFAULT_THEME
_applied_once = False
_watching_system = False
_native_font: QFont | None = None


def current() -> Theme:
    return _current


def apply(theme: Theme) -> None:
    """Switches the whole app's look, live. The comments mark workarounds found in the UI spike."""
    global _current, _applied_once, _native_font
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return
    if _native_font is None:
        _native_font = QFont(app.font())
    scheme = {
        "system": Qt.ColorScheme.Unknown,
        "dark": Qt.ColorScheme.Dark,
        "light": Qt.ColorScheme.Light,
    }[theme.scheme]
    # Compare with the engine applied last, not app.style(): with a stylesheet set, app.style()
    # is Qt's stylesheet wrapper, whose name is empty, so it never reads as "fusion".
    engine_changed = theme.engine != _current.engine or not _applied_once
    _current, _applied_once = theme, True
    _follow_system_changes()
    if theme.engine == "native":
        # Windows' default app font is 9 pt; use the same size as the custom themes.
        readable = QFont(_native_font)
        readable.setPointSizeF(max(DEFAULT_FONT[1], _native_font.pointSizeF()))
        app.setStyleSheet("")
        app.setFont(readable)
        QGuiApplication.styleHints().setColorScheme(scheme)
        app.setPalette(QPalette())  # an empty palette makes Qt resolve the system one again
        # A fresh style instance re-polishes every widget; switching the scheme alone left some
        # views with the previous theme's colours.
        app.setStyle("windows11")
        app.setStyleSheet(
            _NATIVE_QSS % native_tokens(app.palette().color(QPalette.ColorRole.Accent))
        )  # noqa: UP031
        _refont(app, readable.families())
    else:
        if engine_changed:
            app.setFont(_native_font)
            # The stylesheet goes first, so widgets remember the native font to go back to.
            app.setStyleSheet(stylesheet(theme))
            app.setStyle("Fusion")
        font = QFont()
        font.setFamilies(list(theme.font[0]))
        font.setPointSizeF(theme.font[1])
        # Lining digits: in fonts like Georgia, old-style digits make "PC01" read as "PCo1".
        font.setFeature(QFont.Tag("lnum"), 1)
        app.setFont(font)
        QGuiApplication.styleHints().setColorScheme(scheme)
        app.setPalette(_palette(theme.colors))
        app.setStyleSheet(stylesheet(theme))
        _refont(app, font.families())
    for widget in app.topLevelWidgets():
        if widget.isWindow() and widget.isVisible():
            paint_title_bar(widget)


def native_tokens(accent: QColor) -> dict[str, str]:
    """The structure layer's colours for the resolved dark/light, plus selection and hover."""
    tokens = dict(NATIVE_TOKENS[native_scheme()])
    tokens["sel"] = selection_tint(accent, tokens["card"], tokens["text"])
    tokens["hover"] = _mix(QColor(tokens["text"]), QColor(tokens["card"]), 0.06)
    tokens["accent"] = accent.name()
    tokens["arrow"] = (THEMES_DIR / f"arrow-{native_scheme()}.svg").as_posix()
    return tokens


def selection_tint(accent: QColor, card: str, text: str) -> str:
    """The lightest tint of the user's accent colour that stands out from the pane (1.35:1)
    while keeping text readable on it (4.5:1). Any accent works, from yellow to purple."""
    for step in range(10, 70, 2):
        tint = _mix(accent, QColor(card), step / 100)
        if contrast_ratio(tint, card) >= 1.35 and contrast_ratio(text, tint) >= 4.5:
            return tint
    return _mix(QColor(text), QColor(card), 0.18)  # an accent too close to text: plain grey


def _mix(color: QColor, base: QColor, amount: float) -> str:
    """`amount` of `color` laid over `base`."""
    channels = (
        round(base.redF() * 255 + (color.redF() - base.redF()) * 255 * amount),
        round(base.greenF() * 255 + (color.greenF() - base.greenF()) * 255 * amount),
        round(base.blueF() * 255 + (color.blueF() - base.blueF()) * 255 * amount),
    )
    return QColor(*channels).name()


def native_scheme() -> str:
    """The dark/light the native theme resolves to ("follow system" asks Windows)."""
    if _current.scheme != "system":
        return _current.scheme
    dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    return "dark" if dark else "light"


def _follow_system_changes() -> None:
    # When Windows switches dark/light, "follow system" re-applies itself with the new scheme.
    global _watching_system
    if not _watching_system:
        _watching_system = True
        QGuiApplication.styleHints().colorSchemeChanged.connect(_system_scheme_changed)


def _system_scheme_changed() -> None:
    if _current.scheme == "system":
        apply(_current)


def _refont(app: QApplication, families: list[str]) -> None:
    """Widgets given an explicit font (a bold heading) keep their old family; move them over."""
    for widget in app.allWidgets():
        if widget.testAttribute(Qt.WidgetAttribute.WA_SetFont):
            font = QFont(widget.font())
            font.setFamilies(families)
            widget.setFont(font)


def paint_title_bar(window: QWidget) -> None:
    """Custom themes colour the title bar like their background (Windows 11; ignored on 10)."""
    if QGuiApplication.platformName() != "windows":
        return
    if _current.engine == "custom":
        color = QColor(_current.colors["bg"])
        value = color.blue() << 16 | color.green() << 8 | color.red()
    else:
        value = 0xFFFFFFFF  # DWMWA_COLOR_DEFAULT: the system's own title bar
    colorref = ctypes.c_uint32(value)
    dwmapi = ctypes.WinDLL("dwmapi")
    dwmapi.DwmSetWindowAttribute(int(window.winId()), 35, ctypes.byref(colorref), 4)


def _palette(t: dict[str, str]) -> QPalette:
    palette = QPalette()
    role = QPalette.ColorRole
    for color_role, key in (
        (role.Window, "bg"),
        (role.WindowText, "text"),
        (role.Base, "card"),
        (role.AlternateBase, "raised"),
        (role.Text, "text"),
        (role.Button, "card"),
        (role.ButtonText, "text"),
        (role.Highlight, "accent"),
        (role.Accent, "accent"),
        (role.Link, "accent"),
        (role.PlaceholderText, "text3"),
        (role.Mid, "border"),
        (role.ToolTipBase, "card"),
        (role.ToolTipText, "text"),
    ):
        palette.setColor(color_role, QColor(t[key]))
    palette.setColor(role.HighlightedText, QColor("#ffffff"))
    for color_role in (role.ButtonText, role.WindowText, role.Text):
        palette.setColor(QPalette.ColorGroup.Disabled, color_role, QColor(t["text3"]))
    return palette


# Tree rows use padding, never a fixed "height:": a stylesheet height draws rows taller than
# the view spaces them, which made rows overlap in the spike's settings window.
_QSS = """
QMainWindow, QDialog { background: %(bg)s; }
QMenuBar { background: %(chrome)s; border-bottom: 1px solid %(border)s; padding: 4px 8px 2px 8px; }
QMenuBar::item { padding: 4px 10px; border-radius: 6px; color: %(text2)s; background: transparent; }
QMenuBar::item:selected { background: %(hover)s; color: %(text)s; }
QMenu { background: %(card)s; border: 1px solid %(border)s; border-radius: %(r)spx; padding: 5px; }
QMenu::item { padding: 6px 28px 6px 30px; border-radius: 6px; }
QMenu::item:selected { background: %(hover)s; }
QMenu::item:disabled { color: %(text3)s; }
QMenu::separator { height: 1px; background: %(border)s; margin: 5px 6px; }
QMenu::indicator { left: 9px; }

QToolButton { padding: 2px 8px; border-radius: %(r2)spx; color: %(text2)s; background: transparent;
              border: none; }
QToolButton:hover { background: %(hover)s; color: %(text)s; }
/* A line under the toolbar, like the menu bar's: without it, it merges into the panes below. */
QToolBar { background: %(bg)s; border: none; border-bottom: 1px solid %(border)s;
           padding: 6px 8px 4px 8px; spacing: 6px; }
/* Toolbar buttons are outlined (design T1); thin lines divide the groups. */
QToolBar QToolButton { padding: 6px 10px; border: 1px solid %(border)s; background: %(raised)s;
                       color: %(text)s; }
QToolBar QToolButton:hover { background: %(hover)s; }
QToolBar QToolButton:disabled { color: %(text3)s; }
QFrame#toolDivider { background: %(border)s; border: none; }
/* Styling a tool button drops Fusion's menu arrow, so draw our own. */
QToolBar QToolButton[popupMode="1"] { padding-right: 24px; }
QToolBar QToolButton[popupMode="2"] { padding-right: 24px; }
/* The arrow of a split button (Connect) is a part of its own: a divider and its own hover. */
QToolButton::menu-button { border: none; border-left: 1px solid %(border)s; width: 18px;
                           margin: 5px 0; border-top-right-radius: %(r2)spx;
                           border-bottom-right-radius: %(r2)spx; }
QToolButton::menu-button:hover { background: %(hover)s; }
QToolButton::menu-arrow, QToolButton::menu-indicator {
    image: url("%(arrow)s"); width: 10px; height: 6px; }
QToolButton::menu-indicator { subcontrol-position: right center; right: 8px; }
/* Headings inside menus and the Refresh panel. */
QLabel#menuSection { color: %(text3)s; padding: 6px 12px 2px 12px; font-weight: 600; }

QLineEdit, QPlainTextEdit, QSpinBox { background: %(card)s; border: 1px solid %(border)s;
                            border-radius: %(r2)spx; padding: 5px 7px;
                            selection-background-color: %(accent)s; }
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus { border: 1px solid %(accent)s; }
QLineEdit:disabled { color: %(text3)s; background: %(raised)s; }
/* The tag field: a box like a text input, holding chips and a borderless text box. */
QFrame#tagEdit { background: %(card)s; border: 1px solid %(border)s; border-radius: %(r2)spx; }
QFrame#tagEdit[focused="true"] { border-color: %(accent)s; }
QLineEdit#tagInput, QLineEdit#tagInput:focus {
    border: none; background: transparent; padding: 3px 2px; }
QFrame#tagChip { background: %(sel_solid)s; border: none; border-radius: 9px; }
QToolButton#tagChipRemove {
    border: none; background: transparent; padding: 0 3px; color: %(text)s; }
QToolButton#tagChipRemove:hover { background: %(hover)s; }
QComboBox { background: %(card)s; border: 1px solid %(border)s; border-radius: %(r2)spx;
            padding: 4px 10px; min-height: 22px; }
QComboBox:hover { border-color: %(text3)s; }
QComboBox::drop-down { border: none; width: 24px; }
/* Styling the drop-down button removes Fusion's arrow, so draw our own. */
QComboBox::down-arrow { image: url("%(arrow)s"); width: 10px; height: 6px; }
QComboBox QAbstractItemView { background: %(card)s; border: 1px solid %(border)s; outline: 0;
                              selection-background-color: %(sel_solid)s;
                              selection-color: %(text)s; }

QTreeView, QListView { background: %(card)s; border: 1px solid %(border)s; border-radius: %(r)spx;
                       outline: 0; alternate-background-color: %(card)s; padding: 4px; }
QTreeView::item, QListView::item { padding: 5px 4px; border: none; }
QTreeView::item:hover, QListView::item:hover { background: %(hover)s; }
QTreeView::item:selected, QListView::item:selected { background: %(sel_solid)s; color: %(text)s; }
QHeaderView { background: %(card)s; border: none; }
QHeaderView::section { background: %(card)s; color: %(text2)s; border: none;
                       border-bottom: 1px solid %(border)s; padding: 8px 6px; font-weight: 600; }
/* Tables marked "grid" get lines between rows and columns, like a spreadsheet. */
QTreeView#grid::item { border-right: 2px solid %(border)s; border-bottom: 2px solid %(border)s; }
QTreeView#grid QHeaderView::section { border-right: 2px solid %(border)s; }
/* No line after the last column, as there's none before the first. */
QTreeView#grid::item:last, QTreeView#grid::item:only-one,
QTreeView#grid QHeaderView::section:last,
QTreeView#grid QHeaderView::section:only-one { border-right: none; }
QHeaderView::section:hover { color: %(text)s; }

QFrame#card { background: %(card)s; border: 1px solid %(border)s; border-radius: %(r)spx; }
/* Lists inside a card (the groups pane): the card is their only frame. */
QTreeView#flat { border: none; background: transparent; padding: 0 2px; }
/* The search box above the host table: a small pane, with the panes' corners. */
QLineEdit#paneSearch { border-radius: %(r)spx; padding: 6px 8px; }
QFrame#divider { background: %(border)s; border: none; }
QLabel#paneTitle, QLabel#hint { color: %(text2)s; }
QListView#pageList::item { padding: 7px 10px; }

/* Fusion outlines these with a darker shade of the background, invisible in dark themes. */
QRadioButton::indicator, QCheckBox::indicator {
    width: 14px; height: 14px; border: 1px solid %(border)s; background: %(card)s; }
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator { border-radius: 3px; }
QRadioButton::indicator:hover, QCheckBox::indicator:hover { border-color: %(accent)s; }
QRadioButton::indicator:checked { border-color: %(accent)s;
    background: qradialgradient(cx: 0.5, cy: 0.5, radius: 0.5, fx: 0.5, fy: 0.5,
                                stop: 0 %(accent)s, stop: 0.45 %(accent)s,
                                stop: 0.55 %(card)s, stop: 1 %(card)s); }
QCheckBox::indicator:checked { border-color: %(accent)s; background: %(accent)s;
                               image: url("%(check)s"); }
QRadioButton::indicator:disabled, QCheckBox::indicator:disabled { background: %(raised)s; }

QSplitter::handle { background: %(bg)s; }
QSplitter::handle:horizontal { width: 8px; }
QPushButton { background: %(card)s; border: 1px solid %(border)s; border-radius: %(r2)spx;
              padding: 6px 20px; }
QPushButton:hover { background: %(raised)s; }
QPushButton:disabled { color: %(text3)s; }
QPushButton:default { background: %(accent)s; border-color: %(accent)s; color: #ffffff; }
QPushButton:default:hover { background: %(accent_hover)s; }
QGroupBox { border: 1px solid %(border)s; border-radius: %(r)spx; margin-top: 16px;
            padding: 14px 12px 10px 12px; background: %(card)s; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: %(text2)s; }

QStatusBar { background: %(chrome)s; color: %(text2)s; border-top: 1px solid %(border)s; }
QStatusBar QLabel { color: %(text2)s; padding: 2px 8px; }
QStatusBar::item { border: none; }

QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle { background: %(border)s; border-radius: 4px; }
QScrollBar::handle:hover { background: %(text3)s; }
QScrollBar::handle:vertical { min-height: 30px; }
QScrollBar::handle:horizontal { min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

QMessageBox { background: %(card)s; }
QToolTip { background: %(card)s; color: %(text)s; border: 1px solid %(border)s; padding: 4px 8px; }
"""

_NATIVE_QSS = """
QMainWindow, QDialog, QSplitter::handle { background: %(bg)s; }
QMenuBar { background: %(chrome)s; border-bottom: 1px solid %(border)s; }
QToolBar#main { border: none; border-bottom: 1px solid %(border)s; }
QStatusBar { background: %(chrome)s; border-top: 1px solid %(border)s; }
QStatusBar QLabel { color: %(text2)s; }
/* Only the settings page list, not every QListView: combo box pop-ups are list views too. */
QTreeView, QListView#pageList, QFrame#card { background: %(card)s; border: 1px solid %(border)s; }
/* outline: 0 hides Windows' focus box around the current row; the tint already marks it. */
QTreeView, QListView#pageList { outline: 0; }
QTreeView::item { padding: 4px 2px; }
QListView#pageList::item { padding: 4px 8px; }
QTreeView::item:hover, QListView#pageList::item:hover { background: %(hover)s; }
QTreeView::item:selected, QListView#pageList::item:selected {
    background: %(sel)s; color: %(text)s; }
/* Tables marked "grid" get lines between rows and columns, like a spreadsheet. */
QTreeView#grid::item { border-right: 2px solid %(border)s; border-bottom: 2px solid %(border)s; }
QTreeView#grid QHeaderView::section { border-right: 2px solid %(border)s; }
/* No line after the last column, as there's none before the first. */
QTreeView#grid::item:last, QTreeView#grid::item:only-one,
QTreeView#grid QHeaderView::section:last,
QTreeView#grid QHeaderView::section:only-one { border-right: none; }
QLabel#paneTitle, QLabel#hint { color: %(text2)s; }
/* Toolbar buttons are outlined (design T1); thin lines divide the groups. Styling them drops
   the style's own menu arrow, so the theme's arrow is drawn instead. */
QToolBar#main QToolButton { color: %(text)s; background: %(card)s; border: 1px solid %(border)s;
                            border-radius: 4px; padding: 5px 10px; }
QToolBar#main QToolButton:hover { background: %(hover)s; }
QToolBar#main QToolButton:disabled { color: %(text2)s; }
QToolBar#main QToolButton[popupMode="1"], QToolBar#main QToolButton[popupMode="2"] {
    padding-right: 24px; }
QToolBar#main QToolButton::menu-button { border: none; border-left: 1px solid %(border)s;
                                         width: 18px; margin: 5px 0; }
QToolBar#main QToolButton::menu-arrow, QToolBar#main QToolButton::menu-indicator {
    image: url("%(arrow)s"); width: 10px; height: 6px; }
QToolBar#main QToolButton::menu-indicator { subcontrol-position: right center; right: 8px; }
QFrame#toolDivider { background: %(border)s; border: none; }
QTreeView#flat { border: none; background: transparent; }
QLineEdit#paneSearch { background: %(card)s; border: 1px solid %(border)s; padding: 5px 6px; }
QFrame#divider { background: %(border)s; border: none; }
QLabel#menuSection { color: %(text2)s; padding: 6px 12px 2px 12px; font-weight: 600; }
QFrame#tagEdit { background: %(card)s; border: 1px solid %(border)s; border-radius: 4px; }
QFrame#tagEdit[focused="true"] { border-color: %(accent)s; }
QLineEdit#tagInput { border: none; background: transparent; padding: 3px 2px; }
QFrame#tagChip { background: %(sel)s; border: none; border-radius: 9px; }
QToolButton#tagChipRemove {
    border: none; background: transparent; padding: 0 3px; color: %(text)s; }
"""


def stylesheet(theme: Theme) -> str:
    t: dict[str, object] = {k: _qss_color(v) for k, v in theme.colors.items()}
    t["r"], t["r2"] = theme.radius, max(0, theme.radius - 2)
    t["check"] = (THEMES_DIR / "check.svg").as_posix()
    t["arrow"] = (THEMES_DIR / f"arrow-{theme.scheme}.svg").as_posix()
    return _QSS % t  # noqa: UP031 -- %-format: CSS braces would all need doubling for .format()


def contrast_ratio(a: str, b: str) -> float:
    """WCAG contrast between two colours; normal text needs at least 4.5."""

    def luminance(value: str) -> float:
        color = QColor(value)

        def linear(c: float) -> float:
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        red, green, blue = (linear(c) for c in (color.redF(), color.greenF(), color.blueF()))
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _qss_color(value: str) -> str:
    color = QColor(value)
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"

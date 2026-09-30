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
        "bg": "#0b0f17", "card": "#121826", "raised": "#182033", "border": "#212a3b",
        "text": "#e7eaf1", "text2": "#aab2c3", "text3": "#6f7a8f",
        "hover": "#1494a3b8", "sel_solid": "#1b2a45",
        "accent": "#3b82f6", "accent_hover": "#5b95f7", "danger": "#f87171",
    },
    "light": {
        "bg": "#f4f6fb", "card": "#ffffff", "raised": "#f1f4f9", "border": "#e2e7f0",
        "text": "#111827", "text2": "#4b5563", "text3": "#8a94a6",
        "hover": "#0d0f172a", "sel_solid": "#e3ebfc",
        "accent": "#2563eb", "accent_hover": "#3b76ee", "danger": "#dc2626",
    },
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
    Theme("windows-system", "native", "system", N_("Windows — follow system")),
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
    if theme.engine == "native":
        app.setStyleSheet("")
        app.setFont(_native_font)
        QGuiApplication.styleHints().setColorScheme(scheme)
        app.setPalette(QPalette())  # an empty palette makes Qt resolve the system one again
        # A fresh style instance re-polishes every widget; switching the scheme alone left some
        # views with the previous theme's colours.
        app.setStyle("windows11")
        _refont(app, _native_font.families())
    else:
        if engine_changed:
            app.setFont(_native_font)
            # The stylesheet goes first, so widgets remember the native font to go back to.
            app.setStyleSheet(stylesheet(theme))
            app.setStyle("Fusion")
        font = QFont()
        font.setFamilies(list(theme.font[0]))
        font.setPointSizeF(theme.font[1])
        app.setFont(font)
        QGuiApplication.styleHints().setColorScheme(scheme)
        app.setPalette(_palette(theme.colors))
        app.setStyleSheet(stylesheet(theme))
        _refont(app, font.families())
    for widget in app.topLevelWidgets():
        if widget.isWindow() and widget.isVisible():
            paint_title_bar(widget)


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
QMenuBar { background: %(bg)s; padding: 4px 8px 0 8px; }
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

QLineEdit, QPlainTextEdit { background: %(card)s; border: 1px solid %(border)s;
                            border-radius: %(r2)spx; padding: 5px 7px;
                            selection-background-color: %(accent)s; }
QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid %(accent)s; }
QLineEdit:disabled { color: %(text3)s; background: %(raised)s; }
QComboBox { background: %(card)s; border: 1px solid %(border)s; border-radius: %(r2)spx;
            padding: 4px 10px; min-height: 22px; }
QComboBox:hover { border-color: %(text3)s; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: %(card)s; border: 1px solid %(border)s; outline: 0;
                              selection-background-color: %(sel_solid)s;
                              selection-color: %(text)s; }

QTreeView, QListView { background: %(card)s; border: 1px solid %(border)s; border-radius: %(r)spx;
                       outline: 0; alternate-background-color: %(card)s; padding: 4px; }
QTreeView::item, QListView::item { padding: 5px 4px; border: none; }
QTreeView::item:hover, QListView::item:hover { background: %(hover)s; }
QTreeView::item:selected, QListView::item:selected { background: %(sel_solid)s; color: %(text)s; }
QHeaderView { background: %(card)s; border: none; }
QHeaderView::section { background: %(card)s; color: %(text3)s; border: none;
                       border-bottom: 1px solid %(border)s; padding: 8px 6px; font-weight: 600; }
QHeaderView::section:hover { color: %(text)s; }

QSplitter::handle { background: %(bg)s; }
QSplitter::handle:horizontal { width: 8px; }
QPushButton { background: %(card)s; border: 1px solid %(border)s; border-radius: %(r2)spx;
              padding: 6px 14px; min-width: 64px; }
QPushButton:hover { background: %(raised)s; }
QPushButton:disabled { color: %(text3)s; }
QPushButton:default { background: %(accent)s; border-color: %(accent)s; color: #ffffff; }
QPushButton:default:hover { background: %(accent_hover)s; }
QGroupBox { border: 1px solid %(border)s; border-radius: %(r)spx; margin-top: 16px;
            padding: 14px 12px 10px 12px; background: %(card)s; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: %(text2)s; }

QStatusBar { background: %(bg)s; color: %(text3)s; }
QStatusBar QLabel { color: %(text3)s; padding: 2px 8px; }
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


def stylesheet(theme: Theme) -> str:
    t: dict[str, object] = {k: _qss_color(v) for k, v in theme.colors.items()}
    t["r"], t["r2"] = theme.radius, max(0, theme.radius - 2)
    return _QSS % t  # noqa: UP031 -- %-format: CSS braces would all need doubling for .format()


def _qss_color(value: str) -> str:
    color = QColor(value)
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"

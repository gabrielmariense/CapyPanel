"""Starts Qt, wires up the core services and shows the main window with every tool. It imports
no tool itself: the tool catalog loads them."""

import ctypes
import logging
import os
import sys
import time
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from capypanel import BUILD, __version__
from capypanel.__main__ import close_splash
from capypanel.core import applog, i18n, migration, settings
from capypanel.ui import branding, error_window, language
from capypanel.ui.dialogs import ScreenFit
from capypanel.ui.main_window.window import MainWindow
from capypanel.ui.one_copy import OneCopy, already_running_text
from capypanel.ui.themes import engine as themes
from capypanel.ui.tool_catalog import CATALOG
from capypanel.ui.updater import after_restart

log = logging.getLogger(__name__)


def _process_age() -> float:
    """Seconds since Windows made this process: Python's own start and every import before
    run() too. 0 when Windows won't say."""
    times = [wintypes.FILETIME() for _n in range(4)]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, *[ctypes.POINTER(wintypes.FILETIME)] * 4]
    if not kernel32.GetProcessTimes(kernel32.GetCurrentProcess(), *map(ctypes.byref, times)):
        return 0.0
    made = (times[0].dwHighDateTime << 32 | times[0].dwLowDateTime) / 1e7 - 11_644_473_600
    return max(0.0, time.time() - made)


class _Stages:
    """How long each part of the start took, for one line in the log: a slow start then says
    where the time went."""

    def __init__(self) -> None:
        self._before = _process_age()
        self._last = time.perf_counter()
        self._parts = [("before the app's own code", self._before)]

    def done(self, name: str) -> None:
        now = time.perf_counter()
        self._parts.append((name, now - self._last))
        self._last = now

    def text(self) -> str:
        total = sum(seconds for _name, seconds in self._parts)
        parts = ", ".join(f"{name} {seconds:.2f}" for name, seconds in self._parts)
        return f"Started in {total:.2f} s ({parts})"


SPLASH_WATCH_MS, SPLASH_WATCH_FOR_MS = 50, 3000


def _splash_on_screen() -> bool:
    """Whether the splash is still on screen: Tk's window, drawn by the exe's launcher in this
    same process. pyi_splash.close() only asks it to go, so it goes a moment later."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    pid, found = os.getpid(), []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd: int, _extra: int) -> bool:
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            name = ctypes.create_unicode_buffer(32)
            user32.GetClassNameW(hwnd, name, 32)
            if name.value == "TkTopLevel":
                found.append(hwnd)
                return False  # stop looking
        return True

    user32.EnumWindows(each, 0)
    return bool(found)


def _active() -> bool:
    return QGuiApplication.applicationState() == Qt.ApplicationState.ApplicationActive


class _HandOver:
    """The main window takes over from the splash. It's made active first, while the splash
    (this process) still has the focus; then the splash is told to go. Its window closes a
    moment later, and Windows then activates whichever window comes next, sometimes another
    program's: once it's gone, a main window left without the focus asks for it once. Windows
    itself refuses that when the person clicked another program meanwhile."""

    def __init__(self, window: QWidget, on_screen: Callable[[], bool] = _splash_on_screen):
        self._window, self._on_screen = window, on_screen
        self._left = SPLASH_WATCH_FOR_MS // SPLASH_WATCH_MS
        self._forward()
        close_splash()
        self._timer = QTimer()
        self._timer.setInterval(SPLASH_WATCH_MS)
        self._timer.timeout.connect(self.tick)
        self._timer.start()

    def _forward(self) -> None:
        self._window.raise_()
        self._window.activateWindow()

    def tick(self) -> None:
        if self._left <= 0:
            return  # done: a tick already queued does nothing
        self._left -= 1
        if self._left > 0 and self._on_screen():
            return
        self._left = 0
        self._timer.stop()
        window = self._window
        if not _active() and window.isVisible() and not window.isMinimized():
            log.info("The window lost the focus when the splash closed: asking for it back")
            self._forward()


def _set_reads(paths: settings.Paths) -> None:
    """How other PCs are read, as set for everyone on this PC (Settings › Hosts › Connecting)."""
    from capypanel.core.remote import inventory
    from capypanel.core.tools.catalog import reads_of

    inventory.transport = reads_of(paths.company_tools_dir)


def _reads_line() -> str:
    """How CapyPanel reads other PCs this time, for the log: a support question starts there."""
    from capypanel.core.remote import inventory, wmi

    if inventory.transport == inventory.POWERSHELL:
        return "Reads other PCs through PowerShell started on this PC (set in Settings)"
    if not wmi.available():
        return "Reads other PCs through PowerShell: WMI from Python isn't available here"
    if inventory.transport == inventory.DIRECT:
        return "Reads other PCs over WMI from CapyPanel itself, never PowerShell (set in Settings)"
    return "Reads other PCs over WMI from CapyPanel itself (PowerShell only if that can't be used)"


def run(argv: list[str] | None = None) -> int:
    stages = _Stages()
    branding.use_own_taskbar_icon()  # before any window exists
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("CapyPanel")
    app.setWindowIcon(branding.app_icon())
    app.setApplicationVersion(__version__)
    sys.excepthook = error_window.report

    # Logging first, so a problem with the user's folder is logged and shown, not lost.
    paths = settings.resolve_paths()
    applog.setup_logging(paths.log_file)
    _set_reads(paths)
    stages.done("Qt and the log")
    log.info("CapyPanel %s starting for %s (portable=%s)", BUILD, paths.account, paths.portable)
    log.info("%s", _reads_line())
    try:
        settings.ensure_dirs(paths)
    except settings.UserFolderError as e:
        log.error("%s", e)
        close_splash()
        QMessageBox.critical(None, "CapyPanel", str(e))
        return 1
    # One copy per person: started again, the running one comes forward and this one ends,
    # before it reads or writes anything of theirs.
    copy = OneCopy(paths.user_dir, app)
    if not copy.claim():
        came = copy.ask_running()
        close_splash()  # the open window came forward, or a message says why it couldn't
        log.info("Already running: %s", "its window was shown" if came else "it didn't show")
        if not came:
            language.apply(settings.language_of(paths.settings_file))
            QMessageBox.information(None, "CapyPanel", already_running_text(paths.account))
        return 0
    try:
        for copied in migration.migrate(paths):
            log.info("Copied from an older version: %s", copied)
    except OSError:
        log.exception("Couldn't copy files from an older version")
    prefs = settings.load_settings(paths.settings_file)
    stages.done("folders and settings")
    tools = [info.load() for info in CATALOG]
    for tool in tools:
        tool.prepare(paths)  # e.g. the files it starts with
    stages.done("the tools' code")
    language.apply(prefs.get("language", i18n.DEFAULT_LANGUAGE))  # before any window exists

    registry = themes.Registry()
    themes.apply(registry.find(prefs.get("theme")))
    app.installEventFilter(ScreenFit(app))  # no window opens larger than its screen
    stages.done("language and theme")
    window = MainWindow(paths, prefs, registry=registry, tools=tools)
    stages.done("the window and its lists")
    copy.show_requested.connect(window.open_from_tray)
    window.show()
    hand_over = _HandOver(window)  # noqa: F841  # kept until the app ends: its timer runs
    restarted = after_restart(sys.argv if argv is None else argv)
    if restarted is not None:  # the update's helper started this copy
        QTimer.singleShot(0, window, lambda: window.show_restart_note(*restarted))

    def shown() -> None:  # once Qt has drawn it: the wait the person saw
        stages.done("drawing it")
        log.info("%s", stages.text())

    QTimer.singleShot(0, shown)
    code = app.exec()
    copy.release()
    log.info("CapyPanel exiting (code %s)", code)
    return code

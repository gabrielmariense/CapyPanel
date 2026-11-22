import ctypes
import hashlib
import logging
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QEventLoop, QLockFile, QObject, QSysInfo, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from capypanel.core.i18n import _

log = logging.getLogger(__name__)

LOCK_NAME = "running.lock"
WAIT = 2000  # ms
SHOWN, ELSEWHERE = b"shown\n", b"elsewhere\n"


def _session() -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    found = wintypes.DWORD()
    if not kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(), ctypes.byref(found)):
        return -1
    return found.value


def _this_pc() -> str:
    return QSysInfo.machineHostName()


def _let_it_come_forward() -> None:
    """Windows lets a background app take the foreground only when the foreground one allows it."""
    ctypes.WinDLL("user32").AllowSetForegroundWindow(-1)


def pipe_name(lock: Path) -> str:
    """One name per settings folder; a hash, since a pipe's name can't hold a path."""
    return "CapyPanel-" + hashlib.sha256(str(lock).casefold().encode()).hexdigest()[:20]


def already_running_text(account: str) -> str:
    return _(
        "CapyPanel is already running for {account}, but its window couldn't be brought "
        "forward: it's open in another Windows session, or it isn't answering.\n\n"
        "Close it there (or end it in Task Manager), then start CapyPanel again."
    ).format(account=account)


class OneCopy(QObject):
    show_requested = Signal()

    def __init__(self, folder: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        path = folder / LOCK_NAME
        self._lock = QLockFile(str(path))
        self._lock.setStaleLockTime(0)  # never too old: free only once its process is gone
        self._name = pipe_name(path)
        self._server: QLocalServer | None = None

    def claim(self) -> bool:
        if not self._lock.tryLock(0):
            if self._lock.error() == QLockFile.LockError.LockFailedError and self._held_here():
                return False
            # No guard beats a CapyPanel that won't start (another PC's lock, a read-only folder).
            log.warning("Couldn't take %s: starting without it", self._lock.fileName())
        self._listen()
        return True

    def _held_here(self) -> bool:
        info = self._lock.getLockInfo()
        host = next((part for part in info if isinstance(part, str)), "")
        return not host or host.casefold() == _this_pc().casefold()

    def _listen(self) -> None:
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        server.newConnection.connect(self._connected)
        if not server.listen(self._name):
            log.warning("Later starts can't reach this copy: %s", server.errorString())
            return
        self._server = server

    def _connected(self) -> None:
        assert self._server is not None
        while (socket := self._server.nextPendingConnection()) is not None:
            socket.readyRead.connect(lambda s=socket: self._asked(s))
            socket.disconnected.connect(socket.deleteLater)

    def _asked(self, socket: QLocalSocket) -> None:
        if not socket.canReadLine():
            return
        asked_from = bytes(socket.readLine().data()).strip()
        here = asked_from == str(_session()).encode()
        if here:
            self.show_requested.emit()
        socket.write(SHOWN if here else ELSEWHERE)
        socket.flush()
        socket.disconnectFromServer()

    def ask_running(self) -> bool:
        _let_it_come_forward()
        socket = QLocalSocket()
        socket.connectToServer(self._name)
        if not socket.waitForConnected(WAIT):
            return False
        answer = bytearray()
        loop = QEventLoop()

        def read() -> None:
            answer.extend(bytes(socket.readAll().data()))
            if answer.endswith(b"\n"):
                loop.quit()

        socket.readyRead.connect(read)
        socket.disconnected.connect(loop.quit)
        QTimer.singleShot(WAIT, loop.quit)
        socket.write(f"{_session()}\n".encode())
        socket.flush()
        loop.exec()
        read()
        socket.abort()
        return bytes(answer) == SHOWN

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        self._lock.unlock()

"""Handing a secret to a program through a named pipe instead of a file: it never touches disk.
Only this Windows account can open the pipe, once, and the secret is written a single time."""

import ctypes
import logging
import secrets
import threading
from ctypes import wintypes

from capypanel.core import winsec

log = logging.getLogger(__name__)

_PIPE_ACCESS_OUTBOUND = 0x2
_FIRST_PIPE_INSTANCE = 0x80000  # fails if someone already made a pipe with this name
_PIPE_REJECT_REMOTE_CLIENTS = 0x8
_GENERIC_READ = 0x80000000
_OPEN_EXISTING = 3
_ERROR_PIPE_CONNECTED = 535
_INVALID_HANDLE = wintypes.HANDLE(-1).value


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_P = ctypes.POINTER
_kernel32.CreateNamedPipeW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    wintypes.DWORD, wintypes.DWORD, _P(_SecurityAttributes),
]  # fmt: skip
_kernel32.CreateNamedPipeW.restype = wintypes.HANDLE
_kernel32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
_kernel32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                _P(wintypes.DWORD), ctypes.c_void_p]  # fmt: skip
_kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]  # fmt: skip
_kernel32.CreateFileW.restype = wintypes.HANDLE


class SecretPipe:
    """Create it before starting the program, pass `path` to it, then call serve()."""

    def __init__(self) -> None:
        self.path = rf"\\.\pipe\capypanel-{secrets.token_hex(16)}"
        sddl = f"D:P(A;;GA;;;{winsec.current_user_sid()})"  # this account only
        with winsec.security_descriptor(sddl) as descriptor:
            attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
            handle = _kernel32.CreateNamedPipeW(
                self.path, _PIPE_ACCESS_OUTBOUND | _FIRST_PIPE_INSTANCE,
                _PIPE_REJECT_REMOTE_CLIENTS, 1, 4096, 4096, 0, ctypes.byref(attributes),
            )  # fmt: skip
        if handle in (None, _INVALID_HANDLE):
            raise ctypes.WinError(ctypes.get_last_error())
        self._handle = handle
        self._given_up = False

    def serve(self, secret: bytes, timeout: float = 60.0) -> threading.Thread:
        """Writes `secret` to the first reader, in the background. Gives up after `timeout`."""
        timer = threading.Timer(timeout, self._give_up)
        timer.daemon = True
        worker = threading.Thread(target=self._serve, args=(secret, timer), daemon=True)
        worker.start()
        timer.start()
        return worker

    def _serve(self, secret: bytes, timer: threading.Timer) -> None:
        handle = self._handle
        try:
            connected = _kernel32.ConnectNamedPipe(handle, None)  # waits for the reader
            if not connected and ctypes.get_last_error() != _ERROR_PIPE_CONNECTED:
                log.warning("Password pipe: no reader (%s)", ctypes.get_last_error())
                return
            if self._given_up:
                return  # the reader is our own _give_up(), not the program
            written = wintypes.DWORD()
            buffer = ctypes.create_string_buffer(secret, len(secret))
            _kernel32.WriteFile(handle, buffer, len(secret), ctypes.byref(written), None)
            _kernel32.FlushFileBuffers(handle)  # returns once the reader has it
            ctypes.memset(buffer, 0, len(secret))
        finally:  # closing (not disconnecting) lets the reader see a normal end of file
            timer.cancel()
            _kernel32.CloseHandle(handle)

    def close(self) -> None:
        """Closes a pipe that will never be served, e.g. when the program didn't start."""
        _kernel32.CloseHandle(self._handle)

    def _give_up(self) -> None:
        """Unblocks a server still waiting, by connecting to it ourselves without reading."""
        self._given_up = True
        client = _kernel32.CreateFileW(self.path, _GENERIC_READ, 0, None, _OPEN_EXISTING, 0, None)
        if client not in (None, _INVALID_HANDLE):
            log.warning("Password pipe: the program never read it")
            _kernel32.CloseHandle(client)

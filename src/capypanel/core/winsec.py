"""Windows accounts and folder permissions: who the user is, who owns a file, making a folder
private to its user or shared read-only. Reads the real logon token, never environment variables."""

import ctypes
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path

SYSTEM = "S-1-5-18"
ADMINISTRATORS = "S-1-5-32-544"
USERS = "S-1-5-32-545"
TRUSTED_INSTALLER = "S-1-5-80-956008885-3425870976-2464631459-2860876520"
_READ_EXECUTE = "0x1200a9"
_NAME_SAM_COMPATIBLE = 2  # "DOMAIN\user", or "PC\user" for a local account
_SE_FILE_OBJECT = 1
_OWNER_INFO = 0x1
_DACL_INFO = 0x4
_PROTECTED_DACL = 0x80000000
_TOKEN_QUERY = 0x8
_TOKEN_USER = 1

_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_secur32 = ctypes.WinDLL("secur32", use_last_error=True)
# Declared types: without them ctypes passes 64-bit handles and pointers as 32-bit ints.
_P = ctypes.POINTER
_VOID = ctypes.c_void_p
_kernel32.GetCurrentProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.LocalFree.argtypes = [_VOID]
_secur32.GetUserNameExW.argtypes = [ctypes.c_int, wintypes.LPWSTR, _P(wintypes.ULONG)]
_advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, _P(wintypes.HANDLE)]
_advapi32.GetTokenInformation.argtypes = [
    wintypes.HANDLE, ctypes.c_int, _VOID, wintypes.DWORD, _P(wintypes.DWORD)
]  # fmt: skip
_advapi32.GetNamedSecurityInfoW.argtypes = [
    wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, _P(_VOID), _P(_VOID), _P(_VOID), _P(_VOID),
    _P(_VOID),
]  # fmt: skip
_advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
_advapi32.SetNamedSecurityInfoW.argtypes = [
    wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, _VOID, _VOID, _VOID, _VOID
]  # fmt: skip
_advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
_advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, _P(_VOID), _P(wintypes.ULONG)
]  # fmt: skip
_advapi32.GetSecurityDescriptorDacl.argtypes = [
    _VOID, _P(wintypes.BOOL), _P(_VOID), _P(wintypes.BOOL)
]  # fmt: skip
_advapi32.ConvertSidToStringSidW.argtypes = [_VOID, _P(wintypes.LPWSTR)]


def account_name() -> str:
    """The signed-in account as "user@DOMAIN" (or "user@PC" for a local account)."""
    size = wintypes.ULONG(256)
    buffer = ctypes.create_unicode_buffer(size.value)
    if not _secur32.GetUserNameExW(_NAME_SAM_COMPATIBLE, buffer, ctypes.byref(size)):
        raise ctypes.WinError(ctypes.get_last_error())
    domain, _sep, user = buffer.value.rpartition("\\")
    return f"{user}@{domain}" if domain else user


def current_user_sid() -> str:
    token = wintypes.HANDLE()
    if not _advapi32.OpenProcessToken(
        _kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        needed = wintypes.DWORD()
        _advapi32.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(needed))
        info = ctypes.create_string_buffer(needed.value)
        if not _advapi32.GetTokenInformation(
            token, _TOKEN_USER, info, needed, ctypes.byref(needed)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        # TOKEN_USER starts with a pointer to the user's SID.
        return _sid_string(ctypes.c_void_p.from_buffer(info).value)
    finally:
        _kernel32.CloseHandle(token)


def owner_sid(path: Path) -> str | None:
    """The owner of a file or folder, or None where the drive has no owners (FAT, some shares)."""
    owner = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    status = _advapi32.GetNamedSecurityInfoW(
        str(path), _SE_FILE_OBJECT, _OWNER_INFO,
        ctypes.byref(owner), None, None, None, ctypes.byref(descriptor),
    )  # fmt: skip
    if status != 0:
        return None
    try:
        return _sid_string(owner.value) if owner.value else None
    finally:
        _kernel32.LocalFree(descriptor)


def made_by_trusted(path: Path) -> bool:
    """Whether a shared file was made by an administrator, the system or this user. In
    ProgramData any user can add files, so another user's file could lead CapyPanel elsewhere."""
    owner = owner_sid(path)
    trusted = (SYSTEM, ADMINISTRATORS, TRUSTED_INSTALLER, current_user_sid())
    return owner is None or owner in trusted


def make_private(folder: Path, user_sid: str) -> None:
    """Only this user, Administrators and the system can open the folder or anything in it.
    Raises OSError where permissions can't be set (e.g. a FAT USB stick)."""
    _set_dacl(folder, f"(A;OICI;FA;;;{user_sid})")


def make_shared(folder: Path, user_sid: str) -> None:
    """Everyone can read the folder; only its creator, Administrators and the system can change
    it. Without this, ProgramData lets any user add files to it. Raises OSError."""
    _set_dacl(folder, f"(A;OICI;FA;;;{user_sid})(A;OICI;{_READ_EXECUTE};;;{USERS})")


@contextmanager
def security_descriptor(sddl: str) -> Iterator[ctypes.c_void_p]:
    """Windows permissions written as SDDL text, as the structure the API takes; freed after."""
    descriptor = ctypes.c_void_p()
    if not _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, 1, ctypes.byref(descriptor), None
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield descriptor
    finally:
        _kernel32.LocalFree(descriptor)


def _set_dacl(folder: Path, aces: str) -> None:
    sddl = f"D:P(A;OICI;FA;;;{SYSTEM})(A;OICI;FA;;;{ADMINISTRATORS}){aces}"
    with security_descriptor(sddl) as descriptor:
        present, defaulted = wintypes.BOOL(), wintypes.BOOL()
        dacl = ctypes.c_void_p()
        if not _advapi32.GetSecurityDescriptorDacl(
            descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        status = _advapi32.SetNamedSecurityInfoW(
            str(folder), _SE_FILE_OBJECT, _DACL_INFO | _PROTECTED_DACL, None, None, dacl, None
        )
        if status != 0:
            raise ctypes.WinError(status)


def _sid_string(sid: int | None) -> str:
    text = wintypes.LPWSTR()
    if not _advapi32.ConvertSidToStringSidW(ctypes.c_void_p(sid), ctypes.byref(text)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return text.value or ""
    finally:
        _kernel32.LocalFree(ctypes.cast(text, ctypes.c_void_p))

"""Secrets CapyPanel keeps between runs, such as the printers' SNMP community string, stored in
Windows Credential Manager under the user's own account. They never go into the settings file
or a log: Windows encrypts them for this user, who can see or remove them in Control Panel ›
Credential Manager › Windows Credentials."""

import ctypes
from ctypes import wintypes

PREFIX = "CapyPanel/"  # every target name CapyPanel uses starts with this
_GENERIC = 1  # CRED_TYPE_GENERIC
_PERSIST_LOCAL_MACHINE = 2  # kept for this user on this PC, not roamed to others
_NOT_FOUND = 1168  # ERROR_NOT_FOUND
_MAX_SECRET = 2560  # CRED_MAX_CREDENTIAL_BLOB_SIZE, in bytes


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_P = ctypes.POINTER
_advapi32.CredWriteW.argtypes = [_P(_Credential), wintypes.DWORD]
_advapi32.CredWriteW.restype = wintypes.BOOL
_advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                _P(_P(_Credential))]  # fmt: skip
_advapi32.CredReadW.restype = wintypes.BOOL
_advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
_advapi32.CredDeleteW.restype = wintypes.BOOL
_advapi32.CredFree.argtypes = [ctypes.c_void_p]


def save(name: str, secret: str) -> None:
    """Keeps `secret` as CapyPanel/<name>, replacing what was there. Raises OSError."""
    blob = secret.encode("utf-16-le")
    if len(blob) > _MAX_SECRET:
        raise ValueError("too long to keep")
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    credential = _Credential(
        Type=_GENERIC,
        TargetName=PREFIX + name,
        CredentialBlobSize=len(blob),
        CredentialBlob=ctypes.cast(buffer, _P(ctypes.c_ubyte)),
        Persist=_PERSIST_LOCAL_MACHINE,
        UserName="CapyPanel",
    )
    if not _advapi32.CredWriteW(ctypes.byref(credential), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def load(name: str) -> str | None:
    """The secret kept as CapyPanel/<name>, or None when there's none. Raises OSError."""
    found = _P(_Credential)()
    if not _advapi32.CredReadW(PREFIX + name, _GENERIC, 0, ctypes.byref(found)):
        error = ctypes.get_last_error()
        if error == _NOT_FOUND:
            return None
        raise ctypes.WinError(error)
    try:
        credential = found.contents
        blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        return blob.decode("utf-16-le", errors="replace")
    finally:
        _advapi32.CredFree(found)


def forget(name: str) -> None:
    """Removes CapyPanel/<name>; nothing happens when there's none. Raises OSError."""
    if not _advapi32.CredDeleteW(PREFIX + name, _GENERIC, 0):
        error = ctypes.get_last_error()
        if error != _NOT_FOUND:
            raise ctypes.WinError(error)

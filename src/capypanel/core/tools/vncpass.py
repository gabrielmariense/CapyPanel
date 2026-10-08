"""The scrambled form of a VNC password that viewers read from password files (RealVNC's
PasswordFile, .vnc files): DES with a key every VNC program shares. It hides the password from a
glance, not from anyone who wants it, so it's never written to disk."""

import ctypes
from ctypes import wintypes

# The shared VNC key {23,82,107,6,35,78,88,7}, with each byte's bits reversed as VNC's DES expects.
VNC_KEY = bytes.fromhex("e84ad660c4721ae0")
BLOCK = 8

_bcrypt = ctypes.WinDLL("bcrypt")
_P = ctypes.POINTER
_VOID = ctypes.c_void_p
_bcrypt.BCryptOpenAlgorithmProvider.argtypes = [_P(_VOID), wintypes.LPCWSTR, wintypes.LPCWSTR,
                                                wintypes.ULONG]  # fmt: skip
_bcrypt.BCryptSetProperty.argtypes = [_VOID, wintypes.LPCWSTR, _VOID, wintypes.ULONG,
                                      wintypes.ULONG]  # fmt: skip
_bcrypt.BCryptGenerateSymmetricKey.argtypes = [_VOID, _P(_VOID), _VOID, wintypes.ULONG, _VOID,
                                               wintypes.ULONG, wintypes.ULONG]  # fmt: skip
_bcrypt.BCryptEncrypt.argtypes = [_VOID, _VOID, wintypes.ULONG, _VOID, _VOID, wintypes.ULONG,
                                  _VOID, wintypes.ULONG, _P(wintypes.ULONG),
                                  wintypes.ULONG]  # fmt: skip
_bcrypt.BCryptDestroyKey.argtypes = [_VOID]
_bcrypt.BCryptCloseAlgorithmProvider.argtypes = [_VOID, wintypes.ULONG]
for _f in ("BCryptOpenAlgorithmProvider", "BCryptSetProperty", "BCryptGenerateSymmetricKey",
           "BCryptEncrypt", "BCryptDestroyKey", "BCryptCloseAlgorithmProvider"):  # fmt: skip
    getattr(_bcrypt, _f).restype = wintypes.LONG  # NTSTATUS: 0 = success


def obfuscate(password: str) -> bytes:
    """8 bytes per started block of 8 password bytes (UTF-8), zero-padded."""
    raw = password.encode("utf-8") or b"\0"
    raw += b"\0" * (-len(raw) % BLOCK)
    return des_ecb(VNC_KEY, raw)


def des_ecb(key: bytes, data: bytes) -> bytes:
    """Plain single DES, each 8-byte block on its own (Windows' own implementation)."""
    algorithm, handle = _VOID(), _VOID()
    _check(_bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(algorithm), "DES", None, 0))
    try:
        mode = ctypes.create_unicode_buffer("ChainingModeECB")
        _check(_bcrypt.BCryptSetProperty(algorithm, "ChainingMode", mode, ctypes.sizeof(mode), 0))
        secret = ctypes.create_string_buffer(key, len(key))
        _check(_bcrypt.BCryptGenerateSymmetricKey(
            algorithm, ctypes.byref(handle), None, 0, secret, len(key), 0
        ))  # fmt: skip
        try:
            source = ctypes.create_string_buffer(data, len(data))
            out = ctypes.create_string_buffer(len(data))
            written = wintypes.ULONG()
            _check(_bcrypt.BCryptEncrypt(
                handle, source, len(data), None, None, 0, out, len(data), ctypes.byref(written), 0
            ))  # fmt: skip
            return out.raw[: written.value]
        finally:
            _bcrypt.BCryptDestroyKey(handle)
    finally:
        _bcrypt.BCryptCloseAlgorithmProvider(algorithm, 0)


def _check(status: int) -> None:
    if status != 0:
        raise OSError(f"Windows cryptography failed (0x{status & 0xFFFFFFFF:08X})")

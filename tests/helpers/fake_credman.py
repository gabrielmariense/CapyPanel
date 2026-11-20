"""Windows Credential Manager for the tests: credstore's five advapi32 calls, kept in memory, so no
test reads or writes the real one (shared by the user's processes, it lost updates under load)."""

import ctypes
from dataclasses import dataclass
from typing import Any

from capypanel.core import credstore

NOT_FOUND = 1168  # ERROR_NOT_FOUND
_P = ctypes.POINTER


@dataclass(frozen=True)
class Entry:
    target: str
    user: str
    blob: bytes
    type: int
    persist: int


class FakeCredentialManager:
    """One user's generic credentials. Target names match without regard to case, as in
    Windows; a list's filter may end in "*"."""

    def __init__(self) -> None:
        self.entries: dict[str, Entry] = {}  # by target, folded
        self._handed_out: dict[int, list[Any]] = {}  # what CredFree frees, by address

    def CredWriteW(self, credential: Any, flags: int) -> bool:
        written: credstore._Credential = credential._obj  # passed with ctypes.byref
        blob = ctypes.string_at(written.CredentialBlob, written.CredentialBlobSize)
        entry = Entry(written.TargetName, written.UserName or "", blob, written.Type,
                      written.Persist)  # fmt: skip
        self.entries[entry.target.casefold()] = entry
        return True

    def CredReadW(self, target: str, kind: int, flags: int, found: Any) -> bool:
        entry = self.entries.get(target.casefold())
        if entry is None or entry.type != kind:
            return self._fail(NOT_FOUND)
        credential, keep = self._credential(entry)
        self._hand_out(found._obj, credential, keep)
        return True

    def CredEnumerateW(self, pattern: str, flags: int, count: Any, found: Any) -> bool:
        start = pattern.removesuffix("*").casefold()
        exact = not pattern.endswith("*")
        matches = [e for key, e in sorted(self.entries.items())
                   if (key == start if exact else key.startswith(start))]  # fmt: skip
        if not matches:
            return self._fail(NOT_FOUND)
        keep: list[Any] = []
        array = (_P(credstore._Credential) * len(matches))()
        for index, entry in enumerate(matches):
            credential, kept = self._credential(entry)
            array[index] = ctypes.pointer(credential)
            keep += kept
        count._obj.value = len(matches)
        self._hand_out(found._obj, array, keep)
        return True

    def CredDeleteW(self, target: str, kind: int, flags: int) -> bool:
        entry = self.entries.get(target.casefold())
        if entry is None or entry.type != kind:
            return self._fail(NOT_FOUND)
        del self.entries[target.casefold()]
        return True

    def CredFree(self, pointer: Any) -> None:
        address = ctypes.cast(pointer, ctypes.c_void_p).value
        assert address in self._handed_out, "CredFree of something no call handed out"
        del self._handed_out[address]

    def unfreed(self) -> int:
        """How many results credstore hasn't freed yet."""
        return len(self._handed_out)

    @staticmethod
    def _fail(error: int) -> bool:
        ctypes.set_last_error(error)
        return False

    @staticmethod
    def _credential(entry: Entry) -> tuple[credstore._Credential, list[Any]]:
        blob = (ctypes.c_ubyte * len(entry.blob)).from_buffer_copy(entry.blob)
        credential = credstore._Credential(
            Type=entry.type,
            TargetName=entry.target,
            CredentialBlobSize=len(entry.blob),
            CredentialBlob=ctypes.cast(blob, _P(ctypes.c_ubyte)),
            Persist=entry.persist,
            UserName=entry.user,
        )
        return credential, [credential, blob]

    def _hand_out(self, pointer: Any, target: Any, keep: list[Any]) -> None:
        """Points the caller's pointer at `target`, kept alive until CredFree."""
        ctypes.c_void_p.from_buffer(pointer).value = ctypes.addressof(target)
        self._handed_out[ctypes.addressof(target)] = [target, *keep]

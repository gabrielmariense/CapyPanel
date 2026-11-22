"""WMI from Python itself, over DCOM through Windows' scripting objects: no PowerShell or other
program started here, so no antivirus has a command line to judge. Each read has its own thread."""

import contextlib
import logging
import threading
from collections.abc import Callable, Mapping
from typing import Any

from capypanel.core.remote.access import Account, Reason, RemoteError, reason_of

log = logging.getLogger(__name__)

# The registry hives StdRegProv takes, as the signed numbers COM carries them (0x80000002…).
HKLM = 0x80000002 - 2**32
HKU = 0x80000003 - 2**32

_LOCAL_CREDENTIALS = 0x80041064  # WBEM_E_LOCAL_CREDENTIALS: no account when connecting here
_ACCESS_DENIED = 0x80041003  # WBEM_E_ACCESS_DENIED: connected, but not allowed to read
_USE_MAX_WAIT = 0x80  # wbemConnectFlagUseMaxWait: connecting gives up after about 2 minutes
_IMPERSONATE = 3  # wbemImpersonationLevelImpersonate
_PACKET_PRIVACY = 6  # wbemAuthenticationLevelPktPrivacy: what hardened DCOM asks for at least


class Unavailable(Exception):
    """WMI can't be used from this PC at all (pywin32 missing, Windows' scripting objects not
    registered): another way may still work. Never about the other PC."""


def available() -> bool:
    try:
        import pythoncom  # noqa: F401
        import win32com.client  # noqa: F401
    except ImportError:
        return False
    return True


def error_of(error: BaseException) -> RemoteError:
    """A COM failure as the RemoteError the other ways raise. WMI's own code is in the error's
    details; Windows' errors among them (0x8007xxxx) carry the same codes as the other calls."""
    code = 0
    args = getattr(error, "args", ())
    if len(args) >= 3 and isinstance(args[2], tuple) and len(args[2]) >= 6 and args[2][5]:
        code = int(args[2][5])
    elif args and isinstance(args[0], int):
        code = int(args[0])
    code &= 0xFFFFFFFF
    if code >> 16 == 0x8007:
        return RemoteError(reason_of(code & 0xFFFF), code & 0xFFFF)
    if code == _ACCESS_DENIED:
        return RemoteError(Reason.NOT_ADMIN, code)
    return RemoteError(Reason.OTHER, code)


def message_of(error: BaseException) -> str:
    args = getattr(error, "args", ())
    if len(args) >= 3 and isinstance(args[2], tuple) and len(args[2]) >= 3 and args[2][2]:
        return str(args[2][2]).strip()
    return str(error)


class Wmi:
    """One PC's WMI, root\\cimv2 for its classes and root\\default for its registry, signed in
    with `account` (None: this Windows account)."""

    def __init__(self, host: str, account: Account | None) -> None:
        import pywintypes
        import win32com.client

        try:
            self._locator = win32com.client.Dispatch("WbemScripting.SWbemLocator")
        except pywintypes.com_error as e:
            raise Unavailable(message_of(e)) from e
        self._host = self.host = host
        self._user, self._password = (account.user, account.password) if account else ("", "")
        self.cim = self._connect("root\\cimv2")
        self._registry: Any = None

    def _connect(self, namespace: str) -> Any:
        import pywintypes

        try:
            try:
                services = self._locator.ConnectServer(
                    self._host, namespace, self._user, self._password, "", "", _USE_MAX_WAIT
                )
            except pywintypes.com_error as e:
                if error_of(e).code != _LOCAL_CREDENTIALS or not self._user:
                    raise
                # This PC itself: Windows takes no account here, and this one is in use already.
                services = self._locator.ConnectServer(
                    self._host, namespace, "", "", "", "", _USE_MAX_WAIT
                )
        except pywintypes.com_error as e:
            raise error_of(e) from e
        services.Security_.ImpersonationLevel = _IMPERSONATE
        services.Security_.AuthenticationLevel = _PACKET_PRIVACY
        return services

    def rows(self, wql: str) -> list[Any]:
        import pywintypes

        try:
            return list(self.cim.ExecQuery(wql))
        except pywintypes.com_error as e:
            raise error_of(e) from e

    def first(self, wql: str) -> Any:
        found = self.rows(wql)
        return found[0] if found else None

    def call(self, class_name: str, method: str, **arguments: Any) -> Any:
        """A class's own method (Win32_Process.Create…): its answer, with ReturnValue."""
        import pywintypes

        try:
            target = self.cim.Get(class_name)
            given = target.Methods_(method).InParameters.SpawnInstance_()
            for name, value in arguments.items():
                setattr(given, name, value)
            return target.ExecMethod_(method, given)
        except pywintypes.com_error as e:
            raise error_of(e) from e

    def reg(self, method: str, hive: int, key: str, name: str | None = None) -> Any:
        """One StdRegProv call; its answer has ReturnValue and the method's own values."""
        import pywintypes

        try:
            if self._registry is None:
                self._registry = self._connect("root\\default").Get("StdRegProv")
            given = self._registry.Methods_(method).InParameters.SpawnInstance_()
            given.hDefKey = hive
            given.sSubKeyName = key
            if name is not None:
                given.sValueName = name
            return self._registry.ExecMethod_(method, given)
        except pywintypes.com_error as e:
            raise error_of(e) from e

    def subkeys(self, hive: int, key: str) -> list[str]:
        return [str(n) for n in (self.reg("EnumKey", hive, key).sNames or ()) if n]

    def value_names(self, hive: int, key: str) -> tuple[int, list[str], list[int]]:
        """(Windows' answer, 0 when the key exists; its value names; their types)."""
        found = self.reg("EnumValues", hive, key)
        names = [str(n) for n in (found.sNames or ())]
        types = [int(t) for t in (found.Types or ())]
        return int(found.ReturnValue or 0), names, types

    def string(self, hive: int, key: str, name: str) -> str | None:
        value = self.reg("GetStringValue", hive, key, name).sValue
        return None if value is None else str(value)

    def expanded(self, hive: int, key: str, name: str) -> str | None:
        value = self.reg("GetExpandedStringValue", hive, key, name).sValue
        return None if value is None else str(value)

    def dword(self, hive: int, key: str, name: str) -> int | None:
        """A DWORD as the unsigned number it is: COM hands one of 2**31 or more over as negative,
        as a FILETIME's low half is about half the time."""
        value = self.reg("GetDWORDValue", hive, key, name).uValue
        return None if value is None else int(value) & 0xFFFF_FFFF


def read(
    reader: Callable[["Wmi", Mapping[str, str]], Any],
    host: str,
    account: Account | None,
    values: Mapping[str, str],
    timeout: float,
) -> Any:
    """`reader` connected to `host`, on its own thread with COM set up: plain data only comes back.
    Raises what it raises, RemoteError, Unavailable, or TimeoutError after `timeout` seconds."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            import pythoncom
        except ImportError as e:
            box["error"] = Unavailable(str(e))
            return
        pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
        try:
            box["value"] = reader(Wmi(host, account), values)
        except BaseException as e:  # noqa: BLE001 - handed to the caller's thread
            box["error"] = e
        finally:
            with contextlib.suppress(Exception):
                pythoncom.CoUninitialize()

    thread = threading.Thread(target=run, name="wmi", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():  # left to end on its own: COM calls can't be cut short
        raise TimeoutError(f"WMI didn't answer within {timeout:.0f} s")
    if "error" in box:
        raise box["error"]
    return box.get("value")

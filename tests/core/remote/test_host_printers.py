import ctypes
from typing import Any

import pytest

from capypanel.core.remote import host_printers
from capypanel.core.remote.access import Reason, RemoteError
from capypanel.core.remote.host_printers import HostPrinter


def test_this_pcs_printers_can_be_read_with_the_real_api() -> None:
    found = host_printers.list_printers(None)  # checks the structures match Windows
    assert all(isinstance(p, HostPrinter) and p.name and "\\" not in p.name for p in found)
    assert [p.name.casefold() for p in found] == sorted(p.name.casefold() for p in found)


def test_a_printers_status_bits_become_plain_problems() -> None:
    info = host_printers._Info2()
    info.pPrinterName = "\\\\DESK-02\\Front desk"
    info.pDriverName, info.pPortName, info.pShareName = "HP Universal", "IP_192.0.2.51", "FD"
    info.Attributes, info.Status, info.cJobs = 0x8, 0x8 | 0x80000, 3  # shared; jam, toner low
    assert host_printers._printer(info) == HostPrinter(
        "Front desk", "HP Universal", "IP_192.0.2.51", "FD", 3, ("paper jam", "toner low")
    )


class FakeSpooler:
    def __init__(self, error: int = 0) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.error = error

    def OpenPrinterW(self, name: str, handle: Any, defaults: Any) -> bool:  # noqa: N802
        access = ctypes.cast(defaults, ctypes.POINTER(host_printers._Defaults)).contents
        self.calls.append(("open", name, access.DesiredAccess))
        ctypes.cast(handle, ctypes.POINTER(ctypes.c_void_p)).contents.value = 9
        return True

    def SetPrinterW(self, handle: int, level: int, info: None, command: int) -> bool:  # noqa: N802
        self.calls.append(("set", level, command))
        ctypes.set_last_error(self.error)
        return not self.error

    def ClosePrinter(self, handle: int) -> bool:  # noqa: N802
        self.calls.append(("close",))
        return True


def test_clearing_a_queue_purges_that_printer_as_its_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeSpooler()
    monkeypatch.setattr(host_printers, "_winspool", fake)
    monkeypatch.setattr(host_printers, "check_reachable", lambda host: None)
    host_printers.clear_queue("192.0.2.10", "Front desk")
    assert fake.calls == [("open", "\\\\192.0.2.10\\Front desk", 0x4), ("set", 0, 3), ("close",)]


def test_a_refused_purge_says_why_and_closes_the_printer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeSpooler(error=5)
    monkeypatch.setattr(host_printers, "_winspool", fake)
    monkeypatch.setattr(host_printers, "check_reachable", lambda host: None)
    with pytest.raises(RemoteError) as caught:
        host_printers.clear_queue("192.0.2.10", "Front desk")
    assert caught.value.reason is Reason.REJECTED and fake.calls[-1] == ("close",)


def test_an_unreachable_host_is_never_asked() -> None:
    with pytest.raises(RemoteError) as caught:
        host_printers.list_printers("192.0.2.1")  # a documentation address: never a real host
    assert caught.value.reason is Reason.UNREACHABLE

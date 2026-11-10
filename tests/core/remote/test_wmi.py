"""The two ways reads reach a PC's WMI: straight from CapyPanel over COM, and through a
PowerShell started on this PC. On a real PC (this one) both must give the very same answers,
and each falls back or fails the way its setting says. Nothing here reaches another PC."""

import secrets
import subprocess
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from capypanel.core.remote import drives, inventory, run, user_profiles, wmi
from capypanel.core.remote.access import Account, Reason, RemoteError
from capypanel.core.remote.user_profiles import Kind, Outcome, Profile, Scan, State, Why


def _here(path: str) -> str:
    return "\\\\?\\" + path


@pytest.fixture(autouse=True)
def no_reach_check(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for module in (inventory, drives, user_profiles):
        monkeypatch.setattr(module, "check_reachable", lambda host: None)
    yield
    inventory.transport = inventory.AUTO


def _both(read: Callable[[], Any]) -> tuple[Any, Any]:
    """`read` done straight over WMI, then through PowerShell."""
    inventory.transport = inventory.DIRECT
    direct = read()
    inventory.transport = inventory.POWERSHELL
    shell = read()
    return direct, shell


def test_pywin32_is_there_and_this_pc_reads_straight_over_wmi() -> None:
    assert wmi.available()

    def reader(found: wmi.Wmi, _values: Any) -> str:
        return str(found.first("SELECT Caption FROM Win32_OperatingSystem").Caption)

    assert "Windows" in wmi.read(reader, "localhost", None, {}, 60)


def test_this_pcs_facts_are_the_same_both_ways() -> None:
    direct, shell = _both(lambda: inventory.pc_facts("localhost"))
    assert direct == shell and direct.windows.startswith("Windows") and direct.memory > 0


def test_this_pcs_programs_are_the_same_both_ways() -> None:
    direct, shell = _both(lambda: inventory.installed_programs("localhost"))
    assert direct == shell and direct


def test_this_pcs_signed_in_people_are_the_same_both_ways() -> None:
    direct, shell = _both(lambda: drives.saved_drives("localhost"))
    assert direct == shell and direct


def test_this_pcs_profiles_are_the_same_both_ways() -> None:
    direct, shell = _both(lambda: user_profiles.scan("localhost", opened=_here))
    assert direct == shell and direct.profiles


def test_both_delete_ways_find_nothing_to_delete_for_a_sid_nobody_has() -> None:
    sid = f"S-1-5-21-1111111111-222222222-333333333-{secrets.randbelow(80000) + 10000}"
    scanned = Scan("localhost", "C:\\Users", ())
    nobody = f"C:\\Users\\capypanel-nobody-{secrets.token_hex(3)}"
    for transport in (inventory.DIRECT, inventory.POWERSHELL):
        inventory.transport = transport
        for kind in (Kind.PROFILE, Kind.ENTRY):
            profile = Profile(sid, sid, "nobody", False, nobody, kind, State.READY)
            done = user_profiles.delete(scanned, profile, opened=_here)
            assert (done.outcome, done.why, done.detail) == (Outcome.SKIPPED, Why.GONE, "")


def test_an_account_is_left_out_when_the_pc_is_this_one() -> None:
    """Windows takes no account for a connection to itself: the read goes on with this one."""

    def reader(found: wmi.Wmi, _values: Any) -> str:
        return str(found.first("SELECT BuildNumber FROM Win32_OperatingSystem").BuildNumber)

    assert wmi.read(reader, "localhost", Account("EXAMPLE\\nobody", "x"), {}, 60).isdigit()


def test_a_start_goes_straight_over_wmi_too() -> None:
    assert run._START in inventory._READERS  # Win32_Process.Create, with no PowerShell here


# ---- choosing the way ----


def test_auto_falls_back_to_powershell_only_when_wmi_cant_be_used_here(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell: list[str] = []
    monkeypatch.setattr(
        inventory, "_powershell", lambda script, host, *_more: shell.append(host) or {"ok": 1}
    )

    def unusable(*_args: Any) -> Any:
        raise wmi.Unavailable("class not registered")

    monkeypatch.setattr(wmi, "read", unusable)
    assert inventory.run_cim(inventory._FACTS, "DESK-01", None) == {"ok": 1}
    assert shell == ["DESK-01"]
    inventory.transport = inventory.DIRECT  # only WMI: no fallback
    with pytest.raises(RemoteError):
        inventory.run_cim(inventory._FACTS, "DESK-01", None)

    def refused(*_args: Any) -> Any:
        raise RemoteError(Reason.REJECTED, 5)  # the other PC said no: PowerShell won't help

    monkeypatch.setattr(wmi, "read", refused)
    inventory.transport = inventory.AUTO
    with pytest.raises(RemoteError):
        inventory.run_cim(inventory._FACTS, "DESK-01", None)
    assert shell == ["DESK-01"]


def test_powershell_only_and_winrm_never_go_straight(monkeypatch: pytest.MonkeyPatch) -> None:
    shell: list[str] = []
    monkeypatch.setattr(
        inventory,
        "_powershell",
        lambda script, host, account, protocol, *_m: shell.append(protocol),
    )
    monkeypatch.setattr(wmi, "read", lambda *_a: pytest.fail("went straight"))
    inventory.transport = inventory.POWERSHELL
    inventory.run_cim(inventory._FACTS, "DESK-01", None)
    inventory.transport = inventory.AUTO
    inventory.run_cim(run._START, "DESK-01", None, "Wsman", {"command": "x"})  # WinRM
    inventory.run_cim("Send 1", "DESK-01", None)  # a script with no twin
    assert shell == ["Dcom", "Wsman", "Dcom"]


def test_powershell_that_windows_wont_start_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*_args: Any, **_more: Any) -> subprocess.CompletedProcess[bytes]:
        raise PermissionError(13, "Access is denied")  # what an antivirus's refusal looks like

    monkeypatch.setattr(inventory.subprocess, "run", blocked)
    inventory.transport = inventory.POWERSHELL
    with pytest.raises(inventory.PowerShellBlocked) as caught:
        inventory.run_cim(inventory._FACTS, "DESK-01", None)
    assert "an antivirus may have blocked it" in str(caught.value)
    assert isinstance(caught.value, OSError)  # never taken for the other PC's answer


def test_com_errors_read_as_the_other_ways_errors() -> None:
    def failure(code: int) -> Exception:
        return Exception(
            -2147352567, "Exception occurred.", (0, "SWbemLocator", "x", None, 0, code), None
        )

    assert wmi.error_of(failure(0x80070005 - 2**32)).reason is Reason.REJECTED  # access denied
    assert wmi.error_of(failure(0x800706BA - 2**32)).reason is Reason.UNREACHABLE  # RPC down
    assert wmi.error_of(failure(0x80041003 - 2**32)).reason is Reason.NOT_ADMIN
    other = wmi.error_of(failure(0x80041002 - 2**32))  # not found: WMI's own
    assert (other.reason, other.code) == (Reason.OTHER, 0x80041002)
    assert wmi.error_of(Exception(0x800706BA - 2**32, "x", None, None)).reason is Reason.UNREACHABLE

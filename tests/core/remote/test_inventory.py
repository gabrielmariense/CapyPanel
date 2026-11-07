import base64
import json
import subprocess
from datetime import UTC, date, datetime
from typing import Any

import pytest

from capypanel.core.remote import inventory
from capypanel.core.remote.access import Account, Reason, RemoteError


@pytest.fixture
def reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inventory, "check_reachable", lambda host: None)


def test_this_pcs_space_and_last_restart_read_with_the_real_api(reachable: None) -> None:
    space = inventory.disk_space("localhost")
    assert space.total > space.free > 0
    assert (
        datetime(2000, 1, 1, tzinfo=UTC) < inventory.last_restart("localhost") < datetime.now(UTC)
    )


def test_this_pcs_facts_read_over_wmi(reachable: None) -> None:
    facts = inventory.pc_facts("localhost")  # checks the PowerShell script really runs
    assert facts.windows.startswith("Windows") and facts.memory > 0
    assert facts.build.split(".")[0].isdigit()


def test_this_pcs_programs_read_over_wmi(reachable: None) -> None:
    programs = inventory.installed_programs("localhost")
    assert programs and all(p.name for p in programs)
    keys = [(p.name.casefold(), p.version) for p in programs]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)


class FakePowerShell:
    def __init__(self, answer: object, code: int = 0) -> None:
        self.answer, self.code = answer, code
        self.argv: list[str] = []
        self.input = b""

    def __call__(self, argv: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
        self.argv, self.input = argv, options["input"]
        out = base64.b64encode(json.dumps(self.answer).encode())
        return subprocess.CompletedProcess(argv, self.code, out, b"")


def test_the_host_and_password_go_in_through_standard_input(
    monkeypatch: pytest.MonkeyPatch, reachable: None
) -> None:
    fake = FakePowerShell([])
    monkeypatch.setattr(inventory.subprocess, "run", fake)
    host, secret = "192.0.2.10'; Remove-Item C:\\ -Recurse; '", "pa'ss\"wörd"
    inventory.installed_programs(host, Account("EXAMPLE\\admin", secret))
    command = " ".join(fake.argv)
    assert "192.0.2.10" not in command and "pa'ss" not in command
    assert json.loads(fake.input) == {
        "host": host, "protocol": "Dcom", "user": "EXAMPLE\\admin", "password": secret,
    }  # fmt: skip


def test_programs_are_cleaned_sorted_and_listed_once(
    monkeypatch: pytest.MonkeyPatch, reachable: None
) -> None:
    entry = {"DisplayName": " Zip tool ", "DisplayVersion": "2.1", "Publisher": "SAMPLE"}
    answer = [
        {**entry, "InstallDate": "20260115"},
        {**entry, "InstallDate": "15/01/2026"},  # the same, from the 32-bit list
        {"DisplayName": "archive viewer"},
    ]
    monkeypatch.setattr(inventory.subprocess, "run", FakePowerShell(answer))
    assert inventory.installed_programs("192.0.2.10") == [
        inventory.Program("archive viewer", "", "", None),
        inventory.Program("Zip tool", "2.1", "SAMPLE", None),  # the later one's unreadable date
    ]
    one = inventory._program({**entry, "InstallDate": "20260115"})
    assert one.installed == date(2026, 1, 15)


def test_facts_join_the_build_and_its_patch_level(
    monkeypatch: pytest.MonkeyPatch, reachable: None
) -> None:
    answer = {
        "caption": "Microsoft Windows 11 Pro", "release": "25H2", "build": "26200", "patch": 9168,
        "maker": "SAMPLE ", "model": "Desk 3000", "serial": "SAMPLE123", "bios": "1.2.3",
        "memory": 4 * 2**30,
    }  # fmt: skip
    monkeypatch.setattr(inventory.subprocess, "run", FakePowerShell(answer))
    facts = inventory.pc_facts("192.0.2.10")
    assert (facts.windows, facts.release, facts.build) == ("Windows 11 Pro", "25H2", "26200.9168")
    assert facts.maker == "SAMPLE" and facts.memory == 4 * 2**30


@pytest.mark.parametrize(
    ("code", "reason", "windows_code"),
    [
        (0x8007052E, Reason.REJECTED, 1326),  # wrong password
        (0x800706BA, Reason.UNREACHABLE, 1722),  # RPC server unavailable
        (0x80070005, Reason.REJECTED, 5),
        (0x80041003, Reason.NOT_ADMIN, 0x80041003),  # WMI: not allowed to read
        (-2146233088, Reason.OTHER, 0x80131500),  # .NET's generic failure, as a signed number
    ],
)
def test_wmi_failures_say_why(code: int, reason: Reason, windows_code: int) -> None:
    error = inventory.wmi_error(code)
    assert (error.reason, error.code) == (reason, windows_code)


def test_a_failed_wmi_run_raises_its_reason(
    monkeypatch: pytest.MonkeyPatch, reachable: None
) -> None:
    monkeypatch.setattr(inventory.subprocess, "run", FakePowerShell({"error": 0x8007052E}, 1))
    with pytest.raises(RemoteError) as caught:
        inventory.pc_facts("192.0.2.10")
    assert caught.value.reason is Reason.REJECTED


def test_a_wmi_run_that_hangs_gives_up(monkeypatch: pytest.MonkeyPatch, reachable: None) -> None:
    def hang(argv: list[str], **options: Any) -> None:
        raise subprocess.TimeoutExpired(argv, inventory.WMI_TIMEOUT)

    monkeypatch.setattr(inventory.subprocess, "run", hang)
    with pytest.raises(TimeoutError):
        inventory.pc_facts("192.0.2.10")


def test_an_unreachable_host_is_never_asked() -> None:
    with pytest.raises(RemoteError) as caught:
        inventory.disk_space("192.0.2.1")  # a documentation address: never a real host
    assert caught.value.reason is Reason.UNREACHABLE

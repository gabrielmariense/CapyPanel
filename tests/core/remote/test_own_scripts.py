import hashlib
import subprocess
from pathlib import Path

import pytest

from capypanel.core import winsec
from capypanel.core.remote import own_scripts
from capypanel.core.remote.own_scripts import Approval, State
from capypanel.core.remote.run import Language, RunAs


def _digest(code: bytes) -> str:
    return hashlib.sha256(code).hexdigest()


def _approved(code: bytes, **kw: object) -> Approval:
    return Approval(_digest(code), risky=False, **kw)  # type: ignore[arg-type]


def test_scan_lists_scripts_only_by_name(tmp_path: Path) -> None:
    (tmp_path / "b printers.ps1").write_bytes(b"x")
    (tmp_path / "A fix.CMD").write_bytes(b"echo")
    (tmp_path / "notes.txt").write_bytes(b"no")
    (tmp_path / "old.ps1.bak").write_bytes(b"no")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.ps1").write_bytes(b"no")
    found = own_scripts.scan(tmp_path, {})
    assert [s.name for s in found] == ["A fix", "b printers"]
    assert [s.language for s in found] == [Language.BATCH, Language.POWERSHELL]
    assert all(s.state is State.NEW for s in found)


def test_an_unchanged_approved_script_is_ready(tmp_path: Path) -> None:
    (tmp_path / "Fix.ps1").write_bytes(b"Write-Output hi")
    found = own_scripts.scan(tmp_path, {"fix.ps1": _approved(b"Write-Output hi")})
    assert found[0].ready
    assert found[0].code == b"Write-Output hi"


def test_a_changed_script_needs_review_again(tmp_path: Path) -> None:
    (tmp_path / "Fix.ps1").write_bytes(b"Remove-Item C:\\ -Recurse")
    approval = _approved(b"Write-Output hi")
    found = own_scripts.scan(tmp_path, {"fix.ps1": approval})[0]
    assert found.state is State.CHANGED
    assert found.approval == approval  # kept, so the review starts from it
    with pytest.raises(ValueError):
        own_scripts.to_script(found, "DESK-01")


def test_a_big_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "big.cmd").write_bytes(b"x" * (own_scripts.MAX_SIZE + 1))
    assert own_scripts.scan(tmp_path, {})[0].state is State.TOO_BIG


def test_a_file_every_user_may_change_cant_be_approved(tmp_path: Path) -> None:
    script = tmp_path / "open.ps1"
    script.write_bytes(b"x")
    subprocess.run(["icacls", str(script), "/grant", "*S-1-5-32-545:M"], check=True,
                   capture_output=True)  # fmt: skip
    assert winsec.anyone_can_change(script)
    found = own_scripts.scan(tmp_path, {"open.ps1": _approved(b"x")})[0]
    assert found.state is State.OPEN
    assert not found.ready


def test_reading_permissions_only_is_fine(tmp_path: Path) -> None:
    script = tmp_path / "read.ps1"
    script.write_bytes(b"x")
    subprocess.run(["icacls", str(script), "/grant", "*S-1-1-0:RX"], check=True,
                   capture_output=True)  # fmt: skip
    assert not winsec.anyone_can_change(script)


def test_the_script_gets_the_host_then_its_arguments(tmp_path: Path) -> None:
    (tmp_path / "Map.ps1").write_bytes(b"param($h)")
    approval = _approved(b"param($h)", arguments='-Share "\\\\FS01\\Front desk" C:\\Temp')
    found = own_scripts.scan(tmp_path, {"map.ps1": approval})[0]
    script = own_scripts.to_script(found, "DESK-01")
    assert script.arguments == ("DESK-01", "-Share", "\\\\FS01\\Front desk", "C:\\Temp")
    assert script.code == b"param($h)"
    assert script.name == "Map"


def test_an_open_quote_is_an_error() -> None:
    with pytest.raises(ValueError):
        own_scripts.split_arguments('-Name "Front desk')


def test_approvals_survive_the_settings_file() -> None:
    kept = {"fix.ps1": Approval("ab" * 32, True, "-Fast", RunAs.USER, locked=True)}
    saved = own_scripts.approvals_to(kept)
    assert own_scripts.approvals_from(saved) == kept


def test_malformed_approvals_are_left_out() -> None:
    saved = {
        "a.ps1": {"sha256": "x", "risky": "yes", "run_as": "account"},
        "b.ps1": {"sha256": "x", "risky": False, "run_as": "root"},
        "c.ps1": "approved",
        "D.ps1": {"sha256": "x", "risky": False, "run_as": "system"},
    }
    assert list(own_scripts.approvals_from(saved)) == ["d.ps1"]
    assert own_scripts.approvals_from(["a.ps1"]) == {}

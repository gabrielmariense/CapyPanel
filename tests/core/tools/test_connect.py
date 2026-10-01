import json
import logging
import sys
from pathlib import Path

import pytest

from capypanel.core.tools import definitions, vncpass
from capypanel.core.tools.connect import Credential, SessionCredentials, Target, launch

# Stands in for a viewer: records the arguments it received, as the program sees them, and the
# content of a -PasswordFile= it was given (read once, like RealVNC does).
RECORDER = """
import json, sys
args = sys.argv[2:]
read = None
for arg in args:
    if arg.startswith("-PasswordFile="):
        with open(arg.split("=", 1)[1], "rb") as f:
            read = f.read().hex()
open(sys.argv[1], "w", encoding="utf-8").write(json.dumps({"args": args, "file": read}))
"""


def _recording_tool(
    tmp_path: Path, credentials: str = "arguments"
) -> tuple[definitions.ToolDefinition, Path]:
    script = tmp_path / "recorder.py"
    script.write_text(RECORDER, encoding="utf-8")
    out = tmp_path / "received.json"
    secret = (
        [["-password", "{password}"]] if credentials == "arguments"
        else [["-PasswordFile={password_file}"]]
    )  # fmt: skip
    tool = definitions.from_data(
        {
            "schema": 1, "id": "recorder", "name": "Recorder", "kind": "vnc", "port": 5900,
            "credentials": credentials, "options": {"crypto": "Crypto"},
            "arguments": [[str(script), str(out)], ["{address}::{port}"],
                          {"option": "crypto", "arguments": ["-plugin", "crypto.dsm"]},
                          ["-user", "{user}"], *secret],
        }
    )  # fmt: skip
    return tool, out


def _received(out: Path) -> dict[str, object]:
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "password",
    ["plain", "with space", 'quo"te', "back\\slash", 'ends\\with\\"quote\\', "ümlaut€"],
)
def test_the_program_receives_exactly_what_was_typed(tmp_path: Path, password: str) -> None:
    tool, out = _recording_tool(tmp_path)
    process = launch(tool, Path(sys.executable), Target("pc1"), Credential("CORP\\ana", password))
    assert process.wait(30) == 0
    assert _received(out)["args"] == ["pc1::5900", "-user", "CORP\\ana", "-password", password]


def test_a_target_port_overrides_the_tool_s_and_options_add_their_arguments(
    tmp_path: Path,
) -> None:
    tool, out = _recording_tool(tmp_path)
    launch(tool, Path(sys.executable), Target("pc1", 5901), Credential("", "x"), {"crypto"}).wait(
        30
    )
    assert _received(out)["args"] == ["pc1::5901", "-plugin", "crypto.dsm", "-password", "x"]


def test_a_password_file_comes_through_a_pipe_never_the_command_line(tmp_path: Path) -> None:
    tool, out = _recording_tool(tmp_path, "vnc_password_file")
    process = launch(tool, Path(sys.executable), Target("pi1"), Credential("pi", "raspberry"))
    assert process.wait(30) == 0
    received = _received(out)
    args = received["args"]
    assert isinstance(args, list) and "raspberry" not in " ".join(args)
    assert args[-1].startswith(r"-PasswordFile=\\.\pipe\capypanel-")
    assert received["file"] == vncpass.obfuscate("raspberry").hex()
    assert not list(tmp_path.glob("*.vnc"))  # and nothing was written to disk


def test_the_password_never_reaches_the_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    tool, _out = _recording_tool(tmp_path)
    with caplog.at_level(logging.INFO):
        launch(tool, Path(sys.executable), Target("pc1"), Credential("", "hunter2")).wait(30)
    assert "pc1::5900" in caplog.text and "hunter2" not in caplog.text


def test_typed_passwords_are_kept_per_profile_until_forgotten() -> None:
    kept = SessionCredentials()
    assert not kept
    kept.remember("ultravnc-account", Credential("ana", "x"))
    assert kept.get("ultravnc-account") == Credential("ana", "x")
    assert kept.get("realvnc-account") is None  # another profile never gets it
    kept.forget()
    assert not kept and kept.get("ultravnc-account") is None

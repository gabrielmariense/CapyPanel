import json
import logging
import sys
from pathlib import Path

import pytest

from capypanel.core.tools import definitions
from capypanel.core.tools.connect import Credential, SessionCredentials, Target, launch

# Stands in for a viewer: records the arguments it received, as the program sees them.
RECORDER = (
    "import json, sys; open(sys.argv[1], 'w', encoding='utf-8').write(json.dumps(sys.argv[2:]))"
)


def _recording_tool(tmp_path: Path) -> tuple[definitions.ToolDefinition, Path]:
    script = tmp_path / "recorder.py"
    script.write_text(RECORDER, encoding="utf-8")
    out = tmp_path / "received.json"
    tool = definitions.from_data(
        {
            "schema": 1, "id": "recorder", "name": "Recorder", "kind": "vnc", "port": 5900,
            "credentials": "arguments",
            "arguments": [[str(script), str(out)], ["{address}::{port}"],
                          ["-user", "{user}"], ["-password", "{password}"]],
        }
    )  # fmt: skip
    return tool, out


@pytest.mark.parametrize(
    "password",
    ["plain", "with space", 'quo"te', "back\\slash", 'ends\\with\\"quote\\', "ümlaut€"],
)
def test_the_program_receives_exactly_what_was_typed(tmp_path: Path, password: str) -> None:
    tool, out = _recording_tool(tmp_path)
    process = launch(tool, Path(sys.executable), Target("pc1"), Credential("CORP\\ana", password))
    assert process.wait(30) == 0
    received = json.loads(out.read_text(encoding="utf-8"))
    assert received == ["pc1::5900", "-user", "CORP\\ana", "-password", password]


def test_a_target_port_overrides_the_tool_s(tmp_path: Path) -> None:
    tool, out = _recording_tool(tmp_path)
    launch(tool, Path(sys.executable), Target("pc1", 5901), Credential("", "x")).wait(30)
    assert json.loads(out.read_text(encoding="utf-8"))[:3] == ["pc1::5901", "-password", "x"]


def test_the_password_never_reaches_the_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    tool, _out = _recording_tool(tmp_path)
    with caplog.at_level(logging.INFO):
        launch(tool, Path(sys.executable), Target("pc1"), Credential("", "hunter2")).wait(30)
    assert "pc1::5900" in caplog.text and "hunter2" not in caplog.text


def test_typed_passwords_are_kept_per_tool_until_forgotten() -> None:
    kept = SessionCredentials()
    assert not kept
    kept.remember("ultravnc", Credential("", "x"))
    assert kept.get("ultravnc") == Credential("", "x") and kept.get("other") is None
    kept.forget()
    assert not kept and kept.get("ultravnc") is None

from pathlib import Path
from typing import Any

import pytest

from capypanel.core.tools import definitions
from capypanel.core.tools.catalog import SHIPPED_DIR
from capypanel.core.tools.definitions import ToolDefinitionError, command_line, redacted

EXE = Path(r"C:\Tools\viewer.exe")


def _data(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema": 1,
        "id": "viewer",
        "name": "Viewer",
        "kind": "vnc",
        "port": 5900,
        "credentials": "arguments",
        "arguments": [["{address}::{port}"], ["-user", "{user}"], ["-password", "{password}"]],
    }
    return {**base, **changes}


def test_every_shipped_preset_is_valid() -> None:
    presets = sorted(SHIPPED_DIR.glob("*.json"))
    assert presets, "no presets shipped"
    for path in presets:
        tool = definitions.load(path)
        assert path.stem == tool.id  # one file per tool, named after it


def test_groups_with_an_empty_value_are_left_out() -> None:
    tool = definitions.from_data(_data())
    full = {"address": "pc1", "port": "5900", "user": "ana", "password": "s3cret"}
    assert command_line(tool, EXE, full) == [
        str(EXE), "pc1::5900", "-user", "ana", "-password", "s3cret",
    ]  # fmt: skip
    # No user: plain VNC password servers get only -password.
    assert command_line(tool, EXE, {**full, "user": ""}) == [
        str(EXE), "pc1::5900", "-password", "s3cret",
    ]  # fmt: skip


def test_an_address_is_one_argument_never_split_into_more() -> None:
    tool = definitions.from_data(_data())
    argv = command_line(tool, EXE, {"address": "pc1 & calc.exe", "port": "5900", "password": "x"})
    assert argv[1] == "pc1 & calc.exe::5900"


def test_redacted_hides_the_password_everywhere() -> None:
    argv = [str(EXE), "pc::5900", "-password", "s3cret", "--x=s3cret"]
    assert "s3cret" not in " ".join(redacted(argv, ["s3cret"]))


def test_unknown_keys_survive_a_round_trip() -> None:
    tool = definitions.from_data(_data(from_the_future={"x": 1}))
    assert definitions.to_data(tool)["from_the_future"] == {"x": 1}
    assert definitions.from_data(definitions.to_data(tool)) == tool


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"id": "Has Spaces"}, "id"),
        ({"kind": "teleport"}, "kind"),
        ({"schema": 99}, "newer version"),
        ({"arguments": [["{address}", "{hostname}"]], "credentials": "none"}, "placeholder"),
        ({"arguments": [["{address"]], "credentials": "none"}, "Broken placeholder"),
        ({"credentials": "none"}, "arguments"),  # password in the arguments but method "none"
        ({"port": 70000}, "port"),
        ({"arguments": []}, "arguments"),
    ],
)
def test_broken_definitions_say_why(changes: dict[str, Any], reason: str) -> None:
    with pytest.raises(ToolDefinitionError, match=reason):
        definitions.from_data(_data(**changes))

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
        "options": {"crypto": "Encryption plugin"},
        "arguments": [
            ["{address}::{port}"],
            {"option": "crypto", "arguments": ["-plugin", "crypto.dsm"]},
            ["-user", "{user}"],
            ["-password", "{password}"],
        ],
    }
    return {**base, **changes}


def test_every_shipped_preset_is_valid() -> None:
    presets = sorted((SHIPPED_DIR / "tools").glob("*.json"))
    assert {p.stem for p in presets} >= {"ultravnc", "realvnc"}
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


def test_an_option_group_is_used_only_when_the_option_is_on() -> None:
    tool = definitions.from_data(_data())
    values = {"address": "pc1", "port": "5900", "password": "x"}
    assert "-plugin" not in command_line(tool, EXE, values)
    assert command_line(tool, EXE, values, {"crypto"})[2:4] == ["-plugin", "crypto.dsm"]


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


def test_a_password_file_tool_needs_its_placeholder() -> None:
    arguments = [["{address}"], ["-UserName={user}"], ["-PasswordFile={password_file}"]]
    tool = definitions.from_data(
        _data(credentials="vnc_password_file", arguments=arguments, options={})
    )
    assert tool.wants_user and tool.wants_password
    # Its arguments still pass the password on the command line: refused.
    with pytest.raises(ToolDefinitionError, match="placeholder"):
        definitions.from_data(_data(credentials="vnc_password_file"))


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
        ({"options": {}}, "crypto"),  # an option group whose option isn't listed
        ({"options": ["crypto"]}, "options"),
    ],
)
def test_broken_definitions_say_why(changes: dict[str, Any], reason: str) -> None:
    with pytest.raises(ToolDefinitionError, match=reason):
        definitions.from_data(_data(**changes))


def test_account_login_types_and_password_limits_are_read() -> None:
    tool = definitions.from_data(_data(account_types=[113, 118], max_password={"password": 8}))
    assert tool.account_types == (113, 118) and tool.max_password == {"password": 8}
    assert definitions.from_data(definitions.to_data(tool)) == tool
    for broken in ({"account_types": [0]}, {"account_types": "113"}, {"max_password": {"x": 0}}):
        with pytest.raises(ToolDefinitionError):
            definitions.from_data(_data(**broken))


def test_a_settings_file_goes_with_its_placeholder() -> None:
    base = {"schema": 1, "id": "v", "name": "V", "kind": "vnc"}
    tool = definitions.from_data({
        **base, "settings_file": {"extension": ".vnc", "remove": ["host"]},
        "arguments": [["-config", "{settings_file}"], ["{address}"]],
    })  # fmt: skip
    assert tool.settings_file == definitions.SettingsFile(".vnc", ("host",))
    assert definitions.from_data(definitions.to_data(tool)) == tool
    for broken in (
        {"arguments": [["-config", "{settings_file}"], ["{address}"]]},
        {"settings_file": {"extension": ".vnc"}, "arguments": [["{address}"]]},
        {"settings_file": {"extension": "vnc"}, "arguments": [["-config", "{settings_file}"]]},
    ):
        with pytest.raises(definitions.ToolDefinitionError):
            definitions.from_data({**base, **broken})

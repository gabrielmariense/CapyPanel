from typing import Any

import pytest

from capypanel.core.tools import definitions, profiles
from capypanel.core.tools.profile_store import SHIPPED_DIR as PROFILES_DIR
from capypanel.core.tools.profiles import ProfileError

TOOLS_DIR = PROFILES_DIR.parent / "tools"


def _tool(tool_id: str) -> definitions.ToolDefinition:
    return definitions.load(TOOLS_DIR / f"{tool_id}.json")


def test_one_built_in_profile_per_tool_and_each_fits_its_tool() -> None:
    paths = sorted(PROFILES_DIR.glob("*.json"))
    assert {p.stem for p in paths} == {p.stem for p in TOOLS_DIR.glob("*.json")}
    for path in paths:
        profile = profiles.load(path)
        assert path.stem == profile.id and profile.name
        profiles.check_fits(profile, _tool(profile.tool))


def test_a_tool_offers_only_the_logins_it_supports() -> None:
    assert profiles.logins_of(_tool("ultravnc")) == ("account", "password")
    no_user = definitions.from_data(
        {"schema": 1, "id": "t", "name": "T", "kind": "vnc", "credentials": "arguments",
         "arguments": [["{address}"], ["{password}"]]}
    )  # fmt: skip
    assert profiles.logins_of(no_user) == ("password",)
    no_password = definitions.from_data(
        {"schema": 1, "id": "t", "name": "T", "kind": "vnc", "arguments": [["{address}"]]}
    )
    assert profiles.logins_of(no_password) == ("none",)


def test_a_profile_that_asks_too_much_of_its_tool_is_refused() -> None:
    plugin_on_realvnc = profiles.from_data(
        {"schema": 1, "id": "x", "name": "X", "tool": "realvnc", "options": ["securevnc"]}
    )
    with pytest.raises(ProfileError, match="securevnc"):
        profiles.check_fits(plugin_on_realvnc, _tool("realvnc"))


def test_unknown_keys_survive_a_round_trip() -> None:
    data = {"schema": 1, "id": "x", "name": "X", "tool": "ultravnc", "login": "account",
            "later": [1]}  # fmt: skip
    profile = profiles.from_data(data)
    assert profiles.to_data(profile)["later"] == [1]
    assert profiles.from_data(profiles.to_data(profile)) == profile


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"id": "No Spaces"}, "id"),
        ({"tool": ""}, "tool"),
        ({"name": " "}, "name"),
        ({"login": "fingerprint"}, "login"),
        ({"options": "securevnc"}, "options"),
        ({"port": 0}, "port"),
        ({"schema": 2}, "newer version"),
    ],
)
def test_broken_profiles_say_why(changes: dict[str, Any], reason: str) -> None:
    with pytest.raises(ProfileError, match=reason):
        profiles.from_data({"schema": 1, "id": "x", "name": "X", "tool": "ultravnc", **changes})

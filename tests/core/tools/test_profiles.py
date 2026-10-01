from typing import Any

import pytest

from capypanel.core.tools import definitions, profiles
from capypanel.core.tools.catalog import SHIPPED_DIR
from capypanel.core.tools.profiles import ProfileError


def _tool(tool_id: str) -> definitions.ToolDefinition:
    return definitions.load(SHIPPED_DIR / "tools" / f"{tool_id}.json")


def test_every_shipped_profile_is_valid_and_fits_its_tool() -> None:
    paths = sorted((SHIPPED_DIR / "profiles").glob("*.json"))
    assert {p.stem for p in paths} == {
        "ultravnc-password", "ultravnc-account", "ultravnc-password-securevnc",
        "ultravnc-account-securevnc", "realvnc-password", "realvnc-account",
    }  # fmt: skip
    for path in paths:
        profile = profiles.load(path)
        assert path.stem == profile.id
        profiles.check_fits(profile, _tool(profile.tool))


def test_a_profile_without_a_name_is_named_after_what_it_does() -> None:
    profile = profiles.load(SHIPPED_DIR / "profiles" / "ultravnc-account-securevnc.json")
    assert (
        profiles.label(profile, _tool("ultravnc"))
        == "UltraVNC Viewer — user and password + SecureVNC plugin"
    )
    named = profiles.from_data({"schema": 1, "id": "x", "tool": "ultravnc", "name": "Clinic"})
    assert profiles.label(named, _tool("ultravnc")) == "Clinic"


def test_a_profile_that_asks_too_much_of_its_tool_is_refused() -> None:
    plugin_on_realvnc = profiles.from_data(
        {"schema": 1, "id": "x", "tool": "realvnc", "options": ["securevnc"]}
    )
    with pytest.raises(ProfileError, match="securevnc"):
        profiles.check_fits(plugin_on_realvnc, _tool("realvnc"))


def test_unknown_keys_survive_a_round_trip() -> None:
    data = {"schema": 1, "id": "x", "tool": "ultravnc", "login": "account", "later": [1]}
    profile = profiles.from_data(data)
    assert profiles.to_data(profile)["later"] == [1]
    assert profiles.from_data(profiles.to_data(profile)) == profile


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"id": "No Spaces"}, "id"),
        ({"tool": ""}, "tool"),
        ({"login": "fingerprint"}, "login"),
        ({"options": "securevnc"}, "options"),
        ({"port": 0}, "port"),
        ({"schema": 2}, "newer version"),
    ],
)
def test_broken_profiles_say_why(changes: dict[str, Any], reason: str) -> None:
    with pytest.raises(ProfileError, match=reason):
        profiles.from_data({"schema": 1, "id": "x", "tool": "ultravnc", **changes})

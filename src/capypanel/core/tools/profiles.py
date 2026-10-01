"""A connection profile: one way to reach a kind of host. Hosts and groups refer to it by id, so
changing a profile changes every host that uses it. One JSON file per profile:

    {"schema": 1, "id": "ultravnc-account-securevnc", "tool": "ultravnc",
     "login": "account", "options": ["securevnc"]}

`login` says what the prompt asks for: "account" (user and password), "password" or "none".
A typed password is remembered per profile, so one profile's password never reaches another's
hosts. `name` is optional: without it the name is built from the tool, login and options."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from capypanel.core.i18n import _
from capypanel.core.tools.definitions import ToolDefinition

SCHEMA = 1
LOGINS = ("account", "password", "none")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_KEYS = ("schema", "id", "name", "tool", "login", "options", "port")


class ProfileError(ValueError):
    """A profile file is broken, or doesn't fit its tool; the message says what's wrong."""


@dataclass(frozen=True)
class ConnectionProfile:
    id: str
    tool: str
    login: str = "password"
    options: tuple[str, ...] = ()
    port: int | None = None  # None: the tool's port
    name: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)


def login_label(login: str) -> str:
    return {
        "account": _("user and password"),
        "password": _("password only"),
        "none": _("no password"),
    }.get(login, login)


def label(profile: ConnectionProfile, tool: ToolDefinition | None) -> str:
    """The name shown: the profile's own, else e.g. "UltraVNC Viewer — password only"."""
    if profile.name:
        return profile.name
    if tool is None:
        return profile.id
    text = f"{tool.name} — {login_label(profile.login)}"
    for option in profile.options:
        text += f" + {tool.options.get(option, option)}"
    return text


def check_fits(profile: ConnectionProfile, tool: ToolDefinition) -> None:
    """Raises ProfileError when the profile asks for something its tool can't do."""
    for option in profile.options:
        if option not in tool.options:
            raise ProfileError(
                _("{tool} has no option “{option}”.").format(tool=tool.name, option=option)
            )
    if profile.login != "none" and not tool.wants_password:
        raise ProfileError(_("{tool} can't be given a password.").format(tool=tool.name))
    if profile.login == "account" and not tool.wants_user:
        raise ProfileError(_("{tool} can't be given a user name.").format(tool=tool.name))


# ---- JSON <-> records ----


def load(path: Path) -> ConnectionProfile:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise ProfileError(
            _("Couldn't read “{file}”: {error}").format(file=path.name, error=e)
        ) from e
    return from_data(data)


def from_data(data: object) -> ConnectionProfile:
    if not isinstance(data, dict):
        raise ProfileError(_("A connection profile must be a JSON object."))
    if not isinstance(data.get("schema"), int) or data["schema"] > SCHEMA:
        raise ProfileError(_("This connection profile needs a newer version of CapyPanel."))
    profile_id, tool = data.get("id"), data.get("tool")
    for key, value in (("id", profile_id), ("tool", tool)):
        if not isinstance(value, str) or not _ID.match(value):
            raise ProfileError(
                _("The profile's “{key}” must be lowercase letters, digits, - or _.").format(
                    key=key
                )
            )
    login = data.get("login", "password")
    if login not in LOGINS:
        raise ProfileError(_("Unknown login “{login}”.").format(login=login))
    options = data.get("options", [])
    if not isinstance(options, list) or not all(isinstance(o, str) for o in options):
        raise ProfileError(_("The profile's “options” must be a list of option ids."))
    port = data.get("port")
    if port is not None and (not isinstance(port, int) or not 1 <= port <= 65535):
        raise ProfileError(_("The “port” must be a number from 1 to 65535."))
    name = data.get("name", "")
    if not isinstance(name, str):
        raise ProfileError(_("The profile's “name” must be a text."))
    assert isinstance(profile_id, str) and isinstance(tool, str)
    return ConnectionProfile(
        id=profile_id,
        tool=tool,
        login=login,
        options=tuple(options),
        port=port,
        name=name.strip(),
        extra={k: v for k, v in data.items() if k not in _KEYS},
    )


def to_data(profile: ConnectionProfile) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema": SCHEMA,
        "id": profile.id,
        "tool": profile.tool,
        "login": profile.login,
    }
    if profile.name:
        data["name"] = profile.name
    if profile.options:
        data["options"] = list(profile.options)
    if profile.port is not None:
        data["port"] = profile.port
    return {**profile.extra, **data}

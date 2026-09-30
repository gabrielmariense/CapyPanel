"""A tool definition: how to find and start one external program. One JSON file per tool:

    {"schema": 1, "id": "ultravnc", "name": "UltraVNC Viewer", "kind": "vnc", "port": 5900,
     "credentials": "arguments",
     "arguments": [["{address}::{port}"], ["-user", "{user}"], ["-password", "{password}"]],
     "detect": {"installed_as": ["UltraVNC"], "exe": "vncviewer.exe", "paths": ["..."]}}

`arguments` is a list of groups. A group is left out when any placeholder in it is empty, so
one template serves servers that want a user name and servers that don't."""

import json
import re
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from capypanel.core.i18n import _

SCHEMA = 1
KINDS = ("vnc",)  # grows with the features: rdp, ssh…
PLACEHOLDERS = ("address", "port", "user", "password")
CREDENTIALS = ("none", "arguments")  # how the tool gets the password; more methods later
SECRET = "password"
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class ToolDefinitionError(ValueError):
    """A tool definition file is broken; the message says what's wrong."""


@dataclass(frozen=True)
class Detect:
    installed_as: tuple[str, ...] = ()  # names in Windows' list of installed programs
    exe: str = ""  # file name inside the install folder
    paths: tuple[str, ...] = ()  # usual full paths; %ProgramFiles% and the like are expanded


@dataclass(frozen=True)
class ToolDefinition:
    id: str
    name: str
    kind: str
    arguments: tuple[tuple[str, ...], ...]
    credentials: str = "none"
    port: int | None = None
    executable: str = ""  # set by the user; empty means "find it"
    detect: Detect = field(default_factory=Detect)
    extra: Mapping[str, Any] = field(default_factory=dict)  # keys from newer versions, kept

    @property
    def wants_user(self) -> bool:
        return any("{user}" in arg for group in self.arguments for arg in group)


def command_line(tool: ToolDefinition, executable: Path, values: Mapping[str, str]) -> list[str]:
    """The exact argument list for one launch. Never a shell string: an address can't turn
    into a command. Groups with an empty placeholder are dropped."""
    argv = [str(executable)]
    for group in tool.arguments:
        needed = {name for arg in group for name in _names(arg)}
        if all(values.get(name) for name in needed):
            argv.extend(arg.format_map(values) for arg in group)
    return argv


def redacted(argv: Sequence[str], secrets: Sequence[str]) -> list[str]:
    """The argument list with secrets replaced, for logs and error messages."""
    hidden = [s for s in secrets if s]
    out = []
    for arg in argv:
        for secret in hidden:
            arg = arg.replace(secret, "********")
        out.append(arg)
    return out


# ---- JSON <-> records ----

_KEYS = ("schema", "id", "name", "kind", "arguments", "credentials", "port", "executable", "detect")


def load(path: Path) -> ToolDefinition:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise ToolDefinitionError(
            _("Couldn't read “{file}”: {error}").format(file=path.name, error=e)
        ) from e
    return from_data(data)


def from_data(data: object) -> ToolDefinition:
    if not isinstance(data, dict):
        raise ToolDefinitionError(_("A tool definition must be a JSON object."))
    if not isinstance(data.get("schema"), int) or data["schema"] > SCHEMA:
        raise ToolDefinitionError(_("This tool definition needs a newer version of CapyPanel."))
    tool_id, name, kind = data.get("id"), data.get("name"), data.get("kind")
    if not isinstance(tool_id, str) or not _ID.match(tool_id):
        raise ToolDefinitionError(_("The tool's “id” must be lowercase letters, digits, - or _."))
    if not isinstance(name, str) or not name.strip():
        raise ToolDefinitionError(_("The tool needs a “name”."))
    if kind not in KINDS:
        raise ToolDefinitionError(_("Unknown tool kind “{kind}”.").format(kind=kind))
    arguments = _arguments(data.get("arguments"))
    credentials = data.get("credentials", "none")
    if credentials not in CREDENTIALS:
        raise ToolDefinitionError(
            _("Unknown credential method “{method}”.").format(method=credentials)
        )
    uses_password = any("{password}" in arg for group in arguments for arg in group)
    if (credentials == "arguments") != uses_password:
        raise ToolDefinitionError(
            _("A tool gets the password in its arguments only with the “arguments” method.")
        )
    port = data.get("port")
    if port is not None and (not isinstance(port, int) or not 1 <= port <= 65535):
        raise ToolDefinitionError(_("The “port” must be a number from 1 to 65535."))
    executable = data.get("executable", "")
    if not isinstance(executable, str):
        raise ToolDefinitionError(_("The “executable” must be a path."))
    return ToolDefinition(
        id=tool_id,
        name=name.strip(),
        kind=kind,
        arguments=arguments,
        credentials=credentials,
        port=port,
        executable=executable,
        detect=_detect(data.get("detect", {})),
        extra={k: v for k, v in data.items() if k not in _KEYS},
    )


def to_data(tool: ToolDefinition) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema": SCHEMA,
        "id": tool.id,
        "name": tool.name,
        "kind": tool.kind,
        "arguments": [list(group) for group in tool.arguments],
        "credentials": tool.credentials,
    }
    if tool.port is not None:
        data["port"] = tool.port
    if tool.executable:
        data["executable"] = tool.executable
    d = tool.detect
    if d.installed_as or d.exe or d.paths:
        data["detect"] = {
            "installed_as": list(d.installed_as),
            "exe": d.exe,
            "paths": list(d.paths),
        }
    return {**tool.extra, **data}


def _arguments(value: object) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, list) or not value:
        raise ToolDefinitionError(_("The tool needs “arguments”: a list of groups."))
    groups = []
    for group in value:
        if not isinstance(group, list) or not group or not all(isinstance(a, str) for a in group):
            raise ToolDefinitionError(_("Each argument group must be a list of texts."))
        for arg in group:
            for name in _names(arg):
                if name not in PLACEHOLDERS:
                    raise ToolDefinitionError(
                        _("Unknown placeholder “{{{name}}}” in the arguments.").format(name=name)
                    )
        groups.append(tuple(group))
    return tuple(groups)


def _names(arg: str) -> list[str]:
    try:
        return [name for _text, name, _spec, _conv in string.Formatter().parse(arg) if name]
    except ValueError as e:  # an unpaired "{" or "}"
        raise ToolDefinitionError(_("Broken placeholder in “{arg}”.").format(arg=arg)) from e


def _detect(value: object) -> Detect:
    if not isinstance(value, dict):
        raise ToolDefinitionError(_("“detect” must be an object."))
    installed_as, exe, paths = (
        value.get("installed_as", []),
        value.get("exe", ""),
        value.get("paths", []),
    )
    if not (
        isinstance(installed_as, list)
        and all(isinstance(n, str) for n in installed_as)
        and isinstance(exe, str)
        and isinstance(paths, list)
        and all(isinstance(p, str) for p in paths)
    ):
        raise ToolDefinitionError(_("“detect” has a value of the wrong type."))
    return Detect(tuple(installed_as), exe, tuple(paths))

"""A tool definition: how to find and start one external program. One JSON file per tool:

    {"schema": 1, "id": "ultravnc", "name": "UltraVNC Viewer", "kind": "vnc", "port": 5900,
     "credentials": "arguments",
     "options": {"securevnc": "SecureVNC plugin"},
     "arguments": [["{address}::{port}"],
                   {"option": "securevnc", "arguments": ["-dsmplugin", "SecureVNCPlugin64.dsm"]},
                   ["-user", "{user}"], ["-password", "{password}"]],
     "detect": {"installed_as": ["UltraVNC"], "exe": "vncviewer.exe", "paths": ["..."]}}

`arguments` is a list of groups. A group is left out when any placeholder in it is empty, so
one template serves servers that want a user name and servers that don't. A group tied to an
option is used only when the connection profile switches that option on.

A tool that reads a settings file (UltraVNC's -config) describes it with "settings_file": its
extension and the settings that name a computer, emptied ("clear"); see viewer_settings.
"website" is where the tool can be downloaded."""

import json
import re
import string
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from capypanel.core.i18n import _

SCHEMA = 1
KINDS = ("vnc", "rdp")  # grows with the features: ssh…
PLACEHOLDERS = ("address", "port", "user", "password", "password_file", "settings_file")
SECRET = "password"
PASSWORD_FILE = "password_file"
SETTINGS_FILE = "settings_file"
# How the tool gets the password: none, on its command line, or as a VNC password file that
# is really a private pipe (nothing on disk; see pipe.py). Each needs its own placeholder.
CREDENTIALS = {"none": None, "arguments": SECRET, "vnc_password_file": PASSWORD_FILE}
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_EXTENSION = re.compile(r"^\.[a-z0-9]{1,8}$")


class ToolDefinitionError(ValueError):
    """A tool definition file is broken; the message says what's wrong."""


@dataclass(frozen=True)
class Detect:
    installed_as: tuple[str, ...] = ()  # names in Windows' list of installed programs
    exe: str = ""  # file name inside the install folder
    paths: tuple[str, ...] = ()  # usual full paths; %ProgramFiles% and the like are expanded


@dataclass(frozen=True)
class SettingsFile:
    extension: str  # ".vnc"
    clear: tuple[str, ...] = ()  # emptied: they name the computer the file was saved for


@dataclass(frozen=True)
class ArgumentGroup:
    arguments: tuple[str, ...]
    option: str | None = None  # used only when a profile turns this option on


@dataclass(frozen=True)
class ToolDefinition:
    id: str
    name: str
    kind: str
    arguments: tuple[ArgumentGroup, ...]
    credentials: str = "none"
    port: int | None = None
    options: Mapping[str, str] = field(default_factory=dict)  # option id -> name shown
    # VNC login types (RFB security types) that ask for a user and password. When set, an
    # account profile first checks the server offers one, so a Windows password never goes to
    # a server that only wants a VNC password.
    account_types: tuple[int, ...] = ()
    max_password: Mapping[str, int] = field(default_factory=dict)  # login -> longest password
    settings_file: SettingsFile | None = None  # the tool reads a settings file a profile can carry
    website: str = ""  # where to download it
    executable: str = ""  # set by the user; empty means "find it"
    detect: Detect = field(default_factory=Detect)
    extra: Mapping[str, Any] = field(default_factory=dict)  # keys from newer versions, kept

    @property
    def wants_user(self) -> bool:
        return self._uses("user")

    @property
    def wants_password(self) -> bool:
        return self.credentials != "none"

    def _uses(self, name: str) -> bool:
        return any(name in _names(arg) for group in self.arguments for arg in group.arguments)


def command_line(
    tool: ToolDefinition,
    executable: Path,
    values: Mapping[str, str],
    options: Collection[str] = (),
) -> list[str]:
    """The exact argument list for one launch. Never a shell string: an address can't turn
    into a command. Groups with an empty placeholder or an option that's off are dropped."""
    argv = [str(executable)]
    for group in tool.arguments:
        if group.option is not None and group.option not in options:
            continue
        needed = {name for arg in group.arguments for name in _names(arg)}
        if all(values.get(name) for name in needed):
            argv.extend(arg.format_map(values) for arg in group.arguments)
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

_KEYS = (
    "schema", "id", "name", "kind", "arguments", "credentials", "port", "options", "executable",
    "detect", "account_types", "max_password", "settings_file", "website",
)  # fmt: skip


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
    options = _options(data.get("options", {}))
    arguments = _arguments(data.get("arguments"), options)
    credentials = data.get("credentials", "none")
    if credentials not in CREDENTIALS:
        raise ToolDefinitionError(
            _("Unknown credential method “{method}”.").format(method=credentials)
        )
    used = {n for g in arguments for arg in g.arguments for n in _names(arg)}
    for method, placeholder in CREDENTIALS.items():
        if placeholder and (placeholder in used) != (credentials == method):
            raise ToolDefinitionError(
                _(
                    "The placeholder “{{{name}}}” goes with the “{method}” credential method."
                ).format(name=placeholder, method=method)
            )
    settings_file = _settings_file(data.get("settings_file"))
    if (SETTINGS_FILE in used) != (settings_file is not None):
        raise ToolDefinitionError(
            _("The placeholder “{{{name}}}” goes with “settings_file”.").format(name=SETTINGS_FILE)
        )
    port = data.get("port")
    if port is not None and (not isinstance(port, int) or not 1 <= port <= 65535):
        raise ToolDefinitionError(_("The “port” must be a number from 1 to 65535."))
    executable = data.get("executable", "")
    if not isinstance(executable, str):
        raise ToolDefinitionError(_("The “executable” must be a path."))
    website = data.get("website", "")
    if not isinstance(website, str) or (website and not website.startswith("https://")):
        raise ToolDefinitionError(_("The “website” must be an https:// address."))
    return ToolDefinition(
        id=tool_id,
        name=name.strip(),
        kind=kind,
        arguments=arguments,
        credentials=credentials,
        port=port,
        options=options,
        executable=executable,
        detect=_detect(data.get("detect", {})),
        account_types=_account_types(data.get("account_types", [])),
        max_password=_max_password(data.get("max_password", {})),
        settings_file=settings_file,
        website=website,
        extra={k: v for k, v in data.items() if k not in _KEYS},
    )


def to_data(tool: ToolDefinition) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema": SCHEMA,
        "id": tool.id,
        "name": tool.name,
        "kind": tool.kind,
        "arguments": [
            list(g.arguments) if g.option is None
            else {"option": g.option, "arguments": list(g.arguments)}
            for g in tool.arguments
        ],
        "credentials": tool.credentials,
    }  # fmt: skip
    if tool.port is not None:
        data["port"] = tool.port
    if tool.options:
        data["options"] = dict(tool.options)
    if tool.account_types:
        data["account_types"] = list(tool.account_types)
    if tool.max_password:
        data["max_password"] = dict(tool.max_password)
    if tool.settings_file is not None:
        sf = tool.settings_file
        data["settings_file"] = {"extension": sf.extension, "clear": list(sf.clear)}
    if tool.website:
        data["website"] = tool.website
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


def _account_types(value: object) -> tuple[int, ...]:
    if not isinstance(value, list) or not all(
        isinstance(t, int) and not isinstance(t, bool) and 0 < t < 256 for t in value
    ):
        raise ToolDefinitionError(_("“account_types” must be a list of numbers from 1 to 255."))
    return tuple(value)


def _settings_file(value: object) -> SettingsFile | None:
    if value is None:
        return None
    extension = value.get("extension") if isinstance(value, dict) else None
    clear = value.get("clear", []) if isinstance(value, dict) else None
    if not (
        isinstance(extension, str)
        and _EXTENSION.match(extension)
        and isinstance(clear, list)
        and all(isinstance(k, str) and k.strip() for k in clear)
    ):
        raise ToolDefinitionError(
            _("“settings_file” needs an “extension” such as “.vnc” and a list to “clear”.")
        )
    return SettingsFile(extension, tuple(k.strip() for k in clear))


def _max_password(value: object) -> dict[str, int]:
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v > 0
        for k, v in value.items()
    ):
        raise ToolDefinitionError(_("“max_password” must map logins to a length."))
    return dict(value)


def _options(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and _ID.match(k) and isinstance(v, str) and v.strip()
        for k, v in value.items()
    ):
        raise ToolDefinitionError(_("“options” must map option ids to the names shown."))
    return {k: v.strip() for k, v in value.items()}


def _arguments(value: object, options: Mapping[str, str]) -> tuple[ArgumentGroup, ...]:
    if not isinstance(value, list) or not value:
        raise ToolDefinitionError(_("The tool needs “arguments”: a list of groups."))
    groups = []
    for item in value:
        option = None
        if isinstance(item, dict):
            option, item = item.get("option"), item.get("arguments")
            if option not in options:
                raise ToolDefinitionError(
                    _(
                        "The arguments use an option that “options” doesn't list: “{option}”."
                    ).format(option=option)
                )
        if not isinstance(item, list) or not item or not all(isinstance(a, str) for a in item):
            raise ToolDefinitionError(_("Each argument group must be a list of texts."))
        for arg in item:
            for name in _names(arg):
                if name not in PLACEHOLDERS:
                    raise ToolDefinitionError(
                        _("Unknown placeholder “{{{name}}}” in the arguments.").format(name=name)
                    )
        groups.append(ArgumentGroup(tuple(item), option))
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

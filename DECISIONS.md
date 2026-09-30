# CapyPanel — project decisions

This is the reference for anyone working on the project. It describes what the app is and everything decided so far about how it works. If something isn't here, it hasn't been decided yet. Ask the maintainer before assuming. Last updated 2026-09-29.

---

## 1. What the app is

**CapyPanel** is a desktop app for IT staff to manage the computers on their network from one window:

- keep an organized list of machines;
- open remote connections to them;
- see what's going on on each one (who is logged on, printers, status);
- act on one or many at once (restart, run scripts, clean user profiles).

**Who it's for.** Any company or IT team. It's a public project, multilingual, with no features tied to one specific organization.

**Platforms.**
- **Where the app runs:** Windows 10 22H2 and Windows 11, tested mainly on 11. It ships as a packaged app, so users never install Python.
- **macOS:** not a supported client. The code is kept portable (§9) so a Mac version stays possible later, but nothing is built or tested for it now.
- **What the app manages:** Windows hosts, plus anything reachable over SSH (Linux servers, Macs).

**Architecture.** A personal desktop app. Each user runs their own copy. There is no server, no user accounts and no roles. Anything that needs to be shared between people (a host list, a baseline configuration) is shared as a file.

**How it grows.** Development starts at version 0.1 and adds one feature at a time. The first public release is planned around 0.8 or 1.0.

---

## 2. Rules that apply to every feature

1. **Built for any organization.** A feature or request is accepted only if it works for teams with different machines, networks, setups and languages. Nothing is hardcoded to one environment.
2. **Nothing is left accumulating on target machines.** Results should come back through the transport's own output channel (§7). Where a transport cannot return them directly — notably PsExec, whose output relay is capped at ~256 bytes (§7, backend prototype) — the app may write **one temporary result file** on the target and read it back, but it **deletes that file immediately after reading and sweeps any orphans**, so nothing accumulates; it never stages scripts or leaves persistent files. (Revised 2026-09-29: the earlier "never writes any file on a target" was relaxed to this, because PsExec cannot otherwise return output; the goal is no trash on the PCs, not zero temp files.) Tools' own self-cleaning temp mechanisms are also fine: PsExec installs its PSEXESVC service while it runs and removes it afterwards, and PowerShell's `Add-Type` compiles small helpers in a temp folder that it cleans up. The app may also require prerequisites on the client or the targets (WinRM enabled, permissions, an installed tool), and it tells the user what's missing (the prerequisite checker in §7).
3. **User data is never overwritten by the app.** What the user typed and what the app detected are stored separately (see §5). A refresh, update or reload never replaces user data. A shared file changed by someone else is never silently overwritten.
4. **Credentials are never typed into another program's window.** No simulated keystrokes into viewers or dialogs. Each external tool receives credentials only through a mechanism it supports officially.
5. **Credentials never touch disk in plain text.** Before OS keychain support exists, a typed password lives only in memory until the app closes.
6. **Third-party tools are launched, never bundled.** Remote viewers, RDP clients, SSH clients and similar tools are programs the user already has installed. The app finds and launches them and never ships or redistributes them.
7. **Destructive actions ask for confirmation.** This covers restart, shut down, log off and profile cleaning. The confirmation dialog is the safeguard against a misclick, the same in every theme. It names the action and the hosts it applies to, and Cancel is the default button, so Enter or a stray click never confirms.
8. **Themes change only the look, never what the app does.**
   - A theme may change colours, fonts, spacing and layout details, like how a status is drawn or where a label sits.
   - A theme never adds, removes or needs its own windows, dialogs, features or controls. There's no theme-only feature and no feature that works differently in one theme.
   - Every menu, shortcut, piece of information and confirmation is the same in every theme, and nothing may depend on a colour.

---

## 3. Terms used in this document

| Term | Meaning |
|---|---|
| Host | One managed machine: a PC, laptop, server or Mac. |
| Host list | A file containing hosts, groups and tags. The app has one host list open at a time. |
| Group | A folder that organizes hosts. Groups can be nested. Every host is in exactly one group. |
| Tag | A free label on a host (e.g. `floor-3`, `kiosk`). A host can have any number of tags. |
| Remote tool | An external program used to connect to a host: a VNC viewer, RDP client, SSH terminal, AnyDesk-style tool, etc. |
| Tool definition | The app's description of one remote tool: how to find it, how to launch it and how to pass credentials (§6). |
| Preset | A tool definition that ships with the app. Users can add their own definitions next to the presets. |
| Connection profile | A named set of connection settings (default connection, remote tool, port) that a new host copies when it's added (§6). One file per profile. |
| Transport | How the app itself talks to a host to run commands and read data: WinRM, SSH or PsExec. |
| Job | An operation the app runs on one or more hosts, shown with per-host progress and results. |
| Baseline | A settings file a company distributes so every user starts from the same configuration. |

---

## 4. User interface

The layout, menus and panels below were approved from mockups. Target versions follow §8. An item whose feature isn't built yet stays hidden until that feature ships.

**Conventions used everywhere in the UI**
- An item ending in `…` opens a dialog before doing anything.
- Destructive items (restart, shut down, log off, clean profiles) always ask for confirmation (rule 7). A theme may also show them in red, but nothing relies on the colour (rule 8).
- Actions work on the **selected hosts**: one or many. Anything that runs on more than one host becomes a job (§4.5).

### 4.1 Main window layout

From top to bottom:

1. **Menu bar:** File, Inventory, Connect, Inspect, Actions, Tools, View, Help (§4.3).
2. **Toolbar** (§4.2).
3. **Three panes:**
   - **Left: groups.** A tree of groups with the number of hosts in each, plus "All computers" at the top. The header has `+` (add group) and a `⋮` menu. Tags are listed below the tree with their counts. Clicking a group or tag filters the table.
   - **Center: host table.** Columns: Computer (with an online/offline dot), Status, User (logged-on user), OS, Transport, Last seen. Click a header to sort.
   - **Right: details of the selected host.** It has three sections:
     - **Information:** IP, logged-on user with session type (e.g. console), OS, uptime, transport with its port (e.g. WinRM · HTTPS 5986). Memory and disk figures join it when detailed system info ships (after 1.0).
     - **Tags:** the host's tags, with "+ add".
     - **History on this host:** the latest actions from the audit log, with date, action and result (ok / failed).
4. **Jobs panel** (optional, bottom; §4.5).
5. **Status bar:**
   - on the left: the open list (kind and path), host count, online count, selected count;
   - on the right: the number of hosts per transport (e.g. `WinRM: 8 · PsExec: 2 · SSH: 2`).

The Transport column, the transport line in Information and the per-transport counts stay hidden until the first command transport ships (0.1 has none, §7).

### 4.2 Toolbar

Buttons are grouped by category, each group with a small label and separated by dividers.

| Group | Button | What it does | Target |
|---|---|---|---|
| Connect | VNC | Opens the remote screen of the selected host in the external VNC viewer | 0.1 |
| Connect | RDP | Opens the system RDP client to the selected host (in 0.1 the client asks for the password itself) | 0.1 |
| Connect | SSH | Opens an SSH session in an external terminal | 1.0 |
| Inspect | Users | Logged-on users and sessions of the selected hosts | 0.1 |
| Inspect | Information | Information about the selected host: basic facts by 1.0, detailed system info after 1.0 | 1.0 |
| Actions | Run script | Opens the script runner for the selected hosts | 1.0 |
| Actions | Power ▾ | Dropdown with Restart…, Shut down…, Log off user… (all confirmed) | 1.0 |
| — | Refresh | Refreshes online status and detected facts of the hosts in view | 1.0 |

On the right side of the toolbar:
- **Search box:** searches by host, user, IP or tag.
- **Status filter:** a dropdown whose default is "All statuses".
- **Jobs button:** a badge shows how many jobs are running, and clicking it opens the Jobs panel.

### 4.3 Menu bar

**File**
| Item | Shortcut | What it does | Target |
|---|---|---|---|
| New host list… | | Creates an empty host list file | 0.1 |
| Open host list… | Ctrl+O | Opens a host list file | 0.1 |
| Recent lists ▸ | | Recently opened lists, each shown with its kind and path (e.g. "Personal — Documents\…\hosts.json", "Shared — \\\\server\share\hosts.json", "Default — app folder"). The open one is checked | 0.1 |
| Import hosts (CSV)… | | Adds hosts from a CSV file | 1.0 |
| Export hosts (CSV)… | | Saves hosts to a CSV file | 1.0 |
| Settings… | Ctrl+, | Opens the Settings window (§4.6) | 0.1 |
| Exit | Ctrl+Q | Closes the app | 0.1 |

**Inventory**
| Item | Shortcut | What it does | Target |
|---|---|---|---|
| Add host… | Ctrl+N | New host | 0.1 |
| Add group… | Ctrl+Shift+N | New group (inside the selected one, if any) | 0.1 |
| Edit selected… | F2 | Host or group properties, including its connection settings | 0.1 |
| Remove selected | Del | Removes the selected hosts or group | 0.1 |
| Move to group ▸ | | Moves the selected hosts to another group | 1.0 |
| Tags ▸ | | Adds or removes tags on the selected hosts | 1.0 |
| Refresh status | F5 | Same as the toolbar's Refresh | 1.0 |
| Check prerequisites… | | Runs the prerequisite checker (§7) on the selected hosts | 1.0 |

**Connect**
| Item | Shortcut | What it does | Target |
|---|---|---|---|
| Connect (host default) | Enter | Opens the host's default connection, the same as double-click (§6) | 0.1 |
| Remote screen (VNC) | | Always VNC, whatever the default | 0.1 |
| Remote desktop (RDP) | Ctrl+Enter | Always RDP | 0.1 |
| SSH terminal | Ctrl+T | Always SSH | 1.0 |
| Manual connection… | Ctrl+M | Connects to an address typed on the spot, without adding it to the list | 0.1 |
| Copy IP | Ctrl+Shift+C | Copies the host's IP | 0.1 |
| Copy name | | Copies the host's name | 0.1 |

**Inspect**
| Item | Shortcut | What it does | Target |
|---|---|---|---|
| Logged-on users | Ctrl+U | Who is logged on and their sessions | 0.1 |
| System information | Ctrl+I | Host information (see Information in §4.2) | 1.0 |
| Printers | | Printers installed on the host | 1.0 |
| Installed software | | Installed programs | Optional for 1.0 |
| Services and processes | | Services and processes, with start/stop and end process | Optional for 1.0 |

**Actions**
| Item | Shortcut | What it does | Target |
|---|---|---|---|
| Run script… | Ctrl+R | Picks a script from the library and runs it on the selected hosts | 1.0 |
| Run command… | Ctrl+Shift+R | Runs a one-off command on the selected hosts | 1.0 |
| Restart… | | Restarts the selected hosts (confirmed) | 1.0 |
| Shut down… | | Shuts down the selected hosts (confirmed) | 1.0 |
| Log off user… | | Logs off the user on the selected hosts (confirmed) | 1.0 |
| Clean profiles… | | Opens the profile cleaner for the selected hosts (confirmed) | 1.0 |
| Send message to user… | | Shows a message to whoever is logged on | Optional for 1.0 |

**Tools**
| Item | Shortcut | What it does | Target |
|---|---|---|---|
| Script library… | | Manages the saved scripts used by Run script | 1.0 |
| Credentials… | | Manages credential profiles stored in the OS keychain | 1.0 |
| SSH host keys… | | Shows the trusted SSH host keys, and removes or re-trusts them | 1.0 |
| Jobs | Ctrl+J | Shows or hides the Jobs panel | 1.0 |
| Audit log… | Ctrl+L | Opens the full local audit log | 1.0 |

**View**
| Item | What it does | Target |
|---|---|---|
| Toolbar / Groups pane / Details pane / Jobs panel / Status bar | Shows or hides each part of the window (checked = visible) | 0.1 (Jobs panel with jobs, 1.0) |
| Theme ▸ | Windows (Dark, Light, Follow system) and CapyPanel (Dark, Light). Only themes that ship with the app (§9) | 0.1 |
| Language ▸ | English, Português (Brasil) | 1.0 |

**Help**
| Item | Shortcut | What it does | Target |
|---|---|---|---|
| Documentation | F1 | Opens the user documentation | 1.0 |
| What's new | | Release notes of the installed version | 1.0 |
| Check for updates… | | Runs the self-updater check | 1.0 |
| About | | Version, license, credits | 0.1 |

### 4.4 Right-click menu on a host

A shortcut to the most used items, in this order:

1. The host's default connection, shown in **bold** (Enter).
2. Remote screen (VNC), Remote desktop (RDP), SSH terminal.
3. Logged-on users, System information.
4. Run script…, Restart…, Clean profiles…
5. Copy IP, Copy name.
6. Edit… (F2), Remove (Del).

Separators divide the groups. Each item follows the target of its feature.

### 4.5 Jobs panel

The Jobs panel is docked at the bottom of the main window. It's opened from the toolbar's Jobs button, Tools > Jobs or View.

- **Left: the list of jobs.** Each job shows:
  - its name (e.g. "Run script: cleanup-temp.ps1");
  - the number of hosts and the start or finish time;
  - while running, a progress bar with "8 of 18" and the ok/failed counts;
  - when finished, the final ok/failed counts.

  "Clear finished" removes completed jobs from the list.
- **Right: the hosts of the selected job.** Columns: Host, State (Queued, Running, Done, Failed), Time, Result. The result is a short output summary on success, or the specific failure reason on error. For example, "Host offline (no response to ping)" and "WinRM: access denied for <user>" are reported as different failures, never as one generic error.
- **Buttons:**
  - **Retry failed:** reruns the job only on the hosts that failed.
  - **Export:** saves the results.
  - **Cancel:** stops the hosts that haven't finished.

### 4.6 Settings window

The window has a list of pages on the left and **Cancel / Save** at the bottom. Nothing applies until Save.

Pages: General, Host lists, Connections, Credentials, Scripts, Appearance, Language, Updates. Like everything else, a page stays hidden until its feature ships: 0.1 shows General, Host lists, Connections (tool definitions and connection profiles), Appearance and Language.

**Host lists page.** It shows the three kinds of list (§5), and the user picks which one to open:
- **Default list:** `<app folder>\data\hosts.json`. Read-only; it ships with the app or is placed there by an administrator.
- **Personal list:** `Documents\CapyPanel\hosts.json`. Read-write, for this user only.
- **Shared list:** a path field with **Browse…**, e.g. a file on a network share. It's read-write only if the user has write permission on that folder, and the page shows whether they do.

Each list shows a "read-only" or "read-write" label. Two buttons at the bottom:
- **Copy current list to…** saves the open list somewhere else, for example to seed a shared or personal list.
- **New empty list** creates a new, empty list.

The contents of the other pages are defined with their features.

---

## 5. Host lists

### Where lists live
A user can open any of three kinds of host list:
- **Default list:** in the app folder, read-only. It ships with the app or is placed there by an administrator.
- **Personal list:** in the user's Documents folder, read-write, for that user only.
- **Any hosts file the user picks.** This includes a file on a shared network folder, which is how a team shares one list. Editing it requires write permission on that folder.

Only one list is open at a time. Lists are chosen in Settings > Host lists (§4.6) and reopened from **File > Recent lists**.

### Groups and tags
- Every host belongs to **exactly one group**. Groups work like folders and can be nested to any depth. A host that fits two groups goes in one, and a tag covers the other.
- Tags are free labels that cut across groups (floor, contract, device type, etc.).
- Search and filters work on groups, tags, status, OS and logged-on user.

### What a host stores
- **Fields the user types:** name, address, group, tags, notes, credential profile, preferred transport and connection settings (default connection, remote tool and port overrides). The connection settings start as a copy of the connection profile picked when the host is added (§6).
- **Fields the app detects:** OS, IP, **canonical hostname/FQDN (when resolvable)**, online status, last seen, logged-on user, uptime.
- The two sets are kept apart, so detection never overwrites what the user typed.
- Every host has a **hidden internal ID**. The name is only a label, so renaming a machine keeps its history, tags and settings.

### File format
- JSON, UTF-8, with a **schema version number** at the top so later versions can migrate old files.
- Groups have their own IDs and a `parent` reference (`null` for top-level). Hosts reference their group by ID.

Illustrative shape of the user-typed part:

```json
{
  "schema": 1,
  "groups": [
    { "id": "g1", "name": "Headquarters", "parent": null },
    { "id": "g2", "name": "Finance",      "parent": "g1" }
  ],
  "hosts": [
    {
      "id": "h7",
      "name": "FIN-PC04",
      "address": "10.0.12.24",
      "group": "g2",
      "tags": ["floor-3", "contract-2025"],
      "notes": "Reception desk"
    }
  ]
}
```

### Shared lists edited by someone else
- Before saving, the app checks whether the file changed on disk since it was loaded.
- If it did, the app never silently overwrites the other person's changes. It offers to **save the user's own edits as a local copy** before reloading the shared list, possibly with a warning. The exact dialog is designed when the feature is built.
- Several people editing the same shared list at the same moment is not expected. Shared lists are meant to change rarely, so the app needs this safety net, not live merging.

### Import and export
- Hosts can be imported and exported as **CSV**. This is also the migration path from any other tool.
- Importing from Active Directory / LDAP comes after 1.0.

---

## 6. Connecting to hosts

### External remote tools
- Remote screen, RDP and SSH sessions open in **external programs** the user has installed (rule 6). Built-in terminal and remote screen come after 1.0.
- **Long-term goal:** the app can be associated with **any remote tool on the market**, not only a fixed list.

### Tool definitions
No remote tool is hardcoded. Each one is described by a **tool definition**, which holds:

| Field | Meaning |
|---|---|
| Name | Shown in menus and host properties (e.g. "UltraVNC") |
| Kind | Remote screen, remote desktop, terminal, etc. Decides where the tool is offered |
| Executable | Path to the program |
| Arguments | A template with placeholders, e.g. `{address}`, `{port}`, `{user}` |
| Target field | Which host field the tool connects to. Usually the address; tools that use their own ID (AnyDesk-style) use a per-host ID field instead |
| Credential method | How the tool receives the password: none, a command-line option, standard input, or a temporary file deleted right after launch |

- **Presets** are tool definitions that ship with the app. Users can edit them and add their own for any tool.
- **Auto-detection:** the app looks for known tools in their usual install locations and fills in the executable path of the presets it finds. The user only types a path when a tool isn't found.
- **Initial presets:** UltraVNC and the system RDP client (`mstsc`) in 0.1. The SSH client arrives with the SSH feature. Other tools (TigerVNC, RealVNC, TightVNC, AnyDesk, etc.) become presets when requested; until then anyone can add them as their own definitions.
- **Launching:** always with an argument list, never a shell command string, so host names and paths can't be misread as commands.
- **Warning:** if a definition passes the password on the command line, the app warns the user. Other users on the same PC can see command lines in the process list.
- Tool definitions are included in **settings import/export**, so a company baseline can ship its standard tools.
- **Data, with the mechanisms in code.** A definition is a data file that picks from a small fixed set of mechanisms written and tested in code: credential methods, ways to detect a tool. Supporting a new tool means adding a file. Only a tool that needs a genuinely new mechanism means new code, and every definition can use that mechanism afterwards.
- **One JSON file per definition**, like connection profiles (§6), so importing or sharing one never touches the others.

#### Where definitions and profiles live: three layers
Tool definitions and connection profiles are read from three layers. When two layers hold a file with the same ID, the higher one wins:

| Priority | Layer | Where | Written by | Touched by updates? |
|---|---|---|---|---|
| 1 (highest) | **User** | `%APPDATA%\<APP_ID>\tools\` and `...\profiles\` | The user, through the app | Never |
| 2 | **Company** | `<app folder>\data\tools\` and `...\profiles\`, next to the default host list (§5) | An administrator, once | Never |
| 3 | **Shipped presets** | `<app folder>\presets\` | The project | Yes, replaced freely |

- **Editing** a company or shipped entry saves the user's copy in the User layer; the original is never modified. **"Reset"** deletes the user's copy, and the next layer down shows through again.
- **User files never go in the app folder.** It's often under `Program Files`, where users can't write and Windows would silently redirect the file somewhere hidden. The updater also replaces the app folder, and on a shared PC every user would overwrite the others' files.
- **Users never need to know these paths.** Settings > Connections has:
  - **Import…**, which copies a `.json` into the User layer;
  - **Export…**, which saves one to share;
  - **Open folder**, which opens the User layer's folder.

  Each entry also shows which layer it comes from.
- **Portable mode** (§9) puts the User layer inside the app folder too, for a USB stick or a shared tools folder.
- On first run the app creates only the empty User folders. It never copies presets into them.

### Default connection and overrides
- **Double-click on a host connects** using that host's default connection.
- The global default connection is **VNC**. Each host can change its default connection in its properties (e.g. RDP for a server, SSH for a Linux box).
- The remote tool and port have **one global default in settings** (VNC: port 5900), and **any host can override** either one.

### Connection profiles
- **Add host** has a **Connection profile** dropdown. The profile fills in the new host's connection settings (default connection, remote tool, port). Profiles that ship with the app: **VNC, RDP** (0.1) and **SSH** (with the SSH feature). **Custom** leaves the fields for the user to fill in by hand.
- The host **copies** the profile's values when it's created. Editing or deleting a profile later never changes existing hosts (rule 3). A host's settings are always edited on the host itself.
- **One JSON file per profile**, stored in the same three layers as tool definitions: user, company, shipped (see "Where definitions and profiles live"). Importing a profile means adding its file, which never touches the others, and sharing one means sending the file. A company can place its profiles in the company layer or ship them in a settings baseline.
- Users create, edit and delete their own profiles in Settings > Connections. Settings pick which profile Add host preselects (default: VNC).
- Profiles grow with the features: transport and credential profile join them when those ship.

### Credentials when connecting
- **In 0.1:** the user types the password when connecting. It stays in memory until the app closes, so later connections don't ask again. Nothing is written to disk. **RDP gets no credentials from the app in 0.1:** `mstsc` shows its own password prompt. Passing credentials to RDP comes with credential management (1.0) and needs a mechanism that respects rules 4 and 5.
- **By 1.0:** credentials are stored in the OS keychain (Windows Credential Manager), with credential profiles per group.
- In every version, each remote tool gets credentials only through a mechanism that tool supports: a command-line option, standard input, or a temporary file deleted right after launch. The method is confirmed for each tool when it's added. Never keystrokes (rule 4).

---

## 7. Talking to hosts (transports)

- The app runs commands and reads data over **PsExec, WinRM or SSH**. The transport is chosen **per host** (WinRM / PsExec / SSH / automatic). All are available by 1.0.
- **Order (revised 2026-09-29 after the backend prototype — see "Backend prototype outcome" below):**
  - **Logged-on users (0.1) reads over the WTS API's own RPC channel** (`WTSOpenServer`), called from the client — not over PsExec. It is the only 0.1 feature that touches a host, so **0.1 needs no command transport at all.**
  - **WinRM is the preferred general command/data transport** — everything that runs a command or reads data back (Actions §8, inspect features). It arrives with those features (by 1.0), no longer "a few versions later".
  - **PsExec is kept as a per-host fallback** where WinRM isn't enabled, but only for exit-code work: its output relay is capped (below), so it cannot return data unless it writes a temp file read back over ADMIN$ and deleted right after (rule 2, revised). Its advantage is that it needs no target-side setup on a domain LAN.
  - **SSH arrives with the SSH features.**
- **PsExec** is a separately installed Sysinternals tool. The app finds it (configured path, PATH, usual locations) and never bundles it (rule 6).
- **WinRM** needs to be enabled on the targets. It's off by default on Windows 10/11 clients, and the prerequisite checker explains how to turn it on.
- Results come back through the transport's own output channel; where a transport can't (PsExec's cap), through a single temp file deleted right after reading (rule 2). Never by parsing text meant for humans.
- Data read from hosts comes back as **structured output** — JSON from a PowerShell block over WinRM/PsExec, or typed fields straight from the WTS API over RPC — never localized text, because the app must work in any display language.
- A **prerequisite checker** tests each host (reachable? transport enabled? permissions?) and explains how to fix what's missing.
- **SSH host keys** are managed by the app (trusting and checking each host's key).
- Long or multi-host operations run as **jobs**, shown in the Jobs panel (§4.5) with per-host state and results. Jobs can be cancelled, and failed hosts can be retried.
- Every action is written to a **local audit log**. The "History on this host" part of the details pane shows it per host.

### Credentials for host access
- **Session credential (0.1):** one account, typed once and used for every host, kept in memory until the app closes. The default is **"Use my Windows login"**, which needs nothing typed. It's useful because many IT staff work from a non-admin daily account, and that account can't read sessions (259, below). In 0.1 the logged-on-users read uses it; command transports use the same credential when they arrive.
- When a host answers "access denied", the user can set a **per-host override** for that host. It's also kept in memory only.
- **How the WTS read uses another account.** `WTSOpenServer` takes no credentials, so the app swaps only its *network* identity for the call.
  - It uses a "new credentials" logon, the same thing `runas /netonly` does: `LogonUser(LOGON32_LOGON_NEW_CREDENTIALS)` plus per-thread impersonation around the WTS calls. The password stays in memory only (rule 5).
  - **Verified on-site 2026-09-29**, both through `runas /netonly` and in-process (`proto.py --transport rpc --user`). A non-admin shell with an admin credential read the host's sessions.
  - An `IPC$` session opened with other credentials (`net use`) **doesn't work**: the RPC call still authenticates as the caller.
- **Never spray a rejected password.** Windows doesn't check a new-credentials password at logon, only each target does. So a mistyped password would be tried against every host in a multi-host read, and each failure counts toward the domain's account-lockout limit.
  - The app checks the credential **once before fanning out**: with a single real logon against the domain where that's possible, or else by trying one host first.
  - A credential rejection **stops the batch and asks again**. It isn't retried per host.
- **Access errors are told apart**, using codes observed on-site, and each gets its own message (§4.5):
  - `259` = the host accepted the account, but it isn't an admin there;
  - `5` = the host didn't accept the account (wrong password, or an account or trust it doesn't honour).
- **By 1.0:** these move to the OS keychain with credential profiles per group (§6).

### Logged-on users (0.1)
- It's read through the **Windows session API (WTS) over its own RPC channel** (`WTSOpenServer`), called from the client with ctypes — no PowerShell on the target, nothing deployed (decided by the backend prototype; see its outcome below).
- **Fields per session:** user, domain, session type (console or RDP), state (active or disconnected), logon time, and the RDP client name when there is one. **Idle time is reported null** over RPC (not reliable remotely; never guessed), and a **disconnected** session's type is **unknown** (Windows releases the `RDP-Tcp` station on disconnect, leaving no remote signal to tell RDP from console; active/connected sessions still type correctly).
- It works the same whatever the target's display language, because it reads typed fields from the API, not `quser`-style text.

### Backend prototype outcome (2026-09-29)
The stack-independent backend prototype tested PsExec + logged-on users on real machines in a company Windows domain (Portuguese-language hosts). Its spec, code and full results are kept in the maintainer's research archive, outside this repo. Findings that shaped the decisions above:
- **PsExec's stdout relay is capped at ~256 bytes** as invoked (remote stdout → pipe): deterministic, payload-size-dependent, timing-independent (confirmed against flush, in-process linger and padding). The app's framing check caught the truncation and refused the partial data — but it means **PsExec returns only exit codes reliably**, not command/script output.
- A separate, intermittent **PSEXESVC deploy race** ("could not start … cannot find the file specified") appears under rapid repeated same-host use. Targets were always left clean (`PSEXESVC` uninstalled, no leftover files).
- **WTS-over-RPC** reads sessions with **nothing deployed on the target**, is language-independent, and was clean and fast across all hosts (12/12 OK, ~0.13 s median). It became the logged-on-users read path. Its limits are recorded above: no credential parameter (another account goes through a new-credentials logon, verified), idle reported null, and disconnected sessions typed unknown.
- A **non-admin** caller gets `win32=259` (ERROR_NO_MORE_ITEMS) from a remote WTS enumerate — reported as access-denied.
- **WinRM validated on-site (2026-09-29):** `Enable-PSRemoting` succeeded cleanly (service + firewall, no GPO needed); `Invoke-Command` over Kerberos returned **33 KB of structured output intact (215 processes)** from a Portuguese-locale domain host — no ~256-byte cap — confirming it as the general data/command transport. **Connect by host name** (Kerberos): an **IP-address** target instead needs TrustedHosts + HTTPS or explicit credentials, so the prerequisite checker should steer to names. Alternate explicit credentials (`Get-Credential`) weren't exercised (its interactive prompt didn't render on the test client) — deferred to 1.0; the current-Windows-login path is proven.
- **IP-typed hosts auto-resolve to a usable identity — the method is environment-dependent, so the app probes, it doesn't assume (rule 1).** Users add hosts by IP; WinRM/Kerberos needs the host's real FQDN. Several methods exist — reverse DNS (PTR), WMI/DCOM `Win32_ComputerSystem`, NetBIOS (`nbtstat`), AD/LDAP, or the host's self-reported name once any connection succeeds — and which work varies wildly by network, so **none is hardcoded as primary**. Observed 2026-09-29: on the **domain LAN** all three agreed on the AD FQDN (e.g. `PC-0142.corp.example.net`); on a **Tailscale overlay** host, PTR returned a non-domain MagicDNS name (`…ts.net`, useless for Kerberos), NetBIOS found nothing, and WMI was access-denied — a completely different profile. A wider probe across mixed hosts confirmed why the chain matters: some **reachable domain hosts had no PTR or NetBIOS record and were named only by WMI/DCOM** (so reverse DNS alone is not enough), while **powered-off hosts return RPC-unavailable** — which the app reports as offline/unreachable, a distinct signal from a naming failure. So the app runs the methods that apply, **trusts a name only after it validates for the intended transport** (does the connection actually authenticate?), cross-checks agreement between methods (PTR can be stale from a reassigned IP), and for hosts with no domain/Kerberos path (overlay, workgroup, cross-forest) falls back to per-host explicit credentials over HTTPS/TrustedHosts, SSH, or PsExec (§7 already makes transport and credentials per-host). Which methods and transports work is discovered by the prerequisite checker and a **first-run, per-machine environment probe** (the app self-tests the network it's deployed on), not tuned to any one site.
- Antivirus (an expired commercial product on the test hosts) was **not** the cause of any failure (other hosts ran PsExec cleanly under the same posture).

---

## 8. Features and when they ship

"Target" means the release that **includes** the feature. A feature can be built in any earlier version.

### Inventory
| Feature | What it does | Target |
|---|---|---|
| Host list | Hosts, groups and tags as described in §5 | 0.1 |
| Nested groups and tags | Full group tree and tag filtering | 1.0 |
| Search and filters | By name, IP, user, tag, group, status, OS | 1.0 |
| CSV import/export | Bring hosts in from, or out to, other tools | 1.0 |
| Status and basic facts | Online/offline, OS, IP, uptime, logged-on user per host | 1.0 |
| Active Directory / LDAP import | Load hosts from the directory | After 1.0 |

### Connect
| Feature | What it does | Target |
|---|---|---|
| VNC | Remote screen through an external VNC viewer, typed credentials | 0.1 |
| RDP | Opens the system RDP client; credential passing comes with credential management | 0.1 |
| Connection profiles | Pick VNC, RDP, SSH or a custom profile when adding a host (§6) | 0.1 |
| SSH | Opens an SSH session in an external terminal | 1.0 |
| In-app terminal and remote screen | Same sessions inside the app window | After 1.0 |

### Inspect
| Feature | What it does | Target |
|---|---|---|
| Logged-on users | Who is logged on to a host, and their sessions; with the Windows login or a session credential (§7) | 0.1 |
| Printers | Printers installed on a host | 1.0 |
| Installed software | List of installed programs | Optional for 1.0 |
| Services and processes | List them; start/stop services, end processes | Optional for 1.0 |
| System info | Hardware, disks, memory | After 1.0 |
| Event log viewer | Browse a host's event logs | After 1.0 |

### Actions
| Feature | What it does | Target |
|---|---|---|
| Power | Restart, shut down, log off, with confirmation | 1.0 |
| Run command or script | On one or many hosts, from a script library, results per host | 1.0 |
| Profile cleaner | Cleans up Windows user profiles on a host. The cleanup logic already exists and is tested; it gets adapted, not rewritten | 1.0 |
| Send message to user | Show a message to whoever is logged on, without depending on a viewer's chat | Optional for 1.0 |
| Install/uninstall software | May turn out to be covered by the script runner | Optional for 1.0 |
| Add/remove printers | Manage printers on a host | After 1.0 |
| File transfer | Copy files to or from a host | After 1.0 |

### Connections and security (all by 1.0)
- WinRM, PsExec (fallback) and SSH transports, chosen per host. 0.1 needs none (§7)
- Credentials in the OS keychain, credential profiles per group
- SSH host key management
- Prerequisite checker with how-to-fix hints

### App (all by 1.0, except the wizard)
- Jobs panel
- Local audit log
- English and Portuguese (Brazil)
- Dark and light themes: the native Windows look and the CapyPanel look (§9). Both ship from 0.1
- Self-updater
- Settings import/export. It's also how a company distributes a **baseline** configuration that each user then customizes on top of.
- First-run setup wizard: optional for 1.0.

### Out of scope
- **Network discovery (IP range scans).** Hosts come from lists, CSV and, later, the directory.
- **Wake-on-LAN.** It depends on BIOS configuration on every machine, so it's outside what the app can control.

---

## 9. Technical foundation

### Code structure
The code is split into a **core** that knows nothing about the user interface and a **ui** layer on top of it. Inside each, code is organized **by feature**:

```
src/capypanel/            standard "src layout": tests import the installed package, never loose files
  __main__.py             starts the app (python -m capypanel)
  core/                   ← never imports any UI library
    hosts/                host records, list files (load, save, migrate, changed-on-disk check)
    tools/                external programs: tool definitions, connection profiles, detection, launching, credential methods
      presets/            shipped tool definitions and profiles (data files)
    sessions/             logged-on users (WTS bindings + reading)
    settings.py           folders, portable mode, settings load/save
    i18n.py
    transports/  jobs/    later: WinRM/PsExec/SSH, multi-host work
  ui/                     ← the only place that knows the UI toolkit
    main_window/          window layout, actions (menus/toolbar/right-click), host views
    hosts.py              host and group dialogs
    connect.py            manual connection, password prompt
    sessions.py           logged-on users window
    settings/             settings window and its pages, grouped by topic
    themes/               theme engine and theme files
tests/                    mirrors core/
```

- **Files are grouped by topic, not by line count.** A file holds one subject: connection code never contains host-list code. Small related pieces share a file (for example, the small settings pages). A file is split when it starts mixing subjects, or when one part gets big enough to bury the rest.
- `core/tools/` is named after the §3 term "remote tool" and holds everything about the external programs the app finds and launches. PsExec detection can reuse it later. It's one flat folder: a sub-folder inside it would hold only a few files.

- A lint rule fails CI if anything under `core/` imports a UI library. The rule is enforced, not left to discipline.
- The core reports progress and results through plain Python callbacks and data objects. The UI layer turns those into its own mechanism (signals, events). Slow work never runs on the UI thread.
- **What this buys:**
  - The UI toolkit only touches `ui/`.
  - All logic is testable without opening a window.
  - A command-line front end is possible later.
  - A macOS port only needs Windows-specific pieces (transports, presets, paths) swapped, not a rewrite.

### UI toolkit
- **PySide6 (Qt Widgets)**, decided 2026-09-28.
- **How it was chosen:** the same mini app was built with PySide6 and with pywebview on Windows and measured the same way. The spike (spec, code, numbers and friction log) is kept in the maintainer's research archive, outside this repo.
- **Why:**
  - On the maintainer's PC, Qt started about 2.4× faster (0.39 s vs 0.95 s warm).
  - It used about 7× less memory: 78 vs 542 MiB idle, 80 vs 600 MiB during jobs.
  - It doesn't depend on the WebView2 runtime.
  - Responsiveness was similar in both.
  - Qt provides menus, keyboard navigation, docking panels and translated built-in widgets that the web version had to build by hand.
  - The web version was quicker to style, but the spike showed Qt reaches the same custom look with a stylesheet at almost no cost.
- The spike's cold-start measurement wasn't completed; the other numbers were enough to decide.
- **Python 3.13** works with PySide6 and PyInstaller, so it stays the development version.
- In parallel, a stack-independent **backend prototype** tested PsExec + logged-on users on real machines (also in the research archive). Outcome (2026-09-29): the logged-on-users read moved to WTS-over-RPC and WinRM became the preferred general command/data transport — see §7 "Backend prototype outcome".
- The spike's code is throwaway. Its gettext setup and Qt theme engine are ported into the app as the matching features are built.

**Notes from the spike for the UI code:**
- The core calls its callbacks from worker threads. `ui/` turns them into Qt signals, which Qt delivers on the UI thread. The core hands out immutable records, so the UI reads them without locks.
- Host and job lists use `QTreeView` as a column list. Under the Windows 11 style, `QTableView` draws the selection per cell.
- Qt's own strings (context menus, standard dialog buttons) are translated by loading Qt's translation files next to our gettext catalogs. Switching language at runtime needs a "retranslate" step in each window.
- PyInstaller folder mode worked (about 112 MiB). It bundles Qt modules the app doesn't use (QML, Quick, PDF), which can be excluded later.

### Themes
- **The themes that ship:**
  - **Windows:** Dark, Light, Follow system. Qt's native Windows 11 look; it follows the Windows accent colour.
  - **CapyPanel:** Dark, Light. The app's own look: Qt's Fusion style plus a stylesheet generated from our colour list.
- Switching theme takes effect immediately, without a restart (the spike's theme build shows it).
- **Only shipped themes are supported.** Users can't add, import or edit themes, and there's no public theme file format.
- **Later:** more themes may be added. User-made themes may be allowed some day, as an unsupported extra: no help with errors or bugs they cause.
- A theme only changes the look (rule 8). The native Windows look can't colour a single button or menu item, which is fine: destructive actions rely on the confirmation dialog (rule 7), not on red.

### Where the app keeps its files
| What | Where |
|---|---|
| Settings | `%APPDATA%\<APP_ID>` (roams with the Windows profile) |
| Tool definitions and connection profiles: user layer | `%APPDATA%\<APP_ID>\tools\` and `...\profiles\`, one `.json` each (§6) |
| Tool definitions and connection profiles: company layer | `<app folder>\data\tools\` and `...\profiles\`, placed by an administrator, never touched by updates (§6) |
| Shipped presets | `<app folder>\presets\`, read-only, replaced by updates (§6) |
| Logs and audit log | `%LOCALAPPDATA%\<APP_ID>` |
| Personal host list | `Documents\CapyPanel\hosts.json` (§5) |
| Default host list | `<app folder>\data\hosts.json`, read-only (§5) |

- **Portable mode:** if a marker file sits next to the app's executable, everything (settings, logs, lists, the user layer of tools and profiles) stays inside the app's own folder instead. Useful on a USB stick or a shared tools folder.
- **The self-updater replaces the app's own files only.** It never touches `<app folder>\data\` (the default host list and the company layer) or, in portable mode, the user's files.
- `<APP_ID>` is one internal constant. It isn't the visible brand name, so renaming the product never moves user data.

### Translations
- Every visible string goes through **gettext** (`.po`/`.mo` files, Babel tooling), in both core and UI, from the first commit, even while only English exists.
- Error messages produced by the core are translated too.
- By 1.0 the app ships English and Portuguese (Brazil). More languages can be added as `.po` files without code changes.

---

## 10. Development workflow

- **License:** GPL-3.0. Once people outside the maintainer contribute, a **CLA** (Contributor License Agreement) is required, so the project keeps the option to relicense or offer commercial terms later.
- **Repository:** [github.com/gabrielmariense/CapyPanel](https://github.com/gabrielmariense/CapyPanel), **public from its first commit**, so the full history is visible. It holds **development files only**: packaged builds are published as GitHub Release assets, never committed.
- **Pace:** one feature at a time. Each increment ends in a build that's tested on real machines, and anything broken is fixed before the next feature starts.
- **Documentation:** learning docs and project tracking live in the Notion project hub; the repo keeps this file, a README and the license, and more docs can move there later. **Code comments are short** (one or two lines), only where the reason isn't obvious from the code.
- **Python environment:** [uv](https://docs.astral.sh/uv/). `pyproject.toml` declares dependencies, and `uv.lock` pins exact versions.
  - After cloning: `uv sync`.
  - Run anything with `uv run …` (e.g. `uv run pytest`).
  - Add a dependency with `uv add <package>`, never by hand-editing the lockfile.
- **Branches:** `main` always works. Every feature or fix is a short branch merged through a pull request, and CI must be green before merging.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`. The changelog and release notes are generated from them, so they always match what was committed.
- **Versions:** SemVer, starting at 0.1. The version changes only for a release.
- **CI (every pull request, on a Windows runner):**
  - **ruff:** lint, format check, and the "no UI imports in core" rule;
  - **pytest:** tests, mostly on the core, no window needed;
  - **pyright** in standard mode: type checking.

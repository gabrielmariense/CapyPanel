# Checking hosts

CapyPanel can check whether hosts are on, who is logged on to them, and what the PC itself
is. The results show in the host table's **Status** and **User** columns and in the
**Details** panel. They're kept in
memory only: never in the list file, and gone when CapyPanel closes. Editing a host's address
clears its results. To keep them, **Report** on the toolbar writes the last check into a CSV, and
offers to check the hosts first (see [Importing and exporting hosts](importing.md)).

## Refresh

**Refresh all**, on the toolbar, checks every host the table shows: the group picked in the Groups
panel with its subgroups, a tag, All hosts, No group, or the results of a search. Nothing needs to
be selected.

- Click it to run the checks that are ticked, on every host shown. Its tooltip says so: "Refresh
  every host shown, with the checks ticked on a right-click (also F5)".
- Right-click it for the **Refresh every host shown** panel: tick both and click **Run**.
  CapyPanel remembers the ticks.
- **F5** does the same as that **Run**, on the hosts shown, without opening the panel. It's
  ignored while a check is already running.

To check only some hosts, right-click:

- **one host > Refresh host**: its status, logged-on users and PC facts;
- **several selected hosts > Refresh {n} hosts**: their status and logged-on users (PC facts are
  read one PC at a time);
- **a group > Refresh group**: the status and logged-on users of its hosts and those in the groups
  inside it.

CapyPanel checks 8 hosts at a time; the status bar shows the progress and a **Stop** button.
Checking who is logged on to more than 50 hosts asks first. A host without an address, whose name
isn't a computer name, is skipped with a note in the status bar.

## Status

| Status | Meaning |
|---|---|
| **Online** | A ping, or one of the ports CapyPanel connects to, answered |
| **Offline** | Nothing answered within 2 seconds |
| **Host not found** | The name or address doesn't exist |

The ports are 445 (Windows file sharing), 22 (SSH) and each tool's own port, such as 5900 for VNC
and 3389 for Remote Desktop. A refused connection counts as an answer. Every address the name has
is tried, cable and Wi-Fi alike. Hover over a status to see when it was checked and which address
answered: a PC that answers only on its Wi-Fi address may have its cable out. The Details panel
says it under the host's name, as "Online · checked 10:41", or "Not checked: use Refresh".

A host nobody has refreshed yet reads **Not checked** in grey in the Status column, and its User
cell stays empty. Sorting by Status keeps those hosts last whichever way you sort.

When a PC didn't answer, Details says so once, under its name, as "Offline · checked 10:41", and
**Logged on** and **PC facts** show a single dash or one line with the reason rather than
repeating it on every row.

Status uses no account and needs no administrator rights.

### Automatic status

**Settings > Hosts > General > Refresh status by itself** can check the status of the
hosts shown every few minutes: **Every minute**, **Every 5 minutes**, **Every 15 minutes**, **Every
30 minutes**, or **Custom…** for anything from 1 to 120. It's **Off** to begin with, so nothing
is checked by itself unless you turn it on, and turning it off again keeps your interval for next
time.

As the setting says: "Only ping and ports, so no account is needed. Refresh in the toolbar always
works."

## Logged-on users

The **User** column shows who is logged on, as `DOMAIN\user`, with "(disconnected)" for a
disconnected session, or **No one**.

The Details panel lists each session under **Logged on**, with the time of the check, as in
"Logged on (3) · 10:40". Every row names the user, a badge saying **Active** or **Disconnected**,
and under it whether they're at the computer (**Console**) or on **Remote Desktop**, which PC they
came from, and since when. Active sessions come first. Before any check the section says
**Not checked**; with nobody logged on, **No one logged on**; and when a check failed, the reason
below, with the full explanation in its tooltip.

**View > Show users' domain** is on and remembered. Turn it off to see just `user` in the
column, the Details panel and searches; what you hover over still shows the whole
`DOMAIN\user`, so a local "admin" can't pass for the domain's.

CapyPanel reads this through Windows' own remote session service: nothing is installed on the
hosts, and it works whatever their language. It needs an administrator account on each host.

| Shown | Meaning |
|---|---|
| **Unreachable** | Port 445 (Windows file sharing) didn't answer: the PC is off, off the network, blocks file sharing, or isn't Windows |
| **No admin rights** | The account isn't an administrator on that host |
| **Account rejected** | The host refused the account |
| **Couldn't read** | The host answered, but the sessions couldn't be read |

After someone logs off, they may show as disconnected for a while or disappear, the same as in
Task Manager's Users tab. That's how Windows reports it.

### Which account is used

By default, your own Windows account. **Settings > Hosts > Credentials > Accounts** can give a
PC, a group, a tag or every PC another account, and the Details panel's **Commands run as** names
the one each host ends up with (see
[Accounts for other PCs](connecting.md#accounts-for-other-pcs)).

If hosts answer **No admin rights** or **Account rejected**, CapyPanel asks for another account
once the Refresh ends, in a window called **Account for other PCs**, and checks only those hosts
again. The account you type there becomes a row of the Accounts table. It's tried on one host at a
time: if a host rejects it, CapyPanel stops and asks again instead of trying it on the others, so
the account isn't locked out.

## PC facts

The Details panel ends with what the PC says about itself: **Last restart**, **Free on C:**,
**Windows** (its edition, release and build, as in "Windows 11 Pro 25H2 · 26200.9168"),
**Model**, **Serial**, **Memory** and **BIOS**, with a **Read again** button under them.

![The PC facts section in the Details panel: last restart, free space, Windows, model, serial, memory and BIOS](../images/commands-pc-facts-dark.png)

They're read once, when a host stays selected for a moment, and never by Refresh, so a list of
hundreds of hosts is left alone. Until then the section says "Not read yet", with a **Read**
button. The free space and the last restart come in first, while the heading says "PC facts ·
reading…" and the other rows say "Reading…"; the rest follows a few seconds later.

Each fact is read on its own, so one that fails doesn't take the others with it: what was read
shows, and a fact that couldn't be read says why in amber in its place, as in "No access: needs an
admin account on this PC". Click that line to copy it, as you would any value. The app log names
the part that failed.

**PC facts** reads them again whenever you want, from the toolbar's **Commands ▾ > Check** or the
Commands window, and **Refresh host** reads them with the rest (see
[Commands on a host](commands.md)).

## How CapyPanel reads other PCs

Status uses ping and ports, and logged-on users use Windows' remote session service. The PC
facts, the installed programs, the mapped drives and the
[User profiles](../profiles/user-profiles.md) tool read the PC over **WMI**, Windows' own
management service, which every Windows PC answers. Nothing is installed or started on the other
PC.

On your own PC, CapyPanel talks WMI itself, through Windows' scripting objects. It starts
PowerShell for this only when it can't do that on your PC at all, and never because one PC's read
failed. The app log says at each start which way it reads.

Some antivirus products stop programs that another program starts, PowerShell above all. If
yours does, a read through PowerShell fails with "Couldn't read: Windows didn't let PowerShell
start on your PC (an antivirus may block it)". It's your PC that refused, not the one you were
reading, so that's the PC to look at.

**Settings > Hosts > Connecting > Read PC data with** sets the way for everyone on your PC:

| Choice | What it does |
|---|---|
| **Automatic (recommended)** | WMI directly, and through PowerShell only when that can't be used on this PC. "in use:" beside it names the way it's using |
| **WMI directly** | Always talks WMI itself and never starts PowerShell, even when it can't, in which case the reads fail and say why |
| **WMI through PowerShell** | Starts PowerShell on your PC to talk WMI, as CapyPanel did before 0.24. A way back, in case reading directly misbehaves on your network |

Both ways ask the other PC the same questions and get the same answers; only what starts on your
own PC changes.

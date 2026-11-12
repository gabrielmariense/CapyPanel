# Connecting

CapyPanel opens remote screens through VNC viewers you install yourself, and through Windows' own
Remote Desktop client. It never ships, bundles or downloads them.

## Supported tools

| Tool | How CapyPanel gives it the password |
|---|---|
| **UltraVNC Viewer** | On its command line (the only way UltraVNC accepts one). Administrators of your PC can see command lines; the log never shows the password |
| **RealVNC Viewer** | Through a private pipe that only your Windows account can open, read once. Nothing is written to disk or put on the command line |
| **Remote Desktop Connection** | It doesn't: the Remote Desktop client asks for the password itself |

Remote Desktop Connection is built into Windows, so CapyPanel finds it in `System32`. It finds
an installed VNC viewer by itself too: where Windows recorded the install (any folder), the usual
Program Files folders, then your PATH. A portable copy unzipped somewhere else isn't found
automatically; when a viewer is missing, CapyPanel asks you to install it or to locate its
`.exe`. The path is saved once for everyone on the PC, like in **Settings > Hosts > Connecting >
Remote tools** (see [Settings and files](../settings-and-files.md#remote-tools)).

## Connection profiles

A network often mixes several setups: VNC servers that ask for a Windows account (UltraVNC's
MS-Logon), servers that ask only for a VNC password, encryption plugins, RealVNC on Raspberry Pis,
Remote Desktop. A **connection profile** says which one a host uses:

- the **tool**: a VNC viewer or Remote Desktop Connection;
- the **login**: user and password, or password only. For Remote Desktop the table reads
  "asked by Remote Desktop Connection itself";
- **options** the tool offers, such as UltraVNC's **SecureVNC plugin**.

### Managing profiles

- Profiles are managed in **Settings > Hosts > Connecting > Connection profiles** (also
  **Connect > Connection profiles…**): add, edit, duplicate, delete, and restore the ones CapyPanel ships
  with. Each has a name, a tool, a login (only the ones
  that tool supports), the tool's options (such as SecureVNC) and a port, blank for the tool's
  own.
- Each tool comes with a starter profile: **UltraVNC** and **RealVNC**, both with "user and
  password", and **Remote Desktop**. A starter is added once, also on a PC that already had
  profiles; they're ordinary profiles, and one you delete stays deleted.
- All profiles are kept together in `C:\ProgramData\CapyPanel\profiles\`, beside the default
  list, so everyone on the PC sees the same ones and they're easy to check. **Windows
  permissions decide who can change them**: CapyPanel creates the folder at its first start,
  read-only for other users. A profile file made by another user (not an administrator) is ignored.
- **Hosts with no profile use**, the last row of that section, is the profile a host connects
  with when it has none of its own. It's saved in the same folder, so it's the same for everyone.
- Deleting a profile asks first, and says how many hosts and groups in the open list use it.
  Those then follow their group's profile, or the default.
- A profile can name a viewer that isn't installed on this PC (it's marked so), for example to
  prepare profiles before installing the viewers. CapyPanel asks for the viewer only when you
  connect.

### Viewer settings files

By default a profile uses the viewer's own settings, plus the options on the profile. For
everything else the viewer offers (quality, scaling, view-only, full screen and so on), an
**UltraVNC** profile can carry a settings file:

1. In UltraVNC Viewer, set the options you want and save the connection as a `.vnc` file.
2. In the profile editor, **Viewer settings > Choose file…** and pick it. **Use defaults** goes
   back to the viewer's own settings.

When you click **Add**, or **Save** for a profile you're editing, CapyPanel copies the file beside the profile (`profiles\<id>.vnc`). It's
used **exactly as saved**, encryption plugin included; only the `host` is emptied, since the
address comes from the host you open. While a profile has a file, its options (such as SecureVNC)
are off: the file decides. When you connect, the viewer gets a temporary copy, deleted a minute
later, and the shared file is never changed.

### Choosing a profile

- **On a group:** right-click the group > **Connection profile**. Every host inside follows it,
  including hosts in groups nested inside, unless they set their own.
- **On hosts:** in the host's own **Connection profile** field, in **Edit selected…** (F2). One
  edit can cover several hosts at once.
- **"From group"** means the host follows the nearest group that sets a profile. Hosts with no
  profile anywhere use the default.
- **Just once:** the toolbar's **Connect** dropdown lists **Connect with RealVNC**, **Connect
  with Remote Desktop** and so on, one per profile: the selected hosts open with that profile this
  time, without changing them.

A list stores only the profile's ID. When a host or group names a profile your PC doesn't
have, it follows its group's profile (or the default) instead, and the missing one is marked
"not available on this PC" wherever it's offered: the host's **Connection profile** field, and a
group's **Connection profile** menu.

### In the Details panel

![The Details panel's Connection section: address, group, Connect with and Commands run as](../images/commands-details-dark.png)

**Connection**, in the Details panel, shows the host's **Address** and **Group**, then two
dropdowns:

- **Connect with** is the profile Connect opens it with. A click opens the same list as the
  right-click **Connection profile** submenu: the group's choice, as in "From group “Front desk”:
  UltraVNC", or a profile by name, so a host's profile can be changed without opening **Edit
  selected…**. A small key beside the name means a login is kept for that profile; its tooltip
  names the user.
- **Commands run as** is the account that reads who is logged on and runs the host's commands.
  A click offers **Follow Accounts**, which names what the [Accounts](#accounts-for-other-pcs)
  table gives this PC, as in "Follow Accounts: EXAMPLE\admin", then **Your Windows account**,
  each account of the table, and **Another account…**. Picking one sets it for this PC alone, and
  a small pin beside the name says so ("Only this PC" in its tooltip). **Follow Accounts** takes
  the pin off.

**Commands run as** is also on the right-click menu of several selected hosts, where it sets the
account for each of them, and on a group's, where it sets it for every PC in the group.

## Accounts for other PCs

Reading who is logged on to a PC and running its [commands](commands.md) need an account that's
an administrator there. By default that's your own Windows account. **Settings > Hosts >
Credentials > Accounts** says which other account signs in to which PCs:

| Column | What it shows |
|---|---|
| **Account** | The user, as `DOMAIN\user` |
| **Used for** | **Every PC**, a group, as in "Group Clinic › Front desk", a tag, or one PC, as in "DESK-02 (198.51.100.20)" |
| **Kept in** | Where its password is: **Credential Manager**, **Temporary**, or **Asked when needed** when it hasn't been typed yet |

**Add…** and **Edit…** open one window: **User** ("DOMAIN\user, or empty for your Windows
account"), **Password** ("Optional: asked the first time it's needed"), **Use it for**: **Every
PC**, **One PC** (its address or name, as in the host list), **A group** or **A tag**, and
**Remember it on this computer**. **Remove** takes the row away, and its saved password with it.

When several rows match a PC, the narrowest wins: "A PC's own account wins over its group's, a
group's over a tag's, and those over Every PC. PCs none of them names use your Windows account."
Groups and tags are those of the open list. The table is yours only, "kept in your own settings,
never in the shared host lists", so whoever else uses the same list keeps their own accounts.

When PCs answer **No admin rights** or **Account rejected** while Refresh reads who is logged on,
CapyPanel asks for another account once the Refresh ends, and checks those PCs again with it. A
command that failed the same way offers **Try another account…**. Both open **Account for other
PCs**: the user, the password, and **Use it for**: this PC, each group and tag they all share, or
every PC, the narrowest first. **Use account** makes what you picked a row of the table. An
account is tried on one PC at a time: "If a computer rejects it, CapyPanel stops and asks again
instead of trying it on the others, so the account isn't locked."

On PCs that aren't in a domain, the built-in Administrator is the only local account Windows
accepts remotely.

## Remote Desktop

A Remote Desktop profile opens the host in Windows' Remote Desktop client (`mstsc`), on port 3389
unless the host or profile sets another. Its options are checkboxes on the profile:
**Administrative session (servers only)**, which matters only on Remote Desktop Services servers,
**Full screen** and **Use all my monitors**. There's no settings file for Remote Desktop.

CapyPanel never handles a Remote Desktop password: the client asks for it, and the login check
below doesn't apply. A Remote Desktop login is never in **Saved credentials** either. If you tick
**Remember me** in Remote Desktop Connection, Windows keeps that login itself, as
`TERMSRV/<address>`; remove it there, or in **Control Panel > Credential Manager**.

## Passwords

- For VNC, CapyPanel asks for a profile's password the first time you connect with it, and
  **remembers it, per profile**, until it closes. Hosts with another profile never receive it.
- Every window that asks for a password, for a profile or for an account, has **Remember it on
  this computer**, unticked: "Windows keeps it in Credential Manager for your Windows account.
  Otherwise CapyPanel forgets it when it closes and asks once the next time." Neither way puts a
  password in a file of CapyPanel's own. One window starts ticked: when a PC rejects an account
  whose password you had remembered and CapyPanel asks for it again, so that typing it again
  keeps it saved. Typing another account there unticks it.
- Classic VNC passwords are at most 8 characters long, so the password box of an UltraVNC
  "password only" profile stops at 8.

### Saved credentials

A login you ticked **Remember it on this computer** for is kept in **Windows Credential Manager**,
under your own Windows account, so CapyPanel doesn't ask for it again the next time it starts.
That means "Windows encrypts them for your account, so anyone using your Windows session can
connect with them."

**Connect ▾ > Saved credentials…**, and **Manage…** on **Settings > Hosts > Credentials >
Passwords > Saved credentials**, open one window with every login CapyPanel keeps: "Every login
CapyPanel keeps for you. Passwords never show here." The settings row says how many there are and
where, as in "2 kept: 1 in Credential Manager, 1 temporary.", or "None kept."

| Column | What it shows |
|---|---|
| **Used for** | The connection profile, or the PCs an account is for, as in "Every PC" |
| **Tool** | What signs in with it, as in "RealVNC Viewer", or "Hosts › Accounts" for an account |
| **User** | The user name, or "(password only)" for a profile that takes only a password |
| **Kept** | **Credential Manager**, or **Temporary** until CapyPanel closes |

**Forget** drops the login you picked, after a typo for instance: CapyPanel can't tell when a
viewer rejects a password. **Forget all** asks first, listing every login under "Saved in
Credential Manager:" and "Temporary:", then "CapyPanel asks for them again when it needs them.";
Cancel is the default button. A login forgotten here is deleted from Credential Manager too.

Only these logins are listed. The printers' SNMP community string and v3 account are not:
they're managed in **Settings > Printers > Connecting**, where emptying the field forgets them
(see [Checking printers](../printers/checking.md#the-snmp-account)).

## The login check

Classic VNC password login uses only the first 8 characters of a password, and its exchange can
be cracked offline. So before an UltraVNC **user-and-password** profile connects, CapyPanel asks
each server which kinds of login it offers. It reads the server's greeting and hangs up without
logging in. A server that doesn't take a user and password is skipped, with a message, and is
never sent your password.

- The check takes a few milliseconds per host on a local network.
- A server that can't be asked (unreachable, or refusing connections) still opens in the viewer,
  which shows the real error.
- A server using the SecureVNC plugin announces only the plugin, not the login behind it, so the
  check can't tell the two kinds apart there.

## Opening many hosts

Select several hosts and press Enter: each opens in its own viewer window, grouped by profile, so
each profile's password is asked at most once. Opening more than five at once asks first.

A host without an address connects by its name only when the name is a valid computer name. A
name like "Ward 2A - Desk" can't be used as an address, so CapyPanel says so and offers to edit
the host.

## Manual connection

**Connect > Manual connection…** (Ctrl+M) reaches an address that isn't in the list. It opens
the Commands window with its **Host** box empty: type the address, pick a **Profile** and click
**Connect**. An address with a port in it, as in `192.0.2.77:5901`, uses that port. **Add to host
list…**, beside the box, puts the PC into the open list, and the commands in the window work on it
like on any other host (see [Commands on a host](commands.md#the-commands-window)).

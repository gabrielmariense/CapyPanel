# Connecting

CapyPanel opens remote screens through VNC viewers you install yourself. It never ships, bundles
or downloads them.

## Supported viewers

| Viewer | How CapyPanel gives it the password |
|---|---|
| **UltraVNC Viewer** | On its command line (the only way UltraVNC accepts one). Administrators of your PC can see command lines; the log never shows the password |
| **RealVNC Viewer** | Through a private pipe that only your Windows account can open, read once. Nothing is written to disk or put on the command line |

CapyPanel finds an installed viewer by itself: where Windows recorded the install (any folder),
the usual Program Files folders, then your PATH. A portable copy unzipped somewhere else isn't
found automatically; when a viewer is missing, CapyPanel asks you to install it or to locate its
`.exe`, and remembers the path for your account.

## Connection profiles

A network often mixes several setups: VNC servers that ask for a Windows account (UltraVNC's
MS-Logon), servers that ask only for a VNC password, encryption plugins, RealVNC on Raspberry Pis.
A **connection profile** says which one a host uses:

- the **viewer**;
- the **login**: user and password, or password only;
- **options** the viewer offers, such as UltraVNC's **SecureVNC plugin**.

### Built-in and shared profiles

- **Built-in:** one per viewer, **UltraVNC** and **RealVNC**, both with "user and password".
  They can't be changed or deleted, only duplicated.
- **Shared:** the ones you create in **Settings > Connections** (also **Connect > Connection
  profiles…**): a name, the viewer, the login (only the ones that viewer supports), the viewer's
  options (such as SecureVNC) and a port, blank for the viewer's own.
- Shared profiles are kept together in `data\profiles\` next to the app, beside the default
  list, so everyone who uses that copy of CapyPanel sees the same ones and they're easy to check.
  As for the default list, **Windows permissions decide who can change them**; everyone else
  sees them read-only.
- **The default profile**, used by hosts whose groups set none, is chosen in the same place and
  is the same for everyone. It starts as the built-in UltraVNC.
- Deleting a profile asks first, and says how many hosts and groups in the open list use it.
  Those then follow their group's profile, or the default.
- Lists made with version 0.8 may name its six built-in profiles; those keep working.

### Choosing a profile

- **On a group:** right-click the group > **Connection profile**. Every host inside follows it,
  including hosts in groups nested inside, unless they set their own.
- **On hosts:** in the host's **Connection profile** field, or right-click one or more hosts >
  **Connection profile**.
- **"From group"** means the host follows the nearest group that sets a profile. Hosts with no
  profile anywhere use the default.

The **Information** pane shows each host's profile and where it comes from, e.g.
"Raspberry Pis (from group “Raspberries”)".

A list stores only the profile's ID. Opening a list that names a profile your PC doesn't have
shows "not available on this PC" instead of guessing.

## Passwords

- CapyPanel asks for a profile's password the first time you connect with it, and **remembers it
  in memory, per profile**, until it closes. Hosts with another profile never receive it.
- Passwords are **never saved** to disk.
- **Connect > Forget typed passwords** clears them, e.g. after a typo: CapyPanel can't tell
  when a viewer rejects a password.
- Classic VNC passwords are at most 8 characters long, so the password box of an UltraVNC
  "password only" profile stops at 8.

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

**Connect > Manual connection…** (Ctrl+M) opens an address that isn't in the list, with the
profile and port you choose. Leave the port on "Default" to use the profile's.

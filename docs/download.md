# Download and updates

CapyPanel comes as a zip: unzip it and run **CapyPanel.exe**. There's no installer and you don't
need administrator rights. It runs on Windows 10 22H2 or Windows 11, 64-bit.

## Download CapyPanel

1. Open the [latest release](https://github.com/gabrielmariense/CapyPanel/releases/latest) on
   GitHub.
2. Under **Assets**, download `CapyPanel-<version>-windows-x64.zip` (about 38 MB).
3. Unzip it into a folder your account can write to, such as one in your Documents.
4. Open the folder and run **CapyPanel.exe**.

Remote Desktop works out of the box. For VNC you also need a viewer:
[UltraVNC](https://uvnc.com) or [RealVNC Viewer](https://www.realvnc.com/en/connect/download/viewer/).
[Getting started](getting-started.md) takes it from there.

??? note "Windows says it protected your PC"

    CapyPanel isn't signed yet, so the first time you run it Windows SmartScreen may say the
    publisher is unknown. Click **More info**, then **Run anyway**. Until it's signed, the SHA-256
    below is how you know the zip is the one GitHub built.

??? note "Check the download"

    Beside the zip, the release has `CapyPanel-<version>-windows-x64.zip.sha256`, a text file with
    the zip's SHA-256. In PowerShell, in the folder you downloaded to:

    ```
    (Get-FileHash .\CapyPanel-0.26.0-windows-x64.zip).Hash
    ```

    The letters it prints must be the ones in the `.sha256` file (upper or lower case doesn't
    matter). If they differ, the file was changed or cut short: download it again.

??? note "Where your settings live"

    Your settings, your lists and your saved logins aren't in the app's folder: they're in
    `C:\ProgramData\CapyPanel` (see [Where CapyPanel keeps its files](settings-and-files.md#where-capypanel-keeps-its-files)).
    So you can move the folder, or replace it with a newer one, and nothing is lost.

    For a USB stick or a shared folder, put an empty file named `capypanel.portable` next to
    **CapyPanel.exe**: everything is then kept in a `userdata` folder beside it instead.

??? note "Starting it twice"

    One copy of CapyPanel runs per Windows user. Starting it again, from the folder, a shortcut or
    the taskbar, brings the open window to the front, out of the tray too. Each person signed in to
    the PC can run their own.

## Update CapyPanel

When a newer release is out, an **Update 0.26.1** button shows at the right end of the menu bar.

![The Update CapyPanel window: CapyPanel 0.26.1 is out, its notes, and Skip this version, Later and Install and restart](images/update-window-dark.png)

1. Click it. The **Update CapyPanel** window shows what changed.
2. Click **Install and restart**. CapyPanel downloads the zip, closes, and starts again in the new
   version.
3. The window then says "Updated from 0.26.0 to 0.26.1."

**Later** only closes the window: the button stays, and comes back at the next start while that
release is the newest. **Skip this version** hides the button until a newer release comes out
(**Help > Check for updates…** still shows it); the choice is only yours. While it downloads,
**Later** reads **Cancel** and stops the download.

??? note "When CapyPanel looks for updates"

    By default CapyPanel asks GitHub (api.github.com) about 15 seconds after every start, then once
    a day while it stays open. **Settings > CapyPanel > General > Updates** has **At every start**,
    **Once a day**, **Once a week** and **Off**. It's one choice for everyone on this PC (see
    [Settings and files](settings-and-files.md#updates)). **Help > Check for updates…** looks
    right away, whatever is set, and also says when you're up to date.

    Only the question goes to GitHub. Nothing is downloaded until you click **Install and
    restart**.

??? note "What Install and restart does"

    1. It downloads the zip and checks it against its SHA-256.
    2. If a tool is busy, such as a printer Refresh or a profile being deleted, it waits for it
       ("Waiting for CapyPanel to finish what it's doing…") or asks you first.
    3. CapyPanel closes. A small helper swaps the app's files for the new ones and starts the new
       version.
    4. If the new version won't start, the helper puts the old one back, and the window says why.

    Your settings, lists and saved logins are never touched.

## Run CapyPanel from source

For developers, or to try a change before it's released, you need
[uv](https://docs.astral.sh/uv/), which installs Python and everything else:

```
git clone https://github.com/gabrielmariense/CapyPanel.git
cd CapyPanel
uv run capypanel
```

The first run downloads Python and the libraries; later runs start right away. A copy run from
source doesn't update itself: use `git pull`. [Contributing](https://github.com/gabrielmariense/CapyPanel/blob/main/CONTRIBUTING.md)
has the rest.

## Messages you may see

| Message | What it means | What to do |
|---|---|---|
| "Couldn't check for updates." | GitHub didn't answer, or the PC isn't online | Try **Help > Check for updates…** later |
| "The download doesn't match its SHA-256: it was changed or cut short." | The zip that arrived isn't the one GitHub built | Click **Install and restart** again |
| "CapyPanel can't install it from here (CapyPanel can't write to …). Download the zip from the release page and unpack it in place of this one." | Your account can't write to the folder CapyPanel is in, such as Program Files | Unzip the new version over the old one yourself, or move CapyPanel to a folder you can write to |
| "This copy runs from source: update it with git, or download the zip from the release page." | You started CapyPanel with `uv run` | `git pull`, or switch to the zip |
| "The update to 0.26.1 didn't go in, so this is still 0.26.0: …" | The new version wouldn't start, so the old one was put back | Read the reason after the colon; **Report a problem** if it isn't clear |
| "CapyPanel is already running for EXAMPLE\user, but its window couldn't be brought forward: …" | Your other copy is open in another Windows session, or isn't answering | Close it there, or end it in Task Manager, then start CapyPanel again |

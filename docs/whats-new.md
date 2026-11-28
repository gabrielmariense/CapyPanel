# What's new

The changes in each release that you'll notice. The
[releases on GitHub](https://github.com/gabrielmariense/CapyPanel/releases) have the downloads.

## 0.31.1 <a id="whats-new-0311"></a>

- On a new install, the UltraVNC profile leaves the password to UltraVNC Viewer's own window, so
  it's no longer on a command line, which security software often logs. The first Connect with it
  says so once. Profiles already on your PC stay as they are. See [Set up connection
  profiles](hosts/connecting.md#connecting-set-up-connection-profiles).
- A connection profile's window shows only the rows its tool uses. For UltraVNC and RealVNC,
  **Password** is **Asked for by** the viewer or **Saved in CapyPanel**, and saving it for UltraVNC
  asks first. The profiles list has a **Password** column.
- A new UltraVNC profile can't pick a viewer settings file any more. A profile that has one keeps
  it, and CapyPanel empties any password saved inside it.
- Restart Print Spooler no longer leaves a PC without its spooler. One still stopping after 30
  seconds isn't started, and CapyPanel says so; run it again in a minute, and it waits for the stop,
  then starts the spooler.
- The window that lists an update's changes no longer opens with the keyboard ring around its list,
  and neither does any window opened with the mouse.

## 0.31.0 <a id="whats-new-0310"></a>

- CapyPanel works from the keyboard alone in the main window, Settings, Hosts, Printers, SSH and
  Profile cleanup. A ring in the theme's accent shows where the keyboard is, and the menu key or
  Shift+F10 opens the menu a right-click opens. **View > Sort by** and **View > Columns** sort a
  table and pick its columns. See [Keyboard shortcuts](getting-started.md#start-keyboard-shortcuts).
- SSH's terminal finds text with **Find…** (Ctrl+Shift+F), saves it all to a file with **Save all
  the text…**, and rewraps its lines when the tab changes width.
- The terminal also gives the mouse to programs that ask for it, such as htop and mc, opens a web
  address with Ctrl+click, marks a tab with a bell when a server rings in it, and shows the cursor
  shape a program asks for. Settings › SSH › General sets its **Text size** and **Scrollback**.
- A connection can move to a window of its own, for a second monitor, and back again: **Move to a
  new window** on its tab's right-click menu or the terminal's. See [Move a connection to its own
  window](ssh/ssh.md#ssh-move-a-connection-to-its-own-window).
- **Connect in a separate window** can open ssh.exe in Windows Terminal or another terminal program:
  **Open in**, in Settings › SSH › General.
- The first time a server connects in a tab, a strip says ssh.exe will ask whether you trust it, and
  to type yes, not just y.
- **Import hosts…** reads **SSH port** and **SSH login** columns, and SSH's **Inventory** has it
  too. Hosts' Report writes both, ticked in **For Import**.
- In Hosts, right-click a host for **Open in SSH**, or several for **Open 3 hosts in SSH**.
- A portable copy's first start ends Home's guide with a card on what the copy keeps beside it, with
  **Open the userdata folder**.
- The main window opens sooner on a slow PC: about 0.7 s on one we measured.
- In the Windows themes, a Users or Power button that can't be used is grey all over. Before, its
  word stayed amber, so it looked clickable.
- CapyPanel ends as soon as you close it, even in the middle of a refresh. Before, it could keep
  running unseen until every host answered, and an update started meanwhile refused.
- When another CapyPanel from the same folder is still running, the update now says so. Before, it
  said an SSH connection was open in a separate window.
- Switching themes no longer risks closing CapyPanel after one of the Windows themes.
- In Printers, Details says why a printer refused or couldn't be read, under its status line.
  Settings › Printers › Warnings and supplies says what Offline, Stopped and Supply low mean, and
  Add printer says when to start an address with https://.
- The Report's greyed **Refresh** button says why on a line under it.

## 0.30.1 <a id="whats-new-0301"></a>

- In SSH and Profile cleanup, the short line beside the list's tab is now a thin line in the
  theme's border colour, like the toolbar's, so it no longer looks like a text cursor.
- In an SSH tab, a line too long for the tab, which goes on to the next row, now copies as one
  line and pastes whole. Before, the copy had a line break where it wrapped.

## 0.30.0 <a id="whats-new-0300"></a>

- F1, **Help > Help for this screen** or the new **?** at the bottom of the sidebar opens these
  pages at the part for the screen you're on. Settings has a **?** under its page list, and most
  windows have one first in their button row. F1 is kept for help, so it can't be given to another
  command. See [Get help, or report a
  problem](getting-started.md#start-get-help-or-report-a-problem).
- Warnings and errors have **What does this mean?** under their text. It opens the message's row on
  these pages, with what it means and what to do. A failed command's red strip, in Hosts and the
  Commands window, links its reason too, and so does SSH's when a connection ends with an error.
- CapyPanel starts faster with a long host list: with 480 hosts, it opened in about 30% less time in
  our tests. A tool you haven't opened yet fills its list when you open it.
- In Profile cleanup, select several profiles with Ctrl or Shift and a click, Shift and the arrows,
  or Ctrl+A, and **Space** ticks them all. A click on a tick box also makes its row the current
  one, so the arrows go on from there.
- In Profile cleanup's right panel, a card's last line, as in **and 7 more…**, is now a link: its
  menu lists the rest, and picking one goes to it.
- In Profile cleanup and SSH, the tab bar's scroll arrows and **▾** are buttons as tall as the tabs,
  and no tab shows cut off under them. With only the list open, the short line after its tab is
  gone.
- A connection profile's window keeps one size and the same rows whatever tool you pick. A row the
  tool doesn't use is greyed, and its tooltip says why. **Viewer settings** is now **Settings**.
- **Add an account** keeps its PC, group or tag field in place, greyed while **Every PC** is picked,
  so picking where it's used moves nothing.
- The UltraVNC starter profile now has **SecureVNC plugin** ticked. Starters are written on a PC's
  first start and by **Restore built-in…**; profiles already on a PC keep theirs.
- Checking whether a PC is on no longer connects to VNC's port, and CapyPanel asks each UltraVNC
  server its kinds of login once while it runs. UltraVNC servers up to 1.6.1 refuse a PC after six
  connections that don't log in, so a host you checked often and opened rarely could start refusing
  yours. If one still does, wait a minute and open it once from UltraVNC Viewer, or restart its
  UltraVNC service.
- Windows grow to fit their wrapped text when they open and when their rows change. **Open a
  folder** with a long path, **Restart** and **Shut down** were cut short before.
- Settings opens at 960 × 740 the first time, so its page list fits whole in Windows' own themes
  too.
- Clearer messages: a failed save says to close the file in Excel or another program and save again,
  and a list that's gone says it's no longer among your lists. When Windows Credential Manager
  refuses a change in Printers' settings, the box says nothing was changed.
- When saving how often to check for updates failed, picking the same choice again did nothing. Now
  it tries again.

## 0.29.0 <a id="whats-new-0290"></a>

- **SSH** is a fourth tool (Ctrl+4), for the servers, switches and other devices you reach over
  SSH. It shows the host list open in Hosts, checks which hosts answer on their SSH port, and
  opens a terminal on any of them in a tab beside the list, through Windows' own ssh.exe. See
  [The SSH tool](ssh/ssh.md).
- **Log in as** sets the account ssh.exe signs in with, for one host or a whole group, from the
  Details panel or a right-click.
- **Connect in a separate window** opens ssh.exe outside CapyPanel. After an error, the window
  stays open until you press a key, so you can read why.
- **Inventory > Import printers…** adds many printers at once: from a list of names and
  addresses, a Printers Report, or Windows' own printer list (`Get-Printer`). An empty printer list
  offers it too.
- Home's four tiles sit in two even rows.
- Profile cleanup also closes a tab with Ctrl+Shift+W, as SSH does.
- In the Commands window, **Add to host list…** is always there. When there's nothing to add, it's
  greyed and its tooltip says why, such as where the PC already is in the list.
- In Hosts' and Printers' menus, the Refresh items use F as their underlined letter, so R stays
  Remove's.
- The boxes Manual connection opens, such as its password prompt, show over it, so it no longer
  falls behind the main window.
- An update that finds one of CapyPanel's files in use, by a CapyPanel in another Windows session
  or an antivirus scan for instance, now stops with nothing changed, and CapyPanel opens as it
  was. Before, such an update could leave CapyPanel unable to start.

## 0.28.1 <a id="whats-new-0281"></a>

- User profiles is now **Profile cleanup**, a name that says what it's for. Its key, Ctrl+3,
  stays.
- In Hosts, right-click one or more hosts for **Open in Profile cleanup**: each opens there in a
  tab of its own, scanned.
- Type a PC that isn't in Hosts' list into the search box, and **Connect to DESK-07…** opens the
  manual connection with it filled in. Profile cleanup's **Scan** button now shows the same way,
  even while other hosts match part of the name.
- **Connect with**, in the Details panel, ends with **Connection profiles…**, which opens their
  settings.
- Tooltips and the Printers guide show a command's key as it is now, so a key you changed shows
  there too.
- In Profile cleanup, the host list and the panels on the right start level with the Groups panel.
- The field where you press a new key keeps its words centred and in place when a key is refused,
  and in a narrow Settings window the row you're changing stays in view.

## 0.28.0 <a id="whats-new-0280"></a>

- **Settings > CapyPanel > Keyboard shortcuts** is new: give a command the key you want, or take
  its key away. Hosts and Printers keep their own keys, even for a command both have, and the
  menus show your keys at once.
- The update window is new. It shows your version and the new one side by side, each change on
  its own line, and the download's progress at the bottom; after the restart it says **Update
  installed**.
- Checking for updates works on PCs where it failed with "CERTIFICATE_VERIFY_FAILED": Windows now
  checks GitHub's certificate itself, as Edge does. On 0.27.1 with that error, open
  https://api.github.com in Edge once, then update the usual way.
- In the Commands window, **Profile**, a gear for the connection profiles and **Connect** sit on
  the top line beside **Host**, and **Add to host list…** moved to the bottom left.
- The User profiles table no longer has a **Kind** column. A profile's kind is still in its
  details.

## 0.27.1 <a id="whats-new-0271"></a>

- An update no longer stops on a file an earlier update left behind. Copies that couldn't update
  from 0.26.4, with "Access denied", update straight to 0.27.1, with nothing to clean up by hand.

## 0.27.0 <a id="whats-new-0270"></a>

- **Settings > Printers > Warnings and supplies** has a new **Warnings** table: tick which
  problems count in CapyPanel's warnings and which send a Windows notification, reason by reason.
  It replaces the **Windows notification** choice, which carries over.
- What warns by default changed. A printer out of paper or stopped without saying why no longer
  warns (tick **Out of paper** or **Stopped** to bring them back), a door open or a tray pulled out
  never does, and a supply at the low level now also sends a notification.

## 0.26.4 <a id="whats-new-0264"></a>

- **Install and restart** now checks the new version before CapyPanel closes, then says CapyPanel
  will open again by itself in a few seconds. While the files are swapped, the splash says
  "Updating to 0.26.4…".
- An update keeps its working files in Windows' app data folder, never beside CapyPanel's folder,
  and deletes them once it's done. The `CapyPanel.update` and `CapyPanel.previous` folders that
  earlier updates left there are removed at the next start.

## 0.26.3 <a id="whats-new-0263"></a>

- No changes in the app: a release to try 0.26.2's update windows.

## 0.26.2 <a id="whats-new-0262"></a>

- When CapyPanel finds a newer release on its own, the update window opens by itself with the
  release notes, in CapyPanel's language. It looks about a second after it starts.
- After **Install and restart**, CapyPanel opens with a window saying the update went in, or why
  it didn't.

## 0.26.1 <a id="whats-new-0261"></a>

- The window title shows only the version, as in "Default — CapyPanel 0.26.1". The build number
  and the commit are in **Help > About CapyPanel**.

## 0.26.0 <a id="whats-new-0260"></a>

The first release you can download.

- **A zip to download.** Unzip it and run **CapyPanel.exe**: no installer, no administrator
  rights. Each release has the zip's SHA-256 beside it (see [Download and updates](download.md)).
- **Updates from inside the app.** When a newer release is out, an **Update** button shows on the
  menu bar. **Install and restart** downloads it, checks it and swaps the files; your settings,
  lists and logins stay as they are. CapyPanel looks at every start, or once a day, once a week, or
  never, as **Settings > CapyPanel > General > Updates** says.
- **Guides.** The first time each screen opens, a few cards point out what's on it, on a sample PC
  or printer, with the rest of the window dimmed. **Help > Guide to this screen** shows a guide
  again, and **Help > Show all the guides again** brings them all back.
- **A warning before User profiles' first use**, saying what it deletes. **Continue** works once
  you tick that you understand.
- **What's for everyone on this PC.** In Settings, the sections that are the same for everyone who
  uses CapyPanel on the PC say **Everyone on this PC**, and say who can change them (see
  [Settings for everyone on this PC](settings-and-files.md#find-a-setting)).
- **One copy per person.** Starting CapyPanel again brings the open window forward, out of the tray
  too.
- **Starting.** A splash shows while CapyPanel loads, then the window comes to the front, ready to
  type in. The first start uses the language Windows is shown in.
- **Closing.** With **When closing** set to **Ask each time**, the ✕ asks every time.
- **Colours.** Warnings read clearly in every theme, light ones included, and so do Printers' dots
  and supply bars. Graphite and Paper have the same corners as the other themes.
- **Quick commands** keep one order, the Commands window's, on the Details panel and in the
  right-click menu.
- **Refresh all** carries on when a PC refuses an account that other PCs accepted. PCs that refused
  last time are tried last.

Fixed:

- Ticking a quick command could close CapyPanel.
- In User profiles, **Last used** was sometimes blank.
- In the Windows themes, tick boxes in lists didn't show their box.
- In Portuguese, User profiles' **Review** state was called "Verificar"; it's "Revisar" now.

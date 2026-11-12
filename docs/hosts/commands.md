# Commands on a host

A host's commands are the everyday jobs you'd otherwise do from a console: open a PC's C: drive,
see what's installed, message or log off whoever is using it, restart it, or unstick its
printing. They work on one host at a time. Nothing is installed on the other PC: every command uses
Windows' own remote functions.

![The Details panel: the fixed row of buttons, the quick commands under it, then Connection, Logged on and PC facts](../images/commands-details-dark.png)

## Run a command on a host

1. Select the host.
2. Click a button in the Details panel, or right-click the host, or open **Commands ▾** on the
   toolbar.
3. Commands that disturb whoever is using the PC are amber, and always ask first.

The Details panel's first row is always **Refresh**, **Commands** (the
[Commands window](#the-commands-window)), **Users ▾** (log off or disconnect someone) and **Power ▾**
(restart or shut down). Your [quick commands](#choose-your-quick-commands) follow, four to a row.

??? note "Every place a command can start"

    - **Right-click a host:** **Connect** in bold, **Refresh host**, your first four quick
      commands, then **All commands…**, **Copy ▸**, **Edit…**, **Move to ▸**, **Tags ▸** and
      **Remove**. With several hosts selected the menu holds what works on all of them:
      **Connect**, **Refresh {n} hosts**, **Commands run as ▸**, **Copy ▸**, **Move to ▸**, **Tags
      ▸** and **Remove**.
    - **The toolbar:** **Commands** opens the Commands window for the selected host. Its arrow
      lists every command by group (**Check**, **Folders**, **Admin tools**, **Users**,
      **Printers** and **Power**) and ends with **All commands…**.
    - **A person under Logged on:** right-click them in Details for **Send a message to {user}…**,
      **Disconnect {user}…** and **Log off {user}…**, then **Copy ▸**.
    - A tooltip gives each button's full name.

??? note "Which account a command uses"

    The one the Details panel's **Commands run as** names for the host: your own Windows login,
    unless an account is set for it (see
    [Use another account on some PCs](connecting.md#use-another-account-on-some-pcs)). Commands use
    file sharing, the session service, remote shutdown, the print spooler, the service manager,
    and WMI for the PC's facts, its programs and its mapped drives (see
    [How CapyPanel reads other PCs](checking.md#read-a-pcs-facts)).

    A command meant for the person at the PC, such as Send a message or the user's folder, reads
    "… (nobody signed in)" and is greyed when the host's last refresh, less than 10 minutes old,
    found nobody. Before any refresh, or once it's older, it stays usable.

## Choose your quick commands

![The Customize the details panel window on its Quick commands tab: every command by group in the Commands window's order, four ticked](../images/customize-dark.png)

1. Open **View > Customize the details panel…**, or right-click the Details panel.
2. On the **Quick commands** tab, tick the commands you want as buttons. Every change shows on the
   panel at once.

The buttons keep the Commands window's order, on the panel and in the right-click menu, so a
command is always in the same place.

Each admin picks their own: the choice is kept in your settings on this PC, never in the list.
CapyPanel starts with **C$ share**, **User's folder**, **Computer Management** and **Send a
message…**, and **Restore default…** goes back to those. The first four are also in the host's
right-click menu.

??? note "More about quick commands"

    - **Settings > Hosts > General > Details panel > Quick commands > Choose…** opens the same tab.
    - The tab lists every command by group, in the Commands window's order, each with its
      shortcut in grey and the word its button shows; ticking one doesn't move it. A line under
      the table counts them, as in "6 of 15 ticked · 2 rows on the panel", and another says "The
      first four ticked are also in a host's right-click menu."
    - Any of these can be a quick command: Status, Logged-on users, PC facts, Installed programs, C$
      share, User's folder, Startup folder, Open a path…, Computer Management, Event Viewer,
      Services, Send a message…, Mapped drives, Printers on this PC and Restart Print Spooler….
      "Restart, Shut down, Log off and Disconnect can't be quick commands: they cut someone off."

## Open a PC's folders and admin tools

These open something on *your* PC, pointed at the other one:

| Command | What it opens |
|---|---|
| **C$ share** (Ctrl+E) | The PC's C: drive in File Explorer |
| **{user}'s folder** (Ctrl+Shift+U) | The signed-in user's profile folder |
| **Startup folder** | The programs that start for every user who signs in |
| **Open a path…** (Ctrl+Shift+O) | Any folder on the PC, such as `D:\Logs` |
| **Computer Management** (Ctrl+Shift+M) | Windows' Computer Management, pointed at the PC |
| **Event Viewer** | The PC's event logs |
| **Services** | The PC's Windows services |

??? note "More about folders and paths"

    - A folder waits for the PC to answer before File Explorer opens, because Explorer itself can
      hang for half a minute on a PC that's off. The three Windows consoles open straight away and
      show their own error when the PC can't be reached.
    - **Open a path…** takes a path the way you already have it: as File Explorer copies it, quotes
      and all (`"D:\Logs\App"`), on another drive (`D:\Logs` or `D$\Logs`), on C: alone
      (`Users\Public`), or as a whole `\\PC\share\…` path. A line under the box shows what will
      open, as in "Opens \\DESK-02\D$\Logs\App". The box keeps the last 10 folders you opened.
    - A path that isn't a folder is refused, so a file is never opened, and so run, on your own PC.
    - Opening a folder says "Opened \\DESK-02\C$" in the status bar.

## Message, log off or disconnect someone

- **Send a message…** pops up on the screen of everyone signed in at the PC until they click OK,
  titled "Message from {your Windows user name}". Windows shows about 255 characters of it.
- **Log off** and **Disconnect** act on one person: right-click them under **Logged on**, or open
  **Users ▾**, which lists everyone signed in with **Log off…** and **Disconnect…** under each.

Both ask first, naming the person and where they're signed in. Log off warns that "Work they
haven't saved is lost."; Disconnect keeps their programs running for next time.

??? note "More about messages and users"

    - The message's recipients show as chips beside **To:**, whose tooltip says where each is signed
      in; disconnected sessions, and your own, aren't included.
    - **Users ▾** is greyed when nobody is signed in, or nobody was checked yet.
    - **Cancel** is the button that's ready to press in both questions.

## Restart or shut down a PC

![The Restart question: who is signed in, When set to Now, and the message box greyed](../images/commands-restart-dark.png)

1. **Power ▾ > Restart…** or **Shut down…**.
2. Pick **When**: **Now**, or **In 1 minute**, **In 5 minutes** or **In 15 minutes**, which send the
   people signed in a message with a countdown.
3. Click the amber button: **Restart now**, or **Restart** with a delay.

A delayed restart shows in the **Status** column, as "Restart at 2:37 PM", and as an amber strip in
Details with **Cancel restart**. Once the PC answers again, a Windows notification says
"{host} is back online".

![A host with a restart waiting: the Status column and the amber strip in Details, with Cancel restart](../images/commands-restart-waiting-dark.png)

??? note "More about restarts"

    - The window names whoever is signed in and what they stand to lose. With **Now**, the message
      box greys out ("No message: it restarts right away.") and a line warns that the PC restarts
      at once, with no warning on its screen.
    - The delayed message is prefilled as "This PC restarts in 5 minutes. Please save your work."
      and is yours to change.
    - The keyboard starts on **When**: the arrow keys pick, **Tab** goes to the message, then to the
      amber button, where **Enter** runs it. Enter anywhere else is **Cancel**, the default button.
    - The amber strip reads "Restarts at 2:37 PM" and "You asked at 2:32 PM. bruno got your
      message." **Power > Cancel the pending restart** does the same as **Cancel restart**.
    - After the restart, CapyPanel looks the PC up every 15 seconds. The notification adds "It
      restarted at 2:37 PM and answered again at 2:39 PM. Click to show it."; the click selects
      the host. CapyPanel stops watching 20 minutes after the restart time.

## Fix a PC's printing

![The printers installed on a host: printer, driver, port, status and jobs, with Clear queue and Restart Print Spooler](../images/commands-printers-dark.png)

1. **Printers on this PC** lists the PC's printers: **Printer**, **Driver**, **Port**, **Status**
   and **Jobs**.
2. Pick a stuck printer and click **Clear queue…** to delete the documents waiting on it.
3. Or click **Restart Print Spooler…**, which stops every printer on that PC for a few seconds;
   documents waiting stay, and print once it's back.

Both ask first. These are the PC's own printers, not the ones a user added from a print server, and
not the network printers of the [Printers tool](../printers/printers.md).

## See what's installed and mapped

- **Installed programs** lists the programs installed for every user of the PC: **Name**,
  **Publisher**, **Version** and **Installed on**, with **Search programs**, **Copy list**, **Export
  CSV…** and **Read again**.
- **Mapped drives** lists the network drives saved for each person signed in: **Person**,
  **Drive** and **Path**. "These are the drives that come back at every sign-in."

![Mapped drives on a host: each person signed in, their drive letters and where each one points](../images/commands-drives-dark.png)

??? note "More about programs and drives"

    - Windows' own parts and its updates are left out of the programs, and CapyPanel never asks
      Windows through `Win32_Product`, which repairs every program it lists as it goes.
    - The programs' CSV opens in the spreadsheet your PC uses for CSV files, with the same guard
      against formulas as the host report has.
    - Mapped drives are read from each person's part of the PC's registry over WMI; nothing is run
      on the PC. A person with none reads "No saved drives". **Copy list** puts the rows on the
      clipboard.

## The Commands window

![The Commands window: the Host box on top, the groups on the left, every command in the middle, what the picked one found on the right](../images/commands-window-dark.png)

The Commands window holds every command for one PC, with its answer beside it. Open it with the
**Commands** button, **All commands…**, or **Connect > Manual connection…** (Ctrl+M) for an address
that isn't in your list.

1. Pick or type the PC in the **Host** box on top.
2. Pick a command in the middle (arrow keys, or type to search) and press **Enter** or **Run**.
3. Read the answer on the right.

It's a window of its own, beside the main one: you can go back to the host list and leave it open.
A double-click only picks, so a risky command never runs by accident.

??? note "More about the Commands window"

    - The **Host** box lists the hosts the Hosts panel shows, as "DESK-02 · 192.0.2.12", and under
      **Recent** the addresses you typed before; `host:port` works. Picking another host changes the
      whole window to it, its **Profile** included. The title says "Commands · DESK-02", or "Manual
      connection · 198.51.100.40" for a typed address. **Add to host list…** shows beside the box
      for a typed address the open list doesn't have.
    - On the left, a **Search** box and the six groups. In the middle, each command with its
      shortcut in grey; the picked one grows to show what it does.
    - On the right, the answer laid out as the Details panel lays it out. Printers, programs and
      mapped drives show as tables: right-click a printer to clear its queue or copy the row, and a
      program to copy or export, or open the list in its own window with a search.
    - Asking for another host's Commands turns the window to that host, and each host's answers are
      kept while the window stays open.
    - It opens at 1120 × 620 the first time and can be resized: wider, the commands and the answers
      share the extra room; narrower, the answers keep their width and the command list scrolls
      sideways. It opens again at the size you left it at.

## Messages you may see

![The strip above the host table after a command failed, with Try another account](../images/commands-strip-failed-dark.png)

A command that worked says so in green above the host table, as in "Message sent to bruno on
DESK-02.", and the strip closes by itself. One that failed says so in red, with Windows' own reason,
and stays until you close it.

| Message | What it means | What to do |
|---|---|---|
| "Couldn't log off bruno on DESK-02: access denied. It needs an admin account on that PC." | The account isn't an administrator there | **Try another account…** asks for one, and for which PCs, then runs the command again |
| "… (nobody signed in)" on a greyed command | The last refresh, under 10 minutes old, found nobody at the PC | Refresh the host if someone has signed in since |
| "there's no folder there." | The path in **Open a path…** isn't a folder | Check the path |

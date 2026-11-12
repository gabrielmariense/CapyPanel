# The User profiles tool

Every person who signs in to a Windows PC leaves a profile behind: a folder under `C:\Users` and an
entry in the registry. On shared PCs they pile up for years and fill the disk. The **User
profiles** tool (**Ctrl+3**) shows a PC's profiles, says which can be deleted and why the others
can't, counts their size, and deletes the ones you tick, on several PCs at once.

It uses the hosts of the list open in Hosts, and reads each PC with the account its **Commands run
as** names, which must be an administrator there (see
[Use another account on some PCs](../hosts/connecting.md#use-another-account-on-some-pcs)). Nothing
is installed or run on the PCs, and scanning only reads.

## Scan a PC's profiles

![The Hosts tab: the hosts of the picked group with their status, profiles, how many can be deleted and their scan; Progress and the selected host on the right](../images/profiles-hosts-tab-dark.png)

1. On the **Hosts** tab, pick a group on the left.
2. Double-click a host, or press **Enter**, to scan it in a tab of its own.
3. To scan several, pick them and click **Scan** on the toolbar ("Scan 3 hosts"): each opens in a
   tab behind.

A host that isn't in the list can be scanned too: type its name in the search box, and the table
offers **Scan** with it.

??? note "More about the Hosts tab and tabs"

    - The table shows **Name**, **Address**, **Status**, **Profiles**, **Can be deleted**
      (**Deletable** when narrow) and **Scan**, which says when a host was scanned or where its
      scan is ("scanning…", "deleting 2 of 3", "didn't answer"). The **Search name, address** box
      looks through every host of the list, whatever the group. The tab never scans by itself.
    - **Middle-click** a host, or press **Ctrl+Enter**, to open it in a tab behind and stay on the
      list. Right-click a host for **Open**, **Scan**, **Refresh host**, **Copy name** and **Copy
      address**. **Refresh all** checks whether each host shown answers, as in Hosts.
    - On the right, **Progress** follows every host in a tab, as in "4 hosts in tabs · 2 working ·
      2 done". Under it, **Hosts shown** sums up the picked group, and **Ticked in tabs** lists the
      hosts with profiles ticked; a click goes to its tab. With a host picked, the card shows its
      **Address**, **Group**, **Scanned at** and **As**, the account.
    - The Groups panel is read only here: groups are made in Hosts.
    - Tabs never reorder themselves: a new one opens at the right end, and the **▾** at the end of
      the tab bar lists them all. Right-click a tab for **Close**, **Close the others** and **Close
      the finished ones**; a middle-click closes one too. A tab can't be closed while it's deleting.
    - Up to four hosts are read or counted at a time, across every tab; the others wait their turn.

## See which profiles can be deleted

![A host's tab: the filters, the profiles table with three ticked rows outlined in amber, and Ticked to delete on the right](../images/profiles-host-tab-dark.png)

A host's tab lists its profiles with **User**, **Last used**, **Size**, **Kind** and **State**:

| State | What it means |
|---|---|
| **Can be deleted** | "Nobody is signed in to it, it isn't one of Windows' own, and it's in the Users folder." |
| **In use** | "This person is signed in now. It can only be deleted after they sign out." |
| **Protected** | "It's one of Windows' own. It's never deleted here." The built-in Administrator is one of them |
| **Outside Users** | The folder isn't in the Users folder, and CapyPanel only deletes profiles there |
| **Review** | "A .bak entry: a profile that failed to load. CapyPanel never deletes these; the fix is by hand, in the registry." |

Rows that can't be deleted are greyed and have no tick box. To see the old ones first, set **Unused
for:** to 3 or 6 months, or a year.

??? note "The filters and the columns"

    - **Hide Windows' own**, on to begin with: "Public, Default, the built-in Administrator and the
      like: never deleted here".
    - **Only leftovers**: "Only registry entries without a folder and folders without a registry
      entry".
    - **Unused for:** **Any time**, or at least 1, 3 or 6 months, or 1 year. A profile with no date
      at all is left out once this is set. At the right end, how many rows show ("12 of 15 shown"),
      or how many are ticked.
    - **User** is the account, as `DOMAIN\user`; one Windows no longer knows shows its folder's name
      and "(unknown)". **Last used** is when the person last signed in or out, or the folder's own
      date when Windows wrote none. **Kind** is **Profile**, **Registry entry, no folder**,
      **Folder, no registry entry** or **.bak registry entry**.
    - The tab's header names the host, as "User profiles on DESK-03", with its address, when it was
      scanned and the account it was read as. **Scan again** reads the host afresh.

??? note "A profile's details"

    ![A profile's details: its state, account and SID, folder, last used, size and kind, with Tick to delete](../images/profiles-details-dark.png)

    The **ⓘ** at the end of a row, **Enter**, or the row's right-click **Details…** opens a window
    with its **State** and why, the **Account** and its **SID**, the **Folder** with its **Path**,
    **Last used**, **Folder changed**, **Size** and **Kind**. "Windows no longer knows this
    account; it was probably deleted." says so for an account that's gone. **Tick to delete**, at
    its foot, ticks the row from there.

## Count their size

Click **Calculate sizes** on the toolbar: it counts the size of each profile shown, and only reads.
**Stop the count** stops it at once, keeping the sizes already counted.

## Delete profiles

1. **Tick** the profiles to delete: the box, **Space**, or a double-click on the row. A ticked row
   is outlined in amber and reads **Will be deleted**; the **Ticked to delete** card on the right
   lists them with the total, as in "3 profiles · 12.4 GB".
2. Click **Delete 3 profiles…**, at the foot of the right panel or on the toolbar.
3. Read the list, type **DELETE** in the box, and click the amber button.

"This is **final**. With local profiles, each person's desktop and documents go too: there's no
recycle bin and no copy."

![Deleting on a host: one profile deleted, one being deleted, one queued, and the Deleting profiles card with Cancel the rest](../images/profiles-deleting-dark.png)

??? note "While it deletes"

    - Each host deletes one profile at a time, and checks the host again before each one: "anyone
      who signed in since the scan is skipped". The rows go from **Queued** to **Deleting…** to
      **Deleted**, **Skipped** or **Failed**, and the **Deleting profiles** card counts them.
    - **Cancel the rest** lets the profile under way finish and starts no other. When it's over,
      the card reads **Deletion finished**, with what was freed, and **Open the history**.
    - Windows' own profiles and the built-in Administrator are never deleted, and a `.bak` entry is
      left for you to fix by hand.
    - Until **DELETE** is typed, **Cancel** is the default button; then Enter presses the amber one.
    - Quitting CapyPanel while a host is deleting asks first (see
      [Getting started](../getting-started.md#close-capypanel-or-keep-it-in-the-tray)).

??? note "The history"

    Every delete, done or not, goes into a history of its own, one file per Windows user:
    `logs\<you@DOMAIN>.user-profiles.log` in CapyPanel's folder (see
    [Settings and files](../settings-and-files.md#where-capypanel-keeps-its-files)). It says when, on
    which PC, whose profile and how it ended.

??? note "How profiles are read and deleted"

    Profiles are read over WMI, and deleted by Windows' own profile removal on that PC, asked
    through WMI too (see [How CapyPanel reads other PCs](../hosts/checking.md#read-a-pcs-facts)).

## Messages you may see

When a host can't be read, its tab says why in red, with **Try again**.

| Message | What it means | What to do |
|---|---|---|
| "{host} didn't answer" | The PC is off or unreachable | Check it's on, then **Try again** |
| "{host} refused the account {account}" | The account isn't accepted there | **Try another account…** |
| "PowerShell couldn't start on your PC" | Your own PC stopped PowerShell, often an antivirus | See [How CapyPanel reads other PCs](../hosts/checking.md#read-a-pcs-facts) |
| "{host} waits for its turn" | Four hosts are already being read or counted | Nothing: it starts by itself |
| "No host of the list with “…”." | The name you typed isn't in the list | **Scan** it anyway with the button offered |

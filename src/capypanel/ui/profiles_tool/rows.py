"""What the User profiles page says about a profile, with no window involved: the names of
kinds and states, why a row can or can't be deleted, the filters above the table, and how dates
and sizes read."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from PySide6.QtCore import QDate, QLocale

from capypanel.core import i18n
from capypanel.core.i18n import N_, _, ngettext, pgettext
from capypanel.core.remote.access import Reason, RemoteError
from capypanel.core.remote.user_profiles import Kind, Profile, Scan, State
from capypanel.ui.icons import STATUS_COLORS

MB, GB = 1024**2, 1024**3

KIND_NAMES = {
    Kind.PROFILE: N_("Profile"),
    Kind.ENTRY: N_("Registry entry, no folder"),
    Kind.FOLDER: N_("Folder, no registry entry"),
    Kind.BACKUP: N_(".bak registry entry"),
}
KIND_WHY = {
    Kind.PROFILE: N_("The folder and the registry entry, as Windows lists it."),
    Kind.ENTRY: N_(
        "The registry entry exists, but its folder is gone. Deleting removes only the leftover "
        "in the registry."
    ),
    Kind.FOLDER: N_(
        "The folder exists, but no registry entry points to it. Deleting removes the folder."
    ),
    Kind.BACKUP: N_("A registry entry with .bak in its name, and its folder."),
}
STATE_NAMES = {
    State.IN_USE: N_("In use"),
    State.PROTECTED: N_("Protected"),
    State.OUTSIDE: N_("Outside Users"),
    State.REVIEW: N_("Review"),
}
IN_USE_BLUE = "#3b82f6"  # as the status dots, the same in every theme
STATE_COLORS = {
    State.READY: STATUS_COLORS["online"],
    State.IN_USE: IN_USE_BLUE,
    State.PROTECTED: STATUS_COLORS["offline"],
    State.OUTSIDE: STATUS_COLORS["offline"],
    State.REVIEW: STATUS_COLORS["attention"],
}
STATE_ORDER = (State.READY, State.REVIEW, State.IN_USE, State.OUTSIDE, State.PROTECTED)
MONTHS = (0, 1, 3, 6, 12)  # "Unused for": any time, then at least this many months


def state_name(state: State) -> str:
    if state is State.READY:  # its own entry: Portuguese says "Pronto" here, "Pronta" of a printer
        return pgettext("profile", "Ready")
    return _(STATE_NAMES[state])


def state_why(profile: Profile, root: str) -> str:
    """Why a row is in its state, in a sentence."""
    if profile.state is State.OUTSIDE:
        return _(
            "It's outside the Users folder. CapyPanel only deletes profiles inside {folder}."
        ).format(folder=root)
    return {
        State.READY: _(
            "It can be deleted: nobody is signed in to it, it isn't one of Windows' own, and "
            "it's in the Users folder."
        ),
        State.IN_USE: _(
            "This person is signed in now. It can only be deleted after they sign out."
        ),
        State.PROTECTED: _("It's one of Windows' own. It's never deleted here."),
        State.REVIEW: _(
            "A .bak entry: a profile that failed to load. CapyPanel never deletes these; the "
            "fix is by hand, in the registry."
        ),
    }[profile.state]


def user_text(profile: Profile) -> str:
    """The account's name; one Windows no longer knows says so beside the folder's name."""
    return profile.user if profile.known else _("{name}  (unknown)").format(name=profile.user)


def months_text(months: int) -> str:
    if not months:
        return _("Any time")
    if months == 12:
        return _("1 year")
    return ngettext("{n} month", "{n} months", months).format(n=months)


# ---- the filters ----


@dataclass(frozen=True)
class Filters:
    hide_own: bool = True  # Windows' own (Public, Default…): about half the rows, never deletable
    leftovers: bool = False  # only entries without a folder and folders without an entry
    months: int = 0  # only rows not used for this long; 0: any


def used(profile: Profile) -> datetime | None:
    """When a row was last used, for "Unused for": the last sign-in or sign-out Windows wrote
    down, or the folder's own date when it has none (a folder without an entry never has)."""
    return profile.last_used or profile.modified


def visible(
    profiles: Iterable[Profile], filters: Filters, now: datetime | None = None
) -> list[Profile]:
    """The rows the filters leave. With "Unused for", a row with no date at all is left out:
    nothing says it's older than the cut."""
    cut = _months_before(now or datetime.now(UTC), filters.months) if filters.months else None
    shown = []
    for profile in profiles:
        if filters.hide_own and profile.state is State.PROTECTED:
            continue
        if filters.leftovers and profile.kind not in (Kind.ENTRY, Kind.FOLDER):
            continue
        if cut is not None:
            last = used(profile)
            if last is None or last > cut:
                continue
        shown.append(profile)
    return shown


def _months_before(now: datetime, months: int) -> datetime:
    month = now.year * 12 + now.month - 1 - months
    year, month = divmod(month, 12)
    day = min(now.day, 28)  # every month has one
    return now.replace(year=year, month=month + 1, day=day)


# ---- how values read ----


def date_text(when: datetime | None) -> str:
    """A day as the table shows it, in this PC's time: 10/11/2026 (11/10/2026 in English)."""
    if when is None:
        return ""
    local = when.astimezone()
    language = i18n.language()
    pattern = "MM/dd/yyyy" if language.startswith("en") else "dd/MM/yyyy"
    return QLocale(language).toString(QDate(local.year, local.month, local.day), pattern)


def size_text(size: int) -> str:
    """ "3.4 GB" from a tenth of a gigabyte up, megabytes under it."""
    locale = QLocale(i18n.language())
    if size >= GB // 10:
        value = size / GB
        return _("{n} GB").format(n=locale.toString(value, "f", 1 if value < 100 else 0))
    return _("{n} MB").format(n=locale.toString(max(1, round(size / MB)) if size else 0))


# ---- the status bar ----


def status_text(scanned: Scan, name: str, sizes: dict[str, int]) -> str:
    """ "DESK-03 · 15 profiles · 9 can be deleted · 12.4 GB counted"."""
    total = len(scanned.profiles)
    ready = sum(p.ready for p in scanned.profiles)
    parts = [
        name,
        ngettext("{n} profile", "{n} profiles", total).format(n=total),
        ngettext("{n} can be deleted", "{n} can be deleted", ready).format(n=ready),
    ]
    counted = sum(sizes.get(p.ident, 0) for p in scanned.profiles)
    if counted:
        parts.append(_("{size} counted").format(size=size_text(counted)))
    return " · ".join(parts)


def shown_text(shown: int, total: int) -> str:
    return _("{shown} of {total} shown").format(shown=shown, total=total)


# ---- a scan that failed ----


@dataclass(frozen=True)
class Failure:
    title: str  # "LAB-02 didn't answer"
    lines: Sequence[str]  # what it means, then that nothing was read
    status: str  # the status bar: "LAB-02 · didn't answer"
    another_account: bool  # offer "Try another account…"


def failure(error: BaseException, name: str, address: str, account: str) -> Failure:
    """What a failed scan says in the middle of the page."""
    nothing = _("Nothing was read.")
    if isinstance(error, RemoteError) and error.reason is Reason.UNREACHABLE:
        return Failure(
            _("{host} didn't answer").format(host=name),
            (
                _(
                    "There was no answer at {address}. The PC may be off or not on the network."
                ).format(address=address),
                nothing,
            ),
            _("{host} · didn't answer").format(host=name),
            another_account=False,
        )
    if isinstance(error, RemoteError) and error.reason in (Reason.REJECTED, Reason.NOT_ADMIN):
        return Failure(
            _("{host} refused the account {account}").format(host=name, account=account),
            (
                _(
                    "The PC answered, but this account isn't an administrator on it, or its "
                    "password changed."
                ),
                nothing,
            ),
            _("{host} · account refused").format(host=name),
            another_account=True,
        )
    if isinstance(error, TimeoutError):
        why = _("The PC answered, but reading took too long and was stopped.")
    elif isinstance(error, RemoteError):
        why = _("Windows error {code}.").format(code=error.code)
    else:
        why = str(error)
    return Failure(
        _("Couldn't read {host}'s profiles").format(host=name),
        (why, nothing),
        _("{host} · couldn't be read").format(host=name),
        another_account=isinstance(error, RemoteError),
    )

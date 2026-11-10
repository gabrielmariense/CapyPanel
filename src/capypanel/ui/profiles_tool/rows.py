"""What the User profiles page says about a profile, with no window involved: the names of
kinds and states, why a row can or can't be deleted, the filters above the table, and how dates
and sizes read."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from PySide6.QtCore import QDate, QLocale

from capypanel.core import i18n
from capypanel.core.i18n import N_, _, ngettext, pgettext
from capypanel.core.remote.access import Reason, RemoteError
from capypanel.core.remote.inventory import PowerShellBlocked
from capypanel.core.remote.user_profiles import (
    Deleted,
    Kind,
    Outcome,
    Profile,
    Scan,
    State,
    Why,
)
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
    if state is State.READY:  # its own entry: Portuguese says "Pode excluir"
        return pgettext("profile", "Can be deleted")
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


def status_text(scanned: Scan, name: str, ticked: Sequence[Profile], sizes: dict[str, int]) -> str:
    """ "DESK-03 · 15 profiles · 9 can be deleted · 3 ticked · 12.4 GB": the size is the ticked
    rows', once counted."""
    total = len(scanned.profiles)
    ready = sum(p.ready for p in scanned.profiles)
    parts = [
        name,
        ngettext("{n} profile", "{n} profiles", total).format(n=total),
        ngettext("{n} can be deleted", "{n} can be deleted", ready).format(n=ready),
    ]
    if ticked:
        parts.append(ngettext("{n} ticked", "{n} ticked", len(ticked)).format(n=len(ticked)))
        counted = sum(sizes.get(p.ident, 0) for p in ticked)
        if counted:
            parts.append(size_text(counted))
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
    if isinstance(error, PowerShellBlocked):
        return Failure(
            _("PowerShell couldn't start on this PC"),
            (
                _(
                    "Windows didn't let CapyPanel start PowerShell here to read {host}. An "
                    "antivirus may block it."
                ).format(host=name),
                nothing,
            ),  # fmt: skip
            _("{host} · PowerShell blocked on this PC").format(host=name),
            another_account=False,
        )
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


# ---- deleting ----


class Result(StrEnum):
    """Where a ticked row is in a delete run."""

    QUEUED = "queued"
    DELETING = "deleting"
    DELETED = "deleted"
    SKIPPED = "skipped"
    FAILED = "failed"


RESULT_NAMES = {
    Result.QUEUED: N_("Queued"),
    Result.DELETING: N_("Deleting…"),
    Result.DELETED: N_("Deleted"),
    Result.SKIPPED: N_("Skipped"),
    Result.FAILED: N_("Failed"),
}
RESULT_ICONS = {  # an icon and its colour: the status dots' colours
    Result.QUEUED: ("clock", STATUS_COLORS["offline"]),
    Result.DELETING: ("refresh", IN_USE_BLUE),
    Result.DELETED: ("circle-check", STATUS_COLORS["online"]),
    Result.SKIPPED: ("alert-triangle", STATUS_COLORS["attention"]),
    Result.FAILED: ("circle-x", STATUS_COLORS["stopped"]),
}
ENDED = (Result.DELETED, Result.SKIPPED, Result.FAILED)
_RESULTS = {
    Outcome.DELETED: Result.DELETED,
    Outcome.SKIPPED: Result.SKIPPED,
    Outcome.FAILED: Result.FAILED,
}


def result_of(done: Deleted) -> Result:
    return _RESULTS[done.outcome]


def confirm_word() -> str:
    """What the Delete window asks to be typed: DELETE (EXCLUIR in Portuguese)."""
    return pgettext("the word typed to confirm", "DELETE")


def confirms(typed: str) -> bool:
    """Whether the word was typed: any case, spaces around it ignored."""
    return typed.strip().casefold() == confirm_word().casefold()


def ended_text(done: Deleted, size: int | None) -> str:
    """How one delete ended, as the log's line says after the name: "deleted, 6.2 GB"."""
    if done.outcome is Outcome.DELETED:
        return _("deleted, {size}").format(size=size_text(size)) if size else _("deleted")
    why = {
        Why.IN_USE: _("signed in to the PC since the scan"),
        Why.GONE: _("it's no longer there"),
        Why.CHANGED: _("it changed since the scan; scan again"),
        Why.PROTECTED: _("it's one of Windows' own"),
        Why.NOT_READY: _("it can't be deleted"),
        Why.LEFT: _("some files couldn't be removed"),
        Why.ERROR: _("Windows refused, or the PC stopped answering"),
    }.get(done.why, "") if done.why is not None else ""  # fmt: skip
    word = _("skipped") if done.outcome is Outcome.SKIPPED else _("failed")
    if done.outcome is Outcome.FAILED and done.detail:
        if done.why is Why.ERROR:  # Windows' own words say more than ours
            return f"{word}, {done.detail}"
        return f"{word}, {why} ({done.detail})"
    return f"{word}, {why}" if why else word


def result_why(done: Deleted) -> str:
    """Details' sentence for a row that was in a delete run."""
    if done.outcome is Outcome.DELETED:
        return {
            Kind.ENTRY: _("Deleted: the leftover in the registry."),
            Kind.FOLDER: _("Deleted: the folder."),
        }.get(done.profile.kind, _("Deleted: the folder and the registry entry."))
    if done.outcome is Outcome.SKIPPED:
        if done.why is Why.IN_USE:
            return _(
                "Skipped: this person signed in to the PC after the scan. Nothing was deleted."
            )
        if done.why is Why.GONE:
            return _("Skipped: it was no longer there.")
        return _("Skipped: it wasn't what the scan saw any more. Scan again.")
    if done.why is Why.LEFT:
        return _("Failed: some files couldn't be removed.")
    return _("Failed: Windows refused, or the PC stopped answering.")


def counts_text(results: Iterable[Result]) -> str:
    """ "1 deleted, 1 skipped, 1 failed": only the ones that happened."""
    found = list(results)
    deleted, skipped = found.count(Result.DELETED), found.count(Result.SKIPPED)
    failed = found.count(Result.FAILED)
    parts = []
    if deleted:
        parts.append(ngettext("{n} deleted", "{n} deleted", deleted).format(n=deleted))
    if skipped:
        parts.append(ngettext("{n} skipped", "{n} skipped", skipped).format(n=skipped))
    if failed:
        parts.append(ngettext("{n} failed", "{n} failed", failed).format(n=failed))
    return ", ".join(parts)

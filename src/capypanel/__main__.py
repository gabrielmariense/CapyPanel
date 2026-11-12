"""Entry point: `python -m capypanel`, or the `capypanel` command."""

import logging
import sys
from collections.abc import Callable
from pathlib import Path


def close_splash() -> None:
    """The splash CapyPanel.exe's launcher shows (ui/branding/splash.png), once there's a window
    to see, or at once for the self-test, which shows none. From source there is none."""
    try:
        import pyi_splash  # type: ignore[import-not-found]  # only inside CapyPanel.exe
    except ImportError:
        return
    if pyi_splash.is_alive():
        pyi_splash.close()


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        close_splash()
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":  # see ui/selftest.py
        return _quietly(lambda: _self_test(Path(sys.argv[2])))
    if len(sys.argv) == 6 and sys.argv[1] == "--apply-update":  # see core/updates.py
        argv = sys.argv
        return _quietly(lambda: _apply_update(Path(argv[2]), int(argv[3]), argv[4], argv[5]))
    from capypanel.ui.app import run

    return run()


def _quietly(job: Callable[[], int]) -> int:
    """`job`, with nothing ever shown on screen: CapyPanel.exe has no console, so an error
    left uncaught would open a Windows box that waits for someone. It goes to the log."""
    try:
        return job()
    except BaseException:  # noqa: BLE001 -- the last word: nothing may reach the screen
        logging.getLogger("capypanel").exception("%s failed", sys.argv[1])
        return 1


def _self_test(report: Path) -> int:
    from capypanel.ui import selftest

    return selftest.run(report)


def _apply_update(app_dir: Path, pid: int, old_version: str, new_version: str) -> int:
    """The new version's exe, run from where its zip was unpacked: swaps it in for the old
    one once CapyPanel has closed, with the splash and "Updating to …" on screen meanwhile. It
    writes to the person's own log."""
    from capypanel.core import applog, i18n, settings, updates

    paths = settings.resolve_paths(app_dir)
    applog.setup_logging(paths.log_file)
    # Its words show on the splash, and in the new start's window when something goes wrong.
    i18n.set_language(settings.language_of(paths.settings_file))
    try:
        from capypanel.ui import update_splash
    except Exception:  # noqa: BLE001 -- without its window the swap still has to happen
        logging.getLogger("capypanel").exception("Update: no splash")
        close_splash()
        return updates.run_helper(app_dir, pid, old_version, new_version)
    return update_splash.run(app_dir, pid, old_version, new_version, close_splash)


if __name__ == "__main__":
    sys.exit(main())

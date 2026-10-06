"""Running one check on many hosts: a few at a time, stoppable, and careful with passwords.

While an account isn't proven yet, hosts go one by one, so a mistyped password is rejected by
one host instead of being tried on many (each rejection counts toward the account's lockout).
Callbacks run on the worker threads; the UI turns them into Qt signals."""

import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor

WORKERS = 8  # hosts read at the same time: quick for a group, light on the network


class Batch[T, R]:
    """`work(item)` for every item; `report(item, result, error)` after each one. When `halts`
    says an outcome must stop everything, the items not started yet are skipped."""

    def __init__(
        self,
        items: Sequence[T],
        work: Callable[[T], R],
        report: Callable[[T, R | None, Exception | None], None],
        *,
        halts: Callable[[R | None, Exception | None], bool] = lambda _r, _e: False,
        proves: Callable[[R | None, Exception | None], bool] | None = None,
        workers: int = WORKERS,
    ) -> None:
        self._items = list(items)
        self._work, self._report, self._halts = work, report, halts
        # None: nothing to prove, all in parallel from the start.
        self._proves = proves
        self._workers = workers
        self._stop = threading.Event()
        self.halted = False  # stopped by `halts`, not by stop()

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def run(self) -> None:
        """Blocks until every item ran or the batch stopped."""
        pending = list(self._items)
        if self._proves is not None:
            while pending and not self._stop.is_set():
                result, error = self._one(pending.pop(0))
                if self._proves(result, error):
                    break
        if not pending or self._stop.is_set():
            return
        with ThreadPoolExecutor(self._workers) as pool:
            for item in pending:
                pool.submit(self._guarded, item)

    def _guarded(self, item: T) -> None:
        if not self._stop.is_set():
            self._one(item)

    def _one(self, item: T) -> tuple[R | None, Exception | None]:
        try:
            result: R | None = self._work(item)
            error: Exception | None = None
        except Exception as e:  # reported per host; one host's failure never ends the batch
            result, error = None, e
        if self._halts(result, error):
            self.halted = True
            self._stop.set()
        self._report(item, result, error)
        return result, error

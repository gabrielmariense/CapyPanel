import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor

WORKERS = 8


class Batch[T, R]:
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
        self._proves = proves
        self._workers = workers
        self._stop = threading.Event()
        self.halted = False

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def run(self) -> None:
        pending = list(self._items)
        if self._proves is not None:
            # One by one until a host accepts the account: a mistyped password is then refused
            # once, not by every host at once, which could lock the account out.
            while pending and not self._stop.is_set():
                result, error = self._one(pending.pop(0), halting=True)
                if self._proves(result, error):
                    break
        if not pending or self._stop.is_set():
            return
        halting = self._proves is None
        with ThreadPoolExecutor(self._workers) as pool:
            for item in pending:
                pool.submit(self._guarded, item, halting)

    def _guarded(self, item: T, halting: bool) -> None:
        if not self._stop.is_set():
            self._one(item, halting=halting)

    def _one(self, item: T, *, halting: bool) -> tuple[R | None, Exception | None]:
        try:
            result: R | None = self._work(item)
            error: Exception | None = None
        except Exception as e:
            result, error = None, e
        if halting and self._halts(result, error):
            self.halted = True
            self._stop.set()
        self._report(item, result, error)
        return result, error

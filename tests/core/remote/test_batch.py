import threading
import time

from capypanel.core.remote.batch import Batch


def test_every_item_runs_and_is_reported_once() -> None:
    seen: list[int] = []
    lock = threading.Lock()

    def report(item: int, result: int | None, error: Exception | None) -> None:
        with lock:
            seen.append(item)
        assert result == item * 2 and error is None

    Batch(range(20), lambda n: n * 2, report).run()
    assert sorted(seen) == list(range(20))


def test_a_failure_is_reported_and_the_rest_still_run() -> None:
    errors: list[int] = []

    def work(n: int) -> int:
        if n == 3:
            raise RuntimeError("boom")
        return n

    def report(item: int, _r: int | None, error: Exception | None) -> None:
        if error is not None:
            errors.append(item)

    done = Batch(range(6), work, report)
    done.run()
    assert errors == [3] and not done.halted


def test_unproven_items_go_one_by_one_and_a_halt_skips_the_rest() -> None:
    # Like a typed password: the first host rejects it, so no other host ever sees it.
    tried: list[int] = []

    def work(n: int) -> str:
        tried.append(n)
        return "rejected"

    batch = Batch(
        range(10), work, lambda *_a: None,
        halts=lambda r, _e: r == "rejected", proves=lambda r, _e: r == "ok",
    )  # fmt: skip
    batch.run()
    assert tried == [0] and batch.halted and batch.stopped


def test_once_proven_a_refusal_is_that_item_s_and_the_rest_still_run() -> None:
    # A password one host accepted is right: a host refusing it later (a broken trust with the
    # domain) is reported like any failure, and every other host is still read.
    reported: list[tuple[int, str | None]] = []
    lock = threading.Lock()

    def report(item: int, result: str | None, _e: Exception | None) -> None:
        with lock:
            reported.append((item, result))

    batch = Batch(
        range(30), lambda n: "rejected" if n in (4, 17) else "ok", report,
        halts=lambda r, _e: r == "rejected", proves=lambda r, _e: r == "ok",
    )  # fmt: skip
    batch.run()
    assert sorted(item for item, _r in reported) == list(range(30))
    assert sorted(i for i, r in reported if r == "rejected") == [4, 17]
    assert not batch.halted and not batch.stopped


def test_once_proven_the_rest_run_together() -> None:
    running, most = 0, 0
    lock = threading.Lock()

    def work(n: int) -> str:
        nonlocal running, most
        with lock:
            running += 1
            most = max(most, running)
        time.sleep(0.05)
        with lock:
            running -= 1
        return "ok" if n >= 2 else "unreachable"

    order: list[int] = []
    Batch(
        range(12), work, lambda item, *_a: order.append(item), proves=lambda r, _e: r == "ok"
    ).run()
    assert order[:3] == [0, 1, 2]  # one by one until host 2 accepted the account
    assert most > 1 and sorted(order) == list(range(12))


def test_stop_skips_what_hasnt_started() -> None:
    started: list[int] = []
    batch: Batch[int, int]

    def work(n: int) -> int:
        started.append(n)
        batch.stop()
        return n

    batch = Batch(range(50), work, lambda *_a: None, workers=1)
    batch.run()
    assert started == [0] and batch.stopped and not batch.halted

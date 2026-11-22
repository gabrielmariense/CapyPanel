from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject

from capypanel.ui.hosts_tool.runner import Job

AT_ONCE = 4


@dataclass
class _Task:
    owner: object
    work: Callable[[], Any]
    done: Callable[[Any], None]
    failed: Callable[[BaseException], None]
    began: Callable[[], None] | None = None


def start(
    work: Callable[[], Any],
    done: Callable[[Any], None],
    failed: Callable[[BaseException], None],
    jobs: set[Job],
) -> None:
    """`jobs` holds the Job until it ends, or Qt would drop it halfway."""
    job = Job(work)
    jobs.add(job)

    def finish(value: object, error: object) -> None:
        jobs.discard(job)
        if isinstance(error, BaseException):
            failed(error)
        else:
            done(value)

    job.done.connect(finish)
    job.start()


class Pool(QObject):
    def __init__(self, at_once: int = AT_ONCE) -> None:
        super().__init__()
        self._at_once = at_once
        self._reads: list[_Task] = []
        self._counts: list[_Task] = []
        self._running = 0
        self._jobs: set[Job] = set()

    def read(
        self,
        owner: object,
        work: Callable[[], Any],
        done: Callable[[Any], None],
        failed: Callable[[BaseException], None],
        began: Callable[[], None] | None = None,
    ) -> None:
        self._reads.append(_Task(owner, work, done, failed, began))
        self._next()

    def count(
        self,
        owner: object,
        work: Callable[[], Any],
        done: Callable[[Any], None],
        failed: Callable[[BaseException], None],
    ) -> None:
        self._counts.append(_Task(owner, work, done, failed))
        self._next()

    def waiting(self, owner: object) -> int:
        return sum(t.owner is owner for t in (*self._reads, *self._counts))

    def drop(self, owner: object) -> None:
        self._reads = [t for t in self._reads if t.owner is not owner]
        self._counts = [t for t in self._counts if t.owner is not owner]

    def _next(self) -> None:
        while self._running < self._at_once and (self._reads or self._counts):
            task = (self._reads or self._counts).pop(0)
            self._running += 1
            if task.began is not None:
                task.began()

            def done(value: Any, task: _Task = task) -> None:
                self._running -= 1
                task.done(value)
                self._next()

            def failed(error: BaseException, task: _Task = task) -> None:
                self._running -= 1
                task.failed(error)
                self._next()

            start(task.work, done, failed, self._jobs)

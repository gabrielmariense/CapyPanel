"""Work off the main thread for the User profiles tool. Reads and size counts share one limit
across every tab, so many hosts open at once never walk a whole ward of PCs together; reads go
before counts. Deletes don't wait here: each host deletes one profile at a time on its own."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject

from capypanel.ui.hosts_tool.runner import Job

AT_ONCE = 4  # reads and counts running at the same time: walking a tree is mostly waiting


@dataclass
class _Task:
    owner: object  # who asked: what drop() matches
    work: Callable[[], Any]
    done: Callable[[Any], None]
    failed: Callable[[BaseException], None]
    began: Callable[[], None] | None = None  # its turn came: called just before it starts


def start(
    work: Callable[[], Any],
    done: Callable[[Any], None],
    failed: Callable[[BaseException], None],
    jobs: set[Job],
) -> None:
    """`work` on a background thread at once; its value or its error comes back on this one.
    `jobs` holds the Job until then, or Qt would drop it halfway."""
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
    """At most AT_ONCE pieces of work at a time; the rest wait in order, reads first."""

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
        """How many of `owner`'s are still waiting for a turn."""
        return sum(t.owner is owner for t in (*self._reads, *self._counts))

    def drop(self, owner: object) -> None:
        """`owner`'s work that hasn't started never will. Work under way ends on its own."""
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

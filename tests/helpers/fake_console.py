"""A stand-in for core/ssh/conpty.py's PseudoConsole, driven by the test: what the program prints
is queued with `prints`, its own end comes with `ends`, and what the terminal writes is kept in
`written`. It runs no program and reaches no network.

It signals as the real one does, only on the test's own thread: `on_ready` when output arrives
on an empty queue and once more at the output's end; `on_exit(code)` when the program ends. The
output ends only when the console is closed, as a real pseudo console's does. A close while the
program runs sends the output's end first and the exit after it, the order in which a terminal
that waited for the exit before the end never ended: the real one's two threads send either."""

from collections.abc import Callable, Mapping, Sequence

CTRL_C_EXIT = 0xC000013A  # what Windows gives a program its closed console ends


class FakeConsole:
    def __init__(
        self,
        argv: Sequence[str],
        cols: int,
        rows: int,
        *,
        on_ready: Callable[[], None],
        on_exit: Callable[[int], None],
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        max_pending: int = 1 << 20,
        flags: int = 0,
    ) -> None:
        self.argv = list(argv)
        self.size = (cols, rows)
        self.env = env
        self._on_ready = on_ready
        self._on_exit = on_exit
        self._out = bytearray()
        self._eof = False
        self.written: list[bytes] = []
        self.exit_code: int | None = None
        self.closed = False

    # ---- the test's side ----

    def prints(self, data: bytes) -> None:
        """The program prints `data`."""
        was_empty = not self._out
        self._out += data
        if was_empty:
            self._on_ready()

    def ends(self, code: int) -> None:
        """The program ends by itself, with `code`."""
        self.exit_code = code
        self._on_exit(code)

    # ---- the terminal's side, as PseudoConsole's ----

    def take(self, limit: int) -> bytes:
        data = bytes(self._out[:limit])
        del self._out[:limit]
        return data

    @property
    def pending(self) -> int:
        return len(self._out)

    @property
    def at_eof(self) -> bool:
        return self._eof and not self._out

    def write(self, data: bytes) -> None:
        if data and not self.closed:
            self.written.append(bytes(data))

    @property
    def running(self) -> bool:
        return self.exit_code is None

    def resize(self, cols: int, rows: int) -> None:
        if not self.closed:
            self.size = (cols, rows)

    def close(self) -> float:
        if self.closed:
            return 0.0
        self.closed = True
        self._eof = True
        self._on_ready()  # the output's end first...
        if self.exit_code is None:
            self.ends(CTRL_C_EXIT)  # ...then the program, which the close ended
        return 0.0

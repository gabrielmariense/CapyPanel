from collections.abc import Callable, Mapping, Sequence

from capypanel.core.ssh.conpty import WINDOWS, Engine

CTRL_C_EXIT = 0xC000013A  # a program's exit code when its console is closed


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
        engine: Engine | None = None,
    ) -> None:
        self.argv = list(argv)
        self.engine = engine or WINDOWS
        self.size = (cols, rows)
        self.env = env
        self._on_ready = on_ready
        self._on_exit = on_exit
        self._out = bytearray()
        self._eof = False
        self.written: list[bytes] = []
        self.exit_code: int | None = None
        self.closed = False

    def prints(self, data: bytes) -> None:
        was_empty = not self._out
        self._out += data
        if was_empty:
            self._on_ready()

    def ends(self, code: int) -> None:
        self.exit_code = code
        self._on_exit(code)

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
        self._on_ready()
        if self.exit_code is None:
            self.ends(CTRL_C_EXIT)
        return 0.0

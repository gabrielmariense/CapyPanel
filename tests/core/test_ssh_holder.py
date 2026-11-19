"""The separate window's holder, on a pretend console: nothing here opens a window or starts a
program. Line 12 runs the real one, with a stand-in in ssh.exe's place."""

import ctypes
import sys
from collections.abc import Iterator, Sequence
from types import SimpleNamespace

import pytest

from capypanel import __main__ as entry
from capypanel.core import i18n
from capypanel.core.ssh import ending, holder
from capypanel.core.ssh.holder import Request

SSH = [r"C:\Windows\System32\OpenSSH\ssh.exe", "-l", "root", "--", "192.0.2.41"]
STARTED = [("open", False), ("title", SSH[0]), "Ctrl+C", ("run", SSH)]


class FakeConsole:
    """Writes down what the holder asks of Windows; `code` is what the program ends with."""

    def __init__(self, code: int | OSError = 0, *, opens: bool = True) -> None:
        self.code, self.opens = code, opens
        self.steps: list[object] = []
        self.written = ""

    def open(self, *, attach: bool) -> bool:
        self.steps.append(("open", attach))
        return self.opens

    def set_title(self, title: str) -> None:
        self.steps.append(("title", title))

    def let_ctrl_c_through(self) -> None:
        self.steps.append("Ctrl+C")

    def run(self, argv: Sequence[str]) -> int:
        self.steps.append(("run", list(argv)))
        if isinstance(self.code, OSError):
            raise self.code
        return self.code

    def write(self, text: str) -> None:
        self.written += text

    def wait_for_key(self, grace: float) -> None:
        self.steps.append(("key", grace))


@pytest.fixture(autouse=True)
def language_kept() -> Iterator[None]:
    before = i18n.language()
    yield
    i18n.set_language(before)


def _run(code: int | OSError, language: str = "en") -> tuple[int, FakeConsole]:
    console = FakeConsole(code)
    return holder.run(holder.args_for(SSH, "nas-01", language)[1:], console), console


def test_what_capypanel_writes_the_holder_reads_back() -> None:
    args = holder.args_for(SSH, "nas-01", "pt_BR")
    assert args[0] == holder.FLAG == "--ssh-holder"  # what __main__ looks for
    assert holder.parse(args[1:]) == Request(argv=SSH, host="nas-01", language="pt_BR")
    assert holder.parse([holder.ATTACH, *args[1:]]) == Request(SSH, "nas-01", "pt_BR", True)


def test_without_a_name_the_words_use_the_last_argument() -> None:
    assert holder.parse(["--", *SSH]) == Request(argv=SSH, host="192.0.2.41", language="en")


@pytest.mark.parametrize("args", [[], ["--lang=en"], ["--lang=en", "--"], ["--what", "--", "x"]])
def test_a_start_capypanel_wouldn_t_write_does_nothing(args: list[str]) -> None:
    console = FakeConsole()
    assert holder.run(args, console) == holder.NOT_STARTED_BY_CAPYPANEL
    assert console.steps == []  # no window, nothing started


@pytest.mark.parametrize("code", [0, 1, 130, 254, ending.CTRL_C_EXIT])
def test_a_normal_end_closes_the_window(code: int) -> None:
    exit_code, console = _run(code)
    assert exit_code == 0 and console.steps == STARTED and console.written == ""


def test_after_255_it_points_at_ssh_exe_s_message_and_waits_for_a_key() -> None:
    exit_code, console = _run(255)
    assert console.written == (
        "\r\nThe connection to nas-01 ended with an error. ssh.exe's message is above."
        "\r\nPress any key to close this window.\r\n"
    )
    assert console.steps == [*STARTED, ("key", holder.KEY_GRACE)]
    assert exit_code == 0  # after the key: Windows Terminal closes a tab that ends with 0


def test_above_255_it_gives_the_code_in_hex() -> None:
    _exit_code, console = _run(0xC0000005)
    assert "The connection to nas-01 ended with an error (exit code 0xC0000005)." in (
        console.written
    )
    assert console.steps[-1] == ("key", holder.KEY_GRACE)


def test_its_words_come_in_capypanel_s_language() -> None:
    _exit_code, console = _run(255, "pt_BR")
    assert console.written == (
        "\r\nA conexão com nas-01 terminou com um erro. A mensagem do ssh.exe está acima."
        "\r\nPressione qualquer tecla para fechar esta janela.\r\n"
    )


def test_when_ssh_exe_can_t_start_it_says_why_and_waits() -> None:
    exit_code, console = _run(OSError(2, "The system cannot find the file specified"))
    assert console.written == (
        "\r\nCouldn't start ssh.exe: The system cannot find the file specified"
        "\r\nPress any key to close this window.\r\n"
    )
    assert console.steps[-1] == ("key", holder.KEY_GRACE) and exit_code == 0


def test_with_no_console_nothing_starts() -> None:
    console = FakeConsole(255, opens=False)
    assert holder.run(["--", *SSH], console) == holder.NO_CONSOLE
    assert console.steps == [("open", False)]


def test_a_probe_s_start_keeps_the_console_it_was_given() -> None:
    console = FakeConsole(130)
    holder.run([holder.ATTACH, "--", *SSH], console)
    assert console.steps[0] == ("open", True)


def test_a_quick_second_enter_never_closes_the_window_unread() -> None:
    # At the host key question a bare Enter refuses and ssh.exe ends at once with 255; a second
    # Enter close behind it must not close the window before the words are read.
    assert holder.KEY_GRACE >= 1.0


def test_the_key_wait_drops_what_was_pressed_during_the_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class FakeKernel:
        def __getattr__(self, name: str) -> object:
            def call(*_args: object) -> bool:
                calls.append(name)
                return False  # ReadConsoleInputW: the console went away, so the wait ends

            return call

    monkeypatch.setattr(holder, "_k32", FakeKernel())
    monkeypatch.setattr(holder, "time", SimpleNamespace(sleep=lambda s: calls.append(f"sleep {s}")))
    holder.WindowsConsole().wait_for_key(holder.KEY_GRACE)
    # The grace first, then everything pressed in it dropped, then the wait.
    assert calls == ["sleep 1.0", "FlushConsoleInputBuffer", "GetConsoleMode", "ReadConsoleInputW"]


@pytest.mark.parametrize(
    ("code", "error"),
    [(0, False), (1, False), (130, False), (254, False), (255, True), (256, True),
     (0xC0000005, True), (0xC000013A, False)],
)  # fmt: skip
def test_an_error_is_255_or_windows_ending_it_other_than_by_ctrl_c(code: int, error: bool) -> None:
    assert ending.is_error(code) is error


def test_codes_read_as_windows_writes_them() -> None:
    assert ending.code_text(255) == "255"
    assert ending.code_text(0xC0000005) == "0xC0000005"


def test_capypanel_exe_with_the_flag_runs_only_the_holder(monkeypatch: pytest.MonkeyPatch) -> None:
    from capypanel.ui import app

    seen: list[list[str]] = []
    monkeypatch.setattr(holder, "run", lambda args: seen.append(args) or 7)
    monkeypatch.setattr(app, "run", lambda: pytest.fail("the app started"))
    monkeypatch.setattr(sys, "argv", ["CapyPanel.exe", "--ssh-holder", "--", *SSH])
    assert entry.main() == 7
    assert seen == [["--", *SSH]]


@pytest.mark.skipif(ctypes.sizeof(ctypes.c_void_p) != 8, reason="sizes for 64-bit Windows")
def test_the_structures_are_windows_own_size() -> None:
    assert ctypes.sizeof(holder._InputRecord) == 20
    assert ctypes.sizeof(holder._StartupInfoEx) == 112
    assert ctypes.sizeof(holder._ExtendedLimits) == 144

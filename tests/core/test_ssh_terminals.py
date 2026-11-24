import subprocess
from pathlib import Path

import pytest

from capypanel.core.ssh import launch, terminals
from capypanel.core.ssh.host import SshInfo
from capypanel.core.ssh.terminals import Terminal

EXE = Path(r"C:\Windows\System32\OpenSSH\ssh.exe")
SSH = [str(EXE), "-p", "2222", "-l", "root", "--", "192.0.2.41"]
WEZTERM = Terminal(Path(r"C:\Program Files\WezTerm\wezterm-gui.exe"), "start -- {ssh}")


@pytest.mark.parametrize(
    ("line", "words"),
    [
        ("new-tab --title {name} -- {ssh}", ["new-tab", "--title", "{name}", "--", "{ssh}"]),
        ('/x "-run {ssh}"', ["/x", "-run {ssh}"]),
        ('"{ssh}"', ["{ssh}"]),
        (r'a\\"b c" d\e', [r"a\b c", r"d\e"]),
        ("", []),
    ],
)
def test_the_arguments_split_as_a_program_s_c_runtime_splits_them(
    line: str, words: list[str]
) -> None:
    assert terminals.split(line) == words


def test_ssh_alone_becomes_ssh_exe_and_each_of_its_arguments() -> None:
    assert terminals.command(WEZTERM, SSH, "nas-01") == [
        str(WEZTERM.program), "start", "--", *SSH,
    ]  # fmt: skip


def test_ssh_inside_an_argument_becomes_its_whole_command_line() -> None:
    conemu = Terminal(Path(r"C:\Tools\ConEmu\ConEmu64.exe"), '/x "-run {ssh}" -title {name}')
    assert terminals.command(conemu, SSH, "nas-01") == [
        str(conemu.program),
        "/x",
        r"-run C:\Windows\System32\OpenSSH\ssh.exe -p 2222 -l root -- 192.0.2.41",
        "-title",
        "nas-01",
    ]


@pytest.mark.parametrize(
    ("name", "title"),
    [
        ("nas-01", "nas-01"),
        ("Servidor_web.2", "Servidor_web.2"),
        ("Servidor Web", "192.0.2.41"),
        ("-oProxyCommand=calc", "192.0.2.41"),
        ("srv&calc", "192.0.2.41"),
        ('srv"', "192.0.2.41"),
        ("%USERNAME%", "192.0.2.41"),
        ("", "192.0.2.41"),
    ],
)
def test_a_name_a_shell_could_misread_gives_way_to_the_address(name: str, title: str) -> None:
    wt = Terminal(Path(r"C:\Apps\wt.exe"), "new-tab --title {name} -- {ssh}")
    assert terminals.command(wt, SSH, name)[2:4] == ["--title", title]


def test_a_program_is_an_exe_that_s_there_with_ssh_in_its_arguments(tmp_path: Path) -> None:
    program = tmp_path / "term.exe"
    program.touch()
    script = tmp_path / "term.bat"
    script.touch()
    assert terminals.problem(str(program), "-e {ssh}") == ""
    assert terminals.problem("  ", "-e {ssh}") == "Choose the program."
    for not_an_exe in (script, tmp_path / "term.cmd", tmp_path / "term"):
        assert terminals.problem(str(not_an_exe), "-e {ssh}") == (
            "Choose a program: a file whose name ends in .exe."
        )
    for missing in (tmp_path / "gone.exe", Path("term.exe")):
        assert terminals.problem(str(missing), "-e {ssh}") == "There's no program at this path."
    assert terminals.problem(str(program), "-e ssh") == (
        "The arguments need {ssh}, where the program takes the command it runs."
    )


def test_a_ready_line_is_found_where_its_program_installs(tmp_path: Path) -> None:
    apps = tmp_path / "Local" / "Microsoft" / "WindowsApps"
    env = {"LOCALAPPDATA": str(tmp_path / "Local")}
    assert terminals.ready_here(env) == []
    assert terminals.ready_here({}) == []
    apps.mkdir(parents=True)
    (apps / "wt.exe").touch()
    [wt] = terminals.ready_here(env)
    assert wt == Terminal(apps / "wt.exe", "new-tab --title {name} -- {ssh}", "windows-terminal")
    assert wt.name == "Windows Terminal"


def test_a_choice_is_kept_by_its_ready_line_or_as_typed(tmp_path: Path) -> None:
    env = {"LOCALAPPDATA": str(tmp_path)}
    ready = terminals.from_prefs({"ready": "windows-terminal"}, env)
    assert ready is not None and ready.ready == "windows-terminal"
    assert ready.program == tmp_path / "Microsoft" / "WindowsApps" / "wt.exe"
    assert terminals.to_prefs(ready) == {"ready": "windows-terminal"}
    kept = terminals.to_prefs(WEZTERM)
    assert kept == {"program": str(WEZTERM.program), "arguments": "start -- {ssh}"}
    assert terminals.from_prefs(kept) == WEZTERM
    assert WEZTERM.name == "wezterm-gui.exe"


@pytest.mark.parametrize(
    "kept",
    [
        None,
        "wt.exe",
        {"ready": "a-terminal-from-a-newer-capypanel"},
        {"program": "wezterm-gui.exe", "arguments": "start -- {ssh}"},
        {"program": r"C:\Tools\term.bat", "arguments": "{ssh}"},
        {"program": r"C:\Tools\term.exe", "arguments": "start"},
        {"program": r"C:\Tools\term.exe"},
    ],
)
def test_a_kept_choice_it_can_t_run_leaves_the_console_window(kept: object) -> None:
    assert terminals.from_prefs(kept) is None


def test_the_program_starts_with_a_console_of_its_own_if_it_needs_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(
        terminals.subprocess, "Popen", lambda argv, **kw: started.append((argv, kw))
    )
    terminals.start(WEZTERM, SSH, "nas-01")
    [(argv, kw)] = started
    assert argv == [str(WEZTERM.program), "start", "--", *SSH]
    assert kw["executable"] == str(WEZTERM.program)
    assert kw["creationflags"] == subprocess.CREATE_NEW_CONSOLE
    assert kw["cwd"] == Path.home() and kw["close_fds"] is True


def test_connect_hands_ssh_exe_s_checked_line_to_the_picked_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[list[str]] = []
    monkeypatch.setattr(launch, "ssh_exe", lambda: EXE)
    monkeypatch.setattr(launch.subprocess, "Popen", lambda argv, **kw: started.append(argv))
    launch.connect("192.0.2.41", SshInfo(port=2222, login="root"), "nas-01", WEZTERM)
    assert started == [[str(WEZTERM.program), "start", "--", *SSH]]
    with pytest.raises(ValueError):
        launch.connect("srv;calc", SshInfo(), "nas-01", WEZTERM)
    with pytest.raises(ValueError):
        launch.connect("192.0.2.41", SshInfo(login="-oProxyCommand=calc"), "nas-01", WEZTERM)
    assert len(started) == 1

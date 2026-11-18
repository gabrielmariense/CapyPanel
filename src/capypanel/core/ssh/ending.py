"""How an ssh.exe connection ended (topic-029 E): what counts as an error, and the words that
say so. The separate window's holder uses them now; the terminal tab's strip will too, so the
two always agree."""

from capypanel.core.i18n import _

CTRL_C_EXIT = 0xC000013A  # Windows ended the program: Ctrl+C, or its window was closed


def is_error(code: int) -> bool:
    """255 is ssh.exe's own error. Above 255 Windows ended ssh.exe, an error unless it's
    0xC000013A. 1 to 254 is the remote shell's own code, a normal end: "exit" after Ctrl+C on
    tail -f (130) isn't an error."""
    return code == 255 or (code > 255 and code != CTRL_C_EXIT)


def code_text(code: int) -> str:
    """Decimal up to 255 and hex above it (0xC0000005), as Windows writes those codes and as
    people search for them."""
    return str(code) if code <= 255 else f"0x{code:08X}"


def error_line(host: str, code: int) -> str:
    """The line for an error: for 255 it points at ssh.exe's own message, above it; above 255
    ssh.exe usually printed nothing, so it gives the code."""
    if code == 255:
        return _(
            "The connection to {host} ended with an error. ssh.exe's message is above."
        ).format(host=host)
    return _("The connection to {host} ended with an error (exit code {code}).").format(
        host=host, code=code_text(code)
    )

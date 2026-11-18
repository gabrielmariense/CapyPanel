r"""Keys as Windows key events, in win32-input-mode: ESC [ Vk ; Sc ; Uc ; Kd ; Cs ; Rc _

The pseudo console asks for this mode at start (ESC[?9001h) and then encodes each key by the
program's own modes: Up is ESC[A normally and ESC O A after the program's ESC[?1h. The console
doesn't pass that mode on to us, so sending plain text for keys would give vim and less the
wrong arrows. Qt hands over each key's virtual key, scan code, text and modifiers; Windows' own
tables do the rest.

Rules of our own, each for a reason:
- A dead key sends nothing; the key after it brings the composed text (~ then a gives "ã").
- AltGr is Ctrl+Alt to Windows. When a key with both down gives printable text, the Ctrl and Alt
  bits are dropped, so AltGr+Q's "/" isn't read as Ctrl+Alt+/.
- Alt alone keeps its bit, so the console sends ESC and the letter (Alt+B, Alt+F in bash)."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

# dwControlKeyState bits (wincon.h)
RIGHT_ALT, LEFT_ALT, RIGHT_CTRL, LEFT_CTRL = 0x1, 0x2, 0x4, 0x8
SHIFT, NUMLOCK, SCROLLLOCK, CAPSLOCK, ENHANCED = 0x10, 0x20, 0x40, 0x80, 0x100
ALT_BITS, CTRL_BITS = RIGHT_ALT | LEFT_ALT, RIGHT_CTRL | LEFT_CTRL

# QKeyEvent.nativeModifiers() on Windows (qwindowskeymapper.cpp, WindowsNativeModifiers)
Q_SHIFT_L, Q_CTRL_L, Q_ALT_L, Q_META_L = 0x1, 0x2, 0x4, 0x8
Q_SHIFT_R, Q_CTRL_R, Q_ALT_R, Q_META_R = 0x10, 0x20, 0x40, 0x80
Q_CAPS, Q_NUM, Q_SCROLL, Q_EXTENDED = 0x100, 0x200, 0x400, 0x01000000
NATIVE_BITS = (
    (Q_SHIFT_L | Q_SHIFT_R, SHIFT),
    (Q_CTRL_L, LEFT_CTRL),
    (Q_CTRL_R, RIGHT_CTRL),
    (Q_ALT_L, LEFT_ALT),
    (Q_ALT_R, RIGHT_ALT),
    (Q_CAPS, CAPSLOCK),
    (Q_NUM, NUMLOCK),
    (Q_SCROLL, SCROLLLOCK),
    (Q_EXTENDED, ENHANCED),
)

_DEAD_FIRST, _DEAD_LAST = 0x01001250, 0x0100129F  # Qt::Key_Dead_Grave .. the last dead key


def control_state(event: QKeyEvent) -> int:
    """Windows' dwControlKeyState for the key: from Windows' own modifiers when Qt has them,
    which tell the left and right keys apart, else from Qt's."""
    native = event.nativeModifiers()
    state = 0
    if native:
        for q, bit in NATIVE_BITS:
            if native & q:
                state |= bit
        return state
    mods = event.modifiers()
    if mods & Qt.KeyboardModifier.ShiftModifier:
        state |= SHIFT
    if mods & Qt.KeyboardModifier.ControlModifier:
        state |= LEFT_CTRL
    if mods & Qt.KeyboardModifier.AltModifier:
        state |= LEFT_ALT
    return state


def is_dead_key(event: QKeyEvent) -> bool:
    return _DEAD_FIRST <= event.key() <= _DEAD_LAST


def encode(event: QKeyEvent, down: bool) -> bytes:
    """The bytes for one key going down or up; b"" for a key that sends nothing."""
    if is_dead_key(event):
        return b""
    vk = event.nativeVirtualKey()
    sc = event.nativeScanCode()
    text = event.text()
    state = control_state(event)
    if len(text) > 1 or (text and ord(text) > 0xFFFF):
        # Several characters at once, or one beyond a UTF-16 unit (an emoji from the emoji
        # panel): the key event has room for one unit, so it goes as text.
        return text.encode("utf-8") if down else b""
    uc = ord(text) if text else 0
    if uc >= 0x20 and uc != 0x7F and (state & CTRL_BITS) and (state & ALT_BITS):
        state &= ~(CTRL_BITS | ALT_BITS)  # AltGr gave printable text
    if vk == 0 and uc == 0:
        return b""
    return f"\x1b[{vk};{sc};{uc};{1 if down else 0};{state};1_".encode("ascii")

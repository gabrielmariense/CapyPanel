"""Keys for the pseudo console: Windows key events when it asks (Windows 11), else xterm's."""

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
    if is_dead_key(event):  # the next key brings the composed text: ~ then a gives "ã"
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


# Keys with no text, as xterm sends them: cursor keys CSI or (application mode) SS3 and a letter,
# F1 to F4 SS3 and a letter, the rest CSI n ~; a modifier m goes in as CSI 1 ; m x or CSI n ; m ~.
_CURSOR = {int(k): c for k, c in ((Qt.Key.Key_Up, "A"), (Qt.Key.Key_Down, "B"),
           (Qt.Key.Key_Right, "C"), (Qt.Key.Key_Left, "D"), (Qt.Key.Key_Home, "H"),
           (Qt.Key.Key_End, "F"))}  # fmt: skip
_SS3 = {int(k): c for k, c in ((Qt.Key.Key_F1, "P"), (Qt.Key.Key_F2, "Q"), (Qt.Key.Key_F3, "R"),
        (Qt.Key.Key_F4, "S"))}  # fmt: skip
_TILDE = {int(k): n for k, n in ((Qt.Key.Key_Insert, 2), (Qt.Key.Key_Delete, 3),
          (Qt.Key.Key_PageUp, 5), (Qt.Key.Key_PageDown, 6), (Qt.Key.Key_F5, 15),
          (Qt.Key.Key_F6, 17), (Qt.Key.Key_F7, 18), (Qt.Key.Key_F8, 19), (Qt.Key.Key_F9, 20),
          (Qt.Key.Key_F10, 21), (Qt.Key.Key_F11, 23), (Qt.Key.Key_F12, 24))}  # fmt: skip
_KEY_A, _KEY_Z = int(Qt.Key.Key_A), int(Qt.Key.Key_Z)


def encode_text(event: QKeyEvent, *, app_cursor: bool = False) -> bytes:
    """The bytes for one key going down, as text and xterm's sequences, for a console that never
    asked for key events; b"" when it sends nothing. `app_cursor`: the program sent ESC[?1h."""
    if is_dead_key(event):
        return b""
    key = int(event.key())
    mods = event.modifiers()
    shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
    alt = bool(mods & Qt.KeyboardModifier.AltModifier)
    ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
    m = 1 + shift + 2 * alt + 4 * ctrl
    if key in _CURSOR:
        if m > 1:
            return f"\x1b[1;{m}{_CURSOR[key]}".encode("ascii")
        return f"\x1b{'O' if app_cursor else '['}{_CURSOR[key]}".encode("ascii")
    if key in _SS3:
        return (f"\x1b[1;{m}{_SS3[key]}" if m > 1 else f"\x1bO{_SS3[key]}").encode("ascii")
    if key in _TILDE:
        return (f"\x1b[{_TILDE[key]};{m}~" if m > 1 else f"\x1b[{_TILDE[key]}~").encode("ascii")
    if key == int(Qt.Key.Key_Backtab):
        return b"\x1b[Z"
    text = event.text()
    printable = bool(text) and text.isprintable()
    if ctrl and alt and printable:
        return text.encode("utf-8")  # AltGr's text, never Ctrl+Alt
    if ctrl and key == int(Qt.Key.Key_Space):
        body = b"\x00"
    elif ctrl and _KEY_A <= key <= _KEY_Z:
        body = bytes([key - _KEY_A + 1])  # Ctrl+C is 3, as Windows gives it in the key's text
    elif printable:
        body = text.encode("utf-8")
    elif key == int(Qt.Key.Key_Backspace):
        body = b"\x08" if ctrl else b"\x7f"  # as xterm: DEL, and Ctrl+Backspace deletes a word
    elif key in (int(Qt.Key.Key_Return), int(Qt.Key.Key_Enter)):
        body = b"\r"
    elif key == int(Qt.Key.Key_Tab):
        body = b"\t"
    elif key == int(Qt.Key.Key_Escape):
        body = b"\x1b"
    elif len(text) == 1 and ord(text) < 0x20:
        body = text.encode("ascii")  # another control character Windows gave the key
    else:
        return b""
    return b"\x1b" + body if alt else body  # Alt sends ESC first: Alt+B, Alt+F in bash

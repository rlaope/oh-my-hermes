"""Turn raw terminal bytes into keys and pastes, incrementally.

A terminal delivers input in arbitrary chunks: a UTF-8 character, an escape
sequence or a bracketed paste can straddle two reads. `KeyDecoder.feed`
decodes everything complete and keeps the incomplete tail for the next call,
so the caller never sees half a key.

A lone ESC is ambiguous until time passes: it is the Escape key, or the first
byte of an arrow, an Alt chord or a mouse report whose next byte is still in
flight. The decoder never guesses. The caller runs `flush()` after every short
silence, and what is held settles only once the silence since its last byte,
read from the decoder's clock, is long enough for it: a lone ESC becomes
`Key("escape")` at once, or after `REPORTING_ESCAPE_SECONDS` while a mouse
report may still arrive (the caller says whether reporting is on, and when it
last went off). A lone ESC held from an earlier read also settles at the next
read that cannot go on with a sequence (see `_continues_escape`), silence or
not: it is Esc, and that read's bytes are keys of their own. So an Alt chord is
an ESC and its key in one read; split across two reads it is Esc and the key,
which is what Esc and then a key typed before the next silence send. A paste
ends at the terminal's paste-end marker; one whose marker never comes ends at
the first `flush()` after `PASTE_SETTLE_SECONDS` of silence, as what arrived
so far, and the bytes after that are keys again, except that a carriage return
among them is a newline (`Paste("\n")`) until the late end marker arrives,
which is no key, or `PASTE_LATE_SECONDS` pass without a read of more than one
key.

A paste the terminal sent without its markers is plain bytes, and a person
types one key a read. So a read of plain text (no ESC, no control byte but
Tab and line breaks) that holds two line breaks, or one line break with text on
both sides in a read of at least eight characters, is pasted: it is held, every plain read less than the burst window (`BURST_SECONDS`, or
`SSH_BURST_SECONDS` as the caller says) after the one before joins it, and it
settles as one `Paste` at the first read that does not or at the first
`flush()` once the window passed. A read of text that ends in a line break,
less than the window after the read before it, has its text decoded and its
line break held for the window: a next chunk shaped like a paste's (a line
break, or more than one character) makes it a newline; one typed key, a read
that is not plain, or nothing makes it the key it is, before that key. A lone
Enter, a run of bare Enters, and a read of text and Enter after a pause decode
at once, as before.

Nothing here raises on input. A sequence it does not know becomes
`Key("unknown")` and decoding continues with the next byte. So does an OSC
string (`ESC ]` up to BEL or ST) whose `ESC ]` has a digit after it: a
terminal answering a query sends one (the startup background query's answer,
when it comes after the TUI stopped waiting for it), and it types nothing. One
that never ends is dropped whole at the next silence, or at `_MAX_OSC_LENGTH`
bytes. `ESC ]` followed by anything else is Alt+], as the legacy encoding
sends it, and the keys after it are keys. The XTVERSION answer (`ESC P >`
up to ST) is read the same way, and `ESC P` followed by anything else is
Alt+P. An `ESC ]` that ends a read waits
for the next byte, as a lone ESC does: a digit opens an OSC string, anything
else makes it Alt+], and so does the next silence.

Terminals that `Terminal` asks for richer key reports send some keys as kitty
CSI u (`ESC[99;5u`) or xterm modifyOtherKeys (`ESC[27;5;99~`). A key xterm's
legacy bytes can say decodes to the very `Key` those bytes give, so Ctrl+C,
Esc, Tab, Alt+b or Shift+a behave the same either way, and so does every Ctrl
chord xterm sends as one control byte: Ctrl with a letter, with `@ [ \\ ] ^ _ /`
or space, or with a digit from 2 to 8 (Ctrl+2 a NUL, Ctrl+3 Esc, Ctrl+8 and
Ctrl+? DEL, which is Backspace). The reports add what legacy bytes cannot say,
such as Ctrl+Enter and Shift+Enter. A Ctrl chord xterm has no control byte for
(Ctrl+1, Ctrl+9, Ctrl+0, Ctrl+comma, ...) stays a Ctrl chord, where a legacy
terminal may send the bare character instead; the TUI binds none of them. A
key decoded from either form carries `protocol=True`, and
`KeyDecoder.protocol_reported` turns on at the first one: the terminal is
known to send them only once it has. It turns on sooner where the terminal
answers the kitty keyboard query (`ESC[?<flags>u`, `Terminal.query_background`
asks) with the disambiguate flag on, since the reports then come from the
next key on. That answer, flag on or off, is no key and types nothing.

While `Terminal.set_mouse(True)` has mouse reporting on, a click arrives as an
SGR report (`ESC[<b;x;yM` press, `ESC[<b;x;ym` release) and decodes to a
`Mouse`. A wheel turn or a motion report decodes too. Reports the terminal sent
before it acted on an off still arrive after it (the release of the click that
opened a log, over SSH most of all), so the rules below hold for input that
starts arriving while reporting is on or within `MOUSE_REPORT_SECONDS` after it
went off. A pause can split such a report across reads (over SSH, jitter can
stall one mid-way); no byte of it is typed as text if it arrives whole within
`REPORTING_ESCAPE_SECONDS` plus `MOUSE_REPORT_SECONDS` (0.8 s) of its first byte:

- a started report (`ESC[<` and digits and semicolons so far) waits for up to
  `MOUSE_REPORT_SECONDS` of silence, and is then dropped as one unknown key
  (this one holds whenever the input started);
- `ESC` and `ESC[` wait `REPORTING_ESCAPE_SECONDS`, and then settle as Esc and
  as one unknown key; a later read ends an ESC's wait at once unless it starts
  with `[` or with an SS3 key's `O` and final byte (F1 to F4, an arrow, Home or
  End): the ESC is Esc and the new bytes are keys of their own, so a capital O
  typed after Esc is Esc and `O` (an ESC and a key in one read stay an Alt
  chord);
- for `MOUSE_REPORT_SECONDS` after either settled, the bytes that would finish
  the report it began are dropped as they arrive, up to its `M` or `m`.

So such a report split right after its first byte by more than
`REPORTING_ESCAPE_SECONDS` is Esc, and its rest is dropped only if it arrives
within `MOUSE_REPORT_SECONDS` after that; what arrives later is read as keys.
A report that starts arriving later than `MOUSE_REPORT_SECONDS` after reporting
went off, split right after its `ESC` or its `ESC[`, is read as keys, as any
input is with reporting off. A terminal that ignores the SGR request sends the
legacy `ESC[M` and three payload bytes instead; that is one unknown key.

A focus report (`ESC[I` the window gained focus, `ESC[O` it lost it, asked
for by `Terminal`) is no key and types nothing in any mode: it only sets
`KeyDecoder.unfocused_at`. A whole report is taken out of a read before
anything else reads it, so it never ends or splits an unmarked paste, never
moves the burst window and never lands in a bracketed paste's text; a read
of reports alone is no input. Any other read says the window has focus
again, since input comes from a focused window, so a focus-in the terminal
never sent does not keep it counted as unfocused past the next key.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
import time

CHAR = "char"
ENTER = "enter"
TAB = "tab"
BACKSPACE = "backspace"
ESCAPE = "escape"
UP = "up"
DOWN = "down"
LEFT = "left"
RIGHT = "right"
HOME = "home"
END = "end"
INSERT = "insert"
DELETE = "delete"
PAGE_UP = "pageup"
PAGE_DOWN = "pagedown"
UNKNOWN = "unknown"

# Bytes and sequences the decoder reads, in one place.
ESC_BYTE = 0x1B
CSI_BYTE = ord("[")
SS3_BYTE = ord("O")
OSC_BYTE = ord("]")
DCS_BYTE = ord("P")
# `ESC P >` opens the XTVERSION answer (`ESC P > | name ST`, `Terminal.query_background` asks some terminals for it):
# a DCS string, read as an OSC string is. `ESC P` followed by anything else is Alt+P.
DCS_ANSWER_BYTE = ord(">")
BEL_BYTE = 0x07
STRING_TERMINATOR_BYTE = ord("\\")  # ESC and then this byte end an OSC string, as BEL does
CARRIAGE_RETURN = 0x0D
LINE_FEED = 0x0A
HORIZONTAL_TAB = 0x09
BACKSPACE_BYTE = 0x08
DELETE_BYTE = 0x7F
PASTE_START_PARAMETER = "200"
PASTE_END_PARAMETER = "201"
PASTE_END = b"\x1b[201~"
# An open paste this long without a byte is over though its end marker never came, as Hermes' own TUI rules
# (hermes-ink `App.tsx` PASTE_TIMEOUT); without it every later key, Ctrl+C included, would be paste text.
PASTE_SETTLE_SECONDS = 0.5
# After that settle the terminal still owes the paste's rest and its end marker. Until the marker arrives, or this
# long passes without a read that brings more than one key (the rest arrives in chunks; typed keys come one a
# read and do not count), a carriage return is a newline in the paste, not Enter: a stalled multi-line paste must
# not submit its first lines. The marker itself is then no key.
PASTE_LATE_SECONDS = 1.0
# A terminal that sends no paste markers (tmux or SSH strips them, or it has no bracketed paste) delivers a paste as
# plain bytes, so the line breaks in it would be Enter. A person types one key a read, so a read of plain text that
# holds two line breaks, or one between text in a read longer than a typing burst (`_pasted`), is pasted; it is held
# as one paste for as long as reads of plain bytes keep coming less than this apart. A read of text ending in a line
# break, less than this after the read before it, has the line break held as well: a next chunk with a line break or
# more than one character in it joins it, one typed key makes it the key it was. Senpi uses the same window
# (`stdin-buffer.ts`).
BURST_SECONDS = 0.02
# Over SSH a paste's chunks arrive further apart.
SSH_BURST_SECONDS = 0.1

# A CSI longer than this without a final byte is garbage, not a slow key; the
# bound keeps a hostile or broken stream from growing the held tail forever.
_MAX_CSI_LENGTH = 32
# The same bound for an OSC string; a background answer is about 30 bytes.
_MAX_OSC_LENGTH = 512

_CSI_LETTER_KEYS = {"A": UP, "B": DOWN, "C": RIGHT, "D": LEFT, "H": HOME, "F": END}
_SS3_KEYS = _CSI_LETTER_KEYS
# The final bytes of the SS3 keys terminals send: F1 to F4 (`ESC O P` to `ESC O S`, no key `Key` names), and the
# arrows, Home and End in application cursor mode.
_SS3_FINALS = b"PQRS" + "".join(_SS3_KEYS).encode("ascii")
_CSI_TILDE_KEYS = {
    "1": HOME,
    "2": INSERT,
    "3": DELETE,
    "4": END,
    "5": PAGE_UP,
    "6": PAGE_DOWN,
    "7": HOME,
    "8": END,
}
# xterm modifier parameter: 1 + (shift 1 | alt 2 | ctrl 4 | meta 8).
_SHIFT_BIT = 1
_ALT_BIT = 2
_CTRL_BIT = 4
# kitty adds caps lock 64 and num lock 128, which change no key OMH reads;
# super, hyper and meta (8, 16, 32) have no place in `Key`, so such a chord is unknown.
_LOCK_BITS = 64 | 128
_READ_BITS = _SHIFT_BIT | _ALT_BIT | _CTRL_BIT

# kitty CSI u (`ESC[<code>[:<shifted>[:<base>]][;<mods>[:<event>]]u`) and xterm
# modifyOtherKeys (`ESC[27;<mods>;<code>~`) name a key by its code point.
CSI_U_FINAL = "u"
MODIFY_OTHER_KEYS_PARAMETER = "27"
# kitty event types: 1 press, 2 repeat, 3 release. A release is not a key.
_PRESS_EVENTS = ("", "1", "2")
# The kitty keyboard query's answer is `ESC[?<flags>u`; flag 1, disambiguate, is the one `Terminal` pushes.
KEYBOARD_FLAGS_PREFIX = "?"
DISAMBIGUATE_FLAG = 1
_PROTOCOL_KEYS = {
    CARRIAGE_RETURN: ENTER,
    HORIZONTAL_TAB: TAB,
    ESC_BYTE: ESCAPE,
    DELETE_BYTE: BACKSPACE,
    57414: ENTER,  # keypad Enter
}
# kitty's keypad code points (functional key table), for the keys that type text.
_KEYPAD_TEXT = {57399 + digit: str(digit) for digit in range(10)} | {
    57409: ".",
    57410: "/",
    57411: "*",
    57412: "-",
    57413: "+",
    57415: "=",
}
# Besides the letters, the keys whose Ctrl chord legacy xterm sends as one control byte, and that byte.
_CTRL_BYTES = {
    "@": 0x00, " ": 0x00, "2": 0x00,
    "[": ESC_BYTE, "3": ESC_BYTE,
    "\\": 0x1C, "4": 0x1C,
    "]": 0x1D, "5": 0x1D,
    "^": 0x1E, "6": 0x1E,
    "_": 0x1F, "7": 0x1F, "/": 0x1F,
    "8": DELETE_BYTE, "?": DELETE_BYTE,
}

# Mouse buttons a `Mouse` names. NO_BUTTON is a release that does not say which
# button, or motion with none held.
BUTTON_LEFT = "left"
BUTTON_MIDDLE = "middle"
BUTTON_RIGHT = "right"
NO_BUTTON = "none"
WHEEL_UP = "wheel-up"
WHEEL_DOWN = "wheel-down"
WHEEL_LEFT = "wheel-left"
WHEEL_RIGHT = "wheel-right"

# SGR mouse report: `ESC[<b;x;yM` press, `ESC[<b;x;ym` release (xterm mode 1006).
SGR_MOUSE_PREFIX = "<"
SGR_MOUSE_PRESS = "M"
SGR_MOUSE_RELEASE = "m"
_SGR_REPORT_START = bytes((ESC_BYTE, CSI_BYTE)) + SGR_MOUSE_PREFIX.encode("ascii")
_SGR_PARAMETER_BYTES = b"0123456789;"
_SGR_FINAL_BYTES = (SGR_MOUSE_PRESS + SGR_MOUSE_RELEASE).encode("ascii")
# A report a pause splits across reads: once `ESC[<` has arrived, a silence shorter than this does
# not settle what is held, and a longer one drops it as one unknown key. For as long again after that,
# the bytes that would finish it are dropped as they arrive, so its tail is never typed either.
MOUSE_REPORT_SECONDS = 0.5
# While a mouse report may still arrive, `ESC` and `ESC[` wait this long for the rest of one before they
# settle. The wait trades two things: the longer it is, the longer a stall between a report's first byte
# and the rest can be without the ESC reading as Esc (and interrupting a running turn); the shorter, the
# sooner Esc acts when it is pressed on its own. 300 ms covers a stall of a few hundred milliseconds on a
# slow link and keeps Esc within a third of a second; a key typed after Esc does not wait for it at all.
# With no report in flight a lone ESC still settles at the first silence.
REPORTING_ESCAPE_SECONDS = 0.3
# Legacy (X10) mouse report: `ESC[M` and three bytes, each 32 plus a value.
X10_MOUSE_FINAL = ord("M")
_X10_MOUSE_PAYLOAD_BYTES = 3
# The button code: the low two bits pick the button, 64 and 128 move to the
# wheel and the extra buttons, and these four flags ride on top of any of them.
_MOUSE_SHIFT_BIT = 4
_MOUSE_ALT_BIT = 8  # xterm calls it meta; it is the Alt key
_MOUSE_CTRL_BIT = 16
_MOUSE_MOTION_BIT = 32
_MOUSE_FLAG_BITS = _MOUSE_SHIFT_BIT | _MOUSE_ALT_BIT | _MOUSE_CTRL_BIT | _MOUSE_MOTION_BIT
# Buttons 8 to 11 (code 128 and up) have no name here, so their reports are unknown keys.
_MOUSE_BUTTONS = {
    0: BUTTON_LEFT,
    1: BUTTON_MIDDLE,
    2: BUTTON_RIGHT,
    3: NO_BUTTON,
    64: WHEEL_UP,
    65: WHEEL_DOWN,
    66: WHEEL_LEFT,
    67: WHEEL_RIGHT,
}


@dataclass(frozen=True)
class Key:
    """One key press. `protocol` says it arrived as a kitty CSI u or xterm modifyOtherKeys report.

    `protocol` is not part of a key's identity: such a report decodes to the
    very `Key` its legacy bytes give, and compares equal to it. It says which
    form the terminal used, a form only a terminal that honoured the request
    for richer reports sends.

    `arrived_at` is when the key's first byte arrived, on the decoder's clock,
    and is not part of its identity either. A key can be decided well after
    that (an ESC waits for a report's `[`), so a deadline about when the person
    pressed it reads this. None on a key the decoder did not make.

    `reported_shift` retains a protocol report's Shift bit even when Ctrl
    normalization removes it from key identity. Navigation uses it to exclude
    shifted aliases without changing legacy equality, hashing or shortcuts.
    """

    name: str
    char: str = ""
    ctrl: bool = False
    alt: bool = False
    shift: bool = False
    protocol: bool = field(default=False, compare=False, repr=False)
    arrived_at: float | None = field(default=None, compare=False, repr=False)
    reported_shift: bool = field(default=False, compare=False, repr=False)


@dataclass(frozen=True)
class Paste:
    text: str


@dataclass(frozen=True)
class Mouse:
    """One SGR mouse report.

    `x` and `y` are 1-based cells, exactly as the terminal reports them: the
    top-left cell is (1, 1) and the screen's last row is `y == rows`. A wheel
    turn is a press of WHEEL_UP or WHEEL_DOWN; `motion` marks a report sent
    because the pointer moved, which only a motion tracking mode produces, so
    a click is a press that is not motion.
    """

    button: str
    x: int
    y: int
    pressed: bool = True
    motion: bool = False
    shift: bool = False
    alt: bool = False
    ctrl: bool = False


# Internal markers for ESC[200~ and ESC[201~ outside a paste; neither leaves the decoder.
_PASTE_START = Key("paste-start")
_PASTE_END = Key("paste-end")
# Internal markers for the kitty keyboard query's answer, disambiguate on or off; neither leaves the decoder.
_KEYBOARD_FLAGS_ON = Key("keyboard-flags-on")
_KEYBOARD_FLAGS_OFF = Key("keyboard-flags-off")
# Internal markers for the focus reports, `ESC[I` and `ESC[O`; neither leaves the decoder.
_FOCUS_IN = Key("focus-in")
_FOCUS_OUT = Key("focus-out")
_FOCUS_FINALS = {"I": _FOCUS_IN, "O": _FOCUS_OUT}
_FOCUS_IN_BYTES = b"\x1b[I"
_FOCUS_OUT_BYTES = b"\x1b[O"


def _without_focus_reports(data: bytes) -> tuple[bytes, Key | None]:
    """`data` without its whole focus reports, and the marker of the last of them (None when it holds none).

    Taken out before anything else reads the input, so a report never ends an unmarked paste's burst, never moves
    its timing and never lands in a bracketed paste's text. A report split right after its ESC is not whole here;
    the CSI decoding reads it (`_csi_key`).
    """
    gained, lost = data.rfind(_FOCUS_IN_BYTES), data.rfind(_FOCUS_OUT_BYTES)
    if gained < 0 and lost < 0:
        return data, None
    return data.replace(_FOCUS_IN_BYTES, b"").replace(_FOCUS_OUT_BYTES, b""), (
        _FOCUS_IN if gained > lost else _FOCUS_OUT)


def _single_byte_key(byte: int) -> Key:
    if byte == CARRIAGE_RETURN:
        return Key(ENTER)
    if byte == HORIZONTAL_TAB:
        return Key(TAB)
    if byte in (DELETE_BYTE, BACKSPACE_BYTE):
        return Key(BACKSPACE)
    if byte == LINE_FEED:
        return Key(CHAR, "j", ctrl=True)
    if 0x01 <= byte <= 0x1A:
        return Key(CHAR, chr(byte + 0x60), ctrl=True)
    if byte == 0x00 or 0x1C <= byte <= 0x1F:
        # Ctrl+@ (also what Ctrl+Space sends), Ctrl+\, Ctrl+], Ctrl+^, Ctrl+_
        return Key(CHAR, chr(byte + 0x40), ctrl=True)
    return Key(CHAR, chr(byte))


def _utf8_length(lead: int) -> int:
    if 0xC2 <= lead <= 0xDF:
        return 2
    if 0xE0 <= lead <= 0xEF:
        return 3
    if 0xF0 <= lead <= 0xF4:
        return 4
    return 0


def _decode_utf8(data: bytes, start: int, final: bool) -> tuple[Key | None, int]:
    length = _utf8_length(data[start])
    if not length:
        return Key(UNKNOWN), start + 1
    available = min(len(data), start + length)
    for index in range(start + 1, available):
        if not 0x80 <= data[index] <= 0xBF:
            # The byte that broke the sequence starts the next key.
            return Key(UNKNOWN), index
    if available < start + length:
        return (Key(UNKNOWN), len(data)) if final else (None, start)
    try:
        text = data[start : start + length].decode("utf-8")
    except UnicodeDecodeError:  # overlong form or surrogate: well framed, not a character
        return Key(UNKNOWN), start + length
    return Key(CHAR, text), start + length


def _modifiers(parameter: str) -> dict[str, bool] | None:
    if not parameter:
        return {}
    if not (parameter.isascii() and parameter.isdigit()) or int(parameter) < 1:
        return None
    bits = int(parameter) - 1
    return {"shift": bool(bits & _SHIFT_BIT), "alt": bool(bits & _ALT_BIT), "ctrl": bool(bits & _CTRL_BIT)}


def _digits(field: str) -> bool:
    return field.isascii() and field.isdigit()


def _protocol_modifiers(field: str) -> dict[str, bool] | None:
    """`<mods>[:<event>]` of a CSI u or modifyOtherKeys key; None when it is no key press `Key` can carry."""
    mods, _, event = field.partition(":")
    if event not in _PRESS_EVENTS or not _digits(mods) or int(mods) < 1:
        return None
    bits = (int(mods) - 1) & ~_LOCK_BITS
    if bits & ~_READ_BITS:
        return None
    return {"shift": bool(bits & _SHIFT_BIT), "alt": bool(bits & _ALT_BIT), "ctrl": bool(bits & _CTRL_BIT)}


def _code_text(field: str) -> str:
    """The character a code point field names; "" when it is empty or names nothing printable."""
    if not _digits(field) or int(field) > 0x10FFFF:
        return ""
    text = chr(int(field))
    return text if text.isprintable() else ""


def _protocol_key(code_field: str, modifier_field: str) -> Key:
    """A kitty CSI u or xterm modifyOtherKeys key, as the `Key` its legacy bytes give.

    `code_field` is `<code>[:<shifted>[:<base>]]`. Enter, Tab, Esc and
    Backspace keep every modifier, which is how Ctrl+Enter and Shift+Enter
    exist at all. A Ctrl chord on a letter or on a key in `_CTRL_BYTES` is
    what the control byte xterm sends for it decodes to (Ctrl+C, Ctrl+J a
    newline, Ctrl+M Enter, Ctrl+[ and Ctrl+3 Esc, Ctrl+8 Backspace), and Shift
    on a printable key is in its character (Shift+a is "A"), as a legacy
    terminal sends them.
    """
    codes = code_field.split(":")
    flags = _protocol_modifiers(modifier_field)
    if flags is None or len(codes) > 3 or not _digits(codes[0]) or any(part and not _digits(part) for part in codes):
        return Key(UNKNOWN)
    code = int(codes[0])
    if code in _PROTOCOL_KEYS:
        return Key(_PROTOCOL_KEYS[code], reported_shift=flags["shift"], **flags)
    text = _KEYPAD_TEXT.get(code) or _code_text(codes[0])
    if not text:
        return Key(UNKNOWN)
    lowered = text.lower()
    main_key = code not in _KEYPAD_TEXT  # xterm's control bytes are the main keys'; a keypad key keeps its Ctrl
    if flags["ctrl"] and main_key and (lowered.isascii() and lowered.isalpha() or text in _CTRL_BYTES):
        control = _CTRL_BYTES.get(text, ord(lowered) & 0x1F)
        key = Key(ESCAPE) if control == ESC_BYTE else _single_byte_key(control)
        key = replace(key, reported_shift=flags["shift"])
        return replace(key, alt=True) if flags["alt"] else key
    if flags["shift"]:
        upper = text.upper()
        text = _code_text(codes[1] if len(codes) > 1 else "") or (upper if len(upper) == 1 else text)
    return Key(CHAR, text, ctrl=flags["ctrl"], alt=flags["alt"], reported_shift=flags["shift"])


def _sgr_mouse(parameters: str, pressed: bool) -> Key | Mouse:
    """`b;x;y` of an SGR mouse report; one unknown key when it is malformed or names a button `Mouse` does not."""
    fields = parameters.split(";")
    if len(fields) != 3 or not all(_digits(field) for field in fields):
        return Key(UNKNOWN)
    code, x, y = (int(field) for field in fields)
    button = _MOUSE_BUTTONS.get(code & ~_MOUSE_FLAG_BITS)
    if button is None or x < 1 or y < 1:
        return Key(UNKNOWN)
    return Mouse(
        button,
        x,
        y,
        pressed=pressed,
        motion=bool(code & _MOUSE_MOTION_BIT),
        shift=bool(code & _MOUSE_SHIFT_BIT),
        alt=bool(code & _MOUSE_ALT_BIT),
        ctrl=bool(code & _MOUSE_CTRL_BIT),
    )


def _reported(key: Key) -> Key:
    """A key decoded from a CSI u or modifyOtherKeys report, marked as such; an unknown one is not marked."""
    return key if key.name == UNKNOWN else replace(key, protocol=True)


def _csi_key(parameters: str, final: str) -> Key | Mouse:
    if parameters.startswith(SGR_MOUSE_PREFIX) and final in (SGR_MOUSE_PRESS, SGR_MOUSE_RELEASE):
        return _sgr_mouse(parameters[len(SGR_MOUSE_PREFIX) :], final == SGR_MOUSE_PRESS)
    if final == CSI_U_FINAL and parameters.startswith(KEYBOARD_FLAGS_PREFIX):
        flags = parameters[len(KEYBOARD_FLAGS_PREFIX) :]
        if not _digits(flags):
            return Key(UNKNOWN)
        return _KEYBOARD_FLAGS_ON if int(flags) & DISAMBIGUATE_FLAG else _KEYBOARD_FLAGS_OFF
    if final in _FOCUS_FINALS and not parameters:
        return _FOCUS_FINALS[final]
    fields = parameters.split(";")
    if final == CSI_U_FINAL and len(fields) <= 2:
        return _reported(_protocol_key(fields[0], fields[1] if len(fields) == 2 else "1"))
    if final == "~" and len(fields) == 3 and fields[0] == MODIFY_OTHER_KEYS_PARAMETER and ":" not in parameters:
        return _reported(_protocol_key(fields[2], fields[1]))
    if len(fields) > 2:
        return Key(UNKNOWN)
    modifier = fields[1] if len(fields) == 2 else ""
    if final == "~":
        if parameters == PASTE_START_PARAMETER:
            return _PASTE_START
        if parameters == PASTE_END_PARAMETER:
            return _PASTE_END
        name = _CSI_TILDE_KEYS.get(fields[0])
    elif final == "Z" and not parameters:
        return Key(TAB, shift=True)
    elif final in _CSI_LETTER_KEYS and fields[0] in ("", "1"):
        name = _CSI_LETTER_KEYS[final]
    else:
        name = None
    flags = _modifiers(modifier)
    if name is None or flags is None:
        return Key(UNKNOWN)
    return Key(name, **flags)


def _decode_x10_mouse(data: bytes, start: int, final: bool) -> tuple[Key | None, int]:
    """`ESC[M` and its three payload bytes as one unknown key, so none of them is typed as text.

    Every payload byte is 32 or more; a control byte among them (an ESC
    starting the next sequence) means this `ESC[M` carries no payload, and the
    bytes after it decode on their own, as Hermes' own TUI reads them
    (hermes-ink `termio/tokenize.ts`).
    """
    payload_start = start + 3
    payload = data[payload_start : payload_start + _X10_MOUSE_PAYLOAD_BYTES]
    if any(byte < 0x20 for byte in payload):
        return Key(UNKNOWN), payload_start
    if len(payload) < _X10_MOUSE_PAYLOAD_BYTES and not final:
        return None, start
    return Key(UNKNOWN), payload_start + len(payload)


def _decode_csi(data: bytes, start: int, final: bool) -> tuple[Key | Mouse | None, int]:
    index = start + 2  # past ESC [
    while index < len(data):
        byte = data[index]
        if byte == X10_MOUSE_FINAL and index == start + 2:
            return _decode_x10_mouse(data, start, final)
        if 0x40 <= byte <= 0x7E:
            return _csi_key(data[start + 2 : index].decode("ascii"), chr(byte)), index + 1
        if not 0x20 <= byte <= 0x3F or index - start >= _MAX_CSI_LENGTH:
            return Key(UNKNOWN), index
        index += 1
    if not final:
        return None, start
    if len(data) == start + 2:
        return Key(CHAR, "[", alt=True), start + 2
    return Key(UNKNOWN), len(data)


def _decode_ss3(data: bytes, start: int, final: bool) -> tuple[Key | None, int]:
    if len(data) < start + 3:
        return (Key(CHAR, "O", alt=True), start + 2) if final else (None, start)
    byte = data[start + 2]
    if not 0x40 <= byte <= 0x7E:
        return Key(CHAR, "O", alt=True), start + 2
    name = _SS3_KEYS.get(chr(byte))
    return (Key(name) if name else Key(UNKNOWN)), start + 3


def _decode_osc(data: bytes, start: int, final: bool) -> tuple[Key | None, int]:
    """An OSC string (`ESC ]` up to BEL or `ESC \\`) as one unknown key; `(None, start)` while it may still end.

    An ESC inside it that does not start the terminator ends it there and
    starts the next key, and one longer than `_MAX_OSC_LENGTH` is cut off.
    """
    index = start + 2  # past ESC ]
    while index < len(data) and index - start < _MAX_OSC_LENGTH:
        byte = data[index]
        if byte == BEL_BYTE:
            return Key(UNKNOWN), index + 1
        if byte == ESC_BYTE:
            if index + 1 == len(data):
                break  # the terminator may be split after its ESC
            return Key(UNKNOWN), index + 2 if data[index + 1] == STRING_TERMINATOR_BYTE else index
        index += 1
    if index - start >= _MAX_OSC_LENGTH:
        return Key(UNKNOWN), index
    return (Key(UNKNOWN), len(data)) if final else (None, start)


def _decode_escape(data: bytes, start: int, final: bool) -> tuple[Key | Mouse | None, int]:
    if len(data) == start + 1:
        return (Key(ESCAPE), start + 1) if final else (None, start)
    second = data[start + 1]
    if second == CSI_BYTE:
        return _decode_csi(data, start, final)
    if second == OSC_BYTE and len(data) == start + 2 and not final:
        return None, start  # the next byte decides: an answer's OSC number, or anything else after Alt+]
    if second == OSC_BYTE and data[start + 2 : start + 3].isdigit():  # an answer's OSC number, not Alt+]
        return _decode_osc(data, start, final)
    if second == DCS_BYTE and len(data) == start + 2 and not final:
        return None, start  # the next byte decides: the XTVERSION answer's `>`, or anything else after Alt+P
    if second == DCS_BYTE and data[start + 2 : start + 3] == bytes((DCS_ANSWER_BYTE,)):
        return _decode_osc(data, start, final)  # the XTVERSION answer, a string to its ST like an OSC one
    if second == SS3_BYTE:
        return _decode_ss3(data, start, final)
    if second == ESC_BYTE:
        return Key(ESCAPE), start + 1
    key, end = _decode_plain(data, start + 1, final)
    if key is None:
        return None, start
    if key.name == UNKNOWN:
        return key, end
    return replace(key, alt=True), end


def _decode_plain(data: bytes, start: int, final: bool) -> tuple[Key | None, int]:
    byte = data[start]
    if byte < 0x80:
        return _single_byte_key(byte), start + 1
    return _decode_utf8(data, start, final)


def _decode_one(data: bytes, start: int, final: bool) -> tuple[Key | Mouse | None, int]:
    """The key at `start` and the index after it; `(None, start)` means "wait for more"."""
    if data[start] == ESC_BYTE:
        return _decode_escape(data, start, final)
    return _decode_plain(data, start, final)


def _report_started(data: bytes) -> bool:
    """Whether `data` is all of a report's start so far: `ESC`, `ESC[`, or `ESC[<` and digits and semicolons."""
    if not data or len(data) > _MAX_CSI_LENGTH:
        return False
    head, rest = data[: len(_SGR_REPORT_START)], data[len(_SGR_REPORT_START) :]
    return _SGR_REPORT_START.startswith(head) and all(byte in _SGR_PARAMETER_BYTES for byte in rest)


def _report_length(data: bytes) -> int:
    """The length of the whole SGR mouse report `data` starts with; 0 when it starts with none."""
    if not data.startswith(_SGR_REPORT_START):
        return 0
    end = len(_SGR_REPORT_START)
    while end < len(data) and data[end] in _SGR_PARAMETER_BYTES:
        end += 1
    return end + 1 if end < len(data) and data[end] in _SGR_FINAL_BYTES else 0


def _continues_escape(data: bytes) -> bool:
    """Whether a read after a lone ESC held from an earlier read goes on with its sequence: a CSI's `[`, an SS3 key's
    `O` and final, or an OSC string's `]` and the digit that opens it.

    A read that is a lone `O`, or `O` and a byte no SS3 key ends with, is a
    capital O typed after Esc. An SS3 key split again right after its `O` is
    read that way too: Esc, then its letters. So is a lone `]`, or `]` and
    anything but a digit: Esc, then the bracket.
    """
    if data.startswith(bytes((CSI_BYTE,))):
        return True
    if len(data) > 1 and data[0] == SS3_BYTE:
        return data[1] in _SS3_FINALS
    if len(data) > 1 and data[0] == DCS_BYTE:
        return data[1] == DCS_ANSWER_BYTE
    return len(data) > 1 and data[0] == OSC_BYTE and data[1:2].isdigit()


def _paste_text(raw: bytes) -> str:
    return raw.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")


# Bytes a paste is made of: text, Tab and line breaks. ESC, DEL or any other control byte in a read makes it typed.
_PLAIN_BYTES = bytes((HORIZONTAL_TAB, LINE_FEED, CARRIAGE_RETURN, *range(0x20, DELETE_BYTE), *range(DELETE_BYTE + 1, 256)))


def _plain(data: bytes) -> bool:
    return not data.translate(None, _PLAIN_BYTES)


# One line break between text is a paste only in a read longer than this many characters (line breaks aside): a
# stalled loop can hand over a prompt, its Enter and the first key typed after it (`fix A\rt`) in one read.
_ONE_BREAK_PASTE_CHARS = 8


def _pasted(raw: bytes) -> bool:
    """Whether plain `raw` from one read is pasted: it holds text and two line breaks, or one line break with text on
    both sides of it in a read of at least `_ONE_BREAK_PASTE_CHARS` characters."""
    lines = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    text = lines.rstrip(b"\n")
    if not text.replace(b"\n", b""):
        return False
    if lines.count(b"\n") >= 2:
        return True
    before, _, after = text.partition(b"\n")
    chars = len(text.decode("utf-8", "replace")) - 1
    return bool(before and after) and chars >= _ONE_BREAK_PASTE_CHARS


def _paste_shaped(data: bytes) -> bool:
    """Whether a read may go on with a paste: it holds a line break or more than one character. One typed key does
    not, so a held line break it follows is the key it was."""
    return CARRIAGE_RETURN in data or LINE_FEED in data or len(data.decode("utf-8", "replace")) > 1


class KeyDecoder:
    def __init__(self, clock: Callable[[], float] = time.monotonic, burst_seconds: float = BURST_SECONDS) -> None:
        self._clock = clock
        self._pending = bytearray()
        self._paste: bytearray | None = None
        self._fed_at = 0.0  # when the last byte arrived
        self._read_at = float("-inf")  # when the last read arrived
        # Plain bytes held for `burst_seconds` (`BURST_SECONDS`): an unmarked paste (`_burst_pasted`), or the line break
        # that ended a read of text, a key unless the next read joins it. `_burst_at` is when that line break arrived.
        self._burst_seconds = burst_seconds
        self._burst: bytearray | None = None
        self._burst_pasted = False
        self._burst_at = 0.0
        # Until when a carriage return is a newline of a paste `flush` settled without its end marker.
        self._late_paste_until = float("-inf")
        self._held_at = 0.0  # when the first byte of what is held arrived
        # The start of a report `flush` settled, and until when the bytes that would finish it are dropped.
        self._settled_start = b""
        self._drop_until = 0.0
        # True from the first key that arrived as a CSI u or modifyOtherKeys report, or from a kitty keyboard
        # query answer with the disambiguate flag on: the terminal does send them, so Ctrl+Enter reaches the
        # caller apart from Enter. Asking for them proves nothing.
        self.protocol_reported = False
        # When the terminal window lost focus (its focus-out report), on the decoder's clock; None while it has
        # focus or never said otherwise. Any read sets it back to None: input comes from a focused window.
        self.unfocused_at: float | None = None

    @property
    def holding(self) -> bool:
        """Whether bytes wait to be decided (part of a key, an open paste, a settled report's rest): `flush` has work."""
        held = bool(self._pending) or self._paste is not None or bool(self._settled_start)
        return held or self._burst is not None

    def feed(self, data: bytes) -> list[Key | Paste | Mouse]:
        now = self._clock()
        data, focus = _without_focus_reports(data)
        self.unfocused_at = now if focus is _FOCUS_OUT else None
        if not data:  # only focus reports: no input, but a lone ESC held from before is Esc, as at any other read
            if self._pending == bytes((ESC_BYTE,)):
                self._pending.clear()
                return [Key(ESCAPE, arrived_at=self._held_at)]
            return []
        gap, self._read_at = now - self._read_at, now
        events: list[Key | Paste | Mouse] = []
        if self._burst is not None:
            # A paste goes on with any plain read in the window; a held line break only with a read shaped like a
            # paste's next chunk, and it is then a newline once text joined it.
            joins = self._burst_pasted or _paste_shaped(data)
            if gap < self._burst_seconds and _plain(data) and joins:  # the burst goes on
                self._burst.extend(data)
                self._burst_pasted = self._burst_pasted or bool(bytes(self._burst).translate(None, b"\r\n"))
                self._fed_at = now
                return events
            events = self._settle_burst()
        if self._settled_start and now >= self._drop_until:
            self._close_drop_window()
        # A lone ESC held from an earlier read, whether or not a silence passed since: a read that does not go
        # on with a sequence ends the wait. It was Esc, and this read's keys are keys of their own.
        escape = self._pending == bytes((ESC_BYTE,)) and not _continues_escape(data)
        if escape:
            events.append(Key(ESCAPE, arrived_at=self._held_at))
            self._pending.clear()
        if not self._pending:
            self._held_at = now
        self._fed_at = now
        earlier = len(self._pending)  # bytes held from earlier reads, in front of this one's
        self._pending.extend(data)
        if self._settled_start:
            held = self._settled_start + bytes(self._pending)
            length = _report_length(held)
            if length:
                rest = length - len(self._settled_start)
                del self._pending[:rest]  # the rest of a report already settled
                # Every byte held from earlier reads belonged to that rest (it stayed held because the report
                # was not complete yet), so deleting the rest used them all up and what is left came in this read.
                self._held_at = now
                earlier = max(earlier - rest, 0)
                self._settled_start = b""
            elif _report_started(held):
                return events  # still that report's rest: held, and dropped when the window closes
            else:
                self._settled_start = b""
        if self._paste is None and now >= self._late_paste_until and self._hold_burst(gap):
            return events
        held = len(self._pending)
        decoded = self._drain(final=False, earlier=earlier)
        if len(decoded) > 1 and now < self._late_paste_until:
            # More than one key in a read is the paste's rest still arriving; a person types one key a read.
            self._late_paste_until = now + PASTE_LATE_SECONDS
        events += decoded
        if self._pending and len(self._pending) < held:
            self._held_at = now  # what is still held came in this read
        return events

    def flush(self, reporting: bool = False, reporting_off_at: float | None = None) -> list[Key | Paste | Mouse]:
        """Settle what is held once the silence since its last byte is long enough for it.

        `reporting` says mouse reporting is on, and `reporting_off_at` when it
        last went off (None if it never was on). A report may still arrive
        when reporting is on, or when what is held started arriving less than
        `MOUSE_REPORT_SECONDS` after the off. A started report waits for
        `MOUSE_REPORT_SECONDS` and then is one unknown key; while a report may
        still arrive, `ESC` and `ESC[` wait for `REPORTING_ESCAPE_SECONDS` and
        then are Esc and one unknown key (a lone ESC's wait also ends at the
        next read that does not go on with a sequence: see `feed`). An open
        paste ends after `PASTE_SETTLE_SECONDS`, as what it holds, and opens
        the `PASTE_LATE_SECONDS` window for its rest. Plain bytes held as a
        burst settle once the burst window passed since their last read: a
        paste as one `Paste`, a held line break as its key. Anything
        else held settles now: a lone ESC becomes `Key("escape")`.
        """
        now = self._clock()
        if self._burst is not None:
            return [] if now - self._read_at < self._burst_seconds else self._settle_burst()
        if self._paste is not None:
            if now - self._fed_at < PASTE_SETTLE_SECONDS:
                return []
            self._late_paste_until = now + PASTE_LATE_SECONDS
            return self._settle_paste()
        if self._settled_start:
            if now < self._drop_until:
                return []
            self._close_drop_window()
        held, silence = bytes(self._pending), now - self._fed_at
        if len(held) >= len(_SGR_REPORT_START) and _report_started(held):
            return [] if silence < MOUSE_REPORT_SECONDS else self._settle_start(held, Key(UNKNOWN), now)
        off_at = reporting_off_at
        in_flight = reporting or (off_at is not None and self._held_at - off_at < MOUSE_REPORT_SECONDS)
        if in_flight and _report_started(held):
            if silence < REPORTING_ESCAPE_SECONDS:
                return []
            return self._settle_start(held, Key(ESCAPE) if len(held) == 1 else Key(UNKNOWN), now)
        return self._drain(final=True, earlier=len(held))

    def _hold_burst(self, gap: float) -> bool:
        """Hold what this read left, if plain, as a burst: True when it is a paste, held whole; a line break that
        ends text read less than the burst window after the read before is held alone, and its text decodes now."""
        held = bytes(self._pending)
        if (CARRIAGE_RETURN not in held and LINE_FEED not in held) or not _plain(held):
            return False
        if _pasted(held):
            self._burst, self._burst_pasted = bytearray(held), True
            self._pending.clear()
            return True
        text = held.rstrip(b"\r\n")
        if text and gap < self._burst_seconds:
            self._burst, self._burst_pasted, self._burst_at = bytearray(held[len(text) :]), False, self._read_at
            del self._pending[len(text) :]
        return False

    def _settle_burst(self) -> list[Key | Paste | Mouse]:
        """The held burst: one `Paste`, or the line break no paste joined as the keys it is."""
        body, pasted = bytes(self._burst or b""), self._burst_pasted
        self._burst, self._burst_pasted = None, False
        if pasted:
            return [Paste(_paste_text(body))]
        keys: list[Key | Paste | Mouse] = []
        index = 0
        while index < len(body):
            key, index = _decode_one(body, index, final=True)
            if isinstance(key, Key):
                keys.append(replace(key, arrived_at=self._burst_at))
        return keys

    def _settle_paste(self) -> list[Key | Paste | Mouse]:
        """The open paste as it stands, its end marker given up on; nothing when it holds nothing."""
        body = bytes(self._paste or b"") + bytes(self._pending)
        self._paste = None
        self._pending.clear()
        return [Paste(_paste_text(body))] if body else []

    def _settle_start(self, held: bytes, key: Key, now: float) -> list[Key | Paste | Mouse]:
        """`key` for the start of a report held too long, and the window in which the rest of it is dropped."""
        self._pending.clear()
        self._settled_start, self._drop_until = held, now + MOUSE_REPORT_SECONDS
        return [replace(key, arrived_at=self._held_at)]

    def _close_drop_window(self) -> None:
        """Drop what is held of a settled report's rest once it reached `<`; before that it is still a key's."""
        if (self._settled_start + bytes(self._pending)).startswith(_SGR_REPORT_START):
            self._pending.clear()
        self._settled_start = b""

    def _drain(self, final: bool, earlier: int) -> list[Key | Paste | Mouse]:
        """Decode what is held, each key stamped with when its first byte arrived.

        The first `earlier` bytes were held from earlier reads, the first of
        them since `_held_at`, so a key starting among them carries `_held_at`
        (the earliest it can have arrived); any other key came in the last read.
        """
        events: list[Key | Paste | Mouse] = []
        while True:
            if self._paste is not None:
                paste = self._take_paste()
                if paste is None:
                    return events
                events.append(paste)
            data = bytes(self._pending)
            index = 0
            late = self._fed_at < self._late_paste_until
            while index < len(data) and self._paste is None:
                key, end = _decode_one(data, index, final)
                if key is None:
                    break
                arrived_at = self._held_at if index < earlier else self._fed_at
                start, index = index, end
                if key is _PASTE_START:
                    self._paste = bytearray()
                elif key is _PASTE_END:
                    if late:  # the end of a paste `flush` settled: nothing more is owed
                        self._late_paste_until = float("-inf")
                        late = False
                    else:
                        events.append(Key(UNKNOWN, arrived_at=arrived_at))
                elif key is _KEYBOARD_FLAGS_ON or key is _KEYBOARD_FLAGS_OFF:
                    self.protocol_reported = self.protocol_reported or key is _KEYBOARD_FLAGS_ON
                elif key is _FOCUS_IN or key is _FOCUS_OUT:
                    self.unfocused_at = None if key is _FOCUS_IN else self._fed_at
                elif late and data[start] == CARRIAGE_RETURN:
                    if data[index : index + 1] == bytes((LINE_FEED,)):
                        index += 1  # CR LF is one newline, as in a paste
                    events.append(Paste("\n"))
                elif isinstance(key, Key):
                    self.protocol_reported = self.protocol_reported or key.protocol
                    events.append(replace(key, arrived_at=arrived_at))
                else:
                    events.append(key)
            del self._pending[:index]
            earlier = max(earlier - index, 0)
            if self._paste is None:
                return events

    def _take_paste(self) -> Paste | None:
        """Move held bytes into the open paste; the finished `Paste` once its end marker arrived."""
        body = self._paste
        if body is None:
            return None
        # Only the tail can hold a marker split across the previous chunk.
        searched = max(0, len(body) - len(PASTE_END) + 1)
        body.extend(self._pending)
        self._pending.clear()
        end = body.find(PASTE_END, searched)
        if end < 0:
            return None
        self._pending.extend(body[end + len(PASTE_END) :])
        self._paste = None
        return Paste(_paste_text(bytes(body[:end])))


def is_leader_key(event: Key | Paste) -> bool:
    """Whether `event` is a plain Space, with no modifier (including reported Shift)."""
    return (
        isinstance(event, Key)
        and event.name == CHAR
        and event.char == " "
        and not (event.ctrl or event.alt or event.shift or event.reported_shift)
    )


def list_nav_step(event: Key | Paste) -> int:
    """Return navigation delta for list/picker items: +1 (down) or -1 (up), else 0.

    Matches DOWN, Ctrl+N and Ctrl+J (without Alt or Shift) to +1.
    Matches UP, Ctrl+P and Ctrl+K (without Alt or Shift) to -1.
    Shift is read from the protocol report when present (`reported_shift`); legacy control bytes carry none.
    """
    if not isinstance(event, Key):
        return 0
    if event.name == DOWN and not event.ctrl and not event.alt and not event.shift:
        return 1
    if event.name == UP and not event.ctrl and not event.alt and not event.shift:
        return -1
    if (
        event.name == CHAR
        and event.ctrl
        and not event.alt
        and not event.shift
        and not event.reported_shift
        and event.char in ("n", "p", "j", "k")
    ):
        return 1 if event.char in ("n", "j") else -1
    return 0

"""The arrow-key theme picker behind bare `omh theme`.

A colour theme is the one setting nobody can evaluate from a name, so bare
`omh theme` paints each palette while the cursor sits on it. The picker is a
convenience layer only: it never writes anything itself, it returns the chosen
theme and the caller runs the same selection path `omh theme use <name>` runs.

Three seams keep it testable without a terminal: `read_key`, `write`, and the
frame width all arrive as arguments, so a test drives navigation by feeding
key tokens and reads the frames back out of a list. The default `read_key` is
the only part that touches a real tty.

Windows takes the documented plain-list fallback: there is no `termios` there,
and a `msvcrt` raw-key path is more terminal-behaviour risk than a cosmetic
picker earns. `omh theme list` and `omh theme use` are fully supported on every
platform, and `picker_available()` reports the fallback honestly.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from contextlib import contextmanager
import os
import select
import sys
from typing import TextIO

from ..skin_pack import SHORT_NAME_WIDTH, SkinTheme, hex_to_rgb, skin_colors
from ..system.stdin_probe import stdin_is_tty

try:  # pragma: no cover - exercised by platform, not by a branch test
    import termios
    import tty
except ImportError:  # pragma: no cover - Windows ships no termios
    termios = None  # type: ignore[assignment]
    tty = None  # type: ignore[assignment]

# Every escape sequence the picker emits or reads, in one place. Scattering
# these is how a repaint ends up off by one row on somebody else's terminal.
ESC = "\x1b"
RESET = f"{ESC}[0m"
HIDE_CURSOR = f"{ESC}[?25l"
SHOW_CURSOR = f"{ESC}[?25h"
CLEAR_LINE = f"{ESC}[2K"
BOLD = f"{ESC}[1m"

KEY_UP = "up"
KEY_DOWN = "down"
KEY_LEFT = "left"
KEY_RIGHT = "right"
KEY_MINUS = "minus"
KEY_PLUS = "plus"
KEY_DEFAULT = "default"
KEY_TOGGLE = " "
KEY_ENTER = "enter"
KEY_QUIT = "quit"
KEY_NONE = ""

# One vocabulary for every OMH picker. The theme picker uses the vertical
# tokens only and ignores the rest; the chain picker (`model_chain_picker`)
# steps a row's model with left/right and its effort with -/+.
_PLAIN_KEYS = {
    " ": KEY_TOGGLE,
    "\r": KEY_ENTER,
    "\n": KEY_ENTER,
    "q": KEY_QUIT,
    "Q": KEY_QUIT,
    "\x03": KEY_QUIT,  # Ctrl-C: raw mode swallows the signal, so read it as cancel
    "\x04": KEY_QUIT,  # Ctrl-D
    "\x0e": KEY_DOWN,  # Ctrl-N
    "\x10": KEY_UP,  # Ctrl-P
    "j": KEY_DOWN,
    "J": KEY_DOWN,
    "k": KEY_UP,
    "K": KEY_UP,
    "h": KEY_LEFT,
    "H": KEY_LEFT,
    "l": KEY_RIGHT,
    "L": KEY_RIGHT,
    "-": KEY_MINUS,
    "_": KEY_MINUS,
    "+": KEY_PLUS,
    "=": KEY_PLUS,  # the unshifted key under + on most layouts
    "d": KEY_DEFAULT,
    "D": KEY_DEFAULT,
}
_CSI_KEYS = {"A": KEY_UP, "B": KEY_DOWN, "C": KEY_RIGHT, "D": KEY_LEFT}
_ESCAPE_PEEK_SECONDS = 0.05


def plain_key(char: str) -> str:
    """The key token one typed character means to every OMH picker; `KEY_NONE` when it means nothing."""
    return _PLAIN_KEYS.get(char, KEY_NONE)


def cursor_up(rows: int) -> str:
    return f"{ESC}[{rows}A" if rows > 0 else ""


def truecolor(text: str, hex_value: str, *, bold: bool = False) -> str:
    """Paint `text` with a 24-bit foreground, or return it plain if it cannot."""
    rgb = hex_to_rgb(hex_value)
    if rgb is None:
        return text
    red, green, blue = rgb
    prefix = BOLD if bold else ""
    return f"{prefix}{ESC}[38;2;{red};{green};{blue}m{text}{RESET}"


def picker_available(*, stdin: TextIO | None = None, stdout: TextIO | None = None) -> bool:
    """True only when raw-key reading is possible AND both ends are terminals.

    The two environment escapes match the keyboard menu `omh setup` already
    ships (`_keyboard_menu_available`), so one machine that cannot drive a
    cursor menu cannot drive either of them.
    """
    if termios is None or tty is None:
        return False
    if os.environ.get("TERM", "") == "dumb" or os.environ.get("OMH_NO_TUI", "") == "1":
        return False
    sink = stdout if stdout is not None else sys.stdout
    try:
        source_is_tty = stdin.isatty() if stdin is not None else stdin_is_tty()
        return bool(source_is_tty and sink.isatty())
    except (AttributeError, OSError, ValueError):
        # A closed or non-file stream is not a terminal; degrade to the list.
        # `>&-` leaves sys.stdout None, which raises AttributeError.
        return False


@contextmanager
def raw_mode(stream: TextIO):
    """Put one tty in cbreak mode and always put it back."""
    descriptor = stream.fileno()
    saved = termios.tcgetattr(descriptor)
    try:
        tty.setcbreak(descriptor)
        yield
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, saved)


def _read_byte(descriptor: int) -> str:
    try:
        return os.read(descriptor, 1).decode("utf-8", "ignore")
    except OSError:
        # A closed or interrupted tty is a cancelled picker, not a crash.
        return ""


def read_terminal_key(stream: TextIO | None = None) -> str:
    """One normalized key token from a tty already in cbreak mode.

    Reads the file descriptor directly rather than through the text stream on
    purpose. `sys.stdin.read(1)` pulls a whole chunk into Python's buffered
    reader, so the rest of an arrow sequence sits in userspace where `select`
    on the descriptor cannot see it — and every arrow then reads as a bare
    Escape, which cancels the picker instantly (observed on a pty).
    """
    source = stream if stream is not None else sys.stdin
    descriptor = source.fileno()
    first = _read_byte(descriptor)
    if not first:
        return KEY_QUIT
    if first != ESC:
        return plain_key(first)
    # A bare Escape and the start of an arrow sequence look identical until the
    # next byte does or does not arrive; a short peek separates them.
    ready, _, _ = select.select([descriptor], [], [], _ESCAPE_PEEK_SECONDS)
    if not ready:
        return KEY_QUIT
    if _read_byte(descriptor) != "[":
        return KEY_QUIT
    return _CSI_KEYS.get(_read_byte(descriptor), KEY_NONE)


def _swatch(label: str, hex_value: str, use_color: bool) -> str:
    if not use_color:
        return f"{label} {hex_value}"
    return f"{truecolor('██', hex_value)} {label}"


def preview_lines(theme: SkinTheme, *, use_color: bool) -> list[str]:
    """The colour sample painted under the cursor, in the theme's own palette."""
    colors = skin_colors(theme.skin_name)
    title = colors.get("banner_title", "")
    accent = colors.get("ui_accent", "")
    if not use_color:
        return [
            f"    OH-MY-HERMES / {theme.short_name}",
            "    "
            + "  ".join(
                f"{label} {colors.get(token, '')}"
                for label, token in (
                    ("accent", "ui_accent"),
                    ("label", "ui_label"),
                    ("text", "banner_text"),
                    ("dim", "banner_dim"),
                )
            ),
            "    ok  warn  error",
        ]
    heading = f"{truecolor('OH-MY-HERMES', title, bold=True)} {truecolor('▸ ' + theme.short_name, accent)}"
    swatches = "  ".join(
        _swatch(label, colors.get(token, ""), use_color)
        for label, token in (
            ("accent", "ui_accent"),
            ("label", "ui_label"),
            ("text", "banner_text"),
            ("dim", "banner_dim"),
        )
    )
    semantics = "  ".join(
        truecolor(mark, colors.get(token, ""))
        for mark, token in (("✓ ok", "ui_ok"), ("! warn", "ui_warn"), ("✗ error", "ui_error"))
    )
    return [f"    {heading}", f"    {swatches}", f"    {semantics}"]


def render_frame(
    themes: Sequence[SkinTheme],
    cursor: int,
    active_skin: str,
    *,
    use_color: bool,
    width: int,
) -> list[str]:
    """One full repaint: the theme rows, then the highlighted theme's preview."""
    lines = ["Choose an OMH TUI theme  (arrows or j/k, Enter to apply, q to cancel)"]
    for index, theme in enumerate(themes):
        pointer = ">" if index == cursor else " "
        active = "*" if theme.skin_name == active_skin else " "
        row = f" {pointer} [{active}] {theme.short_name:<{SHORT_NAME_WIDTH}} {theme.summary}"
        if index == cursor and use_color:
            row = truecolor(row, skin_colors(theme.skin_name).get("ui_accent", ""), bold=True)
        lines.append(row)
    lines.append("")
    lines.extend(preview_lines(themes[cursor], use_color=use_color))
    # Truncation is width-aware only for the plain rows; a painted row carries
    # escape bytes that no column count applies to, and cutting one mid-escape
    # would leak the sequence into the terminal.
    return [line if use_color or len(line) <= width else line[: max(0, width)] for line in lines]


def run_picker(
    themes: Sequence[SkinTheme],
    active_skin: str,
    *,
    read_key: Callable[[], str],
    write: Callable[[str], None],
    use_color: bool,
    width: int = 100,
    start_index: int = 0,
    max_keys: int = 2000,
) -> SkinTheme | None:
    """Drive the cursor until Enter or cancel. Returns the choice, or None.

    Writes nothing but frames: applying the selection is the caller's job, so
    a cancelled picker cannot have saved a theme by construction.
    """
    if not themes:
        return None
    cursor = max(0, min(start_index, len(themes) - 1))
    frame = render_frame(themes, cursor, active_skin, use_color=use_color, width=width)
    write("\n".join(frame) + "\n")
    # `max_keys` bounds a pathological reader (a stream returning nothing but
    # unknown bytes) instead of spinning forever inside a terminal in raw mode.
    for _ in range(max_keys):
        key = read_key()
        if key == KEY_QUIT:
            return None
        if key == KEY_ENTER:
            return themes[cursor]
        if key == KEY_UP:
            cursor = (cursor - 1) % len(themes)
        elif key == KEY_DOWN:
            cursor = (cursor + 1) % len(themes)
        else:
            continue
        previous_rows = len(frame)
        frame = render_frame(themes, cursor, active_skin, use_color=use_color, width=width)
        repaint = cursor_up(previous_rows) + "".join(f"{CLEAR_LINE}{line}\n" for line in frame)
        write(repaint)
    return None


def pick_theme_interactively(
    themes: Sequence[SkinTheme],
    active_skin: str,
    *,
    use_color: bool,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> SkinTheme | None:
    """`run_picker` wired to the real terminal, cursor hidden for the duration."""
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout
    start_index = next(
        (index for index, theme in enumerate(themes) if theme.skin_name == active_skin),
        0,
    )
    width = os.get_terminal_size(sink.fileno()).columns if sink.isatty() else 100
    with raw_mode(source):
        if use_color:
            sink.write(HIDE_CURSOR)
        try:
            return run_picker(
                themes,
                active_skin,
                read_key=lambda: read_terminal_key(source),
                write=lambda text: (sink.write(text), sink.flush(), None)[-1],
                use_color=use_color,
                width=width,
                start_index=start_index,
            )
        finally:
            if use_color:
                sink.write(SHOW_CURSOR)
                sink.flush()

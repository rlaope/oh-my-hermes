"""The arrow-key chain picker behind bare `omh model-chains`.

One row per mixture category. Up and down move the cursor, stopping at the
first and the last row as every OMH list does; on the selected row, left and
right step the head model through the aliases chains name today, `-` and `+`
step its reasoning effort along that model's ladder, and `d` restores the
shipped default. Enter hands every edited category back to the command, which
writes them through the same validated document `omh model-chains set` writes,
unless a pressed effort is off its head's list: then the picker stays open and
says which row. Esc, q or Ctrl-C hands back nothing, so a cancelled picker
cannot have touched the file by construction.

The chain rules — which aliases the ring holds, how an effort steps, how a
save composes the document — live in the plugin bundle's
`model_chain_picker` so `/omh-model` in the OMH TUI walks the same rows; this
module only paints frames and reads keys. The same seams as the theme picker
keep it testable without a terminal: `read_key`, `write` and the frame width
arrive as arguments, and the raw-mode reader is shared with that picker.

The frame is painted in the OMH theme's palette so it reads as part of the
same product as the OMH TUI: the cursor row sits on the skin's selection
background with `◂ model ▸` and `− effort +` markers showing which keys act
on which cell, effort bars are toned by rung, a value carries `?` when the
model's ladder is not known and `!` when the value is off its list, and a
row's state is a glyph plus a word (`● edited`, `◆ override`, `· default`).
NO_COLOR or a
non-terminal keeps the exact same text with no escape bytes. Every line is
built from fixed-width cells sized to the terminal, and the free-text lines
are cut with an ellipsis, so a frame never wraps — a wrapped line would put
the cursor-up repaint off by one row and duplicate the header.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import os
from pathlib import Path
import sys
from typing import Any, TextIO

from ..plugin_bundle.omh.model_chain_picker import (
    Chain,
    PickerChanges,
    chain_from_entries,
    chain_text,
    step_effort,
    step_head_model,
)
from ..skin_pack import hex_to_rgb, skin_colors
from .theme_picker import (
    CLEAR_LINE,
    ESC,
    HIDE_CURSOR,
    KEY_DEFAULT,
    KEY_DOWN,
    KEY_ENTER,
    KEY_LEFT,
    KEY_MINUS,
    KEY_PLUS,
    KEY_QUIT,
    KEY_RIGHT,
    KEY_UP,
    RESET,
    SHOW_CURSOR,
    cursor_up,
    raw_mode,
    read_terminal_key,
)

CURSOR_MARK = "▍"
LEFT_MARK = "◂"
RIGHT_MARK = "▸"
STATE_GLYPHS = {"edited": "●", "override": "◆", "default": "·"}
# Palette token per state word and per effort rung; the palette itself is
# the OMH theme's (`effective_theme`), so the picker follows `omh theme` like
# the TUI does.
STATE_TONES = {"edited": "ui_warn", "override": "ui_accent", "default": "banner_dim"}
EFFORT_TONES = {"low": "banner_dim", "medium": "ui_ok", "high": "ui_warn", "xhigh": "ui_accent", "max": "banner_title"}
_PROVIDERS_LABEL_WIDTH = 11
KEY_HINTS = (
    ("↑↓", "category"),
    ("←→", "head model"),
    ("−/+", "effort"),
    ("d", "default"),
    ("⏎", "save"),
    ("esc", "cancel"),
)

_MARGIN = 3
_CATEGORY_WIDTH = 19
_PURPOSE_WIDTH = 30
_MODEL_WIDTH = 24
_BAR_WIDTH = 6  # the longest ladder has six rungs above `none`
_EFFORT_WIDTH = 2 + _BAR_WIDTH + 2 + 9
_STATE_WIDTH = 11
_PURPOSE_MIN_WIDTH = _MARGIN + _CATEGORY_WIDTH + _PURPOSE_WIDTH + _MODEL_WIDTH + _EFFORT_WIDTH + _STATE_WIDTH


def default_palette() -> dict[str, str]:
    return skin_colors("omh")


def effort_bar(effort: str, ring: tuple[str, ...] = ("low", "medium", "high", "xhigh")) -> str:
    """One cell per rung above `none`; `max` fills all of them, nothing fills none."""
    cells = tuple(rung for rung in ring if rung != "none")
    if effort == "max":
        filled = len(cells)
    elif effort in cells:
        filled = cells.index(effort) + 1
    else:
        filled = 0
    return "■" * filled + "□" * (len(cells) - filled)


def _fit(text: str, width: int) -> str:
    """Pad to `width` cells, the last of them always blank."""
    if len(text) >= width:
        return text[: width - 2] + "… "
    return text.ljust(width)


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def _sgr(palette: Mapping[str, str], fg: str | None, bg: str | None, bold: bool) -> str:
    codes: list[str] = []
    if bold:
        codes.append("1")
    for token, kind in ((fg, "38"), (bg, "48")):
        rgb = hex_to_rgb(palette.get(token, "")) if token else None
        if rgb is not None:
            codes.append(f"{kind};2;{rgb[0]};{rgb[1]};{rgb[2]}")
    return f"{ESC}[{';'.join(codes)}m" if codes else ""


class _Painter:
    """Paints text with palette tokens, or returns it untouched without color."""

    def __init__(self, palette: Mapping[str, str], use_color: bool) -> None:
        self.palette = palette
        self.use_color = use_color

    def __call__(self, text: str, fg: str | None = None, *, bg: str | None = None, bold: bool = False) -> str:
        if not self.use_color or not text:
            return text
        prefix = _sgr(self.palette, fg, bg, bold)
        return f"{prefix}{text}{RESET}" if prefix else text


def row_status(row: Mapping[str, Any], chain: Chain) -> str:
    """`edited` beats the stored origin: the row shows what Enter would do."""
    if chain != chain_from_entries(row["chain"]):
        return "edited"
    return str(row["origin"])


def _effort_keys_on(payload: Mapping[str, Any]) -> bool:
    """A `model-efforts.json` broken at open turns -/+ off: its ladders are unknown."""
    return not str(payload.get("effort_document_status") or "").startswith("invalid:")


def _effort_mark(effort: str, model: Mapping[str, Any]) -> str:
    """`!` on a value a known ladder will not take or no-thinking on a head with
    no known ladder, `?` on any other value of a model whose ladder is not known."""
    if not model["efforts_configured"]:
        return "!" if effort in ("none", "off") else "?"
    return "!" if effort and effort not in model["efforts"] else ""


def _short_path(path: str) -> str:
    home = str(Path.home())
    return "~" + path[len(home):] if path.startswith(home) else path


def _row_cells(
    row: Mapping[str, Any],
    chain: Chain,
    *,
    cursor: bool,
    labels: Mapping[str, str],
    served: Mapping[str, bool],
    models: Mapping[str, Mapping[str, Any]],
    effort_keys: bool,
    with_purpose: bool,
) -> list[tuple[str, str]]:
    """The row as (text, tone) cells; tones are palette tokens for the painter."""
    head_model, head_effort = chain[0]
    label = labels.get(head_model, head_model)
    unserved = not served.get(head_model, True)
    state = row_status(row, chain)
    cells = [
        (f" {CURSOR_MARK} " if cursor else " " * _MARGIN, "ui_accent"),
        (_fit(str(row["category"]), _CATEGORY_WIDTH), "ui_label"),
    ]
    if with_purpose:
        cells.append((_fit(str(row["purpose"]), _PURPOSE_WIDTH), "banner_dim"))
    # `◂ label ▸` hugs the label on the cursor row so the markers read as
    # handles on the value, not as column borders; the cell keeps its width.
    model_text = _clip(label + (" !" if unserved else ""), _MODEL_WIDTH - 5)
    cells.append((f"{LEFT_MARK} " if cursor else "  ", "ui_accent"))
    cells.append((model_text, "ui_error" if unserved else "banner_text"))
    cells.append((f" {RIGHT_MARK}" if cursor else "  ", "ui_accent"))
    cells.append((" " * (_MODEL_WIDTH - 4 - len(model_text)), None))
    allowed = tuple(models[head_model]["efforts"])
    mark = _effort_mark(head_effort, models[head_model])
    tone = "ui_error" if mark == "!" else EFFORT_TONES.get(head_effort, "banner_dim")
    bar = effort_bar(head_effort, allowed) if allowed else "fixed"
    keys = cursor and effort_keys and bool(allowed)
    cells.append(("− " if keys else "  ", "ui_accent"))
    cells.append((bar, "ui_accent" if cursor else tone))
    cells.append((" +" if keys else "  ", "ui_accent"))
    cells.append((" " * (_BAR_WIDTH - len(bar)), None))
    cells.append((f" {(head_effort or '-')[: 7 - len(mark)] + mark:<8}", tone))
    cells.append((f"{STATE_GLYPHS[state]} {state:<{_STATE_WIDTH - 2}}", STATE_TONES[state]))
    return cells


def render_frame(
    payload: Mapping[str, Any],
    chains: Mapping[str, Chain],
    cursor: int,
    *,
    use_color: bool,
    width: int,
    palette: Mapping[str, str] | None = None,
    notice: str = "",
) -> list[str]:
    """One full repaint: title, column header, one row per category, the
    cursor row's detail, then the key hints. Every line fits `width`."""
    paint = _Painter(palette or default_palette(), use_color)
    rows = payload["categories"]
    models = {row["alias"]: row for row in payload["models"]}
    effort_keys = _effort_keys_on(payload)
    labels = {row["alias"]: row["label"] for row in payload["models"]}
    served = {row["alias"]: bool(row["served"]) for row in payload["models"]}
    with_purpose = width >= _PURPOSE_MIN_WIDTH
    row_width = min(width, _PURPOSE_MIN_WIDTH if with_purpose else _PURPOSE_MIN_WIDTH - _PURPOSE_WIDTH)
    inner = row_width - _MARGIN

    title_left = " ⚚ OMH · Model chains"
    title_right = _short_path(str(payload.get("path", "")))
    gap = row_width - len(title_left) - len(title_right)
    if gap < 2:
        title_right = _clip(title_right, max(0, row_width - len(title_left) - 2))
        gap = row_width - len(title_left) - len(title_right)
    title = paint(" ⚚ OMH", "ui_accent", bold=True) + paint(" · Model chains", "banner_title", bold=True)
    title += " " * gap + paint(title_right, "banner_dim")
    rule = paint("─" * row_width, "input_rule")

    header_cells = [(" " * _MARGIN, None), (_fit("CATEGORY", _CATEGORY_WIDTH), None)]
    if with_purpose:
        header_cells.append((_fit("PURPOSE", _PURPOSE_WIDTH), None))
    header_cells += [(_fit("  HEAD MODEL", _MODEL_WIDTH), None), (_fit("  EFFORT", _EFFORT_WIDTH), None), ("STATE", None)]
    header = paint("".join(text for text, _ in header_cells), "banner_dim")

    # The providers the served marks are judged against, each with where it
    # was found, so a `!` on a row has its reason one glance up. No provider
    # at all is said out loud: with nothing to judge against every model
    # counts as served, and a person should know the marks are empty.
    providers = list(payload.get("providers") or [])
    if providers:
        provider_text = " · ".join(f"{row['id']} ({row['source']})" for row in providers)
    else:
        provider_text = "none linked to Hermes yet · every model counts as served"
    providers_line = (
        " " * _MARGIN
        + paint(_fit("providers", _PROVIDERS_LABEL_WIDTH), "banner_dim")
        + paint(_clip(provider_text, inner - _PROVIDERS_LABEL_WIDTH), "banner_text" if providers else "banner_dim")
    )

    lines = [title, providers_line]
    # An invalid record yields no document at all: its recorded kinds are
    # dropped and a linked row it excluded counts again, so the providers
    # line above is missing the operator's own corrections. One row says so;
    # a valid or absent record adds nothing.
    entitlements_status = str(payload.get("entitlements_status") or "")
    if entitlements_status.startswith("invalid:"):
        reason = entitlements_status[len("invalid:"):].strip()
        lines.append(
            " " * _MARGIN
            + paint(_clip(f"! providers.json ignored: {reason} · any providers it excluded count again", inner), "ui_warn")
        )
    # An override document the reader rejects is ignored whole, so every row
    # below reads `default` -- the exact picture of a chain that was never
    # set. One row says the file is there and why it is not in effect.
    document_status = str(payload.get("document_status") or "")
    if document_status.startswith("invalid:"):
        reason = document_status[len("invalid:"):].strip()
        lines.append(
            " " * _MARGIN
            + paint(_clip(f"! model-chains.json ignored: {reason} · every category shows its shipped default", inner), "ui_warn")
        )
    if not effort_keys:
        reason = str(payload["effort_document_status"])[len("invalid:"):].strip()
        lines.append(
            " " * _MARGIN
            + paint(_clip(f"! model-efforts.json ignored: {reason} · −/+ are off until it is fixed", inner), "ui_warn")
        )
    lines += [rule, header]
    for index, row in enumerate(rows):
        is_cursor = index == cursor
        cells = _row_cells(
            row, chains[row["category"]], cursor=is_cursor, labels=labels, served=served, models=models,
            effort_keys=effort_keys, with_purpose=with_purpose,
        )
        if is_cursor:
            lines.append("".join(paint(text, tone, bg="selection_bg", bold=True) for text, tone in cells))
        else:
            lines.append("".join(paint(text, tone) for text, tone in cells))

    current = rows[cursor]
    chain = chains[current["category"]]
    default_chain = chain_from_entries(current["default_chain"])
    changed = sum(1 for row in rows if chains[row["category"]] != chain_from_entries(row["chain"]))
    lines.append(rule)
    heading = paint(str(current["category"]), "ui_label", bold=True)
    if current.get("purpose"):
        heading += paint(f" · {_clip(str(current['purpose']), inner - len(str(current['category'])) - 3)}", "banner_dim")
    lines.append(" " * _MARGIN + heading)
    lines.append(" " * _MARGIN + paint(_fit("chain", 18), "banner_dim") + paint(_clip(chain_text(chain), inner - 18), "banner_text"))
    head_model, head_effort = chain[0]
    model = models[head_model]
    if not model["efforts_configured"]:
        effort_text = ", ".join(model["efforts"]) + "  (ladder not known: shared steps, not checked for this model)"
    elif model["efforts"]:
        effort_text = ", ".join(model["efforts"]) + f"  ({model['efforts_source']})"
    else:
        effort_text = "fixed: this model's list is empty, so −/+ do nothing"
    lines.append(" " * _MARGIN + paint(_fit("effort", 18) + _clip(effort_text, width - _MARGIN - 18), "banner_text"))
    explained = {
        "none": "explicit no thinking; an unset effort is a different thing and inherits",
        "": "unset: the model or provider default applies, which is not the same as `none`",
        "auto": "`auto` is the provider default, not a rung",
    }.get(head_effort)
    if explained:
        lines.append(" " * _MARGIN + paint(_fit("", 18) + _clip(explained, inner - 18), "banner_dim"))
    if _effort_mark(head_effort, model) == "!" and model["efforts"]:
        if head_effort == "off":
            warning = "! `off` is the old spelling; Hermes does not read it, so the provider default runs; −/+ moves it"
        else:
            warning = f"! `{head_effort}` is not on this list; −/+ moves it onto the list"
        lines.append(" " * _MARGIN + paint(_clip(warning, width - _MARGIN), "ui_warn"))
    default_text = "✓ same as shipped" if chain == default_chain else _clip(chain_text(default_chain), inner - 18)
    lines.append(" " * _MARGIN + paint(_fit("shipped default", 18) + default_text, "banner_dim"))
    if changed:
        lines.append(" " * _MARGIN + paint(f"{changed} unsaved change{'s' if changed != 1 else ''} · ⏎ writes the file", "ui_warn"))
    else:
        lines.append(" " * _MARGIN + paint("no unsaved changes · ⏎ or esc leaves the file as it is", "banner_dim"))
    if not served.get(head_model, True):
        note = _clip(f"! {labels.get(head_model, head_model)} is not served by this machine's providers", inner)
        lines.append(" " * _MARGIN + paint(note, "ui_error"))
    if notice:
        lines.append(" " * _MARGIN + paint(_clip(notice, inner), "ui_error", bold=True))
    lines.append(rule)
    hints = "   ".join(paint(keys, "ui_accent", bold=True) + " " + paint(what, "banner_dim") for keys, what in KEY_HINTS)
    lines.append(" " * _MARGIN + hints)
    # Below the narrowest layout the plain frame is cut to the terminal; a
    # painted row carries escape bytes no column count applies to, and
    # cutting one mid-escape would leak the sequence (the theme picker's
    # rule), so colour keeps the full row there.
    if use_color:
        return lines
    return [line if len(line) <= width else line[: max(0, width - 1)] + "…" for line in lines]


def _refused_edit(
    rows: list[Mapping[str, Any]],
    chains: Mapping[str, Chain],
    original: Mapping[str, Chain],
    effort_edits: set[str],
    ladders: Mapping[str, tuple[str, ...]],
) -> tuple[int, str] | None:
    """The first row a save would refuse, as (its index, the sentence), or None.

    A pressed effort must be on its head's list; switching the head afterwards
    can carry it off. An untouched value and a model-only switch never count.
    """
    for index, row in enumerate(rows):
        name = row["category"]
        if name in effort_edits and chains[name] != original[name]:
            model, effort = chains[name][0]
            if effort not in ladders[model]:
                keys = "−/+ or d" if ladders[model] else "←→ or d"
                return index, f"! {name}: {effort} is not on {model}'s list; {keys}"
    return None


def run_picker(
    payload: Mapping[str, Any],
    *,
    read_key: Callable[[], str],
    write: Callable[[str], None],
    use_color: bool,
    width: int = 110,
    palette: Mapping[str, str] | None = None,
    max_keys: int = 4000,
) -> PickerChanges | None:
    """Drive the cursor until Enter or cancel.

    Returns the edited categories (possibly none) on Enter, or None on
    cancel. Enter with a pressed effort off its head's list stays open, on that
    row, so the session's other edits are not lost to a refused save. Writes
    nothing but frames: applying the result is the caller's job.
    """
    rows = payload["categories"]
    if not rows:
        return None
    aliases = tuple(row["alias"] for row in payload["models"])
    ladders = {row["alias"]: tuple(row["efforts"]) for row in payload["models"]}
    effort_keys = _effort_keys_on(payload)
    effort_edits: set[str] = set()
    original = {row["category"]: chain_from_entries(row["chain"]) for row in rows}
    chains = dict(original)
    cursor = 0
    frame = render_frame(payload, chains, cursor, use_color=use_color, width=width, palette=palette)
    write("\n".join(frame) + "\n")
    # `max_keys` bounds a pathological reader (a stream returning nothing but
    # unknown bytes) instead of spinning forever inside a terminal in raw mode.
    for _ in range(max_keys):
        key = read_key()
        if key == KEY_QUIT:
            return None
        notice = ""
        name = rows[cursor]["category"]
        if key == KEY_ENTER:
            refused = _refused_edit(rows, chains, original, effort_edits, ladders)
            if refused is None:
                return PickerChanges(
                    {name: chain for name, chain in chains.items() if chain != original[name]},
                    effort_edits=frozenset(effort_edits),
                )
            cursor, notice = refused
        elif key == KEY_UP:
            cursor = max(cursor - 1, 0)
        elif key == KEY_DOWN:
            cursor = min(cursor + 1, len(rows) - 1)
        elif key == KEY_LEFT:
            chains[name] = step_head_model(chains[name], aliases, -1)
        elif key == KEY_RIGHT:
            chains[name] = step_head_model(chains[name], aliases, 1)
        elif key in (KEY_MINUS, KEY_PLUS):
            if not effort_keys:
                continue
            stepped = step_effort(chains[name], 1 if key == KEY_PLUS else -1, ladders[chains[name][0][0]])
            if stepped != chains[name]:
                effort_edits.add(name)
            chains[name] = stepped
        elif key == KEY_DEFAULT:
            chains[name] = chain_from_entries(rows[cursor]["default_chain"])
            effort_edits.discard(name)
        else:
            continue
        previous_rows = len(frame)
        frame = render_frame(payload, chains, cursor, use_color=use_color, width=width, palette=palette, notice=notice)
        # The frame's height follows the head's effort and the notice, so a
        # shorter one must clear what the taller one left below it.
        write(cursor_up(previous_rows) + "".join(f"{CLEAR_LINE}{line}\n" for line in frame) + f"{ESC}[J")
    return None


def pick_chains_interactively(
    payload: Mapping[str, Any],
    *,
    use_color: bool,
    palette: Mapping[str, str] | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> PickerChanges | None:
    """`run_picker` wired to the real terminal, cursor hidden for the duration."""
    source = stdin if stdin is not None else sys.stdin
    sink = stdout if stdout is not None else sys.stdout
    width = os.get_terminal_size(sink.fileno()).columns if sink.isatty() else 110
    with raw_mode(source):
        if use_color:
            sink.write(HIDE_CURSOR)
        try:
            return run_picker(
                payload,
                read_key=lambda: read_terminal_key(source),
                write=lambda text: (sink.write(text), sink.flush(), None)[-1],
                use_color=use_color,
                width=width,
                palette=palette,
            )
        finally:
            if use_color:
                sink.write(SHOW_CURSOR)
                sink.flush()

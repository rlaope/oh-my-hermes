"""The arrow-key chain picker behind bare `omh model-chains`.

One row per mixture category. Up and down move the cursor, stopping at the
first and the last row as every OMH list does; on the selected row, left and
right step the head model through the aliases chains name today, `-` and `+`
step its reasoning effort inside that model's resolved selectable ladder
(a model with no contract or override has no ladder and refuses both keys),
and `d` restores the shipped default. Enter hands
every edited category back to the command, which writes them through the
same validated document `omh model-chains set` writes; Esc, q or Ctrl-C
hands back nothing, so a cancelled picker cannot have touched the file by
construction.

The chain rules — which aliases the ring holds, how an effort steps, how a
save composes the document — live in the plugin bundle's
`model_chain_picker` so `/omh-model` in the OMH TUI walks the same rows; this
module only paints frames and reads keys. The same seams as the theme picker
keep it testable without a terminal: `read_key`, `write` and the frame width
arrive as arguments, and the raw-mode reader is shared with that picker.

The frame is painted in the OMH theme's palette so it reads as part of the
same product as the OMH TUI: the cursor row sits on the skin's selection
background with `◂ model ▸` and `− effort +` markers showing which keys act
on which cell, effort bars are toned by rung, and rows retain their
default/override status. NO_COLOR or a
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
STATE_GLYPHS = {
    "edited": "●",
    "override": "◆",
    "default": "·",
}
# Palette token per state word and per effort rung; the palette itself is
# the OMH theme's (`effective_theme`), so the picker follows `omh theme` like
# the TUI does.
STATE_TONES = {
    "edited": "ui_warn",
    "override": "ui_accent",
    "default": "banner_dim",
}
EFFORT_TONES = {
    "none": "banner_dim",
    "minimal": "banner_dim",
    "low": "banner_dim",
    "medium": "ui_ok",
    "high": "ui_warn",
    "xhigh": "ui_accent",
    "max": "banner_title",
}
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
_EFFORT_WIDTH = 22
_STATE_WIDTH = 11
_PURPOSE_MIN_WIDTH = _MARGIN + _CATEGORY_WIDTH + _PURPOSE_WIDTH + _MODEL_WIDTH + _EFFORT_WIDTH + _STATE_WIDTH


def default_palette() -> dict[str, str]:
    return skin_colors("omh")


def effort_bar(effort: str, allowed: tuple[str, ...] = ()) -> str:
    """One cell per selectable rung; `none`/unset fill nothing.

    The bar is sized to the model's own ladder, so a three-rung model and a
    six-rung model are both read at a glance without pretending the shorter
    one has rungs it does not. An effort outside `allowed` (a historical
    value awaiting a +/- edit) fills nothing; the row marks it with `!` and
    the detail line says why.
    """
    if not allowed:
        return ""
    if not effort or effort in ("none", "off") or effort not in allowed:
        filled = 0
    else:
        filled = allowed.index(effort) + 1
    return "■" * filled + "□" * (len(allowed) - filled)


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
    efforts: Mapping[str, tuple[str, ...] | None],
    with_purpose: bool,
) -> list[tuple[str, str | None]]:
    """The row as (text, tone) cells; tones are palette tokens for the painter."""
    head_model, head_effort = chain[0]
    label = labels.get(head_model, head_model)
    unserved = not served.get(head_model, True)
    state = row_status(row, chain)
    cells: list[tuple[str, str | None]] = [
        (f" {CURSOR_MARK} " if cursor else " " * _MARGIN, "ui_accent"),
        (
            _fit(
                str(row["category"]),
                _CATEGORY_WIDTH,
            ),
            "ui_label",
        ),
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
    allowed = efforts.get(head_model)
    unsupported = bool(head_effort) and allowed is not None and head_effort not in allowed
    tone = "ui_error" if unsupported else EFFORT_TONES.get(head_effort, "banner_dim")
    value_cell = f"{(head_effort or '-') + ('!' if unsupported else ''):<8}"[:8]
    if allowed is None:
        # No contract and no user override: show the stored value, say the
        # model is unconfigured, and leave the +/- handles off. Never fall
        # back to a common ladder here.
        cells.append(("  ", None))
        cells.append((f"{'unconfigured':<12}", "ui_error" if cursor else "banner_dim"))
        cells.append((" ", None))
        cells.append((f"{(head_effort or '-')[:6]:<6}", tone))
    elif not allowed:
        # A user override with an empty list is a deliberate "no knob",
        # distinct from the unknown model above.
        cells.append(("  ", None))
        cells.append((f"{'no knob':<8}", "banner_dim"))
        cells.append(("  ", None))
        cells.append((value_cell, tone))
    else:
        cells.append((f"{'− ' if cursor else '  '}", "ui_accent"))
        cells.append((f"{effort_bar(head_effort, allowed):<8}", "ui_accent" if cursor else tone))
        cells.append((f"{' +' if cursor else '  '}", "ui_accent"))
        cells.append((value_cell, tone))
    cells.append(("  " if allowed is not None else " ", None))
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
) -> list[str]:
    """One full repaint: title, column header, one row per category, the
    cursor row's detail, then the key hints. Every line fits `width`."""
    paint = _Painter(palette or default_palette(), use_color)
    rows = payload["categories"]
    labels = {row["alias"]: row["label"] for row in payload["models"]}
    served = {row["alias"]: bool(row["served"]) for row in payload["models"]}
    efforts = {
        row["alias"]: tuple(row["efforts"]) if row.get("efforts") is not None else None
        for row in payload["models"]
    }
    effort_sources = {row["alias"]: str(row.get("efforts_source", "") or "unknown") for row in payload["models"]}
    with_purpose = width >= _PURPOSE_MIN_WIDTH
    row_width = min(width, _PURPOSE_MIN_WIDTH if with_purpose else _PURPOSE_MIN_WIDTH - _PURPOSE_WIDTH)
    inner = row_width - _MARGIN

    title_name = "Model chains"
    title_left = f" ⚚ OMH · {title_name}"
    title_right = _short_path(str(payload.get("path", "")))
    gap = row_width - len(title_left) - len(title_right)
    if gap < 2:
        title_right = _clip(title_right, max(0, row_width - len(title_left) - 2))
        gap = row_width - len(title_left) - len(title_right)
    title = paint(" ⚚ OMH", "ui_accent", bold=True) + paint(f" · {title_name}", "banner_title", bold=True)
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
    # A model-effort document the reader rejects is ignored whole as well. The
    # built-in contract ladders still apply, but a custom model the file meant
    # to configure stays unconfigured; saying so is what keeps that fallback
    # from silently widening the choices.
    effort_document_status = str(payload.get("effort_document_status") or "")
    if effort_document_status.startswith("invalid:"):
        reason = effort_document_status[len("invalid:"):].strip()
        lines.append(
            " " * _MARGIN
            + paint(
                _clip(
                    f"! model-efforts.json ignored: {reason} · built-in ladders apply; custom models stay unconfigured",
                    inner,
                ),
                "ui_warn",
            )
        )
    lines += [rule, header]
    for index, row in enumerate(rows):
        is_cursor = index == cursor
        cells = _row_cells(
            row, chains[row["category"]], cursor=is_cursor, labels=labels, served=served, efforts=efforts,
            with_purpose=with_purpose,
        )
        if is_cursor:
            lines.append("".join(paint(text, tone, bg="selection_bg", bold=True) for text, tone in cells))
        else:
            lines.append("".join(paint(text, tone) for text, tone in cells))

    current = rows[cursor]
    chain = chains[current["category"]]
    default_chain = chain_from_entries(current["default_chain"])
    changed = sum(
        1
        for row in rows
        if chains[row["category"]] != chain_from_entries(row["chain"])
    )
    lines.append(rule)
    heading = paint(str(current["category"]), "ui_label", bold=True)
    if current.get("purpose"):
        heading += paint(f" · {_clip(str(current['purpose']), inner - len(str(current['category'])) - 3)}", "banner_dim")
    lines.append(" " * _MARGIN + heading)
    lines.append(" " * _MARGIN + paint(_fit("chain", 18), "banner_dim") + paint(_clip(chain_text(chain), inner - 18), "banner_text"))
    head_model, head_effort = chain[0]
    allowed = efforts.get(head_model)
    if allowed is None:
        effort_text = "unconfigured · no contract or override names this model; +/- disabled"
        effort_tone = "banner_dim"
    elif not allowed:
        effort_text = "no adjustable effort · this model is configured with an empty list"
        effort_tone = "banner_dim"
    else:
        source = effort_sources.get(head_model, "unknown")
        effort_text = ", ".join(allowed) + f"  ({source})"
        effort_tone = "banner_text"
    lines.append(" " * _MARGIN + paint(_fit("effort", 18) + _clip(effort_text, inner - 18), effort_tone))
    if head_effort == "none":
        lines.append(
            " " * _MARGIN
            + paint(
                _clip("thinking         explicit no thinking (`none`); an empty effort means unset/inherits", inner),
                "banner_dim",
            )
        )
    elif not head_effort:
        lines.append(
            " " * _MARGIN
            + paint(
                _clip("effort           unset: the model/provider default applies (not the same as `none`)", inner),
                "banner_dim",
            )
        )
    elif head_effort == "auto":
        lines.append(
            " " * _MARGIN
            + paint(_clip("effort           `auto` is the provider default (legacy; not a selectable rung)", inner), "banner_dim")
        )
    if allowed and head_effort and head_effort not in allowed:
        if head_effort == "off":
            warning = "! `off` is the legacy spelling of `none`; +/- rewrites it as `none`"
        else:
            warning = (
                f"! chosen effort `{head_effort}` is not selectable for this model; "
                "+/- moves it into the list"
            )
        lines.append(" " * _MARGIN + paint(_clip(warning, inner), "ui_warn"))
    default_text = "✓ same as shipped" if chain == default_chain else _clip(chain_text(default_chain), inner - 18)
    lines.append(" " * _MARGIN + paint(_fit("shipped default", 18) + default_text, "banner_dim"))
    if changed:
        lines.append(" " * _MARGIN + paint(f"{changed} unsaved change{'s' if changed != 1 else ''} · ⏎ writes the file", "ui_warn"))
    else:
        lines.append(" " * _MARGIN + paint("no unsaved changes · ⏎ or esc leaves the file as it is", "banner_dim"))
    if not served.get(head_model, True):
        note = _clip(f"! {labels.get(head_model, head_model)} is not served by this machine's providers", inner)
        lines.append(" " * _MARGIN + paint(note, "ui_error"))
    lines.append(rule)
    hint_items = KEY_HINTS
    hints = "   ".join(paint(keys, "ui_accent", bold=True) + " " + paint(what, "banner_dim") for keys, what in hint_items)
    lines.append(" " * _MARGIN + hints)
    # Below the narrowest layout the plain frame is cut to the terminal; a
    # painted row carries escape bytes no column count applies to, and
    # cutting one mid-escape would leak the sequence (the theme picker's
    # rule), so colour keeps the full row there.
    if use_color:
        return lines
    return [line if len(line) <= width else line[: max(0, width - 1)] + "…" for line in lines]


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
    cancel. Writes nothing but frames: applying the result is the caller's
    job.
    """
    rows = payload["categories"]
    if not rows:
        return None
    aliases = tuple(row["alias"] for row in payload["models"])
    efforts = {
        row["alias"]: tuple(row["efforts"]) if row.get("efforts") is not None else None
        for row in payload["models"]
    }
    original = {row["category"]: chain_from_entries(row["chain"]) for row in rows}
    chains = dict(original)
    effort_edits: set[str] = set()
    cursor = 0
    frame = render_frame(
        payload, chains, cursor, use_color=use_color, width=width, palette=palette
    )
    write("\n".join(frame) + "\n")
    # `max_keys` bounds a pathological reader (a stream returning nothing but
    # unknown bytes) instead of spinning forever inside a terminal in raw mode.
    for _ in range(max_keys):
        key = read_key()
        if key == KEY_QUIT:
            return None
        if key == KEY_ENTER:
            return PickerChanges(
                {name: chain for name, chain in chains.items() if chain != original[name]},
                effort_edits=frozenset(effort_edits),
            )
        name = rows[cursor]["category"]
        if key == KEY_UP:
            cursor = max(cursor - 1, 0)
        elif key == KEY_DOWN:
            cursor = min(cursor + 1, len(rows) - 1)
        elif key == KEY_LEFT:
            chains[name] = step_head_model(chains[name], aliases, -1)
        elif key == KEY_RIGHT:
            chains[name] = step_head_model(chains[name], aliases, 1)
        elif key == KEY_MINUS:
            allowed = efforts.get(chains[name][0][0])
            if not allowed:
                continue
            stepped = step_effort(chains[name], -1, allowed)
            if stepped != chains[name]:
                effort_edits.add(name)
            chains[name] = stepped
        elif key == KEY_PLUS:
            allowed = efforts.get(chains[name][0][0])
            if not allowed:
                continue
            stepped = step_effort(chains[name], 1, allowed)
            if stepped != chains[name]:
                effort_edits.add(name)
            chains[name] = stepped
        elif key == KEY_DEFAULT:
            chains[name] = chain_from_entries(rows[cursor]["default_chain"])
            effort_edits.discard(name)
        else:
            continue
        previous_rows = len(frame)
        frame = render_frame(
            payload, chains, cursor, use_color=use_color, width=width, palette=palette
        )
        write(cursor_up(previous_rows) + "".join(f"{CLEAR_LINE}{line}\n" for line in frame))
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

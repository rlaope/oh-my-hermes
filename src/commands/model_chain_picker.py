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

The frame is painted through the OMH TUI's `Theme` roles (`tui/theme.py`), so
it reads like every other OMH picker and follows `/theme`, the launch look and
a light background as the TUI does. It has no fill: the cursor row is told
apart by the `❯` pointer (`prompts.CHOICE_MARK`) and its name bold in
`menu_current`, other names are `menu`, and the words around them are the
neutral greys (`muted`, `hint`, `faint`). The launch look owns the rules
(`rule`) and an effort bar's filled cells (`accent`); hue is kept for what
says a state (`ok`, `warn`, `error`). On the cursor row `◂ model ▸` and
`− effort +` mark which keys act on which cell; a value carries `?` when the
model ladder is unknown and `!` off its list. Built-in rows say `built-in`
or `customized`; custom identities say `enabled` or `disabled`. NO_COLOR or a
non-terminal keeps the exact same text with no escape bytes. Every line is
built from fixed-width cells sized to the terminal, and the free-text lines
are cut with an ellipsis, so a frame never wraps — a wrapped line would put
the cursor-up repaint off by one row and duplicate the header.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
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
from ..tui.prompts import CHOICE_MARK
from ..tui.style import TRUECOLOR, Style
from ..tui.theme import DEFAULT_THEME, Theme
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
    KEY_TOGGLE,
    KEY_UP,
    RESET,
    SHOW_CURSOR,
    cursor_up,
    raw_mode,
    read_terminal_key,
)

CURSOR_MARK = CHOICE_MARK.strip()
LEFT_MARK = "◂"
RIGHT_MARK = "▸"
STATE_GLYPHS = {
    "edited": "●",
    "customized": "◆",
    "built-in": "·",
    "enabled": "●",
    "disabled": "×",
}
# The `Theme` role each state word is painted in.
STATE_ROLES = {
    "edited": "warn",
    "customized": "label",
    "built-in": "faint",
    "enabled": "ok",
    "disabled": "error",
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
CUSTOM_KEY_HINT = ("space", "toggle custom")

_MARGIN = 3
_CATEGORY_WIDTH = 19
_PURPOSE_WIDTH = 30
_MODEL_WIDTH = 24
_BAR_WIDTH = 6  # the longest ladder has six rungs above `none`
_EFFORT_WIDTH = 2 + _BAR_WIDTH + 2 + 9
_STATE_WIDTH = 11
_PURPOSE_MIN_WIDTH = _MARGIN + _CATEGORY_WIDTH + _PURPOSE_WIDTH + _MODEL_WIDTH + _EFFORT_WIDTH + _STATE_WIDTH


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


class _Painter:
    """Paints text in a `Theme` role's style at `depth`, or returns it untouched without color."""

    def __init__(self, use_color: bool, depth: str) -> None:
        self.use_color = use_color
        self.depth = depth

    def __call__(self, text: str, style: Style | None = None) -> str:
        if not self.use_color or not text or style is None:
            return text
        prefix = replace(style, depth=self.depth).sgr()
        return f"{prefix}{text}{RESET}" if prefix else text


def row_status(row: Mapping[str, Any], chain: Chain, enabled: bool | None = None) -> str:
    """Edited state wins; rows then show type-specific configuration status."""
    if chain != chain_from_entries(row["chain"]):
        return "edited"
    if row.get("type") == "custom":
        if enabled is None:
            enabled = bool(row.get("enabled", True))
        return "enabled" if enabled else "disabled"
    return "customized" if row.get("origin") == "override" else "built-in"


def _effort_keys_on(payload: Mapping[str, Any]) -> bool:
    """A `model-efforts.json` broken at open turns -/+ off: its ladders are unknown."""
    return not str(payload.get("effort_document_status") or "").startswith("invalid:")


def _effort_mark(effort: str, model: Mapping[str, Any]) -> str:
    """`!` on a value the route or a known ladder will not take, `?` on any other
    value of a model whose ladder is not known."""
    no_thinking = effort in ("none", "off")
    if no_thinking and (model["refuses_none"] or not model["efforts_configured"]):
        return "!"
    if not model["efforts_configured"]:
        return "?"
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
    enabled: bool,
    theme: Theme,
) -> list[tuple[str, Style | None]]:
    """The row as (text, style) cells; styles are `theme`'s roles for the painter."""
    head_model, head_effort = chain[0]
    label = labels.get(head_model, head_model)
    unserved = not served.get(head_model, True)
    state = row_status(row, chain, enabled)
    cells: list[tuple[str, Style | None]] = [
        (f" {CHOICE_MARK}" if cursor else " " * _MARGIN, theme.menu_current if cursor else None),
        (
            _fit(
                f"custom:{row['category']}" if row.get("type") == "custom" else str(row["category"]),
                _CATEGORY_WIDTH,
            ),
            theme.menu_current if cursor else theme.menu,
        ),
    ]
    if with_purpose:
        cells.append((_fit(str(row["purpose"]), _PURPOSE_WIDTH), theme.muted))
    # `◂ label ▸` hugs the label on the cursor row so the markers read as
    # handles on the value, not as column borders; the cell keeps its width.
    model_text = _clip(label + (" !" if unserved else ""), _MODEL_WIDTH - 5)
    handle = theme.menu_current if cursor else None
    cells.append((f"{LEFT_MARK} " if cursor else "  ", handle))
    cells.append((model_text, theme.error if unserved else theme.user if cursor else theme.text))
    cells.append((f" {RIGHT_MARK}" if cursor else "  ", handle))
    cells.append((" " * (_MODEL_WIDTH - 4 - len(model_text)), None))
    allowed = tuple(models[head_model]["efforts"])
    mark = _effort_mark(head_effort, models[head_model])
    word = theme.error if mark == "!" else theme.warn if mark == "?" else theme.muted
    bar = effort_bar(head_effort, allowed) if allowed else "fixed"
    keys = cursor and effort_keys and bool(allowed)
    cells.append(("− " if keys else "  ", handle))
    if allowed:
        filled = bar.count("■")
        cells.append((bar[:filled], theme.error if mark == "!" else theme.accent))
        cells.append((bar[filled:], theme.dim))
    else:
        cells.append((bar, theme.muted))
    cells.append((" +" if keys else "  ", handle))
    cells.append((" " * (_BAR_WIDTH - len(bar)), None))
    cells.append((f" {(head_effort or '-')[: 7 - len(mark)] + mark:<8}", word))
    cells.append((f"{STATE_GLYPHS[state]} {state:<{_STATE_WIDTH - 2}}", getattr(theme, STATE_ROLES[state])))
    return cells


def render_frame(
    payload: Mapping[str, Any],
    chains: Mapping[str, Chain],
    cursor: int,
    *,
    use_color: bool,
    width: int,
    theme: Theme | None = None,
    depth: str = TRUECOLOR,
    notice: str = "",
    enabled_overrides: Mapping[str, bool] | None = None,
) -> list[str]:
    """One full repaint: title, column header, one row per category, the
    cursor row's detail, then the key hints. Every line fits `width`.

    `theme` (the OMH TUI's default when None) is painted at `depth`."""
    theme = theme or DEFAULT_THEME
    paint = _Painter(use_color, depth)
    rows = payload.get("rows") or payload["categories"]
    models = {row["alias"]: row for row in payload["models"]}
    effort_keys = _effort_keys_on(payload)
    labels = {row["alias"]: row["label"] for row in payload["models"]}
    served = {row["alias"]: bool(row["served"]) for row in payload["models"]}
    enabled = {row.get("key", row["category"]): bool(row.get("enabled", True)) for row in rows}
    enabled.update(enabled_overrides or {})
    with_purpose = width >= _PURPOSE_MIN_WIDTH
    row_width = min(width, _PURPOSE_MIN_WIDTH if with_purpose else _PURPOSE_MIN_WIDTH - _PURPOSE_WIDTH)
    inner = row_width - _MARGIN

    title_name = "Models & identities" if any(row.get("type") == "custom" for row in rows) else "Model chains"
    title_left = f" ⚚ OMH · {title_name}"
    title_right = _short_path(str(payload.get("path", "")))
    gap = row_width - len(title_left) - len(title_right)
    if gap < 2:
        title_right = _clip(title_right, max(0, row_width - len(title_left) - 2))
        gap = row_width - len(title_left) - len(title_right)
    title = paint(" ⚚ OMH", theme.brand) + paint(f" · {title_name}", theme.heading)
    title += " " * gap + paint(title_right, theme.muted)
    rule = paint("─" * row_width, theme.rule if theme.rule.fg else theme.muted)

    header_cells = [(" " * _MARGIN, None), (_fit("CATEGORY", _CATEGORY_WIDTH), None)]
    if with_purpose:
        header_cells.append((_fit("PURPOSE", _PURPOSE_WIDTH), None))
    header_cells += [(_fit("  HEAD MODEL", _MODEL_WIDTH), None), (_fit("  EFFORT", _EFFORT_WIDTH), None), ("STATE", None)]
    header = paint("".join(text for text, _ in header_cells), theme.muted)

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
        + paint(_fit("providers", _PROVIDERS_LABEL_WIDTH), theme.muted)
        + paint(_clip(provider_text, inner - _PROVIDERS_LABEL_WIDTH), theme.text if providers else theme.muted)
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
            + paint(_clip(f"! providers.json ignored: {reason} · any providers it excluded count again", inner), theme.warn)
        )
    # An override document the reader rejects is ignored whole, so every row
    # below reads `default` -- the exact picture of a chain that was never
    # set. One row says the file is there and why it is not in effect.
    document_status = str(payload.get("document_status") or "")
    if document_status.startswith("invalid:"):
        reason = document_status[len("invalid:"):].strip()
        lines.append(
            " " * _MARGIN
            + paint(_clip(f"! model-chains.json ignored: {reason} · every category shows its shipped default", inner), theme.warn)
        )
    if not effort_keys:
        reason = str(payload["effort_document_status"])[len("invalid:"):].strip()
        lines.append(
            " " * _MARGIN
            + paint(_clip(f"! model-efforts.json ignored: {reason} · −/+ are off until it is fixed", inner), theme.warn)
        )
    lines += [rule, header]
    for index, row in enumerate(rows):
        if row.get("type") == "custom" and (index == 0 or rows[index - 1].get("type") != "custom"):
            lines.append(" " * _MARGIN + paint("── Custom identities ──", theme.heading))
        is_cursor = index == cursor
        cells = _row_cells(
            row, chains[row.get("key", row["category"])], cursor=is_cursor, labels=labels, served=served, models=models,
            effort_keys=effort_keys, with_purpose=with_purpose, enabled=enabled[row.get("key", row["category"])],
            theme=theme,
        )
        lines.append("".join(paint(text, style) for text, style in cells))

    current = rows[cursor]
    chain = chains[current.get("key", current["category"])]
    default_chain = chain_from_entries(current["default_chain"])
    changed = sum(
        1
        for row in rows
        if chains[row.get("key", row["category"])] != chain_from_entries(row["chain"])
        or (
            row.get("type") == "custom"
            and enabled[row.get("key", row["category"])] != bool(row.get("enabled", True))
        )
    )
    lines.append(rule)
    heading = paint(str(current["category"]), theme.user)
    if current.get("purpose"):
        heading += paint(f" · {_clip(str(current['purpose']), inner - len(str(current['category'])) - 3)}", theme.muted)
    lines.append(" " * _MARGIN + heading)
    lines.append(" " * _MARGIN + paint(_fit("chain", 18), theme.muted) + paint(_clip(chain_text(chain), inner - 18), theme.text))
    head_model, head_effort = chain[0]
    model = models[head_model]
    if not model["efforts_configured"]:
        effort_text = ", ".join(model["efforts"]) + "  (ladder not known: shared steps, not checked for this model)"
    elif model["efforts"]:
        effort_text = ", ".join(model["efforts"]) + f"  ({model['efforts_source']})"
    else:
        effort_text = "fixed: this model's list is empty, so −/+ do nothing"
    lines.append(" " * _MARGIN + paint(_fit("effort", 18), theme.muted) + paint(_clip(effort_text, width - _MARGIN - 18), theme.text))
    explained = {
        "none": "explicit no thinking; an unset effort is a different thing and inherits",
        "": "unset: the model or provider default applies, which is not the same as `none`",
        "auto": "`auto` is the provider default, not a rung",
    }.get(head_effort)
    if explained:
        lines.append(" " * _MARGIN + paint(_fit("", 18) + _clip(explained, inner - 18), theme.hint))
    if _effort_mark(head_effort, model) == "!" and model["efforts"]:
        if model["refuses_none"] and head_effort in ("none", "off"):
            warning = f"! the route refuses `{head_effort}` on {head_model}: thinking is always on; −/+ moves it"
        elif head_effort == "off":
            warning = "! `off` is the old spelling; Hermes does not read it, so the provider default runs; −/+ moves it"
        else:
            warning = f"! `{head_effort}` is not on this list; −/+ moves it onto the list"
        lines.append(" " * _MARGIN + paint(_clip(warning, width - _MARGIN), theme.warn))
    if current.get("type") == "custom":
        current_state = "enabled" if enabled[current.get("key", current["category"])] else "disabled"
        lines.append(
            " " * _MARGIN + paint(_fit("status", 18), theme.muted)
            + paint(current_state, theme.ok if current_state == "enabled" else theme.error)
        )
    else:
        default_text = "✓ same as shipped" if chain == default_chain else _clip(chain_text(default_chain), inner - 18)
        lines.append(" " * _MARGIN + paint(_fit("shipped default", 18) + default_text, theme.muted))
    if changed:
        lines.append(" " * _MARGIN + paint(f"{changed} unsaved change{'s' if changed != 1 else ''} · ⏎ writes the file", theme.warn))
    else:
        lines.append(" " * _MARGIN + paint("no unsaved changes · ⏎ or esc leaves the file as it is", theme.hint))
    if not served.get(head_model, True):
        note = _clip(f"! {labels.get(head_model, head_model)} is not served by this machine's providers", inner)
        lines.append(" " * _MARGIN + paint(note, theme.error))
    if notice:
        lines.append(" " * _MARGIN + paint(_clip(notice, inner), replace(theme.error, bold=True)))
    lines.append(rule)
    hint_items = KEY_HINTS + ((CUSTOM_KEY_HINT,) if any(row.get("type") == "custom" for row in rows) else ())
    hints = "   ".join(paint(keys, theme.user) + " " + paint(what, theme.hint) for keys, what in hint_items)
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
        name = row.get("key", row["category"])
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
    theme: Theme | None = None,
    depth: str = TRUECOLOR,
    max_keys: int = 4000,
) -> PickerChanges | None:
    """Drive the cursor until Enter or cancel.

    Returns the edited categories (possibly none) on Enter, or None on
    cancel. Enter with a pressed effort off its head's list stays open, on that
    row, so the session's other edits are not lost to a refused save. Writes
    nothing but frames: applying the result is the caller's job.
    """
    rows = payload.get("rows") or payload["categories"]
    if not rows:
        return None
    aliases = tuple(row["alias"] for row in payload["models"])
    ladders = {row["alias"]: tuple(row["efforts"]) for row in payload["models"]}
    effort_keys = _effort_keys_on(payload)
    effort_edits: set[str] = set()
    original = {row.get("key", row["category"]): chain_from_entries(row["chain"]) for row in rows}
    chains = dict(original)
    original_enabled = {row.get("key", row["category"]): bool(row.get("enabled", True)) for row in rows}
    enabled = dict(original_enabled)
    cursor = 0
    frame = render_frame(
        payload, chains, cursor, use_color=use_color, width=width, theme=theme, depth=depth, enabled_overrides=enabled
    )
    write("\n".join(frame) + "\n")
    # `max_keys` bounds a pathological reader (a stream returning nothing but
    # unknown bytes) instead of spinning forever inside a terminal in raw mode.
    for _ in range(max_keys):
        key = read_key()
        if key == KEY_QUIT:
            return None
        notice = ""
        name = rows[cursor].get("key", rows[cursor]["category"])
        if key == KEY_ENTER:
            refused = _refused_edit(rows, chains, original, effort_edits, ladders)
            if refused is None:
                return PickerChanges(
                    {
                        row.get("key", row["category"]): (
                            {"chain": chains[row["key"]], "enabled": enabled[row["key"]]}
                            if row.get("type") == "custom" else chains[row["category"]]
                        )
                        for row in rows
                        if chains[row.get("key", row["category"])] != original[row.get("key", row["category"])]
                        or enabled[row.get("key", row["category"])] != original_enabled[row.get("key", row["category"])]
                    },
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
        elif key == KEY_TOGGLE and rows[cursor].get("type") == "custom":
            enabled[name] = not enabled[name]
        elif key == KEY_DEFAULT and rows[cursor].get("type") != "custom":
            chains[name] = chain_from_entries(rows[cursor]["default_chain"])
            effort_edits.discard(name)
        else:
            continue
        previous_rows = len(frame)
        frame = render_frame(
            payload, chains, cursor, use_color=use_color, width=width, theme=theme, depth=depth, notice=notice,
            enabled_overrides=enabled,
        )
        # The frame's height follows the head's effort and the notice, so a
        # shorter one must clear what the taller one left below it.
        write(cursor_up(previous_rows) + "".join(f"{CLEAR_LINE}{line}\n" for line in frame) + f"{ESC}[J")
    return None


def pick_chains_interactively(
    payload: Mapping[str, Any],
    *,
    use_color: bool,
    theme: Theme | None = None,
    depth: str = TRUECOLOR,
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
                theme=theme,
                depth=depth,
            )
        finally:
            if use_color:
                sink.write(SHOW_CURSOR)
                sink.flush()

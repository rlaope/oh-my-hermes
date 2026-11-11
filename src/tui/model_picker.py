"""The model picker: `/model` alone lists the models Hermes offers this session, filtered as you type.

`model.options {session_id}` answers with the providers Hermes can reach,
each with the models it lists, and the session's current model and provider.
The picker shows one row per provider and model, the current one marked and
highlighted (a model Hermes runs but no provider lists, such as a route the
provider's own list leaves out, comes first, so the session's model is always
a row), the position of the highlight once the list scrolls (`Model
(12/162)`), and returns the one picked; its last row is the filter
(`session_picker.filter_line`), where the composer is drawn while no picker is
open. The picker holds no IO: the app sends the
pick as `config.set model` with `<name> --provider <slug> --session`
(`gateway_contract.model_switch_value`), so the switch is Hermes' and lasts
for this session only. A name or slug that is not one plain word
(whitespace, a leading dash of any kind, a control character) is left out,
so a pick can never add a flag such as `--global` to that value
(`gateway_contract.plain_word`).

Keys: Up/Down move one row, PageUp/PageDown one page; printable text filters
(model or provider, ignoring case) and Backspace takes a filter character
back; Enter picks the highlighted row; Esc or Ctrl+C closes.

The picker opens as `/model` runs, `loading` until Hermes' list comes: what is
typed meanwhile is already its filter, Enter waits for the rows, and Esc
closes it, so the list that comes later opens nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .escapes import strip_escapes
from .gateway_contract import MODEL_PROVIDER_FLAG, MODEL_SESSION_FLAG, model_switch_value, plain_word
from ..system.local_store import atomic_write_json, read_json_object_result
from .keys import BACKSPACE, CHAR, DOWN, ENTER, ESCAPE, PAGE_DOWN, PAGE_UP, UP, Key, Paste, list_nav_step
from .prompts import CHOICE_MARK
from .session_picker import picker_frame, picker_row
from .style import Line, Span
from .theme import Theme
from .width import cell_width

PICK = "pick"
CLOSE = "close"
# Its keys, longest first: on the info line while it is open.
KEYS = ("↑↓ move · enter switches this session · esc closes", "↑↓ enter switches · esc closes", "esc closes")
TITLE = " Model ({count})"
TITLE_AT = " Model ({at}/{count})"  # once the list has more rows than it shows
TITLE_LOADING = " Model"
LOADING = " waiting for Hermes…"  # the row while the list is on its way (the app's `LIST_WAIT_LINE`)
CURRENT_MARK = "●"
# The recent list: the last switches Hermes confirmed, newest first, kept under the OMH home.
RECENT_SCHEMA = "omh_tui_recent_models/v1"
RECENT_LIMIT = 5
RECENT_GROUP = "Recent"
ALL_GROUP = "All models"  # heads the whole list under the recent rows; with no recent row there is no heading


@dataclass(frozen=True)
class ModelRow:
    model: str
    provider: str  # the slug `--provider` takes
    provider_name: str
    current: bool

    @property
    def arg(self) -> str:
        """What `config.set model` takes to switch this session, and only this session, to this row."""
        return model_switch_value(self.model, self.provider)


@dataclass(frozen=True)
class ModelAction:
    kind: str  # PICK or CLOSE
    row: ModelRow | None = None


def _name(value: object, fallback: str) -> str:
    text = "".join(char for char in strip_escapes(value) if char.isprintable()) if isinstance(value, str) else ""
    return text.strip() or fallback


def typed_switch_value(arg: str) -> str:
    """`/model`'s arguments as a `config.set model` value, when they name a model, maybe its provider, and `--session`.

    That is what Hermes' own TUI sends for them (`session.ts`
    `modelValueForConfigSet`, as typed): `--session` only when it was typed,
    so without it Hermes' stdio entry applies its own persistence rule
    (`model.persist_switch_by_default`) as its typed `/model` does. "" for any
    other flag (`--global`, `--once`, `--reasoning`), which goes to Hermes'
    `/model` as typed.
    """
    words = arg.split()
    model, provider, session, rest = (words[0] if words else ""), "", False, words[1:]
    while rest:
        flag = rest.pop(0)
        if flag == MODEL_SESSION_FLAG:
            session = True
            continue
        if flag == MODEL_PROVIDER_FLAG and rest and not provider:
            provider = rest.pop(0)
            continue
        return ""
    return model_switch_value(model, provider, session)


def recent_path(omh_home: Path) -> Path:
    """Where the recent switches are kept: under the OMH home, beside the TUI's other choices."""
    return Path(omh_home) / "tui" / "recent-models.json"


def read_recent(omh_home: Path) -> list[tuple[str, str]]:
    """The (model, provider) pairs last switched to, newest first; [] when the file is missing, unreadable, or not
    this module's. An entry that is not two plain words is skipped."""
    record, _error = read_json_object_result(recent_path(omh_home))
    entries = record.get("models") if record is not None and record.get("schema_version") == RECENT_SCHEMA else None
    pairs: list[tuple[str, str]] = []
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict):
            pair = (plain_word(entry.get("model")), plain_word(entry.get("provider")))
            if all(pair) and pair not in pairs:
                pairs.append(pair)
    return pairs[:RECENT_LIMIT]


def record_recent(omh_home: Path, model: str, provider: str) -> bool:
    """Put `model` on `provider` at the front of the recent list, dropping its older place and anything past
    `RECENT_LIMIT`; whether it was written (a pair that is not two plain words, or a home that cannot be written,
    writes nothing)."""
    pair = (plain_word(model), plain_word(provider))
    if not all(pair):
        return False
    pairs = [pair, *(kept for kept in read_recent(omh_home) if kept != pair)][:RECENT_LIMIT]
    record = {"schema_version": RECENT_SCHEMA, "models": [{"model": m, "provider": p} for m, p in pairs]}
    try:
        atomic_write_json(recent_path(omh_home), record)
    except OSError:
        return False
    return True


def model_rows(result: Mapping[str, object]) -> list[ModelRow]:
    """Every provider's models in a `model.options` answer, in Hermes' order; a malformed or unsafe one is skipped.

    A row is current when its model is the session's and its provider is the
    session's, by slug, by one of the provider's `aliases`, or as the one
    Hermes marks `is_current`. When no row is, the session's model and
    provider come first as a row of their own, if both are plain words.
    """
    model, provider = result.get("model"), result.get("provider")
    providers = result.get("providers")
    rows: list[ModelRow] = []
    for entry in providers if isinstance(providers, list) else []:
        if not isinstance(entry, dict):
            continue
        slug, models = plain_word(entry.get("slug")), entry.get("models")
        if not slug or not isinstance(models, list):
            continue
        name = _name(entry.get("name"), slug)
        aliases = entry.get("aliases")
        current_provider = (
            slug == provider or entry.get("is_current") is True
            or (isinstance(aliases, list) and isinstance(provider, str) and provider in aliases)
        )
        for listed in map(plain_word, models):
            if listed:
                rows.append(ModelRow(listed, slug, name, current_provider and listed == model))
    running, running_provider = plain_word(model), plain_word(provider)
    if running and running_provider and not any(row.current for row in rows):
        name = next((row.provider_name for row in rows if row.provider == running_provider), running_provider)
        rows.insert(0, ModelRow(running, running_provider, name, True))
    return rows


@dataclass
class ModelPicker:
    rows: list[ModelRow]
    current: str  # the session's model, named in the header whether or not a row holds it
    query: str = ""
    index: int = -1  # -1 picks the current row, else the first
    page: int = 1  # rows the last render showed; PageUp/PageDown move by this many
    caret: tuple[int, int] | None = None  # the last render's caret, at the end of its filter row
    loading: bool = False  # opened before Hermes' list came: no rows yet, the filter already takes what is typed
    recent: list[tuple[str, str]] = field(default_factory=list)  # `read_recent`'s pairs, newest first

    def __post_init__(self) -> None:
        if self.index < 0:
            self.index = next((number for number, row in enumerate(self.visible()) if row.current), 0)

    def recent_rows(self) -> list[ModelRow]:
        """The rows of the recent pairs Hermes still lists, newest first; none while a filter is typed."""
        if self.query:
            return []
        listed = {}
        for row in self.rows:
            listed.setdefault((row.model, row.provider), row)
        return [listed[pair] for pair in self.recent if pair in listed]

    def visible(self) -> list[ModelRow]:
        """The rows Enter can pick, in order: the recent ones, then every row; with a filter, the rows it keeps."""
        needle = self.query.casefold()
        if not needle:
            return [*self.recent_rows(), *self.rows]
        return [row for row in self.rows if needle in f"{row.model}\n{row.provider}\n{row.provider_name}".casefold()]

    def handle_key(self, event: Key | Paste) -> ModelAction | None:
        """Apply one key; a `ModelAction` when the person picked a model or closed the picker."""
        if isinstance(event, Paste):
            self._filter(self.query + event.text.split("\n", 1)[0])
            return None
        if event.name == ESCAPE or (event.name == CHAR and event.ctrl and event.char == "c"):
            return ModelAction(CLOSE)
        shown = self.visible()
        if event.name == ENTER:
            return ModelAction(PICK, shown[min(self.index, len(shown) - 1)]) if shown else None
        steps = {UP: -1, DOWN: 1, PAGE_UP: -self.page, PAGE_DOWN: self.page}
        arc = list_nav_step(event)
        if arc and shown:
            self.index = min(max(self.index + arc, 0), len(shown) - 1)
        elif event.name in steps and shown:
            self.index = min(max(self.index + steps[event.name], 0), len(shown) - 1)
        elif event.name == BACKSPACE:
            self._filter(self.query[:-1])
        elif event.name == CHAR and not event.ctrl and not event.alt:
            self._filter(self.query + event.char)
        return None

    def _filter(self, query: str) -> None:
        self.query = query
        self.index = 0

    def lines(self, width: int, theme: Theme, max_rows: int) -> list[Line]:
        """A header row naming the current model, and the highlight's place once the rows scroll, the filtered
        rows scrolled so the highlighted one shows (the recent ones first, under their heading), the filter row."""
        shown = self.visible()
        self.index = min(self.index, max(len(shown) - 1, 0))
        recent = len(self.recent_rows())
        entries: list[ModelRow | str] = (
            [RECENT_GROUP, *shown[:recent], ALL_GROUP, *shown[recent:]] if recent else list(shown)
        )
        highlighted = self.index + (0 if not recent else 1 if self.index < recent else 2)
        scrolls = max_rows > 2 and len(shown) > max_rows - 2  # the header and the filter row take two
        if self.loading:
            title = TITLE_LOADING
        elif scrolls:
            title = TITLE_AT.format(at=self.index + 1, count=len(shown))
        else:
            title = TITLE.format(count=len(self.rows))
        head = (
            Span(title, theme.heading),
            Span(f"  now {self.current}" if self.current else "", theme.text),
        )
        frame = picker_frame(
            head, len(entries), highlighted,
            lambda number: self._entry(entries[number], number == highlighted, width, theme),
            LOADING if self.loading else " no model matches the filter; /model <name> --provider <slug> names any",
            self.query, width, theme, max_rows,
            lambda number: isinstance(entries[number], str),
        )
        self.page, self.caret = frame.page, frame.caret
        return frame.lines

    def _entry(self, entry: ModelRow | str, highlighted: bool, width: int, theme: Theme) -> Line:
        """A group's heading, muted where the model names start, or a model's row."""
        if isinstance(entry, str):
            inset = cell_width(CHOICE_MARK) + cell_width(f"{CURRENT_MARK} ")
            return (Span(" " * inset, theme.muted), Span(entry, theme.muted))
        return self._row(entry, highlighted, width, theme)

    def _row(self, row: ModelRow, highlighted: bool, width: int, theme: Theme) -> Line:
        return picker_row(highlighted, f"{CURRENT_MARK if row.current else ' '} ", row.model, row.provider_name, width,
                          theme)

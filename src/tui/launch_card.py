"""The launch card: the session, the skills and the first keys, under the logo until the first prompt is sent.

What it says comes from the session as it arrives, so it is drawn in the live
region and grows as the answers come in: the model and effort (`session.info`),
the new session's id, the last stored session (`session.list`) and the skills
Hermes has (`session.info`'s `skills`, category to names, which Hermes' own
session panel lists). Hermes files every skill OMH installs under one category,
since they sit straight under their skills directory, so the card regroups them
by OMH's capability family (the generated `capability_families.json`) and puts
the ulw lanes on a row of their own; Hermes' own skills are named by category on
one row.

Hermes sends the skills only once it has built the session's agent, a second or
two after the first frame, so the card draws the skills the last launch drew
(`read_snapshot`, kept under the OMH home by `write_snapshot`) marked last-known
until then, and the session's own replace them whole. The snapshot holds the
names as drawn, so the first frame imports no skill catalog, and it names the
Hermes home and profile it was drawn for. A first launch, another Hermes home
or profile, or a snapshot this module did not write says loading… instead.

Each launch look (`theme.LAUNCH_PRESETS`) has one of four layouts: a box per
section (spectrum, aurora), one box of stacked sections (violet, sakura), one box
in two columns (gold, ember) or a rule above and below with no side edges
(graphite, moonlit). Every layout is fitted
to the rows it is given (`launch_card`): two rows of names per family, then one,
then rows dropped from the last family up, then the last session, then the
keys; the last form is the last session's one row, so a short terminal still
says where the last session is.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from importlib import resources
import json
from pathlib import Path

from ..system.local_store import atomic_write_json

from .style import Line, Span
from .theme import LaunchStyles, Theme
from .width import cell_width, line_width, truncate, truncate_line

OMH_PREFIX = "omh-"
ULW_PREFIX = "ulw-"
GRAPH_LANE = "dag-ulw"
# OMH's capability families (the sidecar's ids) under the short label the card's gutter shows, in the card's order.
# Where every skill is listed in the OMH TUI: the completion menu `/` opens (Hermes' `/skills` is its terminal's).
FIND_HINT = "type / to find one"
FAMILIES = (
    ("plan_and_decide", "plan"),
    ("delegate_coding_and_ship", "ship"),
    ("operate_and_observe", "operate"),
    ("learn_and_gather", "learn"),
    ("create_materials_and_visuals", "create"),
    ("retain_knowledge", "retain"),
)
LAYOUTS = {"spectrum": "tiles", "violet": "stack", "gold": "split", "graphite": "rules", "sakura": "stack",
           "moonlit": "rules", "aurora": "tiles", "ember": "split"}
GUTTER = 9  # a family's label column
COLUMN = 26  # the narrowest column a name gets; a longer name spans two
# What the card offers to type, in this order; the first is OMH's own lane.
KEYS = (("/dag-ulw", "run a goal as a graph of subagents"), ("/resume", "reopen a stored session"),
        ("/theme", "switch the launch look"), ("?", "every shortcut"))
LOADING = "loading…"
LAST_KNOWN = "last-known"  # the skills drawn are the last launch's, until this session's arrive
SNAPSHOT_SCHEMA = "omh.tui.launch-skills/v1"


@dataclass(frozen=True)
class Facts:
    model: str
    effort: str
    session: str  # the new session's stored id
    last_title: str = ""
    last_id: str = ""
    last_count: int = 0


@dataclass(frozen=True)
class Paint:
    theme: Theme
    look: LaunchStyles


@dataclass(frozen=True)
class Skills:
    groups: tuple[tuple[str, tuple[str, ...]], ...]  # (label, names) per OMH row, in the card's order
    omh: int
    hermes_categories: tuple[str, ...]
    hermes: int
    last_known: bool = False  # read from the last launch's snapshot, not from this session


@lru_cache(maxsize=1)
def family_members() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """(label, installed skill names) per family, from the generated sidecar, read once."""
    from ..skills.catalog_types import omh_skill_display_name  # only once skills arrive, never on the import path

    try:
        sidecar = resources.files("omh.plugin_bundle.omh.tools").joinpath("capability_families.json")
        loaded = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError, ImportError):
        return ()  # no families to group by: OMH's skills all go on the `other` row
    entries = {entry.get("id"): entry for entry in loaded if isinstance(entry, dict)} if isinstance(loaded, list) else {}
    rows = []
    for family, label in FAMILIES:
        workflows = entries.get(family, {}).get("primary_workflows", [])
        rows.append((label, tuple(omh_skill_display_name(name) for name in workflows if isinstance(name, str))))
    return tuple(rows)


def is_omh_name(name: str) -> bool:
    return name.startswith((OMH_PREFIX, ULW_PREFIX)) or name == GRAPH_LANE


def skill_rows(skills: Mapping[str, Sequence[str]], members=family_members) -> Skills:
    """Hermes' skills regrouped: OMH's by family (the ulw lanes first, on their own row, the graph lane leading
    them; one OMH ships in no family under `other`), and Hermes' own counted with their categories."""
    installed = [name for names in skills.values() for name in names if isinstance(name, str)]
    have = set(installed)
    placed: set[str] = set()
    ulw: list[str] = []
    rows: list[tuple[str, tuple[str, ...]]] = []
    for label, names in members():
        kept = []
        for name in names:
            if name in have and name not in placed:
                placed.add(name)
                (ulw if name == GRAPH_LANE or name.startswith(ULW_PREFIX) else kept).append(name)
        rows.append((label, tuple(kept)))
    ulw.sort(key=lambda name: name != GRAPH_LANE)
    other = tuple(dict.fromkeys(name for name in installed if is_omh_name(name) and name not in placed))
    groups = tuple((label, names) for label, names in (("ulw", tuple(ulw)), *rows, ("other", other)) if names)
    omh = placed | set(other)
    categories = tuple(sorted(category for category, names in skills.items()
                              if any(isinstance(name, str) and name not in omh for name in names)))
    return Skills(groups, len(omh), categories, len([name for name in installed if name not in omh]))


def snapshot_path(omh_home: Path) -> Path:
    return Path(omh_home) / "tui" / "launch-skills.json"


def _names(value: object) -> tuple[str, ...] | None:
    return tuple(value) if isinstance(value, list) and all(isinstance(name, str) for name in value) else None


def _count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def read_snapshot(omh_home: Path, hermes_home: str, profile: str) -> Skills | None:
    """The skills the last launch drew for this Hermes home and profile, marked last-known; None when there are
    none this module wrote for them."""
    try:
        record = json.loads(snapshot_path(omh_home).read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    if (not isinstance(record, dict) or record.get("schema_version") != SNAPSHOT_SCHEMA
            or record.get("hermes_home") != hermes_home or record.get("profile") != profile):
        return None
    rows = record.get("groups")
    groups = []
    for row in rows if isinstance(rows, list) else [None]:
        names = _names(row[1]) if isinstance(row, list) and len(row) == 2 and isinstance(row[0], str) else None
        if names is None:
            return None
        groups.append((row[0], names))
    categories = _names(record.get("hermes_categories"))
    omh, hermes = _count(record.get("omh")), _count(record.get("hermes"))
    if categories is None or omh is None or hermes is None:
        return None
    return Skills(tuple(groups), omh, categories, hermes, last_known=True)


def write_snapshot(omh_home: Path, hermes_home: str, profile: str, skills: Skills) -> None:
    """Keep `skills` for the next launch's first frame on this Hermes home and profile, atomically; a failed write
    costs that frame only."""
    record = {"schema_version": SNAPSHOT_SCHEMA, "hermes_home": hermes_home, "profile": profile,
              "groups": [[label, list(names)] for label, names in skills.groups],
              "omh": skills.omh, "hermes_categories": list(skills.hermes_categories), "hermes": skills.hermes}
    try:
        atomic_write_json(snapshot_path(omh_home), record)
    except OSError:
        pass


# --- rows ------------------------------------------------------------------------------------------------------


def _pad(line: Line, width: int) -> Line:
    line = truncate_line(line, width)
    gap = width - line_width(line)
    return (*line, Span(" " * gap)) if gap > 0 else line


def _name(name: str, cells: int, theme: Theme) -> Line:
    shown = truncate(name, cells)
    if shown.startswith(OMH_PREFIX):  # the namespace dim, so the eye reads the rest; the whole name is what is typed
        return (Span(OMH_PREFIX, theme.faint), Span(shown[len(OMH_PREFIX):], theme.text))
    return (Span(shown, theme.text),)


def grid(groups: Sequence[tuple[str, Sequence[str]]], width: int, per_group: int, p: Paint) -> list[Line]:
    """A row (or `per_group` rows) per group: its label in the gutter, then its names in equal columns.

    A name wider than a column spans as many as it needs, so each is shown
    whole and the columns still line up; a group with more names than its
    rows hold ends them with "+N more" in the next free column. Narrower
    than a few cells past the gutter there is no column, and no rows.
    """
    if width - GUTTER < 3:
        return []
    columns = max((width - GUTTER) // COLUMN, 1)
    cell = (width - GUTTER) // columns
    out: list[Line] = []
    for label, names in groups:
        rows: list[list[Span]] = [[]]
        used = 0
        left = list(names)
        while left:
            span = min(-(-(cell_width(left[0]) + 2) // cell), columns)
            last = len(rows) == per_group
            keep = 1 if last and len(left) > 1 else 0  # a column for "+N more"
            if used + span + keep > columns:
                if last:
                    break
                rows.append([])
                used = 0
                continue
            rows[-1] += _pad(_name(left.pop(0), span * cell - 2, p.theme), span * cell)
            used += span
        if left:
            rows[-1].append(Span(f"+{len(left)} more", p.theme.faint))
        for number, row in enumerate(rows):
            out.append(_pad((Span((label if number == 0 else "").ljust(GUTTER), p.look.label), *row), width))
    return out


def model_spans(f: Facts, p: Paint) -> Line:
    effort = f"effort {f.effort}" if f.effort else "ctrl+t effort"
    model = f.model.rsplit("/", 1)[-1]  # as Hermes' own panel names it: the last path segment
    spans = [Span(model or "no model yet", replace(p.theme.text, bold=True)), Span(" · ", p.theme.dim),
             Span(effort, p.theme.muted)]
    if f.session:
        spans += [Span(" · ", p.theme.dim), Span("new session ", p.theme.muted), Span(f.session, p.theme.faint)]
    return tuple(spans)


def skills_header(s: Skills | None, p: Paint) -> Line:
    if s is None:
        return (Span("skills", p.look.label), Span(f"  {LOADING}", p.theme.muted))
    return (Span("skills", p.look.label), Span(f"  {s.omh + s.hermes} installed", p.theme.text), *known(s, p),
            Span(" · ", p.theme.dim), Span(f"{s.omh} from OMH", p.theme.muted), Span(" · ", p.theme.dim),
            Span(f"{s.hermes} from Hermes", p.theme.muted), Span(" · ", p.theme.dim), *find_hint(p))


def known(s: Skills | None, p: Paint) -> Line:
    """The last-known mark after a count read from the snapshot; () once the session's own are drawn."""
    return (Span(" · ", p.theme.dim), Span(LAST_KNOWN, p.theme.faint)) if s is not None and s.last_known else ()


def find_hint(p: Paint) -> Line:
    return (Span("type ", p.theme.muted), Span("/", p.theme.user), Span(FIND_HINT.removeprefix("type /"), p.theme.muted))


def hermes_rows(s: Skills, width: int, p: Paint) -> list[Line]:
    return grid([("hermes", s.hermes_categories)], width, 1, p) if s.hermes_categories else []


def keys_line(p: Paint, width: int, gap: str = "   ") -> Line:
    """The keys, as many whole ones as fit `width`."""
    spans: list[Span] = []
    for index, (key, words) in enumerate(KEYS):
        entry = ([Span(gap)] if index else []) + [Span(key, p.theme.slash if key.startswith("/") else p.theme.user),
                                                  Span(" " + words, p.theme.muted)]
        if line_width((*spans, *entry)) > width:
            break
        spans += entry
    return tuple(spans)


def key_rows(p: Paint) -> list[Line]:
    return [(Span(key.ljust(10), p.theme.slash if key.startswith("/") else p.theme.user), Span(words, p.theme.muted))
            for key, words in KEYS]


def last_line(f: Facts, p: Paint, width: int, label: str = "last  ") -> Line:
    """The last session, its title cut to what the rest of the row leaves; () when there is none."""
    if not f.last_id:
        return ()
    head = (Span(label, p.look.label),) if label else ()
    tail = (Span(" · ", p.theme.dim), Span(f"{f.last_count} messages", p.theme.muted), Span(" · ", p.theme.dim),
            Span("/resume ", p.theme.slash), Span(f.last_id, p.theme.muted))
    if width - line_width(head) - line_width(tail) < 12:
        tail = tail[3:]  # the count goes before the title gets too short
    room = max(width - line_width(head) - line_width(tail), 1)
    return truncate_line((*head, Span(truncate(f.last_title, room), p.theme.text), *tail), width)


# --- frames ----------------------------------------------------------------------------------------------------


def boxed(title: Line, right: Line, body: Sequence[Line], width: int, p: Paint, pad: int = 2) -> list[Line]:
    """`body` in a rounded box `width` wide: `title` set into the top edge on the left, `right` on the right."""
    edge = p.look.edge
    inner = width - 2 - 2 * pad
    title = truncate_line(title, max(width - 6, 1))
    right = right if right and line_width(title) + line_width(right) + 8 <= width else ()
    fill = width - 2 - 3 - line_width(title) - (line_width(right) + 3 if right else 1)
    top: Line = (Span("╭─ ", edge), *title, Span(" " + "─" * max(fill, 0), edge),
                 *((Span(" ", edge), *right, Span(" ─╮", edge)) if right else (Span("╮", edge),)))
    rows = [(Span("│" + " " * pad, edge), *_pad(line, inner), Span(" " * pad + "│", edge)) for line in body]
    return [top, *rows, (Span("╰" + "─" * (width - 2) + "╯", edge),)]


def ruled(title: Line, body: Sequence[Line], foot: Line, width: int, p: Paint) -> list[Line]:
    """`body` between a rule above (`title` on its left) and a rule below (`foot` on its right); no side edges."""
    edge = p.look.edge

    def rule(left: Line, end: Line) -> Line:
        lead = (Span("── ", edge), *left, Span(" ", edge)) if left else ()
        tail = (Span(" ", edge), *end, Span(" ──", edge)) if end else ()
        return (*lead, Span("─" * max(width - line_width(lead) - line_width(tail), 0), edge), *tail)

    return [rule(truncate_line(title, max(width - 8, 1)), ()), *[_pad((Span("  "), *line), width) for line in body],
            rule((), truncate_line(foot, max(width - 8, 1)))]


# --- layouts: each takes (rows per family, how much to drop) and returns the card's lines ------------------------

Build = Callable[[int, int], list[Line]]


def _kept(s: Skills | None, drop: int) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return s.groups[: max(len(s.groups) - drop, 2)] if s is not None else ()


def _skills_body(s: Skills | None, width: int, per_group: int, drop: int, p: Paint) -> list[Line]:
    if s is None:
        return []
    rows = grid(_kept(s, drop), width, per_group, p)
    return rows + (hermes_rows(s, width, p) if drop == 0 else [])


def _tiles(f: Facts, s: Skills | None, p: Paint, width: int) -> Build:
    def build(per_group: int, drop: int) -> list[Line]:
        half = (width - 1) // 2
        session = [model_spans(f, p)[:3], model_spans(f, p)[4:]]
        if f.last_id and drop < 6:
            session += [(Span("last ", p.theme.muted), Span(truncate(f.last_title, max(half - 11, 1)), p.theme.text)),
                        (Span("/resume ", p.theme.slash), Span(f.last_id, p.theme.muted))]
        start = key_rows(p) if drop < 7 else []
        tall = max(len(session), len(start))
        session += [()] * (tall - len(session))
        start += [()] * (tall - len(start))
        left = boxed((Span("session", p.look.label),), (), session, half, p)
        top = ([(*l, Span(" "), *r) for l, r in zip(left, boxed((Span("start here", p.look.label),), (), start,
                                                                 width - half - 1, p), strict=True)]
               if start else left)
        title = (Span("skills", p.look.label),
                 Span(f" {s.omh + s.hermes} installed" if s is not None else f" {LOADING}", p.theme.muted),
                 *known(s, p))
        right = find_hint(p) if s is not None else ()
        return [*top, *boxed(title, right, _skills_body(s, width - 6, per_group, drop, p) or [()], width, p)]
    return build


def _stack(f: Facts, s: Skills | None, p: Paint, width: int) -> Build:
    def build(per_group: int, drop: int) -> list[Line]:
        inner = width - 6
        body = [(), skills_header(s, p), *_skills_body(s, inner, per_group, drop, p)]
        if f.last_id and drop < 6:
            body += [(), last_line(f, p, inner)]
        if drop < 7:
            body += [(), keys_line(p, inner)]
        return boxed(model_spans(f, p), (), [*body, ()], width, p)
    return build


def _split(f: Facts, s: Skills | None, p: Paint, width: int) -> Build:
    def build(per_group: int, drop: int) -> list[Line]:
        left_w = min(44, max(width // 3, 24))
        right_w = width - 6 - left_w - 5
        left: list[Line] = []
        if f.last_id and drop < 6:
            left += [(Span("last session", p.look.label),), (Span(truncate(f.last_title, left_w), p.theme.text),),
                     (Span("/resume ", p.theme.slash), Span(f.last_id, p.theme.muted)), ()]
        if drop < 7:
            left += key_rows(p)
        right = [skills_header(s, p)[:2] + known(s, p) + ((Span(" · ", p.theme.dim), *find_hint(p))
                                                         if s is not None else ()), ()]
        right += _skills_body(s, right_w, per_group, drop, p)
        tall = max(len(left), len(right))
        left += [()] * (tall - len(left))
        right += [()] * (tall - len(right))
        body = [(), *[(*_pad(l, left_w), Span("  "), Span("│", p.look.edge), Span("  "), *r)
                      for l, r in zip(left, right, strict=True)], ()]
        return boxed(model_spans(f, p), (), body, width, p)
    return build


def _rules(f: Facts, s: Skills | None, p: Paint, width: int) -> Build:
    def build(per_group: int, drop: int) -> list[Line]:
        inner = width - 2
        body: list[Line] = [()]
        if f.last_id and drop < 6:
            body += [last_line(f, p, inner, label="last".ljust(GUTTER)), ()]
        body += _skills_body(s, inner, per_group, drop, p) or [skills_header(s, p)]
        if drop < 7:
            body += [(), (Span("keys".ljust(GUTTER), p.look.label), *keys_line(p, inner - GUTTER))]
        foot: Line = (Span(f"skills {LOADING}", p.theme.muted),)
        if s is not None:
            count = Span(f"{s.omh + s.hermes} skills", p.theme.muted)
            foot = (count, *known(s, p), Span(" · ", p.theme.dim), *find_hint(p))
            if line_width(foot) > width - 8:  # a narrow foot drops the mark first, so the hint stays whole
                foot = (count, Span(" · ", p.theme.dim), *find_hint(p))
        return ruled(model_spans(f, p), [*body, ()], foot, width, p)
    return build


FORMS = ((2, 0), (1, 0), (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7))  # (rows per family, drop)


def launch_card(preset: str, f: Facts, p: Paint, width: int, room: int, skills: Skills | None = None) -> list[Line]:
    """The card for launch look `preset`, `width` wide, in the fullest form that fits `room` rows.

    Past every boxed form, the last session's one row (when there is a last
    session and a row); [] when not even that fits.
    """
    if room <= 0 or width < 40:
        return [last_line(f, p, width)] if room > 0 and f.last_id else []
    layout = {"tiles": _tiles, "stack": _stack, "split": _split, "rules": _rules}[LAYOUTS.get(preset, "tiles")]
    build = layout(f, skills, p, width)
    for per_group, drop in FORMS:
        lines = build(per_group, drop)
        if len(lines) <= room:
            return lines
    return [last_line(f, p, width)] if f.last_id else []


def preview(preset: str, f: Facts, p: Paint, wordmark: Line, width: int, skills: Skills | None = None) -> list[Line]:
    """A look in four rows, for the /theme picker when the launch is no longer on screen: the wordmark in the logo's
    colours, then the card's frame in the look's layout around the model and the skills' count."""
    title = model_spans(f, p)[:3]
    body = [skills_header(skills, p)]
    frame = ruled(title, body, (), width, p) if LAYOUTS.get(preset) == "rules" else boxed(title, (), body, width, p)
    return [truncate_line(wordmark, width), *frame]

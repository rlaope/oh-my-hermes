"""What's new: a few lines on what changed in this version of OMH, said once after an update.

`WHATS_NEW` is written by hand in each release's prep PR, from that version's
`CHANGELOG.md` section: three to five of the changes a person sees, one line
each. `tests/test_tui_whats_new.py` fails when the package's own version has no
entry, so a release cannot ship without one.

The last version whose What's new this OMH home has seen is kept in
`<omh_home>/tui/whats-new.json`. A fresh session's launch shows the block under
the launch card when the running version differs from the recorded one, and
records the running one once the block is drawn, so it shows once. A home with
no record that has run the OMH TUI before (`EARLIER_TUI_STATE`: an install from
before this record existed) is shown the block too (owner, 2026-11-02); one
with no TUI state at all is a new install, which records the version and shows
nothing. `/whats-new` shows the block whenever it is asked for.
"""

from __future__ import annotations

from pathlib import Path

from ..system.local_store import atomic_write_json, read_json_object_result
from .style import Line, Span
from .theme import Theme
from .width import truncate_line

SHOWN_SCHEMA = "omh_tui_whats_new/v1"
HEADING = "What's new in v{version}"
BULLET = "  · "
SHORT_HINT = " · /whats-new lists it"
# What an OMH TUI that ran before writes under the OMH home, relative to it: the launch card's skills, written by
# every launch that names a Hermes profile, and by nothing but the TUI. Not `setup-profile.json`, which `omh setup`
# writes before a new install's first launch, nor `tui/theme.json`, which `omh theme` writes from the shell.
EARLIER_TUI_STATE = ("tui/launch-skills.json",)

WHATS_NEW: dict[str, tuple[str, ...]] = {
    "4.0.5": (
        "A part of the screen that fails to draw no longer ends the session",
        "A slow or busy Hermes gateway no longer drops the running turn",
        "Pastes over SSH and WSL land in the composer as one paste",
        "omh memory recall-line and recall-mode: where recall shows, or off",
        "The info line says when a newer OMH is out",
    ),
    "4.0.4": (
        "Vim mode in the composer: turn on Hermes' display.vim_mode",
        "Kanagawa Wave: a theme (omh theme use kanagawa) and a launch look",
        "A steer sent during a turn shows as a prompt row",
        "On Windows, OMH opens the Hermes home Hermes itself uses",
        "Named identities: a prompt and a model chain you pick per request",
    ),
}


def shown_path(omh_home: Path) -> Path:
    """Where the version last shown is kept: under the OMH home, beside the TUI's other choices."""
    return Path(omh_home) / "tui" / "whats-new.json"


def read_shown(omh_home: Path) -> str | None:
    """The version whose What's new this home last recorded; None when nothing this module wrote is there."""
    record, _error = read_json_object_result(shown_path(omh_home))
    if record is None or record.get("schema_version") != SHOWN_SCHEMA:
        return None
    version = record.get("version")
    return version if isinstance(version, str) else None


def is_due(omh_home: Path, version: str) -> bool:
    """Whether this launch shows `version`'s What's new: `version` has an entry and is not the recorded one, and the
    home either recorded another version or, recording none, has run the OMH TUI before. Writes nothing."""
    shown = read_shown(omh_home)
    if shown == version or not WHATS_NEW.get(version):
        return False
    return shown is not None or any((Path(omh_home) / name).exists() for name in EARLIER_TUI_STATE)


def record_shown(omh_home: Path, version: str) -> bool:
    """Record `version` as said; whether it was written (a home that cannot be written says it again next time)."""
    try:
        atomic_write_json(shown_path(omh_home), {"schema_version": SHOWN_SCHEMA, "version": version})
    except OSError:
        return False
    return True


def whats_new_text(version: str) -> str:
    """The block as plain text, for `/whats-new`; "" when `version` has no entry."""
    items = WHATS_NEW.get(version, ())
    return "\n".join([HEADING.format(version=version), *(BULLET.lstrip() + item for item in items)]) if items else ""


def whats_new_forms(version: str, theme: Theme, width: int) -> list[list[Line]]:
    """The block as drawn under the launch card, longest first, each row cut to `width`: the heading and its items,
    then the heading alone with the command that lists them (for a card that leaves fewer rows); [] when `version`
    has no entry."""
    items = WHATS_NEW.get(version, ())
    if not items:
        return []
    heading = Span(HEADING.format(version=version), theme.heading)
    whole: list[Line] = [(heading,), *((Span(BULLET, theme.dim), Span(item, theme.text)) for item in items)]
    short: list[Line] = [(heading, Span(SHORT_HINT, theme.hint))]
    return [[truncate_line(row, width) for row in form] for form in (whole, short)]

"""Scheduling for memory consolidation -- the deterministic half of "dreaming".

Letta surfaces sleep-time compute as dreaming: background subagents that review
recent turns, consolidate what was learned, and rewrite memory without blocking
the foreground session. The consolidation is model work. The *trigger* is not --
it fires after a configured number of user messages, or on a context-compaction
event.

That split is the whole reason this file exists. OMH makes no model call, so it
cannot dream. It can decide precisely when dreaming is due, on what evidence,
and hand Hermes a prepared brief -- and Hermes already runs the consolidation
loop itself (``agent/background_review.py`` forks after each turn with the
memory and skill tools). The gap this closes is that the loop runs with no
statement of what is duplicated, expiring, or out of room. It supplies that.

Counting turns is deliberate and unglamorous. The sleep-time compute paper is
explicit that the technique pays off in proportion to how predictable the next
query is, so a scheduler that fires on a fixed interval should not be sold as
one that fires when consolidation would help most.

The counters and the brief belong to one Hermes profile, not to the OMH home.
Several profiles may name one home -- a multiplexed gateway's profiles can all
bind ``~/.omh`` -- and a brief raised by one profile's turns and its own
MEMORY.md is not another profile's to serve. So both files live under
``memory/profiles/<slot>/``, the slot being `profile_slot` of the profile's
Hermes home, the key the group-activity status already uses (#2087).

Stdlib only; vendored in the bundle because it is imported inside the Hermes
process, where the ``omh`` package does not exist.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from . import runtime_paths
from .group_activity_status import profile_slot
from .memory_state_files import state_file_lock, write_text_atomic, write_text_locked
from .memory_store_io import guard_store_write

DREAMING_STATE_SCHEMA_VERSION = "omh_memory_dreaming_state/v1"
DREAMING_HANDOFF_SCHEMA_VERSION = "omh_memory_consolidation_handoff/v1"

# Letta's server-side sleeptime default is every 5 steps; matched so the cadence
# has a stated origin rather than being picked here.
DEFAULT_TURN_INTERVAL = 5

# Free characters below which the memory file is treated as under pressure,
# whatever the turn count says. A full file is the failure this is meant to
# reach before it happens, not after.
DEFAULT_HEADROOM_FLOOR_CHARS = 300
_FLOOR_REFERENCE_CAP_CHARS = 2200  # MEMORY.md's default cap, where the floor is exactly the default


def headroom_floor_for_cap(cap: int) -> int:
    """The headroom floor for one file: proportional to its cap, never above the default.

    A flat floor is wrong for a smaller file: a cap at or below it would be
    below its floor while empty, and USER.md's 1375 would warn at 22% of the
    cap against MEMORY.md's 14%. MEMORY.md at its default 2200 keeps 300.
    """
    return min(DEFAULT_HEADROOM_FLOOR_CHARS, max(cap, 0) * DEFAULT_HEADROOM_FLOOR_CHARS // _FLOOR_REFERENCE_CAP_CHARS)

# Modes. There is no auto-launch: OMH cannot start Hermes' consolidation, so
# offering the word would claim a capability the wrapper does not have.
DREAMING_MODES = ("off", "reminder")
DEFAULT_DREAMING_MODE = "reminder"
# The profile setting that chooses one: `plugins.entries.omh.settings.dreaming_mode`.
DREAMING_MODE_SETTING = "dreaming_mode"
# `off` written bare is a YAML false, and `hermes config set ... off` stores
# it as `false`; the false spellings all mean the profile chose `off`.
_OFF_SETTING_SPELLINGS = frozenset({"off", "false", "no"})
# A setting written but not read as a mode: a value outside the spellings
# above and the modes, or a config.yaml the scan could not read. The default
# applies either way; this names it so `omh memory dream` and the doctor
# advisory can say so instead of reporting `reminder` as if it were chosen.
MODE_SETTING_UNRECOGNIZED = "mode_setting_unrecognized"
# Enough of an unrecognized value to recognize the typo, never more of the file.
_RAW_SETTING_DISPLAY_CHARS = 64
# Where an earlier release kept one set for the whole home, under `memory/`.
LEGACY_STATE_FILENAMES = ("dreaming.json", "consolidation.json")

# Reasons that describe a moment rather than a state. These clear themselves by
# firing -- the turn counter resets, the compaction flag is lowered -- so they
# may fire again the moment they recur. Everything not listed here is a standing
# condition: it stays true until something outside OMH changes it, so repeating
# it every turn says nothing the previous brief did not.
_EVENT_REASONS = frozenset(
    {
        "turn_interval_reached",
        "session_ending_with_unconsolidated_turns",
        "context_compaction_observed",
    }
)


def profile_states_dir(omh_home: str | Path) -> Path:
    """The directory every profile's counters and brief sit under in one OMH home."""
    return Path(omh_home).expanduser() / "memory" / "profiles"


def profile_dreaming_dir(omh_home: str | Path, hermes_home: str | Path) -> Path:
    """One profile's directory: ``<omh_home>/memory/profiles/<profile_slot(hermes_home)>``."""
    return profile_states_dir(omh_home) / profile_slot(Path(hermes_home))


def dreaming_state_path(omh_home: str | Path, hermes_home: str | Path) -> Path:
    return profile_dreaming_dir(omh_home, hermes_home) / "dreaming.json"


def read_dreaming_mode_setting(hermes_home: str | Path) -> dict[str, object]:
    """What this profile's `dreaming_mode` setting says, and the mode in force.

    Read from the profile's own ``config.yaml`` at
    ``plugins.entries.omh.settings.dreaming_mode``, the per-profile plugin
    setting Hermes keeps beside ``omh_home``: each profile of a multiplexed
    host has its own file, so profiles sharing one store can choose
    differently, and nobody edits a managed file to choose. The text scan is
    the one the standalone lane reads ``omh_home`` with, keyed by the Hermes
    home the caller is bound to rather than whichever profile the process
    has in scope; the managed overlay is not consulted.

    Returns ``{"mode", "raw", "recognized"}``. ``raw`` is the value as
    written, bounded and printable only, or None when nothing was written or
    the file could not be read. Anything not read as a mode falls back to the
    default -- a setting this reader cannot see must not turn dreaming off,
    and must not raise into the turn that asked -- but is not ``recognized``,
    and carries ``issue`` (`MODE_SETTING_UNRECOGNIZED`) with ``reason``
    ``unknown_value`` or ``config_unreadable``. No config.yaml at all is an
    unset setting, which is recognized: the default is what nobody chose.
    """
    try:
        text = (Path(hermes_home).expanduser() / "config.yaml").read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"mode": DEFAULT_DREAMING_MODE, "raw": None, "recognized": True}
    except (OSError, ValueError):
        return _unrecognized_mode_setting(None, "config_unreadable")
    try:
        value = runtime_paths.plugin_setting_text(text, DREAMING_MODE_SETTING)
    except runtime_paths.RuntimeBindingError:
        return _unrecognized_mode_setting(None, "config_unreadable")
    if value is None:
        return {"mode": DEFAULT_DREAMING_MODE, "raw": None, "recognized": True}
    raw = "".join(character for character in value if character.isprintable())[:_RAW_SETTING_DISPLAY_CHARS]
    spelled = value.strip().lower()
    if spelled in _OFF_SETTING_SPELLINGS:
        return {"mode": "off", "raw": raw, "recognized": True}
    if spelled in DREAMING_MODES:
        return {"mode": spelled, "raw": raw, "recognized": True}
    return _unrecognized_mode_setting(raw, "unknown_value")


def _unrecognized_mode_setting(raw: str | None, reason: str) -> dict[str, object]:
    return {
        "mode": DEFAULT_DREAMING_MODE,
        "raw": raw,
        "recognized": False,
        "issue": MODE_SETTING_UNRECOGNIZED,
        "reason": reason,
    }


def configured_dreaming_mode(hermes_home: str | Path) -> str:
    """The mode in force for this profile (`read_dreaming_mode_setting`).

    Read fresh on each call, so a change applies from the next evaluation;
    a caller that needs the mode twice in one render or evaluation reads it
    once and passes it down.
    """
    return str(read_dreaming_mode_setting(hermes_home)["mode"])


def adopt_legacy_dreaming_files(omh_home: str | Path, hermes_home: str | Path) -> list[str]:
    """Move the home-wide counters and brief an earlier release wrote into this profile's directory.

    Before #2087 every profile on a home read and wrote ``memory/dreaming.json``
    and ``memory/consolidation.json``, and neither records which profile
    raised it. The provider claims them only for a profile that is not
    routed (`runtime_paths.profile_is_routed`): a process serving its launch
    profile alone. On a single-profile host they are that profile's own;
    where separate processes for different profiles share one store, the
    first to start claims them. A routed profile leaves them where they are
    and never reads them. A file the profile already has is never replaced,
    and the old file is moved, not copied, so it is claimed once. Returns the
    names moved. Raises ``OSError``.

    One lock on the old location covers the whole claim. Locking each target
    alone let two profiles claim at once: in a two-thread probe most losers
    raised ``FileNotFoundError`` on a file the winner had already moved, and
    some runs split the counters and the brief between the two profiles.
    """
    memory_dir = Path(omh_home).expanduser() / "memory"
    legacy_files = [memory_dir / name for name in LEGACY_STATE_FILENAMES]
    if not any(path.is_file() and not path.is_symlink() for path in legacy_files):
        return []
    target_dir = profile_dreaming_dir(omh_home, hermes_home)
    # The lock sidecar and the moved files stay inside the store: a linked
    # directory or target on the way is refused (OSError), never followed.
    guard_store_write(memory_dir / "consolidation.json", omh_home=Path(omh_home).expanduser())
    for name in LEGACY_STATE_FILENAMES:
        guard_store_write(target_dir / name, omh_home=Path(omh_home).expanduser())
    moved: list[str] = []
    with state_file_lock(memory_dir / "consolidation.json"):
        for legacy in legacy_files:
            if legacy.is_symlink() or not legacy.is_file():
                continue
            target = target_dir / legacy.name
            # The target's own lock as well: this profile's writers take only that one.
            with state_file_lock(target):
                if target.exists():
                    continue
                try:
                    os.replace(legacy, target)
                except FileNotFoundError:
                    # Claimed by a writer outside this lock; nothing left to move.
                    continue
            moved.append(legacy.name)
    return moved


def empty_dreaming_state() -> dict[str, object]:
    return {
        "schema_version": DREAMING_STATE_SCHEMA_VERSION,
        "turns_since_consolidation": 0,
        "compaction_pending": False,
        "memory_writes_observed": 0,
        "last_consolidated_at": "",
        "last_reasons": [],
    }


def read_dreaming_state(omh_home: str | Path, hermes_home: str | Path) -> dict[str, object]:
    """This profile's persisted counters, or a fresh state when absent or unusable.

    Never raises. A corrupt counter file must cost at most one missed
    consolidation, not the turn that read it.
    """
    path = dreaming_state_path(omh_home, hermes_home)
    try:
        if path.is_symlink() or not path.is_file():
            return empty_dreaming_state()
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return empty_dreaming_state()
    if not isinstance(data, dict) or data.get("schema_version") != DREAMING_STATE_SCHEMA_VERSION:
        return empty_dreaming_state()
    state = empty_dreaming_state()
    state["turns_since_consolidation"] = _non_negative_int(data.get("turns_since_consolidation"))
    state["compaction_pending"] = bool(data.get("compaction_pending"))
    state["memory_writes_observed"] = _non_negative_int(data.get("memory_writes_observed"))
    state["last_consolidated_at"] = str(data.get("last_consolidated_at", "") or "")
    state["last_reasons"] = [str(item) for item in data.get("last_reasons", []) if isinstance(item, str)]
    return state


def write_dreaming_state(omh_home: str | Path, hermes_home: str | Path, state: dict[str, Any]) -> Path:
    """Replace this profile's counters whole, under the state lock. Raises ``OSError``."""
    path = dreaming_state_path(omh_home, hermes_home)
    guard_store_write(path, omh_home=Path(omh_home).expanduser())
    write_text_locked(path, json.dumps(state, ensure_ascii=False, sort_keys=True))
    return path


def update_dreaming_state(
    omh_home: str | Path,
    hermes_home: str | Path,
    mutate: Callable[[dict[str, Any]], dict[str, Any]],
) -> dict[str, Any]:
    """Read, mutate and replace the counters as one step; returns what was written.

    Two sessions on one home -- a CLI and a gateway -- each used to read the
    counters, add one, and write them back, so the later write erased the
    earlier increment. The read now happens inside the same lock as the
    write. A ``mutate`` that raises leaves the previous file untouched.
    Raises ``OSError`` (a lock timeout is one).
    """
    path = dreaming_state_path(omh_home, hermes_home)
    guard_store_write(path, omh_home=Path(omh_home).expanduser())
    with state_file_lock(path):
        updated = mutate(read_dreaming_state(omh_home, hermes_home))
        write_text_atomic(path, json.dumps(updated, ensure_ascii=False, sort_keys=True))
    return updated


def record_turn(state: dict[str, Any]) -> dict[str, object]:
    """One more user turn since the last consolidation."""
    updated = dict(state)
    updated["turns_since_consolidation"] = _non_negative_int(state.get("turns_since_consolidation")) + 1
    return updated


def record_compaction(state: dict[str, Any]) -> dict[str, object]:
    """Hermes is about to discard messages; consolidation is due next chance."""
    updated = dict(state)
    updated["compaction_pending"] = True
    return updated


def record_memory_write(state: dict[str, Any]) -> dict[str, object]:
    """Hermes wrote its own memory; the two stores may have diverged."""
    updated = dict(state)
    updated["memory_writes_observed"] = _non_negative_int(state.get("memory_writes_observed")) + 1
    return updated


def record_consolidation_observed(state: dict[str, Any]) -> dict[str, object]:
    """A consolidation-shaped write happened; the clock restarts here.

    `turns_since_consolidation` reset only when a BRIEF fired, never when the
    consolidation itself did -- despite the name. Observed live: a session
    whose only work was consolidating memory still ended with turns > 0, so
    `session_ending_with_unconsolidated_turns` raised a fresh brief at the
    exit of the very session that had just consolidated. Every tidy-up ended
    by requesting the next one.

    A replace/remove from Hermes' memory tool is the consolidation the counter
    is named after, so it zeroes the turn count and lowers the compaction
    flag: both describe work waiting to be consolidated, and it just was.
    """
    updated = dict(state)
    updated["turns_since_consolidation"] = 0
    updated["compaction_pending"] = False
    return updated


def clear_after_consolidation(state: dict[str, Any], *, at: str, reasons: list[str]) -> dict[str, object]:
    updated = dict(state)
    updated["turns_since_consolidation"] = 0
    updated["compaction_pending"] = False
    updated["memory_writes_observed"] = 0
    updated["last_consolidated_at"] = at
    updated["last_reasons"] = list(reasons)
    return updated


def consolidation_reasons(
    state: dict[str, Any],
    *,
    mode: str = DEFAULT_DREAMING_MODE,
    turn_interval: int = DEFAULT_TURN_INTERVAL,
    headroom_chars: int | None = None,
    headroom_floor_chars: int = DEFAULT_HEADROOM_FLOOR_CHARS,
    file_headrooms: dict[str, tuple[int, int]] | None = None,
    duplicate_count: int = 0,
    expiring_count: int = 0,
    session_ending: bool = False,
    suppress: bool = True,
) -> list[str]:
    """Why consolidation is due now, or an empty list when it is not.

    Reasons are returned rather than a bare boolean so the handoff can state its
    own cause. "It is time" and "the file is nearly full" ask for different work,
    and a brief that cannot tell them apart is a brief that says nothing.

    ``session_ending`` (a closing session, or the recovery of one that closed
    without consolidating) uses the same threshold as the interval. It once
    lowered the bar to a single turn; that raised a brief at nearly every
    session start (213 of 216 console turns carried one, 153 via recovery), and
    the brief asks the model to capture, so it inflated the store it feeds. A
    session shorter than the interval leaves nothing worth a brief.

    A reason that describes a *condition* is suppressed until the condition
    actually changes. Observed live: 19 consecutive briefs, every one of them
    reading ``headroom_below_floor:289<=300``. Turn counts and compaction flags
    clear themselves when they fire, but headroom only clears when somebody
    consolidates -- and OMH cannot, by design. So a standing condition re-fired
    on every single turn and the journal filled with the same sentence. Each
    reason encodes its own value, so an unchanged condition is an unchanged
    string, and that is what the suppression compares.

    ``headroom_chars`` is MEMORY.md's and keeps its original reason string.
    ``file_headrooms`` maps every other Hermes memory file (USER.md) to its
    ``(headroom, floor)``; its reason names the file --
    ``headroom_below_floor:USER.md:34<=187`` -- so suppression compares each
    file's own string and an unchanged file condition stays quiet while another
    file's change still raises. The brief is retired only once no file is below
    its floor.
    """
    if normalize_dreaming_mode(mode) == "off":
        return []
    reasons: list[str] = []
    interval = turn_interval if isinstance(turn_interval, int) and turn_interval > 0 else DEFAULT_TURN_INTERVAL
    turns = _non_negative_int(state.get("turns_since_consolidation"))
    if turns >= interval:
        # A closing session is named for the moment, not the interval: the
        # same threshold, a different request ("save it now").
        reasons.append(
            f"session_ending_with_unconsolidated_turns:{turns}"
            if session_ending
            else f"turn_interval_reached:{turns}/{interval}"
        )
    if bool(state.get("compaction_pending")):
        reasons.append("context_compaction_observed")
    if headroom_chars is not None and headroom_chars <= max(headroom_floor_chars, 0):
        reasons.append(f"headroom_below_floor:{headroom_chars}<={headroom_floor_chars}")
    for label, (file_headroom, file_floor) in (file_headrooms or {}).items():
        if file_headroom <= max(file_floor, 0):
            reasons.append(f"headroom_below_floor:{label}:{file_headroom}<={file_floor}")
    if duplicate_count > 0:
        reasons.append(f"duplicate_records:{duplicate_count}")
    if expiring_count > 0:
        reasons.append(f"expiring_records:{expiring_count}")
    # ``suppress=False`` answers a different question: not "should a new brief
    # fire now" but "is anything still true at all". Retirement needs the
    # second -- a suppressed standing condition is still standing, and retiring
    # its brief because the scheduler declined to repeat it would clear a
    # notice whose fact had not cleared.
    if not suppress:
        return reasons
    return reasons if _has_unfired_reason(reasons, state) else []


def _has_unfired_reason(reasons: list[str], state: dict[str, Any]) -> bool:
    """Is anything here new since the last brief?

    An event reason always counts: it describes a moment, and the moment
    happened again. A condition reason counts only when its exact string has
    changed, because an unchanged string means the same standing condition
    nobody has cleared.

    Returning the full reason list -- rather than only the unfired part -- when
    anything is fresh is deliberate. A brief woken by the turn interval while
    memory is also nearly full should still say memory is nearly full.
    """
    already = {str(reason) for reason in state.get("last_reasons", []) if isinstance(reason, str)}
    return any(_is_event_reason(reason) or reason not in already for reason in reasons)


def _is_event_reason(reason: str) -> bool:
    return reason.split(":", 1)[0] in _EVENT_REASONS


# What the executor is asked to do differs by which moment woke it. A brief
# written because the context is about to be discarded is asking for something
# a routine interval brief is not.
#
# The compaction brief is raised in `on_pre_compress` but read in the next
# turn's pack, after the messages are gone, so it says so and names what is
# left: the summary.
_TRIGGER_INSTRUCTIONS = {
    "compaction": (
        "Context compression replaced earlier turns of this conversation with a summary; their raw "
        "messages are gone."
    ),
    "shutdown": (
        "Hermes is closing. Save what is worth keeping now; there is no later turn in this session."
    ),
    "session_end": "The session ended. Consolidate what it produced before it is only a transcript.",
    "session_start_recovery": (
        "A previous session ended without consolidating -- a closed laptop, a killed process, a lost "
        "gateway. Its counters are below and its work was never reviewed."
    ),
    "turn": "The turn interval came due. Review recent work and consolidate what proved durable.",
}


def normalize_record_expiry(value: Any) -> dict[str, int]:
    """Non-negative expired/expiring_soon counts, whatever was on disk.

    Briefs written before this key existed -- and briefs a hand edit mangled --
    must read as zeros, not as a TypeError in every consumer.
    """
    source = value if isinstance(value, dict) else {}
    return {
        "expired": _non_negative_int(source.get("expired")),
        "expiring_soon": _non_negative_int(source.get("expiring_soon")),
    }


# Replaces "trim or merge" when the file is nearly full. Trimming loses the
# fact; demotion keeps it in OMH, where recall brings it back on demand.
HEADROOM_DEMOTE_INSTRUCTION = (
    'Hermes memory is nearly full. For each demote row call omh_memory(action="demote", '
    "entry_sha256=<entry>), and remove the entry with Hermes' memory tool only when the status is "
    "demoted or already_covered. Keep anything refused or pending_review."
)
# Only with a USER.md row. The model decides what is about the user; OMH does
# not read the entries to guess. SOUL owns voice and language, not memory.
HEADROOM_USER_GUARD_INSTRUCTION = (
    "In USER.md keep entries about who the user is, how to address them, and reply language or voice; "
    "demote only the other entries."
)
HEADROOM_TRIM_INSTRUCTION = "When Hermes memory headroom is low, trim or merge its entries with Hermes' own memory tool."
CAPTURE_INSTRUCTION = (
    'Move durable facts, preferences, and decisions from this session into OMH with '
    'omh_memory(action="capture"), one bounded line each.'
)
# The compaction brief's capture line. OMH cannot ask Hermes' summarizer for a
# list -- Hermes hands provider text to it as source material, not instructions
# -- but Hermes' own summary template keeps "User preferences, coding style,
# constraints, important decisions" under one heading (`agent/context_compressor.py`).
# "Key Decisions" is left out on purpose: it holds the work's technical
# decisions, most of them scoped to the task at hand. Hermes' iterative summary
# carries earlier items forward, so each compaction would offer them again;
# only new ones are asked for, and a held one answers `already_remembered`.
COMPACTION_CAPTURE_INSTRUCTION = (
    'From that summary\'s "Constraints & Preferences", capture each fact, preference, or decision the user '
    "stated that should hold in later sessions and that you have not already captured in this conversation: "
    'one omh_memory(action="capture") call per fact. A fact OMH already holds answers already_remembered.'
)

# Only `demote`: an entry is removed only on the action's own live verdict, so
# the brief never offers a row the model could remove without calling it.
DEMOTION_ROW_KINDS = ("demote",)


def normalize_demotion_rows(value: Any) -> list[dict[str, object]]:
    """Well-formed ``{kind, file, sha12, chars}`` rows; anything else is dropped.

    Only those four keys survive, so no caller can put entry text on disk
    through this field by passing a richer row.
    """
    rows: list[dict[str, object]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict) or item.get("kind") not in DEMOTION_ROW_KINDS:
            continue
        sha12 = str(item.get("sha12", "") or "")
        if len(sha12) != 12 or any(c not in "0123456789abcdef" for c in sha12):
            continue
        rows.append(
            {
                "kind": str(item["kind"]),
                "file": str(item.get("file", "") or ""),
                "sha12": sha12,
                "chars": _non_negative_int(item.get("chars")),
            }
        )
    return rows


def normalize_hermes_files(value: Any) -> list[dict[str, object]]:
    """Well-formed ``{label, headroom_chars, floor}`` per-file headroom rows; numbers and a label only."""
    return [
        {
            "label": str(item["label"]),
            "headroom_chars": _non_negative_int(item.get("headroom_chars")),
            "floor": _non_negative_int(item.get("floor")),
        }
        for item in (value if isinstance(value, list) else [])
        if isinstance(item, dict) and isinstance(item.get("label"), str) and item["label"]
    ]


def build_consolidation_handoff(
    reasons: list[str],
    *,
    block_summaries: list[dict[str, object]] | None = None,
    eviction_plan: dict[str, object] | None = None,
    record_expiry: dict[str, int] | None = None,
    mode: str = DEFAULT_DREAMING_MODE,
    trigger: str = "manual",
    messages_at_risk: int = 0,
    session_id: str = "",
    raised_at: str = "",
    demotion_rows: list[dict[str, object]] | None = None,
    hermes_files: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """A prepared brief for whoever actually consolidates.

    OMH never executes this. It states what it observed and what it would like
    decided; only the model can act on it -- durable facts through
    `omh_memory(action="capture")`, Hermes memory through Hermes' own memory tool.

    ``demotion_rows`` name Hermes entries to move into OMH when the file is
    nearly full, by file, sha256 prefix and length only: this brief is written
    to a world-readable file and journalled metadata-only, so entry text never
    rides it. The renderer resolves a preview from the live Hermes file.
    """
    rows = normalize_demotion_rows(demotion_rows)
    requested = [_TRIGGER_INSTRUCTIONS.get(trigger, "Review what is below and consolidate what is durable.")]
    if messages_at_risk and trigger == "compaction":
        requested.append(f"{messages_at_risk} message(s) went into that summary.")
    requested.extend(
        [
            COMPACTION_CAPTURE_INSTRUCTION if trigger == "compaction" else CAPTURE_INSTRUCTION,
            (
                # Rows exist only under a headroom reason; with none to name,
                # the instruction would point at nothing.
                HEADROOM_DEMOTE_INSTRUCTION
                if rows
                else HEADROOM_TRIM_INSTRUCTION
            ),
            *([HEADROOM_USER_GUARD_INSTRUCTION] if any(row["file"] == "USER.md" for row in rows) else []),
            "Leave anything you cannot source; an unsourced entry is not evidence it is wrong.",
        ]
    )
    return {
        "schema_version": DREAMING_HANDOFF_SCHEMA_VERSION,
        "mode": normalize_dreaming_mode(mode),
        "due": bool(reasons),
        "trigger": trigger,
        # The brief's own timestamp. `last_consolidated_at` in the dreaming
        # state is when the PREVIOUS brief fired, which is strictly earlier;
        # labelling that "raised_at" mislabelled it for every consumer.
        "raised_at": raised_at,
        "session_id": session_id,
        "messages_at_risk": messages_at_risk,
        "reasons": list(reasons),
        "record_expiry": normalize_record_expiry(record_expiry),
        "blocks": list(block_summaries or []),
        "eviction_plan": dict(eviction_plan or {}),
        "demotion_rows": rows,
        "hermes_files": normalize_hermes_files(hermes_files),
        "requested_of_executor": requested,
        "redaction_policy": "metadata_only",
        "claim_boundary": (
            "A consolidation handoff is prepared context. It is not evidence that memory was "
            "consolidated, that Hermes read it, or that any entry was written, changed, or removed."
        ),
    }


def consolidation_path(omh_home: str | Path, hermes_home: str | Path) -> Path:
    return profile_dreaming_dir(omh_home, hermes_home) / "consolidation.json"


def read_latest_consolidation(
    omh_home: str | Path,
    hermes_home: str | Path,
    *,
    mode: str | None = None,
) -> dict[str, Any] | None:
    """This profile's newest brief on disk, or None when there is none to read.

    Never raises, and never returns fields a consumer has to type-check. The
    first version validated only that the file was a dict with the right
    schema string and passed everything else through -- so a brief whose
    ``reasons`` was an int survived the read and raised ``TypeError`` in the
    consumer, which for the chat notice meant one malformed local file took
    down every reply on every messenger. Fields are normalized here, once,
    for every consumer.

    A profile whose mode is `off` has no brief to read, including one written
    before it chose `off`: the pack, the chat notice, the tool and doctor all
    read through here, so none of them serves or reports it. ``mode`` is the
    mode a caller already read in this render or evaluation; None reads it.
    """
    if (configured_dreaming_mode(hermes_home) if mode is None else mode) == "off":
        return None
    path = consolidation_path(omh_home, hermes_home)
    try:
        if path.is_symlink() or not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema_version") != DREAMING_HANDOFF_SCHEMA_VERSION:
        return None
    raw_reasons = data.get("reasons")
    normalized = dict(data)
    normalized["due"] = bool(data.get("due"))
    normalized["reasons"] = (
        [reason for reason in raw_reasons if isinstance(reason, str)] if isinstance(raw_reasons, list) else []
    )
    normalized["trigger"] = str(data.get("trigger", "") or "")
    normalized["raised_at"] = str(data.get("raised_at", "") or "")
    normalized["record_expiry"] = normalize_record_expiry(data.get("record_expiry"))
    normalized["demotion_rows"] = normalize_demotion_rows(data.get("demotion_rows"))
    normalized["hermes_files"] = normalize_hermes_files(data.get("hermes_files"))
    if normalized["due"] and not normalized["reasons"]:
        # A brief that claims to be due but cannot say why is not actionable.
        normalized["due"] = False
    return normalized


def normalize_dreaming_mode(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in DREAMING_MODES else DEFAULT_DREAMING_MODE


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value

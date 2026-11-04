"""Read what Hermes actually remembers, not just how large the file is.

Hermes keeps its built-in memory in ``~/.hermes/memories/MEMORY.md`` and
``USER.md`` as a ``§``-delimited entry list, and enforces a *character* cap per
file on write (``hermes-agent/tools/memory_tool.py``). OMH's advisory lane used
``stat().st_size`` for that comparison, which is a different unit: UTF-8 spends
three bytes on a Hangul syllable, so a Korean MEMORY.md reads about 1.2x its own
length. A 1,933-character file reports as ``2347 bytes (cap ~2200)`` and looks
over budget while Hermes still accepts writes. An ASCII file of the same length
reports correctly, which is why the mismatch went unnoticed.

Counting characters fixes the unit. Splitting the entries is what lets the rest
of OMH say *which* entry is stale or already duplicated in its own store,
instead of only how full the file is.

The cap itself is read rather than assumed. Hermes takes it from
``memory.memory_char_limit`` / ``memory.user_char_limit`` in ``config.yaml`` and
only falls back to 2200/1375, so hardcoding those two numbers reported a raised
limit as exhausted headroom on any host that had changed them. Each reading
carries the cap it was measured against and whether that cap was observed in
config or assumed.

Read-only by construction: nothing here opens a file for writing. Hermes owns
these files, and the `memory` tool it exposes to the model is the surface that
edits them.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from .iso_datetime import strict_fromisoformat

# Hermes' own entry separator: ENTRY_DELIMITER in its memory store
# (``tools/memory_tool_store.py``), which splits on the FULL "\n§\n" so a bare
# "§" inside an entry survives, and joins with it when counting characters. A
# bare-"§" split cut such an entry into fragments OMH treated as separate
# entries -- and a demoted fragment let Hermes remove the whole entry.
HERMES_MEMORY_DELIMITER = "\n§\n"

# The caps Hermes falls back to, not the caps it necessarily enforces. Hermes
# builds its memory tool with ``mem_config.get("memory_char_limit", 2200)`` and
# ``mem_config.get("user_char_limit", 1375)`` (``agent/agent_init.py``), so a
# user who raises either limit in ``config.yaml`` keeps writing while OMH -- which
# used to hardcode these two numbers -- reported the file over cap and its
# headroom exhausted. Read the config; treat these as the fallback they are.
DEFAULT_MEMORY_FILE_CAP_CHARS = 2200
DEFAULT_USER_FILE_CAP_CHARS = 1375

# Memory file, the ``memory`` config key that overrides its cap, and the default.
HERMES_MEMORY_FILES = (
    ("MEMORY.md", "memory_char_limit", DEFAULT_MEMORY_FILE_CAP_CHARS),
    ("USER.md", "user_char_limit", DEFAULT_USER_FILE_CAP_CHARS),
)


@dataclass(frozen=True)
class HermesMemoryFile:
    """One Hermes memory file as OMH observed it."""

    label: str
    path: Path
    exists: bool
    chars: int
    cap: int
    entries: tuple[str, ...]
    age_days: float
    error: str = ""
    cap_source: str = "default"

    @property
    def over_cap(self) -> bool:
        return self.exists and self.chars > self.cap

    @property
    def headroom_chars(self) -> int:
        """Characters a new entry may occupy, delimiter included."""
        if not self.exists:
            return self.cap
        return max(0, self.cap - self.chars)

    def to_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "path": str(self.path),
            "exists": self.exists,
            "chars": self.chars,
            "cap": self.cap,
            "cap_source": self.cap_source,
            "over_cap": self.over_cap,
            "headroom_chars": self.headroom_chars,
            "entry_count": len(self.entries),
            "age_days": round(self.age_days, 1),
            "error": self.error,
        }


def parse_memory_entries(text: str) -> tuple[str, ...]:
    """Split one Hermes memory file into its entries."""
    return tuple(entry.strip() for entry in text.split(HERMES_MEMORY_DELIMITER) if entry.strip())


def memory_char_count(entries: tuple[str, ...] | list[str]) -> int:
    """Count characters the way Hermes counts them when enforcing the cap."""
    if not entries:
        return 0
    return len(HERMES_MEMORY_DELIMITER.join(entries))


def resolve_memory_caps(hermes_home: str | Path) -> tuple[tuple[str, int, str], ...]:
    """Per-file ``(label, cap, cap_source)`` for one Hermes home.

    ``cap_source`` is ``"config"`` when ``config.yaml`` overrode the cap and
    ``"default"`` otherwise, so a reader can tell an observed limit from an
    assumed one instead of trusting every cap equally.

    A key that is absent, unparseable, or not a positive integer falls back to
    the default: OMH reports on Hermes memory and must not turn a malformed
    config into a headroom figure that looks measured.
    """
    config_text = _read_hermes_config(hermes_home)
    resolved: list[tuple[str, int, str]] = []
    for label, config_key, default_cap in HERMES_MEMORY_FILES:
        configured = _positive_int(_config_section_scalar(config_text, "memory", config_key))
        if configured is None:
            resolved.append((label, default_cap, "default"))
        else:
            resolved.append((label, configured, "config"))
    return tuple(resolved)


def read_hermes_memory_file(
    path: Path,
    *,
    label: str,
    cap: int,
    now: float | None = None,
    cap_source: str = "default",
) -> HermesMemoryFile:
    """Read one memory file. Never raises: an unreadable file reports its error."""
    moment = time.time() if now is None else now
    if not path.exists():
        return HermesMemoryFile(label, path, False, 0, cap, (), 0.0, cap_source=cap_source)
    try:
        # utf-8-sig like Hermes' reader: a BOM left by an editor must not stay
        # glued to the first entry, or its digest matches nothing Hermes holds.
        text = path.read_text(encoding="utf-8-sig")
        age_days = max(0.0, (moment - path.stat().st_mtime) / 86400.0)
    except (OSError, UnicodeDecodeError) as error:
        return HermesMemoryFile(label, path, True, 0, cap, (), 0.0, error=str(error), cap_source=cap_source)
    entries = parse_memory_entries(text)
    return HermesMemoryFile(
        label,
        path,
        True,
        memory_char_count(entries),
        cap,
        entries,
        age_days,
        cap_source=cap_source,
    )


def read_hermes_memory(
    hermes_home: str | Path,
    *,
    now: float | None = None,
) -> tuple[HermesMemoryFile, ...]:
    """Read every Hermes memory file under one Hermes home, at its configured cap."""
    memories_dir = Path(hermes_home).expanduser() / "memories"
    return tuple(
        read_hermes_memory_file(memories_dir / label, label=label, cap=cap, now=now, cap_source=cap_source)
        for label, cap, cap_source in resolve_memory_caps(hermes_home)
    )


def _read_hermes_config(hermes_home: str | Path) -> str:
    """Hermes' ``config.yaml`` as text, or empty when it cannot be read."""
    path = Path(hermes_home).expanduser() / "config.yaml"
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _positive_int(value: str) -> int | None:
    """A positive integer scalar, or None when the text is not one."""
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _config_section_scalar(config_text: str, section: str, key: str) -> str:
    """One scalar under one top-level section, in dotted or nested form.

    Vendored rather than imported: this module is loaded inside the Hermes
    process, where the `omh` package is absent, so it cannot reach OMH's own
    reader in `workflows/hermes_retained_context_probes.py`. Same two forms,
    same comment and quote handling.
    """
    dotted = f"{section}.{key}:"
    section_header = f"{section}:"
    in_section = False
    for line in config_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(dotted):
            return _clean_config_scalar(stripped[len(dotted) :])
        if not line.startswith(" "):
            in_section = stripped == section_header
            continue
        if in_section and line.startswith("  ") and not line.startswith("    "):
            prefix = f"{key}:"
            if stripped.startswith(prefix):
                return _clean_config_scalar(stripped[len(prefix) :])
    return ""


def _clean_config_scalar(value: str) -> str:
    stripped = _strip_unquoted_yaml_comment(value).strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def _strip_unquoted_yaml_comment(value: str) -> str:
    in_single_quote = False
    in_double_quote = False
    for index, character in enumerate(value):
        if character == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            continue
        if character == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            continue
        if character == "#" and not in_single_quote and not in_double_quote and _starts_yaml_comment(value, index):
            return value[:index]
    return value


def _starts_yaml_comment(value: str, index: int) -> bool:
    return index == 0 or value[index - 1].isspace()


# A fact restated in Hermes' own words shares most of its nouns but almost none
# of its punctuation or particles, so token overlap separates "already known"
# from "new" where exact matching cannot. The threshold is deliberately loose:
# this only decides what to *show* a reviewer, never what to write.
DUPLICATE_SIMILARITY_THRESHOLD = 0.6

_TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]{2,}")


def text_tokens(text: str) -> frozenset[str]:
    """Comparable tokens for one memory summary or entry."""
    return frozenset(_TOKEN_PATTERN.findall(text.lower()))


def similarity(left: str, right: str) -> float:
    """Jaccard overlap of two memory texts, 0.0 when either side has no tokens."""
    left_tokens = text_tokens(left)
    right_tokens = text_tokens(right)
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    return len(left_tokens & right_tokens) / len(union)


def nearest_entry(text: str, entries: tuple[str, ...] | list[str]) -> tuple[int, float]:
    """Index and score of the entry closest to ``text``; ``(-1, 0.0)`` when none."""
    best_index = -1
    best_score = 0.0
    for index, entry in enumerate(entries):
        score = similarity(text, entry)
        if score > best_score:
            best_index, best_score = index, score
    return best_index, best_score


HERMES_MEMORY_BRIDGE_SCHEMA_VERSION = "hermes_memory_bridge/v1"
PROJECT_MEMORY_RECORD_SCHEMA_VERSION = "project_memory_record/v2"
PRINCIPAL_PROJECT_MEMORY_RECORD_SCHEMA_VERSION = "project_memory_record/v3"


# What `unreadable` holds when a whole directory could not be listed, in place
# of a file basename. Relative on purpose: the receipt carries home digests,
# never home paths.
RECORDS_DIRECTORY_LABEL = "memory/records"
REVIEWS_DIRECTORY_LABEL = "memory/reviews"


def read_reviewed_records(omh_home: str | Path, *, unreadable: list[str] | None = None) -> list[dict[str, Any]]:
    """Every v2 record whose admission review exists, never legacy display-only records.

    No replay verdict is applied here. Supersession, expiry and review
    staleness depend on a clock, and the prefetch selector classifies them at
    the caller's clock; a reader that judged them at host wall clock first
    would drop a superseded or expired record before the selector could name
    it, so the live receipt could never report the exclusion the canonical
    handoff reports.

    A record or review that cannot be read or parsed is still skipped, so
    one corrupt file never costs the rest of the store. When ``unreadable``
    is given, each skip appends the file's basename (never its content) and
    a directory that cannot be listed appends its label, so the caller can
    tell a corrupt store from an empty one.
    """
    home = Path(omh_home).expanduser() / "memory"
    return _reviewed_records(home, _read_reviews(home / "reviews", unreadable=unreadable), unreadable=unreadable)


def read_approved_records(omh_home: str | Path) -> list[dict[str, Any]]:
    """Replay-eligible v2 records at wall clock, for the bridge, demotion and expiry views."""
    evaluate_memory_replay = _memory_governance.evaluate_memory_replay

    home = Path(omh_home).expanduser() / "memory"
    reviews = _read_reviews(home / "reviews")
    return [
        record
        for record in _reviewed_records(home, reviews)
        if evaluate_memory_replay(record, review_resolver=reviews or None).get("eligible")
    ]


def _reviewed_records(
    home: Path,
    reviews: dict[str, dict[str, object]],
    *,
    unreadable: list[str] | None = None,
    legacy_approved: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        candidates = _json_candidates(home / "records")
    except OSError:
        if unreadable is not None:
            unreadable.append(RECORDS_DIRECTORY_LABEL)
        return records
    for path in candidates:
        try:
            if path.is_symlink() or not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            if unreadable is not None:
                unreadable.append(path.name)
            continue
        if legacy_approved is not None and _legacy_approved(data):
            legacy_approved.append(data)
        if not isinstance(data, dict) or data.get("schema_version") not in {
            PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
            PRINCIPAL_PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
        }:
            continue
        admission = data.get("admission") if isinstance(data.get("admission"), dict) else {}
        review_id = admission.get("review_id") if isinstance(admission, dict) else None
        if isinstance(review_id, str) and review_id in reviews:
            records.append(data)
    return records


def _json_candidates(directory: Path) -> list[Path]:
    """The directory's ``*.json`` entries, sorted; [] when it does not exist.

    Listed with ``os.scandir`` rather than ``Path.glob`` because glob turns a
    directory it may not read into an empty result (measured on CPython
    3.14), which made a store whose directory lost its permissions look
    exactly like an empty one. Any listing failure but absence raises.
    """
    try:
        with os.scandir(directory) as entries:
            names = [entry.name for entry in entries if fnmatch.fnmatch(entry.name, "*.json")]
    except FileNotFoundError:
        return []
    # The order `sorted()` gives these paths, which differ only in their name,
    # without comparing `Path` objects: that comparison re-derives both
    # paths' parts every time, and a live turn lists the records and reviews
    # directories several times.
    return [directory / name for name in sorted(names, key=_name_sort_key())]


def _name_sort_key() -> Callable[[str], str] | None:
    """The key that orders file names the way `sorted()` orders paths of one directory.

    A case-insensitive flavour (Windows) orders by `str.lower()`, which is not
    what `os.path.normcase` does there for every non-ASCII name, so the key is
    `str.lower` itself; a case-sensitive one needs none.
    """
    return None if os.path.normcase("Aa") == "Aa" else str.lower


def _read_reviews(directory: Path, *, unreadable: list[str] | None = None) -> dict[str, dict[str, object]]:
    reviews: dict[str, dict[str, object]] = {}
    try:
        candidates = _json_candidates(directory)
    except OSError:
        if unreadable is not None:
            unreadable.append(REVIEWS_DIRECTORY_LABEL)
        return reviews
    for path in candidates:
        try:
            if path.is_symlink() or not path.is_file():
                continue
            review = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            if unreadable is not None:
                unreadable.append(path.name)
            continue
        if isinstance(review, dict) and isinstance(review.get("review_id"), str):
            reviews[review["review_id"]] = review
    return reviews


# "Expiring soon" reaches this many days ahead. No upstream default exists for
# TTL look-ahead; seven days is chosen conservative and is threaded, not read
# from config, so every caller states the window it asked about.
RECORD_EXPIRY_WINDOW_DAYS = 7


def _parse_expires_at(value: Any) -> tuple[datetime | None, str]:
    """An aware UTC datetime, or (None, why-not).

    Naive timestamps are UTC by definition here. The workflows-side parser reads
    a naive value through ``astimezone``, which means host-local time -- up to
    +/-14h of skew depending on where the host happens to be. A classifier
    whose verdict moves files cannot inherit that; one rule, stated once:
    no offset means Z.
    """
    text = str(value or "").strip()
    if not text:
        return None, "no_ttl"
    try:
        parsed = strict_fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None, "malformed"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc), ""


def classify_record_expiry(
    record: dict[str, Any],
    *,
    now: datetime,
    window_days: int = RECORD_EXPIRY_WINDOW_DAYS,
) -> str:
    """One record's TTL state: fresh, expiring, expired, no_ttl, or malformed.

    N5 integration: Delegates to memory_governance for expiry authority.
    The single source of truth for what "expired" means. Recall exclusion and
    retirement both route through this so they can never disagree; ``expired``
    uses the same ``<=`` recall has always used. ``no_ttl`` (absent or empty
    ``expires_at``) is a healthy record that never expires. ``malformed`` is a
    value that claims to be a deadline but cannot be read -- never treated as
    expired, because a move on a misread is a move that cannot be defended.
    """
    classify_record_expiry_v1_compat = _memory_governance.classify_record_expiry_v1_compat
    return classify_record_expiry_v1_compat(record, now=now, window_days=window_days)


def count_record_expiry(
    omh_home: str | Path,
    *,
    now: datetime,
    window_days: int = RECORD_EXPIRY_WINDOW_DAYS,
) -> dict[str, int]:
    """How many approved records are past or approaching their deadline.

    Only the two actionable states are counted: ``no_ttl`` records cannot
    expire and ``malformed`` records must not be acted on from here -- the
    retirement report is where an unreadable deadline is surfaced, per file,
    with its reason.
    """
    evaluate_memory_replay = _memory_governance.evaluate_memory_replay

    counts = {"expired": 0, "expiring_soon": 0}
    # Legacy expiry totals are metadata-only reminder evidence; they never make
    # a v1 summary eligible for bridge, provider, or tool replay. One pass over
    # the records directory finds both: this runs on every attended turn.
    home = Path(omh_home).expanduser() / "memory"
    reviews = _read_reviews(home / "reviews")
    legacy: list[dict[str, Any]] = []
    approved = [
        record
        for record in _reviewed_records(home, reviews, legacy_approved=legacy)
        if evaluate_memory_replay(record, review_resolver=reviews or None).get("eligible")
    ]
    for record in (*approved, *legacy):
        state = classify_record_expiry(record, now=now, window_days=window_days)
        if state == "expired":
            counts["expired"] += 1
        elif state == "expiring":
            counts["expiring_soon"] += 1
    return counts


def _legacy_approved(record: object) -> bool:
    """An approved v1 record: counted for expiry, never replayed."""
    return (
        isinstance(record, dict)
        and record.get("schema_version") == "project_memory_record/v1"
        and record.get("review_status") == "approved"
    )


def build_hermes_memory_bridge(omh_home: str | Path, hermes_home: str | Path) -> dict[str, object]:
    """Relate OMH's approved records to what Hermes already remembers.

    The two stores share no identifier, so neither could see the other: OMH
    deduplicated against itself, and Hermes' memory tool rejects only exact
    strings. A fact approved in OMH and restated by hand in MEMORY.md lived in
    both, worded differently, with nothing linking them.

    Read-only. Hermes owns these files; its own `memory` tool is what edits them.
    """
    readings = read_hermes_memory(hermes_home)
    records = read_approved_records(omh_home)
    memory_file = next((reading for reading in readings if reading.label == "MEMORY.md"), None)
    entries = memory_file.entries if memory_file else ()
    already_present: list[dict[str, object]] = []
    promotable: list[dict[str, object]] = []
    matched_entries: set[int] = set()
    for record in records:
        summary = str(record.get("summary", "") or "")
        index, score = nearest_entry(summary, entries)
        row: dict[str, object] = {
            "record_id": str(record.get("record_id", "")),
            "summary_length": len(summary),
            "scope": record.get("scope", {}),
            "nearest_entry_index": index,
            "similarity": round(score, 2),
        }
        if score >= DUPLICATE_SIMILARITY_THRESHOLD:
            matched_entries.add(index)
            already_present.append(row)
            continue
        # The delimiter Hermes inserts before an appended entry is part of the cost.
        row["fits_headroom"] = bool(memory_file) and len(summary) + len(HERMES_MEMORY_DELIMITER) <= memory_file.headroom_chars
        promotable.append(row)
    return {
        "schema_version": HERMES_MEMORY_BRIDGE_SCHEMA_VERSION,
        "files": [reading.to_dict() for reading in readings],
        "approved_records": len(records),
        "already_in_hermes": already_present,
        "promotable": promotable,
        "hermes_entries_without_omh_record": _unsourced_entry_rows(entries, matched_entries),
        "external_context": {
            "provider": {"source_class": "provider", "admission_status": "not_omh_reviewed"},
            "vector": {"source_class": "vector", "admission_status": "not_omh_reviewed"},
        },
        "duplicate_similarity_threshold": DUPLICATE_SIMILARITY_THRESHOLD,
        "redaction_policy": "metadata_only",
        "next_action": (
            "Promote a record by asking Hermes to add it through its own memory tool; free headroom first "
            "when nothing fits."
        ),
        "claim_boundary": (
            "OMH reads Hermes memory and cannot change it. This comparison is prepared review context only; "
            "it is not a Hermes memory write, execution, review, CI, or merge evidence. A configured Hermes "
            "runtime may transmit rendered OMH prefetch content to its model request."
        ),
    }


def _unsourced_entry_rows(entries: tuple[str, ...], matched: set[int]) -> list[dict[str, object]]:
    """Hermes entries no approved OMH record explains, as metadata only."""
    return [
        {
            "entry_index": index,
            "chars": len(entry),
            "sha256": hashlib.sha256(entry.encode("utf-8")).hexdigest(),
            "source_class": "hermes_native",
            "admission_status": "not_omh_reviewed",
        }
        for index, entry in enumerate(entries)
        if index not in matched
    ]


MEMORY_DEMOTION_PLAN_SCHEMA_VERSION = "hermes_memory_demotion_plan/v1"

# How much of the entry the reference line quotes back. Long enough that an
# operator recognises which fact moved, short enough that the move still frees
# space -- freeing space is the entire reason to make it.
DEMOTION_REFERENCE_LABEL_CHARS = 60


def build_memory_demotion_plan(
    omh_home: str | Path,
    hermes_home: str | Path,
    *,
    file_label: str | None = None,
    max_entries: int = 5,
) -> dict[str, object]:
    """Plan which Hermes entries to move down into OMH's store, biggest first.

    Hermes memory is L1: small, character-capped, and paid for on every turn.
    The OMH record store is L2: reviewed, governed, and not bound by that cap.
    When L1 fills the usual move is deleting an entry, which loses the fact.
    Demotion is the other move -- the content goes to L2 and a short reference
    line stays in L1 -- and this function is the plan for it.

    An entry an approved OMH record already explains is not demotion work: its
    content is in L2 already, so it is reported separately as deletable rather
    than copied down a second time. What remains is ranked by size, so the
    first row an operator applies buys the most headroom.

    The reference line is keyed by the sha256 of the entry's exact UTF-8 bytes,
    which is the one identifier both stores can compute without agreeing on
    anything: it is the same before the candidate is captured and after the
    record is approved, so the line survives the lifecycle it points into.

    Prepared text only. Nothing here opens a Hermes file for writing -- Hermes
    applies a row through its own `memory` tool, or the row is not applied.
    """
    if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 1:
        raise ValueError(f"max_entries must be an integer of at least 1, got {max_entries!r}")
    readings = read_hermes_memory(hermes_home)
    if file_label is not None and not any(reading.label == file_label for reading in readings):
        return _unknown_file_label_plan(file_label, readings)
    selected = [reading for reading in readings if file_label is None or reading.label == file_label]
    summaries = [
        (str(record.get("record_id", "")), str(record.get("summary", "") or ""))
        for record in read_approved_records(omh_home)
    ]
    already_covered: list[dict[str, object]] = []
    candidates: list[tuple[str, int, str]] = []
    for reading in selected:
        for index, entry in enumerate(reading.entries):
            record_id, score = _nearest_record(entry, summaries)
            if score >= DUPLICATE_SIMILARITY_THRESHOLD:
                already_covered.append(_already_covered_row(reading.label, index, entry, record_id, score))
                continue
            candidates.append((reading.label, index, entry))
    # Biggest saving first; label and index only break ties, so two runs over
    # the same store propose the same rows in the same order.
    candidates.sort(key=lambda candidate: (-len(candidate[2]), candidate[0], candidate[1]))
    rows = [_demotion_row(label, index, entry) for label, index, entry in candidates[:max_entries]]
    return {
        "schema_version": MEMORY_DEMOTION_PLAN_SCHEMA_VERSION,
        "files": [_demotion_file_summary(reading, rows) for reading in selected],
        "rows": rows,
        "already_covered": already_covered,
        "row_count": len(rows),
        "estimated_savings_chars": sum(max(int(row["savings_chars"]), 0) for row in rows),
        "redaction_policy": "local_content_plan",
        "next_action": _DEMOTION_NEXT_ACTION,
        "claim_boundary": _DEMOTION_CLAIM_BOUNDARY,
    }


# Unlike the bridge, these rows carry entry text: a demotion cannot be reviewed
# or applied without the content being moved. The text is the operator's own
# local Hermes memory, staying on the same host, and no lane transmits it.
_DEMOTION_NEXT_ACTION = (
    "Stage the rows with `omh memory demote --stage`, approve the staged candidates, then ask Hermes to "
    "replace each original entry with its reference line through Hermes's own memory tool."
)
_DEMOTION_CLAIM_BOUNDARY = (
    "OMH reads Hermes memory and cannot change it. This plan is prepared local text only "
    "(prepared_not_observed); it is not a Hermes memory write, execution, review, CI, or merge evidence."
)


def _unknown_file_label_plan(file_label: str, readings: tuple[HermesMemoryFile, ...]) -> dict[str, object]:
    """An empty plan that names the labels that do exist.

    A typo'd label must not read as "this file has nothing to demote": the two
    answers look identical from the payload unless the reason is stated.
    """
    return {
        "schema_version": MEMORY_DEMOTION_PLAN_SCHEMA_VERSION,
        "files": [],
        "rows": [],
        "already_covered": [],
        "row_count": 0,
        "estimated_savings_chars": 0,
        "reason_code": "unknown_file_label",
        "requested_file_label": file_label,
        "known_file_labels": [reading.label for reading in readings],
        "redaction_policy": "local_content_plan",
        "next_action": _DEMOTION_NEXT_ACTION,
        "claim_boundary": _DEMOTION_CLAIM_BOUNDARY,
    }


def _nearest_record(entry: str, summaries: list[tuple[str, str]]) -> tuple[str, float]:
    """Record id and score of the approved summary closest to ``entry``."""
    best_id = ""
    best_score = 0.0
    for record_id, summary in summaries:
        score = similarity(entry, summary)
        if score > best_score:
            best_id, best_score = record_id, score
    return best_id, best_score


def _already_covered_row(
    label: str,
    index: int,
    entry: str,
    record_id: str,
    score: float,
) -> dict[str, object]:
    """One L1 entry an approved L2 record already explains: delete, don't demote."""
    return {
        "file": label,
        "entry_index": index,
        "chars": len(entry),
        "sha256": entry_digest(entry),
        "matched_record_id": record_id,
        "similarity": round(score, 2),
        "already_in_omh": True,
    }


def _demotion_row(label: str, index: int, entry: str) -> dict[str, object]:
    """One proposed move, with the text to store and the line that replaces it."""
    reference_line = demotion_reference_line(entry)
    return {
        "file": label,
        "entry_index": index,
        "chars": len(entry),
        "sha256": entry_digest(entry),
        "entry_text": entry,
        "reference_line": reference_line,
        "reference_chars": len(reference_line),
        # Negative for an entry shorter than its own reference line. Reported
        # rather than hidden: a row that costs characters is still a real
        # answer, and clamping it would inflate the total saving.
        "savings_chars": len(entry) - len(reference_line),
    }


def demotion_reference_line(entry: str) -> str:
    """The line that stays in L1 once the entry's content lives in OMH."""
    digest = entry_digest(entry)
    label_text = " ".join(entry.split())
    if len(label_text) > DEMOTION_REFERENCE_LABEL_CHARS:
        label_text = label_text[:DEMOTION_REFERENCE_LABEL_CHARS] + "…"
    return f"[omh#{digest[:12]}] {label_text}"


def entry_digest(entry: str) -> str:
    """The entry's identity in both stores: sha256 of its exact UTF-8 bytes."""
    return hashlib.sha256(entry.encode("utf-8")).hexdigest()


def demotion_origin_ref(file_label: str, entry: str) -> str:
    """The `source_ref` a demoted candidate carries back to its L1 entry.

    The same string `omh memory demote --stage` writes, so the model's path and
    the operator's path see each other's candidates and never stage one twice.
    """
    return f"hermes:{file_label}#{entry_digest(entry)[:16]}"


def _demotion_file_summary(reading: HermesMemoryFile, rows: list[dict[str, object]]) -> dict[str, object]:
    """One file's headroom now, and the headroom the planned rows would leave."""
    planned = [row for row in rows if row["file"] == reading.label]
    return {
        "label": reading.label,
        "cap": reading.cap,
        "chars": reading.chars,
        "headroom_chars": reading.headroom_chars,
        "over_cap": reading.over_cap,
        "entry_count": len(reading.entries),
        "planned_demotions": len(planned),
        "estimated_headroom_after": reading.headroom_chars
        + sum(max(int(row["savings_chars"]), 0) for row in planned),
    }


# Module scope, not call time: Hermes can evict the bundle from sys.modules
# while its callbacks stay live (#1979). Last, so an import cycle finds every name.
from . import memory_governance as _memory_governance

"""Deterministic owner-to-OMH progress vocabulary normalization (`omh_owner_progress_normalization/v1`).

Every coding owner narrates its own progress in its own words. Codex says
`targeted_tests_passed`, a Claude Code stream says `result`, an omo host says
nothing structured at all. Downstream surfaces -- the status board, the live
executor projection, the chat reporter -- need one vocabulary, and the
translation into it is where a wrapper quietly starts lying: an unrecognized
word becomes a plausible neighbour, a preparation-class word becomes an
execution claim, and the original word is gone.

This module is that translation and nothing else. It sits UPSTREAM of
`executor_progress`, which keeps owning liveness, suppression, dedupe, and its
own claim boundary; it hands back a record and never writes one.

Relationship to `executor_progress` (read this before "fixing" either module):

    `executor_progress` owns the shipped `omh_progress_event/v1` record and the
    binding lane, whose owner set (`ALLOWED_EXECUTOR_PROFILES`) is four lanes
    wide because those are the lanes that can carry a binding. This module
    covers the FANOUT owner set (`executors.EXECUTOR_PROFILES`, seven owners),
    because a normalization question is asked about owners that have no
    progress lane at all. The two sets are deliberately different sizes and
    neither is a bug in the other: a lane rejects an owner it cannot observe,
    while a normalizer must still answer, honestly, for an owner it cannot map.

Boundaries, in order of importance:

- Never fabricate. An owner event this module cannot map becomes
  `unmapped_source_event` with the bounded raw `source_event` retained
  verbatim. It is never quietly rounded to a neighbouring event, and it is
  never dropped: a plausible wrong word is worse than an honest unknown,
  because only the honest unknown can be noticed.
- Never upgrade. The evidence tier a SOURCE event carries is declared once per
  WORD (`_SOURCE_EVENT_EVIDENCE_TIERS`) and is never restated by the row that
  maps it: a row that brought its own source tier could always declare one high
  enough to pass, which would make the comparison compare a value with itself.
  `normalization_raises_evidence` compares the word's tier against the tier its
  normalized event sits at, and a row that would raise the tier is refused at
  runtime rather than emitted. A preparation-class source event therefore
  cannot become a dispatch, execution, or verification claim -- and because the
  normalized vocabulary has no preparation-tier member, a preparation-class
  event has no home and says so
  (`no_normalized_event_at_source_evidence_tier`) instead of borrowing one. A
  word nobody classified sits at the floor for the same reason.
- Never outrun the stream. Each owner also carries an evidence CEILING taken
  from this repo's own telemetry contract: an owner whose structured stream
  nothing here can read cannot reach the verification tier no matter which word
  it says (`owner_stream_cannot_carry_the_source_evidence_tier`).
- Pure and deterministic. `normalize_owner_progress_event` performs no file
  I/O, no clock read, no environment read, and no network call; the same
  `(owner, source_event, source_version, correlation)` always yields a
  byte-identical record. It never raises.
- Honest absence over invented coverage. Owners with no progress lane
  (`omx-runtime`, `omc-runtime`, `generic`) return a visible record with
  `owner_supported: False`, not an exception and not a silent collapse. An
  owner name this repo does not know at all is distinguished from a known
  owner that simply has no lane, because those need different fixes.
- Lossy is a fact, not a failure. Several owner words legitimately collapse
  onto one normalized word (`targeted_tests_passed` and `full_tests_passed`
  both become `tests_passed`). `mapping_confidence: "lossy"` records that the
  normalized event alone cannot identify which source word it was; the
  `source_event` field is what recovers it.
- Reporting only. A normalization record is an observation of what an owner
  said. It is not result, verification, review, CI, merge-readiness, or merge
  evidence.

Reading a record (`omh_owner_progress_normalization/v1`)
-------------------------------------------------------

A record answers "why does this event say what it says", and every field exists
because something is unrecoverable without it:

    owner                     the fanout owner, after alias folding
    owner_supported           False for an owner with no progress lane at all
    source_event              the raw word, bounded, verbatim -- the only thing
                              that recovers a `lossy` collapse
    source_version            the dialect version the caller named, if any
    correlation               which run/session the word belongs to
    normalized_event          the shared-vocabulary word it became
    source_evidence_tier      what the source word carries, after the owner's
                              ceiling is applied
    normalized_evidence_tier  where the normalized word sits; never above the
                              line above it
    mapping_confidence        exact | aliased | lossy | unmapped | absent
    mapping_note              the closed reason code (`MAPPING_NOTES`)
    claim_boundary            what the record is not

Where a person reads one: `executor_progress.progress_event_normalization`
attaches it to any stored progress event whose type is `unmapped_source_event`,
so it surfaces on `omh runtime progress-status` under
`latest_progress_events[].normalization` and on each active row's
`latest_event.normalization`. It is absent for every other event type, because
for those the event type is already the whole answer.

Two refusals reach `unmapped_source_event` and read differently on purpose. The
notes beginning `source_event_not_in_owner_dialect` /
`owner_stream_cannot_carry_the_source_evidence_tier` /
`mapping_would_raise_the_evidence_tier` are this module's: the word could not be
translated. `self_reported_end_state_not_corroborated` is the LANE's: the claim
translated perfectly well, and `executor_progress.infer_progress_event_type`
refused it because nothing the lane OBSERVED agreed that the run had ended.
"Independent" there means observed rather than told -- the process state omh
sampled, or a stream it parsed itself -- not merely "a different field of the
same caller's sentence", which is how the same caller's `--profile-status` came
to corroborate the word it was passed beside.
"""

from __future__ import annotations

from typing import Any, Final, NamedTuple

from .executors import EXECUTOR_PROFILES

OWNER_PROGRESS_NORMALIZATION_SCHEMA_VERSION: Final[str] = "omh_owner_progress_normalization/v1"

OWNER_PROGRESS_NORMALIZATION_CLAIM_BOUNDARY: Final[str] = (
    "A normalization record renames one owner-reported progress event into the shared OMH progress "
    "vocabulary. It is metadata-only observed narration, not result, verification, review, CI, "
    "merge-readiness, or merge evidence, and it never raises the evidence tier the source event carried."
)

# The one addition to the shipped vocabulary. It carries the bounded raw
# `source_event` verbatim so an owner word this repo does not map stays VISIBLE
# instead of being rounded to a neighbouring event. It is deliberately NOT a
# terminal or closing event type in `executor_progress`: an unrecognized word
# ends nothing.
UNMAPPED_NORMALIZED_EVENT: Final[str] = "unmapped_source_event"

# The shared progress vocabulary. `executor_progress.PROGRESS_EVENT_TYPES` is
# this tuple -- there is one definition, not two, because the mirror in
# `plugin_bundle/omh/runtime_reader.py` already proves how expensive a second
# copy is. The first twelve entries keep their original order; the CLI derives
# `omh runtime progress observe --event` choices from it.
NORMALIZED_PROGRESS_EVENT_TYPES: Final[tuple[str, ...]] = (
    "executor_dispatched",
    "repo_exploration",
    "running_no_diff_observed",
    "diff_started",
    "tests_started",
    "tests_failed",
    "tests_passed",
    "executor_completed",
    "executor_blocked",
    "executor_failed",
    # An observed cancellation. It sits beside the other three end-state words
    # rather than folding into `executor_failed`, because "this ran and did not
    # work" and "someone stopped this" call for different recovery. The lane
    # (`executor_progress.infer_progress_event_type`) is what decides whether a
    # word this table translates is CORROBORATED; a run whose process was never
    # observed to stop cannot reach this event by narration alone.
    "executor_cancelled",
    "reported_change_not_observed",
    "progress_observed",
    UNMAPPED_NORMALIZED_EVENT,
)

# Evidence tiers, weakest first. The rank is the index, so "is this an upgrade"
# is one comparison. `preparation` is the floor and the only tier with no
# normalized event other than `unmapped_source_event`, which is exactly why a
# preparation-class owner word cannot be normalized into an execution claim.
PROGRESS_EVIDENCE_TIERS: Final[tuple[str, ...]] = (
    "preparation",
    "dispatch",
    "progress",
    "result_claimed",
    "verified",
)

_FLOOR_TIER: Final[str] = PROGRESS_EVIDENCE_TIERS[0]

# `tests_failed` sits at `verified` alongside `tests_passed`: the tier names
# which KIND of evidence was observed, not whether the news was good. A failing
# verification signal is still a verification-class observation.
_TIER_BY_NORMALIZED_EVENT: Final[dict[str, str]] = {
    UNMAPPED_NORMALIZED_EVENT: "preparation",
    "executor_dispatched": "dispatch",
    "repo_exploration": "progress",
    "running_no_diff_observed": "progress",
    "diff_started": "progress",
    "tests_started": "progress",
    "progress_observed": "progress",
    # A claim/observation mismatch is observed activity, not a result: it fires
    # when narration and the working tree disagree, which settles nothing.
    "reported_change_not_observed": "progress",
    "executor_completed": "result_claimed",
    "executor_blocked": "result_claimed",
    "executor_failed": "result_claimed",
    "executor_cancelled": "result_claimed",
    "tests_passed": "verified",
    "tests_failed": "verified",
}

MAPPING_CONFIDENCES: Final[tuple[str, ...]] = ("exact", "aliased", "lossy", "unmapped", "absent")

# Closed note vocabulary. Every record justifies its confidence with one of
# these; they are identifiers, not prose, so a caller can branch on them and a
# test can assert them.
MAPPING_NOTES: Final[tuple[str, ...]] = (
    "source_event_matches_normalized_vocabulary",
    "owner_dialect_alias",
    "owner_dialect_collapses_onto_one_normalized_event",
    "no_normalized_event_at_source_evidence_tier",
    "source_event_not_in_owner_dialect",
    "owner_has_no_progress_lane",
    "owner_is_not_a_known_fanout_owner",
    "no_source_event_reported",
    "mapping_would_raise_the_evidence_tier",
    # The owner said a word this repo maps, but its stream cannot carry the
    # evidence that word claims -- see `_OWNER_EVIDENCE_CEILING`.
    "owner_stream_cannot_carry_the_source_evidence_tier",
    # No owner was named, so only the dialect every lane-carrying owner shares
    # could answer. See `normalize_shared_progress_event`.
    "resolved_in_the_shared_dialect_without_an_owner",
    # Produced by the LANE (`executor_progress.infer_progress_event_type`), not
    # by this pure function: deciding that a reported end state has nothing
    # behind it needs the process status, the observable activity, the git
    # hashes, and WHERE the progress summary came from, none of which a
    # word-only normalizer ever sees. It answers for the summary's own `status`
    # as well as for the narrated word, because those are one claim in two
    # fields. It lives in this closed vocabulary anyway so a consumer branches
    # on one list rather than two.
    "self_reported_end_state_not_corroborated",
)

# Owner spellings folded onto one fanout owner. `_` is folded to `-` before the
# lookup, so the progress-lane spellings (`claude_code`, `omo_runtime`,
# `hermes_local`) arrive here already matching their hyphenated keys. The omo
# host CLIs collapse into one owner for the same reason the progress lane
# collapses them: the question is which lane narrated, not which binary was on
# PATH.
_OWNER_ALIASES: Final[dict[str, str]] = {
    "codex": "codex",
    "claude": "claude-code",
    "claude-code": "claude-code",
    "claude-code-cli": "claude-code",
    "omx-runtime": "omx-runtime",
    "omo-runtime": "omo-runtime",
    "pi": "omo-runtime",
    "senpi": "omo-runtime",
    "opencode": "omo-runtime",
    "omc-runtime": "omc-runtime",
    "generic": "generic",
    "hermes": "hermes",
    "hermes-local": "hermes",
}

# Owners that narrate progress this repo can read. Every other fanout owner --
# `omx-runtime`, `omc-runtime`, `generic` -- has no progress lane today and
# resolves to an honest, visible unmapped record. That is the required answer,
# not a gap to close later by guessing at their words.
OWNERS_WITH_PROGRESS_LANE: Final[tuple[str, ...]] = ("codex", "claude-code", "omo-runtime", "hermes")

_KNOWN_OWNERS: Final[frozenset[str]] = frozenset(EXECUTOR_PROFILES)


class OwnerEventMapping(NamedTuple):
    """One resolved dialect row: where a word goes, and what it carried on its own.

    `source_evidence_tier` is DERIVED from the source word by
    `source_event_evidence_tier`, never restated by the row, because a row that
    declares its own source tier can always declare one high enough to pass the
    anti-upgrade guard -- and then every shipped row passes by construction.
    """

    normalized_event: str
    source_evidence_tier: str


# What each SOURCE WORD claims on its own, before anything is mapped. Declared
# once per word and shared by every owner that speaks it, so a dialect row can
# choose only a TARGET; the left-hand side of the anti-upgrade comparison is
# never in the row's gift.
#
# A word missing from this table sits at the floor (`preparation`) and can
# therefore only map to `unmapped_source_event`. That is deliberate: an
# unclassified word carries no declared evidence, and refusing it is cheaper
# than inheriting whatever tier its target happened to sit at.
_SOURCE_EVENT_EVIDENCE_TIERS: Final[dict[str, str]] = {
    # preparation -- the workflow moved; nobody was dispatched, nothing ran.
    "workflow_started": "preparation",
    # dispatch -- an executor was handed the work.
    "executor_dispatched": "dispatch",
    "dispatch_to_executor": "dispatch",
    "system": "dispatch",
    # progress -- something was observed happening, and nothing ended.
    "repo_exploration": "progress",
    "running_no_diff_observed": "progress",
    "diff_started": "progress",
    "tests_started": "progress",
    "targeted_tests_started": "progress",
    "full_tests_started": "progress",
    "progress_observed": "progress",
    "reported_change_not_observed": "progress",
    "status_update": "progress",
    "bug_discovered": "progress",
    "root_cause_identified": "progress",
    "fix_strategy_selected": "progress",
    "files_area_chosen": "progress",
    # A commit or a changed file is evidence a diff exists, not verification.
    "file_changed": "progress",
    "commit_created": "progress",
    "pr_created": "progress",
    "pr_updated": "progress",
    "assistant": "progress",
    "user": "progress",
    "item.completed": "progress",
    # result_claimed -- the owner says the work ended. Its own word about
    # itself, not an observation of the process or of the working tree.
    "executor_completed": "result_claimed",
    "executor_blocked": "result_claimed",
    "executor_failed": "result_claimed",
    "executor_cancelled": "result_claimed",
    "run_cancelled": "result_claimed",
    "workflow_cancelled": "result_claimed",
    "workflow_completed": "result_claimed",
    "failure_discovered": "result_claimed",
    "blocker_encountered": "result_claimed",
    "turn.completed": "result_claimed",
    "result": "result_claimed",
    # verified -- the owner says a verification ran and reported an outcome.
    # The tier names WHICH KIND of evidence was observed, not whether the news
    # was good, so the failing spellings sit here beside the passing ones.
    "tests_passed": "verified",
    "tests_failed": "verified",
    "targeted_tests_passed": "verified",
    "targeted_tests_failed": "verified",
    "full_tests_passed": "verified",
    "full_tests_failed": "verified",
}

# The dialect every lane-carrying owner speaks, as `source word -> normalized
# event`: the chat/workflow progress vocabulary
# `context_safety._PROGRESS_EVENT_TYPES` registers and `codex_progress` emits as
# `latest_progress_event.event_type`, plus the executor-lane spellings the
# progress signal already carried.
#
# `workflow_started` is the concrete anti-upgrade case. It is a
# preparation-class word -- the workflow began, nobody has been dispatched --
# and the normalized vocabulary has no preparation-tier member, so the honest
# answer is that it has no home. Mapping it to `executor_dispatched` would read
# as "an executor is running" on every board that shows it.
#
# The targeted/full test distinction is real and is lost by the normalized name
# alone, which is what `lossy` records; the retained `source_event` recovers it.
_SHARED_DIALECT: Final[dict[str, str]] = {
    # Identity rows: an owner already speaking the normalized vocabulary.
    "executor_dispatched": "executor_dispatched",
    "repo_exploration": "repo_exploration",
    "running_no_diff_observed": "running_no_diff_observed",
    "diff_started": "diff_started",
    "tests_started": "tests_started",
    "tests_failed": "tests_failed",
    "tests_passed": "tests_passed",
    "executor_completed": "executor_completed",
    "executor_blocked": "executor_blocked",
    "executor_failed": "executor_failed",
    "executor_cancelled": "executor_cancelled",
    "reported_change_not_observed": "reported_change_not_observed",
    "progress_observed": "progress_observed",
    # Workflow vocabulary.
    "workflow_started": UNMAPPED_NORMALIZED_EVENT,
    "dispatch_to_executor": "executor_dispatched",
    "workflow_completed": "executor_completed",
    # Two owner spellings of the same end state. They translate here; whether
    # the lane ACCEPTS the translation still depends on corroboration, so a
    # host that narrates a cancellation it did not observe gets the same
    # `self_reported_end_state_not_corroborated` answer any other end-state
    # word gets.
    "run_cancelled": "executor_cancelled",
    "workflow_cancelled": "executor_cancelled",
    "status_update": "progress_observed",
    "bug_discovered": "progress_observed",
    "failure_discovered": "executor_failed",
    "root_cause_identified": "progress_observed",
    "fix_strategy_selected": "progress_observed",
    "files_area_chosen": "repo_exploration",
    "blocker_encountered": "executor_blocked",
    # Verification vocabulary.
    "targeted_tests_started": "tests_started",
    "targeted_tests_passed": "tests_passed",
    "targeted_tests_failed": "tests_failed",
    "full_tests_started": "tests_started",
    "full_tests_passed": "tests_passed",
    "full_tests_failed": "tests_failed",
    # Change vocabulary.
    "file_changed": "diff_started",
    "commit_created": "diff_started",
    # Review-lane words carry no executor-progress meaning beyond "something
    # happened", so they normalize down rather than sideways.
    "pr_created": "progress_observed",
    "pr_updated": "progress_observed",
}

# Owner-native stream words, on top of the shared dialect.
#
# Provenance, stated per owner because it differs: the codex row names are
# confirmed inside this repo (`codex_progress._RAW_RUNTIME_EVENT_TYPES` carries
# `turn.completed`, and `item.completed` is read by its event reader). The
# claude-code rows are the documented `--output-format stream-json` envelope
# types and are NOT confirmed from a stream captured in this repo; they are
# supported as documented, the same standard `unit_telemetry` applies to that
# owner's result object. `omo-runtime` has no structured stdout surface at all
# -- `unit_telemetry` reports `source="none"` for its pi/senpi/opencode hosts --
# so it adds no native words and speaks the shared dialect only. `hermes`
# narrates through the same workflow vocabulary.
_OWNER_DIALECT_DELTAS: Final[dict[str, dict[str, str]]] = {
    "codex": {
        "turn.completed": "executor_completed",
        "item.completed": "progress_observed",
    },
    "claude-code": {
        "system": "executor_dispatched",
        "assistant": "progress_observed",
        "user": "progress_observed",
        "result": "executor_completed",
    },
    "omo-runtime": {},
    "hermes": {},
}

# The highest evidence tier an owner's words can reach, whatever they say.
#
# `unit_telemetry._STRUCTURED_SOURCE_BY_OWNER` is this repo's telemetry
# contract for which owners emit a stream it can read, and it names `codex` and
# `claude-code` only: omo's pi/senpi/opencode hosts report `source="none"`. An
# omo `full_tests_passed` is therefore narration with nothing behind it, and
# granting it the verification tier would let an unreadable stream produce the
# strongest claim in the ladder. Capping it is the same refusal
# `_change_reported_but_not_observed` already makes about a self-reported edit
# against a clean tree.
#
# `hermes` is listed here rather than read from that table because it is not a
# spawned CLI at all: it never reaches `unit_telemetry`, and a `hermes_local`
# binding already requires explicit observed local execution evidence before it
# exists (`executor_progress.normalize_executor_profile`). Its absence from the
# telemetry table means "not a spawned stdout source", not "unreadable".
_OWNER_EVIDENCE_CEILING: Final[dict[str, str]] = {
    "codex": "verified",
    "claude-code": "verified",
    "hermes": "verified",
    "omo-runtime": "result_claimed",
}

# Bounds. A source event is an identifier-shaped word, not a log line; the caps
# exist so a pathological value costs a predictable amount of room in a record
# that a chat surface may render.
MAX_OWNER_CHARS: Final[int] = 80
MAX_SOURCE_EVENT_CHARS: Final[int] = 120
MAX_SOURCE_VERSION_CHARS: Final[int] = 80
MAX_CORRELATION_CHARS: Final[int] = 200


def source_event_evidence_tier(source_event: str) -> str:
    """What one SOURCE WORD claims on its own; the floor for a word nobody classified.

    Defined before the dialect tables are built because they are built FROM it:
    a row supplies a target and nothing else, so no row can hand itself a source
    tier high enough to survive the anti-upgrade guard.
    """
    return _SOURCE_EVENT_EVIDENCE_TIERS.get(str(source_event), _FLOOR_TIER)


def owner_evidence_ceiling(owner: str) -> str:
    """The highest tier this owner's stream can carry; the floor for an owner with no lane."""
    return _OWNER_EVIDENCE_CEILING.get(_normalized_owner(owner), _FLOOR_TIER)


def _owner_tables() -> dict[str, dict[str, OwnerEventMapping]]:
    tables: dict[str, dict[str, OwnerEventMapping]] = {}
    for owner in OWNERS_WITH_PROGRESS_LANE:
        targets = dict(_SHARED_DIALECT)
        targets.update(_OWNER_DIALECT_DELTAS.get(owner, {}))
        tables[owner] = {
            source_event: OwnerEventMapping(target, source_event_evidence_tier(source_event))
            for source_event, target in targets.items()
        }
    return tables


_MAPPINGS_BY_OWNER: Final[dict[str, dict[str, OwnerEventMapping]]] = _owner_tables()


def normalize_owner_progress_event(
    owner: str,
    source_event: str,
    *,
    source_version: str = "",
    correlation: str = "",
) -> dict[str, object]:
    """Return one owner progress event translated into the shared vocabulary.

    Pure and total: no I/O, no clock, no environment, no network, and no
    exception path. The record always carries the five fields the caller needs
    to audit the translation -- what was said (`source_event`), in which dialect
    version (`source_version`), about which run (`correlation`), what it became
    (`normalized_event`), and how much the translation can be trusted
    (`mapping_confidence`) -- plus the two tiers the anti-upgrade guard compared.

    `source_evidence_tier` is `preparation`, the floor, whenever nothing could
    be attributed to the source event. Claiming the weakest tier is the only
    safe answer to "how much evidence is this", because no normalized event can
    outrank it.
    """
    owner_label = _bounded_text(_normalized_owner(owner), MAX_OWNER_CHARS)
    event = _bounded_text(source_event, MAX_SOURCE_EVENT_CHARS)
    normalized, source_tier, confidence, note = _resolve(owner_label, event)
    return {
        "schema_version": OWNER_PROGRESS_NORMALIZATION_SCHEMA_VERSION,
        "owner": owner_label,
        "owner_supported": owner_label in _MAPPINGS_BY_OWNER,
        "source_event": event,
        "source_version": _bounded_text(source_version, MAX_SOURCE_VERSION_CHARS),
        "correlation": _bounded_text(correlation, MAX_CORRELATION_CHARS),
        "normalized_event": normalized,
        "source_evidence_tier": source_tier,
        "normalized_evidence_tier": progress_evidence_tier(normalized),
        "mapping_confidence": confidence,
        "mapping_note": note,
        "claim_boundary": OWNER_PROGRESS_NORMALIZATION_CLAIM_BOUNDARY,
    }


def normalized_owner_progress_event(owner: str, source_event: str) -> str:
    """Just the normalized event name, for callers that already own the context."""
    return str(normalize_owner_progress_event(owner, source_event)["normalized_event"])


def normalize_shared_progress_event(
    source_event: str,
    *,
    source_version: str = "",
    correlation: str = "",
) -> dict[str, object]:
    """Normalize one word when NO owner is named, against the shared dialect only.

    Every lane-carrying owner speaks `_SHARED_DIALECT` by construction, so a
    shared-dialect word means the same thing whichever of them said it:
    resolving it without an owner is not a guess. Owner-native words
    (`turn.completed`, `result`, `system`) stay unmapped, because those are
    exactly the ones that DO differ by owner.

    The ceiling is the strictest any lane owner carries, so an unnamed owner can
    never buy a claim the weakest readable stream could not support. Re-inferring
    over a stored signal whose `executor_profile` is missing therefore recovers
    the word instead of discarding it, without recovering more than it can hold.
    """
    event = _bounded_text(source_event, MAX_SOURCE_EVENT_CHARS)
    normalized, source_tier, confidence, note = _resolve_shared(event)
    return {
        "schema_version": OWNER_PROGRESS_NORMALIZATION_SCHEMA_VERSION,
        "owner": "",
        "owner_supported": False,
        "source_event": event,
        "source_version": _bounded_text(source_version, MAX_SOURCE_VERSION_CHARS),
        "correlation": _bounded_text(correlation, MAX_CORRELATION_CHARS),
        "normalized_event": normalized,
        "source_evidence_tier": source_tier,
        "normalized_evidence_tier": progress_evidence_tier(normalized),
        "mapping_confidence": confidence,
        "mapping_note": note,
        "claim_boundary": OWNER_PROGRESS_NORMALIZATION_CLAIM_BOUNDARY,
    }


def shared_dialect_source_events() -> tuple[str, ...]:
    """Every source word every lane-carrying owner speaks, sorted.

    Exists so a containment gate can prove the chat/workflow vocabulary in
    `context_safety` is a subset of it. A value added there and not here makes
    every executor signal carrying that value normalize to
    `unmapped_source_event`, silently.
    """
    return tuple(sorted(_SHARED_DIALECT))


def progress_evidence_tier(normalized_event: str) -> str:
    """The evidence tier a normalized event sits at; the floor when unrecognized."""
    return _TIER_BY_NORMALIZED_EVENT.get(str(normalized_event), _FLOOR_TIER)


def progress_evidence_rank(tier: str) -> int:
    """Rank of a tier, or -1 for an unrecognized one so it can never outrank a real tier."""
    try:
        return PROGRESS_EVIDENCE_TIERS.index(str(tier))
    except ValueError:
        return -1


def normalization_raises_evidence(*, source_evidence_tier: str, normalized_event: str) -> bool:
    """True when normalizing would claim more evidence than the source event carried.

    Deliberately independent of any binding, signal, or record so it can be
    tested on its own. Its spirit is `runtime.claims.allowed_runtime_claims`,
    which stops at the first unsatisfied rung rather than skipping to the top.
    """
    return progress_evidence_rank(progress_evidence_tier(normalized_event)) > progress_evidence_rank(
        source_evidence_tier
    )


def owner_progress_mapping_table(owner: str) -> dict[str, OwnerEventMapping]:
    """A copy of one owner's dialect table; empty for an owner with no progress lane."""
    return dict(_MAPPINGS_BY_OWNER.get(_normalized_owner(owner), {}))


def normalization_owners() -> tuple[str, ...]:
    """Every fanout owner a normalization question can be asked about."""
    return tuple(EXECUTOR_PROFILES)


def is_known_owner(owner: str) -> bool:
    """True when the name is a fanout owner, whether or not it has a progress lane."""
    return _normalized_owner(owner) in _KNOWN_OWNERS


def normalization_row_raises_evidence(*, source_event: str, normalized_event: str) -> bool:
    """True when one `source word -> normalized event` row would claim more than the word carries.

    The row supplies only the target; the source tier comes from
    `source_event_evidence_tier`, so a row cannot pass this check by declaring a
    convenient tier for itself. A word this repo has not classified sits at the
    floor and can therefore only map to `unmapped_source_event`.
    """
    return normalization_raises_evidence(
        source_evidence_tier=source_event_evidence_tier(source_event),
        normalized_event=normalized_event,
    )


def normalization_table_violations(rows: dict[str, str] | None = None) -> list[str]:
    """Rows whose normalized event would outrank the evidence their SOURCE WORD carries.

    Called with no argument it scans every shipped dialect and MUST return [].
    The runtime resolver refuses such a row anyway, so this is the gate that
    keeps the resolver from having to: a row that silently degrades to
    `unmapped_source_event` in production is a table bug, not a feature.

    A caller may pass its own `{source_event: normalized_event}` rows to check a
    table before shipping it. That argument is also how this guard is proven
    capable of failing at all -- every shipped row passes, so a check that only
    ever looked at shipped rows could not tell "no violations" from "cannot
    detect violations".

    The per-owner evidence CEILING is deliberately not applied here. A capped
    row (an omo `full_tests_passed`) is refused at runtime on purpose; it is a
    correct row about an owner whose stream cannot carry it, not a table bug.
    """
    if rows is not None:
        return [
            f"{source_event}->{normalized_event}"
            for source_event, normalized_event in sorted(rows.items())
            if normalization_row_raises_evidence(source_event=source_event, normalized_event=normalized_event)
        ]
    violations: list[str] = []
    for owner in sorted(_MAPPINGS_BY_OWNER):
        for source_event, mapping in sorted(_MAPPINGS_BY_OWNER[owner].items()):
            if normalization_row_raises_evidence(
                source_event=source_event,
                normalized_event=mapping.normalized_event,
            ):
                violations.append(f"{owner}:{source_event}->{mapping.normalized_event}")
    return violations


def _capped_source_tier(source_evidence_tier: str, ceiling: str) -> str:
    """The weaker of what the word claims and what the owner's stream can carry."""
    if progress_evidence_rank(ceiling) < progress_evidence_rank(source_evidence_tier):
        return ceiling
    return source_evidence_tier


def _refused(mapping: OwnerEventMapping, capped_tier: str) -> tuple[str, str, str, str] | None:
    """The refusal this row earns, or None when it may be emitted.

    Two different failures share one outcome and must not share one note: a row
    whose target outranks its own word is a TABLE bug, while a row refused only
    because the owner's stream cannot carry the tier is a correct row about an
    owner this repo cannot read.
    """
    if not normalization_raises_evidence(
        source_evidence_tier=capped_tier,
        normalized_event=mapping.normalized_event,
    ):
        return None
    note = (
        "mapping_would_raise_the_evidence_tier"
        if normalization_raises_evidence(
            source_evidence_tier=mapping.source_evidence_tier,
            normalized_event=mapping.normalized_event,
        )
        else "owner_stream_cannot_carry_the_source_evidence_tier"
    )
    return UNMAPPED_NORMALIZED_EVENT, capped_tier, "unmapped", note


def _resolve(owner_label: str, source_event: str) -> tuple[str, str, str, str]:
    if not source_event:
        return UNMAPPED_NORMALIZED_EVENT, _FLOOR_TIER, "absent", "no_source_event_reported"
    table = _MAPPINGS_BY_OWNER.get(owner_label)
    if table is None:
        # A known fanout owner without a lane and a name this repo has never
        # heard of both end unmapped, but they need different fixes -- one is a
        # missing dialect, the other is a typo or a new owner -- so the note
        # keeps them apart.
        note = "owner_has_no_progress_lane" if owner_label in _KNOWN_OWNERS else "owner_is_not_a_known_fanout_owner"
        return UNMAPPED_NORMALIZED_EVENT, _FLOOR_TIER, "unmapped", note
    mapping = table.get(source_event)
    if mapping is None:
        return UNMAPPED_NORMALIZED_EVENT, _FLOOR_TIER, "unmapped", "source_event_not_in_owner_dialect"
    capped = _capped_source_tier(mapping.source_evidence_tier, owner_evidence_ceiling(owner_label))
    refusal = _refused(mapping, capped)
    if refusal is not None:
        return refusal
    confidence, note = _confidence_and_note(source_event, mapping, table)
    return mapping.normalized_event, capped, confidence, note


def _resolve_shared(source_event: str) -> tuple[str, str, str, str]:
    if not source_event:
        return UNMAPPED_NORMALIZED_EVENT, _FLOOR_TIER, "absent", "no_source_event_reported"
    target = _SHARED_DIALECT.get(source_event)
    if target is None:
        return UNMAPPED_NORMALIZED_EVENT, _FLOOR_TIER, "unmapped", "source_event_not_in_owner_dialect"
    mapping = OwnerEventMapping(target, source_event_evidence_tier(source_event))
    capped = _capped_source_tier(mapping.source_evidence_tier, _strictest_lane_ceiling())
    refusal = _refused(mapping, capped)
    if refusal is not None:
        return refusal
    if target == UNMAPPED_NORMALIZED_EVENT:
        return target, capped, "unmapped", "no_normalized_event_at_source_evidence_tier"
    return target, capped, "aliased", "resolved_in_the_shared_dialect_without_an_owner"


def _strictest_lane_ceiling() -> str:
    """The weakest ceiling any lane-carrying owner has.

    What an unnamed owner is allowed, because any of them could have been the
    one speaking and the answer has to hold for all of them.
    """
    return min(
        (owner_evidence_ceiling(owner) for owner in OWNERS_WITH_PROGRESS_LANE),
        key=progress_evidence_rank,
    )


def _confidence_and_note(
    source_event: str,
    mapping: OwnerEventMapping,
    table: dict[str, OwnerEventMapping],
) -> tuple[str, str]:
    """Derive the confidence from the table instead of hand-declaring it.

    A declared confidence drifts the moment a row is added; a derived one
    cannot. `lossy` means several of this owner's words share one normalized
    word, so the normalized name alone no longer identifies which was said --
    the retained `source_event` is what recovers it.
    """
    if mapping.normalized_event == UNMAPPED_NORMALIZED_EVENT:
        return "unmapped", "no_normalized_event_at_source_evidence_tier"
    if source_event == mapping.normalized_event:
        return "exact", "source_event_matches_normalized_vocabulary"
    sharing = sum(1 for row in table.values() if row.normalized_event == mapping.normalized_event)
    if sharing > 1:
        return "lossy", "owner_dialect_collapses_onto_one_normalized_event"
    return "aliased", "owner_dialect_alias"


def _normalized_owner(value: Any) -> str:
    normalized = str(value).strip().casefold().replace("_", "-")
    return _OWNER_ALIASES.get(normalized, normalized)


def _bounded_text(value: Any, limit: int) -> str:
    """Bounded, single-line, printable text -- the raw value, not a rewrite of it.

    Unprintable characters (including newlines and tabs) are dropped so a
    record can never carry a multi-line blob into a chat surface; spaces
    survive, so a value that was already a word survives byte-for-byte. An
    over-long value is truncated with a visible marker rather than rejected:
    rejecting it would delete the visibility this module exists to provide.
    """
    text = "".join(char for char in str(value).strip() if char.isprintable())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."

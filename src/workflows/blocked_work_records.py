"""Append-only records for work that was blocked, and for the decisions around it (issues #808, #806).

Why this exists at all
----------------------

A preflight denial used to leave nothing behind. `coding.coding_delegation`
collapses a denied gate through `denied_executor_selection()` with an empty
isolation plan, and `commands.coding` then computes a `runtime_skip_reason` and
returns `payload["runtime"] = {"recorded": False, ...}`. No run is created, no
`coding_delegation.json` is written, and no journal event is appended -- so
"why was this blocked?" had no answer once the turn ended. That is worse than
rendering a block as a skipped success, because a skipped success can at least
be contradicted later. This store is the durable answer.

Why this is its own record family and not a field group
-------------------------------------------------------

The repo refused a new family twice (#811, #818) and accepted one once (#807),
on a rule worth restating: a family joins on run id, and a join is where an
artifact and its metadata desynchronize, so a field group on the record that
already exists is the default. A separate family has to earn it.

This one earns it on every dimension #807 used, and on one more:

- Different creation time. The block happens *before* a delegation exists.
- Different actor. The evaluator or the gate decides, not the router.
- Its own lifetime. #806's whole acceptance criterion is "explainable after the
  original turn"; the delegation's lifetime is the turn.
- It must survive a rebuild under a moved safety-profile revision as a second
  linked record rather than an overwrite, so the history of a decision that was
  re-made is a chain and not a replacement.

And decisively: on a preflight denial there is no host record to be a field
group *on*. `run_id` is empty on exactly those records, which is not a defect
to be fixed but the shape of the problem.

Nothing here can name what was blocked
--------------------------------------

#808 AC1 is that raw prompts, tokens, files, and payloads cannot serialize into
a record. That is enforced structurally rather than by scrubbing:

- The key set is closed, and `RAW_OR_HIDDEN_KEYS` is refused by name first so
  the error says *why* rather than "unsupported key".
- There is no free-text field. Not one. Every string on a record is either an
  opaque reference or a member of a closed vocabulary, so there is nowhere for
  a sentence to go, let alone a transcript.
- Reference fields additionally refuse anything path-shaped. The shared
  `require_opaque_metadata_ref` permits `/` (approval receipts store a scope
  path on purpose), which would let `src/auth/token.py` ride in as an
  identifier. Here a file name is never the answer to any question the record
  asks, so `_PATH_SHAPED` refuses it and AC1 holds by construction.

The fingerprint hashes the input class, never the input
-------------------------------------------------------

A truncated sha of a filename is dictionary-reversible: anyone holding the
repository can hash every path and read the digest straight back. It would pass
"we stored a hash" and fail "hashes are non-reversible" in spirit, which is the
criterion that matters.

So `request_fingerprint` digests the *multiset of classes and closed-vocabulary
values present* in the request, and no value that a caller chose. The class
labels are the ones `quality.safety_preflight` already assigned -- `FIELD_CLASSES`
is imported, not restated -- because two answers to "what class is this field"
is the defect that guard tables exist to prevent. `REQUEST_CLASS_LABELS` is
derived from the preflight's own vocabularies for the same reason, so a class
added there cannot go unnamed here.

The result: two requests with the same class shape and different values share a
fingerprint (which is what makes it useful for grouping repeat blocks), a
different class shape gives a different fingerprint, and no amount of
brute-force recovers a path, because no path byte was ever an input.

Decision history is a projection, not a second store
----------------------------------------------------

#806 is answered by `project_decision_history` over these records. The tree's
precedent is `project_external_effects` and `project_run_lifecycle`, both
derived and never stored; and a second store over one decision sequence is a
fork by construction, which `supersede_chain_errors` already rejects.

The history records **allows** as well as blocks, with their own outcome and
lifecycle transition. That is not bookkeeping: it is what turns "an allow is
never rendered as attempted or completed" into an enforceable invariant over
`OUTCOME_WORK_CLAIMS` instead of an accidental absence of rows.

Enforcing versus observing
--------------------------

The Hermes plugin host does honor a `pre_tool_call` deny channel
(`hermes_cli/plugins.py`, `_get_pre_tool_call_directive_details`: a returned
`{"action": "block", "message": ...}` vetoes the call and the message becomes
the tool result), and OMH's toolcall rules use it. That does not move
`plugin_hook_observation` into the enforcing set: returning a block directive
is not evidence the host received, honored, or surfaced it — hook invocation
is host-owned and unobserved from here. A hook can mint a record *about* a
block, and cannot prove one happened. `DECISION_SOURCES` therefore stays split
into `ENFORCING_SOURCES` and `OBSERVING_SOURCES`, an observing source is
pinned to `declared_not_enforced` with a stated blocker, and
`build_blocked_work_record` refuses the combination that would lie.

What actually produces and reads these records today
----------------------------------------------------

Stated because the vocabularies above are wider than the wiring, and a reader
who takes `DECISION_SOURCES` for a coverage claim would be wrong:

- **One producer.** `commands.coding.cmd_coding_delegate` mints one record per
  `omh coding delegate` build, from the one action-gate verdict, through
  `decision_from_action_gate`. That reaches two sources -- `safety_preflight`
  and `action_gate` -- and two reason domains.
- **`approval_gate` and `runtime_claim_gate` mint nothing yet.** They are
  declared here because the reason domains they join (`approval_refusal`,
  `runtime_claim_block`) are the vocabularies a record from those gates would
  have to cite, and a record family whose sources are invented later is a
  migration. Until those gates call in, no record carries either source, and
  `decision_history` therefore covers the delegation lane and nothing else.
- **Every observing source mints nothing yet.** No plugin hook, executor, or
  operator surface calls in; `OBSERVING_SOURCES` is the shape a report from one
  would have to take, not a lane that exists.
- **One read surface.** `runtime.artifacts.export_runtime` carries
  `decision_history` into `omh runtime export`, and
  `validate_blocked_work_record_store` carries the store's integrity into
  `omh runtime validate`. There is no dedicated `omh` command for the history.

Store mechanics
---------------

All of it is `system.append_only_store`, shared with the two receipt families:
the torn-tail-safe binary append under a real OS lock on both platforms, the
opaque-reference guards, the supersede-chain walk, the digest handles, and the
best-effort mint-failure sidecar. This module adds no store mechanics of its
own; it passes its own key names to the shared walk so its records are not
described as receipts they are not.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from ..quality.safety_preflight import (
    ACCESS_INTENTS,
    DATA_CLASSES,
    EVIDENCE_CLAIMS,
    FIELD_CLASS_OPAQUE_REF,
    FIELD_CLASS_PATH,
    FIELD_CLASS_VOCABULARY,
    FIELD_CLASSES,
    MESSAGE_CONTEXT_MODES,
    REMOTE_TARGET_KINDS,
    REQUEST_FIELDS,
)
from ..system.append_only_store import (
    RAW_OR_HIDDEN_KEYS,
    append_sidecar_line,
    append_store_line,
    closed_vocabulary_value,
    digest_ref,
    latest_record_in,
    mint_record_id,
    opaque_ref,
    record_fingerprint,
    redacted_ref,
    reference_errors,
    store_errors,
)
from ..system.local_store import file_lock, read_jsonl_objects, utc_now
from ..system.metadata_safety import is_sensitive_metadata_text
from ..system.paths import OmhPaths


BLOCKED_WORK_RECORD_SCHEMA_VERSION: Final[str] = "blocked_work_record/v1"
BLOCKED_WORK_RECORD_STORE_VALIDATION_SCHEMA_VERSION: Final[str] = "blocked_work_record_store_validation/v1"
BLOCKED_WORK_MINT_RESULT_SCHEMA_VERSION: Final[str] = "blocked_work_mint_result/v1"
BLOCKED_WORK_MINT_FAILURE_SCHEMA_VERSION: Final[str] = "blocked_work_mint_failure/v1"
DECISION_HISTORY_SCHEMA_VERSION: Final[str] = "decision_history/v1"

BLOCKED_WORK_RECORD_STORE_NAME: Final[str] = "blocked_work_records.jsonl"
BLOCKED_WORK_MINT_FAILURE_STORE_NAME: Final[str] = "blocked_work_mint_failures.jsonl"

RECORD_PRIVACY: Final[str] = "metadata_only"

# Stated on every record and echoed on every history projection. The claim a
# blocked-work record makes is deliberately small: a decision was reached. It is
# never evidence about what the blocked work would have done, and on an
# observing source it is not even evidence that OMH is what stopped it.
CLAIM_BOUNDARY: Final[str] = (
    "A blocked work record is one recorded decision about one request shape: what was decided, by which source, "
    "under which reason code, and what recovery it allows. It carries the class of the request and never its "
    "content. It is not dispatch, execution, or evidence of what the work would have done, and from an observing "
    "source it is not evidence that OMH enforced anything."
)

# Sources that can actually stop work, and sources that can only watch it stop.
#
# The split is not stylistic. The host does honor a `pre_tool_call` block
# directive (see the module docstring), but returning one is a request whose
# receipt OMH cannot observe -- so a record minted from a hook remains a
# report, never proof OMH stopped anything. Collapsing the two would ship an
# outcome that implies OMH verified a block it has no way to verify.
ENFORCING_SOURCES: Final[tuple[str, ...]] = (
    "safety_preflight",
    "action_gate",
    "approval_gate",
    "runtime_claim_gate",
)
OBSERVING_SOURCES: Final[tuple[str, ...]] = (
    "plugin_hook_observation",
    "executor_report",
    "operator_report",
)
DECISION_SOURCES: Final[tuple[str, ...]] = ENFORCING_SOURCES + OBSERVING_SOURCES

ENFORCEMENT_MODES: Final[tuple[str, ...]] = ("enforced", "declared_not_enforced")
SOURCE_ENFORCEMENT: Final[dict[str, str]] = {
    **{source: "enforced" for source in ENFORCING_SOURCES},
    **{source: "declared_not_enforced" for source in OBSERVING_SOURCES},
}

# Why an observing source cannot enforce, as a closed vocabulary rather than a
# sentence: the record has no free text, and a blocker that renders is a blocker
# an operator can act on.
ENFORCEMENT_BLOCKERS: Final[tuple[str, ...]] = (
    "hermes_plugin_hooks_have_no_deny_channel",
    "executor_runs_outside_omh",
    "operator_report_is_not_a_control_point",
)
SOURCE_ENFORCEMENT_BLOCKERS: Final[dict[str, str]] = {
    "plugin_hook_observation": "hermes_plugin_hooks_have_no_deny_channel",
    "executor_report": "executor_runs_outside_omh",
    "operator_report": "operator_report_is_not_a_control_point",
}

# The five states #808 AC2 requires to stay apart, plus the allow #806 AC3 needs
# on record. Each is a different claim about the same request shape:
#
#   allowed   -- the gate said yes. Nothing has run. This is permission, and the
#                reason it is stored is that "an allow is never rendered as
#                attempted or completed" is only enforceable if allows exist.
#   blocked   -- a gate stopped the work before anything ran. Recoverable: every
#                blocked record carries a recovery action.
#   cancelled -- work that had already started was stopped deliberately. The
#                difference from `blocked` is when, and by whom.
#   failed    -- work ran and did not succeed.
#   completed -- work ran and succeeded.
DECISION_OUTCOMES: Final[tuple[str, ...]] = ("allowed", "blocked", "cancelled", "completed", "failed")

# Where the outcome leaves the work. `paused` is the state `blocked` maps to and
# nothing else does: a block is not terminal, because a recovery action exists.
# The nearest success-shaped state in the tree is a gate's `not_required`, and a
# block must never fold into it -- `not_required` says no evidence is owed,
# while `blocked` says work is owed and cannot proceed yet.
LIFECYCLE_STATES: Final[tuple[str, ...]] = ("open", "paused", "terminal")
OUTCOME_LIFECYCLE: Final[dict[str, str]] = {
    "allowed": "open",
    "blocked": "paused",
    "cancelled": "terminal",
    "completed": "terminal",
    "failed": "terminal",
}

# What each outcome permits a renderer to claim about the work itself. This
# table is the enforceable form of #806 AC3: `allowed` maps to `not_attempted`,
# so no projection can render an allow as attempted or completed without
# contradicting a constant that `tests/test_blocked_work_records.py` iterates.
WORK_CLAIMS: Final[tuple[str, ...]] = ("not_attempted", "attempted_not_completed", "completed")
OUTCOME_WORK_CLAIMS: Final[dict[str, str]] = {
    # Permission is not an attempt. This is the row #806 AC3 is about.
    "allowed": "not_attempted",
    # A gate stopped it before anything ran, which is what separates it from
    # `cancelled`.
    "blocked": "not_attempted",
    "cancelled": "attempted_not_completed",
    "completed": "completed",
    "failed": "attempted_not_completed",
}
# The only outcome a success-shaped render may be built from. Named so the
# guard reads as the rule rather than as an equality check on a string.
SUCCESS_OUTCOMES: Final[tuple[str, ...]] = ("completed",)

# Which existing explanation vocabulary a reason code belongs to. There are
# already four in the tree -- `RUNTIME_CLAIM_BLOCK_REASONS`, `REFUSAL_REASONS`,
# `_CORRECTIONS`, and `EXCLUSION_REASON_CODES` -- and a fifth would be a fifth
# answer to "why". A record therefore names the domain and the code, and the
# prose is joined at read time from whichever module already owns it.
REASON_DOMAIN_SAFETY_PREFLIGHT: Final[str] = "safety_preflight_correction"
REASON_DOMAIN_ACTION_GATE: Final[str] = "action_gate_exclusion"
REASON_DOMAIN_APPROVAL: Final[str] = "approval_refusal"
REASON_DOMAIN_RUNTIME_CLAIM: Final[str] = "runtime_claim_block"
REASON_DOMAINS: Final[tuple[str, ...]] = (
    REASON_DOMAIN_ACTION_GATE,
    REASON_DOMAIN_APPROVAL,
    REASON_DOMAIN_RUNTIME_CLAIM,
    REASON_DOMAIN_SAFETY_PREFLIGHT,
)

# What an operator can do about it. A closed id vocabulary keyed off the reason
# code, so localized copy is a lookup per locale rather than a translated
# `correction` string: `safety_preflight._CORRECTIONS` is deliberately
# constant-only and interpolation-free, and translating one would turn a
# constant into a formatted string built from caller values.
RECOVERY_ACTIONS: Final[tuple[str, ...]] = (
    "declare_missing_field",
    "remove_prohibited_content",
    "narrow_declared_scope",
    "request_approval",
    "record_observed_evidence",
    "choose_executor",
    "no_recovery_available",
)
# The recovery a decision allows when nothing was blocked. An allow is not a
# recovery, so it names the one id that promises nothing.
ALLOW_RECOVERY_ACTION: Final[str] = "no_recovery_available"

BLOCKED_WORK_RECORD_KEYS: Final[tuple[str, ...]] = (
    "claim_boundary",
    "decided_at",
    "decision_id",
    "enforcement",
    "enforcement_blocker",
    "lifecycle_state",
    "outcome",
    "owner",
    "privacy",
    "reason_code",
    "reason_domain",
    "recovery_action",
    "record_id",
    "request_class_shape",
    "request_fingerprint",
    "run_id",
    "safety_profile_revision",
    "schema_version",
    "source",
    "supersedes_record_ref",
)

# The three keys whose value is a module constant rather than data. Everything
# else is rendered, and `compact_blocked_work_record` must cover all of it -- a
# key in the tuple and missing from the compactor is a field that is stored and
# never seen, which has cost this repo twice.
BLOCKED_WORK_RECORD_CONSTANT_KEYS: Final[tuple[str, ...]] = ("claim_boundary", "privacy", "schema_version")

# The four field classes, in the sibling stores' layout. Every string field on a
# record belongs to exactly one of them, and the union is pinned by
# `tests/test_blocked_work_records.py` so a new field cannot arrive without a
# class.
#
# Identifiers that must be present, through the opaque-reference guard plus the
# path-shape refusal below.
_REQUIRED_RECORD_REFS: Final[tuple[str, ...]] = (
    "decided_at",
    "decision_id",
    "owner",
    "record_id",
    "request_fingerprint",
    "safety_profile_revision",
)
# Identifiers that are legitimately absent. `run_id` is empty on exactly the
# records this family exists for: a preflight denial happens before a run
# exists, and inventing one would be the join #811 and #818 were refused over.
# The link is empty on the first decision about a request shape and only then.
_OPTIONAL_RECORD_REFS: Final[tuple[str, ...]] = ("run_id", "supersedes_record_ref")
# Closed vocabularies, checked by membership everywhere including at render.
# `reason_code` is absent here on purpose: it is closed *given* the domain, so
# it is checked against `reason_codes_for_domain` instead of one flat tuple.
_RECORD_VOCABULARIES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("enforcement", ENFORCEMENT_MODES),
    ("lifecycle_state", LIFECYCLE_STATES),
    ("outcome", DECISION_OUTCOMES),
    ("reason_domain", REASON_DOMAINS),
    ("recovery_action", RECOVERY_ACTIONS),
    ("source", DECISION_SOURCES),
)
# Closed vocabularies that may also be empty, which is a state and not a value.
_OPTIONAL_RECORD_VOCABULARIES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("enforcement_blocker", ENFORCEMENT_BLOCKERS),
)
# The one list field. Its members are closed-vocabulary class labels, never
# caller text, which is why this family has a list at all and still has no free
# text.
_RECORD_LIST_FIELDS: Final[tuple[str, ...]] = ("request_class_shape",)

# Every string field, which is every key that is not the one list. There is
# deliberately no free-text member: a summary line would be one more place for a
# prompt to arrive, and a decision needs no prose to be citable.
_RECORD_STRING_FIELDS: Final[tuple[str, ...]] = tuple(
    key for key in BLOCKED_WORK_RECORD_KEYS if key not in _RECORD_LIST_FIELDS
)

# What identifies *which decision* a record is about. The stamp, the record id,
# and the supersede link are excluded: re-reporting the same decision must not
# mint a second record just because the clock moved.
_DECISION_IDENTITY_KEYS: Final[tuple[str, ...]] = (
    "decision_id",
    "outcome",
    "reason_code",
    "reason_domain",
    "request_fingerprint",
    "run_id",
    "safety_profile_revision",
    "source",
)

MAX_CLASS_SHAPE_ENTRIES: Final[int] = 64

# What a record cites when the profile revision behind a decision cannot be
# read. A required field with no honest value is the shape that makes readers
# invent one, so this names the absence instead of leaving it empty.
UNKNOWN_REVISION: Final[str] = "revision-unknown"

# The store label every error line and every reference fault is reported under.
_LABEL: Final[str] = "blocked_work_record"

# A reference on this record never names a file. `require_opaque_metadata_ref`
# permits `/` because approval receipts store a workspace scope path on purpose;
# here a path is exactly what must not serialize, so it is refused separately
# rather than by loosening a guard two other families depend on.
_PATH_SHAPED: Final[re.Pattern[str]] = re.compile(r"[/\\]")


class BlockedWorkRecordError(ValueError):
    """Raised when a decision cannot become a blocked work record."""


# ---------------------------------------------------------------------------
# Request class shape and fingerprint
# ---------------------------------------------------------------------------

# Every label a class shape may contain, derived from the preflight's own
# vocabularies rather than restated. Deriving it is what stops a data class or
# an access intent added there from becoming an unnamed label here.
REQUEST_CLASS_LABELS: Final[tuple[str, ...]] = tuple(
    sorted(
        [f"field_class:{name}" for name in (FIELD_CLASS_OPAQUE_REF, FIELD_CLASS_PATH, FIELD_CLASS_VOCABULARY)]
        + [f"data_class:{value}" for value in DATA_CLASSES]
        + [f"access_intent:{value}" for value in ACCESS_INTENTS]
        + [f"remote_target_kind:{value}" for value in REMOTE_TARGET_KINDS]
        + [f"evidence_claim:{value}" for value in EVIDENCE_CLAIMS]
        + [f"message_context_mode:{value}" for value in MESSAGE_CONTEXT_MODES]
        + ["raw_content:included", "raw_content:excluded"]
    )
)

# Which closed-vocabulary request fields contribute their *values* to the shape.
# These are safe to carry verbatim precisely because they are closed: the value
# is a label the profile already publishes, not something a caller authored.
_VOCABULARY_VALUE_FIELDS: Final[tuple[tuple[str, str, tuple[str, ...]], ...]] = (
    ("data_classes", "data_class", DATA_CLASSES),
    ("access_intents", "access_intent", ACCESS_INTENTS),
    ("evidence_claims", "evidence_claim", EVIDENCE_CLAIMS),
)

# The three request fields read by name rather than through `REQUEST_FIELDS`,
# named as constants so `REQUEST_FIELDS_READ` below can be pinned against the
# preflight's own tuple. A field renamed there and left as a literal here would
# silently stop contributing to the shape, which changes every fingerprint
# without failing anything.
_REMOTE_TARGETS_FIELD: Final[str] = "remote_targets"
_MESSAGE_CONTEXT_MODE_FIELD: Final[str] = "message_context_mode"
_RAW_CONTENT_FIELD: Final[str] = "raw_content_included"
# The nested key on a destination entry, owned by `DESTINATION_FIELD_CLASSES`.
_DESTINATION_KIND_KEY: Final[str] = "kind"

# Every request field this module reads by name. Pinned against `REQUEST_FIELDS`
# by `tests/test_blocked_work_records.py`.
REQUEST_FIELDS_READ: Final[tuple[str, ...]] = tuple(
    sorted(
        {field for field, _, _ in _VOCABULARY_VALUE_FIELDS}
        | {_REMOTE_TARGETS_FIELD, _MESSAGE_CONTEXT_MODE_FIELD, _RAW_CONTENT_FIELD}
    )
)


def request_class_shape(request: Mapping[str, object] | None) -> list[str]:
    """The multiset of classes and closed-vocabulary values present in a request.

    This is the only thing about a request that reaches the store. A caller's
    path, owner string, or destination reference contributes its *class* and its
    presence, never a byte of itself, which is what makes the fingerprint built
    from it non-reversible rather than merely hashed.

    The class of each field is read from `safety_preflight.FIELD_CLASSES`, with
    the same `opaque_ref` default that module documents for an unclassified
    string. Re-deriving it here would be a second answer to "what class is this
    field", and the two would drift.

    A declared-empty list contributes no occurrences. It used to contribute one,
    through a `max(1, ...)` floor, so a request that declared `target_paths: []`
    shipped a record claiming one workspace path it did not name. Zero values of
    a class is zero occurrences of it, and a declared-empty list is therefore
    indistinguishable from an absent field in the shape -- which is correct,
    because both carried nothing of that class.

    Sorted, so two requests that differ only in key order share a shape.
    """
    if not isinstance(request, Mapping):
        return []
    labels: list[str] = []
    for field in REQUEST_FIELDS:
        if field not in request:
            continue
        value = request[field]
        field_class = FIELD_CLASSES.get(field, FIELD_CLASS_OPAQUE_REF)
        labels.extend([f"field_class:{field_class}"] * _occurrences(value))
    for field, prefix, vocabulary in _VOCABULARY_VALUE_FIELDS:
        for value in _string_members(request.get(field)):
            if value in vocabulary:
                labels.append(f"{prefix}:{value}")
    for entry in _destination_entries(request.get(_REMOTE_TARGETS_FIELD)):
        kind = str(entry.get(_DESTINATION_KIND_KEY, ""))
        if kind in REMOTE_TARGET_KINDS:
            labels.append(f"remote_target_kind:{kind}")
    mode = str(request.get(_MESSAGE_CONTEXT_MODE_FIELD, ""))
    if mode in MESSAGE_CONTEXT_MODES:
        labels.append(f"message_context_mode:{mode}")
    if _RAW_CONTENT_FIELD in request:
        labels.append("raw_content:included" if request.get(_RAW_CONTENT_FIELD) else "raw_content:excluded")
    return _bounded_class_shape(labels)


def _bounded_class_shape(labels: list[str]) -> list[str]:
    """The shape inside its budget, with every distinct label still present.

    The budget used to be applied as `sorted(labels)[:MAX]`, which truncates by
    alphabet. On a request with more than `MAX_CLASS_SHAPE_ENTRIES` field
    occurrences that dropped whole labels from the tail of the alphabet --
    `raw_content:included` and `message_context_mode:full` among them -- so a
    request carrying raw content and one that excluded it collapsed onto a
    single fingerprint. A fingerprint that merges those two is worse than no
    fingerprint, because it is consulted to group repeat blocks.

    Presence is therefore never truncated: every distinct label survives, and
    only the repeat counts are trimmed, round-robin over the labels in sorted
    order so no one field's occurrences can crowd out another's. The vocabulary
    is closed and small (`REQUEST_CLASS_LABELS`), so the distinct set fits the
    budget by construction; the guard below is what makes that a checked fact
    rather than an assumption about a vocabulary someone may extend.

    What this does *not* preserve is exact multiplicity beyond the budget: two
    requests differing only in occurrence counts above it still share a shape.
    That is the honest cost of a bounded field, and it is a cost in grouping
    precision rather than in what the fingerprint distinguishes.
    """
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    distinct = sorted(counts)
    if len(distinct) >= MAX_CLASS_SHAPE_ENTRIES:
        return distinct[:MAX_CLASS_SHAPE_ENTRIES]
    kept = dict.fromkeys(distinct, 1)
    budget = MAX_CLASS_SHAPE_ENTRIES - len(distinct)
    while budget > 0:
        spent = 0
        for label in distinct:
            if budget == 0:
                break
            if kept[label] < counts[label]:
                kept[label] += 1
                budget -= 1
                spent += 1
        if spent == 0:
            break
    return sorted(label for label in distinct for _ in range(kept[label]))


def request_fingerprint(shape: Sequence[str]) -> str:
    """A stable handle for one request *shape*, which no input can be read back out of.

    The digest's only inputs are closed-vocabulary labels and their counts.
    Nothing a caller authored is hashed, so unlike a truncated sha of a filename
    this cannot be inverted by hashing a dictionary: there is no dictionary of
    candidate inputs, only the label set the profile publishes, and recovering
    that recovers no request.
    """
    known = sorted(str(label) for label in shape if str(label) in REQUEST_CLASS_LABELS)
    digest = hashlib.sha256(json.dumps(known, sort_keys=True).encode("utf-8")).hexdigest()
    return f"shape-{digest[:32]}"


def fingerprint_for_request(request: Mapping[str, object] | None) -> str:
    """`request_fingerprint` over the shape of a request in hand."""
    return request_fingerprint(request_class_shape(request))


def decision_id(*, source: str, request_fingerprint_value: str, run_id: str) -> str:
    """Stable identity of one decision question.

    The outcome is deliberately not in it: re-deciding the same question after
    the profile moved must supersede the earlier answer rather than open a
    second, parallel chain that both claim to be current. That is the same rule
    `approval_receipts.approval_id` follows, and for the same reason.
    """
    base = json.dumps(
        {
            "request_fingerprint": str(request_fingerprint_value),
            "run_id": str(run_id),
            "source": str(source),
        },
        sort_keys=True,
    )
    return f"decision-{hashlib.sha256(base.encode('utf-8')).hexdigest()[:16]}"


# ---------------------------------------------------------------------------
# Reason codes: the join, not a fifth vocabulary
# ---------------------------------------------------------------------------


def reason_codes_for_domain(domain: str) -> tuple[str, ...]:
    """Every reason code one existing vocabulary defines.

    Imported lazily, and only the module that owns each vocabulary is asked.
    Lazy because `coding.action_gate` already imports `workflows.approval_receipts`
    and `runtime.claims` already imports `workflows.external_effect_receipts`, so
    a module-level import from here would put a workflows module underneath two
    of its own consumers.
    """
    if domain == REASON_DOMAIN_SAFETY_PREFLIGHT:
        from ..quality.safety_preflight import correction_reason_codes

        return correction_reason_codes()
    if domain == REASON_DOMAIN_ACTION_GATE:
        from ..coding.action_gate import EXCLUSION_REASON_CODES

        return tuple(EXCLUSION_REASON_CODES)
    if domain == REASON_DOMAIN_APPROVAL:
        from .approval_receipts import REFUSAL_CODES

        return tuple(REFUSAL_CODES)
    if domain == REASON_DOMAIN_RUNTIME_CLAIM:
        from ..runtime.claims import RUNTIME_CLAIM_BLOCK_REASONS

        return tuple(sorted(str(claim) for claim in RUNTIME_CLAIM_BLOCK_REASONS))
    return ()


def decision_reason_text(domain: str, reason_code: str) -> str:
    """The constant line the owning vocabulary already publishes for this code.

    Joined at read time rather than stored, which is what keeps #806 answerable
    offline without this family owning a fifth copy of "why". A code outside its
    domain returns empty: rendering reads whatever is on disk, and an
    unrecognised code is not a new explanation, it is a value with no meaning.
    """
    code = str(reason_code or "")
    if code not in reason_codes_for_domain(domain):
        return ""
    if domain == REASON_DOMAIN_SAFETY_PREFLIGHT:
        from ..quality.safety_preflight import correction_for_reason_code

        return correction_for_reason_code(code)
    if domain == REASON_DOMAIN_APPROVAL:
        from .approval_receipts import REFUSAL_REASONS

        return str(REFUSAL_REASONS.get(code, ""))
    if domain == REASON_DOMAIN_RUNTIME_CLAIM:
        from ..runtime.claims import RUNTIME_CLAIM_BLOCK_REASONS

        for claim, text in RUNTIME_CLAIM_BLOCK_REASONS.items():
            if str(claim) == code:
                return str(text)
        return ""
    if domain == REASON_DOMAIN_ACTION_GATE:
        return _ACTION_GATE_REASONS.get(code, "")
    return ""


# `EXCLUSION_REASON_CODES` is the one of the four vocabularies that ships codes
# without constant prose -- `action_gate` requires each exclusion to carry its
# own `explanation` string, built where the exclusion is raised. A history read
# back on a later turn has no such string, so the constant line lives here. This
# is a rendering of codes that already exist, not a fifth vocabulary: the tuple
# is `action_gate`'s, and `tests/test_blocked_work_records.py` fails when the
# two go out of step.
_ACTION_GATE_REASONS: Final[dict[str, str]] = {
    "narrowed_by_request": "The request itself narrowed the authority envelope below what this action needs.",
    "not_required_by_task": "The task does not require this action, so the envelope never granted it.",
    "outside_permission_profile": "The active permission profile does not include this action.",
    "safety_preflight_denied": "The safety preflight denied the request before any authority was granted.",
    "user_authorized_pending_verification": (
        "The user authorized this action as a post-verification step; it stays a separate observed "
        "action gated on receipt evidence and the envelope never grants it."
    ),
    "withheld_pending_approval": "The action is withheld until an operator answers the confirmation it requires.",
}

# Which recovery a reason code allows. Keyed off the code so the copy is a
# lookup and never an interpolation, and defaulted per domain so a code added
# upstream still renders a usable action instead of an empty cell.
_RECOVERY_BY_REASON_CODE: Final[dict[str, str]] = {
    "safety_preflight_denied": "remove_prohibited_content",
    "withheld_pending_approval": "request_approval",
    "outside_permission_profile": "request_approval",
    "narrowed_by_request": "narrow_declared_scope",
    "not_required_by_task": "no_recovery_available",
    # The merge is not blocked by policy; it waits on the receipt evidence the
    # verification step produces, so recovery is to record that observed
    # evidence -- the closest existing recovery vocabulary to this reason.
    "user_authorized_pending_verification": "record_observed_evidence",
}
_RECOVERY_BY_DOMAIN: Final[dict[str, str]] = {
    REASON_DOMAIN_ACTION_GATE: "request_approval",
    REASON_DOMAIN_APPROVAL: "request_approval",
    REASON_DOMAIN_RUNTIME_CLAIM: "record_observed_evidence",
    REASON_DOMAIN_SAFETY_PREFLIGHT: "declare_missing_field",
}


def recovery_action_for(domain: str, reason_code: str) -> str:
    """The recovery id one blocked decision allows.

    A closed id, never a sentence: the localized copy for it lives in
    `wrapper.localized_copy` keyed by this id, which is what lets a recovery be
    stated in the operator's language without translating a
    `safety_preflight._CORRECTIONS` constant that is deliberately
    interpolation-free.
    """
    code = str(reason_code or "")
    if code in _RECOVERY_BY_REASON_CODE:
        return _RECOVERY_BY_REASON_CODE[code]
    if code.startswith("secret_") or code.startswith("prohibited_") or code.startswith("data_class_"):
        return "remove_prohibited_content"
    if code.endswith("_count_exceeded") or code.endswith("_too_long"):
        return "narrow_declared_scope"
    if code == "executor_choice_required":
        return "choose_executor"
    return _RECOVERY_BY_DOMAIN.get(domain, "no_recovery_available")


# Every key this module reads off an action-gate verdict, and off the denial
# that verdict carries. `tests/test_blocked_work_records.py` re-derives the
# actual reads from this module's source and checks them against
# `action_gate.ACTION_GATE_KEYS` and `action_gate.DENIAL_KEYS`, so these tuples
# describe the code rather than being trusted to.
#
# The pin exists because the first version of this lane read
# `denial["reason_code"]` -- singular, and not a member of the denial contract
# at all, which has only the plural `reason_codes`. Every gate denial therefore
# minted the fallback code instead of the one the gate raised, and the whole
# suite stayed green because each test built its own denial dict carrying the
# key the code was looking for.
ACTION_GATE_VERDICT_KEYS_READ: Final[tuple[str, ...]] = ("denial", "outcome", "safety_profile_revision")
ACTION_GATE_DENIAL_KEYS_READ: Final[tuple[str, ...]] = ("reason_codes",)

# The keys `decision_from_action_gate` hands to a recording surface. Closed and
# pinned so a consumer cannot read a key the producer never emits: `wrapper.contract`
# read `recovery_action` off this block before the block carried one, and fell
# through to a recomputation that happened to agree.
BLOCKED_WORK_DECISION_KEYS: Final[tuple[str, ...]] = (
    "class_shape",
    "outcome",
    "owner",
    "reason_code",
    "reason_domain",
    "recovery_action",
    "run_id",
    "safety_profile_revision",
    "source",
)


def decision_from_action_gate(
    action_gate: Mapping[str, Any] | None,
    *,
    owner: str,
    safety_profile_revision: str,
    request: Mapping[str, object] | None = None,
    class_shape: Sequence[str] | None = None,
    run_id: str = "",
) -> dict[str, Any]:
    """The decision one action-gate verdict already reached, as mint keywords.

    A translation and never a second judgement. `coding.action_gate.evaluate_action_gate`
    is the single decision path in this tree; this function reads its outcome
    and its denial and maps them onto this family's vocabulary, so a record can
    never disagree with the verdict that produced it.

    An allow maps to outcome `allowed` carrying the verdict's own `allowed`
    reason code, which is what puts allows in the history at all -- and that in
    turn is what makes "an allow is never rendered as attempted or completed" a
    property something can violate, rather than a claim about rows that do not
    exist.

    Only the request's *class shape* leaves this function. The request itself is
    read and dropped, because the returned block is embedded in the delegation
    payload and that payload is serialized; returning the request would have put
    every path and owner string a caller named into an artifact this family
    exists to keep them out of.
    """
    gate = action_gate if isinstance(action_gate, Mapping) else {}
    denial = gate.get("denial")
    denial_map = denial if isinstance(denial, Mapping) else {}
    # Plural. The denial contract is `DENIAL_KEYS` and carries a list of codes;
    # there is no singular member to read.
    listed = denial_map.get("reason_codes")
    reason_codes = [code for code in listed if isinstance(code, str)] if isinstance(listed, (list, tuple)) else []
    blocked = str(gate.get("outcome", "")) == "deny"
    if blocked:
        domain, code = _denial_reason(reason_codes)
    else:
        domain, code = REASON_DOMAIN_SAFETY_PREFLIGHT, "allowed"
    return {
        "source": "safety_preflight" if domain == REASON_DOMAIN_SAFETY_PREFLIGHT else "action_gate",
        "outcome": "blocked" if blocked else "allowed",
        "reason_domain": domain,
        "reason_code": code,
        "recovery_action": recovery_action_for(domain, code) if blocked else ALLOW_RECOVERY_ACTION,
        "owner": str(owner or "hermes"),
        # The verdict's own revision first: a record must cite the profile the
        # decision was actually made under, not the one live when it is written.
        # `UNKNOWN_REVISION` rather than an empty string when neither is
        # available, because the field is required and "we do not know" is a
        # thing a record may honestly say while "" is not.
        "safety_profile_revision": (
            str(gate.get("safety_profile_revision", "") or "")
            or str(safety_profile_revision or "")
            or UNKNOWN_REVISION
        ),
        "class_shape": list(class_shape) if class_shape is not None else request_class_shape(request),
        "run_id": run_id,
    }


def _denial_reason(reason_codes: Sequence[str]) -> tuple[str, str]:
    """Which vocabulary explains a denial, and which of its codes.

    Preflight corrections are consulted before action-gate exclusions because a
    denial the preflight raised is the more specific of the two: the gate's own
    `safety_preflight_denied` names *that the preflight denied*, while the
    preflight's code names *what it found*.

    `allowed` is skipped. It is a member of the preflight's code set because
    every passing verdict carries it, and a denial that somehow carries it too
    must not be recorded as though the reason for the block were a pass.
    """
    preflight_codes = reason_codes_for_domain(REASON_DOMAIN_SAFETY_PREFLIGHT)
    gate_codes = reason_codes_for_domain(REASON_DOMAIN_ACTION_GATE)
    for code in reason_codes:
        if code != "allowed" and code in preflight_codes:
            return REASON_DOMAIN_SAFETY_PREFLIGHT, code
    for code in reason_codes:
        if code in gate_codes:
            return REASON_DOMAIN_ACTION_GATE, code
    # A denial whose codes this build cannot explain is still a denial --
    # `_revision_drift_denial` is the live example, whose codes are
    # `carried:...`/`live:...` and belong to no explanation vocabulary.
    # Recording it as an allow to keep the vocabulary tidy would be the one
    # unrecoverable mistake this family can make, so it is recorded as blocked
    # under the code that names the gate's denial itself. That is deliberately a
    # weaker claim than naming the drift: the record says the gate denied before
    # authority was granted, which is true of every denial reaching this line,
    # and says nothing about which rule did it.
    return REASON_DOMAIN_ACTION_GATE, "safety_preflight_denied"


# ---------------------------------------------------------------------------
# Build, validate, append
# ---------------------------------------------------------------------------


def build_blocked_work_record(
    *,
    source: str,
    outcome: str,
    reason_domain: str,
    reason_code: str,
    owner: str,
    safety_profile_revision: str,
    request: Mapping[str, object] | None = None,
    class_shape: Sequence[str] | None = None,
    run_id: str = "",
    decided_at: str = "",
    supersedes_record_ref: str = "",
) -> dict[str, Any]:
    """Mint one record, or refuse.

    `request` is the bounded preflight request; only its class shape is read and
    it is never retained. A caller that already holds the shape passes
    `class_shape` instead, which is the path the gate takes so the request is
    not walked twice.
    """
    if source not in DECISION_SOURCES:
        raise BlockedWorkRecordError(f"blocked_work_record source is unsupported: {source!r}")
    if outcome not in DECISION_OUTCOMES:
        raise BlockedWorkRecordError(f"blocked_work_record outcome is unsupported: {outcome!r}")
    if reason_domain not in REASON_DOMAINS:
        raise BlockedWorkRecordError(f"blocked_work_record reason_domain is unsupported: {reason_domain!r}")
    if reason_code not in reason_codes_for_domain(reason_domain):
        raise BlockedWorkRecordError(
            f"blocked_work_record reason_code {reason_code!r} is not defined by {reason_domain}"
        )
    enforcement = SOURCE_ENFORCEMENT[source]
    if enforcement == "declared_not_enforced" and outcome not in {"blocked", "failed", "cancelled", "completed"}:
        # An observing source reports what it watched. It cannot be the thing
        # that granted permission, so it cannot mint an allow.
        raise BlockedWorkRecordError(
            f"blocked_work_record source {source!r} observes decisions and cannot record outcome {outcome!r}"
        )
    shape = sorted(str(label) for label in (class_shape if class_shape is not None else request_class_shape(request)))
    unknown_labels = sorted({label for label in shape if label not in REQUEST_CLASS_LABELS})
    if unknown_labels:
        raise BlockedWorkRecordError(f"blocked_work_record request_class_shape has unsupported labels: {unknown_labels}")
    safe_owner = _opaque(owner, field="blocked_work_record owner")
    safe_run_id = _opaque(run_id, field="blocked_work_record run_id") if run_id else ""
    safe_revision = _opaque(safety_profile_revision, field="blocked_work_record safety_profile_revision")
    safe_supersedes = (
        _opaque(supersedes_record_ref, field="blocked_work_record supersedes_record_ref")
        if supersedes_record_ref
        else ""
    )
    stamp = _opaque(str(decided_at or utc_now()), field="blocked_work_record decided_at")
    fingerprint = request_fingerprint(shape)
    identity = decision_id(source=source, request_fingerprint_value=fingerprint, run_id=safe_run_id)
    record = {
        "schema_version": BLOCKED_WORK_RECORD_SCHEMA_VERSION,
        "record_id": _record_id(stamp, identity, outcome),
        "decision_id": identity,
        "run_id": safe_run_id,
        "owner": safe_owner,
        "source": source,
        "outcome": outcome,
        "lifecycle_state": OUTCOME_LIFECYCLE[outcome],
        "reason_domain": reason_domain,
        "reason_code": reason_code,
        "recovery_action": ALLOW_RECOVERY_ACTION if outcome == "allowed" else recovery_action_for(reason_domain, reason_code),
        "enforcement": enforcement,
        "enforcement_blocker": SOURCE_ENFORCEMENT_BLOCKERS.get(source, ""),
        "request_fingerprint": fingerprint,
        "request_class_shape": shape,
        "safety_profile_revision": safe_revision,
        "decided_at": stamp,
        "supersedes_record_ref": safe_supersedes,
        "privacy": RECORD_PRIVACY,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    errors = validate_blocked_work_record(record)
    if errors:
        raise BlockedWorkRecordError(errors[0])
    return record


def validate_blocked_work_record(record: dict[str, Any]) -> list[str]:
    """Every reason one record is not a blocked work record."""
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["blocked_work_record must be an object"]
    forbidden = sorted(key for key in record if str(key).lower() in RAW_OR_HIDDEN_KEYS)
    if forbidden:
        errors.append(f"blocked_work_record must not carry raw or hidden keys: {forbidden}")
    extra_keys = sorted(set(record) - set(BLOCKED_WORK_RECORD_KEYS) - set(forbidden))
    if extra_keys:
        errors.append(f"blocked_work_record has unsupported keys: {extra_keys}")
    missing = sorted(set(BLOCKED_WORK_RECORD_KEYS) - set(record))
    if missing:
        errors.append(f"blocked_work_record is missing keys: {missing}")
    if record.get("schema_version") != BLOCKED_WORK_RECORD_SCHEMA_VERSION:
        errors.append(f"blocked_work_record schema_version must be {BLOCKED_WORK_RECORD_SCHEMA_VERSION}")
    for key in _RECORD_STRING_FIELDS:
        if not isinstance(record.get(key), str):
            errors.append(f"blocked_work_record {key} must be a string")
    for key, vocabulary in _RECORD_VOCABULARIES:
        if record.get(key) not in vocabulary:
            errors.append(f"blocked_work_record {key} is unsupported: {record.get(key)!r}")
    for key, vocabulary in _OPTIONAL_RECORD_VOCABULARIES:
        value = record.get(key)
        if value and value not in vocabulary:
            errors.append(f"blocked_work_record {key} is unsupported: {value!r}")
    if record.get("privacy") != RECORD_PRIVACY:
        errors.append("blocked_work_record privacy must be metadata_only")
    if record.get("claim_boundary") != CLAIM_BOUNDARY:
        errors.append("blocked_work_record claim_boundary must state the decision boundary")
    for field in _REQUIRED_RECORD_REFS:
        errors.extend(_ref_errors(record.get(field), field=field, required=True))
    for field in _OPTIONAL_RECORD_REFS:
        errors.extend(_ref_errors(record.get(field), field=field, required=False))
    errors.extend(_class_shape_errors(record.get("request_class_shape")))
    errors.extend(_reason_errors(record))
    errors.extend(_consistency_errors(record))
    return errors


def _reason_errors(record: Mapping[str, Any]) -> list[str]:
    domain = str(record.get("reason_domain", ""))
    if domain not in REASON_DOMAINS:
        return []
    code = record.get("reason_code")
    if not isinstance(code, str) or code not in reason_codes_for_domain(domain):
        return [f"blocked_work_record reason_code is not defined by {domain}: {code!r}"]
    return []


def _consistency_errors(record: Mapping[str, Any]) -> list[str]:
    """The derived fields, re-derived.

    Without this a hand-edited store could pair `blocked` with a terminal
    lifecycle, or hang an `enforced` claim off a hook that has no deny channel,
    and every reader downstream would believe it.
    """
    errors: list[str] = []
    outcome = str(record.get("outcome", ""))
    source = str(record.get("source", ""))
    if outcome in OUTCOME_LIFECYCLE and record.get("lifecycle_state") != OUTCOME_LIFECYCLE[outcome]:
        errors.append(
            f"blocked_work_record lifecycle_state must be {OUTCOME_LIFECYCLE[outcome]} for outcome {outcome}"
        )
    if source in SOURCE_ENFORCEMENT and record.get("enforcement") != SOURCE_ENFORCEMENT[source]:
        errors.append(f"blocked_work_record enforcement must be {SOURCE_ENFORCEMENT[source]} for source {source}")
    if source in SOURCE_ENFORCEMENT_BLOCKERS:
        if record.get("enforcement_blocker") != SOURCE_ENFORCEMENT_BLOCKERS[source]:
            errors.append(f"blocked_work_record enforcement_blocker must state why {source} cannot enforce")
        if outcome == "allowed":
            errors.append(f"blocked_work_record source {source} observes decisions and cannot record an allow")
    elif record.get("enforcement_blocker"):
        errors.append("blocked_work_record enforcement_blocker must be empty for an enforcing source")
    if outcome == "allowed" and record.get("recovery_action") != ALLOW_RECOVERY_ACTION:
        errors.append("blocked_work_record recovery_action must promise nothing for an allow")
    shape = record.get("request_class_shape")
    if isinstance(shape, list) and all(isinstance(label, str) for label in shape):
        expected = request_fingerprint(shape)
        if str(record.get("request_fingerprint", "")) != expected:
            # Without this a hand-edited store could point one decision's shape
            # at another decision's fingerprint and merge two chains.
            errors.append("blocked_work_record request_fingerprint does not identify its own class shape")
        expected_identity = decision_id(
            source=source,
            request_fingerprint_value=expected,
            run_id=str(record.get("run_id", "")),
        )
        if str(record.get("decision_id", "")) != expected_identity:
            errors.append("blocked_work_record decision_id does not identify its own source, run, and request shape")
    if str(record.get("record_id", "")) and str(record.get("record_id", "")) == str(
        record.get("supersedes_record_ref", "")
    ):
        errors.append("blocked_work_record supersedes_record_ref must not name itself")
    return errors


def _class_shape_errors(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["blocked_work_record request_class_shape must be a list"]
    if len(value) > MAX_CLASS_SHAPE_ENTRIES:
        return [f"blocked_work_record request_class_shape must hold at most {MAX_CLASS_SHAPE_ENTRIES} labels"]
    errors: list[str] = []
    for index, label in enumerate(value):
        if not isinstance(label, str):
            errors.append(f"blocked_work_record request_class_shape[{index}] must be a string")
        elif label not in REQUEST_CLASS_LABELS:
            errors.append(f"blocked_work_record request_class_shape[{index}] is unsupported: {label!r}")
    if value != sorted(str(label) for label in value if isinstance(label, str)) and not errors:
        errors.append("blocked_work_record request_class_shape must be sorted")
    return errors


def append_blocked_work_record(paths: OmhPaths, record: dict[str, Any]) -> dict[str, Any]:
    """Append one validated record. Never rewrites, never reorders."""
    errors = validate_blocked_work_record(record)
    if errors:
        raise BlockedWorkRecordError(errors[0])
    with file_lock(paths.runtime_blocked_work_records_path, private=True):
        append_store_line(paths.runtime_blocked_work_records_path, record)
    return record


def record_blocked_work(
    paths: OmhPaths,
    *,
    source: str,
    outcome: str,
    reason_domain: str,
    reason_code: str,
    owner: str,
    safety_profile_revision: str,
    request: Mapping[str, object] | None = None,
    class_shape: Sequence[str] | None = None,
    run_id: str = "",
    now: str = "",
) -> dict[str, Any]:
    """Mint and append one record, or return the record that already states it.

    The strict entry point: it raises when the decision cannot become a record
    and when the store cannot be written. Producers on a live turn call
    `mint_blocked_work_record` instead, because a store outage must not fail the
    gate that already reached its verdict.
    """
    record, _ = _record_decision(
        paths.runtime_blocked_work_records_path,
        source=source,
        outcome=outcome,
        reason_domain=reason_domain,
        reason_code=reason_code,
        owner=owner,
        safety_profile_revision=safety_profile_revision,
        request=request,
        class_shape=class_shape,
        run_id=run_id,
        now=now,
    )
    return record


def mint_blocked_work_record(
    paths: OmhPaths,
    *,
    source: str,
    outcome: str,
    reason_domain: str,
    reason_code: str,
    owner: str,
    safety_profile_revision: str,
    request: Mapping[str, object] | None = None,
    class_shape: Sequence[str] | None = None,
    run_id: str = "",
    now: str = "",
) -> dict[str, Any]:
    """Record one decision without ever raising into the deciding surface.

    A gate records *after* it has already denied. Letting the store fail that
    path would turn an unwritable store into a request that looks like it was
    never judged, which is precisely the hole this family exists to close, so
    every refusal and every write failure is returned instead of raised.

    Returns a `blocked_work_mint_result/v1` mapping:

        schema_version -- BLOCKED_WORK_MINT_RESULT_SCHEMA_VERSION
        minted         -- True when a record reached the store
        outcome        -- "recorded" | "repeat_recorded" | "refused" | "not_written"
        decision_id    -- the decision this call was about
        record_id      -- the record now on file, "" when there is none
        decision       -- the outcome now on file, "" when there is none
        error          -- the refusal or write failure, "" otherwise

    `repeat_recorded` is a record that restates a decision already on file. It
    is appended rather than folded into the earlier one, for the reason
    `_record_decision` gives.

    Failures are also appended to `blocked_work_mint_failures.jsonl` beside the
    store, best effort, so a decision that went unrecorded is itself visible.
    """
    return mint_blocked_work_record_at(
        paths.runtime_blocked_work_records_path,
        source=source,
        outcome=outcome,
        reason_domain=reason_domain,
        reason_code=reason_code,
        owner=owner,
        safety_profile_revision=safety_profile_revision,
        request=request,
        class_shape=class_shape,
        run_id=run_id,
        now=now,
    )


def mint_blocked_work_record_at(
    store_path: Path,
    *,
    source: str,
    outcome: str,
    reason_domain: str,
    reason_code: str,
    owner: str,
    safety_profile_revision: str,
    request: Mapping[str, object] | None = None,
    class_shape: Sequence[str] | None = None,
    run_id: str = "",
    now: str = "",
) -> dict[str, Any]:
    """`mint_blocked_work_record` against an already-resolved store path."""
    shape = sorted(str(label) for label in (class_shape if class_shape is not None else request_class_shape(request)))
    identity = decision_id(
        source=str(source),
        request_fingerprint_value=request_fingerprint(shape),
        run_id=str(run_id),
    )
    try:
        record, mint_outcome = _record_decision(
            store_path,
            source=source,
            outcome=outcome,
            reason_domain=reason_domain,
            reason_code=reason_code,
            owner=owner,
            safety_profile_revision=safety_profile_revision,
            request=None,
            class_shape=shape,
            run_id=run_id,
            now=now,
        )
    except BlockedWorkRecordError as exc:
        return _mint_failure(
            store_path,
            outcome="refused",
            error=str(exc),
            decision_id_value=identity,
            source=source,
            decision=outcome,
            run_id=run_id,
        )
    except OSError as exc:
        # Covers FileLockTimeout, which is a TimeoutError and therefore an
        # OSError: an unavailable lock is a store that could not be written.
        return _mint_failure(
            store_path,
            outcome="not_written",
            error=str(exc),
            decision_id_value=identity,
            source=source,
            decision=outcome,
            run_id=run_id,
        )
    return {
        "schema_version": BLOCKED_WORK_MINT_RESULT_SCHEMA_VERSION,
        "minted": True,
        "outcome": mint_outcome,
        "decision_id": str(record.get("decision_id", "")),
        "record_id": str(record.get("record_id", "")),
        "decision": str(record.get("outcome", "")),
        "error": "",
    }


def _record_decision(
    path: Path,
    *,
    source: str,
    outcome: str,
    reason_domain: str,
    reason_code: str,
    owner: str,
    safety_profile_revision: str,
    request: Mapping[str, object] | None,
    class_shape: Sequence[str] | None,
    run_id: str,
    now: str,
) -> tuple[dict[str, Any], str]:
    """The record this call put on file, and whether it restates an earlier one.

    The read of the prior record and the append happen under one lock, so two
    concurrent decisions on one question cannot both link to the same
    predecessor and fork the chain.

    A decision that restates one already on file is appended, not folded into
    it. Folding looked like idempotent minting and was not: a decision is
    identified by `(source, request class shape, run)`, and a class shape is
    deliberately shared by every request of the same shape, so two *different*
    blocks -- different requests, different turns, same shape, same reason --
    landed on one record dated at the first of them. The store then reported one
    decision where there had been several, and reported the wrong time for the
    one it kept. Appending keeps every occurrence, dates the head at the latest,
    and leaves the earlier ones on file as superseded records the history counts.

    What the projection still does not do is show the repeats as separate
    entries: `project_decision_history` renders chain heads, so a shape blocked
    ten times is one entry with `superseded_count` 9. It is a history of
    decisions, not of block events.
    """
    shape = sorted(str(label) for label in (class_shape if class_shape is not None else request_class_shape(request)))
    with file_lock(path, private=True):
        identity = decision_id(
            source=str(source),
            request_fingerprint_value=request_fingerprint(shape),
            run_id=str(run_id),
        )
        records, _ = read_jsonl_objects(path)
        prior = latest_record_in(records, key="decision_id", value=identity)
        record = build_blocked_work_record(
            source=source,
            outcome=outcome,
            reason_domain=reason_domain,
            reason_code=reason_code,
            owner=owner,
            safety_profile_revision=safety_profile_revision,
            class_shape=shape,
            run_id=run_id,
            decided_at=now,
            supersedes_record_ref=str(prior.get("record_id", "")) if prior else "",
        )
        repeat = bool(prior) and _decision_fingerprint(prior) == _decision_fingerprint(record)
        append_store_line(path, record)
    return record, "repeat_recorded" if repeat else "recorded"


# ---------------------------------------------------------------------------
# Read, validate the store, render
# ---------------------------------------------------------------------------


def read_blocked_work_records_result(paths: OmhPaths) -> tuple[list[dict[str, Any]], list[str]]:
    return read_jsonl_objects(paths.runtime_blocked_work_records_path)


def read_blocked_work_records(
    paths: OmhPaths,
    *,
    run_id: str | None = None,
    decision_id_value: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """The store, in append order, optionally scoped to one run or one decision."""
    records, _ = read_blocked_work_records_result(paths)
    if run_id is not None:
        records = [record for record in records if str(record.get("run_id", "")) == run_id]
    if decision_id_value is not None:
        records = [record for record in records if str(record.get("decision_id", "")) == decision_id_value]
    if limit is None:
        return records
    if limit < 1:
        return []
    return records[-limit:]


def latest_record_for_decision(
    records: Sequence[Mapping[str, Any]],
    decision_id_value: str,
) -> dict[str, Any]:
    """The record that speaks for one decision: the one selection rule."""
    return dict(latest_record_in(records, key="decision_id", value=str(decision_id_value)))


def validate_blocked_work_record_store(path: Path, *, run_id: str | None = None) -> dict[str, Any]:
    """Validate the blocked-work store, optionally scoped to one run's records.

    Unscoped this is the store's own report: unparseable lines, every record's
    schema, and the integrity of the supersede chain. The chain walk is the
    shared one, told this family's key names so its findings read as records
    rather than as receipts it has none of.
    """
    records, read_errors = read_jsonl_objects(path)
    record_count, errors = store_errors(
        path,
        records,
        read_errors,
        run_id=run_id,
        validate_record=validate_blocked_work_record,
        label=_LABEL,
        id_key="record_id",
        link_key="supersedes_record_ref",
        noun="record",
    )
    return {
        "schema_version": BLOCKED_WORK_RECORD_STORE_VALIDATION_SCHEMA_VERSION,
        "path": str(path),
        "run_id": run_id or "",
        "ok": not errors,
        "record_count": record_count,
        "mint_failure_count": len(read_blocked_work_mint_failures(path)),
        "errors": errors,
    }


def blocked_work_mint_failures_path(store_path: Path) -> Path:
    """Where unrecorded decisions are logged, beside the store they failed to reach."""
    return store_path.with_name(BLOCKED_WORK_MINT_FAILURE_STORE_NAME)


def read_blocked_work_mint_failures(store_path: Path) -> list[dict[str, Any]]:
    failures, _ = read_jsonl_objects(blocked_work_mint_failures_path(store_path))
    return failures


def compact_blocked_work_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """The user-facing shape, with every field through its class's guard.

    Rendering is the last point at which a hand-edited store reaches a human, so
    nothing is copied through verbatim: identifiers fold to a stable
    non-navigable handle when they are not opaque, and closed vocabularies
    render empty outside their vocabulary. `work_claim` and `reason` are derived
    here rather than stored -- the first because what a renderer may claim is a
    property of the outcome and never of the file, and the second because the
    prose belongs to whichever vocabulary already owns the code.
    """
    outcome = closed_vocabulary_value(record.get("outcome"), DECISION_OUTCOMES)
    domain = closed_vocabulary_value(record.get("reason_domain"), REASON_DOMAINS)
    reason_code = str(record.get("reason_code", ""))
    return {
        "record_id": redacted_blocked_work_ref(str(record.get("record_id", ""))),
        "decision_id": redacted_blocked_work_ref(str(record.get("decision_id", ""))),
        "run_id": redacted_blocked_work_ref(str(record.get("run_id", ""))),
        "owner": redacted_blocked_work_ref(str(record.get("owner", ""))),
        "source": closed_vocabulary_value(record.get("source"), DECISION_SOURCES),
        "outcome": outcome,
        "lifecycle_state": closed_vocabulary_value(record.get("lifecycle_state"), LIFECYCLE_STATES),
        "work_claim": OUTCOME_WORK_CLAIMS.get(outcome, "not_attempted"),
        "reason_domain": domain,
        "reason_code": reason_code if reason_code in reason_codes_for_domain(domain) else "",
        "reason": decision_reason_text(domain, reason_code),
        "recovery_action": closed_vocabulary_value(record.get("recovery_action"), RECOVERY_ACTIONS),
        "enforcement": closed_vocabulary_value(record.get("enforcement"), ENFORCEMENT_MODES),
        "enforcement_blocker": closed_vocabulary_value(record.get("enforcement_blocker"), ENFORCEMENT_BLOCKERS),
        "request_fingerprint": redacted_blocked_work_ref(str(record.get("request_fingerprint", ""))),
        "request_class_shape": [
            label for label in _string_members(record.get("request_class_shape")) if label in REQUEST_CLASS_LABELS
        ],
        "safety_profile_revision": redacted_blocked_work_ref(str(record.get("safety_profile_revision", ""))),
        "decided_at": redacted_blocked_work_ref(str(record.get("decided_at", ""))),
        "supersedes_record_ref": redacted_blocked_work_ref(str(record.get("supersedes_record_ref", ""))),
    }


def redacted_blocked_work_ref(value: str) -> str:
    """Fold any handle into a bounded, non-navigable record reference.

    This family's path refusal, applied at the third place it is needed. `_opaque`
    applies it on write and `_ref_errors` applies it on validate; render used to
    delegate straight to the shared `redacted_ref`, whose opaque-ref pattern
    permits an interior `/` because approval receipts store a workspace scope
    path on purpose.

    The accurate scope of what leaked: a leading `/`, any `\\`, and `../` are
    already folded by `require_opaque_metadata_ref` inside `redacted_ref`. What
    passed through verbatim was a *relative POSIX path beginning with an
    alphanumeric* -- `src/views/home.py`. So `validate_blocked_work_record`
    refused a record that `compact_blocked_work_record` and
    `project_decision_history` then published as written: one file, two readers,
    opposite answers. Folding it to a digest handle here is what makes the three
    surfaces agree.
    """
    text = str(value or "").strip()
    if text and _PATH_SHAPED.search(text):
        return digest_ref(text)
    return redacted_ref(text, field="blocked_work_ref")


# ---------------------------------------------------------------------------
# #806: decision history, projected over the records above
# ---------------------------------------------------------------------------


def project_decision_history(
    records: Sequence[Mapping[str, Any]],
    *,
    run_id: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Every decision on file, explainable without the request that caused it.

    A projection and not a second store, for the reason `project_external_effects`
    and `project_run_lifecycle` are: a second store over one decision sequence is
    a fork by construction, and `supersede_chain_errors` already rejects forks.

    Allows appear here beside blocks. Each entry carries `work_claim` from
    `OUTCOME_WORK_CLAIMS`, so an allow renders as `not_attempted` and there is no
    shape in which it renders as attempted or completed.

    Every entry is answerable offline: `reason` is joined from the vocabulary
    that owns the code, `recovery_action` is a closed id, and nothing in the
    entry needs the original request -- which is the point, because after the
    turn the request is gone.

    One entry per *decision*, not per block event. A decision is identified by
    source, request class shape, and run, and a class shape is shared by every
    request of that shape, so a shape blocked ten times is one entry whose
    `decided_at` is the latest of the ten and whose nine predecessors are
    counted in `superseded_count`. Reading it as "ten requests were blocked"
    would be wrong; `record_count` is the number of records in scope and is the
    number to read for that.
    """
    known = [record for record in records if isinstance(record, Mapping)]
    scoped = known if run_id is None else [record for record in known if str(record.get("run_id", "")) == run_id]
    heads = _chain_heads(scoped)
    entries = [
        compact_blocked_work_record(record)
        for record in scoped
        if heads.get(str(record.get("decision_id", ""))) == str(record.get("record_id", ""))
    ]
    if limit is not None:
        entries = [] if limit < 1 else entries[-limit:]
    superseded = len(scoped) - len(
        [
            record
            for record in scoped
            if heads.get(str(record.get("decision_id", ""))) == str(record.get("record_id", ""))
        ]
    )
    return {
        "schema_version": DECISION_HISTORY_SCHEMA_VERSION,
        "run_id": run_id or "",
        "entries": entries,
        "summary": {
            "decision_count": len(entries),
            # Every record in scope, heads and superseded alike. `decision_count`
            # counts decisions and this counts the times one was recorded, and
            # the two differ by exactly the repeats.
            "record_count": len(scoped),
            "superseded_count": superseded,
            "outcome_counts": {
                outcome: sum(1 for entry in entries if entry["outcome"] == outcome) for outcome in DECISION_OUTCOMES
            },
            "lifecycle_counts": {
                state: sum(1 for entry in entries if entry["lifecycle_state"] == state) for state in LIFECYCLE_STATES
            },
            # Explainability is measured over the entries that need explaining.
            # An allow carries reason code `allowed`, whose correction is empty
            # because there is nothing to correct, so counting allows here would
            # dilute the one number #806 AC1 is about. Counts rather than a
            # boolean because a store written by an older build can hold codes a
            # newer one dropped, and "part of this history is no longer
            # explainable" is the honest report of that.
            "blocked_count": sum(1 for entry in entries if entry["outcome"] == "blocked"),
            "explainable_blocked_count": sum(
                1 for entry in entries if entry["outcome"] == "blocked" and entry["reason"]
            ),
            "unexplainable_blocked_count": sum(
                1 for entry in entries if entry["outcome"] == "blocked" and not entry["reason"]
            ),
            "enforced_count": sum(1 for entry in entries if entry["enforcement"] == "enforced"),
            "declared_not_enforced_count": sum(
                1 for entry in entries if entry["enforcement"] == "declared_not_enforced"
            ),
        },
        "claim_boundary": CLAIM_BOUNDARY,
    }


def decision_history(paths: OmhPaths, *, run_id: str | None = None, limit: int | None = None) -> dict[str, Any]:
    """`project_decision_history` over the store on disk."""
    records, _ = read_blocked_work_records_result(paths)
    return project_decision_history(records, run_id=run_id, limit=limit)


def _chain_heads(records: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """The current record for every decision in one pass over the store.

    The same selection rule as `latest_record_for_decision` -- last record wins
    -- built once so projecting a store of n records does not walk it n times.
    """
    heads: dict[str, str] = {}
    for record in records:
        heads[str(record.get("decision_id", ""))] = str(record.get("record_id", ""))
    return heads


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mint_failure(
    store_path: Path,
    *,
    outcome: str,
    error: str,
    decision_id_value: str,
    source: str,
    decision: str,
    run_id: str,
) -> dict[str, Any]:
    failure = {
        "schema_version": BLOCKED_WORK_MINT_FAILURE_SCHEMA_VERSION,
        "recorded_at": utc_now(),
        "outcome": outcome,
        "decision_id": str(decision_id_value),
        "source": str(source),
        "decision": str(decision),
        "run_id": str(run_id),
        "error": _bounded_error(error),
    }
    append_sidecar_line(blocked_work_mint_failures_path(store_path), failure)
    return {
        "schema_version": BLOCKED_WORK_MINT_RESULT_SCHEMA_VERSION,
        "minted": False,
        "outcome": outcome,
        "decision_id": str(decision_id_value),
        "record_id": "",
        "decision": "",
        "error": str(error),
    }


def _decision_fingerprint(record: Mapping[str, Any]) -> str:
    """Which decision a record states, ignoring when it was recorded."""
    return record_fingerprint(record, _DECISION_IDENTITY_KEYS)


def _record_id(decided_at: str, decision_id_value: str, outcome: str) -> str:
    return mint_record_id(
        prefix="blocked-work",
        identity={"decided_at": decided_at, "decision_id": decision_id_value, "outcome": outcome},
    )


def _ref_errors(value: Any, *, field: str, required: bool) -> list[str]:
    """The shared reference guard, plus this family's refusal of anything path-shaped."""
    errors = reference_errors(value, field=field, label=_LABEL, required=required)
    if errors or not isinstance(value, str) or not value:
        return errors
    if _PATH_SHAPED.search(value):
        return [f"{_LABEL} {field} must not name a path; this record carries the class of a request, never its content"]
    return []


def _opaque(value: str, *, field: str) -> str:
    text = opaque_ref(value, field=field, error=BlockedWorkRecordError)
    if _PATH_SHAPED.search(text):
        raise BlockedWorkRecordError(
            f"{field} must not name a path; this record carries the class of a request, never its content"
        )
    return text


def _bounded_error(value: str) -> str:
    """One bounded, secret-free line for the failure log."""
    raw = " ".join(str(value or "").split())
    if not raw:
        return ""
    if is_sensitive_metadata_text(raw):
        return "[redacted]"
    return raw[:200]


def _occurrences(value: object) -> int:
    """How many values one request field contributes to the class shape.

    A declared-empty list contributes none. The caller used to floor this at one,
    so `target_paths: []` -- a request declaring that it names no workspace path
    -- shipped a record whose shape claimed one.
    """
    if isinstance(value, (list, tuple)):
        return len(value)
    return 1


def _string_members(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, str)]


def _destination_entries(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, Mapping)]

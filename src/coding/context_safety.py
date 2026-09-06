from __future__ import annotations

import hashlib
import re
from typing import Any


CONTEXT_ARTIFACT_REF_SCHEMA_VERSION = "omh_context_artifact_ref/v1"
PROGRESS_EVENT_SCHEMA_VERSION = "omh_progress_event/v1"
CODING_PROGRESS_REPORTING_POLICY_SCHEMA_VERSION = "coding_progress_reporting_policy/v1"
CODING_PROGRESS_POLICY_ENFORCEMENT_SCHEMA_VERSION = "coding_progress_policy_enforcement/v1"
MAX_VISIBLE_MESSAGE_CHARS = 180
MAX_SUMMARY_CHARS = 240
MAX_PROGRESS_EVENT_SUMMARY_CHARS = 220
MAX_PROGRESS_EVENTS = 6
MAX_SOURCE_REF_CHARS = 240
MAX_EVIDENCE_REFS = 8
MAX_EVIDENCE_REF_CHARS = 160
MAX_ARTIFACT_REFS = 4
# Bound for an event name this closed vocabulary could not accept. It is a word,
# not a message; the cap only exists so a pathological value cannot ride into a
# chat-facing record through the omitted bag.
MAX_UNMAPPED_SOURCE_EVENT_CHARS = 120
# Observe-surface budgets. Run history only grows, so status checks emit a
# bounded tail, and each run has a cumulative emission budget after which the
# observe surfaces degrade to summary-only output plus artifact pointers.
MAX_RUN_HISTORY_EVENTS = 20
RUN_CONTEXT_BUDGET_BYTES = 200_000

_BACKGROUND_PROCESS_WRAPPER_RE = re.compile(
    r"\[?\s*\bBackground\s+process\s+\S+\s+finished\s+with\s+exit\s+code\s+\d+~?\s+"
    r"Here'?s\s+the\s+final\s+output:?\s*\]?",
    re.IGNORECASE,
)
_BACKGROUND_PROCESS_COMPLETION_LINE_RE = re.compile(
    r"^\[?\s*\bBackground\s+process\s+\S+\s+finished\s+with\s+exit\s+code\s+\d+~?\s*\]?\s*$",
    re.IGNORECASE,
)
_FINAL_OUTPUT_HEADER_LINE_RE = re.compile(r"^Here'?s\s+the\s+final\s+output:?$", re.IGNORECASE)
_FINAL_OUTPUT_HEADER_PREFIX_RE = re.compile(r"^\[?\s*Here'?s\s+the\s+final\s+output:?\s*\]?\s*", re.IGNORECASE)
_RAW_CODEX_JSONL_RE = re.compile(
    r'"type"\s*:\s*"(?:turn|item)\.completed"'
    r'|"\w*usage\w*"\s*:'
    r'|"\w*(?:input|output|reasoning|cached)_tokens\w*"\s*:',
    re.IGNORECASE,
)
_SELF_IMPROVEMENT_REVIEW_RE = re.compile(r"\bSelf-improvement\s+review\s*:", re.IGNORECASE)
# Absolute filesystem paths in chat-facing progress copy leak the operator's
# home directory -- on this repo's own machines that segment is an email-shaped
# account name -- into whatever surface renders the progress line, and they pad
# a one-line status with machine layout nobody reading chat can act on. The
# useful part of "/Users/<account>/work/<repo>/src/skills/render.py" is the tail
# after the repo root, so keep a bounded tail and drop the rooted prefix.
#
# Matching is deliberately conservative: an absolute POSIX path with at least
# two segments, or a drive-lettered Windows path. Relative paths are already
# safe and are left untouched, so `src/skills/render.py` survives verbatim.
_ABSOLUTE_POSIX_PATH_RE = re.compile(r"(?<![\w./])/(?:[\w.@+-]+/){1,}[\w.@+-]+")
_ABSOLUTE_WINDOWS_PATH_RE = re.compile(r"(?<![\w\\])[A-Za-z]:\\(?:[\w.@+ -]+\\)*[\w.@+ -]+")
_REDACTED_PATH_TAIL_SEGMENTS = 3

CODING_PROGRESS_REPORTABLE_EVENTS = (
    "workflow_started",
    "dispatch_to_executor",
    "blocker_encountered",
    "reported_change_not_observed",
    "targeted_tests_failed",
    "root_cause_identified",
    "fix_strategy_selected",
    "targeted_tests_passed",
    "full_tests_started",
    "full_tests_passed",
    "commit_created",
    "pr_updated",
    "workflow_completed",
)

_PROGRESS_EVENT_TYPES = {
    "status_update",
    "bug_discovered",
    "failure_discovered",
    "root_cause_identified",
    "fix_strategy_selected",
    "files_area_chosen",
    "targeted_tests_started",
    "targeted_tests_passed",
    "targeted_tests_failed",
    "full_tests_started",
    "full_tests_passed",
    "full_tests_failed",
    "commit_created",
    "pr_created",
    "pr_updated",
    "dispatch_to_executor",
    "blocker_encountered",
    "workflow_started",
    "workflow_completed",
    # Claim/observation mismatches. Registered here so `build_progress_event`
    # does not normalize them down to "status_update", which would erase the one
    # signal that says the narration and the repository disagree.
    "reported_change_not_observed",
}
_PROGRESS_EVENT_STATUSES = {"prepared", "observed", "running", "passed", "failed", "blocked"}
_PROGRESS_EVENT_SEVERITIES = {"info", "success", "warning", "error", "blocked"}


def compact_visible_text(value: Any, *, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return f"{text[: max_chars - 3]}..."


def bounded_prompt_preview(value: Any, *, max_chars: int = MAX_VISIBLE_MESSAGE_CHARS) -> str:
    """Structure-preserving bounded preview for composed delegate prompts.

    Unlike `compact_visible_text`, newlines and indentation survive, so the
    preview stays readable inside a fenced code block. A prompt over the bound
    keeps its head and ends with the documented
    ``... [truncated, N chars total]`` marker (N = original character count),
    the exact shape `DELEGATE_PROMPT_DISPLAY_RULE` promises.
    """
    text = str(value)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}... [truncated, {len(text)} chars total]"


def redact_absolute_paths(value: Any) -> str:
    """Reduce absolute filesystem paths to a bounded, account-free tail.

    `/Users/someone/work/repo/src/skills/render.py` becomes
    `.../repo/src/skills/render.py`. Relative paths are returned unchanged,
    because they carry no home directory and are already the readable form.
    """
    text = str(value)
    if not text.strip():
        return ""
    return _ABSOLUTE_WINDOWS_PATH_RE.sub(
        lambda match: _shorten_path(match.group(0), "\\"),
        _ABSOLUTE_POSIX_PATH_RE.sub(lambda match: _shorten_path(match.group(0), "/"), text),
    )


def _shorten_path(path: str, separator: str) -> str:
    segments = [segment for segment in path.split(separator) if segment]
    if len(segments) <= _REDACTED_PATH_TAIL_SEGMENTS:
        # Short enough to carry no home directory; keep it byte-identical so
        # `/etc/hosts` does not silently lose its leading separator.
        return path
    return "..." + separator + separator.join(segments[-_REDACTED_PATH_TAIL_SEGMENTS:])


def sanitize_user_facing_progress_text(value: Any, *, max_chars: int | None = None) -> str:
    """Drop raw process/JSONL maintenance noise from chat-facing progress copy."""
    text = redact_absolute_paths(value)
    if not text.strip():
        return ""
    clean_lines: list[str] = []
    for raw_line in text.splitlines() or [text]:
        line = raw_line.strip()
        if not line:
            continue
        if _raw_jsonl_or_self_review_noise_line(line):
            continue
        line = _BACKGROUND_PROCESS_WRAPPER_RE.sub(" ", line).strip()
        line = _FINAL_OUTPUT_HEADER_PREFIX_RE.sub("", line).strip()
        if _raw_progress_noise_line(line):
            continue
        clean_lines.append(line)
    cleaned = re.sub(r"\s+", " ", " ".join(clean_lines)).strip()
    if not cleaned:
        return ""
    if max_chars is None:
        return cleaned
    return compact_visible_text(cleaned, max_chars=max_chars)


def is_user_facing_progress_noise(value: Any) -> bool:
    text = str(value)
    return bool(text.strip()) and not sanitize_user_facing_progress_text(text)


def _raw_progress_noise_line(line: str) -> bool:
    return bool(
        _BACKGROUND_PROCESS_WRAPPER_RE.search(line)
        or _BACKGROUND_PROCESS_COMPLETION_LINE_RE.search(line)
        or _FINAL_OUTPUT_HEADER_LINE_RE.search(line)
        or _raw_jsonl_or_self_review_noise_line(line)
    )


def _raw_jsonl_or_self_review_noise_line(line: str) -> bool:
    return bool(_RAW_CODEX_JSONL_RE.search(line) or _SELF_IMPROVEMENT_REVIEW_RE.search(line))


def compact_context_refs(
    values: Any,
    *,
    max_items: int = MAX_EVIDENCE_REFS,
    max_chars: int = MAX_EVIDENCE_REF_CHARS,
) -> tuple[list[str], int]:
    if not isinstance(values, (list, tuple)):
        return [], 0
    seen: list[str] = []
    omitted = 0
    for value in values:
        text = compact_visible_text(value, max_chars=max_chars)
        if not text:
            continue
        if text in seen:
            continue
        if len(seen) >= max_items:
            omitted += 1
            continue
        seen.append(text)
    return seen, omitted


def build_progress_event(
    event_type: str,
    summary: Any,
    *,
    status: str = "observed",
    severity: str = "info",
    file_refs: list[str] | tuple[str, ...] | None = None,
    artifact_refs: list[object] | tuple[object, ...] | None = None,
    evidence_refs: list[str] | tuple[str, ...] | None = None,
) -> dict[str, object]:
    compact_files, omitted_files = compact_context_refs(file_refs or [])
    compact_evidence, omitted_evidence = compact_context_refs(evidence_refs or [])
    compact_artifacts, omitted_artifacts = _compact_artifact_refs(artifact_refs or [])
    omitted: dict[str, object] = {
        "file_ref_count": omitted_files,
        "artifact_ref_count": omitted_artifacts,
        "evidence_ref_count": omitted_evidence,
        "max_summary_chars": MAX_PROGRESS_EVENT_SUMMARY_CHARS,
        "max_artifact_refs": MAX_ARTIFACT_REFS,
        "max_evidence_refs": MAX_EVIDENCE_REFS,
    }
    # The omitted bag already records what this builder dropped, so the words it
    # refused belong here too. Present only when a value was actually discarded:
    # an absent key means nothing was lost, never that nothing was checked.
    #
    # All THREE closed vocabularies are recorded, not just the event type. An
    # owner reporting `status: "cancelled"` collapses to `observed` and an owner
    # reporting nothing also collapses to `observed`, so without this the two
    # are indistinguishable -- the same silent collapse the event type was fixed
    # for, in the same function, one line further down.
    omitted.update(
        unmapped_progress_event_sources(event_type=event_type, status=status, severity=severity)
    )
    return {
        "schema_version": PROGRESS_EVENT_SCHEMA_VERSION,
        "event_type": _normalize_progress_event_type(event_type),
        "status": _normalize_choice(status, _PROGRESS_EVENT_STATUSES, "observed"),
        "severity": _normalize_choice(severity, _PROGRESS_EVENT_SEVERITIES, "info"),
        "summary": compact_visible_text(
            sanitize_user_facing_progress_text(_strip_code_fences(summary))
            or "Progress observed; raw process output stayed in artifacts.",
            max_chars=MAX_PROGRESS_EVENT_SUMMARY_CHARS,
        ),
        "file_refs": compact_files,
        "artifact_refs": compact_artifacts,
        "evidence_refs": compact_evidence,
        "omitted": omitted,
        "context_policy": "event_triggered_summary_only",
        "raw_content_included": False,
        "claim_boundary": (
            "This progress event is a compact wrapper/status update. It is not execution, review, CI, "
            "merge-readiness, merge, or raw-log evidence unless separate observed evidence records say so."
        ),
    }


def build_coding_progress_reporting_policy(
    *,
    next_action: str = "",
    lifecycle_status: str = "",
    wait_mechanism: str = "",
    wait_observation_mode: str = "",
) -> dict[str, object]:
    # Imported inside the function on purpose. `wait_strategy` depends on this
    # module for its bounded-text and refused-vocabulary helpers, so the module
    # dependency runs one way; the policy needs one block back from it, and a
    # local import is what keeps that from becoming an import cycle.
    from .wait_strategy import wait_strategy_policy_reference

    return {
        "schema_version": CODING_PROGRESS_REPORTING_POLICY_SCHEMA_VERSION,
        "mode": "event_triggered",
        "metadata_only": True,
        "raw_content_included": False,
        "timed_polling_rejected": True,
        "final_only_silence_rejected": True,
        "raw_log_dumping_rejected": True,
        # The half of the anti-polling rule that has to be decided BEFORE the
        # work starts. `timed_polling_rejected` says what not to do; this says
        # what to do instead, in terms of the completion primitive the host
        # actually exposed, and records which one this dispatch bound to.
        "wait_strategy": wait_strategy_policy_reference(
            mechanism=wait_mechanism,
            observation_mode=wait_observation_mode,
        ),
        "reportable_events": list(CODING_PROGRESS_REPORTABLE_EVENTS),
        "state_guidance": {
            "next_action": _normalize_token(next_action),
            "lifecycle_status": _normalize_token(lifecycle_status),
            "reportable_events": _coding_state_reportable_events(next_action),
        },
        "language_policy": {
            "style": "concise",
            "mirror_chat_language": True,
            "korean_friendly": True,
        },
        "evidence_boundary": (
            "Progress reports are concise lifecycle/status updates only. They are not execution, review, CI, "
            "merge-readiness, or merge proof unless matching observed records exist."
        ),
        "forbidden_patterns": [
            "final_only_silence_for_long_running_executor_work",
            "raw_log_dumping",
            "claiming_execution_review_ci_or_merge_without_observed_records",
            "waiting_by_repeated_status_reads_instead_of_a_bound_completion_signal",
        ],
        "enforcement": coding_progress_policy_enforcement(),
    }


def coding_progress_policy_enforcement() -> dict[str, object]:
    """Describe the mechanical backstop behind the declarative anti-polling rules.

    `timed_polling_rejected` and `raw_log_dumping_rejected` are enforced by the
    observe surfaces themselves, not only by asking the agent nicely: run status
    projections emit a bounded tail, and repeated calls consume a per-run
    emission budget that degrades output to summary-only plus artifact pointers.

    Those bounds act after a poll happened. The `wait_binding` block below is
    the precondition that keeps the poll from happening at all: a dispatch binds
    to a completion primitive first, records the handle and observation mode it
    bound to, and consumes that completion exactly once into a terminal state.
    """
    from .wait_strategy import (
        EXECUTION_WAIT_BINDING_SCHEMA_VERSION,
        EXECUTION_WAIT_STRATEGY_SCHEMA_VERSION,
        MIDPOINT_PEEK_BUDGET,
        WAIT_OBSERVATION_MODES,
        WAIT_TERMINAL_STATES,
    )

    return {
        "schema_version": CODING_PROGRESS_POLICY_ENFORCEMENT_SCHEMA_VERSION,
        "mechanism": "bounded_tail_plus_run_context_budget_ledger",
        # `omh coding status-board` belongs here for the same reason the other
        # three do: it is a surface an agent will poll while waiting on work, so
        # it caps its own rows (`--limit`, default 20) instead of growing with
        # the number of observed units. `omh goal board` is the same shape one
        # level up: polled while waiting on a multi-part goal, and capped the
        # same way.
        #
        # `omh runtime health-summary` is the same shape of temptation -- an
        # agent asks "is this run stuck yet" repeatedly -- and caps its own
        # output at `run_health.MAX_RUN_HEALTH_EVENTS` observations plus a fixed
        # metric set, so a longer run does not buy a longer answer.
        #
        # `omh runtime action-readiness` is that temptation aimed outward --
        # "can you send it yet" -- and answers in a fixed shape: one verdict, a
        # capped list of rejected records, and a capped list of store faults, no
        # matter how large the evidence stores have grown.
        "bounded_surfaces": [
            "omh runtime show",
            "omh runtime health-summary",
            "omh runtime action-readiness",
            "omh coding fanout show",
            "omh coding fanout brief",
            "omh coding status-board",
            "omh goal board",
        ],
        "default_history_limit": MAX_RUN_HISTORY_EVENTS,
        "run_context_budget_bytes": RUN_CONTEXT_BUDGET_BYTES,
        "degraded_output": "summary_only_with_artifact_pointers",
        "full_history_opt_out": "--full",
        "wait_binding": {
            "strategy_schema_version": EXECUTION_WAIT_STRATEGY_SCHEMA_VERSION,
            "binding_schema_version": EXECUTION_WAIT_BINDING_SCHEMA_VERSION,
            "precondition": "select_and_arm_the_wait_strategy_before_dispatch",
            "records": ["executor_handle", "observation_mode"],
            "observation_modes": list(WAIT_OBSERVATION_MODES),
            "completion_consumed_once": True,
            "terminal_states": list(WAIT_TERMINAL_STATES),
            "midpoint_peek_budget": MIDPOINT_PEEK_BUDGET,
            "unbounded_idle_or_busy_wait_rejected": True,
        },
        "declarative_only": False,
    }


def _coding_state_reportable_events(next_action: str) -> list[str]:
    normalized = _normalize_token(next_action)
    events_by_next_action = {
        "dispatch_to_executor": [
            "workflow_started",
            "dispatch_to_executor",
        ],
        "wait_for_executor_evidence": [
            "blocker_encountered",
            "targeted_tests_failed",
            "root_cause_identified",
            "fix_strategy_selected",
            "targeted_tests_passed",
        ],
        "surface_executor_blocker": [
            "blocker_encountered",
            "targeted_tests_failed",
        ],
        "record_verification_evidence": [
            "targeted_tests_passed",
            "full_tests_started",
        ],
        "record_review_evidence": [
            "full_tests_passed",
            "commit_created",
            "pr_updated",
        ],
        "record_ci_evidence": [
            "full_tests_passed",
            "pr_updated",
        ],
        "record_merge_readiness": [
            "full_tests_passed",
            "commit_created",
            "pr_updated",
        ],
        "report_completion_with_evidence": [
            "full_tests_passed",
            "commit_created",
            "pr_updated",
            "workflow_completed",
        ],
        "report_merge_ready": [
            "full_tests_passed",
            "commit_created",
            "pr_updated",
            "workflow_completed",
        ],
        "report_merged": [
            "workflow_completed",
        ],
    }
    return list(events_by_next_action.get(normalized, ["workflow_started"]))


def compact_progress_events(
    events: Any,
    *,
    max_items: int = MAX_PROGRESS_EVENTS,
) -> tuple[list[dict[str, object]], int]:
    if not isinstance(events, (list, tuple)):
        return [], 0
    compacted: list[dict[str, object]] = []
    omitted = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        if len(compacted) >= max_items:
            omitted += 1
            continue
        built = build_progress_event(
            str(event.get("event_type", "status_update")),
            event.get("summary", ""),
            status=str(event.get("status", "observed")),
            severity=str(event.get("severity", "info")),
            file_refs=event.get("file_refs", []) if isinstance(event.get("file_refs", []), list) else [],
            artifact_refs=event.get("artifact_refs", []) if isinstance(event.get("artifact_refs", []), list) else [],
            evidence_refs=event.get("evidence_refs", []) if isinstance(event.get("evidence_refs", []), list) else [],
        )
        # A second pass over an ALREADY-built event re-runs the vocabulary
        # checks against values that were already downgraded, so it finds
        # nothing to report and the note the first pass recorded disappears on
        # the way into a wrapper card. Carrying the recorded notes forward is
        # what keeps the first refusal visible after the rebuild.
        carried = _carried_unmapped_sources(event.get("omitted"))
        if carried:
            omitted_bag = built["omitted"]
            if isinstance(omitted_bag, dict):
                omitted_bag.update({key: value for key, value in carried.items() if key not in omitted_bag})
        compacted.append(built)
    return compacted, omitted


# The `omitted.unmapped_source_*` notes a previous `build_progress_event` may
# already have recorded. Named as a tuple rather than matched by prefix so a
# future omitted key cannot join this carry-forward by accident.
_CARRIED_UNMAPPED_SOURCE_KEYS = (
    "unmapped_source_event",
    "unmapped_source_status",
    "unmapped_source_severity",
)


def _carried_unmapped_sources(omitted: Any) -> dict[str, object]:
    if not isinstance(omitted, dict):
        return {}
    carried: dict[str, object] = {}
    for key in _CARRIED_UNMAPPED_SOURCE_KEYS:
        text = compact_visible_text(omitted.get(key, ""), max_chars=MAX_UNMAPPED_SOURCE_EVENT_CHARS)
        if text:
            carried[key] = text
    return carried


def context_budget_payload() -> dict[str, object]:
    return {
        "schema_version": "omh_context_budget/v1",
        "max_visible_message_chars": MAX_VISIBLE_MESSAGE_CHARS,
        "max_summary_chars": MAX_SUMMARY_CHARS,
        "max_progress_event_summary_chars": MAX_PROGRESS_EVENT_SUMMARY_CHARS,
        "max_progress_events": MAX_PROGRESS_EVENTS,
        "max_evidence_refs": MAX_EVIDENCE_REFS,
        "max_evidence_ref_chars": MAX_EVIDENCE_REF_CHARS,
        "raw_output_policy": "store_raw_output_as_artifact_and_inject_refs_and_summary_only",
    }


def raw_output_artifact_ref(
    text: str,
    *,
    source: str,
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    omitted_evidence_ref_count: int = 0,
) -> dict[str, object]:
    compact_refs, extra_omitted = compact_context_refs(evidence_refs or [])
    encoded = text.encode("utf-8")
    return {
        "schema_version": CONTEXT_ARTIFACT_REF_SCHEMA_VERSION,
        "source": compact_visible_text(source or "stdin", max_chars=MAX_SOURCE_REF_CHARS),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "byte_count": len(encoded),
        "line_count": len(text.splitlines()),
        "evidence_refs": compact_refs,
        "omitted_evidence_ref_count": omitted_evidence_ref_count + extra_omitted,
        "storage_policy": "store_raw_output_as_artifact",
        "in_context_policy": "refs_and_summary_only",
        "raw_content_included": False,
        "claim_boundary": "Raw output should stay in artifacts; Hermes context receives only this reference and bounded summaries.",
    }


def _normalize_progress_event_type(value: str) -> str:
    normalized = _normalize_token(value)
    return normalized if normalized in _PROGRESS_EVENT_TYPES else "status_update"


def progress_event_type_vocabulary() -> tuple[str, ...]:
    """The closed chat/workflow progress vocabulary, sorted.

    Public so a containment gate can prove every value here is a source word the
    executor normalizer knows. A value added here and not there makes every
    executor signal carrying it normalize to `unmapped_source_event` -- silently,
    and only on the surfaces a person reads.
    """
    return tuple(sorted(_PROGRESS_EVENT_TYPES))


def unmapped_progress_event_source(value: Any) -> str:
    """The event name `_normalize_progress_event_type` discarded, or "" when it kept it.

    The collapse to `status_update` is the right DOWNGRADE -- this vocabulary
    is closed, and an unknown word must not be promoted into it. What was wrong
    was that the word then vanished, so a caller reading the event could not
    tell "the executor reported a status update" from "the executor reported
    something we do not understand". This returns the discarded word so
    `build_progress_event` can record it as omitted rather than lose it.
    """
    return _unmapped_choice_source(value, _PROGRESS_EVENT_TYPES)


def unmapped_progress_event_sources(*, event_type: Any, status: Any, severity: Any) -> dict[str, object]:
    """Every closed-vocabulary value `build_progress_event` refused, keyed by field.

    Empty when all three were accepted, and each key is absent individually, so
    a reader never has to tell "kept" from "not checked".
    """
    refused = {
        "unmapped_source_event": _unmapped_choice_source(event_type, _PROGRESS_EVENT_TYPES),
        "unmapped_source_status": _unmapped_choice_source(status, _PROGRESS_EVENT_STATUSES),
        "unmapped_source_severity": _unmapped_choice_source(severity, _PROGRESS_EVENT_SEVERITIES),
    }
    return {key: value for key, value in refused.items() if value}


def _unmapped_choice_source(value: Any, allowed: set[str]) -> str:
    normalized = _normalize_token(value)
    if not normalized or normalized in allowed:
        return ""
    return compact_visible_text(value, max_chars=MAX_UNMAPPED_SOURCE_EVENT_CHARS)


def _normalize_choice(value: str, allowed: set[str], fallback: str) -> str:
    normalized = _normalize_token(value)
    return normalized if normalized in allowed else fallback


def _normalize_token(value: str) -> str:
    return str(value).strip().casefold().replace("-", "_").replace(" ", "_")


def _strip_code_fences(value: Any) -> str:
    return str(value).replace("```", " ")


def _compact_artifact_refs(values: list[object] | tuple[object, ...]) -> tuple[list[dict[str, object]], int]:
    compacted: list[dict[str, object]] = []
    omitted = 0
    for value in values:
        if len(compacted) >= MAX_ARTIFACT_REFS:
            omitted += 1
            continue
        artifact = _compact_artifact_ref(value)
        if artifact:
            compacted.append(artifact)
    return compacted, omitted


def _compact_artifact_ref(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        artifact = {
            "schema_version": compact_visible_text(value.get("schema_version", CONTEXT_ARTIFACT_REF_SCHEMA_VERSION), max_chars=80),
            "source": compact_visible_text(value.get("source", ""), max_chars=MAX_SOURCE_REF_CHARS),
            "sha256": compact_visible_text(value.get("sha256", ""), max_chars=80),
            "byte_count": max(0, int(value.get("byte_count", 0) or 0)),
            "line_count": max(0, int(value.get("line_count", 0) or 0)),
            "storage_policy": compact_visible_text(value.get("storage_policy", "store_raw_output_as_artifact"), max_chars=80),
            "in_context_policy": compact_visible_text(value.get("in_context_policy", "refs_and_summary_only"), max_chars=80),
            "raw_content_included": False,
        }
        return {key: item for key, item in artifact.items() if not _empty_artifact_field(item)}
    source = compact_visible_text(value, max_chars=MAX_SOURCE_REF_CHARS)
    if not source:
        return {}
    return {
        "schema_version": CONTEXT_ARTIFACT_REF_SCHEMA_VERSION,
        "source": source,
        "storage_policy": "store_raw_output_as_artifact",
        "in_context_policy": "refs_and_summary_only",
        "raw_content_included": False,
    }


def _empty_artifact_field(value: object) -> bool:
    return not isinstance(value, bool) and value in ("", 0)

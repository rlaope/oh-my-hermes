"""Let Hermes see how its own memory relates to OMH's approved records.

PR #672 built the comparison but left it CLI-only: `omh memory status` carried
it, and none of the nine registered tools did, so the model could not reach it
from chat. That is the half of the problem #672 did not close -- the store had
governance and no outlet.

OMH's memory blocks split into a tier rendered every turn and a tier read on
request. The full ``omh_memory`` tool stays on the plugin path; the memory
provider adds only the small ``omh_remember`` save/recall tool, which Hermes
tool_search never defers. When toolset config hides provider tools
(``memory_provider_tools_enabled`` in ``agent/memory_manager.py``),
``omh_memory`` still provides the full memory path.

Two different redaction rules meet here, and they do not merge. OMH block values
are OMH's own content and are returned in full. Hermes memory entries are not
OMH's, are never returned, and appear only as counts, hashes, and similarity
scores -- the same boundary this file has always held. One action narrows that
rule rather than breaking it: ``demote`` returns, for the one entry OMH now
holds, the ``old_text`` Hermes' own memory tool needs to remove it -- the
entry itself when it is at most 60 characters, else the first window of at
most 60 characters no other entry contains, and the whole entry only when no
such window exists. That text is the model's own memory, already in its
system prompt every turn, so the prefix discloses nothing the reader did not
hold -- the reasoning ``demotion_reference_line`` already quotes an entry under.

Read-only with respect to Hermes: nothing here opens a Hermes file for writing.
Hermes owns ``~/.hermes/memories``, and the `memory` tool Hermes exposes to the
model is what edits it.

The one write is ``capture``, into OMH's own store. It is the model's path
into that store with no operator step: the store held zero records after two
months while capture and approve existed only as CLI verbs. ``capture`` calls
memory admission (``memory_admission``) in-process -- the same path the
``omh memory capture`` CLI reaches through its adapters -- and reports the
receipt state admission observed on disk, never one it did not.

``demote`` is the second write, also into OMH's own store only. Hermes memory
is a small character-capped file paid for on every turn, and the operator path
(`omh memory demote --stage`, review, then a person asking Hermes to edit)
never ran on the machine it was built for while that file sat nearly full.
The action reads the entry from the Hermes file itself -- never a paraphrase
the model supplies -- copies it into OMH under the guards the staging
workflow holds, and only when an approved, intact, durable user-global copy
exists tells the model to remove the original with Hermes' own `memory` tool.
Token similarity never authorizes that removal.

Both writes read the lens below first: they run on an operator console or
the owner's messenger DM. A shared surface (a gateway chat nothing verified)
refuses them, because nothing says which of its participants stated the
fact; a background run and a session with no published lens refuse every
write. Another person's verified DM and a verified group capture inside their
own binding -- that person's principal, that channel's scope -- and never
demote the operator's Hermes memory. ``blocks`` and ``read`` read the lens
too: blocks are the operator's own notes, listed and read on the operator's
surfaces only.

``recall``, ``confirm``, ``correct`` and ``retire`` are the rest of the loop,
which used to exist only as operator verbs (`omh memory recall|confirm|correct|
retire`) in a package this process cannot import. They act on OMH's own store
only, through the lens the memory provider published for this session
(``memory_session_lens``): its homes, scope allowlist inputs, principal
context, shared-surface verdict and write permission. The tool never derives
those itself; with no published lens it reads the session as a shared surface
with no writes. Within that lens a record passes the selector's principal,
scope and perspective gates; lifecycle state is each action's own refusal.
``recall`` runs the prefetch selector itself, so its order is the order a
prefetch for that query would serve. ``confirm`` renews a review deadline the
way `omh memory confirm` does and counts one use per record per session in
``usage.json``, the counter the ranking reads. ``correct`` admits the
corrected fact through the model capture gates, linked to the old record, and
the approval that admits it moves the old revision to ``history/`` with
``superseded_by``. ``retire`` moves the record to the archive with a journal
line, the operator retire's recoverable shape; nothing here deletes a record.
"""

from __future__ import annotations

from .. import runtime_paths

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from ..awareness_delivery import _with_windows_retry
from ..degradation import safe_error_type as _safe_error_type
from ..hermes_memory import (
    HERMES_MEMORY_DELIMITER,
    HermesMemoryFile,
    build_hermes_memory_bridge,
    demotion_origin_ref,
    entry_digest,
    read_approved_records,
    read_hermes_memory,
)
from ..memory_admission import (
    DEMOTION_SUMMARY_MAX_CHARS,
    MODEL_CAPTURE_SOURCE,
    _days_after,
    _staleness_projection,
    _supersede_corrected_record_unlocked,
    capture_project_memory_candidate,
    demotion_refusal_reason,
    held_durable_user_global_record,
    read_project_memory_policy,
)
from ..memory_principals import principal_recall_decision
from ..memory_session_lens import (
    OWNER_SURFACE_CLASSES,
    SURFACE_BACKGROUND,
    SURFACE_CHANNEL,
    SURFACE_DIRECT,
    SURFACE_OPERATOR_CONSOLE,
    SURFACE_OWNER_DIRECT,
    SURFACE_SHARED,
    lens_channel_scope,
    lens_surface_class,
    note_session_records,
    read_session_lens,
    surface_flags,
)
from ..memory_recall_selector import resolve_scope_allowlist
from ..memory_recall_support import (
    PROJECT_MEMORY_RECORD_SCHEMA_VERSION,
    _REVIEW_DEFAULT_DAYS,
    _cadence_value,
    _parse_utc_naive_as_utc,
    _record_perspective_matches,
    _record_resolution,
    _record_staleness,
    _retention_class,
    normalize_memory_subject,
    record_subject,
)
from ..memory_records import (
    DEFAULT_RECORD_LIMIT,
    PREFETCH_EXECUTOR_TARGET,
    prefetch_required_scope_kinds,
    prefetch_scope_allowlist,
    read_record_store_snapshot,
    record_used,
    select_prefetch_records,
)
from ..memory_store_io import (
    assert_under_memory_root,
    ensure_private_dir,
    memory_dir,
    memory_index_path,
    memory_record_path,
    memory_store_lock,
    read_json_object_result,
    read_project_memory_candidates,
    utc_now,
    write_memory_index_unlocked,
    write_project_memory_candidate_unlocked,
    write_project_memory_record,
)
from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, host_session_id, observe_plugin_tool_call
from ..memory_blocks import read_memory_block, read_memory_blocks, select_memory_blocks
from ..memory_dreaming import read_dreaming_state, read_latest_consolidation
from ..memory_origin import origin_session_id, origin_source_ref, resolve_origin
from ..project_identity import resolve_project_identity

MEMORY_ACTIONS = ("status", "blocks", "read", "consolidation", "capture", "demote", "recall", "confirm", "correct", "retire")
LIFECYCLE_ACTIONS = ("recall", "confirm", "correct", "retire")
# The prefetch's own record limit: recall never returns more than a turn gets.
RECALL_MAX_LIMIT = DEFAULT_RECORD_LIMIT
RECALL_QUERY_MAX_CHARS = 500
RETIRE_REASONS = ("no_longer_true", "superseded", "user_asked")
# The surfaces whose recall rows carry an `origin` handle into Hermes' session store.
ORIGIN_SURFACE_CLASSES = frozenset({SURFACE_OPERATOR_CONSOLE, SURFACE_OWNER_DIRECT, SURFACE_DIRECT, SURFACE_CHANNEL})
RECALL_ORIGIN_NEXT_ACTION = (
    "To quote the person's exact words, open session_search(session_id=..., around_message_id=...) with a row's origin."
)
_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
CAPTURE_RECORD_TYPES = ("fact", "decision", "lesson", "procedure", "episode")
CAPTURE_SCOPES = ("project", "user")
CAPTURE_RETENTION_CLASSES = ("durable", "standard", "volatile")
# Admission stores at most this many summary characters.
CAPTURE_SUMMARY_MAX_CHARS = 500
CAPTURE_MAX_TAGS = 8
SUBJECT_NEXT_ACTION = (
    "Nothing was saved. Pass subject as lowercase letters, digits and hyphens, starting with a letter or digit, "
    "at most 48 characters (deploy-branch), or leave it out."
)
# A sha256 prefix shorter than this is not an identifier a brief prints.
DEMOTE_SHA_PREFIX_MIN_CHARS = 12
# The most of a Hermes entry `demote` returns: enough for Hermes' `old_text`.
DEMOTE_OLD_TEXT_MAX_CHARS = 60
# Hermes' memory tool names its two files by these `target` values.
HERMES_MEMORY_TARGETS = {"MEMORY.md": "memory", "USER.md": "user"}

REMEMBER_TOOL_NAME = "omh_remember"
REMEMBER_TOOL_SCHEMA = {
    "name": REMEMBER_TOOL_NAME,
    "description": (
        "Call save without asking when the user states a lasting preference, a decision, or a fact "
        "about their setup or project that should still hold in a later conversation. One fact per "
        "call, in one or two self-contained sentences with absolute dates. Never save secrets, logs, "
        "transcripts or task progress. After saving, tell the user in one short line. "
        "Use recall to look up what was saved before."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["save", "recall"], "default": "save"},
            "summary": {"type": "string", "description": "save: the fact, at most 500 characters."},
            "record_type": {"type": "string", "enum": list(CAPTURE_RECORD_TYPES)},
            "subject": {"type": "string", "description": "Optional lowercase slug, at most 48 characters."},
            "query": {"type": "string", "description": "recall: what to look up."},
        },
        "additionalProperties": False,
    },
}

OMH_MEMORY_SCHEMA = {
    "name": "omh_memory",
    "description": (
        "Read and add to OMH's durable memory. Call action='capture' yourself, without asking, when "
        "the user states something worth knowing in a later session: a lasting preference, a decision, "
        "a fact about their setup or project, or a lesson learned. One fact per call, as one or two "
        "sentences with absolute dates (never 'yesterday' or 'next week'). Never capture secrets, raw "
        "logs, transcripts, or task progress. Safe captures are remembered at once; the result's status "
        "says remembered, already_remembered, pending_review, or refused. Call 'status' first only when "
        "unsure what is already held. 'status' compares Hermes' built-in memory (MEMORY.md, USER.md) "
        "with OMH's approved records; 'blocks' lists blocks with admission and replay state; 'read' "
        "returns a replay-eligible block's value; 'consolidation' reads the latest reminder without "
        "evaluating it. 'demote' copies one Hermes entry (entry_sha256) into OMH; only if status is "
        "demoted or already_covered, remove it with Hermes' memory tool per remove_from_hermes. Hermes "
        "entries are otherwise only counted and hashed. 'recall' searches OMH records. With a record_id: "
        "'confirm' one that proved true or useful, 'correct' it (summary), 'retire' it (reason) when it no "
        "longer holds. After capture, demote, correct or retire, tell the user in one short line; "
        "display_line is suggested wording."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(MEMORY_ACTIONS),
                "description": "Defaults to 'status'. capture, demote, confirm, correct and retire write OMH memory.",
            },
            "label": {
                "type": "string",
                "description": "Block label, required by the 'read' action.",
            },
            "summary": {
                "type": "string",
                "description": "capture: the fact itself, self-contained, at most 500 characters.",
            },
            "record_type": {
                "type": "string",
                "enum": list(CAPTURE_RECORD_TYPES),
                "description": "capture: defaults to 'fact'.",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "capture: up to 8 short topic tags.",
            },
            "subject": {
                "type": "string",
                "description": "capture/correct: optional slug naming what the fact is about (deploy-branch).",
            },
            "scope": {
                "type": "string",
                "enum": list(CAPTURE_SCOPES),
                "description": "capture: defaults to 'project' inside an identified repository.",
            },
            "retention_class": {
                "type": "string",
                "enum": list(CAPTURE_RETENTION_CLASSES),
                "description": "capture: defaults to 'durable'; 'volatile' expires within a week.",
            },
            "entry_sha256": {
                "type": "string",
                "description": "demote: the entry's sha256 or a unique 12+ hex prefix.",
            },
            "query": {"type": "string"},
            "limit": {"type": "integer", "description": "recall: 1-6."},
            "record_id": {"type": "string"},
            "reason": {"type": "string", "enum": list(RETIRE_REASONS)},
            "observation": OBSERVATION_SCHEMA,
        },
    },
}


def omh_remember_handler(args: dict, *, session_id: str, **kwargs) -> str:
    """Save or recall through the full tool's admission and published session lens."""
    kwargs = {**kwargs, "session_id": session_id}
    args = args or {}
    observation = observe_plugin_tool_call(REMEMBER_TOOL_NAME, args, kwargs)
    action = str(args.get("action", "") or "save").strip().lower()
    if action == "save":
        payload = _capture({key: args[key] for key in ("summary", "record_type", "subject") if key in args}, kwargs)
    elif action == "recall":
        payload = _lifecycle("recall", {key: args[key] for key in ("query", "limit") if key in args}, kwargs)
    else:
        payload = _capture_result(
            "refused", reason="unknown_action", supported_actions=["save", "recall"],
            next_action="Nothing changed. Use action='save' or action='recall'.",
        )
    payload["plugin_tool"] = REMEMBER_TOOL_NAME
    payload["action"] = action
    payload["source_backend"] = "bundle_memory"
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)


def omh_memory_handler(args: dict, **kwargs) -> str:
    observation = observe_plugin_tool_call("omh_memory", args, kwargs)
    action = str((args or {}).get("action", "") or "status").strip().lower()
    if action not in MEMORY_ACTIONS:
        payload, backend = _unknown_action(action), "bundle_memory"
    elif action == "blocks":
        payload, backend = _blocks(kwargs), "bundle_memory"
    elif action == "read":
        payload, backend = _read_block(str((args or {}).get("label", "") or ""), kwargs), "bundle_memory"
    elif action == "consolidation":
        payload, backend = _consolidation()
    elif action == "capture":
        payload, backend = _capture(args or {}, kwargs), "bundle_memory"
    elif action == "demote":
        payload, backend = _demote(args or {}, kwargs), "bundle_memory"
    elif action in LIFECYCLE_ACTIONS:
        payload, backend = _lifecycle(action, args or {}, kwargs), "bundle_memory"
    else:
        payload, backend = _memory_bridge()
    payload["plugin_tool"] = "omh_memory"
    payload["action"] = action
    payload["source_backend"] = backend
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)


def _memory_bridge() -> tuple[dict[str, object], str]:
    """Compare the two stores using the bundle's own reader.

    This used to delegate to `omh.memory` and fall back when the import failed.
    The Hermes process cannot import that package -- it lives in its own
    environment -- so the fallback was the *only* path taken on the host this
    tool exists for, and the tool answered "package_absent" every time. Measured
    live before the fix: the model called it, got nothing, and shelled out to
    `omh memory status` instead. The reader is vendored here now, which is what
    every other working bundle surface already does.
    """
    try:
        return (
            build_hermes_memory_bridge(_home("OMH_HOME", "~/.omh"), _home("HERMES_HOME", "~/.hermes")),
            "bundle_memory",
        )
    except Exception as exc:
        # A read failure must stay distinguishable from an empty comparison, or
        # an unreadable memory file reads as a memory with nothing in it.
        return _unavailable(_safe_error_type(type(exc).__name__)), "bundle_memory_error"


def _blocks(kwargs: dict) -> dict[str, object]:
    """Review-readable block status, never values or ineligible descriptions. Operator consoles only."""
    lens = _session_lens(kwargs)
    refusal = _surface_read_refusal(lens)
    if refusal:
        return _block_refusal("omh_memory_block_listing/v2", refusal)
    home = lens.lens_home
    blocks = read_memory_blocks(home)
    selection = select_memory_blocks(blocks, omh_home=home)
    rows = []
    for block in blocks:
        row = block.to_summary()
        row["replay"] = _public_replay(selection.evaluations[block.block_id])
        rows.append(row)
    return {
        "schema_version": "omh_memory_block_listing/v2",
        "blocks": rows,
        "block_count": len(rows),
        "next_action": "Use action='read' only for a replay-eligible block label.",
        "claim_boundary": "Listings are review-readable metadata, not evidence Hermes read, wrote, or used memory.",
    }


def _read_block(label: str, kwargs: dict) -> dict[str, object]:
    """One block's value, or a stated miss. Operator consoles only.

    A missing block returns ``found: false`` rather than an empty value, so an
    absent block is never mistaken for a block that has nothing to say.
    """
    lens = _session_lens(kwargs)
    refusal = _surface_read_refusal(lens)
    if refusal:
        return _block_refusal("omh_memory_block_read/v2", refusal)
    if not label:
        return {
            "schema_version": "omh_memory_block_read/v1",
            "found": False,
            "reason": "label_required",
            "next_action": "Call action='blocks' to list available labels.",
        }
    home = lens.lens_home
    blocks = read_memory_blocks(home)
    selection = select_memory_blocks(blocks, omh_home=home)
    for block in blocks:
        if block.label != label:
            continue
        replay = _public_replay(selection.evaluations[block.block_id])
        if not replay["eligible"]:
            return {
                "schema_version": "omh_memory_block_read/v2",
                "found": True,
                "block_id": block.block_id,
                "revision": block.revision,
                "replay": replay,
                "next_action": "Review or reactivate this block; ineligible blocks never return values.",
            }
        return {
            "schema_version": "omh_memory_block_read/v2",
            "found": True,
            "block": block.to_dict(),
            "replay": replay,
            "claim_boundary": "A replay-eligible value is prepared OMH context, not observed Hermes use or mutation.",
        }
    return {
        "schema_version": "omh_memory_block_read/v1",
        "found": False,
        "reason": "unknown_label",
        "label": label,
        "next_action": "Call action='blocks' to list available labels.",
    }


def _surface_read_refusal(lens: "_SessionLens") -> tuple[str, str] | None:
    """Why ``blocks`` and ``read`` may not run in this session, as (reason, next_action); None when they may.

    Blocks are the operator's own always-on notes, rendered into the pack on
    an operator console only, so the tool lists and reads them there only. A
    background run reads like a shared surface and gets the same refusal.
    """
    if not lens.bound:
        return "session_lens_unavailable", "The OMH memory provider has not described this session; nothing was listed or read."
    if lens.surface_class not in OWNER_SURFACE_CLASSES:
        return (
            "shared_surface_reads_refused",
            "Memory blocks are the operator's own notes and are listed and read on the Hermes CLI, TUI, Desktop or the owner's direct message only; nothing was listed or read here.",
        )
    return None


def _block_refusal(schema_version: str, refusal: tuple[str, str]) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "status": "refused",
        "reason": refusal[0],
        "next_action": refusal[1],
        "claim_boundary": "No block was listed or read. This is not evidence about which blocks exist.",
    }


def _public_replay(evaluation: dict[str, object]) -> dict[str, object]:
    return {
        "eligible": bool(evaluation.get("eligible")),
        "reason_code": str(evaluation.get("reason_code", "ineligible")),
        "admission_state": evaluation.get("admission_state"),
        "source_class": evaluation.get("source_class"),
        "retention_class": evaluation.get("retention_class"),
    }


def _consolidation() -> tuple[dict[str, object], str]:
    """Read the latest reminder and counters without entering a provider session.

    Like `omh memory dream` without `--evaluate`, this is a status query, not
    a scheduler trigger. Keep a recorded due brief visible even when its
    reasons are suppressed for the next evaluation. No brief means unknown,
    not a fresh evaluation that found nothing due. Both are the calling
    profile's: another profile on the same store keeps its own.
    """
    omh_home = _home("OMH_HOME", "~/.omh")
    try:
        hermes_home = _home("HERMES_HOME", "~/.hermes")
        payload = dict(read_latest_consolidation(omh_home, hermes_home) or {})
        payload["state"] = read_dreaming_state(omh_home, hermes_home)
        payload["evaluated"] = False
        return payload, "bundle_memory"
    except Exception as exc:
        return _unavailable(_safe_error_type(type(exc).__name__)), "bundle_memory_error"


def _capture(args: dict, kwargs: dict) -> dict[str, object]:
    """Capture one memory through memory admission and map its answer."""
    summary = " ".join(str(args.get("summary", "") or "").split())
    record_type = str(args.get("record_type", "") or "fact").strip().lower()
    retention = str(args.get("retention_class", "") or "durable").strip().lower()
    tags = args.get("tags") or []
    refusal = _summary_refusal(summary, tags)
    if refusal:
        return _capture_result("refused", reason=refusal[0], next_action=refusal[1])
    if record_type not in CAPTURE_RECORD_TYPES:
        return _capture_result("refused", reason="unsupported_record_type", next_action=f"Use one of: {', '.join(CAPTURE_RECORD_TYPES)}.")
    if retention not in CAPTURE_RETENTION_CLASSES:
        return _capture_result("refused", reason="unsupported_retention_class", next_action=f"Use one of: {', '.join(CAPTURE_RETENTION_CLASSES)}.")
    subject = args.get("subject")
    if not _subject_ok(subject):
        return _capture_result("refused", reason="invalid_subject", next_action=SUBJECT_NEXT_ACTION)
    try:
        lens = _session_lens(kwargs)
    except ValueError as exc:  # RuntimeBindingError is a ValueError
        return _capture_result("error", reason=_safe_error_type(type(exc).__name__), next_action="Nothing was saved; this session's OMH home could not be resolved.")
    refusal = _surface_write_refusal(lens)
    if refusal:
        return _capture_result("refused", reason=refusal[0], next_action="Nothing was saved. " + refusal[1])
    bound = _bound_capture_scope(lens, str(args.get("scope", "") or "").strip().lower())
    if isinstance(bound, tuple):
        return _capture_result("refused", reason=bound[0], next_action="Nothing was saved. " + bound[1])
    if bound is not None:
        scope_kind, scope_ref, principal_context = str(bound["scope_kind"]), bound["scope_ref"], bound["principal_context"]
    else:
        cwd = _session_cwd(kwargs)
        identity = resolve_project_identity(cwd) if cwd is not None else None
        in_project = identity is not None and identity.state == "resolved"
        scope = str(args.get("scope", "") or ("project" if in_project else "user")).strip().lower()
        if scope not in CAPTURE_SCOPES:
            return _capture_result("refused", reason="unsupported_scope", next_action="Use scope 'project' or 'user'.")
        if scope == "project" and not in_project:
            return _capture_result(
                "refused",
                reason="project_scope_unresolved",
                next_action="This session is not inside a repository OMH can identify; retry with scope='user'.",
            )
        # `user` maps to the user-global scope: it needs no acting-principal
        # context, and recall delivers it beside the project scope.
        scope_kind = "project" if scope == "project" else "user-global"
        scope_ref = identity.identity if scope == "project" and identity is not None else None
        principal_context = None
    try:
        payload = capture_project_memory_candidate(
            lens.lens_home,
            summary,
            record_type=record_type,
            retention_class=retention,
            # The model's own loop has no reviewer who would act on a duplicate
            # candidate, so a duplicate names the existing record and writes nothing.
            on_duplicate="skip",
            source=MODEL_CAPTURE_SOURCE,
            # Which Hermes session said it, so recall can point back at the
            # person's own words in Hermes' store (`memory_origin`).
            source_ref=origin_source_ref(lens.session_id),
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            principal_context=principal_context,
            tags=list(tags),
            subject=subject or "",
            # Hints name only records this session's own lens admits, the
            # gates `recall` applies; with no published lens that is none.
            hint_admits=lambda record: _in_session_scope(record, lens),
        )
    except Exception as exc:
        # In-process now, so a store fault would otherwise raise into Hermes'
        # tool dispatch. It is an error result naming the exception class --
        # never a status that says something was saved.
        return _capture_result(
            "error",
            reason=_safe_error_type(type(exc).__name__),
            next_action="Nothing is confirmed saved. Tell the user the capture failed; call action='status' to see what is held.",
        )
    return _map_capture_payload(payload, lens)


def _bound_capture_scope(lens: "_SessionLens", requested: str) -> dict[str, object] | tuple[str, str] | None:
    """Where a messenger DM or channel keeps a capture, or why it will not; None on the owner's surfaces.

    Another person's DM keeps it bound to that person's principal (a v3
    record recalled only in their DMs) and a group conversation keeps it in
    the channel's scope, recalled only there. A scope the surface cannot
    honor is refused rather than quietly moved: the model would otherwise
    believe it stored a project fact.
    """
    direct = lens.surface_class == SURFACE_DIRECT
    if not direct and lens.surface_class != SURFACE_CHANNEL:
        return None
    if requested and not (direct and requested == "user"):
        where = "for this person only" if direct else "for this channel only"
        return "scope_unavailable_here", f"In this conversation memory is kept {where}; retry without scope."
    if direct:
        return {"scope_kind": "user", "scope_ref": None, "principal_context": lens.principal_context}
    return {"scope_kind": "channel", "scope_ref": str((lens.channel_scope or {}).get("ref", "")), "principal_context": None}


def _summary_refusal(summary: str, tags: object) -> tuple[str, str] | None:
    """Why a capture or correction summary/tags cannot be stored, as (reason, next_action)."""
    if not summary:
        return "summary_required", "Retry with a one- or two-sentence summary."
    if "\x00" in summary or any(isinstance(tag, str) and "\x00" in tag for tag in (tags if isinstance(tags, list) else [])):
        # Refused rather than stored: the CLI path can never carry one (a NUL
        # cannot travel in an argv), so neither does this one.
        return "control_character", "Remove the NUL character and retry."
    if len(summary) > CAPTURE_SUMMARY_MAX_CHARS:
        return "summary_too_long", f"Restate the fact in at most {CAPTURE_SUMMARY_MAX_CHARS} characters."
    if not isinstance(tags, list) or len(tags) > CAPTURE_MAX_TAGS or not all(isinstance(tag, str) for tag in tags):
        return "invalid_tags", f"Pass at most {CAPTURE_MAX_TAGS} tags as a list of strings."
    return None


def _subject_ok(value: object) -> bool:
    """Absent, empty, or a slug of the closed shape recall groups by."""
    try:
        normalize_memory_subject(value)
    except ValueError:
        return False
    return True


def _recallable_ids(lens: "_SessionLens") -> set[str]:
    """Record ids an unqueried prefetch under this lens would serve, budget aside.

    The selector itself decides -- scope, principal, perspective, eligibility,
    attention tier, subject collapse -- so a hint's "recalls" or "does not
    recall" is computed by the same code a turn runs, never assumed.
    """
    snapshot = read_record_store_snapshot(lens.homes)
    selection = select_prefetch_records(
        snapshot,
        "",
        allowed_scopes=lens.scopes,
        session_id=lens.session_id,
        executor_target=lens.executor_target,
        limit=max(len(snapshot.records), 1),
        principal_context=lens.principal_context,
        shared_surface=lens.shared_surface,
        required_scope_kinds=lens.required_scope_kinds,
    )
    pack = selection.pack
    served = {str(item.get("record_id", "")) for item in pack.get("included_records", [])}
    served |= {str(item.get("record_id", "")) for item in pack.get("excluded_records", []) if item.get("reason") == "over_budget"}
    return served


def _recall_clause(record_id: str, recallable: set[str] | None) -> str:
    if recallable is None:
        return f"whether {record_id} recalls could not be read"
    return f"{record_id} recalls" if record_id in recallable else f"{record_id} does not recall"


def _capture_hints(payload: dict, candidate: dict, new_id: str, lens: "_SessionLens | None") -> tuple[dict[str, object], str]:
    """Admission's two hints as result fields, plus the sentence that says what to do.

    The capture already went through either way. Whether each named record
    recalls is computed with the selector over this session's lens after the
    write (`_recallable_ids`), so a same-second tie on the subject, or a held
    record that is stale, is reported as it is. For a replacement, `correct`
    with this same summary moves the old record to history, linked to the new
    one. Wording says "similar wording", never "the same fact": term overlap
    cannot tell a replacement from a negation, so the model decides.
    """
    held_by = str(payload.get("subject_held_by", "") or "")
    similar = str(payload.get("similar_record_id", "") or "")
    if not held_by and not similar:
        return {}, ""
    try:
        recallable: set[str] | None = _recallable_ids(lens) if lens is not None else None
    except (OSError, ValueError):
        recallable = None
    involved = sorted({record_id for record_id in (new_id, held_by, similar) if record_id})
    fields: dict[str, object] = {
        "recalls_now": [record_id for record_id in involved if recallable is not None and record_id in recallable],
    }
    if held_by:
        fields["subject_held_by"] = held_by
    if similar:
        fields["similar_record_id"] = similar
        fields["similar_summary"] = str(payload.get("similar_summary", "") or "")
        fields["similar_wording_pct"] = int(payload.get("similar_wording_pct", 0) or 0)
    if not new_id:
        return fields, ""
    status = f"{_recall_clause(new_id, recallable)}, {_recall_clause(held_by or similar, recallable)}."
    if held_by:
        subject = str(candidate.get("subject", "") or "")
        return fields, (
            f"Saved. {held_by} also has subject '{subject}': {status} If this replaces it, call action='correct' with "
            f"record_id='{held_by}' and this same summary to move it to history. If both still hold, correct one of "
            "them with a reworded summary and a different subject."
        )
    return fields, (
        f"Saved. {similar} has similar wording: {status} If this replaces it, call action='correct' with "
        f"record_id='{similar}' and this same summary to move it to history; if both hold, nothing more is needed."
    )


def _map_capture_payload(payload: dict, lens: "_SessionLens | None" = None) -> dict[str, object]:
    """Translate an admission result into the tool's closed status set."""
    candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
    record = payload.get("record") if isinstance(payload.get("record"), dict) else {}
    receipt = payload.get("receipt_state")
    fields: dict[str, object] = {
        "receipt_state": str(receipt) if receipt else None,
        "candidate_id": str(candidate.get("candidate_id", "") or "") or None,
        "record_id": str(record.get("record_id", "") or "") or None,
        "admission_state": _admission_state(record),
    }
    new_id = str(record.get("record_id", "") or "") if payload.get("auto_approved") else ""
    hints, hint_action = _capture_hints(payload, candidate, new_id, lens)
    if not payload.get("captured"):
        reason = str(payload.get("reason", "") or "not_captured")
        if reason == "duplicate":
            duplicate_of = str(payload.get("duplicate_of", "") or "")
            return _capture_result(
                "already_remembered",
                **{**fields, "record_id": duplicate_of or None},
                duplicate_of=duplicate_of,
                next_action="Nothing new was saved; the same fact is already held.",
            )
        if payload.get("instruction_cue"):
            # A vocabulary item from admission's closed cue list, never the
            # user's text, so the model sees which words made it an order.
            fields["instruction_cue"] = str(payload["instruction_cue"])
        return _capture_result(
            "refused",
            **fields,
            reason=reason,
            # A refusal that names its own fix (an instruction-shaped summary)
            # passes it through, so the model learns how to restate it.
            next_action=(
                "Memory is turned off in OMH settings; nothing was saved."
                if reason == "project_memory_disabled"
                else str(payload.get("next_action", "") or "") or "Nothing was saved. Do not retry the same text."
            ),
        )
    if payload.get("auto_approved"):
        return _capture_result(
            "remembered",
            **fields,
            **hints,
            display_line=_display_line("📌 OMH remembered: ", str(candidate.get("summary", "") or ""), 80),
            next_action=hint_action or "Saved. Later sessions receive it when it fits their recall budget.",
        )
    return _capture_result(
        "pending_review",
        **{**fields, "admission_state": "pending_review"},
        **hints,
        review_reason=str(payload.get("review_reason", "") or "unknown"),
        next_action=(
            "Saved as a candidate that waits for operator review (`omh memory review`). For "
            "relative_time_phrase, capture the fact again with an absolute date instead."
        ),
    )


def _admission_state(record: dict) -> str | None:
    admission = record.get("admission")
    state = admission.get("state") if isinstance(admission, dict) else None
    return str(state) if state else None


def _capture_result(status: str, **fields: object) -> dict[str, object]:
    return {
        "schema_version": "omh_memory_capture/v1",
        "status": status,
        "receipt_state": None,
        "record_id": None,
        "candidate_id": None,
        "admission_state": None,
        **fields,
        "claim_boundary": (
            "receipt_state is what OMH memory admission observed on local disk; it is not "
            "evidence that a later session recalled or used the memory, and Hermes memory is unchanged."
        ),
    }


def _demote(args: dict, kwargs: dict) -> dict[str, object]:
    """Move one Hermes entry into OMH; say whether its original may now go."""
    wanted = str(args.get("entry_sha256", "") or "").strip().lower()
    if not DEMOTE_SHA_PREFIX_MIN_CHARS <= len(wanted) <= 64 or any(c not in "0123456789abcdef" for c in wanted):
        return _demote_result(
            "refused",
            reason="entry_sha256_invalid",
            next_action=f"Pass the entry's sha256 or a prefix of at least {DEMOTE_SHA_PREFIX_MIN_CHARS} hex characters.",
        )
    try:
        lens = _session_lens(kwargs)
        refusal = _surface_write_refusal(lens)
        if not refusal and lens.surface_class not in OWNER_SURFACE_CLASSES:
            # Hermes' built-in memory is the operator's; a DM of anyone else or
            # a group may not move it.
            refusal = (
                "demote_owner_only",
                "Hermes' built-in memory belongs to the operator; it is moved from the Hermes CLI, TUI, Desktop or the owner's direct message.",
            )
        if refusal:
            return _demote_result("refused", reason=refusal[0], next_action="Keep the Hermes entry; nothing was moved. " + refusal[1])
        return _demote_entry(wanted, lens.lens_home, Path(_home("HERMES_HOME", "~/.hermes")))
    except Exception as exc:
        # In-process inside Hermes' tool dispatch: a fault is an error result,
        # never `demoted`, so the model is never told to remove the original.
        return _demote_result(
            "error",
            reason=_safe_error_type(type(exc).__name__),
            next_action="Keep the Hermes entry; nothing is confirmed moved.",
        )


def _demote_entry(wanted: str, omh_home: Path, hermes_home: Path) -> dict[str, object]:
    matches: list[tuple[HermesMemoryFile, str]] = []
    for reading in read_hermes_memory(hermes_home):
        # An entry repeated verbatim in one file is one entry to Hermes too:
        # its store de-duplicates on load and its remove treats copies as one.
        for entry in dict.fromkeys(reading.entries):
            if entry_digest(entry).startswith(wanted):
                matches.append((reading, entry))
    if not matches:
        return _demote_result("refused", reason="entry_not_found", next_action="Nothing changed. The entry may already be gone.")
    if len({entry for _reading, entry in matches}) == 1 and len(matches) > 1:
        # The same text in MEMORY.md and USER.md has one digest, so no prefix
        # can tell the two apart, and removing one would leave the other.
        return _demote_result(
            "refused",
            reason="entry_in_both_files",
            files=[reading.label for reading, _entry in matches],
            next_action="Keep both; this entry is in MEMORY.md and USER.md. Remove one copy with Hermes' memory tool first if it should move.",
        )
    if len(matches) > 1:
        return _demote_result("refused", reason="entry_ambiguous", next_action="Retry with a longer entry_sha256 prefix.")
    reading, entry = matches[0]
    label = reading.label
    fields: dict[str, object] = {"file": label, "entry_sha256": entry_digest(entry), "chars": len(entry)}
    hermes_entries = _hermes_parsed_entries(reading.path)
    if entry not in hermes_entries:
        # Removing a fragment's old_text removes the whole Hermes entry around
        # it, so only an entry Hermes itself would parse may be moved.
        return _demote_result("refused", **fields, reason="entry_not_whole", next_action="Keep the Hermes entry; it is not one whole Hermes entry.")
    siblings = tuple(dict.fromkeys(hermes_entries))
    origin_ref = demotion_origin_ref(label, entry)
    # A standing decision on exactly this entry comes before any notion of
    # "already held": a rejection is never overridden by a matching record.
    for candidate in read_project_memory_candidates(omh_home):
        if str(candidate.get("source_ref", "")) != origin_ref:
            continue
        status = str(candidate.get("status", ""))
        candidate_id = str(candidate.get("candidate_id", "")) or None
        if status == "rejected":
            return _demote_result(
                "refused", **fields, reason="previously_rejected", candidate_id=candidate_id,
                next_action="A reviewer rejected this entry; keep it in Hermes.",
            )
        if status in ("pending_review", "blocked_review_required"):
            return _demote_result(
                "pending_review",
                **fields,
                candidate_id=candidate_id,
                next_action="A copy already waits for review; keep the Hermes entry until it is approved.",
            )
        if status != "approved":
            return _demote_result(
                "refused", **fields, reason="candidate_status_unknown", candidate_status=status,
                candidate_id=candidate_id, next_action="Keep the Hermes entry.",
            )
    for record in read_approved_records(omh_home):
        if str(record.get("source_ref", "")) != origin_ref:
            continue
        if str(record.get("summary", "")) != entry:
            return _demote_result(
                "refused",
                **fields,
                reason="content_not_intact",
                record_id=str(record.get("record_id", "")) or None,
                next_action="Keep the Hermes entry; the OMH copy of it differs.",
            )
        return _demoted("already_covered", reading, entry, siblings, fields, str(record.get("record_id", "")))
    # Similarity never authorizes a removal: a negation of the same fact shares
    # nearly every token. Only an exact durable user-global copy does; a merely
    # similar record falls through to a capture of the entry itself.
    held = held_durable_user_global_record(omh_home, entry)
    if held:
        return _demoted("already_covered", reading, entry, siblings, fields, held)
    refusal = demotion_refusal_reason(entry)
    if refusal:
        # Checked before capture: a redacted or truncated copy is never written.
        return _demote_result(
            "refused",
            **fields,
            reason=refusal,
            next_action=(
                f"Keep the Hermes entry; split it into entries of at most {DEMOTION_SUMMARY_MAX_CHARS} characters to move it."
                if refusal == "summary_bound_exceeded"
                else "Keep the Hermes entry; OMH would store it redacted."
            ),
        )
    payload = capture_project_memory_candidate(
        omh_home,
        entry,
        record_type="fact",
        on_duplicate="skip",
        source="hermes_demotion",
        source_ref=origin_ref,
        # Hermes memory belongs to one Hermes home, not to a project.
        scope_kind="user-global",
        retention_class="durable",
        tags=["hermes-demotion"],
    )
    if not payload.get("captured"):
        if payload.get("reason") == "duplicate":
            # The exact durable user-global case returned above, so the record
            # admission matched (by normalized summary) differs in case or
            # spacing, is not durable, or is not replay-eligible: it is not an
            # exact copy that comes back the way the Hermes entry would.
            return _demote_result(
                "refused",
                **fields,
                reason="held_record_not_removable",
                record_id=str(payload.get("duplicate_of", "") or "") or None,
                next_action="Keep the Hermes entry; OMH holds only an inexact, non-durable, or non-recallable copy of it.",
            )
        return _demote_result(
            "refused",
            **fields,
            reason=str(payload.get("reason", "") or "not_captured"),
            next_action="Keep the Hermes entry; nothing was moved.",
        )
    candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
    record = payload.get("record") if isinstance(payload.get("record"), dict) else {}
    fields["candidate_id"] = str(candidate.get("candidate_id", "") or "") or None
    if str(candidate.get("summary", "") or record.get("summary", "")) != entry:
        # Not retired here: retiring needs the review workflow, which this
        # process cannot import. Every later call refuses through the
        # source_ref check above, so the Hermes entry is never removed on it.
        return _demote_result("refused", **fields, reason="content_not_intact", next_action="Keep the Hermes entry; OMH stored an altered copy.")
    if not payload.get("auto_approved"):
        return _demote_result(
            "pending_review",
            **fields,
            review_reason=str(payload.get("review_reason", "") or "unknown"),
            next_action="Saved for review; keep the Hermes entry until it is approved.",
        )
    return _demoted("demoted", reading, entry, siblings, fields, str(record.get("record_id", "") or ""))


def _hermes_parsed_entries(path: Path) -> list[str]:
    """The file split exactly as Hermes' store splits it (``_parse_entries``)."""
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return []
    return [part.strip() for part in raw.split(HERMES_MEMORY_DELIMITER) if part.strip()]


def _demoted(
    status: str,
    reading: HermesMemoryFile,
    entry: str,
    siblings: tuple[str, ...],
    fields: dict[str, object],
    record_id: str,
) -> dict[str, object]:
    """OMH holds the entry: hand the model the native remove that frees the space."""
    target = HERMES_MEMORY_TARGETS.get(reading.label, "memory")
    prefix = "📦 OMH moved to long-term memory: " if status == "demoted" else "📦 OMH already holds: "
    return _demote_result(
        status,
        **fields,
        record_id=record_id or None,
        remove_from_hermes={"target": target, "old_text": _unique_old_text(entry, siblings)},
        display_line=_display_line(prefix, entry, DEMOTE_OLD_TEXT_MAX_CHARS),
        next_action=(
            f"Remove the entry with Hermes' memory tool: action='remove', target='{target}', old_text from "
            "remove_from_hermes. Confirm the entry Hermes reports removed is this one."
        ),
    )


def _unique_old_text(entry: str, siblings: tuple[str, ...]) -> str:
    """The shortest-reach `old_text` that selects only this entry in Hermes.

    Hermes strips `old_text`, prefers a whole-entry exact match, and refuses a
    substring two distinct entries contain. A short entry is its own exact
    match; a longer one gets the first window of at most 60 characters no
    other entry contains. An entry wholly inside a sibling has no such window,
    so it is returned whole: correct beats short.
    """
    if len(entry) <= DEMOTE_OLD_TEXT_MAX_CHARS:
        return entry
    others = [sibling for sibling in siblings if sibling != entry]
    for start in range(len(entry) - DEMOTE_OLD_TEXT_MAX_CHARS + 1):
        window = entry[start : start + DEMOTE_OLD_TEXT_MAX_CHARS].strip()
        if window and not any(window in other for other in others):
            return window
    return entry


def _display_line(prefix: str, text: str, limit: int) -> str:
    """Suggested user-facing wording; the model relays it in its own voice."""
    flat = " ".join(text.split())
    return prefix + (flat if len(flat) <= limit else flat[:limit] + "…")


def _demote_result(status: str, **fields: object) -> dict[str, object]:
    return {
        "schema_version": "omh_memory_demote/v1",
        "status": status,
        **fields,
        "claim_boundary": (
            "OMH wrote only its own store. Hermes memory is unchanged until Hermes' own memory tool "
            "removes the entry; this result is not evidence that it did."
        ),
    }


@dataclass(frozen=True)
class _SessionLens:
    """The provider's published confinement for this session, or the fail-closed one."""

    bound: bool
    homes: tuple[Path, ...]
    scopes: list[dict[str, str]]
    session_id: str
    shared_surface: bool
    writes_enabled: bool
    principal_context: dict | None
    executor_target: str
    lens_home: Path
    surface_class: str
    required_scope_kinds: tuple[str, ...]
    # A group conversation's own scope (`memory_session_lens.lens_channel_scope`).
    channel_scope: dict[str, str] | None = None


def _lifecycle(action: str, args: dict, kwargs: dict) -> dict[str, object]:
    """recall / confirm / correct / retire, under the confinement the provider published."""
    try:
        lens = _session_lens(kwargs)
        if action == "recall":
            return _recall(args, lens)
        record_id = str(args.get("record_id", "") or "").strip()
        if not record_id:
            return _lifecycle_result(action, "refused", record_id=None, reason="record_id_required", next_action="Pass the record_id that recall or capture returned.")
        if action == "correct":
            summary = " ".join(str(args.get("summary", "") or "").split())
            tags = args.get("tags")
            refusal = _summary_refusal(summary, [] if tags is None else tags)
            if refusal:
                return _lifecycle_result(action, "refused", record_id=record_id, reason=refusal[0], next_action=refusal[1])
            subject = args.get("subject")
            if not _subject_ok(subject):
                return _lifecycle_result(action, "refused", record_id=record_id, reason="invalid_subject", next_action=SUBJECT_NEXT_ACTION)
        reason = str(args.get("reason", "") or "").strip().lower()
        if action == "retire" and reason not in RETIRE_REASONS:
            return _lifecycle_result(action, "refused", record_id=record_id, reason="unsupported_reason", next_action=f"Pass reason as one of: {', '.join(RETIRE_REASONS)}.")
        if not lens.writes_enabled:
            # Cron jobs and subagents run with provider writes disabled, and a
            # session the provider never described is read as one of them.
            return _lifecycle_result(
                action,
                "refused",
                record_id=record_id,
                reason="writes_disabled" if lens.bound else "session_lens_unavailable",
                next_action="Nothing changed; this session may not write OMH memory.",
            )
        located = _locate_in_session(action, record_id, lens)
        if isinstance(located, dict):
            return located
        home, record = located
        if action == "confirm":
            return _confirm(home, record, lens)
        if action == "correct":
            return _correct(home, record, summary, tags, lens, subject=subject or "")
        return _retire(home, record, reason, lens)
    except Exception as exc:
        # In-process inside Hermes' tool dispatch: a store fault is an error
        # result naming the exception class, never a status that says the
        # record changed, and never a raise into the host. A retire whose
        # archive move already happened reports that itself, before this.
        return _lifecycle_result(
            action,
            "error",
            reason=_safe_error_type(type(exc).__name__),
            next_action="Nothing is confirmed changed. Tell the user the memory update failed.",
        )


def _session_lens(kwargs: dict) -> _SessionLens:
    """Read the confinement the memory provider published for this session.

    The provider owns the decision: its surface class (an operator console, a
    shared surface, or a background run that may not write) and the principal
    context that narrows principal-bound records (`memory_session_lens`). The tool
    finds it by the ``session_id`` Hermes passes every tool call. No session
    id, no published lens, or an unreadable one: a shared surface with no
    principal and no writes, which reaches no identity-unbound record.
    """
    session_id = host_session_id(kwargs)
    omh_home = Path(_home("OMH_HOME", "~/.omh"))
    published = read_session_lens(omh_home, session_id)
    if published is None:
        return _SessionLens(False, (omh_home,), [], session_id, True, False, None, PREFETCH_EXECUTOR_TARGET, omh_home, SURFACE_BACKGROUND, ("project",))
    # Both flags follow the class (`memory_session_lens`), for a lens an
    # earlier provider wrote too.
    surface_class = lens_surface_class(published)
    shared, writes = surface_flags(surface_class)
    principal = published.get("principal_context") if isinstance(published.get("principal_context"), dict) else None
    project_identity = str(published.get("project_identity", "") or "")
    channel = lens_channel_scope(published)
    scopes = prefetch_scope_allowlist(
        project_identity=project_identity,
        session_id=session_id,
        principal_ref=str((principal or {}).get("principal", "") or ""),
        include_legacy_personal=not shared,
        channel_ref=channel["ref"] if channel is not None else "",
    )
    return _SessionLens(
        True,
        tuple(Path(home) for home in published["homes"]),
        scopes,
        session_id,
        shared,
        writes,
        principal,
        str(published.get("executor_target", "") or PREFETCH_EXECUTOR_TARGET),
        omh_home,
        surface_class,
        prefetch_required_scope_kinds(project_identity),
        channel,
    )


def _surface_write_refusal(lens: _SessionLens) -> tuple[str, str] | None:
    """Why ``capture`` or ``demote`` may not write in this session, as (reason, next_action); None when it may.

    The provider's surface class decides (`memory_session_lens`). A shared
    surface does not capture: it is a chat several people write in, and
    nothing tells OMH which of them stated a fact. A verified messenger DM or
    group writes, inside its own binding (`_bound_capture_scope`).
    """
    if not lens.bound:
        return "session_lens_unavailable", "The OMH memory provider has not described this session, so it cannot write OMH memory; tell the user it was not remembered."
    if lens.surface_class == SURFACE_BACKGROUND:
        return "writes_disabled", "This is a background run, such as a cron job, which does not write OMH memory."
    if lens.surface_class == SURFACE_SHARED:
        return (
            "shared_surface_writes_refused",
            "OMH does not write memory from a shared chat surface; tell the user it was not remembered here. It can be saved from the Hermes CLI, TUI or Desktop.",
        )
    return None


def _recall(args: dict, lens: _SessionLens) -> dict[str, object]:
    """The prefetch selector over the prefetch's homes, allowlist and principal."""
    query = " ".join(str(args.get("query", "") or "").split())
    if not query or "\x00" in query or len(query) > RECALL_QUERY_MAX_CHARS:
        return _lifecycle_result("recall", "refused", reason="query_invalid", next_action=f"Pass a query of 1 to {RECALL_QUERY_MAX_CHARS} characters.")
    limit = args.get("limit", RECALL_MAX_LIMIT)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= RECALL_MAX_LIMIT:
        return _lifecycle_result("recall", "refused", reason="limit_invalid", next_action=f"Pass limit between 1 and {RECALL_MAX_LIMIT}.")
    if not lens.bound:
        # Not "nothing matches": the provider never described this session,
        # so nothing was searched at all.
        return _lifecycle_result(
            "recall", "refused", reason="session_lens_unavailable", lens_state="unbound",
            next_action="OMH memory is not available to this session right now; nothing was searched.",
        )
    snapshot = read_record_store_snapshot(lens.homes)
    selection = select_prefetch_records(
        snapshot,
        query,
        allowed_scopes=lens.scopes,
        session_id=lens.session_id,
        executor_target=lens.executor_target,
        limit=limit,
        principal_context=lens.principal_context,
        shared_surface=lens.shared_surface,
        required_scope_kinds=lens.required_scope_kinds,
    )
    rows = []
    for item in selection.pack.get("included_records", [])[:limit]:
        row = {key: item.get(key) for key in ("record_id", "record_type", "summary", "tags", "approved_at")}
        if item.get("resolution_marker"):
            row["resolution_marker"] = item["resolution_marker"]
        if item.get("subject"):
            row["subject"] = item["subject"]
        rows.append(row)
    has_origin = _attach_origins(rows, snapshot.records, lens)
    if rows:
        # What this session has seen is what it may retire while it is live.
        note_session_records(lens.lens_home, lens.session_id, "seen", [str(row["record_id"]) for row in rows])
    next_action = (
        "Use a record_id with confirm, correct, or retire when the conversation settles it."
        if rows
        else "No recallable OMH record matches; nothing was counted."
    )
    if has_origin:
        next_action += " " + RECALL_ORIGIN_NEXT_ACTION
    return _lifecycle_result(
        "recall",
        "found" if rows else "nothing_found",
        records=rows,
        record_count=len(rows),
        scope_status=selection.scope_status,
        lens_state="provider",
        next_action=next_action,
    )


def _attach_origins(rows: list[dict[str, object]], records: tuple[dict, ...], lens: _SessionLens) -> bool:
    """Give each row captured in a Hermes session its ``origin`` handle; True when any row got one.

    Only on a surface that speaks for one conversation's owner or binding: the
    lens already admitted each row there, so the session it points at is one
    this conversation may open. A shared or background lens gets no handle.
    """
    if not rows or lens.surface_class not in ORIGIN_SURFACE_CLASSES:
        return False
    by_id: dict[str, dict] = {}
    for record in records:
        by_id.setdefault(str(record.get("record_id", "")), record)
    hermes_home: Path | None = None
    attached = False
    for row in rows:
        record = by_id.get(str(row.get("record_id", "")), {})
        session_id = origin_session_id(str(record.get("source_ref", "") or ""))
        if not session_id:
            continue
        if hermes_home is None:
            hermes_home = Path(_home("HERMES_HOME", "~/.hermes"))
        captured_at = str(record.get("created_at", "") or record.get("approved_at", "") or "")
        origin = resolve_origin(hermes_home, session_id, captured_at)
        if origin is not None:
            row["origin"] = origin
            attached = True
    return attached


def _locate_in_session(action: str, record_id: str, lens: _SessionLens) -> tuple[Path, dict] | dict[str, object]:
    """The record from the first home that holds it (prefetch's order), or a refusal."""
    if not _SAFE_RECORD_ID.fullmatch(record_id):
        return _lifecycle_result(action, "refused", record_id=None, reason="record_not_found", next_action="Nothing changed. Use a record_id from recall.")
    for home in lens.homes:
        path = memory_record_path(home, record_id)
        if path.is_symlink() or not path.is_file():
            continue
        record, error = read_json_object_result(path)
        if error or not isinstance(record, dict) or str(record.get("record_id", "")) != record_id:
            return _lifecycle_result(action, "refused", record_id=record_id, reason="record_unreadable", next_action="Nothing changed; the record file could not be read.")
        if not _in_session_scope(record, lens):
            # Says nothing about the record beyond its id: it belongs to
            # another project, thread, principal, or executor lens.
            return _lifecycle_result(
                action, "refused", record_id=record_id, reason="record_not_in_scope",
                next_action="Nothing changed; this session's lens does not reach that record.",
            )
        return home, record
    return _lifecycle_result(action, "refused", record_id=record_id, reason="record_not_found", next_action="Nothing changed. It may already be retired or superseded.")


def _in_session_scope(record: dict, lens: _SessionLens) -> bool:
    """The selector's lens gates, in its order: principal, scope, perspective.

    Lifecycle state (expired, stale, superseded) is not a lens gate: each
    action refuses what it cannot act on, as the operator verb does.
    """
    scopes, status = resolve_scope_allowlist(lens.scopes, required_scope_kinds=lens.required_scope_kinds)
    if status != "resolved":
        return False
    channels = tuple(scope for scope in scopes if scope["kind"] == "channel")
    if not principal_recall_decision(record, lens.principal_context, shared_surface=lens.shared_surface, channel_scopes=channels)["allowed"]:
        return False
    if record.get("scope") not in scopes:
        return False
    return _record_perspective_matches(record, observer=None, observed=lens.executor_target)


def _confirm(home: Path, located: dict, lens: _SessionLens) -> dict[str, object]:
    """`omh memory confirm`'s rewrite, plus at most one use per record per session.

    The deadline arithmetic is the operator verb's: the cadence stored on the
    record, else the policy default, else 90 days; an open record is answered
    "resolved". Two differences. A record with no review deadline (a durable
    capture, the model's default) is not refused, because the use is still
    worth counting; nothing on the record is rewritten for it. And there is
    no explicit date or day count: the model does not pin deadlines.
    """
    record_id = str(located.get("record_id", ""))
    stamp = utc_now()
    moment = datetime.now(timezone.utc).replace(microsecond=0)
    with memory_store_lock(memory_index_path(home)):
        record, error = read_json_object_result(memory_record_path(home, record_id))
        if error or not isinstance(record, dict):
            return _lifecycle_result("confirm", "refused", record_id=record_id, reason="record_not_found", next_action="Nothing changed.")
        refusal = _live_record_refusal(record, moment)
        if refusal:
            return _lifecycle_result("confirm", "refused", record_id=record_id, reason=refusal, next_action=_CONFIRM_REFUSAL_NEXT_ACTION.get(refusal, "Nothing changed."))
        staleness = _record_staleness(record, now=moment)
        if str(staleness.get("source_state", "")) in {"changed", "unreadable"}:
            return _lifecycle_result(
                "confirm", "refused", record_id=record_id, reason="source_requires_correction",
                next_action="Nothing changed; its cited source moved, so correct or retire it instead.",
            )
        previous_due = str(staleness.get("review_due_at", "") or "")
        was_open = str(staleness.get("resolution", "")) == "open"
        new_deadline, days, cadence_reset = previous_due, None, False
        if previous_due or was_open:
            if previous_due:
                stored = record.get("staleness", {}).get("stale_after_days") if isinstance(record.get("staleness"), dict) else None
                if isinstance(stored, int) and not isinstance(stored, bool) and stored > 0:
                    days = stored
                else:
                    days = _cadence_value(read_project_memory_policy(home), "stale_after_days_default") or _REVIEW_DEFAULT_DAYS
                    cadence_reset = True
                new_deadline = _days_after(stamp, days)
            else:
                new_deadline = ""
            revalidation = record.get("revalidation") if isinstance(record.get("revalidation"), dict) else {}
            updated = {
                **{key: value for key, value in revalidation.items() if key != "deadline"},
                **({"deadline": new_deadline} if new_deadline else {}),
                "confirmed_at": stamp,
                "confirmed_by": MODEL_CAPTURE_SOURCE,
            }
            stored_staleness = record.get("staleness") if isinstance(record.get("staleness"), dict) else {}
            write_project_memory_record(
                home,
                {
                    **record,
                    "revalidation": updated,
                    "staleness": {
                        **_staleness_projection(updated),
                        "stale_after_days": days,
                        **_resolved_staleness_fields(stored_staleness, resolved_at=stamp),
                    },
                    "updated_at": stamp,
                },
            )
            write_memory_index_unlocked(home, updated_at=stamp)
    first_this_session = bool(note_session_records(lens.lens_home, lens.session_id, "confirmed", [record_id]))
    return _lifecycle_result(
        "confirm",
        "confirmed",
        record_id=record_id,
        review_due_at=new_deadline or None,
        previous_review_due_at=previous_due or None,
        deadline_renewed=bool(previous_due),
        was_stale=str(staleness.get("state", "")) == "stale",
        was_open=was_open,
        cadence_reset=cadence_reset,
        # One confirmation per session is one use: re-confirming the same
        # record in a session must not inflate the ranking's usage signal.
        used_recorded=_count_used(home, record_id, stamp) if first_this_session else False,
        used_already_counted_this_session=not first_this_session,
        next_action=(
            f"Renewed; it recalls normally until {new_deadline}." if new_deadline
            else "Counted as used; it carries no review deadline, so nothing else changed."
        ),
    )


_CONFIRM_REFUSAL_NEXT_ACTION = {
    "retention_expired": "Nothing changed; it expired. Capture the fact again if it still holds.",
    "unresolved_expired": "Nothing changed; the open question expired unanswered. Retire it or capture the answer.",
}


def _lifecycle_schema_supported(record: dict) -> bool:
    """A reviewed v2 record, or a person's own v3 record: user scope, its subject the only audience.

    A person's DM memory is v3 and bound to that person; the lens already
    admitted it for this principal alone (`_in_session_scope`). A v3 record
    shared with an explicit audience is not the actor's to rewrite, and its
    correction would come back identity-unbound.
    """
    schema = record.get("schema_version")
    if schema == PROJECT_MEMORY_RECORD_SCHEMA_VERSION:
        return True
    scope = record.get("scope") if isinstance(record.get("scope"), dict) else {}
    identity = record.get("identity") if isinstance(record.get("identity"), dict) else {}
    audience = identity.get("audience") if isinstance(identity.get("audience"), dict) else {}
    return schema == "project_memory_record/v3" and scope.get("kind") == "user" and audience.get("kind") == "subject_only"


def _live_record_refusal(record: dict, moment: datetime) -> str:
    """The refusals every lifecycle write shares with the operator verbs."""
    if not _lifecycle_schema_supported(record):
        return "unsupported_record_schema"
    if str(record.get("superseded_by", "") or ""):
        return "superseded"
    staleness = _record_staleness(record, now=moment)
    if str(staleness.get("state", "")) == "expired":
        return "unresolved_expired" if str(staleness.get("reason", "")) == "unresolved_expired" else "retention_expired"
    return ""


def _resolved_staleness_fields(staleness: dict, *, resolved_at: str) -> dict[str, object]:
    """Carry an open/resolved marker through a rewrite, answering an open one.

    Vendored from the control plane's helper of the same name (confirm and
    correct are the only writers of ``resolved``): the open ceiling goes with
    the answer and ``open_since`` stays as the record of how long it was open.
    """
    resolution = _record_resolution(staleness)
    if not resolution:
        return {}
    fields: dict[str, object] = {"resolution": "resolved", "open_since": str(staleness.get("open_since", "") or "")}
    fields["resolved_at"] = str(resolved_at) if resolution == "open" else str(staleness.get("resolved_at", "") or resolved_at)
    return fields


def _count_used(home: Path, record_id: str, stamp: str) -> bool:
    """One use in ``usage.json``; a lost count is reported, never raised."""
    try:
        return record_used(home, [record_id], now=stamp) == 1
    except OSError:
        return False


def _correction_carryover(record: dict, retention: str) -> dict[str, object]:
    """What a correction keeps from the record it replaces, in capture's own arguments.

    Perspective, cited source, the review cadence day count, and a retention
    TTL day count. Absolute dates are not carried: capture refuses
    a past one, and a correction is a new statement with its own clock.
    """
    carried: dict[str, object] = {}
    perspective = record.get("perspective") if isinstance(record.get("perspective"), dict) else {}
    if str(perspective.get("observed", "") or ""):
        carried["observer"] = str(perspective.get("observer", "") or "") or None
        carried["observed"] = str(perspective["observed"])
    if str(record.get("source_ref", "") or ""):
        carried["source_ref"] = str(record["source_ref"])
    staleness = record.get("staleness") if isinstance(record.get("staleness"), dict) else {}
    days = staleness.get("stale_after_days")
    # Approved records do not keep `cadence_source`, so the stored day count is
    # carried as it stands; for a defaulted cadence that is the same number.
    if retention != "volatile" and isinstance(days, int) and not isinstance(days, bool) and days > 0:
        carried["stale_after_days"] = days
    ttl = record.get("ttl") if isinstance(record.get("ttl"), dict) else {}
    ttl_days = ttl.get("ttl_days")
    if retention != "durable" and isinstance(ttl_days, int) and not isinstance(ttl_days, bool) and ttl_days > 0:
        carried["ttl_days"] = ttl_days
    return carried


def _correct(home: Path, record: dict, summary: str, tags: object, lens: _SessionLens, *, subject: str = "") -> dict[str, object]:
    """Admit the corrected fact like a capture, linked to the record it replaces.

    The candidate carries ``derived_from`` and ``correction_of`` naming the old
    record, so whichever approval admits it -- auto-safe now, or an operator's
    review later -- supersedes the old record inside that approval's store
    lock (`_supersede_corrected_record_unlocked`). Until then the old record
    stays active: a pending correction never makes the fact vanish. The
    subject is the one given, else the old record's, so a corrected value
    stays in its subject's group.
    """
    record_id = str(record.get("record_id", ""))
    refusal = _live_record_refusal(record, datetime.now(timezone.utc))
    if refusal in ("unsupported_record_schema", "superseded"):
        return _lifecycle_result("correct", "refused", record_id=record_id, reason=refusal, next_action="Nothing changed.")
    scope = record.get("scope") if isinstance(record.get("scope"), dict) else {}
    retention = _retention_class(record) or "durable"
    try:
        payload = capture_project_memory_candidate(
            home,
            summary,
            record_type=str(record.get("record_type", "") or "fact"),
            retention_class=retention,
            on_duplicate="skip",
            source=MODEL_CAPTURE_SOURCE,
            scope_kind=str(scope.get("kind", "")),
            scope_ref=str(scope.get("ref", "")),
            tags=list(tags) if isinstance(tags, list) else [str(tag) for tag in record.get("tags", []) if isinstance(tag, str)],
            derived_from=[record_id],
            correction_of=record_id,
            correction_revision=record.get("revision"),
            principal_context=lens.principal_context if scope.get("kind") == "user" else None,
            subject=subject or record_subject(record),
            **_correction_carryover(record, retention),
        )
    except ValueError as exc:
        if str(exc).startswith("derived-from record"):
            # Admission re-reads the old record before writing anything; it
            # was retired or corrected by a concurrent call in between.
            return _lifecycle_result(
                "correct", "refused", record_id=record_id, reason="record_not_found",
                next_action="Nothing was saved; the record was retired or corrected meanwhile.",
            )
        raise
    if not payload.get("captured"):
        reason = str(payload.get("reason", "") or "not_captured")
        if reason == "duplicate":
            duplicate_of = str(payload.get("duplicate_of", "") or "")
            if duplicate_of == record_id:
                return _lifecycle_result("correct", "refused", record_id=record_id, reason="unchanged", next_action="Nothing changed; the record already says this.")
            return _correct_to_held(home, record, duplicate_of, summary, lens, subject=subject or record_subject(record))
        return _lifecycle_result(
            "correct",
            "refused",
            record_id=record_id,
            reason=reason,
            **({"instruction_cue": str(payload["instruction_cue"])} if payload.get("instruction_cue") else {}),
            next_action=str(payload.get("next_action", "") or "") or "Nothing was saved and the record is unchanged.",
        )
    candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
    if not payload.get("auto_approved"):
        return _lifecycle_result(
            "correct",
            "pending_review",
            record_id=record_id,
            candidate_id=str(candidate.get("candidate_id", "") or "") or None,
            review_reason=str(payload.get("review_reason", "") or "unknown"),
            next_action=(
                "Saved for operator review; the old record stays active and is replaced when the correction is "
                "approved. For relative_time_phrase, correct it again with an absolute date."
            ),
        )
    successor = payload.get("record") if isinstance(payload.get("record"), dict) else {}
    new_id = str(successor.get("record_id", "")) or None
    supersession = payload.get("supersession") if isinstance(payload.get("supersession"), dict) else {}
    if supersession.get("state") != "superseded":
        # Saved, but the old record was already gone or already replaced when
        # the approval reached it -- a concurrent retire or correct.
        return _lifecycle_result(
            "correct",
            "corrected",
            record_id=new_id,
            superseded_record_id=None,
            supersede_skipped=str(supersession.get("reason", "") or "unknown"),
            receipt_state=str(payload.get("receipt_state", "") or "") or None,
            display_line=_display_line("✏️ OMH corrected: ", str(successor.get("summary", "") or summary), 80),
            next_action=f"Saved as {new_id}; the old record was already retired or replaced by another call, so nothing was superseded.",
        )
    return _lifecycle_result(
        "correct",
        "corrected",
        record_id=new_id,
        superseded_record_id=record_id,
        receipt_state=str(payload.get("receipt_state", "") or "") or None,
        display_line=_display_line("✏️ OMH corrected: ", str(successor.get("summary", "") or summary), 80),
        next_action=f"The old revision is kept under history/ and no longer recalls; {new_id} replaces it.",
    )


_RETENTION_RANK = {"volatile": 0, "standard": 1, "durable": 2}


def _record_expiry(record: dict) -> datetime | None:
    """A record's retention expiry, or None when it does not expire."""
    retention = record.get("retention") if isinstance(record.get("retention"), dict) else {}
    ttl = record.get("ttl") if isinstance(record.get("ttl"), dict) else {}
    value = str(retention.get("expires_at", "") or ttl.get("expires_at", "") or "")
    return _parse_utc_naive_as_utc(value) if value else None


def _held_replacement_refusal(record: dict, held: dict, held_id: str, subject: str, lens: _SessionLens) -> str:
    """Why the held record cannot stand in for the corrected one, or "" when it can.

    Superseding into a record that cannot be served makes the fact vanish, so
    the held record must recall under this session's lens now (eligible, not
    archived, not itself replaced by a newer subject value), keep it at least
    as long (retention class and expiry), and not declare a different subject
    than the correction carries.
    """
    if held_id not in _recallable_ids(lens):
        return "held_not_recallable"
    if _RETENTION_RANK.get(_retention_class(held), -1) < _RETENTION_RANK.get(_retention_class(record), -1):
        return "held_retention_shorter"
    held_expiry, old_expiry = _record_expiry(held), _record_expiry(record)
    if held_expiry is not None and (old_expiry is None or held_expiry < old_expiry):
        return "held_expires_sooner"
    held_subject = record_subject(held)
    if subject and held_subject and held_subject != subject:
        return "subject_conflict"
    return ""


def _correct_to_held(home: Path, record: dict, held_id: str, summary: str, lens: _SessionLens, *, subject: str = "") -> dict[str, object]:
    """Finish a correction whose corrected text another record already holds.

    This is the step capture's subject and similar-wording hints point at: the
    new fact was saved first, so correcting the old record to that same text
    meets it in admission's duplicate check, which looks only inside the old
    record's own confinement. When the held record can stand in
    (`_held_replacement_refusal`), it is the replacement: the old revision
    moves to ``history/`` with ``superseded_by`` naming it, under the store
    lock, pinned to the revision this call read, and the correction's subject
    is written onto the held record when it has none. Nothing new is captured.
    Otherwise nothing changes and the result says which record holds the text.
    """
    record_id = str(record.get("record_id", ""))
    held, error = read_json_object_result(memory_record_path(home, held_id))
    refusal = "record_absent" if error or not isinstance(held, dict) else _held_replacement_refusal(record, held, held_id, subject, lens)
    if refusal:
        return _lifecycle_result(
            "correct", "already_remembered", record_id=record_id, duplicate_of=held_id, supersede_skipped=refusal,
            next_action=f"The corrected fact is already held as {held_id}; retire {record_id} with reason='superseded' if it no longer holds.",
        )
    stamp = utc_now()
    with memory_store_lock(memory_index_path(home)):
        successor, error = read_json_object_result(memory_record_path(home, held_id))
        if error or not isinstance(successor, dict):
            supersession: dict[str, str] = {"state": "skipped", "reason": "record_absent"}
        else:
            supersession = _supersede_corrected_record_unlocked(home, record_id, successor, stamp=stamp, revision=record.get("revision"))
            if supersession.get("state") == "superseded":
                if subject and not record_subject(successor):
                    # Not part of the payload digest, so the review linkage stands.
                    successor = {**successor, "subject": subject}
                    write_project_memory_record(home, successor)
                write_memory_index_unlocked(home, updated_at=stamp)
    if supersession.get("state") != "superseded":
        return _lifecycle_result(
            "correct", "already_remembered", record_id=record_id, duplicate_of=held_id,
            supersede_skipped=str(supersession.get("reason", "") or "unknown"),
            next_action=f"The corrected fact is already held as {held_id}; {record_id} was not changed.",
        )
    return _lifecycle_result(
        "correct",
        "corrected",
        record_id=held_id,
        superseded_record_id=record_id,
        replacement="already_held",
        display_line=_display_line("✏️ OMH corrected: ", str(successor.get("summary", "") or summary), 80),
        next_action=f"{held_id} already said this and now replaces {record_id}; the old revision is kept under history/ and no longer recalls.",
    )


def _retire(home: Path, located: dict, reason: str, lens: _SessionLens) -> dict[str, object]:
    """`omh memory retire --apply`'s move for one record: archive, journal, candidate flip, index.

    The operator retire archives only an expired or open record. The model
    may also retire a live one, but only one this session was served or
    recalled: the conversation that settled it is the one that saw it.
    """
    record_id = str(located.get("record_id", ""))
    stamp = utc_now()
    with memory_store_lock(memory_index_path(home)):
        source = memory_record_path(home, record_id)
        record, error = read_json_object_result(source)
        if error or not isinstance(record, dict) or source.is_symlink():
            return _lifecycle_result("retire", "refused", record_id=record_id, reason="record_not_found", next_action="Nothing changed.")
        if not _lifecycle_schema_supported(record):
            return _lifecycle_result("retire", "refused", record_id=record_id, reason="unsupported_record_schema", next_action="Nothing changed.")
        expired = str(_record_staleness(record, now=datetime.now(timezone.utc)).get("state", "")) == "expired"
        published = read_session_lens(lens.lens_home, lens.session_id) or {}
        if not expired and record_id not in [str(item) for item in published.get("seen", [])]:
            return _lifecycle_result(
                "retire", "refused", record_id=record_id, reason="record_not_seen_this_session",
                next_action="Nothing changed; recall it first so the conversation sees what it retires.",
            )
        archive = memory_dir(home) / "archive"
        ensure_private_dir(archive)
        # The operator retire's archive name, so its reconciliation pass
        # pairs this file with the journal line below.
        destination = archive / f"{record_id}.{stamp.replace('-', '').replace(':', '')}.json"
        assert_under_memory_root(home, destination)
        if destination.exists():
            return _lifecycle_result("retire", "refused", record_id=record_id, reason="archive_collision", next_action="Nothing changed; retry in a second.")
        _with_windows_retry(lambda: source.replace(destination))
        try:
            _with_windows_retry(lambda: destination.chmod(0o600))
            ttl = record.get("ttl") if isinstance(record.get("ttl"), dict) else {}
            entry = {
                "schema_version": "omh_memory_retirement_journal/v1",
                "record_id": record_id,
                "retired_at": stamp,
                "expires_at": str(ttl.get("expires_at", "") or ""),
                "reason": reason,
                "retired_by": MODEL_CAPTURE_SOURCE,
                "session_id": lens.session_id,
                "redaction_policy": "metadata_only",
                "claim_boundary": (
                    "A retirement journal line records that OMH moved one of its own records to its local "
                    "archive. It is not a deletion and not Hermes internal-memory evidence."
                ),
            }
            journal = archive / "retirements.jsonl"
            with memory_store_lock(journal):
                with journal.open("a", encoding="utf-8", newline="") as handle:
                    handle.write(json.dumps(entry, sort_keys=True) + "\n")
            for candidate in read_project_memory_candidates(home):
                # A still-approved source candidate would let a re-approval
                # resurrect the record silently, as in the operator retire.
                if str(candidate.get("record_id", "")) == record_id and str(candidate.get("status", "")) == "approved":
                    write_project_memory_candidate_unlocked(home, {**candidate, "status": "retired", "retired_at": stamp})
            write_memory_index_unlocked(home, updated_at=stamp)
        except (OSError, ValueError) as exc:
            # The move already happened: the record no longer recalls. Say so,
            # and leave the bookkeeping to the operator retire's reconciliation.
            return _lifecycle_result(
                "retire",
                "error",
                record_id=record_id,
                reason=_safe_error_type(type(exc).__name__),
                archived_as=destination.name,
                next_action=(
                    "The record was archived and no longer recalls, but its journal, candidate, or index update "
                    "failed; `omh memory retire --apply` reconciles it."
                ),
            )
    return _lifecycle_result(
        "retire",
        "retired",
        record_id=record_id,
        reason=reason,
        archived_as=destination.name,
        display_line=_display_line("🗄️ OMH retired: ", str(record.get("summary", "") or ""), 60),
        next_action="Archived, not deleted; it no longer recalls. An operator can restore it with `omh memory restore`.",
    )


_LIFECYCLE_CLAIM_BOUNDARIES = {
    "recall": (
        "Recall lists OMH's own records under the lens the memory provider published for this session, as "
        "prefetch ranks them; it counts nothing as used and is not evidence that a record is true."
    ),
    "confirm": (
        "Confirm rewrites only OMH-local review metadata and the usage counter; the record's content, "
        "admission, and review are untouched, and Hermes memory is unchanged."
    ),
    "correct": (
        "OMH wrote only its own store, and the old revision is kept, never deleted. This is not evidence "
        "that a later session recalls the new record, and Hermes memory is unchanged."
    ),
    "retire": "Retire moves an OMH record into OMH's local archive; it never deletes, and Hermes memory is unchanged.",
}


_LIFECYCLE_SCHEMA_VERSIONS = {
    "recall": "omh_memory_recall/v1",
    "confirm": "omh_memory_confirm/v1",
    "correct": "omh_memory_correct/v1",
    "retire": "omh_memory_retire/v1",
}


def _lifecycle_result(action: str, status: str, **fields: object) -> dict[str, object]:
    return {
        "schema_version": _LIFECYCLE_SCHEMA_VERSIONS[action],
        "status": status,
        **fields,
        "claim_boundary": _LIFECYCLE_CLAIM_BOUNDARIES[action],
    }


def _session_cwd(kwargs: dict) -> Path | None:
    """A host-supplied cwd, else Hermes' logical working directory, else None."""
    supplied = kwargs.get("cwd")
    try:
        if supplied:
            return runtime_paths.expand_path(supplied)
        return runtime_paths.runtime_cwd()
    except (OSError, ValueError):
        return None


def _unknown_action(action: str) -> dict[str, object]:
    return {
        "schema_version": "omh_memory_unknown_action/v1",
        "status": "unavailable",
        "reason": "unknown_action",
        "requested_action": action,
        "supported_actions": list(MEMORY_ACTIONS),
        "next_action": f"Retry with one of: {', '.join(MEMORY_ACTIONS)}.",
        "claim_boundary": "No memory view was produced. This is not evidence about memory state.",
    }


def _home(variable: str, default: str) -> str:
    return str(runtime_paths.default_omh_home() if variable == "OMH_HOME" else runtime_paths.default_hermes_home())


def _unavailable(reason: str) -> dict[str, object]:
    return {
        "schema_version": "omh_memory_bridge_unavailable/v1",
        "status": "unavailable",
        "reason": reason,
        "next_action": "Run `omh memory status` locally, or `omh doctor` if OMH may not be installed.",
        "claim_boundary": (
            "No memory comparison was produced. This is not evidence that Hermes memory is empty, "
            "in sync, or readable."
        ),
    }


__all__ = [
    "MEMORY_ACTIONS", "OMH_MEMORY_SCHEMA", "omh_memory_handler", "read_memory_block",
    "REMEMBER_TOOL_NAME", "REMEMBER_TOOL_SCHEMA", "omh_remember_handler",
]

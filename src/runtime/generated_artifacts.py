"""Which locally generated artifact is current, and which one is safe to remove (issue #835).

OMH writes plans, plan variants, operation reports, and skill drafts into local
stores and never takes any of them back. A user looking at four files with
similar names has no way to tell which one a handoff still points at, which one
was replaced, or which one could go. This module answers that from what the
producers already wrote.

A read-side projection, not new producer metadata
-------------------------------------------------

Nothing here is stamped onto an artifact at write time. `generated_artifact/v1`
is derived on read from data the producing workflows already persist: the file
itself (its digest and, for plans, the timestamp its own writer put in the
name), the producer's status word, the identity field that says which artifact
is another revision of the same thing, and every local file that names it. No
producing workflow is touched, so an artifact written before this module existed
projects exactly like one written after.

What "superseded" means here
----------------------------

Each kind declares a *revision line* -- the field that says two artifacts are
two revisions of one thing -- and an *ordering key* that says which came second:

    hermes_plan         line = task_statement_sha256   order = the stamp its writer put in the filename
    operation_artifact  line = surface|kind|title      order = created_at
    plan_variant        line = parent digest|name      order = created_at
    skill_draft         line = proposed_skill_name     order = created_at

The newest member of a line is `current`; every earlier member is `superseded`
and names the artifact that replaced it. A plan whose own frontmatter already
says `superseded` is superseded regardless of position.

Ordering fails closed. If two members of one line carry no readable creation
time, or carry the same one, nothing in the line is called superseded --
guessing which of two files replaced the other is exactly the mistake that would
put a live artifact on a cleanup list.

Deletion
--------

There is none. `build_generated_artifact_cleanup_preview` is a dry run: it
reports what *would* be eligible and why, and this module contains no unlink,
no remove, no rmtree, and no write of any kind.
`tests/test_generated_artifact_cleanup.py` walks this module's AST and fails if
one appears.

Cleanup eligibility
-------------------

An artifact is eligible only when all three hold, and the record says which one
failed when it is not:

1. it is superseded -- a current artifact is never eligible;
2. no local artifact references it -- see the scan below;
3. its retention window has ended, measured from its creation time against the
   caller's `now`.

"Referenced" is a real reverse scan, not a guess. Every reference-source file is
read and every string in it is collected, so a handoff context pack that pins a
plan by path, a run's coding delegation that pins it by path and digest, a
variant that names its parent plan, and a report that cites another artifact all
count. Two matches are deliberately not counted: an artifact never references
itself, and a content digest that more than one stored artifact answers to
identifies none of them, so it is not a reference key for any of them (see
`_ambiguous_digests` -- re-planning one task writes byte-identical files).

The observation journal is deliberately *not* a reference source. It is an
append-only history, so every artifact ever written appears in it; treating
history as a live pin would make the eligible set empty by construction and the
whole preview useless. A reference here means something that would be left
dangling if the file went away.

Determinism
-----------

`now` is a required parameter, never a clock read, because the retention verdict
depends on it and a projection whose answer changes between two calls in the
same second cannot be compared or tested. Nothing else in a record comes from
the clock.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from ..plugin_bundle.omh.memory_governance import build_retention
from ..system.local_store import read_json_object_result
from ..system.paths import OmhPaths, project_artifact_dir
from ..workflows.hermes_planning import read_hermes_plan_artifact
from ..workflows.operations import SURFACES as OPERATION_SURFACES
from ..plugin_bundle.omh.iso_datetime import strict_fromisoformat


GENERATED_ARTIFACT_SCHEMA_VERSION = "generated_artifact/v1"
GENERATED_ARTIFACT_REFERENCE_SCHEMA_VERSION = "generated_artifact_reference/v1"
GENERATED_ARTIFACT_CLEANUP_PREVIEW_SCHEMA_VERSION = "generated_artifact_cleanup_preview/v1"

# The kinds whose store is discoverable, whose revision line is a field the
# producer already writes, and whose ordering key exists on the record. A kind
# missing any of the three cannot answer AC1 and is left out rather than
# guessed at -- see `UNSUPPORTED_ARTIFACT_KIND_REASONS`.
GENERATED_ARTIFACT_KINDS = ("hermes_plan", "operation_artifact", "plan_variant", "skill_draft")
LIFECYCLE_STATES = ("current", "superseded")

# Local artifact families read to answer "does anything still point at this?".
# Each one holds a pin that would dangle if the artifact it names were removed.
GENERATED_ARTIFACT_REFERENCE_KINDS = (
    "coding_delegation",
    "handoff_context_pack",
    "operation_artifact",
    "plan_variant",
    "role_context_pack",
)

# Where an artifact's provenance actually comes from: the symbol that writes it.
# `tests/test_generated_artifact_cleanup.py` imports every one of these, so a
# renamed or deleted writer fails the suite instead of leaving this table
# claiming a producer that no longer exists.
GENERATED_ARTIFACT_PRODUCERS = {
    "hermes_plan": "omh.workflows.hermes_planning.write_hermes_plan",
    "operation_artifact": "omh.workflows.operations.write_operation_artifact",
    "plan_variant": "omh.workflows.plan_variants.write_plan_variant",
    "skill_draft": "omh.workflows.skill_draft.write_skill_draft",
}

# Named so the gap is a documented boundary rather than an omission a reader has
# to notice. Both families are still scanned as reference *sources* -- a pinned
# pack is what keeps a plan off the eligible list -- they just cannot be told
# apart by revision.
UNSUPPORTED_ARTIFACT_KIND_REASONS = {
    "role_context_pack": (
        "A role context pack is content-addressed and deliberately carries no timestamp and no successor "
        "link, so nothing on the record says which of two packs for one scope came second."
    ),
    "handoff_context_pack": (
        "A plan handoff context pack is named after the plan it serves and rewritten in place, so one plan "
        "never has two revisions of it on disk to compare."
    ),
}

# The producer's own status word, when it has one, and what it means for
# lifecycle. Only `superseded` forces the verdict: `cancelled` and `blocked` say
# the work stopped, not that something replaced it.
PLAN_STATUS_SUPERSEDED = "superseded"

# The retention policy every generated artifact is measured against, built
# through the same `build_retention` the memory lane uses so there is one
# retention shape in the tree. `episode` is the record type because a generated
# artifact is the output of one episode of work, and it is the one record type
# whose standard class carries a default window at all.
DEFAULT_RETENTION_CLASS = "standard"
DEFAULT_RETENTION_RECORD_TYPE = "episode"
DEFAULT_RETENTION_DAYS = 30

# Scan bounds. A projection that walks an unbounded store turns a status check
# into an unbounded read, which is the cost `show_run` already bounds for run
# history. `--all` lifts the artifact bound; the reference scan stays bounded
# because a missed reference source can only ever *add* an artifact to the
# eligible list, and that is the one direction this feature must not fail in --
# so the bound is high enough to cover a real store and the payload says when it
# was hit.
DEFAULT_ARTIFACT_SCAN_LIMIT = 200
MAX_REFERENCE_SOURCE_FILES = 2000
MAX_REFERENCE_TOKEN_LENGTH = 512
MAX_REFERENCE_SCAN_DEPTH = 12

GENERATED_ARTIFACT_KEYS = (
    "schema_version",
    "artifact_kind",
    "artifact_id",
    "path",
    "content_digest",
    "source_schema_version",
    "producer",
    "created_at",
    "declared_status",
    "revision_line",
    "revision_index",
    "revision_count",
    "lifecycle",
    "replaces",
    "replaced_by",
    "referenced_by",
    "reference_count",
    "retention_class",
    "retention_days",
    "retention_expires_at",
    "retention_reason",
    "cleanup_eligible",
    "cleanup_reason",
)
GENERATED_ARTIFACT_REFERENCE_KEYS = ("schema_version", "ref_kind", "ref_path", "matched_on")
GENERATED_ARTIFACT_REFERENCE_MATCHES = ("path", "artifact_id", "content_digest")
GENERATED_ARTIFACT_CLEANUP_PREVIEW_KEYS = (
    "schema_version",
    "evaluated_at",
    "retention_days",
    "dry_run",
    "artifact_count",
    "eligible",
    "eligible_count",
    "retained",
    "retained_count",
    "kinds",
    "unsupported_kinds",
    "store_paths",
    "reference_source_count",
    "scan_truncated",
    "claim_boundary",
    "next_action",
)

CLEANUP_PREVIEW_CLAIM_BOUNDARY = (
    "This cleanup preview is a dry run over local files. It deletes nothing, moves nothing, and writes "
    "nothing: the module that builds it has no removal path at all, and an artifact that is current, "
    "referenced by another local artifact, or still inside its retention window is never listed as "
    "eligible. Every record here is a read-side projection and prepared metadata, not execution, review, "
    "CI, merge-readiness, or merge evidence."
)
CLEANUP_PREVIEW_NEXT_ACTION = (
    "Read the eligible list and remove those files by hand if you want them gone. OMH does not remove them."
)


def project_generated_artifacts(
    paths: OmhPaths,
    *,
    now: datetime,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    limit: int | None = DEFAULT_ARTIFACT_SCAN_LIMIT,
) -> list[dict[str, Any]]:
    """Every locally generated artifact, with its provenance, revision, and verdict.

    `now` is required: the retention verdict is measured against it, and reading
    a clock in here would make two calls in the same second incomparable.
    """
    if isinstance(retention_days, bool) or not isinstance(retention_days, int) or retention_days < 1:
        raise ValueError("retention_days must be a positive integer")
    current = _as_utc(now)
    found = _scan_artifacts(paths, limit=limit)
    references = _reference_index(paths)
    ambiguous = _ambiguous_digests(found)
    records: list[dict[str, Any]] = []
    for kind in GENERATED_ARTIFACT_KINDS:
        for member in _resolve_revision_lines(found.get(kind, [])):
            records.append(_build_record(member, references, ambiguous, current, retention_days))
    records.sort(key=lambda record: (str(record["artifact_kind"]), str(record["path"])))
    return records


def build_generated_artifact_cleanup_preview(
    paths: OmhPaths,
    *,
    now: datetime,
    retention_days: int = DEFAULT_RETENTION_DAYS,
    limit: int | None = DEFAULT_ARTIFACT_SCAN_LIMIT,
) -> dict[str, Any]:
    """A dry-run cleanup list. Nothing is removed here or anywhere downstream."""
    records = project_generated_artifacts(paths, now=now, retention_days=retention_days, limit=limit)
    eligible = [record for record in records if record["cleanup_eligible"]]
    retained = [record for record in records if not record["cleanup_eligible"]]
    # Directory listings only -- `_reference_source_files` never opens a file --
    # so counting the scan a second time costs a re-glob of a bounded set, not a
    # second read of every pin.
    sources = list(_reference_source_files(paths))
    payload = {
        "schema_version": GENERATED_ARTIFACT_CLEANUP_PREVIEW_SCHEMA_VERSION,
        "evaluated_at": _stamp(_as_utc(now)),
        "retention_days": retention_days,
        "dry_run": True,
        "artifact_count": len(records),
        "eligible": eligible,
        "eligible_count": len(eligible),
        "retained": retained,
        "retained_count": len(retained),
        "kinds": list(GENERATED_ARTIFACT_KINDS),
        "unsupported_kinds": [
            {"artifact_kind": kind, "reason": reason}
            for kind, reason in sorted(UNSUPPORTED_ARTIFACT_KIND_REASONS.items())
        ],
        "store_paths": generated_artifact_store_paths(paths),
        "reference_source_count": len(sources),
        "scan_truncated": len(sources) >= MAX_REFERENCE_SOURCE_FILES,
        "claim_boundary": CLEANUP_PREVIEW_CLAIM_BOUNDARY,
        "next_action": CLEANUP_PREVIEW_NEXT_ACTION,
    }
    return payload


def generated_artifact_store_paths(paths: OmhPaths) -> dict[str, str]:
    """Where each supported kind is read from, as the projection resolved it."""
    return {
        "hermes_plan": str(_plans_dir(paths)),
        "operation_artifact": str(paths.operations_dir),
        "plan_variant": str(_plan_variants_dir(paths)),
        "skill_draft": str(paths.learning_skill_drafts_dir),
    }


def validate_generated_artifact(record: Any) -> list[str]:
    """Every contract violation in one pass; empty means the record is valid.

    The three cleanup invariants are checked here as well as computed, so a
    hand-built or transport-mangled record claiming eligibility for a current or
    referenced artifact is refused rather than rendered.
    """
    if not isinstance(record, dict):
        return ["generated artifact must be an object"]
    errors = _key_set_errors(record, GENERATED_ARTIFACT_KEYS, "generated_artifact")
    if record.get("schema_version") != GENERATED_ARTIFACT_SCHEMA_VERSION:
        errors.append(f"schema_version must be {GENERATED_ARTIFACT_SCHEMA_VERSION}")
    if record.get("artifact_kind") not in GENERATED_ARTIFACT_KINDS:
        errors.append("artifact_kind is unsupported")
    if not str(record.get("artifact_id", "")).strip():
        errors.append("artifact_id must not be empty")
    if not str(record.get("path", "")).strip():
        errors.append("path must not be empty")
    if record.get("lifecycle") not in LIFECYCLE_STATES:
        errors.append("lifecycle must be current or superseded")
    if not isinstance(record.get("cleanup_eligible"), bool):
        errors.append("cleanup_eligible must be a boolean")
    # AC2, as a validator rule and not only as a rendering habit: an entry
    # without a readable reason is refused, whichever list it lands in.
    if not str(record.get("cleanup_reason", "")).strip():
        errors.append("cleanup_reason must explain the verdict in words")
    if not str(record.get("retention_reason", "")).strip():
        errors.append("retention_reason must explain the retention window in words")
    for key in ("revision_index", "revision_count", "reference_count"):
        value = record.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            errors.append(f"{key} must be a non-negative integer")
    references = record.get("referenced_by")
    if not isinstance(references, list):
        errors.append("referenced_by must be a list")
    else:
        for index, reference in enumerate(references):
            for error in _reference_errors(reference):
                errors.append(f"referenced_by[{index}]: {error}")
        if record.get("reference_count") != len(references):
            errors.append("reference_count must match referenced_by")
    if record.get("cleanup_eligible") is True:
        if record.get("lifecycle") != "superseded":
            errors.append("a current artifact must never be cleanup_eligible")
        if record.get("reference_count") != 0:
            errors.append("a referenced artifact must never be cleanup_eligible")
        if not str(record.get("retention_expires_at", "")).strip():
            errors.append("an artifact with no evaluated retention window must never be cleanup_eligible")
    return errors


def validate_generated_artifact_cleanup_preview(payload: Any) -> list[str]:
    """Refuse a preview that is not a dry run or that lists an unsafe artifact."""
    if not isinstance(payload, dict):
        return ["cleanup preview must be an object"]
    errors = _key_set_errors(payload, GENERATED_ARTIFACT_CLEANUP_PREVIEW_KEYS, "cleanup_preview")
    if payload.get("schema_version") != GENERATED_ARTIFACT_CLEANUP_PREVIEW_SCHEMA_VERSION:
        errors.append(f"schema_version must be {GENERATED_ARTIFACT_CLEANUP_PREVIEW_SCHEMA_VERSION}")
    if payload.get("dry_run") is not True:
        errors.append("dry_run must be True; this preview never removes anything")
    if payload.get("claim_boundary") != CLEANUP_PREVIEW_CLAIM_BOUNDARY:
        errors.append("claim_boundary must state that the preview deletes nothing")
    retention_days = payload.get("retention_days")
    if isinstance(retention_days, bool) or not isinstance(retention_days, int) or retention_days < 1:
        errors.append("retention_days must be a positive integer")
    eligible = payload.get("eligible")
    retained = payload.get("retained")
    for label, group in (("eligible", eligible), ("retained", retained)):
        if not isinstance(group, list):
            errors.append(f"{label} must be a list")
            continue
        for index, record in enumerate(group):
            for error in validate_generated_artifact(record):
                errors.append(f"{label}[{index}]: {error}")
    if isinstance(eligible, list):
        if payload.get("eligible_count") != len(eligible):
            errors.append("eligible_count must match eligible")
        for index, record in enumerate(eligible):
            if isinstance(record, dict) and record.get("cleanup_eligible") is not True:
                errors.append(f"eligible[{index}]: a retained artifact must not be listed as eligible")
    if isinstance(retained, list):
        if payload.get("retained_count") != len(retained):
            errors.append("retained_count must match retained")
        for index, record in enumerate(retained):
            if isinstance(record, dict) and record.get("cleanup_eligible") is not False:
                errors.append(f"retained[{index}]: an eligible artifact must not be listed as retained")
    if isinstance(eligible, list) and isinstance(retained, list):
        if payload.get("artifact_count") != len(eligible) + len(retained):
            errors.append("artifact_count must match the eligible and retained lists")
    return errors


def render_generated_artifact_cleanup_preview_text(payload: dict[str, Any]) -> str:
    """Plain text for an operator: what is current, what is not, and why."""
    eligible = [record for record in payload.get("eligible", []) or [] if isinstance(record, dict)]
    retained = [record for record in payload.get("retained", []) or [] if isinstance(record, dict)]
    lines = [
        f"Generated artifacts ({payload.get('artifact_count', 0)} found, "
        f"evaluated at {payload.get('evaluated_at', '')})",
        f"  Retention window: {payload.get('retention_days', 0)} days from creation.",
        "",
        f"Safe to remove ({len(eligible)})",
    ]
    lines.extend(_preview_row_lines(eligible) or ["  Nothing is eligible."])
    lines.extend(["", f"Kept ({len(retained)})"])
    lines.extend(_preview_row_lines(retained) or ["  Nothing is stored yet."])
    unsupported = [row for row in payload.get("unsupported_kinds", []) or [] if isinstance(row, dict)]
    if unsupported:
        lines.extend(["", "Not covered by revision"])
        lines.extend(f"  {row.get('artifact_kind', '')}: {row.get('reason', '')}" for row in unsupported)
    if payload.get("scan_truncated"):
        lines.append("")
        lines.append("  The reference scan hit its file bound; treat the eligible list as incomplete.")
    lines.extend(["", str(payload.get("claim_boundary", "")), str(payload.get("next_action", ""))])
    return "\n".join(line for line in lines if line is not None)


def _preview_row_lines(records: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for record in records:
        lines.append(
            f"  {record.get('artifact_kind', '')} — {record.get('lifecycle', '')} — "
            f"{record.get('artifact_id', '')}"
        )
        lines.append(f"    {record.get('path', '')}")
        lines.append(f"    {record.get('cleanup_reason', '')}")
    return lines


# --- scanning -----------------------------------------------------------------


def _scan_artifacts(paths: OmhPaths, *, limit: int | None) -> dict[str, list[dict[str, Any]]]:
    found: dict[str, list[dict[str, Any]]] = {}
    for kind, members in (
        ("hermes_plan", _scan_plans(paths)),
        ("operation_artifact", _scan_operation_artifacts(paths)),
        ("plan_variant", _scan_plan_variants(paths)),
        ("skill_draft", _scan_skill_drafts(paths)),
    ):
        found[kind] = _bounded(members, limit)
    return found


def _scan_plans(paths: OmhPaths) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for path in _json_like_files(_plans_dir(paths), "*.md"):
        # The plan lane's own reader, not a second parser here: it already
        # derives the digest, the status, and the task-statement identity, and a
        # copy of that derivation would drift the day the plan format moves.
        try:
            artifact = read_hermes_plan_artifact(path)
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if artifact.get("schema_version") == "hermes_plan_input/v1":
            # A planning-input bundle lives beside the plans but is not one: with
            # the same task statement it would otherwise share a revision line and
            # mark the accepted plan superseded. Every other file is listed as before.
            continue
        status = str(artifact.get("status", ""))
        members.append(
            {
                "artifact_kind": "hermes_plan",
                "artifact_id": path.stem,
                "path": path,
                "content_digest": str(artifact.get("sha256", "")),
                "source_schema_version": str(artifact.get("schema_version", "")),
                "declared_status": status,
                # The plan writer puts its own creation stamp in the filename and
                # nowhere else, so that is where creation time comes from.
                "created": _parse_stamp(path.stem[:24]),
                "revision_line": str(artifact.get("task_statement_sha256", "")) or path.stem,
                "forced_superseded": status == PLAN_STATUS_SUPERSEDED,
            }
        )
    return members


def _scan_operation_artifacts(paths: OmhPaths) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for surface in OPERATION_SURFACES:
        for path in _json_like_files(paths.operations_dir / surface, "*.json"):
            record = _read_json(path)
            if record is None:
                continue
            title = _normalized(str(record.get("title", "")))
            members.append(
                {
                    "artifact_kind": "operation_artifact",
                    "artifact_id": str(record.get("artifact_id", "")) or path.stem,
                    "path": path,
                    "content_digest": _file_digest(path),
                    "source_schema_version": str(record.get("schema_version", "")),
                    "declared_status": str(record.get("status", "")),
                    "created": _parse_stamp(str(record.get("created_at", ""))),
                    "revision_line": f"{surface}|{record.get('kind', '')}|{title}",
                    "forced_superseded": False,
                }
            )
    return members


def _scan_plan_variants(paths: OmhPaths) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for path in _json_like_files(_plan_variants_dir(paths), "*.json"):
        record = _read_json(path)
        if record is None:
            continue
        parent = str(record.get("parent_plan_sha256", ""))
        members.append(
            {
                "artifact_kind": "plan_variant",
                "artifact_id": str(record.get("variant_id", "")) or path.stem,
                "path": path,
                "content_digest": _file_digest(path),
                "source_schema_version": str(record.get("schema_version", "")),
                "declared_status": str(record.get("prepared_state", "")),
                "created": _parse_stamp(str(record.get("created_at", ""))),
                "revision_line": f"{parent}|{_normalized(str(record.get('name', '')))}",
                "forced_superseded": False,
            }
        )
    return members


def _scan_skill_drafts(paths: OmhPaths) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    for path in _json_like_files(paths.learning_skill_drafts_dir, "*.json"):
        record = _read_json(path)
        if record is None:
            continue
        lifecycle = record.get("lifecycle")
        state = str(lifecycle.get("state", "")) if isinstance(lifecycle, dict) else ""
        members.append(
            {
                "artifact_kind": "skill_draft",
                "artifact_id": str(record.get("draft_id", "")) or path.stem,
                "path": path,
                "content_digest": _file_digest(path),
                "source_schema_version": str(record.get("schema_version", "")),
                "declared_status": state,
                "created": _parse_stamp(str(record.get("created_at", ""))),
                "revision_line": str(record.get("proposed_skill_name", "")) or path.stem,
                "forced_superseded": False,
            }
        )
    return members


# --- revision lines -----------------------------------------------------------


def _resolve_revision_lines(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order each line and mark every member current or superseded.

    Fails closed twice. A line whose members do not all carry a readable
    creation time, or that carries the same time twice, keeps every member
    `current` and says so: nothing on disk orders them, so calling one superseded
    would be a guess. And a member the producer already marked superseded is
    superseded whatever its position says.
    """
    lines: dict[str, list[dict[str, Any]]] = {}
    for member in members:
        lines.setdefault(str(member["revision_line"]), []).append(member)
    resolved: list[dict[str, Any]] = []
    for line_members in lines.values():
        resolved.extend(_resolve_one_line(line_members))
    return resolved


def _resolve_one_line(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    count = len(members)
    stamps = [member["created"] for member in members]
    orderable = count > 1 and all(stamp is not None for stamp in stamps) and len(set(stamps)) == count
    if not orderable:
        return [
            {
                **member,
                "revision_index": 1,
                "revision_count": count,
                "lifecycle": "superseded" if member["forced_superseded"] else "current",
                "replaces": "",
                "replaced_by": "",
                "ambiguous_order": count > 1,
            }
            for member in members
        ]
    ordered = sorted(members, key=lambda member: (member["created"], str(member["artifact_id"])))
    resolved: list[dict[str, Any]] = []
    for index, member in enumerate(ordered):
        newest = index == count - 1
        resolved.append(
            {
                **member,
                "revision_index": index + 1,
                "revision_count": count,
                "lifecycle": "current" if newest and not member["forced_superseded"] else "superseded",
                "replaces": str(ordered[index - 1]["artifact_id"]) if index else "",
                "replaced_by": "" if newest else str(ordered[index + 1]["artifact_id"]),
                "ambiguous_order": False,
            }
        )
    return resolved


# --- reverse reference scan ---------------------------------------------------


def _reference_index(paths: OmhPaths) -> dict[str, list[tuple[str, str]]]:
    """token -> [(reference kind, source file)], over every local pin.

    Every string in every reference source is a token, which is what makes the
    scan real rather than a guess about which field holds a pin: a path, a
    digest, and an id are all just strings on disk, and a producer that starts
    recording a pin under a new key is covered the day it does.
    """
    index: dict[str, list[tuple[str, str]]] = {}
    for ref_kind, path in _reference_source_files(paths):
        record = _read_json(path)
        if record is None:
            continue
        source = str(_resolved(path))
        for token in _collect_tokens(record, MAX_REFERENCE_SCAN_DEPTH):
            index.setdefault(token, []).append((ref_kind, source))
    return index


def _reference_source_files(paths: OmhPaths) -> Iterator[tuple[str, Path]]:
    seen = 0
    for ref_kind, directory, pattern in (
        ("coding_delegation", paths.runtime_runs_dir, "*/coding_delegation.json"),
        ("handoff_context_pack", paths.runtime_plan_context_dir, "*.json"),
        ("plan_variant", _plan_variants_dir(paths), "*.json"),
        ("role_context_pack", paths.role_context_packs_dir, "*.json"),
        *(("operation_artifact", paths.operations_dir / surface, "*.json") for surface in OPERATION_SURFACES),
    ):
        for path in _json_like_files(directory, pattern):
            if seen >= MAX_REFERENCE_SOURCE_FILES:
                return
            seen += 1
            yield ref_kind, path


def _collect_tokens(value: Any, depth: int) -> set[str]:
    if depth <= 0:
        return set()
    if isinstance(value, str):
        token = _reference_token(value)
        return {token} if token else set()
    if isinstance(value, dict):
        tokens: set[str] = set()
        for item in value.values():
            tokens |= _collect_tokens(item, depth - 1)
        return tokens
    if isinstance(value, list):
        tokens = set()
        for item in value:
            tokens |= _collect_tokens(item, depth - 1)
        return tokens
    return set()


def _reference_token(value: str) -> str:
    """Normalize one string into a comparable token.

    Path-shaped values are resolved, and so is the artifact path they are
    compared against, so the two sides never differ only by separator, by a
    relative prefix, or by a symlinked store root.
    """
    text = value.strip()
    if not text or len(text) > MAX_REFERENCE_TOKEN_LENGTH:
        return ""
    if "/" in text or "\\" in text:
        return str(_resolved(Path(text)))
    return text


def _ambiguous_digests(found: dict[str, list[dict[str, Any]]]) -> frozenset[str]:
    """Content digests that more than one stored artifact answers to.

    Two revisions of one plan really can be byte-identical: the plan renderer is
    a pure function of the task statement, so re-planning the same task writes
    the same bytes under a new name. A pin recorded against that digest names
    all of them and therefore identifies none of them, and crediting it to every
    revision would keep every duplicate on disk forever while printing a reason
    that points at a sibling's pin.

    Dropping the ambiguous digest is safe because every artifact pin in this
    tree that records a digest records the path beside it -- a coding
    delegation, a plan handoff context pack, and a plan variant all do -- so the
    file the pin actually means is still held by its path match. A digest-only
    pin would be the exception, and there is none.
    """
    counts: dict[str, int] = {}
    for members in found.values():
        for member in members:
            digest = str(member["content_digest"])
            if digest:
                counts[digest] = counts.get(digest, 0) + 1
    return frozenset(digest for digest, count in counts.items() if count > 1)


def _references_for(
    member: dict[str, Any],
    index: dict[str, list[tuple[str, str]]],
    ambiguous_digests: frozenset[str],
) -> list[dict[str, Any]]:
    own = str(_resolved(member["path"]))
    digest = str(member["content_digest"])
    found: dict[tuple[str, str, str], dict[str, Any]] = {}
    for matched_on, token in (
        ("path", own),
        ("artifact_id", _reference_token(str(member["artifact_id"]))),
        ("content_digest", "" if digest in ambiguous_digests else _reference_token(digest)),
    ):
        if not token:
            continue
        for ref_kind, source in index.get(token, []):
            # An artifact naming itself is not a reference. Without this, every
            # record that stores its own id would pin itself forever.
            if source == own:
                continue
            found[(ref_kind, source, matched_on)] = {
                "schema_version": GENERATED_ARTIFACT_REFERENCE_SCHEMA_VERSION,
                "ref_kind": ref_kind,
                "ref_path": source,
                "matched_on": matched_on,
            }
    return [found[key] for key in sorted(found)]


# --- record assembly ----------------------------------------------------------


def _build_record(
    member: dict[str, Any],
    index: dict[str, list[tuple[str, str]]],
    ambiguous_digests: frozenset[str],
    now: datetime,
    retention_days: int,
) -> dict[str, Any]:
    references = _references_for(member, index, ambiguous_digests)
    created = member["created"]
    retention = (
        build_retention(
            DEFAULT_RETENTION_CLASS,
            record_type=DEFAULT_RETENTION_RECORD_TYPE,
            admitted_at=created,
            ttl_days=retention_days,
        )
        if created is not None
        else {}
    )
    expires_at = str(retention.get("expires_at", ""))
    expires = _parse_stamp(expires_at)
    eligible, cleanup_reason = _cleanup_verdict(member, references, now, expires, retention_days)
    return {
        "schema_version": GENERATED_ARTIFACT_SCHEMA_VERSION,
        "artifact_kind": str(member["artifact_kind"]),
        "artifact_id": str(member["artifact_id"]),
        "path": str(member["path"]),
        "content_digest": str(member["content_digest"]),
        "source_schema_version": str(member["source_schema_version"]),
        "producer": GENERATED_ARTIFACT_PRODUCERS[str(member["artifact_kind"])],
        "created_at": _stamp(created) if created is not None else "",
        "declared_status": str(member["declared_status"]),
        "revision_line": str(member["revision_line"]),
        "revision_index": int(member["revision_index"]),
        "revision_count": int(member["revision_count"]),
        "lifecycle": str(member["lifecycle"]),
        "replaces": str(member["replaces"]),
        "replaced_by": str(member["replaced_by"]),
        "referenced_by": references,
        "reference_count": len(references),
        "retention_class": DEFAULT_RETENTION_CLASS,
        "retention_days": retention_days,
        "retention_expires_at": expires_at,
        "retention_reason": _retention_reason(created, expires_at, retention_days),
        "cleanup_eligible": eligible,
        "cleanup_reason": cleanup_reason,
    }


def _retention_reason(created: datetime | None, expires_at: str, retention_days: int) -> str:
    if created is None:
        return (
            "No creation time is readable from this artifact or its filename, so the retention window "
            "cannot be evaluated and the artifact is kept."
        )
    return (
        f"Kept for {retention_days} days from {_stamp(created)} under the {DEFAULT_RETENTION_CLASS} "
        f"retention class; the window ends at {expires_at}."
    )


def _cleanup_verdict(
    member: dict[str, Any],
    references: list[dict[str, Any]],
    now: datetime,
    expires: datetime | None,
    retention_days: int,
) -> tuple[bool, str]:
    """The eligibility answer and the sentence that explains it.

    The order of the checks is the order an operator asks them in, and the first
    blocking one is the sentence they get. Every branch returns text: a record
    with no reason fails `validate_generated_artifact`, which is AC2.
    """
    if member["lifecycle"] != "superseded":
        if member.get("ambiguous_order"):
            return False, (
                f"Kept: {member['revision_count']} artifacts share this revision line and do not carry "
                "distinct creation times, so nothing on disk says which one replaced the other."
            )
        return False, "Kept: this is the current revision and nothing has replaced it."
    if references:
        first = references[0]
        return False, (
            f"Kept: {len(references)} local artifact(s) still point at it, starting with the "
            f"{first['ref_kind']} at {first['ref_path']} (matched on {first['matched_on']})."
        )
    if expires is None:
        return False, (
            "Kept: no creation time is readable, so the retention window cannot be shown to have ended."
        )
    if now < expires:
        return False, (
            f"Kept: superseded by {member['replaced_by'] or 'a later revision'}, but still inside its "
            f"{retention_days}-day retention window until {_stamp(expires)}."
        )
    return True, (
        f"Eligible: superseded by {member['replaced_by'] or 'a later revision'}, no local artifact "
        f"references it, and its {retention_days}-day retention window ended at {_stamp(expires)}."
    )


# --- small helpers ------------------------------------------------------------


def _plans_dir(paths: OmhPaths) -> Path:
    return project_artifact_dir(paths, "plans")


def _plan_variants_dir(paths: OmhPaths) -> Path:
    return project_artifact_dir(paths, "plan-variants")


def _json_like_files(directory: Path, pattern: str) -> list[Path]:
    try:
        if not directory.is_dir():
            return []
        return sorted(path for path in directory.glob(pattern) if path.is_file() and not path.is_symlink())
    except OSError:
        return []


def _read_text(path: Path) -> str | None:
    try:
        # Universal newlines on read, matching `read_hermes_plan_artifact`, so a
        # digest taken here equals the digest the plan lane records for the same
        # file on a host that stored it with CRLF.
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _read_json(path: Path) -> dict[str, Any] | None:
    record, error = read_json_object_result(path)
    return None if error else record


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    """The artifact's content digest, or empty when the bytes are unreadable.

    Empty rather than the digest of an empty string: a digest is one of the
    tokens the reference scan matches on, and giving every unreadable file the
    same well-known digest would make them reference each other.
    """
    text = _read_text(path)
    return _digest(text) if text is not None else ""


def _resolved(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return path


def _bounded(members: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if limit is None:
        return members
    if limit < 1:
        return []
    return members[-limit:]


def _normalized(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("now must be a datetime")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return _as_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_stamp(value: str) -> datetime | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        return _as_utc(strict_fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        pass
    for pattern in ("%Y-%m-%dT%H%M%S%fZ", "%Y%m%dT%H%M%S%fZ", "%Y%m%dT%H%M%SZ"):
        try:
            return _as_utc(datetime.strptime(text, pattern))
        except ValueError:
            continue
    return None


def _reference_errors(reference: Any) -> list[str]:
    if not isinstance(reference, dict):
        return ["reference must be an object"]
    errors = _key_set_errors(reference, GENERATED_ARTIFACT_REFERENCE_KEYS, "reference")
    if reference.get("schema_version") != GENERATED_ARTIFACT_REFERENCE_SCHEMA_VERSION:
        errors.append(f"schema_version must be {GENERATED_ARTIFACT_REFERENCE_SCHEMA_VERSION}")
    if reference.get("ref_kind") not in GENERATED_ARTIFACT_REFERENCE_KINDS:
        errors.append("ref_kind is unsupported")
    if reference.get("matched_on") not in GENERATED_ARTIFACT_REFERENCE_MATCHES:
        errors.append("matched_on is unsupported")
    if not str(reference.get("ref_path", "")).strip():
        errors.append("ref_path must not be empty")
    return errors


def _key_set_errors(payload: Any, expected: tuple[str, ...], label: str) -> list[str]:
    if not isinstance(payload, dict):
        return [f"{label} must be an object"]
    errors: list[str] = []
    missing = sorted(set(expected) - set(payload))
    if missing:
        errors.append(f"{label} is missing keys: {', '.join(missing)}")
    unexpected = sorted(set(payload) - set(expected))
    if unexpected:
        errors.append(f"{label} has unexpected keys: {', '.join(unexpected)}")
    return errors

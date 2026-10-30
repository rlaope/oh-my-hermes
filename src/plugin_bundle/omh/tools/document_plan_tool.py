from __future__ import annotations

from .. import runtime_paths

import json
import os
from pathlib import Path
from typing import Any

from ..document_chunk_plan import (
    CHUNK_STATES,
    CLAIM_BOUNDARY,
    DEFAULT_BUDGET_CHARS,
    DEFAULT_CHARS_PER_PAGE,
    DOCUMENT_CHUNK_PLAN_SCHEMA_VERSION,
    FAN_OUT_RANGE_THRESHOLD,
    RESULT_RANGE_LIMIT_DEFAULT,
    RESULT_RANGE_LIMIT_MAX,
    DocumentPlanError,
    DocumentPlanMissing,
    build_document_plan,
    fingerprint_source,
    mark_document_plan_chunk,
    normalize_plan_request,
    plan_id_for,
    plan_path,
    read_document_plan,
    result_view,
    write_document_plan,
)
from ..host_observation import attach_public_observation, observe_plugin_tool_call

OMH_DOCUMENT_PLAN_SCHEMA = {
    "name": "omh_document_plan",
    "description": (
        "Split a long document into read ranges. Call it BEFORE reading a PDF, paper, book or report: "
        "numbered ranges let a document larger than one read_file window be walked range by range, resumed after "
        "compression, or fanned out one delegate_task child per range. read_file extracts a document "
        "to line-numbered text, returns about 100k characters / 2,000 lines per call, re-extracts the "
        "whole file on every paginated read, and drops page numbers; a 300-page PDF is roughly five "
        "windows that conversation compression later folds into one summary. Sequence: read the first "
        "window once to learn total_lines (and the page count or outline from the front matter), call "
        "action=plan with those numbers, then read each range's read_window and mark it covered. "
        "Results are bounded: a plan or show result carries one page of ranges plus the next range "
        "and a ledger summary, never the whole plan. OMH never opens or parses the document: every "
        "page and character count in the plan is caller_supplied; only a local file's size and sha256 "
        "are observed. The plan is a reading schedule and a ledger, never coverage or comprehension "
        "evidence."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["plan", "show", "mark"],
                "description": (
                    "plan derives the ranges from source plus pages/chars/outline and writes "
                    "<omh_home>/documents/<plan_id>/plan.json (re-planning the same document with the "
                    "same numbers returns the existing plan and keeps its ledger); show re-reads a plan "
                    "by plan_id one page of ranges at a time; mark records one chunk's state and returns "
                    "the ledger summary and the next range, advancing next to the lowest missing chunk "
                    "after a covered mark."
                ),
            },
            "source": {
                "type": "string",
                "description": (
                    "For action=plan: the document's path or a label (title, arXiv id, URL). A path to "
                    "an existing local file is fingerprinted by size and sha256 and never parsed; a "
                    "label is recorded as given and binds the ledger to nothing but itself. Only a "
                    "source written as a path (absolute, ~, ./, or containing a separator) is "
                    "treated as a file; a bare title is always a label."
                ),
            },
            "pages": {
                "type": "integer",
                "description": (
                    "Page count when known (from the front matter, the PDF viewer, or the citation). "
                    "Ranges are then page spans, which is how a reader cites them."
                ),
            },
            "chars": {
                "type": "integer",
                "description": (
                    "Extracted text length when known. With pages it fixes the real characters-per-page "
                    "density; alone it makes the ranges character spans."
                ),
            },
            "lines": {
                "type": "integer",
                "description": (
                    "The total_lines field of the first read_file result: the line count of the WHOLE "
                    "extraction, not the number of lines that one call returned. With it every "
                    "read_window is an exact line offset; without it the offsets are estimated from an "
                    "assumed line density and the plan says so. A value that cannot address the ranges "
                    "(too few lines, or thousands of characters per line) is refused."
                ),
            },
            "outline": {
                "type": "array",
                "description": (
                    "Section anchors as {title, page} in any order; ranges then start at section "
                    "boundaries and list the sections they cover. Needs pages."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Section heading as printed."},
                        "page": {"type": "integer", "description": "Page the section starts on."},
                    },
                    "required": ["title", "page"],
                },
            },
            "budget_chars": {
                "type": "integer",
                "default": DEFAULT_BUDGET_CHARS,
                "description": (
                    "Characters one range may hold; mirrors Hermes file_read_max_chars so one range "
                    "is one read_file window at the assumed density. Lower it for a model with a "
                    "smaller context."
                ),
            },
            "chars_per_page": {
                "type": "integer",
                "default": DEFAULT_CHARS_PER_PAGE,
                "description": (
                    "Assumed extracted characters per page when chars is not given; a dense two-column "
                    "paper runs higher, a slide deck lower. Ignored when chars and pages are both given."
                ),
            },
            "plan_id": {
                "type": "string",
                "description": "For action=show and action=mark: the id a plan action returned.",
            },
            "from": {
                "type": "integer",
                "description": (
                    "For action=show: the first chunk number of the page of ranges to return; a "
                    "result's page_hint names the next value."
                ),
            },
            "limit": {
                "type": "integer",
                "description": (
                    f"For action=show: how many ranges the page holds, at most {RESULT_RANGE_LIMIT_MAX}; "
                    "the default is a page a caller can read in one turn."
                ),
            },
            "chunk": {
                "type": "integer",
                "description": "For action=mark: the 1-based range number being marked.",
            },
            "state": {
                "type": "string",
                "enum": list(CHUNK_STATES),
                "description": (
                    "For action=mark: covered means the caller states it read and reported this range; "
                    "next names the range to read now (any other next demotes to missing); missing "
                    "means not yet read or its report was lost to compression. While any chunk is "
                    "missing exactly one is next, so marking the only remaining chunk missing "
                    "promotes it straight back to next."
                ),
            },
            "note": {
                "type": "string",
                "description": "For action=mark: a short metadata note, such as where the range's report lives. No content excerpts.",
            },
        },
        "required": ["action"],
    },
}


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)


def _looks_like_path(label: str) -> bool:
    """A source is treated as a path only when it is written as one.

    A bare title that happens to match a file name in the working directory
    must stay a label: fingerprinting it would record an absolute path and a
    hash the caller never asked for.
    """
    return (
        label.startswith(("/", "~", "./", "../"))
        or "/" in label
        or os.sep in label
        or Path(label).is_absolute()
    )


def _source_path(label: str) -> Path | None:
    """Resolve a caller label to a local path only when that is safe to do.

    Variable references and named-user expansion are refused by the runtime
    path helper; a label that is not written as a path resolves to nothing.
    """
    if not _looks_like_path(label):
        return None
    try:
        return runtime_paths.expand_input_path(label)
    except runtime_paths.RuntimeBindingError:
        return None


def _page_arg(args: dict[str, Any], key: str, default: int) -> int:
    value = args.get(key)
    if isinstance(value, bool) or value is None or value == "":
        return default
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if not isinstance(value, int):
        raise DocumentPlanError(f"{key} must be a whole number")
    if value < 1:
        raise DocumentPlanError(f"{key} must be at least 1")
    return value


def _with_view(payload: dict[str, Any], plan: dict[str, Any], **page: int) -> dict[str, Any]:
    payload.update(result_view(plan, **page))
    return payload


def omh_document_plan_handler(args: dict[str, Any], **kwargs) -> str:
    if error := runtime_paths.tool_home_error(args):
        return _json(error)
    observation = observe_plugin_tool_call("omh_document_plan", args, kwargs)
    action = str(args.get("action", "") or "").strip().lower()
    home_arg = str(args.get("omh_home", "") or "")
    payload: dict[str, Any] = {
        "schema_version": "omh_document_plan_result/v1",
        "plan_schema_version": DOCUMENT_CHUNK_PLAN_SCHEMA_VERSION,
        "action": action,
        "fan_out_threshold": FAN_OUT_RANGE_THRESHOLD,
        "claim_boundary": CLAIM_BOUNDARY,
    }
    if action not in {"plan", "show", "mark"}:
        payload["status"] = "invalid_action"
        payload["error"] = "action must be plan, show, or mark"
        return _json(attach_public_observation(payload, observation))
    # Mutations bind to the configured home only: a caller-chosen path would
    # turn this metadata tool into an arbitrary-location file writer.
    if action != "show" and home_arg:
        payload["status"] = "invalid_home"
        payload["error"] = "omh_home override is read-only; plan and mark use the configured OMH home"
        return _json(attach_public_observation(payload, observation))
    try:
        omh_home = runtime_paths.plugin_home(home_arg or None)
    except runtime_paths.RuntimeBindingError:
        payload["status"] = "invalid_home"
        payload["error"] = "OMH runtime home binding is unavailable for this call"
        return _json(attach_public_observation(payload, observation))
    try:
        if action == "plan":
            request = normalize_plan_request(args)
            fingerprint = fingerprint_source(request["source"], _source_path(request["source"]))
            plan_id = plan_id_for(request, fingerprint)
            try:
                existing = read_document_plan(omh_home, plan_id)
            except DocumentPlanMissing:
                existing = None
            except DocumentPlanError as error:
                # A plan file that exists but cannot be read is not "never
                # planned": replacing it would discard a ledger nobody chose
                # to drop. Name the file and stop. A refusal with no file
                # behind it (a symlinked root) stays the refusal it is.
                if not plan_path(omh_home, plan_id).is_file():
                    raise
                payload["status"] = "plan_unreadable"
                payload["plan_id"] = plan_id
                payload["plan_path"] = str(plan_path(omh_home, plan_id))
                payload["error"] = f"{error}; move or delete the file to plan afresh"
                return _json(attach_public_observation(payload, observation))
            if existing is not None:
                payload["status"] = "existing"
                payload["plan_path"] = str(plan_path(omh_home, plan_id))
                return _json(attach_public_observation(_with_view(payload, existing), observation))
            plan = build_document_plan(request, fingerprint)
            destination = write_document_plan(omh_home, plan)
            payload["status"] = "planned"
            payload["plan_path"] = str(destination)
            return _json(attach_public_observation(_with_view(payload, plan), observation))
        plan_id = str(args.get("plan_id", "") or "").strip()
        if action == "show":
            start = _page_arg(args, "from", 1)
            limit = _page_arg(args, "limit", RESULT_RANGE_LIMIT_DEFAULT)
            plan = read_document_plan(omh_home, plan_id)
            payload["status"] = "read"
            payload["plan_path"] = str(plan_path(omh_home, plan_id))
            return _json(attach_public_observation(_with_view(payload, plan, start=start, limit=limit), observation))
        plan = mark_document_plan_chunk(
            omh_home, plan_id, args.get("chunk"), args.get("state"), args.get("note", "")
        )
        payload["status"] = "marked"
        payload["chunk"] = int(args.get("chunk"))
        payload["state"] = plan["ledger"][str(payload["chunk"])]["state"]
        payload["plan_path"] = str(plan_path(omh_home, plan_id))
        # A mark answers with the ledger and the next range, never the plan:
        # the caller marks once per range, and a full plan per mark would
        # cost more context than the document itself.
        return _json(attach_public_observation(_with_view(payload, plan, limit=1, start=payload["chunk"]), observation))
    except DocumentPlanError as error:
        payload["status"] = "invalid_plan" if action == "plan" else "invalid_" + action
        payload["error"] = str(error)
        return _json(attach_public_observation(payload, observation))

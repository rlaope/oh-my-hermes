"""Bounded, metadata-only degradation signalling for OMH-local call failures.

A broad `except` around a delegated call is acceptable when the failure is
classified and surfaced; it is a defect when the failure is relabeled as a
normal result (`tests/test_broad_exception_policy.py`). This module owns the
vocabulary those handlers use to surface a failure: a closed set of component
labels, a sanitized exception *class name*, and a bounded payload block.

Nothing here raises. Every producer calls into it from inside an `except`
body, so a helper that could raise there would recreate exactly the class of
defect it exists to fix.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

OMH_DEGRADATION_SCHEMA_VERSION = "omh_degradation/v1"

# Named label constants. Every producer imports and uses these, never a bare
# string literal: a typo in a literal is silently coerced to
# `UNKNOWN_COMPONENT` below and yields a well-formed payload that names
# nothing useful, while a typo in an imported name is an ImportError at load.
COMPONENT_LOCALIZED_ROUTING_TEXT = "localized_routing_text"
COMPONENT_LOOP_ROUTE_HINT_ASSESSMENT = "loop_route_hint_assessment"
COMPONENT_CATALOG_QUESTION_CLASSIFIER = "catalog_question_classifier"
COMPONENT_RUNTIME_STATUS_READ = "runtime_status_read"
COMPONENT_DELEGATION_ROUTE_RESTORE = "delegation_route_restore"

DEGRADATION_COMPONENTS = frozenset(
    {
        COMPONENT_LOCALIZED_ROUTING_TEXT,
        COMPONENT_LOOP_ROUTE_HINT_ASSESSMENT,
        COMPONENT_CATALOG_QUESTION_CLASSIFIER,
        COMPONENT_RUNTIME_STATUS_READ,
        COMPONENT_DELEGATION_ROUTE_RESTORE,
    }
)
UNKNOWN_COMPONENT = "unknown_component"
# The closed component set (5) times two distinct error types. Exceeding it
# indicates a duplication bug, which `components_truncated` makes visible.
MAX_DEGRADATION_COMPONENTS = 10

DEGRADATION_CLAIM_BOUNDARY = (
    "An OMH-local delegated call failed and a reduced local fallback answered. "
    "This is a local call failure, not a genuine standalone host. It is an "
    "observation of that failure and nothing else: it is not execution, review, "
    "CI, merge-readiness, or merge evidence."
)

# The one line a chat surface renders. Deliberately label-free: the component
# names are engineer-facing and mean nothing to a Discord or Slack reader, so
# they stay in the structured block and never reach rendered text. English
# only; localized output is explicit opt-in via `--language`/`OMH_LANG`, and
# nothing here may auto-detect a locale.
DEGRADATION_CHAT_NOTE = (
    "Heads-up: part of this answer came from a reduced local fallback because an "
    "OMH-local step failed, so it may be less accurate than usual. Ask again if it "
    "looks wrong."
)


def runtime_binding_degradation(error: BaseException) -> dict[str, object]:
    """Binding failed before hook I/O; never reflect exception text or retry.

    The context line names the exception TYPE as well as the component. A
    binding fault leaves no store to write a record into -- that is what the
    fault means -- so this payload is all the failure can say, and WHERE it
    lands differs by hook, which a caller here must not assume.

    Hermes reads a `pre_llm_call` result's `context` and injects it into the
    turn's user message (`agent/turn_context.py`, the host's only consumer
    of that key). It reads a `pre_tool_call` result's `action` and nothing
    else, skipping every other shape (`hermes_cli/plugins.py`,
    `_get_pre_tool_call_directive_details`). The structured block is read by
    no host path at all. So on the turn hook this text reaches a person, and
    on the tool hook the whole payload is discarded.

    The type is carried for the surfaces that do read it, where it is the
    only thing separating a session no profile owns from a store that was
    named and could not be read (#1674 observation 3).

    The type only, never `str(error)`: an exception message is free text from
    whatever raised, and these are raised while resolving paths, so the
    message is exactly where a path value would appear. `safe_error_type`
    bounds and character-filters a class name; it is not a redactor for
    arbitrary text and must not be handed any.
    """
    error_type = safe_error_type(type(error).__name__)
    return {
        "omh_degradation": degradation_payload([
            (COMPONENT_RUNTIME_STATUS_READ, error_type)]),
        "context": "[OMH Degraded] components=" + COMPONENT_RUNTIME_STATUS_READ
        + " error_type=" + error_type
        + ". Runtime home binding failed; no runtime state was read or written.",
    }


def safe_error_type(error_type: str) -> str:
    """Return a bounded, character-safe exception class name."""
    text = re.sub(r"[^A-Za-z0-9_.-]", "", str(error_type or ""))
    return text[:80] or "Exception"


def degradation_component(component: str, error_type: str) -> dict[str, str]:
    """Return one bounded degradation row, coercing contract violations."""
    label = str(component or "")
    if label not in DEGRADATION_COMPONENTS:
        label = UNKNOWN_COMPONENT
    return {"component": label, "error_type": safe_error_type(error_type)}


def degradation_chat_note(degradation: object) -> str:
    """Return the chat-surface note for a degradation block, or `""`.

    The empty string is the happy path and must stay empty: a caller appends
    the result unconditionally, so a non-empty default would put permanent
    degradation text in front of every healthy chat user.
    """
    if not isinstance(degradation, dict) or not degradation.get("degraded"):
        return ""
    return DEGRADATION_CHAT_NOTE


def degradation_payload(components: Iterable[tuple[str, str]]) -> dict[str, object]:
    """Return a bounded degradation block, or `{}` when nothing degraded."""
    rows = sorted(
        {
            (row["component"], row["error_type"])
            for row in (degradation_component(component, error_type) for component, error_type in components)
        }
    )
    if not rows:
        return {}
    capped = rows[:MAX_DEGRADATION_COMPONENTS]
    return {
        "schema_version": OMH_DEGRADATION_SCHEMA_VERSION,
        "degraded": True,
        "components": [{"component": component, "error_type": error_type} for component, error_type in capped],
        "component_count": len(rows),
        "components_truncated": len(capped) < len(rows),
        "privacy": {
            "mode": "metadata_only",
            "raw_prompt_stored": False,
            "raw_prompt_echoed": False,
            "error_message_stored": False,
        },
        "claim_boundary": DEGRADATION_CLAIM_BOUNDARY,
    }

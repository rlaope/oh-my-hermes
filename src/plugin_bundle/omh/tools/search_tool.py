"""Local search data processing only; Hermes owns retrieval and authorization."""
from __future__ import annotations

import json
import math
import re

from ..host_observation import attach_public_observation, observe_plugin_tool_call
from ..search_state import HostSearchContextError, anchored_search

OMH_SEARCH_SCHEMA = {
    "name": "omh_search",
    "description": (
        "Plan, merge or assess search data. The data is bounded; this tool never searches, reads, invokes a provider or grants access. "
        "Use existing Hermes tools for retrieval and current authorization. All scope, provenance and semantic "
        "judgments remain assertions, not verified truth. Requires host session and request context. "
        "Strict nested contracts are checked at runtime; load the research skill for their field definitions."
    ),
    "parameters": {
        "type": "object", "additionalProperties": False, "required": ["action", "payload"],
        "properties": {
            "action": {"type": "string", "enum": ["plan", "merge", "assess"]},
            "payload": {
                "type": "object", "additionalProperties": False,
                "description": (
                    "plan: {spec: search_spec/v1, capabilities: search_capabilities/v1}; "
                    "merge: {candidate_sets: search_candidate_set/v1[], scope: search_merge_context/v1}; "
                    "assess: {plan: search_plan/v1, observations: search_observations/v1}. "
                    "Pass the exact last assessment state and cumulative ledger. Data is returned, never persisted."
                ),
                "properties": {
                    "spec": {"type": "object"}, "capabilities": {"type": "object"},
                    "candidate_sets": {"type": "array", "maxItems": 5, "items": {"type": "object"}},
                    "scope": {"type": "object"}, "plan": {"type": "object"},
                    "observations": {"type": "object"},
                },
            },
        },
    },
}

_BOUNDARY = (
    "Local validation/fusion and attributed coverage only; no retrieval, authenticated permission, "
    "verified truth, source independence, download/license completion or live search-quality evidence. "
    "Hermes must establish and recheck actual connector authorization before every call and disclosure."
)

_FIELDS = {"plan": {"spec", "capabilities"}, "merge": {"candidate_sets", "scope"},
           "assess": {"plan", "observations"}}
_SAFE_ERROR = re.compile(
    r"(?:invalid_type|unknown_field|missing_field|unsupported_value|bounds|duplicate_id|dangling_reference|"
    r"scope_mismatch|invalid_time|invalid_state|invalid_budget|invalid_provenance):/[A-Za-z0-9_/]*"
)
MAX_INPUT_BYTES = 4 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024


def _bounded_json(value: object) -> None:
    """Refuse non-JSON, cycles, huge scalars and deep trees before producer work."""
    stack = [(value, 0)]
    count = 0
    scalar_bytes = 0
    while stack:
        item, depth = stack.pop()
        count += 1
        if count > 100000 or depth > 24:
            raise ValueError("bounds:/payload")
        kind = type(item)
        if kind is dict:
            if len(item) > 4096 or any(type(key) is not str or len(key) > 128 for key in item):
                raise ValueError("invalid_type:/payload")
            scalar_bytes += sum(len(key.encode("utf-8")) for key in item)
            stack.extend((child, depth + 1) for child in item.values())
        elif kind is list:
            if len(item) > 4096:
                raise ValueError("bounds:/payload")
            stack.extend((child, depth + 1) for child in item)
        elif kind is str:
            if len(item) > 32768:
                raise ValueError("bounds:/payload")
            scalar_bytes += len(item.encode("utf-8"))
        elif kind is int:
            if item.bit_length() > 64:
                raise ValueError("bounds:/payload")
        elif kind is float:
            if not math.isfinite(item):
                raise ValueError("invalid_type:/payload")
        elif item is not None and kind is not bool:
            raise ValueError("invalid_type:/payload")
        if scalar_bytes > MAX_INPUT_BYTES:
            raise ValueError("bounds:/payload")
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_INPUT_BYTES:
        raise ValueError("bounds:/payload")


def _arguments(args: object) -> tuple[str, dict]:
    _bounded_json(args)
    if type(args) is not dict or set(args) != {"action", "payload"}:
        raise ValueError("invalid_type:/")
    action, data = args["action"], args["payload"]
    if type(action) is not str or action not in _FIELDS:
        raise ValueError("unsupported_value:/action")
    if type(data) is not dict or set(data) != _FIELDS[action]:
        raise ValueError("invalid_type:/payload")
    return action, data


def _response(result: dict, payload: dict, observation: dict | None) -> str:
    if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ValueError("bounds:/result")
    response = json.dumps(attach_public_observation(dict(payload, result=result), observation),
                          ensure_ascii=False, allow_nan=False)
    if len(response.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ValueError("bounds:/result")
    return response


def omh_search_handler(args: dict, **kwargs) -> str:
    # Only fixed event metadata reaches the existing observer, never model data.
    metadata = {key: kwargs[key] for key in ("host", "session_id") if key in kwargs}
    observation = observe_plugin_tool_call("omh_search", {}, metadata)
    payload = {"plugin_tool": "omh_search", "source": "package_search", "degraded": False,
               "retrieval_performed": False, "persistence": "no_search_body_persistence",
               "claim_boundary": _BOUNDARY}
    try:
        action, data = _arguments(args)
        from omh.workflows.search_amplification import assess_search_coverage, build_search_plan
        from omh.workflows.search_evidence import merge_search_candidates
        functions = {"plan": build_search_plan, "merge": merge_search_candidates, "assess": assess_search_coverage}
        return anchored_search(action, data, kwargs, functions,
                               lambda result: _response(result, payload, observation))
    except HostSearchContextError as exc:
        payload.update(degraded=True, error=str(exc))
    except ImportError:
        payload.update(degraded=True, error="backend_unavailable", source="standalone_plugin_bundle_fallback")
    except ValueError as exc:
        reason = str(exc)
        payload.update(degraded=True, error="invalid_arguments",
                       reason=reason if len(reason) <= 200 and _SAFE_ERROR.fullmatch(reason) else "invalid_type:/payload")
    except (TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        payload.update(degraded=True, error="invalid_arguments", reason="invalid_type:/payload")
    except Exception:
        # The backend failed; never return a guessed result or raw exception body.
        payload.update(degraded=True, error="package_backend_error")
    return json.dumps(attach_public_observation(payload, observation), ensure_ascii=False, allow_nan=False)

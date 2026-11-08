from __future__ import annotations

from ..ingress import CHAT_SOURCES, MESSAGING_CHAT_SOURCES
from ..plugin_bundle.omh.awareness import (
    awareness_generic_tool_checkpoint_payload,
    awareness_route_hint,
    awareness_route_hint_context_from_payload,
    route_hint_withheld,
    route_hint_without_disabled_skills,
)
from ..plugin_bundle.omh.capability_off import disabled_skill_families
from ..plugin_bundle.omh.degradation import degradation_chat_note
from ..plugin_bundle.omh.hermes_session_commands import host_command_turn, host_context_removed, person_request_text
from ..plugin_bundle.omh.route_answerers import answerer_ladder
from ..plugin_bundle.omh.route_question_mode import ROUTE_QUESTION_MODE_OFF, read_route_question_mode
from ..routing.catalog_questions import is_skill_catalog_question
from ..routing.action_copy import next_action_label
from ..routing.capability_off import CAPABILITY_OFF_KEY
from ..routing.chat import DIRECT_ANSWER_REASON_CODES, route_chat_message
from ..routing.reference_regions import executable_routing_text

# `contract` never imports this module, so the edge is one-way and cycle-free.
# Reusing its helpers keeps the route-hint path on the same messenger-safe
# rendering rules as the main interaction path instead of a second copy.
from .contract import (
    RENDER_PROFILE_RICH_MARKDOWN,
    display_workflow_name,
    _messenger_chunking_hint,
    _messenger_safe_body,
    _render_body_blocks,
    render_profile_for_source,
)

CHAT_ROUTE_HINT_SCHEMA_VERSION = "chat_route_hint/v1"
CHAT_ROUTE_HINT_RESPONSE_SCHEMA_VERSION = "chat_route_hint_response/v1"


def build_chat_route_hint_payload(
    message: str,
    *,
    source: str = "generic",
    max_hints: int = 2,
    source_metadata: dict[str, str] | None = None,
    include_prompt_context: bool = False,
    paths: object = None,
) -> dict[str, object]:
    """Return a wrapper-facing route hint without storing or echoing raw prompt text.

    `route_question` and `route_question_answerers` are additive top-level
    keys; the schema id is unchanged because nothing that reads the existing
    keys reads differently. They are threaded explicitly rather than arriving
    with the rest of the route: this payload is built from the awareness hint
    plus the compact route contract, and neither carries the core router's
    own block, so a key added in `_enriched_route` reaches this surface only
    by being named here.

    `paths` is optional and is the only thing that can produce the answerer
    ladder, which reads the machine's plugin directory and OMH home. Without
    it the ladder is empty -- a caller with no homes has not been told there
    is no answerer, only that nothing was read.
    """
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported chat route hint source: {source}")
    metadata = dict(source_metadata or {})
    # A turn Hermes wrote from one of its session-command templates holds the
    # host's instruction for itself, and the router answers it directly; a
    # hint read from its text would name a workflow beside that fallback. The
    # hint reads no request on such a turn, as the `pre_llm_call` hook's does.
    # On a person's turn it reads their own words, never the gateway material
    # around them; the catalog picker below reads the same text.
    hint_message = (
        ""
        if host_command_turn(message)
        else person_request_text(message, messaging=source in MESSAGING_CHAT_SOURCES)
    )
    route_hint = awareness_route_hint(hint_message, max_hints=max_hints, context_removed=host_context_removed(message))
    route_hint = _route_hint_with_catalog_picker(route_hint, hint_message)
    # A capability family this home turned off is neither hinted nor routed,
    # and a request the router answers "this family is off" gets no hint.
    omh_home = getattr(paths, "omh_home", None) if paths is not None else None
    disabled = disabled_skill_families(omh_home) if omh_home else {}
    route = route_chat_message(message, source=source, limit=max_hints, disabled_skills=disabled or None)
    if disabled:
        route_hint = route_hint_without_disabled_skills(route_hint, disabled)
        if CAPABILITY_OFF_KEY in route:
            route_hint = route_hint_withheld(route_hint)
    route_decision = route["route_decision"]
    route_question = route.get("route_question")
    route_question = route_question if isinstance(route_question, dict) else None
    # Only with an OMH home is there a config to read; `off` withholds the
    # question here exactly as it does on the interaction payload.
    if omh_home and read_route_question_mode(omh_home)["mode"] == ROUTE_QUESTION_MODE_OFF:
        route_question = None
    generic_tool_checkpoint = _generic_tool_checkpoint()
    hints = [hint for hint in route_hint.get("hints", []) if isinstance(hint, dict)]
    primary_hint = hints[0] if hints else {}
    response = _response_for_hint(
        primary_hint,
        hints,
        route_hint=route_hint,
        source=source,
        render_profile=render_profile_for_source(source, metadata),
        generic_tool_checkpoint=generic_tool_checkpoint,
        route_decision=route_decision,
    )
    payload: dict[str, object] = {
        "schema_version": CHAT_ROUTE_HINT_SCHEMA_VERSION,
        "source": source,
        "message_length": len(message),
        "source_metadata": metadata,
        "route_hint": route_hint,
        "route_decision": route_decision,
        "route_question": route_question,
        "route_question_answerers": _answerer_ladder(route_question, paths),
        "generic_tool_checkpoint": generic_tool_checkpoint,
        "chat_response": response,
        "wrapper_contract": {
            "schema_version": "omh_route_hint_wrapper_contract/v1",
            "purpose": "Render a lightweight OMH hint before generic chat/tools when plugin context is unavailable or a wrapper wants an explicit preview.",
            "read_path": "chat_response",
            "state_path": "chat_response.state.route_hint",
            "generic_tool_checkpoint_path": "generic_tool_checkpoint",
            "safe_to_render_without_shell_approval": True,
            "does_not_require_plugin_load": True,
            # A direct answer offers no hinted workflow here either.
            "next_backend_commands": _next_backend_commands({} if _answers_directly(route_decision) else primary_hint),
        },
        "privacy": {
            "mode": "metadata_only",
            "raw_prompt_stored": False,
            "raw_prompt_echoed": False,
            "stored_fields": ["message length", "message hash", "matched cue labels", "workflow hint"],
        },
        "claim_boundary": str(route_hint.get("claim_boundary") or ""),
    }
    if include_prompt_context:
        payload["prompt_context"] = awareness_route_hint_context_from_payload(route_hint)
        payload["prompt_context_boundary"] = (
            "Prompt context is for Hermes routing guidance only; it is not workflow execution or observed evidence."
        )
    return payload


def _answerer_ladder(route_question: dict[str, object] | None, paths: object) -> list[dict[str, object]]:
    """Who could answer this question on this machine, or an empty list.

    Built only when there IS a question: naming the answerers for a route the
    router decided would report a machine fact nobody asked about, and the
    ladder costs a plugin-directory sweep to produce.
    """
    if not route_question or paths is None:
        return []
    return answerer_ladder(
        getattr(paths, "hermes_home", ""),
        getattr(paths, "omh_home", ""),
    )


def _generic_tool_checkpoint() -> dict[str, object]:
    return awareness_generic_tool_checkpoint_payload()


def _route_hint_with_catalog_picker(route_hint: dict[str, object], message: str) -> dict[str, object]:
    hints = [hint for hint in route_hint.get("hints", []) if isinstance(hint, dict)]
    if hints or not is_skill_catalog_question(executable_routing_text(message)):
        return route_hint
    hint = {
        "id": "catalog_question_picker",
        "workflow": "oh-my-hermes",
        "lane": "intent_to_plan",
        "next_action": "choose_skill",
        "next_action_label": next_action_label("choose_skill"),
        "reason": "The user is asking which OMH workflows are available; show the workflow picker without shell approval.",
        "fallback_action": "show_workflow_picker_or_capability_summary",
        "fallback_action_label": next_action_label("show_workflow_picker"),
        "matched_cues": ["catalog_question"],
        "adjacent_workflows": ["deep-interview", "ralplan", "dag-ulw", "loop", "ultrawork"],
        "workflow_context_card": {
            "id": "intent_to_plan",
            "label": "Intent to plan",
            "first_response_shape": "Open the OMH workflow picker, then let the user pick a lane or route the original request.",
            "not_evidence_until_observed": [
                "workflow selection",
                "plan acceptance",
                "executor dispatch",
                "verification",
            ],
        },
        "not_evidence_yet": ["workflow selection", "plan acceptance", "executor dispatch", "verification"],
    }
    updated = dict(route_hint)
    updated.update(
        {
            "status": "hinted",
            "selected_workflow": "oh-my-hermes",
            "primary_workflow": "oh-my-hermes",
            "primary_next_action": "choose_skill",
            "primary_next_action_label": next_action_label("choose_skill"),
            "adjacent_workflows": list(hint["adjacent_workflows"]),
            "hints": [hint],
            "catalog_question": True,
        }
    )
    return updated


def _answers_directly(route_decision: dict[str, object]) -> bool:
    """The router answers this turn in chat, read from its reason code."""
    return route_decision.get("action") == "fallback" and route_decision.get("reason_code") in DIRECT_ANSWER_REASON_CODES


def _checkpoint_body_text(generic_tool_checkpoint: dict[str, object]) -> str:
    body = str(generic_tool_checkpoint.get("body") or "").strip()
    if not body:
        return ""
    return f"Checkpoint: {body}"


def _action_label_with_id(action: str, label: str = "") -> str:
    normalized = action.strip()
    if not normalized:
        return ""
    resolved_label = label.strip() or next_action_label(normalized)
    if not resolved_label or resolved_label == normalized:
        return normalized
    return f"{resolved_label} (`{normalized}`)"


def _response_for_hint(
    primary_hint: dict[str, object],
    hints: list[dict[str, object]],
    *,
    route_hint: dict[str, object],
    source: str,
    render_profile: str,
    generic_tool_checkpoint: dict[str, object],
    route_decision: dict[str, object],
) -> dict[str, object]:
    checkpoint_body = _checkpoint_body_text(generic_tool_checkpoint)
    if _answers_directly(route_decision):
        # The router answers this turn in chat: a host turn, a thank-you, a
        # plain question, or a loop on a timer. The card says so whatever the
        # hint rail named, and offers nothing to open or clarify; the hint
        # itself stays in `route_hint` for a reader. The tool checkpoint is
        # left out too: it asks to name a workflow first.
        workflow = ""
        next_action = "answer_directly"
        next_action_label_text = next_action_label(next_action)
        headline = "[omh] no workflow needed."
        body = "This message needs no OMH workflow; Hermes can answer it directly in chat."
        checkpoint_body = ""
        actions: list[dict[str, object]] = []
        render_kind = "direct_answer_route_hint"
    elif primary_hint:
        workflow = str(primary_hint.get("workflow") or "")
        next_action = str(primary_hint.get("next_action") or "")
        next_action_label_text = str(primary_hint.get("next_action_label") or next_action_label(next_action)).strip()
        # `submit_text` stays canonical: it is invocation syntax OMH's own router
        # has to match. Only the prose the user reads takes the display label.
        workflow_submit_text = "./omh" if workflow == "oh-my-hermes" and next_action == "choose_skill" else f"./{workflow}"
        workflow_display = display_workflow_name(workflow)
        workflow_action_label = "Open omh" if workflow_submit_text == "./omh" else f"Open {workflow_display}"
        lane = str(primary_hint.get("lane") or "")
        if workflow == "oh-my-hermes" and next_action == "choose_skill":
            headline = "[omh] workflow picker is ready."
            body = (
                "This looks like an OMH catalog question, so I can open the workflow picker instead of asking "
                "for shell approval. "
                f"Next action: {_action_label_with_id(next_action, next_action_label_text)}. "
                "This is only a route hint until a workflow is selected and observed."
            )
        else:
            headline = f"[omh] {workflow_display} looks relevant."
            body = (
                f"I can open `{workflow_display}` first because this request matches the {lane.replace('_', ' ')} lane. "
                f"Next action: {_action_label_with_id(next_action, next_action_label_text)}. "
                "This is only a route hint until a workflow is selected and observed."
            )
        if checkpoint_body:
            body = f"{body} {checkpoint_body}"
        actions = [
            {
                "id": "open_workflow",
                "label": workflow_action_label,
                "enabled": True,
                "workflow": workflow,
                "next_action": next_action,
                "submit_text": workflow_submit_text,
            },
            {
                "id": "route_for_me",
                "label": "Route for me",
                "enabled": True,
                "backend_command": "omh chat interact --json",
            },
        ]
        if workflow_submit_text != "./omh":
            actions.append(
                {
                    "id": "open_picker",
                    "label": "Open omh",
                    "enabled": True,
                    "submit_text": "./omh",
                }
            )
        render_kind = "workflow_route_hint"
    else:
        workflow = ""
        next_action = "open_picker_or_clarify"
        next_action_label_text = next_action_label(next_action)
        headline = "[omh] no strong workflow hint yet."
        body = (
            "I do not have a strong OMH workflow hint from this message alone. "
            "Open the workflow picker or ask Hermes to clarify before choosing a workflow."
        )
        if checkpoint_body:
            body = f"{body} {checkpoint_body}"
        actions = [
            {
                "id": "open_picker",
                "label": "Open omh",
                "enabled": True,
                "submit_text": "./omh",
            },
            {
                "id": "clarify",
                "label": "Clarify",
                "enabled": True,
                "backend_command": "omh chat interact --mode clarify --json",
            },
        ]
        render_kind = "no_route_hint"
    # Appended after both branches so the note is always the last sentence a
    # chat reader sees, whichever branch built the body.
    degradation = route_hint.get("degradation") if isinstance(route_hint, dict) else None
    degradation_note = degradation_chat_note(degradation)
    if degradation_note:
        body = f"{body} {degradation_note}"
    state_route_hint: dict[str, object] = {
        "schema_version": "omh_route_hint/v1",
        "primary_workflow": workflow,
        "primary_next_action": next_action,
        "primary_next_action_label": next_action_label_text,
        "intent_class": str(route_hint.get("intent_class") or ""),
        "selected_workflow": str(route_hint.get("selected_workflow") or workflow),
        "mentioned_workflows": list(route_hint.get("mentioned_workflows", [])),
        "mentioned_runtime_terms": list(route_hint.get("mentioned_runtime_terms", [])),
        "adjacent_workflows": list(route_hint.get("adjacent_workflows", [])),
        "not_executed": list(route_hint.get("not_executed", [])),
        "hints": hints,
        "catalog_question": bool(route_hint.get("catalog_question", False)),
        "route_decision": route_decision,
    }
    # This rebuild is an explicit key whitelist, so a key added upstream is
    # dropped here by default. `degradation` is set conditionally: a healthy
    # request must keep exactly today's key set.
    if isinstance(degradation, dict) and degradation:
        state_route_hint["degradation"] = degradation
    # Built from the final `body`, so the degradation note (appended above) is
    # inside the messenger-safe text exactly once instead of being re-added or
    # dropped by the transform.
    fallback_body_text, fallback_transforms = _messenger_safe_body(body)
    if render_profile == RENDER_PROFILE_RICH_MARKDOWN:
        rendered_body_text = body
        transforms_applied: list[str] = []
    else:
        rendered_body_text = fallback_body_text
        transforms_applied = fallback_transforms
    return {
        "schema_version": CHAT_ROUTE_HINT_RESPONSE_SCHEMA_VERSION,
        "kind": render_kind,
        "source": source,
        "headline": headline,
        "body": body,
        "visible_prefix": f"[omh] hint:{workflow}" if workflow else "[omh] hint:none",
        "actions": actions,
        "messenger_rendering": {
            "schema_version": "messenger_route_hint_rendering/v1",
            # `profile` is the raw source echo kept for backward compatibility.
            # Deprecated in favour of `render_profile`, which is the resolved
            # render profile a wrapper should actually render against.
            "profile": source,
            "render_profile": render_profile,
            "title": headline,
            "body_text": rendered_body_text,
            "body_blocks": _render_body_blocks(rendered_body_text, render_profile=render_profile),
            "fallback_body_text": fallback_body_text,
            "transforms_applied": transforms_applied,
            # Per-platform, not the old one-size-fits-all number: Discord,
            # Slack, and Telegram each get their own real ceiling here too,
            # since a route hint is itself a messenger-rendered reply.
            "chunking": _messenger_chunking_hint(source),
            "checkpoint_text": checkpoint_body,
            "primary_action": actions[0] if actions else None,
            "secondary_actions": actions[1:],
        },
        "state": {
            "schema_version": "omh_route_hint_state/v1",
            "selected_workflow": workflow,
            "next_action": next_action,
            "next_action_label": next_action_label_text,
            "route_hint_count": len(hints),
            "route_hint": state_route_hint,
        },
        "claim_boundary": (
            "This response is a preview hint only. It is not workflow selection, execution, generated output, "
            "verification, review, CI, merge, or delivery evidence."
        ),
    }


def _next_backend_commands(primary_hint: dict[str, object]) -> list[dict[str, object]]:
    workflow = str(primary_hint.get("workflow") or "")
    commands = [
        {
            "id": "route_for_me",
            "command": "omh chat interact --source <source> --json <message>",
            "purpose": "Build the full wrapper interaction envelope from the same event.",
        },
    ]
    if workflow != "oh-my-hermes":
        commands.append(
            {
                "id": "open_picker",
                "command": "omh chat interact --source <source> --json ./omh",
                "purpose": "Open the compact OMH workflow picker.",
            }
        )
    if workflow:
        workflow_command = (
            "omh chat interact --source <source> --json ./omh"
            if workflow == "oh-my-hermes"
            else f"omh chat interact --source <source> --json ./{workflow} <message>"
        )
        commands.insert(
            0,
            {
                "id": "open_workflow",
                "command": workflow_command,
                "purpose": "Open the hinted workflow explicitly when the user chooses it.",
            },
        )
    return commands

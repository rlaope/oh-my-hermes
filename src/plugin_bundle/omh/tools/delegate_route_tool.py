from __future__ import annotations

from .. import runtime_paths

import json
import time
from pathlib import Path
from typing import Any, Mapping

from ..delegation_route_restore import (
    conversation_route_for,
    load_route_restore_record,
    newest_written_provenance,
    provenance_route_keys,
    restore_delegation_baseline,
    write_route_with_baseline,
)
# Every write of the three keys now goes through `delegation_route_restore`,
# which pairs it with the baseline bookkeeping under one lock. Reaching for
# the raw writer here again would reopen the window this PR closed.
from ..delegation_routing import (
    read_child_endpoint,
    read_config_snapshot,
    read_delegation_route,
    read_session_provider,
)
from ..hermes_delegation import (
    HERMES_MIXTURE_CATEGORY_CHAINS,
    append_delegation_route_provenance,
    chain_alias_for,
    load_mixture_chain_overrides,
    load_model_provider_routes,
    load_provider_entitlements,
    effective_provider_entitlements,
    provider_serves_alias,
    provider_block_name,
    providers_known_to_serve_alias,
    providers_serving_alias,
    mixture_chain_overrides_path,
    model_provider_routes_path,
    resolve_provider_model,
    effective_mixture_category_chains,
)
from ..delegation_backend_mode import (
    DEFAULT_BACKEND,
    MODEL_MAP_BACKEND,
    PROFILE_ROUTES_BACKEND,
    STATUS_UNREADABLE,
    option_chain,
    option_for,
    read_backend_mode,
)
from ..omh_identities import read_identity_chains
from ..route_endpoint_guard import managed_config_layer, route_endpoint_refusal
from ..provider_detection import config_provider_base_url_hosts, config_provider_declared_models, configured_provider_ids
from ..host_observation import OBSERVATION_SCHEMA, attach_public_observation, host_session_id, observe_plugin_tool_call
from ..kanban_board_reader import conversation_session_ids
from ..orchestration_say import route_say, with_say

_EVIDENCE_BOUNDARY = (
    "Prepared route only: the delegation.* keys apply to the NEXT delegate_task "
    "dispatch (Hermes re-reads config.yaml per dispatch). Writing a route is not "
    "execution, dispatch, or completion evidence."
)
_BACKEND_EVIDENCE_BOUNDARY = (
    "Prepared choice only: under a non-default Hermes delegation backend OMH writes "
    "nothing. A selected option applies only when the delegate_task task carries it, "
    "and the backend decides; the child's own result `route` is what ran."
)


def _backend_route(
    mode: dict[str, Any],
    *,
    category: str,
    chain: tuple[tuple[str, str], ...],
    alias: str,
    effort: str,
    after_option: str,
    provider_routes: dict[str, tuple[str, str]],
    identity: str = "",
    identity_digest: str = "",
    explicit_override: bool = False,
) -> dict[str, Any]:
    """`set`/`fallback`'s answer when `delegation.backend` is not `default`.

    No config byte is written and no provenance is recorded: the delegation
    keys OMH would write are ignored by these backends, so writing them would
    report a route nothing applies. Under `model_map` the user's own option
    that serves the chain entry is named for the task's ``option`` field;
    every other case is `not_applied` with the reason.
    """
    backend = str(mode.get("backend") or "")
    base: dict[str, Any] = {
        "delegation_backend": backend,
        "category": category,
        "evidence_boundary": _BACKEND_EVIDENCE_BOUNDARY,
    }
    if identity:
        base["identity"] = identity
        base["identity_digest"] = identity_digest
    if mode.get("status") == STATUS_UNREADABLE:
        return {**base, "status": "not_applied", "reason": "backend_config_unreadable"}
    if backend == PROFILE_ROUTES_BACKEND:
        return {
            **base,
            "status": "not_applied",
            "reason": "profile_routes_backend",
            "profiles": list(mode.get("profiles") or []),
            "default": str(mode.get("default") or ""),
            "note": (
                "profile_routes runs each child as a whole Hermes profile (its credentials and "
                "tools). OMH never picks one: pass `profile` only when the user named it."
            ),
        }
    if backend != MODEL_MAP_BACKEND:
        return {
            **base,
            "status": "not_applied",
            "reason": "backend_not_default",
            "note": "OMH routes only the default and model_map backends; `/delegation default` restores OMH routing.",
        }
    options = list(mode.get("options") or [])
    carried = option_chain(chain, options, provider_routes) if chain else []
    matched = False
    if alias:
        # The lane's own model (the category head, or the user's explicit
        # model) leads; the rest of the chain follows as its fallbacks.
        provider, wire_model = provider_routes.get(alias, ("", ""))
        name = option_for(options, alias, effort, wire_model=wire_model, provider=provider)
        matched = bool(name)
        if name:
            carried = [{"option": name, "alias": alias, "reasoning_effort": effort}] + [
                entry for entry in carried if entry["option"] != name
            ]
    if explicit_override and not matched:
        # An explicit model or effort outranks the identity: when no option
        # serves it, the identity's own options must not stand in for it.
        carried = []
    names = [entry["option"] for entry in carried]
    if after_option:
        if after_option not in names:
            return {
                **base,
                "status": "not_applied",
                "reason": "option_not_in_chain",
                "option": after_option,
                "option_chain": carried,
            }
        rest = carried[names.index(after_option) + 1 :]
        if not rest:
            return {
                **base,
                "status": "options_exhausted",
                "option_chain": carried,
                "default": str(mode.get("default") or ""),
                "note": "No later option serves this category; dispatching with no `option` uses the backend's default.",
            }
        return {
            **base,
            "status": "option_selected",
            "option": rest[0]["option"],
            "alias": rest[0]["alias"],
            "reasoning_effort": rest[0]["reasoning_effort"],
            "fallback_from": after_option,
            "option_chain": carried,
        }
    if not carried:
        return {
            **base,
            "status": "not_applied",
            "reason": "no_matching_option",
            "available_options": [str(option.get("name", "")) for option in options],
            "default": str(mode.get("default") or ""),
            "note": (
                "None of the user's model_map options runs this lane's models. Dispatch with no "
                "`option` (the backend's default) or ask the user to add one; OMH never edits options."
            ),
        }
    return {
        **base,
        "status": "option_selected",
        "option": carried[0]["option"],
        "alias": carried[0]["alias"],
        "reasoning_effort": carried[0]["reasoning_effort"],
        "option_chain": carried,
    }


# Anthropic models that cannot disable thinking: the Fable-tier generation
# (Fable 5.x and its Mythos sibling), Opus 5.5, and Sonnet 5.5. A
# thinking-off request is a 400 on Mythos 5.1, on Opus 5.5 (Anthropic's
# whats-new-opus-5-5, read 2026-09-23), and on Sonnet 5.5 (its migration
# guide, read 2026-10-01: the API's one thinking-off mode, `between_tools`,
# is a different request no Hermes build sends), and is dropped silently on
# Fable 5.1, so an effort that means
# "no thinking" never reaches delegation.reasoning_effort for these models.
# Opus 5 and Sonnet 5 still accept it, so the Opus and Sonnet entries name
# the 5.5 generation only; the dotted spellings are a gateway's (OpenRouter's
# `anthropic/claude-opus-5.5`, `anthropic/claude-sonnet-5.5`). The bare
# `sonnet` word is deliberately absent: Claude Code resolves it to Sonnet 4.5
# on Bedrock, Google Cloud, and Foundry, where thinking-off is accepted.
# Matched on the alias and on the wire id's model segment, after a Bedrock
# `anthropic.` vendor prefix and any regional prefix before it
# (`us.anthropic.claude-opus-5-5`). This guard refuses on the model name
# alone, so it also covers regional ids the core contract table does not
# declare; core routing raises the no-thinking rung on the spellings it does.
_NO_THINKING_EFFORTS = frozenset({"none", "off", "false", "disabled"})
_ALWAYS_THINKING_CLAUDE_PREFIXES = (
    "claude-fable-", "claude-mythos-", "claude-opus-5-5", "claude-opus-5.5", "claude-sonnet-5-5",
    "claude-sonnet-5.5",
)


def _always_thinking_claude(model: str) -> bool:
    normalized = str(model or "").strip().casefold()
    if "/" in normalized:
        normalized = normalized.rsplit("/", 1)[1]
    if "anthropic." in normalized:
        normalized = normalized.rsplit("anthropic.", 1)[1]
    return normalized in {"fable", "mythos"} or normalized.startswith(_ALWAYS_THINKING_CLAUDE_PREFIXES)


def _chain_entry(
    alias: str,
    effort: str,
    routes: dict[str, tuple[str, str]],
) -> dict[str, str]:
    """Render one chain position.

    The public shape always carries alias, provider, executable model, and
    effort; unresolved aliases report an empty provider explicitly.
    """
    entry = {
        "alias": alias,
        "provider": "",
        "model": alias,
        "reasoning_effort": effort,
    }
    wire_model, provider = resolve_provider_model(alias, routes=routes)
    if provider:
        entry["provider"] = provider
        entry["model"] = wire_model
    return entry


def _legacy_custom_provider_names(config_text: str) -> set[str]:
    """`name:` of each top-level `custom_providers:` list entry, normalized.

    Hermes names such an entry `custom:<name>` with the display name
    lowercased and spaces dashed (`custom_provider_slug`), so the same
    normalization is applied here.
    """
    names: set[str] = set()
    in_section = False
    item_indent = -1
    for line in config_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent == 0 and not stripped.startswith("- "):
            in_section = stripped.split(":", 1)[0].strip().strip("\"'") == "custom_providers"
            item_indent = -1
            continue
        if not in_section:
            continue
        if stripped.startswith("- "):
            if item_indent < 0:
                item_indent = indent
            if indent != item_indent:
                continue
            stripped = stripped[2:].strip()
        elif indent != item_indent + 2:
            continue
        key, separator, rest = stripped.partition(":")
        if separator and key.strip().strip("\"'") == "name":
            value = rest.split("#", 1)[0].strip().strip("\"'").casefold().replace(" ", "-")
            if value:
                names.add(value)
    return names


def _block_lists_alias(hermes_home: Any, provider_id: str, alias: str, wire_model: str) -> bool | None:
    """Whether the `providers.<name>` block behind ``provider_id`` lists the model.

    False only when the block exists and its `models:` section names neither
    the alias nor its wire id; None (unknown) when there is no provider, no
    readable config, no such block, or a block that lists nothing.
    """
    name = provider_block_name(provider_id)
    if not name:
        return None
    text, _signature, error = read_config_snapshot(Path(hermes_home).expanduser() / "config.yaml")
    if error:
        return None
    declared = config_provider_declared_models(text).get(name)
    if not declared:
        return None
    wanted = {str(alias or "").casefold(), str(wire_model or "").casefold()} - {""}
    return bool(wanted & declared)


def _inherited_provider_view(
    hermes_home: Any,
    omh_home: Any,
    alias: str,
    wire_model: str,
    *,
    serving: str,
    on_endpoint: bool,
    entitlements: Any,
) -> tuple[bool | None, tuple[str, ...], tuple[str, ...]]:
    """What a route with no provider would inherit, judged three ways.

    Returns ``(serves, candidates, pinnable)``: whether the inherited provider
    can serve the model (None = unknown), the providers to name in a refusal,
    and the configured providers the catalog knows serve it.

    A relay the catalog cannot place still says what it serves when its
    `providers.<name>` block lists models: Hermes reads the same list to find
    the block that serves a model. A listed block that omits the model cannot
    serve it, so it is neither the inherited answer nor a candidate. Observed
    live: a session on `custom:cliproxy`, a block listing only Claude models,
    inherited by a `gpt-6.1-sol` category head, and every child died on
    "model not found" before a single model call.
    """
    serves = provider_serves_alias(alias, serving, entitlements)
    if serves is None and not on_endpoint:
        serves = _block_lists_alias(hermes_home, serving, alias, wire_model)
    candidates = tuple(
        item
        for item in providers_serving_alias(alias, entitlements)
        if _block_lists_alias(hermes_home, item, alias, wire_model) is not False
    )
    configured = _configured_providers(hermes_home, omh_home)
    pinnable = tuple(
        item for item in providers_known_to_serve_alias(alias, entitlements) if item.casefold() in configured
    )
    return serves, candidates, pinnable


def _configured_providers(hermes_home: Any, omh_home: Any) -> frozenset[str]:
    """Provider ids the person configured for Hermes themselves, casefolded.

    A delegated child sends its whole task context to the provider a route
    names, so a route may only name one of these: the providers counted by
    `effective_provider_entitlements` (linked in auth.json, config.yaml, or
    `.env`, plus the recorded document, minus what the operator excluded),
    every `providers.<id>` block and `model.provider` in config.yaml (a
    loopback block is configured even though entitlements skip it), the
    `custom:<name>` identities of `providers.<id>` blocks with a `base_url`
    and of legacy `custom_providers` entries, and the session's own provider.
    """
    recorded, _ = load_provider_entitlements(omh_home)
    excluded = {str(item).casefold() for item in (recorded or {}).get("excluded_providers", [])}
    entitlements, _status, _rows = effective_provider_entitlements(omh_home, hermes_home)
    configured = {str(item).casefold() for item in ((entitlements or {}).get("providers") or {})}
    text, _signature, error = read_config_snapshot(Path(hermes_home).expanduser() / "config.yaml")
    if not error:
        config_ids = {item.casefold() for item in configured_provider_ids(text)} - excluded
        custom_names = {
            item.casefold() for item in config_provider_base_url_hosts(text) if not item.startswith("custom:")
        }
        custom_names |= _legacy_custom_provider_names(text)
        configured |= config_ids | {f"custom:{name}" for name in custom_names - excluded}
    session = read_session_provider(hermes_home).casefold()
    if session:
        configured.add(session)
    return frozenset(configured)


def _unconfigured_provider_error(
    provider: str, configured: frozenset[str], *, origin: str, hermes_home: Any
) -> dict[str, Any]:
    # The endpoint refusals the writer applies are more specific than this
    # one -- they name the person's own keys that send the child elsewhere --
    # so a route both would refuse keeps their reason.
    text, _signature, error = read_config_snapshot(Path(hermes_home).expanduser() / "config.yaml")
    if not error:
        refusal = route_endpoint_refusal(
            text,
            provider=provider,
            current_provider=read_delegation_route(hermes_home).get("provider", ""),
            managed=managed_config_layer(),
        )
        if refusal:
            return refusal
    listed = ", ".join(sorted(configured)) or "none found"
    return {
        "status": "error",
        "reason": "provider_not_configured",
        "error": (
            f"provider {provider!r} ({origin}) is not one you configured for Hermes; "
            f"configured: {listed}. A delegated child sends its task to the provider its "
            "route names, so a route only names a provider you linked yourself "
            "(config.yaml providers/custom_providers, a Hermes login or key, or this "
            "session's provider). No route was written."
        ),
        "provider": provider,
        "configured_providers": sorted(configured),
    }


def _clear_to_baseline(
    hermes_home: Any,
    omh_home: Any,
    *,
    trigger: str,
    unrecorded_clear: str,
    task_id: str,
    conversation: set[str],
    expected_previous: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Put the recorded baseline back, or remove the keys when none was recorded.

    Both halves run inside the restore's own lock. Doing the unrecorded
    removal out here instead left a window: a route landing in it recorded a
    person's pinned model as a baseline that the next restore then discarded
    as `foreign_edit`, losing the pinned model with nothing reported.

    The two callers ask for different strengths of that removal, which is
    why `unrecorded_clear` is passed rather than assumed. `clear` is a
    person asking, so it removes. Chain exhaustion is automatic, so it may
    only remove a value OMH can prove it wrote -- otherwise a single failed
    lane deleted the model the person had pinned.

    The KEYS are deliberately NOT scoped to the calling session or task,
    unlike the two hooks. Both callers here are asking for the route to come
    off now, and the recorded writer exists to stop an AUTOMATIC restore
    acting on someone else's route, not to refuse an explicit instruction.
    The value check still holds, so a key a person set by hand is safe
    either way. What IS scoped is the conversation route: only the caller's
    own is released, so another session whose route this took out of the
    keys gets it back at its own next dispatch (#2251). The release runs in
    the restore's own lock and only after it: released in a second lock, a
    timeout there left the cleared route -- or, for exhaustion, the failing
    model -- recorded, and the next dispatch of the same task put it back.
    """
    return restore_delegation_baseline(
        hermes_home,
        omh_home=omh_home,
        trigger=trigger,
        unrecorded_clear=unrecorded_clear,
        expected_previous=expected_previous,
        release_task=task_id,
        release_conversation=conversation,
    )


def _conversation(hermes_home: Any, session_id: str) -> set[str]:
    """The host's session id plus its compression continuations, or none."""
    return (
        {session_id} | conversation_session_ids(hermes_home, session_id)
        if session_id
        else set()
    )


def _fallback_position(
    route: dict[str, str], hermes_home: Any, omh_home: Any, session_id: str
) -> tuple[dict[str, str], str, str, str, str]:
    """The route a fallback is advancing FROM, where that came from, and its lane.

    Only the CALLING conversation's own route is a position. The live keys,
    the restore record and provenance are each one per profile, shared by
    every session on it, and reading the newest of them let another
    session's route decide this one's fallback: an error naming a model
    this conversation never routed, a fallback from that session's model,
    an exhausted chain that still had candidates, or that session's live
    route advanced as if it were this one's (#2175). The conversation is the
    host's session id plus its compression continuations, the identity set
    the HUD owns children and route records with. The id itself counts when
    `state.db` cannot answer, since it is the host's own keyword, and with
    no id there is no conversation and so no position. `task_id` is no use:
    provenance does not record it, and TUI and CLI mint a new one each turn
    while a fallback normally comes the turn after the route.

    The live keys are used ONLY when the restore record shows this
    conversation wrote them and the file still holds that write. They are
    not simply "empty once the route has been taken back": a turn-end
    restore puts the PERSON's pinned model back, and reading that as the
    chain position is how one failed lane came to report a whole exhausted
    chain, never try the next candidate, and then delete the pin. A pinned
    model that is in no chain produced a hard error, and one in several
    chains an `ambiguous origins` refusal -- all on the recovery path for a
    child that has just died on HTTP 400, the worst moment to fail.

    Provenance records every route OMH wrote, so the position survives the
    restore even though the value does not.

    The category is the one this conversation's newest provenance record
    names, when that record wrote exactly the position; ``""`` otherwise. A
    shared model is in several chains, so it is what lets a fallback with no
    category continue the chain this conversation routed instead of failing
    as ambiguous. It is read here rather than added to
    `provenance_route_keys`, whose three keys the leftover check compares
    with the file.

    The last two return values name the identity lane the position was
    prepared under, when the same newest record carried one: the identity
    name and the identities.json digest it resolved against. A fallback on
    an identity-routed position stays inside that identity's chain — never
    inside a mixture category that happens to list the same model — and a
    digest that no longer matches the file says the config moved between
    the write and the read, which the caller reports instead of advancing.
    """
    conversation = _conversation(hermes_home, session_id)
    newest = newest_written_provenance(omh_home, session_ids=conversation)
    recovered = provenance_route_keys(newest)
    record = load_route_restore_record(omh_home)
    if (
        route.get("model")
        and record
        and record["writer_session_id"] in conversation
        and dict(route) == record["written"]
    ):
        position, source = dict(route), "live_route"
    elif recovered.get("model"):
        position, source = recovered, "provenance"
    else:
        return {}, "none", "", "", ""
    if recovered == position:
        category = str(newest.get("category", "") or "")
        identity = str(newest.get("identity", "") or "")
        identity_digest = str(newest.get("identity_digest", "") or "")
    else:
        category, identity, identity_digest = "", "", ""
    return position, source, category, identity, identity_digest


OMH_DELEGATE_ROUTE_SCHEMA = {
    "name": "omh_delegate_route",
    "description": (
        "Route the NEXT Hermes-native delegate_task dispatch onto a mixture model "
        "category (ultrabrain, deep, deep-work, architect, capable, unspecified-high, "
        "unspecified-low, quick, simple-work, writing, visual-engineering, artistry, "
        "google-search, x-search, review, swarm, forensics, synthesize) by "
        "writing the delegation.model / "
        "delegation.reasoning_effort keys Hermes reads per dispatch. Sequence per lane: "
        "set the route, call delegate_task for that lane, then set the next lane's route. "
        "Under a model_map delegation backend nothing is written: set/fallback return the "
        "`option` to put on the task; other backends: not_applied. "
        "SET THE ROUTE IN THE SAME TURN THAT DISPATCHES. How long a route lives depends on "
        "the surface: in the Hermes TUI and CLI it is put back when the turn ends, so a "
        "route set in one turn and dispatched in the next runs on the previous model rather "
        "than yours; on a chat platform it lasts the session. Routing in the dispatching "
        "turn is correct on both, so do not rely on a route you set earlier. You do NOT "
        "have to clear at the end; call clear only to put the previous values back sooner. "
        "A restore is skipped, and says so, when the keys no longer hold what OMH wrote -- "
        "a value someone else set is never overwritten. Children already running keep their model. "
        "Hermes has NO provider-side fallback: a child whose model the billing account "
        "cannot serve dies on an HTTP 400 yet its delegation still reports completed with "
        "the error text as the result — a completed child with no recorded model usage "
        "means exactly this. When that happens call action=fallback to advance the route "
        "and re-dispatch; it stays in the category this conversation set, or the one you "
        "pass. An exhausted chain restores what the delegation keys "
        "held before OMH first wrote them, which is the user's own pinned model when they "
        "had one and parent inheritance when they did not; if it cannot prove OMH wrote "
        "the current value it changes nothing and reports unrecorded_value_not_ours. "
        "Relay any `say` field to the user once, in their language and your own words."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["set", "clear", "status", "fallback"],
                "description": (
                    "set writes a route for the current turn; clear restores the keys to "
                    "what they held before OMH first wrote them, which is parent inheritance "
                    "unless the user had pinned their own; status reads the current route; fallback "
                    "advances the current route to the next candidate in its category "
                    "chain (restoring that baseline once the chain is exhausted). "
                    "Without a category passed or recorded, a model in several chains fails closed."
                ),
            },
            "category": {
                "type": "string",
                "enum": sorted(HERMES_MIXTURE_CATEGORY_CHAINS),
                "description": (
                    "Mixture category to route to; resolves to the chain head "
                    "(e.g. ultrabrain -> gpt-6-astra xhigh). Required for set unless "
                    "an explicit model is given."
                ),
            },
            "model": {
                "type": "string",
                "description": (
                    "Explicit model id override; wins over the category's chain head. "
                    "Use for a fallback candidate when the head is unavailable, or to pin "
                    "a model the user named for the run (e.g. 'use fable'): keep the "
                    "fitting category for the lane label and pass the user's model (plus "
                    "reasoning_effort) here on every lane of that run."
                ),
            },
            "reasoning_effort": {
                "type": "string",
                "description": (
                    "Explicit reasoning effort override (e.g. low, medium, high, xhigh). "
                    "Defaults to the chain entry's declared effort; omitted keys inherit "
                    "the parent session's level."
                ),
            },
            "provider": {
                "type": "string",
                "description": (
                    "Hermes provider override. Supply it together with model so the "
                    "provider/wire identity remains atomic."
                ),
            },
            "option": {
                "type": "string",
                "description": "fallback under model_map: the failed child's route.label.",
            },
            "identity": {
                "type": "string",
                "description": (
                    "Identity profile name from routing/identities.json; an unknown name "
                    "answers choice_required."
                ),
            },
            "hermes_home": {
                "type": "string",
                "description": "Standalone operator override only. Native Hermes calls reject this field; omit it to use the active profile.",
            },
            "omh_home": {
                "type": "string",
                "description": "Standalone operator override only. Native Hermes calls reject this field; omit it to use the active profile.",
            },
            "observation": OBSERVATION_SCHEMA,
        },
    },
}


def omh_delegate_route_handler(args: dict[str, Any], **kwargs) -> str:
    if error := runtime_paths.tool_home_error(args):
        return json.dumps(error, sort_keys=True)
    observation = observe_plugin_tool_call("omh_delegate_route", args, kwargs)
    # Only the host keyword names the session; tool args are model-supplied and
    # must not be able to claim another session's route record. Two stores
    # read it: the restore baseline below, and the provenance record, whose
    # owner decides which conversation's HUD may label a child with this
    # route.
    session_id = host_session_id(kwargs)
    # The host gives a tool handler `task_id` but never `turn_id`
    # (`model_tools._execute_tool`), so the task is the finest scope a route
    # can record. What that means differs by flow and both are ordinary: in
    # TUI and CLI the host mints a fresh task per turn, so the scope is the
    # turn; on every gateway platform `task_id` IS the session id
    # (`gateway/run_turn_runner.py`), so the scope is the session and a
    # route survives later turns of it.
    task_id = str(kwargs.get("task_id", "") or "").strip()
    action = str(args.get("action", "") or "set").strip().lower()
    hermes_home = runtime_paths.plugin_home(args.get("hermes_home"), hermes=True)
    omh_home = runtime_paths.plugin_home(args.get("omh_home"))
    # Every chain read below honors the user's routing/model-chains.json
    # overrides and the provider reorder (routing/providers.json plus the
    # providers Hermes is linked to); the category vocabulary itself stays
    # the shipped closed set. One function owns that composition so
    # `omh model-chains show`, the HUD label projection, and this dispatch
    # path never disagree on a head.
    _overrides, override_status = load_mixture_chain_overrides(omh_home)
    chains = effective_mixture_category_chains(omh_home, hermes_home)
    # Chains name models the way a person says them. A host that reaches
    # models through a provider needs a provider id and that provider's own
    # (often namespaced) model string; routing/model-providers.json supplies
    # that mapping. With no document every alias dispatches unchanged.
    provider_routes, provider_route_status = load_model_provider_routes(omh_home)
    # Hermes 0.22.5+: a non-default `delegation.backend` ignores the keys this
    # tool writes. Decide before any write so no `routed` answer names a
    # route the backend will not apply.
    mode = read_backend_mode(hermes_home)
    # The user's identity profiles: explicit `set --identity` routes onto the
    # named chain, and `fallback` reads them only to continue a position the
    # conversation's own provenance already routed under one. Neither read
    # creates state: an absent document is an empty map and a route that
    # named no identity never consults it. The digest rides alongside so a
    # config edited between write and continuation shows up as a changed
    # basis, not silently as the same identity.
    identity_doc = read_identity_chains(omh_home)
    raw_identity_chains = identity_doc.get("identities")
    identity_chains: dict[str, tuple[tuple[str, str], ...]] = {
        str(name): tuple(chain)
        for name, chain in (raw_identity_chains.items() if isinstance(raw_identity_chains, Mapping) else ())
        if isinstance(chain, (list, tuple))
    }
    fingerprint = identity_doc.get("fingerprint")
    identity_digest = (
        str(fingerprint.get("digest", "") or "") if isinstance(fingerprint, Mapping) else ""
    )
    requested_identity = str(args.get("identity", "") or "").strip()
    identity_chain = identity_chains.get(requested_identity, ())
    if action in ("set", "fallback") and requested_identity and not identity_chain:
        # Typed choice_required, never a silent fallback to a different
        # identity or the category table: the name the caller passed is not
        # in the validated document, so the lane is for the caller to
        # re-pick. This fires under every backend — an unknown name is a
        # bad request, not a backend limitation.
        result = {
            "status": "choice_required",
            "reason": "unknown_identity",
            "identity": requested_identity,
            "available_identities": sorted(identity_chains),
            "delegation_backend": mode["backend"],
            "evidence_boundary": _BACKEND_EVIDENCE_BOUNDARY,
        }
        return json.dumps(attach_public_observation(result, observation), sort_keys=True)
    if action in ("set", "fallback") and mode["backend"] != DEFAULT_BACKEND:
        category = str(args.get("category", "") or "").strip()
        model = str(args.get("model", "") or "").strip()
        effort = str(args.get("reasoning_effort", "") or "").strip()
        after_option = str(args.get("option", "") or "").strip() if action == "fallback" else ""
        if category and category not in chains:
            payload = {
                "status": "error",
                "error": f"unknown category {category!r}; choose one of " + ", ".join(sorted(chains)),
            }
            return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
        if action == "fallback" and not ((category or requested_identity) and after_option):
            payload = {
                "status": "error",
                "error": (
                    f"delegation.backend is {mode['backend']}: fallback needs the lane "
                    "(category or identity) and the `option` the failed child ran on"
                ),
                "delegation_backend": mode["backend"],
            }
            return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
        if action == "set" and not (category or model or requested_identity):
            payload = {"status": "error", "error": "set needs a category, an identity, or an explicit model"}
            return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
        # An identity supplies its own chain; `model` still outranks it, and a
        # declared category rides only as the lane label, never as the chain.
        chain = tuple(identity_chain) if identity_chain else tuple(chains.get(category, ()))
        # An explicit model outranks the identity; an explicit effort does too on
        # `set`, where it is matched against the identity head. A fallback walks
        # the identity chain and never matches its effort, so it does not gate.
        explicit_override = bool(identity_chain and (model or (effort and action == "set")))
        alias = model
        if identity_chain and not model and action == "set":
            alias, head_effort = identity_chain[0]
            effort = effort or head_effort
        elif category and not model and action == "set" and chain:
            alias, head_effort = chain[0]
            effort = effort or head_effort
        result = _backend_route(
            mode,
            category=category,
            chain=chain,
            alias=alias,
            effort=effort,
            after_option=after_option,
            provider_routes=provider_routes,
            identity=requested_identity if identity_chain else "",
            identity_digest=identity_digest if identity_chain else "",
            explicit_override=explicit_override,
        )
        return json.dumps(attach_public_observation(result, observation), sort_keys=True)
    if action == "status":
        route = read_delegation_route(hermes_home)
        if route.get("model"):
            route.setdefault("provider", "")
            route["alias"] = chain_alias_for(
                str(route["model"]),
                str(route["provider"]),
                provider_routes,
            )
        payload: dict[str, Any] = {
            "status": "status",
            # The profile-wide keys, which may hold another session's route.
            "route": route,
            # This conversation's own route, the one its next delegate_task
            # is put back on (#2251); None when it set none in this task.
            "conversation_route": conversation_route_for(
                hermes_home, omh_home=omh_home, session_id=session_id, task_id=task_id
            ),
            # Where a direct delegation.base_url sends the child, whatever
            # provider the route names; None when no direct endpoint applies.
            "child_endpoint": read_child_endpoint(hermes_home),
            "categories": {
                category: [
                    _chain_entry(alias, effort, provider_routes)
                    for alias, effort in chain
                ]
                for category, chain in chains.items()
            },
            "chain_overrides": override_status,
            "chain_overrides_path": str(mixture_chain_overrides_path(omh_home)),
            "delegation_backend": {
                "backend": mode["backend"],
                "status": mode["status"],
                "default": mode["default"],
                "options": [option["name"] for option in mode["options"]],
                "profiles": list(mode["profiles"]),
            },
            # The validated user identity chains — the other explicit routing
            # source beside categories. Bounded: names plus their declared
            # (model, effort) entries and the document digest, never prompts.
            "identities": {
                name: [
                    {"model": model, "reasoning_effort": entry_effort}
                    for model, entry_effort in chain
                ]
                for name, chain in identity_chains.items()
            },
            "identities_fingerprint": identity_digest,
            "provider_routes": provider_route_status,
            "provider_routes_path": str(model_provider_routes_path(omh_home)),
            "evidence_boundary": _EVIDENCE_BOUNDARY,
        }
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)

    if action == "clear":
        result = _clear_to_baseline(
            hermes_home,
            omh_home,
            trigger="clear",
            unrecorded_clear="always",
            task_id=task_id,
            conversation=_conversation(hermes_home, session_id),
        )
        if result.get("status") in ("cleared", "restored"):
            # A cleared route must supersede the head/fallback record that
            # preceded it, or a later child on a coincidentally matching
            # model would still inherit that record's label.
            result["route_provenance"] = append_delegation_route_provenance(
                {
                    "origin": "cleared",
                    "session_id": session_id,
                    "written_at": time.time(),
                },
                omh_home,
            )
        result["evidence_boundary"] = _EVIDENCE_BOUNDARY
        return json.dumps(attach_public_observation(result, observation), sort_keys=True)

    if action == "fallback":
        if override_status.startswith("invalid:"):
            payload = {"status": "error", "error": override_status}
            return json.dumps(
                attach_public_observation(payload, observation),
                sort_keys=True,
            )
        if provider_route_status.startswith("invalid:"):
            payload = {"status": "error", "error": provider_route_status}
            return json.dumps(
                attach_public_observation(payload, observation),
                sort_keys=True,
            )
        route = read_delegation_route(hermes_home)
        # A fallback normally happens a turn AFTER the route was written --
        # the child dies on HTTP 400 and the model is told next turn -- and
        # by then the turn-end restore has taken the route back out. The
        # chain position therefore comes from this conversation's provenance
        # when the live keys no longer carry its route; `expected_previous`
        # below still guards against what is actually in the file.
        position, position_source, position_category, position_identity, position_identity_digest = _fallback_position(
            route, hermes_home, omh_home, session_id
        )
        current_model = str(position.get("model", ""))
        current_provider = str(position.get("provider", ""))
        # The live route holds whatever was dispatched, which is the provider's
        # wire model when a route applied. Chain positions are keyed by alias,
        # so translate back before any chain lookup below -- otherwise a routed
        # model reads as absent from the very chain it came from.
        if not current_provider and any(
            current_model in {alias, wire_model}
            for alias, (_, wire_model) in provider_routes.items()
        ):
            payload = {
                "status": "error",
                "error": (
                    f"current route {current_model!r} requires configured "
                    "provider identity"
                ),
            }
            return json.dumps(
                attach_public_observation(payload, observation),
                sort_keys=True,
            )
        current_alias = chain_alias_for(
            current_model,
            current_provider,
            provider_routes,
        )
        if not current_model:
            payload = {
                "status": "error",
                "error": "no active route to fall back from; use set with a category first",
                # This is the return that fires when the position could not
                # be recovered AT ALL, so it is the one an operator most
                # needs the source on. `_fallback_position` reports "none"
                # here rather than omitting the field.
                "position_source": position_source,
                "from": current_model,
            }
            return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
        category = str(args.get("category", "") or "").strip()
        if category and category not in chains:
            payload = {
                "status": "error",
                "error": (
                    f"unknown category {category!r}; choose one of "
                    + ", ".join(sorted(chains))
                ),
            }
            return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
        if not current_provider and "/" in current_model:
            payload = {
                "status": "error",
                "error": f"current route {current_model!r} requires an explicit provider",
            }
            return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
        # With no category passed, the one this conversation routed the
        # position under decides; the alias must still be in that chain.
        recorded = not category and position_category in chains
        if recorded:
            category = position_category
        # An identity position continues inside the identity's own chain --
        # never inside a mixture category that happens to list the model.
        # The continuation key is the newest provenance record's identity --
        # or an `identity` the caller passed explicitly, which is an explicit
        # re-resolution and skips the prepare-vs-read digest check -- and the
        # recorded digest must still match the file for the recorded path.
        matches: list[tuple[str, int]] = []
        index = -1
        recorded_identity = ""
        recorded_digest = ""
        chain: tuple[tuple[str, str], ...] = ()
        explicit_identity = bool(requested_identity) and requested_identity != position_identity
        identity_fallback = not category and bool(position_identity or requested_identity)
        if identity_fallback:
            recorded_identity = requested_identity or position_identity
            # An explicitly re-passed identity resolves fresh against the file
            # (the caller saw it), so only a position-carried identity checks
            # that the document has not moved since the route was written.
            recorded_digest = "" if explicit_identity else position_identity_digest
            identity_chain = tuple(identity_chains.get(recorded_identity, ()))
            if not identity_chain:
                payload = {
                    "status": "choice_required",
                    "reason": "identity_unavailable",
                    "error": (
                        f"this conversation routed under identity {recorded_identity!r}, "
                        "which is no longer in the validated identity document"
                    ),
                    "identity": recorded_identity,
                    "available_identities": sorted(identity_chains),
                    "position_source": position_source,
                    "from": current_model,
                }
                return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
            if recorded_digest and recorded_digest != identity_digest:
                # The document moved between the write that produced this
                # position and this read: continuing the chain now would
                # advance entries that may not be the ones the route meant.
                payload = {
                    "status": "choice_required",
                    "reason": "identity_config_changed",
                    "error": (
                        f"identity {recorded_identity!r} changed since this conversation "
                        "routed under it; set the route again to re-resolve it"
                    ),
                    "identity": recorded_identity,
                    "frozen_digest": recorded_digest,
                    "current_digest": identity_digest,
                    "position_source": position_source,
                    "from": current_model,
                }
                return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
            matched = [index for index, (alias, _) in enumerate(identity_chain) if alias == current_alias]
            if len(matched) != 1:
                payload = {
                    "status": "error",
                    "error": (
                        f"current route model {current_model!r} "
                        + (
                            "is not in the identity chain this conversation routed it under"
                            if not matched
                            else "appears more than once in that identity chain"
                        )
                    ),
                    "position_source": position_source,
                    "from": current_model,
                }
                return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
            index = matched[0]
            chain = identity_chain
        else:
            matches = [
                (name, index)
                for name, chain in chains.items()
                for index, (alias, _) in enumerate(chain)
                if alias == current_alias and (not category or name == category)
            ]
        if not identity_fallback and not matches:
            payload = {
                "status": "error",
                "error": (
                    f"current route model {current_model!r} does not match "
                    + (
                        f"category {category!r}"
                        + (", the one this conversation routed it under" if recorded else "")
                        if category
                        else "any mixture chain; pass category explicitly"
                    )
                ),
                # An operator reading this has to be able to see WHICH
                # position the tool thought it had, and whether it came from
                # the live keys or from provenance.
                "position_source": position_source,
                "from": current_model,
            }
            return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
        if len(matches) > 1:
            origins = ", ".join(sorted({name for name, _ in matches}))
            payload = {
                "status": "error",
                "error": (
                    f"current route model {current_model!r} has ambiguous origins "
                    f"across {origins}; pass category explicitly"
                ),
                "position_source": position_source,
                "from": current_model,
            }
            return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
        if not identity_fallback:
            category, index = matches[0]
            chain = chains[category]
        # A candidate whose route names a provider the person never
        # configured is passed over, never written: model-providers.json is a
        # file a model with a file tool can write too, and the child would
        # carry its whole task to that provider.
        configured = _configured_providers(hermes_home, omh_home)
        skipped_unconfigured: list[dict[str, str]] = []
        while index + 1 < len(chain):
            candidate_alias = chain[index + 1][0]
            _candidate_wire, candidate_provider = resolve_provider_model(
                candidate_alias, routes=provider_routes
            )
            if not candidate_provider or candidate_provider.casefold() in configured:
                break
            skipped_unconfigured.append({"alias": candidate_alias, "provider": candidate_provider})
            index += 1
        if index + 1 >= len(chain):
            # Chain exhausted: put the person's own delegation keys back so the
            # next dispatch runs on a model known to work -- their pinned one
            # when they had one, parent inheritance when they did not -- instead
            # of one more rejection.
            result = _clear_to_baseline(
                hermes_home,
                omh_home,
                trigger="chain_exhausted",
                unrecorded_clear="if_omh_wrote",
                task_id=task_id,
                conversation=_conversation(hermes_home, session_id),
                expected_previous=route,
            )
            if result.get("status") in ("cleared", "restored"):
                result["status"] = "exhausted_to_inherit"
                result["route_provenance"] = append_delegation_route_provenance(
                    {
                        "origin": "exhausted_to_inherit",
                        "category": category,
                        "from_alias": current_alias,
                        "session_id": session_id,
                        "written_at": time.time(),
                        **(
                            {"identity": recorded_identity, "identity_digest": identity_digest}
                            if identity_fallback
                            else {}
                        ),
                    },
                    omh_home,
                )
            result["category"] = category
            if identity_fallback:
                result["identity"] = recorded_identity
            result["from"] = current_model
            result["position_source"] = position_source
            if skipped_unconfigured:
                result["skipped_unconfigured"] = skipped_unconfigured
            result["evidence_boundary"] = _EVIDENCE_BOUNDARY
            return json.dumps(attach_public_observation(with_say(result, route_say(result)), observation), sort_keys=True)
        next_model, next_effort = chain[index + 1]
        wire_model, next_provider = resolve_provider_model(
            next_model, routes=provider_routes
        )
        fallback_pinned: dict[str, str] | None = None
        if not next_provider and not read_child_endpoint(hermes_home):
            # The same inheritance the set path guards: a fallback entry with
            # no provider runs on the session's, and a session the entry
            # cannot run on dies the same way the head did. Pin the one known
            # server when there is exactly one; otherwise write it as before.
            inherited = read_session_provider(hermes_home)
            fallback_entitlements, _fs, _fp = effective_provider_entitlements(omh_home, hermes_home)
            fallback_serves, _fc, fallback_pinnable = _inherited_provider_view(
                hermes_home, omh_home, next_model, wire_model,
                serving=inherited, on_endpoint=False, entitlements=fallback_entitlements,
            )
            if fallback_serves is False and len(fallback_pinnable) == 1:
                next_provider = fallback_pinnable[0]
                fallback_pinned = {"inherited_provider": inherited, "pinned_provider": next_provider}
        if "/" in wire_model and not next_provider:
            payload = {
                "status": "error",
                "error": (
                    f"next route {next_model!r} has no provider-aware wire model; "
                    "fallback refused without mutation"
                ),
            }
            return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
        result = write_route_with_baseline(
            hermes_home,
            omh_home=omh_home,
            session_id=session_id,
            task_id=task_id,
            model=wire_model,
            reasoning_effort=next_effort,
            provider=next_provider,
            expected_previous=route,
        )
        if result.get("status") == "routed":
            result["status"] = "fell_back"
            result["applied"]["alias"] = next_model
            if fallback_pinned is not None:
                result["provider_pinned"] = fallback_pinned
            result["category"] = category
            if identity_fallback:
                result["identity"] = recorded_identity
            result["from"] = current_model
            result["position_source"] = position_source
            result["route_provenance"] = append_delegation_route_provenance(
                {
                    "origin": "fallback",
                    "category": category,
                    "alias": next_model,
                    "wire_model": wire_model,
                    "provider": next_provider,
                    "reasoning_effort": next_effort,
                    "from_alias": current_alias,
                    "session_id": session_id,
                    "written_at": time.time(),
                    **(
                        {"identity": recorded_identity, "identity_digest": identity_digest}
                        if identity_fallback
                        else {}
                    ),
                },
                omh_home,
            )
            result["fallback_candidates"] = [
                _chain_entry(alias, chain_effort, provider_routes)
                for alias, chain_effort in chain[index + 2 :]
            ]
        if skipped_unconfigured:
            result["skipped_unconfigured"] = skipped_unconfigured
        result["evidence_boundary"] = _EVIDENCE_BOUNDARY
        return json.dumps(attach_public_observation(with_say(result, route_say(result)), observation), sort_keys=True)

    if action != "set":
        payload = {
            "status": "error",
            "error": f"unknown action {action!r}; use set, clear, status, or fallback",
        }
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)

    if override_status.startswith("invalid:"):
        payload = {"status": "error", "error": override_status}
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    if provider_route_status.startswith("invalid:"):
        payload = {"status": "error", "error": provider_route_status}
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    category = str(args.get("category", "") or "").strip()
    model = str(args.get("model", "") or "").strip()
    effort = str(args.get("reasoning_effort", "") or "").strip()
    provider = str(args.get("provider", "") or "").strip()
    if category and category not in chains:
        payload = {
            "status": "error",
            "error": (
                f"unknown category {category!r}; choose one of "
                + ", ".join(sorted(chains))
            ),
        }
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    if provider and not model:
        payload = {
            "status": "error",
            "error": "provider and model overrides must appear together",
        }
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    if not model and not category and not requested_identity:
        payload = {"status": "error", "error": "set needs a category, an identity, or an explicit model"}
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    alias = model
    if identity_chain and not model:
        # The identity's own chain supplies the lane; an explicit category on
        # the same call stays the lane label but never supplies the chain.
        alias, head_effort = identity_chain[0]
        if not effort:
            effort = head_effort
    elif category and not model:
        alias, head_effort = chains[category][0]
        if not effort:
            effort = head_effort
    identity_routed = bool(identity_chain) and not model
    always_thinking = _always_thinking_claude(alias)
    if always_thinking and effort.casefold() in _NO_THINKING_EFFORTS:
        payload = {
            "status": "error",
            "error": (
                f"{alias} always thinks; a reasoning_effort of {effort!r} asks the provider to "
                "disable thinking, which this generation rejects. Route `low` instead."
            ),
        }
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    if provider:
        wire_model = model
    else:
        wire_model, provider = resolve_provider_model(alias, routes=provider_routes)
    pinned_for_inherited: dict[str, str] | None = None
    if not provider:
        # With no provider the child inherits the session's own, and nothing
        # checked that it can serve the model being pinned. Observed live: a
        # Fable alias inherited an `openai-codex` session and every dispatch
        # returned HTTP 400, twice, before the operator worked out the model
        # needed a different provider and hunted down its wire id by hand.
        # Refuse only what is known wrong -- an unrecorded provider, an alias
        # the catalog never described, or a multi-vendor account all answer
        # "unknown" and dispatch unchanged -- and refuse it beside the answer.
        # A direct `delegation.base_url` takes the session's place: Hermes
        # builds the child against that endpoint and names its provider by
        # the URL. A named one (`anthropic`, `openai-codex`) is checked
        # instead, `custom` serves whatever the endpoint serves and is not,
        # and an endpoint the scan cannot read (host "") keeps the session's.
        endpoint = read_child_endpoint(hermes_home) or {}
        on_endpoint = bool(endpoint.get("host"))
        serving = endpoint["provider"] if on_endpoint else read_session_provider(hermes_home)
        entitlements, _status, _providers = effective_provider_entitlements(omh_home, hermes_home)
        serves, candidates, pinnable = _inherited_provider_view(
            hermes_home, omh_home, alias, wire_model, serving=serving, on_endpoint=on_endpoint, entitlements=entitlements
        )
        if not (on_endpoint and serving == "custom") and serves is False:
            if not endpoint and len(pinnable) == 1:
                # Exactly one provider the operator holds is known to serve the
                # model: pin it rather than refuse. It is the provider the
                # refusal would have told the caller to pass, and a route that
                # names it is what a careful caller writes by hand. Never with
                # `delegation.base_url` set, readable or not: a route naming a
                # provider there is refused (`route_endpoint_refusal`), so a
                # pin would swap this answer for that one.
                provider = pinnable[0]
                pinned_for_inherited = {"inherited_provider": serving, "pinned_provider": provider}
            else:
                remedy = (
                    f"pin one of your providers that can: {', '.join(candidates)}"
                    if candidates
                    else "record which provider serves it in routing/model-providers.json"
                )
                if on_endpoint:
                    payload = {
                        "status": "error",
                        "error": (
                            f"{alias} would run on delegation.base_url ({endpoint['host']}), which Hermes builds "
                            f"as provider {serving!r}, and that provider does not serve it. Route a model it "
                            "serves, or remove delegation.base_url yourself "
                            f"(`hermes config unset delegation.base_url`) and {remedy}."
                        ),
                        "alias": alias,
                        "endpoint_provider": serving,
                        "providers_serving_alias": list(candidates),
                    }
                else:
                    payload = {
                        "status": "error",
                        "error": (
                            f"{alias} would inherit this session's provider {serving!r}, "
                            f"which does not serve it. Pass an explicit provider with its wire model, "
                            f"or {remedy}."
                        ),
                        "alias": alias,
                        "inherited_provider": serving,
                        "providers_serving_alias": list(candidates),
                    }
                return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    if "/" in wire_model and not provider:
        payload = {
            "status": "error",
            "error": "a wire-shaped model requires an explicit provider",
        }
        return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    if provider:
        # The provider is model-supplied (tool arg) or read from
        # routing/model-providers.json; either way the person must have
        # configured it before a delegated child's task goes there.
        configured = _configured_providers(hermes_home, omh_home)
        if provider.casefold() not in configured:
            origin = "explicit provider argument" if args.get("provider") else "routing/model-providers.json"
            payload = _unconfigured_provider_error(provider, configured, origin=origin, hermes_home=hermes_home)
            return json.dumps(attach_public_observation(payload, observation), sort_keys=True)
    result = write_route_with_baseline(
        hermes_home,
        omh_home=omh_home,
        session_id=session_id,
        task_id=task_id,
        model=wire_model,
        reasoning_effort=effort,
        provider=provider,
    )
    if result.get("status") == "routed":
        result["applied"]["alias"] = alias
        result["category"] = category
        if identity_routed:
            result["identity"] = requested_identity
            result["identity_digest"] = identity_digest
        if pinned_for_inherited is not None:
            result["provider_pinned"] = pinned_for_inherited
        result["route_provenance"] = append_delegation_route_provenance(
            {
                "origin": "head" if (category or identity_routed) and not model else "explicit",
                "category": category,
                "alias": alias,
                "wire_model": wire_model,
                "provider": provider,
                "reasoning_effort": effort,
                "session_id": session_id,
                "written_at": time.time(),
                **(
                    {"identity": requested_identity, "identity_digest": identity_digest}
                    if identity_routed
                    else {}
                ),
            },
            omh_home,
        )
        # The identity's own chain supplies the fallback candidates when the
        # identity supplied the head; a category keeps its own chain either way.
        fallback_chain = identity_chain if identity_routed else chains.get(category, ())
        result["fallback_candidates"] = [
            _chain_entry(chain_alias, chain_effort, provider_routes)
            for chain_alias, chain_effort in fallback_chain[1:]
        ]
    result["evidence_boundary"] = _EVIDENCE_BOUNDARY
    return json.dumps(attach_public_observation(with_say(result, route_say(result)), observation), sort_keys=True)

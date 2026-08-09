from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import hashlib
from pathlib import Path
import re
from typing import Any

from ..coding_contracts import (
    CLAUDE_CODE_SESSION_OBSERVATION_CONTRACT_SCHEMA_VERSION,
    CODING_EXECUTOR_TARGETS,
    CODEX_SESSION_OBSERVATION_CONTRACT_SCHEMA_VERSION,
    EXECUTOR_PROMPTING_REQUIRED_SECTIONS,
    EXECUTOR_HANDOFF_SCHEMA_VERSION,
    LOCAL_CAPABILITY_REPORT_ALLOWED_KINDS,
    LOCAL_CAPABILITY_REPORT_CAPABILITY_FIELDS,
    LOCAL_CAPABILITY_REPORT_CONTRACT_SCHEMA_VERSION,
    LOCAL_CAPABILITY_REPORT_REQUIRED_FIELDS,
    PROMPT_HANDOFF_SCHEMA_VERSION,
    RUNTIME_HANDOFF_SCHEMA_VERSION,
    TASK_PROMPT_CONTRACT_SCHEMA_VERSION,
    TASK_PROMPT_REQUIRED_SECTIONS,
)
from .action_gate import evaluate_action_gate, split_handoff_safety_contract
from .prompting import build_executor_prompting_contract, render_executor_prompt_sections
from ..executors import (
    HERMES_CODING_TEAM_WRAPPER_ACTIONS,
    denied_executor_selection,
    executor_label,
    executor_selection_for_target,
    hermes_coding_team_path_contract,
    prompt_invocation_for_profile,
    public_executor_options,
    runtime_invocation_for_profile,
    runtime_profile_contract,
    runtime_templates_for_profile,
)
from .hermes_harness import build_hermes_coding_harness
from .executor_capability_snapshots import (
    KNOWN_CAPABILITY_NAMES,
    LOCAL_WORKFLOW_CAPABILITY_NAME,
    build_executor_capability_snapshot,
    executor_capability_snapshot_path,
    read_matching_executor_capability_snapshot,
)
from .executor_local_workflow import build_executor_local_workflow
from .executor_local_workflow_selection import is_workflow
from .product_family_templates import product_family_template
from .product_quality_harnesses import product_quality_harness
from .project_governance import discover_project_governance, governance_handoff_attachment
from ..executor_readiness import (
    executor_readiness_contract,
    executor_readiness_for_selection,
    with_executor_readiness_options,
)
from .agentic_playbook import maybe_build_agentic_playbook
from .context_safety import (
    MAX_VISIBLE_MESSAGE_CHARS,
    bounded_prompt_preview,
    compact_visible_text,
    context_budget_payload,
    raw_output_artifact_ref,
)
from ..harness_quality import with_wrapper_actions
from ..quality.specialist_work import build_specialist_work_quality_contract
from ..ingress import CHAT_SOURCES, extract_message_text, extract_source_metadata
from ..isolation import build_isolation_plan
from ..memory import validate_handoff_context_blocked, validate_handoff_context_pack, validate_project_memory_recall_pack
from ..workflows.role_context_packs import build_role_context_pack, pin_role_context_pack
from ..routing.executor_cues import contains_boundary_phrase
from ..routing.recommend import recommend_skills
from ..workflows.blocked_work_records import decision_from_action_gate, request_class_shape
from ..skills.catalog import (
    CODING_INTENT_PRIORITY,
    CODING_REVIEW_TERMS,
    catalog_intent_delegation_skill_names,
    coding_intent_for_skill,
    coding_skills_for_intent,
    coding_terms_for_intent,
    routable_definitions,
    harness_quality_contract,
    primary_harness_for_skill,
    retained_delegation_skill_names,
)


SCHEMA_VERSION = "coding_delegation/v1"
DELEGATION_ACTIONS = ("delegate", "clarify", "fallback")
DELEGATION_POLICY_SCHEMA_VERSION = "coding_delegation_policy/v1"
INLINE_CODING_POLICY_STATEMENT = (
    "Hermes never implements main coding work inline. Coding-shaped work always becomes a prepared "
    "handoff owned by a selected coding executor; when no executor is resolvable, ask the user which "
    "coding agent should own the work instead of retaining it."
)
MESSAGE_CONTEXT_SCHEMA_VERSION = "coding_delegation_message_context/v1"
MESSAGE_CONTEXT_MODES = ("full", "bounded")
# Four rules pinned from one live Slack session where a chat wrapper went wrong in front of a user:
# (a) after a context compaction it said "승인 받았어" (I received approval) and dispatched to Codex —
#     no approving user message existed, the compaction resume was mistaken for approval;
# (b) its status copy never named which executor/model actually ran, so nobody could tell;
# (c) it proposed retrying "with a working model (gpt-5.1-codex 등)", inventing a model name from stale
#     memory; and (d) it read `which codex` plus an existing ~/.codex/auth.json as "Codex ready", dispatched,
#     and the run then failed — a binary on PATH and an auth file are not run evidence.
# These travel on the shared payload (not copied into each per-target handoff builder) so every executor
# target — codex, claude-code, hermes, generic, or a future one — carries the same guardrail text.
APPROVAL_EVIDENCE_RULE = (
    "Approval is a quoted user message visible in the current context. A compaction or session resume "
    "is never approval. If the approving message is not visible after compaction, re-ask before dispatching."
)
EXECUTOR_IDENTITY_RULE = (
    "State the executor and model exactly as configured or observed (e.g. from the runtime record or CLI "
    "config), in parentheses after status lines. If the model is not observed, say the model is unconfirmed."
)
MODEL_NAMING_RULE = (
    "Never name a concrete model from memory. Model names come only from observed config, runtime records, "
    "or the executor CLI's own output; otherwise ask or say unknown."
)
READINESS_EVIDENCE_RULE = (
    "A binary on PATH and an auth file are not run evidence. Before claiming an executor is ready, observe "
    "it execute — a --version or no-op invocation — and read its configured model from its own config or "
    "output. Readiness claimed from file existence alone must be labeled prepared, not observed."
)
_CATALOG_INTENT_RETAINED_WORKFLOWS = set(catalog_intent_delegation_skill_names())
_RETAINED_HERMES_WORKFLOWS = set(retained_delegation_skill_names())
_LOCAL_CAPABILITY_STRATEGY_SCHEMA_VERSION = "executor_local_capability_strategy/v1"
_LOCAL_CAPABILITY_PREFERRED_SOURCES = (
    "project instructions such as AGENTS.md, CLAUDE.md, or executor-specific rules",
    "executor-native skills, slash commands, workflow commands, or prompt libraries",
    "executor-local installed skill catalogs, slash-command registries, and custom agent definitions",
    "user-installed open-source workflow packs",
    "available subagents, worker lanes, or task planners",
    "MCP tools exposed to the selected executor",
    "repo scripts, tests, task runners, and CI metadata",
)
_LOCAL_CAPABILITY_STAGE_GUIDANCE = {
    "planning": "Use local planning or reviewed-plan capability when it materially improves scope, acceptance criteria, or risk review.",
    "implementation": "Use local implementation, goal, or work-management capability when it improves delivery discipline.",
    "parallelization": "Use local subagents, workers, or worktrees only when lanes are independent and ownership is explicit.",
    "qa_review": "Use local QA, code-review, or adversarial review capability when it improves verification quality.",
}
_CODE_REFERENCE_PREFIXES = ("src/", "src\\", "tests/", "tests\\")
_CODE_REFERENCE_EXTENSIONS = (
    "py",
    "js",
    "ts",
    "tsx",
    "jsx",
    "go",
    "rs",
    "java",
    "kt",
    "swift",
    "rb",
    "php",
    "cs",
    "cpp",
    "c",
    "h",
)
_CODE_REFERENCE_FILE_RE = re.compile(
    rf"(?<![\w@.-])(?:[\w.-]+[\\/])*[\w.-]+\.({'|'.join(_CODE_REFERENCE_EXTENSIONS)})(?![\w.-])",
    re.IGNORECASE,
)
_CODE_REFERENCE_TRIM_CHARS = "`'\"“”‘’.,;:!?()[]{}<>"
# The same set without `.`, for trimming the *front* of a path token: a leading
# dot is part of the path (`./src/a.py`, `../../etc/loader.py`), and stripping
# it rewrites the path into a different one.
_CODE_REFERENCE_OPENING_TRIM_CHARS = "`'\"“”‘’,;:!?()[]{}<>"
_CODE_REFERENCE_CONTEXT_RE = re.compile(
    "|".join(
        (
            r"\b(?:debug|edit|fix|implement|modify|patch|refactor)\b",
            r"\b(?:change|update)\s+(?:the\s+)?(?:code|file|module|tests?)\b",
            r"\b(?:unit|integration|regression)\s+tests?\b",
            r"\btests?\s+for\b",
            r"\b(?:repo|repository|source)\s+file\b",
            r"\b(?:class|code|function|module)\b",
        )
    ),
    re.IGNORECASE,
)
_LOCAL_CAPABILITY_EXAMPLES = {
    "codex": [
        "Codex-native skills",
        "OMX or other oh-my workflow packs",
        "custom Codex skills",
        "Codex subagents",
        "$ralph",
        "$ralplan",
        "$ultragoal",
        "$ultrawork",
        "$ultraqa",
        "$code-review",
    ],
    "claude-code": [
        "CLAUDE.md",
        "Claude Code slash commands",
        "Claude skills",
        "Everything Claude Code skill packs",
        "user-defined Claude Code skills",
        "custom Claude Code slash commands",
        "Claude Code agents/subagents",
        "subagents",
        "MCP tools",
    ],
    "hermes": [
        "installed Hermes skills",
        "Hermes delegation",
        "OMH ultrawork/team/ultraqa/code-review",
    ],
    "generic": [
        "local agent instructions",
        "repo scripts",
        "documented workflow commands",
    ],
    "omx-runtime": [
        "OMX/oh-my runtime templates",
        "OMX skills",
        "team or worker lanes",
        "MCP tools",
    ],
    "omo-runtime": [
        "OMO/oh-my runtime templates",
        "OMO skills",
        "worker lanes",
        "MCP tools",
    ],
    "omc-runtime": [
        "OMC/oh-my runtime templates",
        "Claude Code-backed workflow commands",
        "worker lanes",
        "MCP tools",
    ],
}
_CODING_STATUS_AGENT_TERMS = (
    "codex",
    "claude code",
    "coding agent",
    "coding-agent",
    "hermes coding",
    "senpi",
    "opencode",
    "omo runtime",
    "코덱스",
    "클로드 코드",
    "클로드",
    "코딩 에이전트",
    "코딩-agent",
)
# Bare "pi" hides inside "api" and "pipeline", so the omo host CLI only counts
# through these right-bounded forms — and never when the message carries
# Raspberry-Pi (or api) context, which names hardware, not the executor.
# Right-bounding alone is not enough: "raspi status" and "spi status" contain
# "pi status", so these terms are matched with `contains_boundary_phrase`
# (word-boundary occurrence), never raw containment.
_CODING_STATUS_PI_AGENT_TERMS = (
    "pi 진행",
    "pi 상태",
    "pi 세션",
    "pi session",
    "pi progress",
    "pi status",
)
_CODING_STATUS_PI_BLOCKER_TERMS = (
    "raspberry",
    "라즈베리",
    "api",
)
_CODING_STATUS_REQUEST_TERMS = (
    "progress",
    "status",
    "session",
    "where",
    "how far",
    "running",
    "done",
    "completed",
    "진행",
    "진행상황",
    "상태",
    "세션",
    "어디까지",
    "뭐하고",
    "뭐 하고",
    "완료",
    "끝났",
)


@dataclass(frozen=True)
class CodingDelegation:
    action: str
    intent: str
    recommended_workflow: str
    recommended_harness: str
    executor_profile: str
    acceptance_criteria: tuple[str, ...]
    verification: tuple[str, ...]
    review_required: bool
    review_workflow: str | None
    delegation_prompt_template: str

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["acceptance_criteria"] = list(self.acceptance_criteria)
        data["verification"] = list(self.verification)
        return data


def build_coding_delegation_payload(
    message: str,
    *,
    source: str = "generic",
    limit: int = 3,
    include_message: bool = False,
    source_metadata: dict[str, str] | None = None,
    executor_target: str = "generic",
    context_pack: dict[str, object] | None = None,
    memory_recall_pack: dict[str, object] | None = None,
    plan_artifact: dict[str, object] | None = None,
    preferred_workflow: str | None = None,
    preferred_workflow_score: int | None = None,
    prefer_direct_coding_handoff: bool = True,
    force_coding_handoff: bool = False,
    capability_snapshot_directory: Path | None = None,
    project_root: str | Path | None = None,
    governance_default: str = "not_applicable",
    product_family: str | None = None,
    message_context_mode: str = "full",
    safety_preflight: dict[str, object] | None = None,
    live_safety_profile_revision: str | None = None,
    requested_authority_actions: tuple[str, ...] | list[str] | None = None,
) -> dict[str, object]:
    message = message.strip()
    if not message:
        raise ValueError("coding delegate requires a task description")
    if message_context_mode not in MESSAGE_CONTEXT_MODES:
        raise ValueError(f"unsupported coding delegate message context mode: {message_context_mode}")
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported coding delegate source: {source}")
    if executor_target not in CODING_EXECUTOR_TARGETS:
        raise ValueError(f"unsupported coding delegate executor: {executor_target}")
    if limit < 1:
        raise ValueError("coding delegate --limit must be at least 1")
    governance = discover_project_governance(project_root, decision=governance_default) if project_root else None
    family_template = product_family_template(product_family) if product_family else None
    quality_harness = product_quality_harness(product_family) if product_family else None

    full_recommendations = recommend_skills(message, limit=max(limit, 5), apply_guardrails=False)
    full_recommendations = _prioritize_preferred_workflow(
        full_recommendations,
        preferred_workflow=preferred_workflow,
        preferred_workflow_score=preferred_workflow_score,
    )
    recommendations = _compact_recommendations(full_recommendations[:limit])
    top = full_recommendations[0]
    workflow = str(top["skill"])
    score = int(top["score"])
    intent = _intent_for(message, workflow, score)
    if (
        prefer_direct_coding_handoff
        and score >= 4
        and workflow in _RETAINED_HERMES_WORKFLOWS
        and intent == "coding"
        and (plan_artifact is not None or _has_code_reference(message))
    ):
        workflow = "plan"
    action = _action_for(intent, score, workflow)
    if force_coding_handoff and action == "clarify" and intent in {"coding", "review"} and score >= 4:
        action = "delegate"
    if action == "fallback":
        workflow = "oh-my-hermes"
    elif action == "clarify" and workflow not in _RETAINED_HERMES_WORKFLOWS:
        workflow = "oh-my-hermes"
    harness = primary_harness_for_skill(workflow)
    review_required = _review_required(message, intent, workflow)
    delegation = CodingDelegation(
        action=action,
        intent=intent,
        recommended_workflow=workflow,
        recommended_harness=harness,
        executor_profile=_executor_profile(intent, action),
        acceptance_criteria=_acceptance_criteria(intent, action, workflow),
        verification=_verification(intent, action, workflow),
        review_required=review_required,
        review_workflow="code-review" if review_required else None,
        delegation_prompt_template=_delegation_prompt_template(action, intent, workflow, harness),
    )
    payload: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "delegation": delegation.to_dict(),
        "recommendations": recommendations,
        "approval_evidence_rule": APPROVAL_EVIDENCE_RULE,
        "executor_identity_rule": EXECUTOR_IDENTITY_RULE,
        "model_naming_rule": MODEL_NAMING_RULE,
        "readiness_evidence_rule": READINESS_EVIDENCE_RULE,
    }
    proposed_selection = executor_selection_for_target(executor_target, action=delegation.action)
    selection = proposed_selection
    selected_profile = selection.selected_executor_profile
    capability_snapshot = (
        _resolved_executor_capability_snapshot(selected_profile, capability_snapshot_directory)
        if selected_profile
        else None
    )
    executor_local_workflow = (
        build_executor_local_workflow(
            profile=selected_profile,
            routed_workflow=delegation.recommended_workflow,
            parent_handoff_dispatchable=selection.dispatchable,
            availability_evidence=_local_workflow_evidence(capability_snapshot),
        )
        if selected_profile
        else None
    )
    isolation_plan = (
        build_isolation_plan(
            message,
            intent=delegation.intent,
            workflow=delegation.recommended_workflow,
            work_owner_mode=selection.work_owner_mode,
            selected_executor_profile=selection.selected_executor_profile,
        )
        if delegation.action == "delegate"
        else {}
    )
    # Built once and handed to both the preflight and the gate. The gate's
    # risk classifier reads the *declared* request — destinations, access
    # intents, target paths — and rebuilding it there would scan the message a
    # second time to produce a value this build already has.
    preflight_request = _safety_preflight_request(
        message,
        owner=proposed_selection.selected_executor_profile or "hermes",
        workflow=delegation.recommended_workflow,
        message_context_mode=message_context_mode,
        # The same condition `_attach_visible_message` is called under below, so
        # the flag states what the artifact will carry.
        raw_content_included=include_message and message_context_mode == "full",
        intent=delegation.intent,
        action=delegation.action,
    )
    # The single decision path. Every downstream authority value — dispatchable,
    # choice_required, the executor selection status, and which confirmation
    # ladder is armed — is derived from this one verdict; nothing recomputes it.
    gate_verdict = evaluate_action_gate(
        message=message,
        delegation_action=delegation.action,
        intent=delegation.intent,
        review_required=delegation.review_required,
        work_owner_mode=proposed_selection.work_owner_mode,
        selected_executor_profile=proposed_selection.selected_executor_profile,
        dispatch_policy=proposed_selection.dispatch_policy,
        dispatchable=proposed_selection.dispatchable,
        choice_required=proposed_selection.choice_required,
        executor_selection_status=proposed_selection.status,
        isolation_plan=isolation_plan,
        context_pack=context_pack,
        memory_recall_pack=memory_recall_pack,
        safety_preflight=(
            safety_preflight if safety_preflight is not None else _safety_preflight_verdict(preflight_request)
        ),
        # What this build declared it would touch. The gate classifies risk from
        # these declarations and never from the message.
        safety_preflight_request=preflight_request,
        live_safety_profile_revision=live_safety_profile_revision,
        requested_actions=list(requested_authority_actions or []),
    )
    # The #818 safety contract rides back on the verdict because the gate is the
    # one place that runs per build; it is stored beside the gate, not inside
    # it, so there is exactly one copy for a reader to trust.
    action_gate, handoff_safety_contract = split_handoff_safety_contract(gate_verdict)
    authority_envelope = action_gate["authority_envelope"]
    if action_gate["outcome"] == "deny":
        # The deny flows through the same value the record validators read: the
        # selection collapses to retained Hermes so no handoff is built and no
        # ladder is armed, instead of a dispatchable handoff beside a denial.
        selection = denied_executor_selection()
        selected_profile = None
        capability_snapshot = None
        executor_local_workflow = None
        isolation_plan = {}
    payload.update(
        {
            "work_owner_mode": selection.work_owner_mode,
            "selected_executor_profile": selection.selected_executor_profile,
            "dispatch_policy": selection.dispatch_policy,
            "dispatchable": bool(action_gate["dispatchable"]),
            "executor_readiness": executor_readiness_for_selection(
                selection.selected_executor_profile,
                choice_required=bool(action_gate["choice_required"]),
            ),
            "executor_selection": {
                "status": str(action_gate["executor_selection_status"]),
                "choice_required": bool(action_gate["choice_required"]),
                "options": (
                    with_executor_readiness_options(public_executor_options())
                    if action_gate["choice_required"]
                    else []
                ),
            },
            "action_gate": action_gate,
            "handoff_safety_contract": handoff_safety_contract,
            # What the recording surface needs to persist this decision, derived
            # here because this is where the decision was made. `commands.coding`
            # must not re-read the verdict to decide what to store: the gate is
            # the single decision path, and a second reading of it is a second
            # answer. Only the request's *class shape* travels -- never the
            # request -- so this block is safe to serialize wherever the payload
            # goes.
            "blocked_work_decision": decision_from_action_gate(
                action_gate,
                owner=preflight_request.get("owner", "hermes") or "hermes",
                safety_profile_revision=live_safety_profile_revision or "",
                class_shape=request_class_shape(preflight_request),
            ),
        }
    )
    if isolation_plan:
        payload["isolation_plan"] = isolation_plan
    if _inline_coding_policy_applies(
        message.lower(), delegation.intent, delegation.action, bool(action_gate["choice_required"])
    ):
        payload["delegation_policy"] = inline_coding_policy_payload()
    if selection.selected_executor_profile == "codex" and delegation.action == "delegate":
        prompting_contract = _executor_prompting_contract(
            "codex",
            delegation,
            message=message,
            isolation_plan=isolation_plan,
            has_plan_artifact=bool(plan_artifact),
            plan_artifact_status=str(plan_artifact.get("status", "")) if plan_artifact else "",
        )
        payload["executor_handoff"] = _executor_handoff(
            executor_target,
            delegation,
            isolation_plan=isolation_plan,
            prompting_contract=prompting_contract,
            capability_snapshot=capability_snapshot,
            executor_local_workflow=executor_local_workflow,
        )
        _attach_context_pack(payload["executor_handoff"], context_pack)
        _attach_memory_recall_pack(payload["executor_handoff"], memory_recall_pack)
    elif selection.work_owner_mode == "runtime_handoff" and selection.selected_executor_profile and delegation.action == "delegate":
        prompting_contract = _executor_prompting_contract(
            selection.selected_executor_profile,
            delegation,
            message=message,
            isolation_plan=isolation_plan,
            has_plan_artifact=bool(plan_artifact),
            plan_artifact_status=str(plan_artifact.get("status", "")) if plan_artifact else "",
        )
        payload["runtime_handoff"] = _runtime_handoff(
            selection.selected_executor_profile,
            delegation,
            isolation_plan=isolation_plan,
            prompting_contract=prompting_contract,
            capability_snapshot=capability_snapshot,
            executor_local_workflow=executor_local_workflow,
        )
        _attach_context_pack(payload["runtime_handoff"], context_pack)
        _attach_memory_recall_pack(payload["runtime_handoff"], memory_recall_pack)
    elif selection.work_owner_mode == "prompt_only_handoff" and selection.selected_executor_profile and delegation.action == "delegate":
        prompting_contract = _executor_prompting_contract(
            selection.selected_executor_profile,
            delegation,
            message=message,
            isolation_plan=isolation_plan,
            has_plan_artifact=bool(plan_artifact),
            plan_artifact_status=str(plan_artifact.get("status", "")) if plan_artifact else "",
        )
        payload["prompt_handoff"] = _prompt_handoff(
            selection.selected_executor_profile,
            delegation,
            isolation_plan=isolation_plan,
            prompting_contract=prompting_contract,
            capability_snapshot=capability_snapshot,
            executor_local_workflow=executor_local_workflow,
        )
        _attach_context_pack(payload["prompt_handoff"], context_pack)
        _attach_memory_recall_pack(payload["prompt_handoff"], memory_recall_pack)
    specialist_work_quality = build_specialist_work_quality_contract(
        delegation.recommended_workflow,
        phase="implementation" if delegation.action == "delegate" else "planning",
        acceptance_criteria=delegation.acceptance_criteria,
    )
    payload["specialist_work_quality"] = specialist_work_quality
    _attach_specialist_work_quality(payload, specialist_work_quality)
    _attach_role_context_pack(payload)
    _attach_task_authority_envelope(payload, authority_envelope)
    _attach_governance_and_family(payload, governance, family_template, quality_harness)
    payload["harness_quality"] = _public_harness_quality(
        harness,
        action=delegation.action,
        work_owner_mode=selection.work_owner_mode,
        has_executor_handoff="executor_handoff" in payload,
        has_runtime_handoff="runtime_handoff" in payload,
        has_prompt_handoff="prompt_handoff" in payload,
        choice_required=bool(action_gate["choice_required"]),
        runtime_profile=selection.selected_executor_profile,
    )
    metadata = {key: value for key, value in (source_metadata or {}).items() if value}
    if metadata:
        payload["source_metadata"] = metadata
    if plan_artifact:
        payload["plan_artifact"] = plan_artifact
    if include_message:
        _attach_visible_message(payload, message, delegation, bounded=message_context_mode == "bounded")
    agentic_playbook = maybe_build_agentic_playbook(message, delegation_payload=payload)
    if agentic_playbook:
        payload["agentic_playbook"] = agentic_playbook
    return payload


_VISIBLE_PROMPT_KEYS = (
    ("executor_handoff", "executor_handoff_prompt"),
    ("prompt_handoff", "prompt_handoff_prompt"),
    ("runtime_handoff", "runtime_handoff_prompt"),
)


def _attach_bounded_text(payload: dict[str, object], key: str, text: str, *, preserve_structure: bool = False) -> None:
    if preserve_structure:
        # Composed delegate prompts keep their newlines/indentation and the
        # documented `... [truncated, N chars total]` marker, so the preview
        # can sit inside a fenced code block (DELEGATE_PROMPT_DISPLAY_RULE).
        payload[f"{key}_preview"] = bounded_prompt_preview(text)
    else:
        payload[f"{key}_preview"] = compact_visible_text(text, max_chars=MAX_VISIBLE_MESSAGE_CHARS)
    payload[f"{key}_artifact"] = raw_output_artifact_ref(text, source=f"coding_delegate:{key}")


def _attach_visible_message(
    payload: dict[str, object],
    message: str,
    delegation: CodingDelegation,
    *,
    bounded: bool,
) -> None:
    """Attach the raw message and expanded prompts under an explicit context policy.

    Bounded mode is the agent-facing default: previews capped at the
    `context_safety` budget plus verifiable artifact refs (sha256, byte count),
    never the fully expanded prompt. Full mode stays available for wrappers that
    dispatch the expanded prompt verbatim.
    """
    expansions: list[tuple[str, str]] = [
        ("message", message),
        ("delegation_prompt", str(delegation.delegation_prompt_template).replace("{message}", message)),
    ]
    for handoff_key, prompt_key in _VISIBLE_PROMPT_KEYS:
        handoff = payload.get(handoff_key)
        if isinstance(handoff, dict) and "prompt_template" in handoff:
            expansions.append((prompt_key, str(handoff["prompt_template"]).replace("{message}", message)))
    if not bounded:
        for key, text in expansions:
            payload[key] = text
        payload["message_context"] = {
            "schema_version": MESSAGE_CONTEXT_SCHEMA_VERSION,
            "mode": "full",
            "raw_content_included": True,
            "policy": "verbatim_expanded_prompt_for_dispatching_wrappers",
        }
        return
    for key, text in expansions:
        _attach_bounded_text(payload, key, text, preserve_structure=key == "prompt_handoff_prompt")
    payload["message_context"] = {
        "schema_version": MESSAGE_CONTEXT_SCHEMA_VERSION,
        "mode": "bounded",
        "raw_content_included": False,
        "policy": "refs_and_preview_only",
        "bounded_keys": [key for key, _ in expansions],
        "max_preview_chars": MAX_VISIBLE_MESSAGE_CHARS,
        "full_output_flag": "--include-message-full",
    }
    payload["context_budget"] = context_budget_payload()


def _attach_governance_and_family(
    payload: dict[str, object],
    governance: dict[str, object] | None,
    family_template: dict[str, object] | None,
    quality_harness: dict[str, object] | None,
) -> None:
    attachment = governance_handoff_attachment(governance) if governance else {}
    for key in ("executor_handoff", "runtime_handoff", "prompt_handoff"):
        handoff = payload.get(key)
        if not isinstance(handoff, dict):
            continue
        handoff.update(attachment)
        if family_template:
            handoff["product_family_template"] = family_template
        if quality_harness:
            handoff["product_quality_harness"] = quality_harness


def _attach_task_authority_envelope(payload: dict[str, object], envelope: dict[str, object]) -> None:
    """Authority travels with the artifact, not in a separate record family.

    A separate family would introduce a join where the handoff and the authority
    it was prepared under can desynchronize; attaching the envelope to whichever
    handoff exists keeps them one object.
    """
    for key in ("executor_handoff", "runtime_handoff", "prompt_handoff"):
        handoff = payload.get(key)
        if isinstance(handoff, dict):
            handoff["task_authority_envelope"] = envelope


# One more than the evaluator's `MAX_TARGET_PATHS`, so a request naming more
# targets than the bound allows reaches the count rule and denies instead of
# being silently trimmed to an allowed 32. Mirrored rather than imported
# because the evaluator is an optional lane resolved lazily below.
_SAFETY_PREFLIGHT_TARGET_PATH_SCAN_LIMIT = 33


@lru_cache(maxsize=1)
def _safety_preflight_evaluator() -> Any:
    """Resolve the #804/#802 safety preflight evaluator when it is installed.

    Bound lazily so this module keeps working when the evaluator lane is not
    present; the call itself uses the evaluator's real signature.
    """
    try:
        from ..quality.safety_preflight import evaluate_safety_preflight
    except ImportError:
        return None
    return evaluate_safety_preflight


def _path_anchor_start(token: str, start: int) -> int:
    """Extend a file match back over its filesystem anchor and nothing else.

    The file regex stops at the first non-path character, which drops a leading
    `/`, `\\`, or `~`. Re-attaching the anchor keeps an absolute path absolute:
    laundering it into a relative one would hide it from the very rule that is
    supposed to see it. A Windows drive prefix is part of the same anchor, so
    `C:\\Windows\\loader.py` stays the path the caller wrote instead of
    collapsing to `\\Windows\\loader.py`.
    """
    while start > 0 and token[start - 1] in "/\\~":
        start -= 1
    if start == 2 and token[1] == ":" and token[0].isalpha():
        return 0
    return start


def _is_preflight_remote_location(lowered: str) -> bool:
    """`_is_external_location_fragment`, minus its dot-segment false positive.

    That predicate reads any first component containing a dot as a host, which
    is right for `github.com/...` and wrong for `../../etc/loader.py`. A
    relative path that leaves the project has to reach the containment rule
    instead of being filtered out as a remote location, so leading dot segments
    are excluded from the host test here. The routing predicate keeps its own
    behaviour: widening it would change which messages count as code references.
    """
    if lowered.replace("\\", "/").split("/", 1)[0] in {".", ".."}:
        return False
    return _is_external_location_fragment(lowered)


def _safety_preflight_target_paths(message: str) -> list[str]:
    """Filesystem targets the user named in the message, and nothing else.

    Scanning is per whitespace token so an anchor is only ever restored from
    inside the token that carries the file reference. `_CODE_REFERENCE_FILE_RE`
    cannot match a URL scheme, so on a pasted link the match starts after
    `https://` and a message-wide backward walk would swallow the scheme's `//`
    and hand the preflight `//github.com/.../chat.py` -- an absolute path that
    denies. External locations are skipped outright, by the same predicate
    `_has_code_reference` already uses, because a URL is not a filesystem
    target and pasting one is a normal way to open a coding request.
    """
    paths: list[str] = []
    for raw_token in message.split():
        token = raw_token.rstrip(_CODE_REFERENCE_TRIM_CHARS).lstrip(_CODE_REFERENCE_OPENING_TRIM_CHARS)
        if not token or _is_preflight_remote_location(token.lower()):
            continue
        for match in _CODE_REFERENCE_FILE_RE.finditer(token):
            fragment = token[_path_anchor_start(token, match.start()) : match.end()]
            if fragment not in paths:
                paths.append(fragment)
            if len(paths) >= _SAFETY_PREFLIGHT_TARGET_PATH_SCAN_LIMIT:
                return paths
    return paths


def _safety_preflight_access_intents(intent: str, action: str) -> list[str]:
    """Read, write, and share, declared for what this build will actually prepare.

    Read is unconditional: preparing coding work means reading the workspace
    the request names. Write is claimed only when the routed action would carry
    `repo_edit`, on the same intent set `action_gate.required_actions_for` uses
    for that action -- this is a declaration made before the gate runs, and the
    gate's own answer stays the authority on what the envelope grants. Share is
    never claimed, because the lane names no remote target and
    `external_action_authority` is pinned to prepare_only, so there is nothing
    to share with.
    """
    intents = ["read"]
    if action == "delegate" and intent in {"coding", "cleanup", "docs"}:
        intents.append("write")
    return intents


def _safety_preflight_data_classes(target_paths: list[str], raw_content_included: bool) -> list[str]:
    """The data classes this build will actually touch, and no others.

    Bounded metadata is always present: a prepared artifact stores digests,
    paths, and references rather than content. Workspace source appears once
    the user names a file. The user's own request text appears only when the
    build will carry it verbatim, which is the same flag the raw-context rule
    reads. No prohibited class is ever derivable here, which is the point: the
    rule that refuses one is live for any caller, and this lane can never
    produce a request that trips it.
    """
    classes = ["workspace_metadata"]
    if target_paths:
        classes.append("workspace_source")
    if raw_content_included:
        classes.append("user_request_text")
    return classes


def _safety_preflight_request(
    message: str,
    *,
    owner: str,
    workflow: str,
    message_context_mode: str,
    raw_content_included: bool,
    intent: str = "",
    action: str = "",
) -> dict[str, object]:
    """The closed, bounded metadata request the preflight evaluates.

    Target paths come from the *user message* only. Context packs and recall
    packs are deliberately excluded: a path pasted into retrieved content is
    not the user asking for that target, and letting it through would be the
    exact widening #811 forbids.

    The #801 boundary halves are declared here too. `workspace_roots` stays
    empty on purpose: nothing in a chat request narrows the project, and the
    evaluator reads an undeclared boundary as "the project itself", which the
    absolute-path and escape rules already enforce. Declaring a synthetic root
    derived from the very paths it would bound would be a boundary that can
    never refuse anything. `approved_destinations` stays empty for the same
    reason the lane names no remote target: nothing here reaches one, and an
    empty approval approves nothing rather than everything.
    """
    target_paths = _safety_preflight_target_paths(message)
    return {
        "owner": owner,
        "approved_scope": f"coding/{workflow}",
        "message_context_mode": message_context_mode,
        # What this build will actually do with the raw message, not the mode
        # written twice: `_attach_visible_message` emits the verbatim message
        # and expanded prompts only when the caller asked for the message AND
        # the mode is full, so the declaration is False on the default path
        # even under full mode. Re-deriving it from the mode would make the
        # rule unable to disagree with its own input.
        "raw_content_included": raw_content_included,
        "data_classes": _safety_preflight_data_classes(target_paths, raw_content_included),
        "workspace_roots": [],
        "target_paths": target_paths,
        "approved_destinations": [],
        "access_intents": _safety_preflight_access_intents(intent, action),
        "evidence_claims": ["prepared_not_observed"],
    }


def _safety_preflight_verdict(request: dict[str, object]) -> dict[str, object] | None:
    """The preflight verdict for an already-built request, or None when no evaluator is installed.

    Takes the request rather than rebuilding it: the gate reads the same
    declarations to classify action risk, and building it twice would scan the
    message twice to produce one value.

    The two absences stay distinct, which is the distinction the action gate
    then acts on. `None` means the lane is not present and delegation must keep
    working. An installed evaluator that answers with anything other than a
    verdict carrying a status has malfunctioned, and that returns an unreadable
    status the gate denies on rather than the `None` the gate would read as
    "no lane at all". The shape check belongs here because this is the caller
    that knows what the evaluator returns.
    """
    evaluator = _safety_preflight_evaluator()
    if evaluator is None:
        return None
    verdict = evaluator(request)
    if isinstance(verdict, dict) and verdict.get("status"):
        return verdict
    return {"status": "unreadable"}


def _attach_specialist_work_quality(payload: dict[str, object], contract: dict[str, object]) -> None:
    """Attach one prepared-only quality contract to whichever executor handoff exists."""
    for key in ("executor_handoff", "runtime_handoff", "prompt_handoff"):
        handoff = payload.get(key)
        if isinstance(handoff, dict):
            handoff["specialist_work_quality"] = contract


def build_coding_delegation_event_payload(
    event: dict[str, Any] | str,
    *,
    source: str = "generic",
    limit: int = 3,
    include_message: bool = False,
) -> dict[str, object]:
    message = extract_message_text(event)
    return build_coding_delegation_payload(
        message,
        source=source,
        limit=limit,
        include_message=include_message,
        source_metadata=extract_source_metadata(event),
    )


def _attach_context_pack(handoff: object, context_pack: dict[str, object] | None) -> None:
    if not isinstance(handoff, dict) or not context_pack:
        return
    blocked = context_pack.get("blocked_by_conflicts", [])
    if isinstance(blocked, list) and blocked:
        blocked_marker = {
            "schema_version": "handoff_context_blocked/v1",
            "blocked_by_conflicts": blocked,
            "claim_boundary": "Unresolved memory conflicts block this context pack from executor handoff attachment.",
        }
        errors = validate_handoff_context_pack(context_pack, require_conflict_free=False, label="context_pack")
        errors.extend(validate_handoff_context_blocked(blocked_marker, label="context_pack_blocked"))
        if errors:
            raise ValueError("; ".join(errors))
        handoff["context_pack_blocked"] = blocked_marker
        return
    errors = validate_handoff_context_pack(context_pack, require_conflict_free=True, label="context_pack")
    if errors:
        raise ValueError("; ".join(errors))
    handoff["context_pack"] = context_pack


def _attach_role_context_pack(payload: dict[str, object]) -> None:
    """Mint and pin one immutable guidance pack on whichever handoff exists.

    Minting runs after the guidance surfaces are attached, so the pack names
    exactly what survived attachment -- a blocked context pack contributes
    nothing, and a handoff carrying no reviewed guidance still gets a pack,
    an empty one whose hash says so. That ordering is what makes the pinned
    hash unavoidable: there is no route that attaches guidance to a coding
    handoff and skips the hash, because the hash is derived from the handoff
    rather than passed into it.
    """
    for key in ("executor_handoff", "runtime_handoff", "prompt_handoff"):
        handoff = payload.get(key)
        if not isinstance(handoff, dict):
            continue
        context_pack = handoff.get("context_pack")
        memory_recall_pack = handoff.get("memory_recall_pack")
        pin_role_context_pack(
            handoff,
            build_role_context_pack(
                context_pack=context_pack if isinstance(context_pack, dict) else None,
                memory_recall_pack=memory_recall_pack if isinstance(memory_recall_pack, dict) else None,
            ),
        )


def _attach_memory_recall_pack(handoff: object, memory_recall_pack: dict[str, object] | None) -> None:
    if not isinstance(handoff, dict) or not memory_recall_pack:
        return
    if not memory_recall_pack.get("included_records"):
        return
    errors = validate_project_memory_recall_pack(memory_recall_pack, label="memory_recall_pack")
    if errors:
        raise ValueError("; ".join(errors))
    replayable = all(
        isinstance(item.get("replay_evaluation"), dict)
        and item["replay_evaluation"].get("eligible") is True
        and item["replay_evaluation"].get("reason_code") == "eligible"
        for item in memory_recall_pack["included_records"]
        if isinstance(item, dict)
    )
    if not replayable:
        raise ValueError("memory_recall_pack contains legacy or ineligible records and cannot be attached")
    handoff["memory_recall_pack"] = memory_recall_pack


def coding_delegation_record_payload(
    payload: dict[str, object],
    message: str,
    *,
    source_metadata: dict[str, str] | None = None,
) -> dict[str, object]:
    delegation = payload.get("delegation")
    if not isinstance(delegation, dict):
        raise ValueError("coding delegation payload is missing delegation")
    metadata = dict(source_metadata or {})
    payload_metadata = payload.get("source_metadata")
    if isinstance(payload_metadata, dict):
        metadata.update({str(key): str(value) for key, value in payload_metadata.items() if str(value)})
    record: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "record_type": "coding_delegation",
        "source": payload.get("source", "generic"),
        "action": delegation.get("action", "fallback"),
        "intent": delegation.get("intent", "unknown"),
        "recommended_workflow": delegation.get("recommended_workflow", "oh-my-hermes"),
        "recommended_harness": delegation.get("recommended_harness", "coding-handling"),
        "executor_profile": delegation.get("executor_profile", "router"),
        "work_owner_mode": payload.get("work_owner_mode", "retained_hermes"),
        "selected_executor_profile": payload.get("selected_executor_profile"),
        "dispatch_policy": payload.get("dispatch_policy", "prepare_only"),
        "dispatchable": bool(payload.get("dispatchable", False)),
        "executor_selection": payload.get("executor_selection", {}),
        "review_required": bool(delegation.get("review_required", False)),
        "review_workflow": delegation.get("review_workflow"),
        "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
        "message_length": len(message),
        "source_metadata": metadata,
        "recommendation_evidence": payload.get("recommendations", []),
        "harness_quality": payload.get("harness_quality", {}),
        "acceptance_criteria": delegation.get("acceptance_criteria", []),
        "verification": delegation.get("verification", []),
        "status": "prepared_not_observed",
    }
    if isinstance(payload.get("action_gate"), dict):
        record["action_gate"] = payload["action_gate"]
    if isinstance(payload.get("handoff_safety_contract"), dict):
        record["handoff_safety_contract"] = payload["handoff_safety_contract"]
    for key in ("executor_handoff", "runtime_handoff", "prompt_handoff"):
        if isinstance(payload.get(key), dict):
            record[key] = payload[key]
    if isinstance(payload.get("isolation_plan"), dict):
        record["isolation_plan"] = payload["isolation_plan"]
    if isinstance(payload.get("plan_artifact"), dict):
        record["plan_artifact"] = payload["plan_artifact"]
    return record


def inline_coding_policy_payload() -> dict[str, object]:
    """Return the delegation-mandatory policy block for coding-shaped requests."""
    return {
        "schema_version": DELEGATION_POLICY_SCHEMA_VERSION,
        "inline_coding_prohibited": True,
        "policy": INLINE_CODING_POLICY_STATEMENT,
        "ask_user_shape": (
            "Ask which coding agent should own the work — for example Claude Code or Codex — "
            "before any implementation starts."
        ),
    }


# Cues that mark a message as coding-shaped for the prohibition even when
# scoring produced no intent (score 0 → "unknown" → fallback is exactly the
# path a bare "코딩 해줘" takes). Extends the catalog's coding terms with the
# bare activity words the catalog reserves for stronger signals; matched with
# the same substring rule `_intent_for` already uses for these terms.
_INLINE_CODING_POLICY_EXTRA_TERMS = ("coding", "코딩", "패치", "patch ", " 짜줘", "코드 좀")


def _message_is_coding_shaped(lowered_message: str, intent: str) -> bool:
    if intent in {"coding", "review"}:
        return True
    if _has_any(lowered_message, coding_terms_for_intent("coding")):
        return True
    return _has_any(lowered_message, _INLINE_CODING_POLICY_EXTRA_TERMS)


def _inline_coding_policy_applies(lowered_message: str, intent: str, action: str, choice_required: bool) -> bool:
    # The prohibition is product-wide; the block rides every payload where a
    # wrapper could otherwise read "Hermes keeps it" into coding-shaped work:
    # clarify/fallback outcomes (including score-0 fallbacks like a bare
    # "코딩 해줘") and unresolved-owner delegations, including retained
    # workflows. Wrappers read it from the payload; retained-workflow chat
    # cards keep their contractually executor-free copy and never render it
    # into user-facing text.
    if not _message_is_coding_shaped(lowered_message, intent):
        return False
    return action != "delegate" or choice_required


def _intent_for(message: str, workflow: str, score: int) -> str:
    if score == 0:
        return "unknown"
    lowered = message.lower()
    if _coding_status_request_applies(lowered, workflow):
        return "coding"
    if workflow in _CATALOG_INTENT_RETAINED_WORKFLOWS:
        if _has_any(lowered, coding_terms_for_intent("coding")):
            return "coding"
        return coding_intent_for_skill(workflow)
    for intent in CODING_INTENT_PRIORITY:
        if workflow in coding_skills_for_intent(intent) or _has_any(lowered, coding_terms_for_intent(intent)):
            return intent
    return coding_intent_for_skill(workflow)


def _coding_status_request_applies(lowered: str, workflow: str) -> bool:
    if workflow != "ultraprocess":
        return False
    if not _has_any(lowered, _CODING_STATUS_REQUEST_TERMS):
        return False
    if _has_any(lowered, _CODING_STATUS_AGENT_TERMS):
        return True
    return contains_boundary_phrase(lowered, _CODING_STATUS_PI_AGENT_TERMS) and not _has_any(
        lowered, _CODING_STATUS_PI_BLOCKER_TERMS
    )


def _action_for(intent: str, score: int, workflow: str) -> str:
    if intent == "unknown":
        return "fallback"
    if workflow in _RETAINED_HERMES_WORKFLOWS:
        return "clarify"
    if score < 4:
        return "clarify"
    return "delegate"


def _has_code_reference(message: str) -> bool:
    has_code_context = _CODE_REFERENCE_CONTEXT_RE.search(message) is not None
    for raw_fragment in message.split():
        fragment = raw_fragment.strip(_CODE_REFERENCE_TRIM_CHARS)
        lowered = fragment.lower()
        if not lowered or _is_external_location_fragment(lowered):
            continue
        if any(prefix in lowered for prefix in _CODE_REFERENCE_PREFIXES):
            return True
        if _CODE_REFERENCE_FILE_RE.search(fragment) and (_is_path_fragment(fragment) or has_code_context):
            return True
    return False


def _is_path_fragment(fragment: str) -> bool:
    return "/" in fragment or "\\" in fragment


def _is_external_location_fragment(fragment: str) -> bool:
    if "://" in fragment or fragment.startswith("www."):
        return True
    normalized = fragment.replace("\\", "/")
    if "/" not in normalized:
        return False
    first_path_component = normalized.split("/", 1)[0]
    return "." in first_path_component and not any(normalized.startswith(prefix) for prefix in _CODE_REFERENCE_PREFIXES)


def _review_required(message: str, intent: str, workflow: str) -> bool:
    lowered = message.lower()
    if workflow in _RETAINED_HERMES_WORKFLOWS:
        return False
    if workflow == "code-review" or intent == "review":
        return True
    return _has_any(lowered, CODING_REVIEW_TERMS)


def _executor_profile(intent: str, action: str) -> str:
    if action == "fallback":
        return "router"
    if action == "clarify":
        return "planner"
    return {
        "planning": "planner",
        "review": "reviewer",
        "diagnostics": "qa-verifier",
        "docs": "docs-writer",
    }.get(intent, "coding-agent")


def _acceptance_criteria(intent: str, action: str, workflow: str) -> tuple[str, ...]:
    if action == "fallback":
        return (
            "Clarify the desired coding outcome before dispatching to an executor.",
            "Do not claim code was implemented or reviewed.",
        )
    if action == "clarify":
        if workflow in _RETAINED_HERMES_WORKFLOWS:
            return (
                "Confirm the retained Hermes workflow scope before advancing the next visible stage.",
                "Keep missing evidence explicit and avoid claiming execution or a coding handoff.",
            )
        return (
            "Ask the smallest blocking clarification before executor/runtime dispatch.",
            "Preserve the original task constraints in the eventual handoff.",
        )
    criteria = {
        "planning": (
            "Produce an execution-ready plan with goals, non-goals, risks, and acceptance criteria.",
            "Identify the verification commands or evidence required before implementation starts.",
        ),
        "review": (
            "Review the referenced code or plan with findings first and concrete evidence.",
            "State clearly when no actionable issue is found.",
        ),
        "diagnostics": (
            "Reproduce or inspect the reported failure before proposing a fix.",
            "Record the smallest evidence that proves the diagnosis.",
        ),
        "docs": (
            "Update documentation to match implemented behavior and known limitations.",
            "Keep examples reproducible and conservative.",
        ),
    }.get(
        intent,
        (
            "Implement only the requested coding change within the discovered scope.",
            "Preserve existing behavior outside the requested change.",
        ),
    )
    return criteria


def _verification(intent: str, action: str, workflow: str) -> tuple[str, ...]:
    if action == "fallback":
        return ("No executor verification until the task is clarified.",)
    if action == "clarify":
        if workflow in _RETAINED_HERMES_WORKFLOWS:
            return ("Verify the retained Hermes response names scope, evidence boundary, and next visible action.",)
        return ("Verify the clarified handoff includes scope, constraints, and stop condition.",)
    checks = {
        "planning": ("Review the plan for testable acceptance criteria.", "Run implementation checks only after execution starts."),
        "review": ("Cite file, diff, command, or test evidence for every finding.",),
        "diagnostics": ("Run the smallest diagnostic or health check that can prove the claim.",),
        "docs": ("Run docs generation/check commands when docs are generated.",),
    }.get(
        intent,
        ("Run targeted tests for the changed behavior.", "Run static or compile checks when available."),
    )
    return checks


def _executor_handoff(
    executor_target: str,
    delegation: CodingDelegation,
    *,
    isolation_plan: dict[str, object],
    prompting_contract: dict[str, object],
    capability_snapshot: dict[str, object] | None,
    executor_local_workflow: dict[str, object] | None,
) -> dict[str, object]:
    if executor_target != "codex":
        raise ValueError(f"unsupported coding delegate executor: {executor_target}")
    if executor_local_workflow is None:
        raise KeyError("executor_local_workflow")
    candidate = executor_local_workflow["candidate"]
    if not isinstance(candidate, dict):
        raise KeyError("executor_local_workflow.candidate")
    candidate_invocation = candidate.get("invocation")
    dispatchability = executor_local_workflow.get("dispatchability")
    if not isinstance(candidate_invocation, dict) or not isinstance(dispatchability, dict):
        raise KeyError("executor_local_workflow candidate invocation or dispatchability")
    candidate_template = str(candidate_invocation["template"])
    codex_skill = candidate_template.removesuffix(" {message}")
    candidate_dispatchable = dispatchability.get("candidate_invocation_dispatchable") is True
    dispatch_text_template = candidate_template if candidate_dispatchable else "{message}"
    handoff: dict[str, object] = {
        "schema_version": EXECUTOR_HANDOFF_SCHEMA_VERSION,
        "work_owner_mode": "external_executor",
        "selected_executor_profile": "codex",
        "dispatch_policy": "ask_before_dispatch",
        "dispatchable": True,
        "executor_target": "codex",
        "handoff_mode": "instruction_payload",
        "send_action": "send_to_executor",
        "codex_skill": codex_skill,
        "codex_invocation": {
            "syntax": "$skill",
            "skill": codex_skill,
            "dispatch_text_template": dispatch_text_template,
            "message_placeholder": "{message}",
            "wrapper_note": "Replace {message} only at dispatch time; do not persist the raw task in OMH artifacts.",
        },
        "executor_local_capability_strategy": _executor_local_capability_strategy("codex"),
        "executor_capability_snapshot": capability_snapshot or _prepared_executor_capability_snapshot("codex"),
        "executor_local_workflow": executor_local_workflow,
        "status": "prepared_not_observed",
        "recording_contract": "prepared_not_observed",
        "dispatch_contract": "wrapper_dispatches_to_codex; omh_does_not_execute_codex",
        "executor_readiness": executor_readiness_contract("codex"),
        "task_prompt_contract": _task_prompt_contract("codex"),
        "executor_prompting_contract": prompting_contract,
        "session_observation_contract": _codex_session_observation_contract(),
        "local_capability_report_contract": _local_capability_report_contract("codex"),
        "prompt_template": _codex_prompt_template(
            delegation,
            candidate_template=candidate_template if candidate_dispatchable else None,
            prompting_contract=prompting_contract,
        ),
        "execution_brief": {
            "task_source": str(prompting_contract["task_source"]),
            "recommended_workflow": delegation.recommended_workflow,
            "recommended_harness": delegation.recommended_harness,
            "intent": delegation.intent,
            "codex_owns": [
                "repository inspection",
                "code edits when needed",
                "tests and verification",
                "commits or PR updates when authorized",
                "executor evidence report",
            ],
            "hermes_owns": [
                "chat intake",
                "plan and status narration",
                "prepared versus observed evidence boundaries",
            ],
        },
        "isolation_plan": isolation_plan,
        "scope": [
            "Use the original task message as the implementation request.",
            (
                f"Ask before dispatching the observed Codex-side workflow `{candidate_template}`."
                if candidate_dispatchable
                else "Keep dispatch text generic because the executor-local workflow is not observed available."
            ),
            "Respect the recommended OMH workflow and harness metadata.",
            "Keep Hermes-facing status separate from Codex execution evidence.",
        ],
        "non_goals": [
            "Do not claim Hermes implemented the code.",
            "Do not claim review, CI, or merge status without wrapper evidence.",
            "Do not call network services from omh while preparing this handoff.",
        ],
        "acceptance_criteria": list(delegation.acceptance_criteria),
        "verification": list(delegation.verification),
        "review": {
            "required": delegation.review_required,
            "workflow": delegation.review_workflow,
            "evidence_required": "Record separate wrapper/runtime evidence before marking review observed.",
        },
        "report_contract": {
            "allowed_statuses": ["completed", "blocked", "failed"],
            "required_fields": [
                "status",
                "changed_files",
                "commits",
                "tests_run",
                "blockers",
                "evidence_refs",
            ],
            "review_fields": ["review_comments_addressed", "remaining_review_risks"],
        },
        "evidence_contract": {
            "prepared_is_not": ["dispatch", "implementation", "verification", "review", "ci", "merge"],
            "observed_required_for": [
                "executor_dispatch",
                "executor_result",
                "verification",
                "review",
                "ci",
                "merge_readiness",
                "merge",
            ],
        },
        "harness_quality": harness_quality_contract(delegation.recommended_harness),
    }
    return handoff


def _prompt_handoff(
    profile: str,
    delegation: CodingDelegation,
    *,
    isolation_plan: dict[str, object],
    prompting_contract: dict[str, object],
    capability_snapshot: dict[str, object] | None,
    executor_local_workflow: dict[str, object] | None,
) -> dict[str, object]:
    invocation = prompt_invocation_for_profile(profile)
    label = executor_label(profile)
    handoff: dict[str, object] = {
        "schema_version": PROMPT_HANDOFF_SCHEMA_VERSION,
        "work_owner_mode": "prompt_only_handoff",
        "selected_executor_profile": profile,
        "dispatchable": False,
        "invocation": invocation,
        "status": "prepared_not_observed",
        "recording_contract": "prompt_prepared_not_dispatched",
        "dispatch_contract": "prompt_only_no_dispatch",
        "executor_readiness": executor_readiness_contract(profile),
        "executor_local_capability_strategy": _executor_local_capability_strategy(profile),
        "executor_capability_snapshot": capability_snapshot or _prepared_executor_capability_snapshot(profile),
        "task_prompt_contract": _task_prompt_contract(profile),
        "executor_prompting_contract": prompting_contract,
        "local_capability_report_contract": _local_capability_report_contract(profile),
        "prompt_template": _prompt_only_template(
            delegation,
            profile=profile,
            label=label,
            prompting_contract=prompting_contract,
        ),
        "isolation_plan": isolation_plan,
        "scope": [
            "Use the original task message as the executor request.",
            f"Give the prompt to {label} only after the user chooses that executor.",
            "Keep OMH wrapper/session state separate from executor evidence.",
        ],
        "non_goals": [
            "Do not claim OMH or Hermes dispatched the prompt.",
            "Do not create a lifecycle run for this prompt-only handoff.",
            "Do not claim implementation, review, CI, or merge status from a prepared prompt.",
        ],
        "acceptance_criteria": list(delegation.acceptance_criteria),
        "verification": list(delegation.verification),
        "review": {
            "required": delegation.review_required,
            "workflow": delegation.review_workflow,
            "evidence_required": "Review evidence must be reported by the chosen executor or wrapper after real work occurs.",
        },
        "evidence_contract": {
            "prepared_is_not": ["dispatch", "implementation", "verification", "review", "ci", "merge"],
            "observed_required_for": [
                "executor_dispatch",
                "executor_result",
                "verification",
                "review",
                "ci",
                "merge_readiness",
                "merge",
            ],
        },
        "harness_quality": with_wrapper_actions(
            harness_quality_contract(delegation.recommended_harness),
            ("show_prompt_handoff", "copy_prompt_handoff", "choose_executor", "show_status"),
        ),
    }
    if executor_local_workflow is not None:
        handoff["executor_local_workflow"] = executor_local_workflow
    if profile == "claude-code":
        handoff["session_observation_contract"] = _claude_code_session_observation_contract()
    return handoff


def _runtime_handoff(
    profile: str,
    delegation: CodingDelegation,
    *,
    isolation_plan: dict[str, object],
    prompting_contract: dict[str, object],
    capability_snapshot: dict[str, object] | None,
    executor_local_workflow: dict[str, object] | None,
) -> dict[str, object]:
    invocation = runtime_invocation_for_profile(profile)
    contract = runtime_profile_contract(profile)
    label = executor_label(profile)
    handoff: dict[str, object] = {
        "schema_version": RUNTIME_HANDOFF_SCHEMA_VERSION,
        "work_owner_mode": "runtime_handoff",
        "selected_executor_profile": profile,
        "runtime_profile": contract,
        "dispatchable": False,
        "invocation": invocation,
        "status": "prepared_not_observed",
        "recording_contract": "runtime_prepared_not_started",
        "dispatch_contract": "wrapper_or_user_starts_runtime; omh_does_not_execute_runtime",
        "executor_readiness": executor_readiness_contract(profile),
        "executor_local_capability_strategy": _executor_local_capability_strategy(profile),
        "executor_capability_snapshot": capability_snapshot or _prepared_executor_capability_snapshot(profile),
        "task_prompt_contract": _task_prompt_contract(profile),
        "executor_prompting_contract": prompting_contract,
        "local_capability_report_contract": _local_capability_report_contract(profile),
        "prompt_template": _runtime_prompt_template(
            delegation,
            profile=profile,
            label=label,
            prompting_contract=prompting_contract,
        ),
        "runtime_brief": {
            "task_source": str(prompting_contract["task_source"]),
            "recommended_workflow": delegation.recommended_workflow,
            "recommended_harness": delegation.recommended_harness,
            "intent": delegation.intent,
            "runtime_owns": [
                "repository inspection when coding is selected",
                "team or swarm lane creation when the task is safely splittable",
                "tmux-style worker or pane coordination when the chosen runtime supports it",
                "worker ACK/claim/result discipline",
                "worktree isolation when parallel, risky, or multi-file coding starts",
                "verification evidence reporting",
            ],
            "hermes_owns": [
                "chat intake",
                "runtime selection narration",
                "prepared versus observed evidence boundaries",
                "status narration from observed runtime artifacts",
            ],
        },
        "isolation_plan": isolation_plan,
        "runtime_templates": runtime_templates_for_profile(profile),
        "team_contract": {
            "modes": ["solo", "team", "swarm"],
            "leader_owns": [
                "scope split",
                "worker assignment",
                "shared-file conflict control",
                "verification integration",
                "final status report",
            ],
            "worker_protocol": [
                "ACK assigned lane before editing",
                "use tmux-style worker labels or equivalent runtime lane IDs for parallel work",
                "claim files or worktree before shared changes",
                "report changed files, tests, blockers, and evidence refs",
                "escalate scope expansion to the leader",
            ],
            "fanout_when": [
                "lanes are independent",
                "verification can be integrated by one leader",
                "parallel worktree or file ownership is explicit",
            ],
            "do_not_fanout_when": [
                "requirements are still ambiguous",
                "lanes would edit the same files without a merge plan",
                "review or verification ownership is unclear",
            ],
        },
        "worktree_contract": {
            "policy": "recommended_for_parallel_or_risky_coding",
            "isolation": "use one branch/worktree per worker lane when more than one coding agent may edit the repository",
            "required_before": [
                "parallel implementation",
                "risky refactor",
                "large generated changes",
                "team or swarm coding",
            ],
            "not_observed_by_omh": [
                "worktree creation",
                "branch creation",
                "worker process launch",
                "merge back to main worktree",
            ],
        },
        "observation_contract": {
            "record_schema": "runtime_observation/v1",
            "record_with": (
                "omh runtime observe --session <wrapper-session-id> --runtime-profile "
                f"{profile} --event <runtime_start|worktree_creation|worker_dispatch|worker_result|verification|review|ci|merge_readiness|merge> "
                "--status <observed|blocked|failed|not_observed> --summary <observed metadata>"
            ),
            "allowed_events": [
                "runtime_start",
                "worktree_creation",
                "worker_dispatch",
                "worker_result",
                "verification",
                "review",
                "ci",
                "merge_readiness",
                "merge",
            ],
            "status_ladder": [
                "runtime_start",
                "worktree_creation",
                "worker_dispatch",
                "worker_result",
                "verification",
                "review",
                "ci",
                "merge_readiness",
                "merge",
            ],
            "claim_boundary": (
                "Runtime templates are prepared guidance. Runtime status changes only when a wrapper or operator records "
                "runtime_observation/v1 evidence."
            ),
        },
        "scope": [
            "Use the original task message as the runtime request.",
            f"Run {label} with the recommended OMH workflow unless local runtime routing has stronger evidence.",
            "For Hermes-owned coding, use OMH coding skills directly instead of pretending a separate executor ran.",
            "For OMX/OMO/OMC, treat the runtime as the chosen oh-my execution layer, not a plain prompt.",
            "Keep prepared runtime state separate from observed runtime evidence.",
        ],
        "non_goals": [
            "Do not claim OMH started the runtime.",
            "Do not claim worktrees, workers, subagents, or tmux panes exist until observed.",
            "Do not claim implementation, review, CI, or merge status from this prepared runtime handoff.",
        ],
        "acceptance_criteria": list(delegation.acceptance_criteria),
        "verification": list(delegation.verification),
        "review": {
            "required": delegation.review_required,
            "workflow": delegation.review_workflow,
            "evidence_required": "Runtime review evidence must be reported after real runtime work occurs.",
        },
        "evidence_contract": {
            "prepared_is_not": [
                "runtime_start",
                "worktree_creation",
                "worker_dispatch",
                "implementation",
                "verification",
                "review",
                "ci",
                "merge",
            ],
            "observed_required_for": [
                "runtime_start",
                "worktree_creation",
                "worker_dispatch",
                "worker_result",
                "verification",
                "review",
                "ci",
                "merge_readiness",
                "merge",
            ],
        },
        "harness_quality": with_wrapper_actions(
            harness_quality_contract(delegation.recommended_harness),
            _runtime_wrapper_actions(profile),
        ),
    }
    team_path = hermes_coding_team_path_contract(profile)
    if team_path:
        handoff["hermes_coding_team_path"] = team_path
        handoff["hermes_coding_harness"] = build_hermes_coding_harness(runtime_handoff=handoff)
    if executor_local_workflow is not None:
        handoff["executor_local_workflow"] = executor_local_workflow
    return handoff


def _public_harness_quality(
    harness: str,
    *,
    action: str,
    work_owner_mode: str,
    has_executor_handoff: bool,
    has_runtime_handoff: bool,
    has_prompt_handoff: bool,
    choice_required: bool,
    runtime_profile: str | None,
) -> dict[str, object]:
    contract = harness_quality_contract(harness)
    if action == "delegate" and has_executor_handoff:
        return with_wrapper_actions(contract, ("send_to_executor", "send_to_codex", "show_status"))
    if action == "delegate" and has_runtime_handoff:
        return with_wrapper_actions(contract, _runtime_wrapper_actions(runtime_profile or ""))
    if action == "delegate" and has_prompt_handoff:
        return with_wrapper_actions(contract, ("show_prompt_handoff", "copy_prompt_handoff", "choose_executor", "show_status"))
    if action == "delegate" and work_owner_mode == "runtime_handoff":
        return with_wrapper_actions(contract, ("show_runtime_handoff", "choose_executor", "show_status"))
    if action == "delegate" and work_owner_mode == "prompt_only_handoff":
        return with_wrapper_actions(contract, ("show_prompt_handoff", "copy_prompt_handoff", "choose_executor", "show_status"))
    if action == "delegate" and choice_required:
        return with_wrapper_actions(contract, ("choose_executor", "show_status"))
    if work_owner_mode == "retained_hermes":
        return with_wrapper_actions(contract, ("show_status",))
    return with_wrapper_actions(contract, ("show_status",))


def _runtime_wrapper_actions(profile: str) -> tuple[str, ...]:
    if profile == "hermes":
        return (
            "show_runtime_handoff",
            *HERMES_CODING_TEAM_WRAPPER_ACTIONS[:-1],
            "choose_executor",
            HERMES_CODING_TEAM_WRAPPER_ACTIONS[-1],
        )
    return (
        "show_runtime_handoff",
        "start_runtime",
        "prepare_worktree",
        "start_team",
        "start_swarm",
        "choose_executor",
        "show_status",
    )


def _executor_local_capability_strategy(profile: str) -> dict[str, object]:
    return {
        "schema_version": _LOCAL_CAPABILITY_STRATEGY_SCHEMA_VERSION,
        "profile": profile,
        "mode": "discover_then_use_when_helpful",
        "installation_observed": False,
        "execution_observed": False,
        "preferred_sources": list(_LOCAL_CAPABILITY_PREFERRED_SOURCES),
        "stage_guidance": dict(_LOCAL_CAPABILITY_STAGE_GUIDANCE),
        "examples_if_available": {key: list(values) for key, values in _LOCAL_CAPABILITY_EXAMPLES.items()},
        "selection_rule": (
            "Use local capabilities only when they materially improve planning, implementation, "
            "verification, review, or coordination; otherwise keep the handoff plain and focused."
        ),
        "fallback": _local_capability_fallback(profile),
        "claim_boundary": (
            "This strategy is prepared guidance only; it is not evidence that local executor "
            "capabilities exist, were loaded, or were executed."
        ),
    }


def _prepared_executor_capability_snapshot(profile: str) -> dict[str, object]:
    capabilities = {name: {"status": "unknown"} for name in sorted(KNOWN_CAPABILITY_NAMES)}
    capabilities["worktree_isolation"] = {"status": "prepared"}
    return build_executor_capability_snapshot(executor=profile, capabilities=capabilities)


def _resolved_executor_capability_snapshot(profile: str, directory: Path | None) -> dict[str, object]:
    if directory is not None:
        snapshot = read_matching_executor_capability_snapshot(
            executor_capability_snapshot_path(directory, profile),
            expected_executor=profile,
        )
        if snapshot is not None:
            return snapshot
    return _prepared_executor_capability_snapshot(profile)


def _local_workflow_evidence(snapshot: dict[str, object] | None) -> dict[str, object] | None:
    if snapshot is None:
        return None
    capabilities = snapshot.get("capabilities")
    if not isinstance(capabilities, dict):
        return None
    evidence = capabilities.get(LOCAL_WORKFLOW_CAPABILITY_NAME)
    if not isinstance(evidence, dict):
        return None
    return {**evidence, "recorded_at": snapshot.get("recorded_at", "")}


def _local_capability_fallback(profile: str) -> str:
    fallback_labels = {
        "codex": "plain Codex",
        "claude-code": "plain Claude Code",
        "generic": "plain generic executor",
        "hermes": "plain Hermes runtime",
        "omx-runtime": "plain OMX runtime",
        "omo-runtime": "plain OMO runtime",
        "omc-runtime": "plain OMC runtime",
    }
    label = fallback_labels.get(profile, f"plain {executor_label(profile)}")
    return (
        f"If no relevant local capability is available or recognized, continue as the selected executor using "
        f"the OMH task, harness, acceptance criteria, verification, and evidence contract as a {label} task."
    )


def _task_prompt_contract(profile: str) -> dict[str, object]:
    return {
        "schema_version": TASK_PROMPT_CONTRACT_SCHEMA_VERSION,
        "profile": profile,
        "status": "prepared_not_observed",
        "required_sections": list(TASK_PROMPT_REQUIRED_SECTIONS),
        "language_policy": (
            "Use English for executor-facing dispatch prompts unless preserving identifiers, paths, "
            "error text, quoted user-facing copy, or target-language output."
        ),
        "steering_policy": (
            "When steering an active executor turn, send only the changed constraint, result, or blocker; "
            "do not replay the full prepared prompt unless the executor explicitly needs a restart."
        ),
        "claim_boundary": (
            "This contract describes prepared prompt shape only; it is not dispatch, execution, "
            "verification, review, CI, or merge evidence."
        ),
    }


def _executor_prompting_contract(
    profile: str,
    delegation: CodingDelegation,
    *,
    message: str,
    isolation_plan: dict[str, object],
    has_plan_artifact: bool,
    plan_artifact_status: str,
) -> dict[str, object]:
    return build_executor_prompting_contract(
        profile,
        intent=delegation.intent,
        message=message,
        has_plan_artifact=has_plan_artifact,
        plan_artifact_status=plan_artifact_status,
        isolation_plan=isolation_plan,
    )


def _codex_session_observation_contract() -> dict[str, object]:
    return {
        "schema_version": CODEX_SESSION_OBSERVATION_CONTRACT_SCHEMA_VERSION,
        "profile": "codex",
        "status": "prepared_not_observed",
        "identity_fields": ["thread_id", "turn_id", "cwd", "git_sha", "executor_profile"],
        "status_fields": [
            "thread_status.type",
            "thread_status.active_flags",
            "turn_status",
            "turn_error.message",
            "approval_requests",
            "user_input_requests",
        ],
        "completion_statuses": ["completed"],
        "blocker_statuses": ["interrupted", "failed", "inProgress", "waitingOnApproval", "waitingOnUserInput"],
        "final_answer_rule": (
            "Use the full final agent message or executor result when observed; do not use truncated "
            "list/read previews as the completion answer."
        ),
        "approval_rule": (
            "Approval or user-input waits are blockers until an explicit observed approval, rejection, or input "
            "is recorded; never auto-approve from a prepared handoff. A compaction or session resume is never "
            "that observed approval."
        ),
        "event_filter_rule": "Observe only events for the matching thread and turn identifiers.",
        "observed_state_owner": [
            "runtime_observation/v1",
            "executor_session/v1",
            "coding_lifecycle",
            "coding_briefing/v1",
        ],
        "not_implemented": [
            "websocket_client",
            "host_token_lookup",
            "polling_connector",
            "appserver_dispatch",
            "auto_approval",
        ],
        "claim_boundary": (
            "This is a prepared Codex session observation requirement, not live telemetry or completion evidence. "
            "Observed execution state must be recorded through OMH runtime, executor-session, lifecycle, or briefing evidence."
        ),
    }


def _claude_code_session_observation_contract() -> dict[str, object]:
    return {
        "schema_version": CLAUDE_CODE_SESSION_OBSERVATION_CONTRACT_SCHEMA_VERSION,
        "profile": "claude-code",
        "status": "prepared_not_observed",
        "identity_fields": ["session_id", "turn_id", "cwd", "git_sha", "executor_profile", "project_path"],
        "status_fields": [
            "session_status",
            "turn_status",
            "tool_use_status",
            "approval_requests",
            "user_input_requests",
            "subagent_status",
            "slash_command_invocations",
        ],
        "completion_statuses": ["completed"],
        "blocker_statuses": ["interrupted", "failed", "inProgress", "waitingOnApproval", "waitingOnUserInput"],
        "final_answer_rule": (
            "Use the full final Claude Code message or executor result when observed; do not use truncated "
            "list/read previews as the completion answer."
        ),
        "approval_rule": (
            "Approval or user-input waits are blockers until an explicit observed approval, rejection, or input "
            "is recorded; never auto-approve from a prepared handoff. A compaction or session resume is never "
            "that observed approval."
        ),
        "event_filter_rule": "Observe only events for the matching Claude Code session and turn identifiers.",
        "observed_state_owner": [
            "executor_session/v1",
            "wrapper_session",
            "coding_lifecycle",
            "coding_briefing/v1",
        ],
        "not_implemented": [
            "claude_code_log_reader",
            "session_log_connector",
            "mcp_host_polling",
            "prompt_dispatch",
            "auto_approval",
        ],
        "claim_boundary": (
            "This is a prepared Claude Code session observation requirement, not live telemetry or completion evidence. "
            "Observed execution state must be recorded through OMH runtime, executor-session, lifecycle, or briefing evidence."
        ),
    }


def _local_capability_report_contract(profile: str) -> dict[str, object]:
    return {
        "schema_version": LOCAL_CAPABILITY_REPORT_CONTRACT_SCHEMA_VERSION,
        "profile": profile,
        "status": "prepared_not_observed",
        "required_fields": list(LOCAL_CAPABILITY_REPORT_REQUIRED_FIELDS),
        "capability_item_fields": list(LOCAL_CAPABILITY_REPORT_CAPABILITY_FIELDS),
        "allowed_capability_kinds": list(LOCAL_CAPABILITY_REPORT_ALLOWED_KINDS),
        "empty_report_policy": (
            "If no relevant local capability was used, report local_capabilities_used=[] and set "
            "local_capability_fallback_reason to the plain-executor fallback reason."
        ),
        "evidence_rule": (
            "Each local_capabilities_used item must include an evidence_ref that points to actual executor output, "
            "a command, a log, or a generated artifact; do not report guessed or merely available capabilities as used."
        ),
        "claim_boundary": (
            "This is a prepared report-shape contract, not evidence that OMH observed local capability availability, "
            "dispatch, execution, review, CI, merge readiness, or merge."
        ),
    }


def _task_prompt_shape_block() -> str:
    return (
        "Task prompt shape:\n"
        "- Shape executor-facing work as: Goal / Do / Don't / Expected result / Test.\n"
        "- Extend that base with required executor sections: "
        + " / ".join(EXECUTOR_PROMPTING_REQUIRED_SECTIONS)
        + ".\n"
        + "- Keep dispatch prompts in English unless preserving identifiers, paths, errors, quotes, or target-language output.\n"
        + "- If steering an active turn, send only the corrective delta instead of replaying the full prompt.\n\n"
    )


def _local_capability_prompt_block(profile: str, label: str) -> str:
    if profile == "codex":
        return (
            "Local capability discovery:\n"
            "- Before implementing, inspect the executor environment for relevant local capabilities: project instructions, "
            "AGENTS.md, Codex-native skills/workflows, user-installed workflow packs including installed OMX/oh-my workflow "
            "packs, custom Codex skills, Codex subagents, MCP tools, repo scripts, tests, and CI metadata.\n"
            "- Examples, if actually available: OMX or other oh-my triggers such as $ralplan, $ultragoal, $ultrawork, "
            "$ultraqa, or $code-review; $ralph for persistent completion loops; custom Codex skills; or Codex subagents. "
            "These are examples, not requirements.\n"
            "- If a relevant local skill, workflow pack, or subagent exists and materially improves planning, "
            "implementation, verification, review, or coordination, use that executor-native capability before falling "
            "back to the generic prompt.\n"
            "- If no relevant local capability is available, proceed as plain Codex using this task, harness, and evidence "
            "contract.\n"
            "- Do not claim OMH observed local capability availability, dispatch, implementation, review, CI, or merge.\n\n"
        )
    if profile == "claude-code":
        return (
            "Local capability discovery:\n"
            "- Before acting, inspect project instructions and executor-local capabilities such as AGENTS.md, CLAUDE.md, "
            "slash commands, skills, subagents, MCP tools, repo scripts, tests, and CI metadata, plus installed skill packs.\n"
            "- For Claude Code, examples include Everything Claude Code skill packs, user-defined Claude Code skills, "
            "custom Claude Code slash commands, Claude Code agents/subagents, and MCP tools when actually available. "
            "These are examples, not requirements.\n"
            "- If a relevant Claude Code skill, slash command, custom agent, or skill pack exists and materially improves "
            "planning, implementation, verification, review, or coordination, use that executor-native capability before "
            "falling back to the generic prompt.\n"
            f"- If no relevant local capability is available, proceed as a plain {label} task using this task, harness, "
            "and evidence contract.\n"
            "- Do not claim OMH observed capability availability or execution.\n\n"
        )
    return (
        "Local capability discovery:\n"
        "- Before acting, inspect project instructions and executor-local capabilities such as AGENTS.md, CLAUDE.md, "
        "slash commands, skills, subagents, MCP tools, repo scripts, tests, and CI metadata, plus installed skill packs.\n"
        "- If a relevant local skill, command, workflow pack, or custom agent exists and materially improves planning, "
        "implementation, verification, review, or coordination, use that executor-native capability before falling back "
        "to the generic prompt.\n"
        f"- If no relevant local capability is available, proceed as a plain {label} task using this task, harness, and "
        "evidence contract.\n"
        "- Do not claim OMH observed capability availability or execution.\n\n"
    )


def _runtime_local_capability_prompt_block(profile: str, label: str) -> str:
    runtime_examples = "OMX/OMO/OMC templates"
    if profile == "hermes":
        runtime_examples = "Hermes/OMH runtime skills and coding-team paths"
    return (
        "Runtime capability discovery:\n"
        "- Before acting, inspect runtime-local capabilities: runtime-native workflow templates, skills, "
        "worker lanes, subagents, MCP tools, repo scripts, tests, CI metadata, and project instructions.\n"
        f"- For {label}, examples include {runtime_examples} when actually available. "
        "These are examples, not proof of availability.\n"
        "- If a relevant runtime-local skill, workflow template, worker lane, subagent, or MCP tool materially "
        "improves planning, implementation, verification, review, or coordination, use that runtime-native "
        "capability before falling back to solo runtime execution.\n"
        f"- If no relevant local capability is available, continue with solo runtime execution as a plain {label} "
        "task using this task, harness, and evidence contract.\n"
        "- Do not claim OMH observed runtime capability availability, dispatch, implementation, review, CI, or merge.\n\n"
    )


def _codex_prompt_template(
    delegation: CodingDelegation,
    *,
    candidate_template: str | None,
    prompting_contract: dict[str, object],
) -> str:
    workflow_instruction = (
        "Observed executor-local workflow candidate: `{candidate_template}`.\n"
        "Ask before dispatching this candidate.\n"
    ).format(candidate_template=candidate_template) if candidate_template else (
        "Executor-local workflow invocation is not observed available.\n"
        "Keep the dispatched task text generic.\n"
    )
    return (
        "You are Codex, acting as the coding executor for a Hermes-orchestrated request.\n\n"
        "Executor target: codex\n"
        "{workflow_instruction}"
        "Recommended OMH workflow: `{workflow}`\n"
        "Recommended harness: `{harness}`\n"
        "Intent: `{intent}`\n"
        "Prepared status: `prepared_not_observed`\n\n"
        "{local_capability_prompt}"
        "{task_prompt_shape}"
        "Rules:\n"
        "- Implement only after inspecting the repository and confirming the scope.\n"
        "- Preserve unrelated behavior and user changes.\n"
        "- Run targeted verification and report exact evidence.\n"
        "- Do not say Hermes performed the implementation; Hermes prepared this handoff.\n\n"
        "Report local executor capabilities only with evidence refs.\n\n"
        "{prompt_sections}"
    ).format(
        workflow_instruction=workflow_instruction,
        workflow=delegation.recommended_workflow,
        harness=delegation.recommended_harness,
        intent=delegation.intent,
        local_capability_prompt=_local_capability_prompt_block("codex", "Codex"),
        task_prompt_shape=_task_prompt_shape_block(),
        prompt_sections=_executor_prompt_sections(delegation, prompting_contract),
    )


def _prompt_only_template(
    delegation: CodingDelegation,
    *,
    profile: str,
    label: str,
    prompting_contract: dict[str, object],
) -> str:
    return (
        "You are {label}, receiving a Hermes-orchestrated coding handoff.\n\n"
        "Executor profile: `{profile}`\n"
        "Recommended OMH workflow: `{workflow}`\n"
        "Recommended harness: `{harness}`\n"
        "Intent: `{intent}`\n"
        "Prepared status: `prepared_not_observed`\n\n"
        "{local_capability_prompt}"
        "{task_prompt_shape}"
        "Rules:\n"
        "- Treat this as a prompt prepared by Hermes/OMH, not as observed execution.\n"
        "- Inspect the repository or local context before claiming a code change.\n"
        "- Do not claim Hermes performed implementation, review, CI, or merge work.\n\n"
        "{prompt_sections}"
    ).format(
        label=label,
        profile=profile,
        workflow=delegation.recommended_workflow,
        harness=delegation.recommended_harness,
        intent=delegation.intent,
        local_capability_prompt=_local_capability_prompt_block(profile, label),
        task_prompt_shape=_task_prompt_shape_block(),
        prompt_sections=_executor_prompt_sections(delegation, prompting_contract),
    )


def _runtime_prompt_template(
    delegation: CodingDelegation,
    *,
    profile: str,
    label: str,
    prompting_contract: dict[str, object],
) -> str:
    return (
        "You are {label}, receiving a Hermes-orchestrated runtime handoff.\n\n"
        "Runtime profile: `{profile}`\n"
        "Recommended OMH workflow: `{workflow}`\n"
        "Recommended harness: `{harness}`\n"
        "Intent: `{intent}`\n"
        "Prepared status: `prepared_not_observed`\n\n"
        "{local_capability_prompt}"
        "{task_prompt_shape}"
        "Runtime rules:\n"
        "- Treat this as a runtime contract prepared by Hermes/OMH, not as observed execution.\n"
        "- Use solo execution unless lanes are independent; use team/swarm only with explicit lane ownership.\n"
        "- Use tmux-style workers, panes, or equivalent runtime lanes when parallel coding is selected.\n"
        "- Use a worktree or equivalent isolation before risky or parallel coding.\n"
        "- Workers must ACK, claim scope/files, report results, and escalate blockers to the leader.\n"
        "- Do not claim Hermes, OMH, or this runtime completed implementation, review, CI, or merge work without observed evidence.\n\n"
        "{prompt_sections}"
    ).format(
        label=label,
        profile=profile,
        workflow=delegation.recommended_workflow,
        harness=delegation.recommended_harness,
        intent=delegation.intent,
        local_capability_prompt=_runtime_local_capability_prompt_block(profile, label),
        task_prompt_shape=_task_prompt_shape_block(),
        prompt_sections=_executor_prompt_sections(delegation, prompting_contract),
    )


def _executor_prompt_sections(delegation: CodingDelegation, prompting_contract: dict[str, object]) -> str:
    return render_executor_prompt_sections(
        prompting_contract,
        recommended_workflow=delegation.recommended_workflow,
        recommended_harness=delegation.recommended_harness,
        acceptance_criteria=delegation.acceptance_criteria,
        verification=delegation.verification,
        review_required=delegation.review_required,
    )


def _delegation_prompt_template(action: str, intent: str, workflow: str, harness: str) -> str:
    if action == "fallback":
        return (
            "Use the `oh-my-hermes` router before coding delegation.\n\n"
            "Ask one concise clarification question for this task:\n{message}"
        )
    if action == "clarify":
        if workflow in _RETAINED_HERMES_WORKFLOWS:
            return (
                "Keep this {workflow_label} request in Hermes as a retained workflow.\n\n"
                "Candidate workflow: `{workflow}` / `{harness}`.\n\n"
                "Task:\n{message}"
            ).format(
                workflow_label=workflow.replace("-", " "),
                workflow=workflow,
                harness=harness,
                message="{message}",
            )
        return (
            "Clarify this {intent} request before executor/runtime dispatch.\n\n"
            "Candidate workflow: `{workflow}` / `{harness}`.\n\n"
            "Task:\n{message}"
        ).format(intent=intent, workflow=workflow, harness=harness, message="{message}")
    return (
        "Delegate this {intent} request to a {workflow} executor lane.\n\n"
        "Recommended workflow: `{workflow}`\n"
        "Recommended harness: `{harness}`\n"
        "Do not claim execution is observed unless wrapper/runtime evidence proves it.\n\n"
        "Task:\n{message}"
    ).format(intent=intent, workflow=workflow, harness=harness, message="{message}")


def _resolved_reasoning_demand(item: dict[str, object]) -> str:
    value = item.get("reasoning_demand")
    if value in {"light", "standard", "heavy"}:
        return str(value)
    skill = str(item.get("skill") or "")
    return next(
        (definition.reasoning_demand for definition in routable_definitions() if definition.name == skill),
        "standard",
    )


def _compact_recommendations(recommendations: object) -> list[dict[str, object]]:
    if not isinstance(recommendations, list):
        return []
    compact: list[dict[str, object]] = []
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        matched = item.get("matched", [])
        compact.append(
            {
                "skill": str(item.get("skill", "")),
                "score": int(item.get("score", 0)),
                "confidence": str(item.get("confidence", "low")),
                "matched": [str(value) for value in matched] if isinstance(matched, list) else [],
                "reasoning_demand": _resolved_reasoning_demand(item),
            }
        )
    return compact


def _prioritize_preferred_workflow(
    recommendations: list[dict[str, object]],
    *,
    preferred_workflow: str | None,
    preferred_workflow_score: int | None,
) -> list[dict[str, object]]:
    workflow = str(preferred_workflow or "").strip()
    if not is_workflow(workflow):
        return recommendations
    route_score = _int_or_none(preferred_workflow_score)
    prioritized: dict[str, object] | None = None
    rest: list[dict[str, object]] = []
    for item in recommendations:
        if str(item.get("skill", "")) == workflow and prioritized is None:
            prioritized = dict(item)
            if route_score is not None:
                prioritized["score"] = max(int(prioritized.get("score", 0)), route_score)
            matched = list(prioritized.get("matched", [])) if isinstance(prioritized.get("matched"), list) else []
            if "route:selected_workflow" not in matched:
                matched.insert(0, "route:selected_workflow")
            prioritized["matched"] = matched
            prioritized["confidence"] = "high"
        else:
            rest.append(item)
    if prioritized is None:
        prioritized = {
            "skill": workflow,
            "score": max(route_score or 0, 4),
            "confidence": "high",
            "matched": ["route:selected_workflow"],
        }
    return [prioritized] + [item for item in rest if str(item.get("skill", "")) != workflow]


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _has_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)

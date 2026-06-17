from __future__ import annotations

from dataclasses import dataclass


EXECUTOR_HANDOFF_SCHEMA_VERSION = "coding_executor_handoff/v1"
PROMPT_HANDOFF_SCHEMA_VERSION = "coding_prompt_handoff/v1"
RUNTIME_HANDOFF_SCHEMA_VERSION = "coding_runtime_handoff/v1"
HERMES_CODING_TEAM_PATH_SCHEMA_VERSION = "hermes_coding_team_path/v1"
HERMES_CODING_TEAM_START_MODE_IDS = ("solo", "durable_goal", "team", "swarm")
HERMES_CODING_TEAM_STATUS_LADDER = (
    "runtime_start",
    "worktree_creation",
    "worker_dispatch",
    "worker_result",
    "verification",
    "review",
    "ci",
    "merge_readiness",
    "merge",
)

WORK_OWNER_MODES = ("retained_hermes", "prompt_only_handoff", "runtime_handoff", "external_executor")
DISPATCH_POLICIES = ("prepare_only", "ask_before_dispatch", "configured_auto_dispatch_reserved")

EXECUTOR_PROFILES = ("codex", "claude-code", "omx-runtime", "omo-runtime", "omc-runtime", "generic", "hermes")
CODING_EXECUTOR_HANDOFF_TARGETS = ("codex",)
CODING_RUNTIME_HANDOFF_TARGETS = ("hermes", "omx-runtime", "omo-runtime", "omc-runtime")
CODING_EXECUTOR_TARGETS = ("choose", *EXECUTOR_PROFILES)
PROMPT_ONLY_EXECUTOR_PROFILES = ("claude-code", "generic")


RUNTIME_PROFILE_DETAILS = {
    "hermes": {
        "label": "Hermes coding skill runtime",
        "runtime_family": "omh",
        "underlying_agent": "Hermes Agent",
        "tool_label": "Hermes Agent",
        "invocation_mode": "hermes_skill",
        "dispatch_text_template": "Use the selected OMH coding skill for: {message}",
        "recommended_for": "Hermes-owned coding using OMH skills, team/swarm guidance, tmux-style workers, worker protocol, and worktree discipline",
        "templates": (
            {
                "label": "Hermes solo coding skill",
                "syntax": "Hermes skill",
                "command_template": "Use OMH ultrawork for: {message}",
                "when_to_use": "Use when the operator wants Hermes itself to own one bounded coding task with OMH guardrails.",
                "observed_event": "runtime_start",
            },
            {
                "label": "Hermes durable goal loop",
                "syntax": "Hermes skill",
                "command_template": "Use OMH ultragoal for: {message}",
                "when_to_use": "Use when Hermes should keep one ambitious coding goal durable across planning, implementation, review, and verification.",
                "observed_event": "runtime_start",
            },
            {
                "label": "Hermes coordinated team",
                "syntax": "Hermes skill",
                "command_template": "Use OMH team for: {message}",
                "when_to_use": "Use only when Hermes can split independent lanes and the wrapper can record worker dispatch/result evidence.",
                "observed_event": "worker_dispatch",
            },
            {
                "label": "Hermes review gate",
                "syntax": "Hermes skill",
                "command_template": "Use OMH code-review for: {message}",
                "when_to_use": "Use after implementation evidence exists and Hermes should frame or run a review workflow.",
                "observed_event": "review",
            },
        ),
    },
    "omx-runtime": {
        "label": "OMX runtime",
        "runtime_family": "omx",
        "underlying_agent": "Codex",
        "tool_label": "OMX",
        "invocation_mode": "oh_my_runtime",
        "dispatch_text_template": "Run the selected OMX coding workflow with this task:\n{message}",
        "recommended_for": "Codex-backed oh-my runtime workflows with skills, team/swarm workers, tmux-style coordination, and worktree-aware delivery",
        "templates": (
            {
                "label": "OMX durable goal",
                "syntax": "$skill",
                "command_template": "$ultragoal {message}",
                "when_to_use": "Use for one ambitious implementation goal that needs durable state, verification, review, and a PR.",
                "observed_event": "runtime_start",
            },
            {
                "label": "OMX parallel team",
                "syntax": "$skill",
                "command_template": "$team {message}",
                "when_to_use": "Use only when lanes are independent and worktree/file ownership can be made explicit.",
                "observed_event": "worker_dispatch",
            },
            {
                "label": "OMX throughput work",
                "syntax": "$skill",
                "command_template": "$ultrawork {message}",
                "when_to_use": "Use for a prepared implementation batch where parallel execution is justified.",
                "observed_event": "worker_dispatch",
            },
            {
                "label": "OMX review gate",
                "syntax": "$skill",
                "command_template": "$code-review {message}",
                "when_to_use": "Use after implementation evidence exists and review should be independently checked.",
                "observed_event": "review",
            },
        ),
    },
    "omo-runtime": {
        "label": "OMO runtime",
        "runtime_family": "omo",
        "underlying_agent": "OpenAgent",
        "tool_label": "OMO",
        "invocation_mode": "oh_my_runtime",
        "dispatch_text_template": "Run the selected OMO workflow with this task:\n{message}",
        "recommended_for": "OpenAgent-style runtime workflows when the operator has OMO installed",
        "templates": (
            {
                "label": "OMO goal handoff",
                "syntax": "$skill",
                "command_template": "$ultragoal {message}",
                "when_to_use": "Use when OpenAgent-backed runtime has an equivalent durable goal workflow.",
                "observed_event": "runtime_start",
            },
            {
                "label": "OMO team handoff",
                "syntax": "$skill",
                "command_template": "$team {message}",
                "when_to_use": "Use when the OMO runtime exposes independent worker lanes and evidence reporting.",
                "observed_event": "worker_dispatch",
            },
        ),
    },
    "omc-runtime": {
        "label": "OMC runtime",
        "runtime_family": "omc",
        "underlying_agent": "Claude Code",
        "tool_label": "OMC",
        "invocation_mode": "oh_my_runtime",
        "dispatch_text_template": "Run the selected OMC workflow with this task:\n{message}",
        "recommended_for": "Claude Code-backed oh-my runtime workflows when the operator has OMC installed",
        "templates": (
            {
                "label": "OMC durable goal",
                "syntax": "$skill",
                "command_template": "$ultragoal {message}",
                "when_to_use": "Use when Claude Code-backed runtime has an equivalent durable goal workflow.",
                "observed_event": "runtime_start",
            },
            {
                "label": "OMC review gate",
                "syntax": "$skill",
                "command_template": "$code-review {message}",
                "when_to_use": "Use after implementation evidence exists and review should be checked separately.",
                "observed_event": "review",
            },
        ),
    },
}


@dataclass(frozen=True)
class ExecutorSelection:
    work_owner_mode: str
    selected_executor_profile: str | None
    dispatch_policy: str
    dispatchable: bool
    status: str
    choice_required: bool = False


def executor_selection_for_target(executor_target: str, *, action: str) -> ExecutorSelection:
    if action != "delegate":
        return ExecutorSelection(
            work_owner_mode="retained_hermes",
            selected_executor_profile=None,
            dispatch_policy="prepare_only",
            dispatchable=False,
            status="retained_hermes",
        )
    if executor_target == "choose":
        return ExecutorSelection(
            work_owner_mode="external_executor",
            selected_executor_profile=None,
            dispatch_policy="ask_before_dispatch",
            dispatchable=False,
            status="executor_choice_required",
            choice_required=True,
        )
    if executor_target == "hermes":
        return ExecutorSelection(
            work_owner_mode="runtime_handoff",
            selected_executor_profile="hermes",
            dispatch_policy="prepare_only",
            dispatchable=False,
            status="runtime_handoff_prepared",
        )
    if executor_target == "codex":
        return ExecutorSelection(
            work_owner_mode="external_executor",
            selected_executor_profile="codex",
            dispatch_policy="ask_before_dispatch",
            dispatchable=True,
            status="handoff_prepared",
        )
    if executor_target in CODING_RUNTIME_HANDOFF_TARGETS:
        return ExecutorSelection(
            work_owner_mode="runtime_handoff",
            selected_executor_profile=executor_target,
            dispatch_policy="prepare_only",
            dispatchable=False,
            status="runtime_handoff_prepared",
        )
    if executor_target in PROMPT_ONLY_EXECUTOR_PROFILES:
        return ExecutorSelection(
            work_owner_mode="prompt_only_handoff",
            selected_executor_profile=executor_target,
            dispatch_policy="prepare_only",
            dispatchable=False,
            status="prompt_handoff_prepared",
        )
    raise ValueError(f"unsupported coding delegate executor: {executor_target}")


def public_executor_options() -> list[dict[str, object]]:
    return [
        {
            "profile": "codex",
            "label": "Codex",
            "work_owner_mode": "external_executor",
            "dispatchable": True,
            "recommended_for": "run-backed coding lifecycle with observed dispatch/result/review evidence",
        },
        {
            "profile": "claude-code",
            "label": "Claude Code",
            "work_owner_mode": "prompt_only_handoff",
            "dispatchable": False,
            "recommended_for": "copyable coding-agent prompt handoff when direct dispatch is not configured",
        },
        {
            "profile": "omx-runtime",
            "label": "OMX runtime",
            "work_owner_mode": "runtime_handoff",
            "dispatchable": False,
            "recommended_for": RUNTIME_PROFILE_DETAILS["omx-runtime"]["recommended_for"],
        },
        {
            "profile": "omo-runtime",
            "label": "OMO runtime",
            "work_owner_mode": "runtime_handoff",
            "dispatchable": False,
            "recommended_for": RUNTIME_PROFILE_DETAILS["omo-runtime"]["recommended_for"],
        },
        {
            "profile": "omc-runtime",
            "label": "OMC runtime",
            "work_owner_mode": "runtime_handoff",
            "dispatchable": False,
            "recommended_for": RUNTIME_PROFILE_DETAILS["omc-runtime"]["recommended_for"],
        },
        {
            "profile": "generic",
            "label": "Generic coding agent",
            "work_owner_mode": "prompt_only_handoff",
            "dispatchable": False,
            "recommended_for": "portable prompt handoff for an executor OMH does not directly know",
        },
        {
            "profile": "hermes",
            "label": "Hermes coding skill runtime",
            "work_owner_mode": "runtime_handoff",
            "dispatchable": False,
            "recommended_for": RUNTIME_PROFILE_DETAILS["hermes"]["recommended_for"],
        },
    ]


def executor_label(profile: str | None) -> str:
    labels = {str(option["profile"]): str(option["label"]) for option in public_executor_options()}
    return labels.get(profile or "", "Unselected executor")


def prompt_invocation_for_profile(profile: str) -> dict[str, str]:
    labels = {
        "claude-code": "Claude Code",
        "omx-runtime": "OMX runtime",
        "omo-runtime": "OMO runtime",
        "omc-runtime": "OMC runtime",
        "generic": "generic coding agent",
    }
    templates = {
        "claude-code": "Paste into Claude Code:\n{message}",
        "omx-runtime": "Run the chosen OMX coding workflow with this task:\n{message}",
        "omo-runtime": "Run the chosen OMO workflow with this task:\n{message}",
        "omc-runtime": "Run the chosen OMC workflow with this task:\n{message}",
        "generic": "Give this task to your coding agent:\n{message}",
    }
    if profile not in PROMPT_ONLY_EXECUTOR_PROFILES:
        raise ValueError(f"unsupported prompt-only executor profile: {profile}")
    return {
        "mode": "copy_prompt",
        "tool_label": labels[profile],
        "dispatch_text_template": templates[profile],
        "message_placeholder": "{message}",
        "wrapper_note": "Copy or pass this prompt only when the user chooses that executor; OMH does not dispatch it.",
    }


def runtime_invocation_for_profile(profile: str) -> dict[str, str]:
    if profile not in CODING_RUNTIME_HANDOFF_TARGETS:
        raise ValueError(f"unsupported runtime executor profile: {profile}")
    details = RUNTIME_PROFILE_DETAILS[profile]
    return {
        "mode": str(details["invocation_mode"]),
        "tool_label": str(details["tool_label"]),
        "dispatch_text_template": str(details["dispatch_text_template"]),
        "message_placeholder": "{message}",
        "wrapper_note": (
            "Start this runtime only after the user or wrapper chooses it; OMH records the prepared runtime contract, "
            "not execution evidence."
        ),
    }


def runtime_profile_contract(profile: str) -> dict[str, object]:
    if profile not in CODING_RUNTIME_HANDOFF_TARGETS:
        raise ValueError(f"unsupported runtime executor profile: {profile}")
    details = RUNTIME_PROFILE_DETAILS[profile]
    return {
        "profile": profile,
        "label": str(details["label"]),
        "runtime_family": str(details["runtime_family"]),
        "underlying_agent": str(details["underlying_agent"]),
        "supports_team_swarm": True,
        "supports_tmux_workers": True,
        "supports_worker_protocol": True,
        "supports_worktree_guidance": True,
        "supports_hermes_coding_team_path": profile == "hermes",
        "requires_operator_runtime": profile != "hermes",
    }


def runtime_templates_for_profile(profile: str) -> list[dict[str, str]]:
    if profile not in CODING_RUNTIME_HANDOFF_TARGETS:
        raise ValueError(f"unsupported runtime executor profile: {profile}")
    templates = RUNTIME_PROFILE_DETAILS[profile].get("templates", ())
    return [{key: str(value) for key, value in template.items()} for template in templates]


def hermes_coding_team_path_contract(profile: str) -> dict[str, object]:
    if profile != "hermes":
        return {}
    return {
        "schema_version": HERMES_CODING_TEAM_PATH_SCHEMA_VERSION,
        "profile": "hermes",
        "status": "prepared_not_observed",
        "purpose": (
            "Let Hermes own coding through selected OMH coding skills, solo/team/swarm guidance, "
            "and observed runtime ledger events without pretending a separate executor ran."
        ),
        "start_modes": [
            {
                "id": "solo",
                "label": "Hermes solo coding",
                "use_when": "One bounded coding lane is enough and shared-file coordination is unnecessary.",
                "entrypoint": "Use OMH ultrawork for: {message}",
                "first_observed_event": "runtime_start",
            },
            {
                "id": "durable_goal",
                "label": "Hermes durable goal",
                "use_when": "The task needs a durable plan, implementation pass, review, verification, and PR-level report.",
                "entrypoint": "Use OMH ultragoal for: {message}",
                "first_observed_event": "runtime_start",
            },
            {
                "id": "team",
                "label": "Hermes coding team",
                "use_when": "Independent lanes can be assigned with explicit ownership and integration by one leader.",
                "entrypoint": "Use OMH team for: {message}",
                "first_observed_event": "worker_dispatch",
            },
            {
                "id": "swarm",
                "label": "Hermes swarm batch",
                "use_when": "A prepared batch has many independent lanes and a clear verification integrator.",
                "entrypoint": "Use OMH ultrawork for: {message}",
                "first_observed_event": "worker_dispatch",
            },
        ],
        "leader_contract": [
            "Keep chat intake, clarification, scope split, and status narration in Hermes.",
            "Assign one owner per lane and one verifier/integrator before any parallel work starts.",
            "Require worker ACK, file/worktree ownership, result summary, and verification refs for each lane.",
            "Report blockers instead of upgrading missing runtime events into evidence.",
        ],
        "worker_contract": [
            "ACK the assigned lane before work starts.",
            "Claim files or a worktree before editing shared repository state.",
            "Report changed files, tests, blockers, and evidence references back to the Hermes leader.",
            "Escalate scope expansion, shared-file conflicts, or unclear verification ownership.",
        ],
        "status_ladder": list(HERMES_CODING_TEAM_STATUS_LADDER),
        "wrapper_actions": [
            "show_coding_team_path",
            "start_hermes_coding",
            "prepare_worktree",
            "start_team",
            "start_swarm",
            "record_runtime_observation",
            "show_status",
        ],
        "not_observed_by_omh": [
            "Hermes skill start",
            "team or swarm worker launch",
            "tmux pane creation",
            "worktree creation",
            "code edits",
            "verification",
            "review",
            "CI",
            "merge readiness",
            "merge",
        ],
        "claim_boundary": (
            "This is an optional Hermes coding path contract. It becomes runtime evidence only after a wrapper "
            "or operator records matching runtime_observation/v1 events."
        ),
    }

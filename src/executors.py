from __future__ import annotations

from dataclasses import dataclass


EXECUTOR_HANDOFF_SCHEMA_VERSION = "coding_executor_handoff/v1"
PROMPT_HANDOFF_SCHEMA_VERSION = "coding_prompt_handoff/v1"
RUNTIME_HANDOFF_SCHEMA_VERSION = "coding_runtime_handoff/v1"

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
    },
    "omx-runtime": {
        "label": "OMX runtime",
        "runtime_family": "omx",
        "underlying_agent": "Codex",
        "tool_label": "OMX",
        "invocation_mode": "oh_my_runtime",
        "dispatch_text_template": "Run the selected OMX coding workflow with this task:\n{message}",
        "recommended_for": "Codex-backed oh-my runtime workflows with skills, team/swarm workers, tmux-style coordination, and worktree-aware delivery",
    },
    "omo-runtime": {
        "label": "OMO runtime",
        "runtime_family": "omo",
        "underlying_agent": "OpenAgent",
        "tool_label": "OMO",
        "invocation_mode": "oh_my_runtime",
        "dispatch_text_template": "Run the selected OMO workflow with this task:\n{message}",
        "recommended_for": "OpenAgent-style runtime workflows when the operator has OMO installed",
    },
    "omc-runtime": {
        "label": "OMC runtime",
        "runtime_family": "omc",
        "underlying_agent": "Claude Code",
        "tool_label": "OMC",
        "invocation_mode": "oh_my_runtime",
        "dispatch_text_template": "Run the selected OMC workflow with this task:\n{message}",
        "recommended_for": "Claude Code-backed oh-my runtime workflows when the operator has OMC installed",
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
        "requires_operator_runtime": profile != "hermes",
    }

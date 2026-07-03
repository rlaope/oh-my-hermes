from __future__ import annotations


from ..executors import (
    CODING_EXECUTOR_HANDOFF_TARGETS,
    CODING_RUNTIME_HANDOFF_TARGETS,
    CODING_EXECUTOR_TARGETS,
    EXECUTOR_HANDOFF_SCHEMA_VERSION,
    PROMPT_HANDOFF_SCHEMA_VERSION,
    RUNTIME_HANDOFF_SCHEMA_VERSION,
)

TASK_PROMPT_CONTRACT_SCHEMA_VERSION = "executor_task_prompt_contract/v1"
TASK_PROMPT_REQUIRED_SECTIONS = ("Goal", "Do", "Don't", "Expected result", "Test")
CODEX_SESSION_OBSERVATION_CONTRACT_SCHEMA_VERSION = "codex_session_observation_contract/v1"
CLAUDE_CODE_SESSION_OBSERVATION_CONTRACT_SCHEMA_VERSION = "claude_code_session_observation_contract/v1"
LOCAL_CAPABILITY_REPORT_CONTRACT_SCHEMA_VERSION = "executor_local_capability_report_contract/v1"
LOCAL_CAPABILITY_REPORT_REQUIRED_FIELDS = (
    "local_capabilities_used",
    "local_capability_evidence_refs",
    "local_capability_fallback_reason",
)
LOCAL_CAPABILITY_REPORT_CAPABILITY_FIELDS = ("name", "kind", "source", "purpose", "evidence_ref")
LOCAL_CAPABILITY_REPORT_ALLOWED_KINDS = (
    "skill",
    "workflow",
    "slash_command",
    "subagent",
    "agent",
    "mcp_tool",
    "repo_script",
    "test_harness",
    "ci_metadata",
    "runtime_template",
    "worker_lane",
    "worktree",
)


__all__ = [
    "CODING_EXECUTOR_HANDOFF_TARGETS",
    "CODING_RUNTIME_HANDOFF_TARGETS",
    "CODING_EXECUTOR_TARGETS",
    "EXECUTOR_HANDOFF_SCHEMA_VERSION",
    "PROMPT_HANDOFF_SCHEMA_VERSION",
    "RUNTIME_HANDOFF_SCHEMA_VERSION",
    "TASK_PROMPT_CONTRACT_SCHEMA_VERSION",
    "TASK_PROMPT_REQUIRED_SECTIONS",
    "CODEX_SESSION_OBSERVATION_CONTRACT_SCHEMA_VERSION",
    "CLAUDE_CODE_SESSION_OBSERVATION_CONTRACT_SCHEMA_VERSION",
    "LOCAL_CAPABILITY_REPORT_CONTRACT_SCHEMA_VERSION",
    "LOCAL_CAPABILITY_REPORT_REQUIRED_FIELDS",
    "LOCAL_CAPABILITY_REPORT_CAPABILITY_FIELDS",
    "LOCAL_CAPABILITY_REPORT_ALLOWED_KINDS",
]

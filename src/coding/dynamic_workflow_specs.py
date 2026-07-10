from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Sequence

from .dynamic_workflow_contracts import PREPARED_NOT_OBSERVED

DEFAULT_PLANNERS: Final[tuple[str, ...]] = ("planning-model-pool:auto:Planning model pool:adaptive:model",)
DEFAULT_CRITICS: Final[tuple[str, ...]] = ("critique-model-pool:auto:Critique model pool:adaptive:model",)
DEFAULT_IMPLEMENTERS: Final[tuple[str, ...]] = (
    "implementation-model-pool:auto:Implementation model pool:adaptive:model",
    "executor-runtime-pool:auto:Executor runtime pool:runtime-variable:runtime",
)
DEFAULT_REVIEWERS: Final[tuple[str, ...]] = (
    "review-model-pool:auto:Review model pool:adaptive:model",
    "review-runtime-pool:auto:Review runtime pool:runtime-variable:runtime",
)
DEFAULT_REPORTER: Final[str] = "hermes:omh:Hermes/OMH report:wrapper:wrapper"
SUPPORTED_TARGET_TYPES: Final[tuple[str, ...]] = ("model", "runtime", "wrapper", "tool", "agent")
_COST_TIERS: Final[dict[str, str]] = {
    "planning-model-pool": "adaptive",
    "critique-model-pool": "adaptive",
    "implementation-model-pool": "adaptive",
    "executor-runtime-pool": "runtime-variable",
    "review-model-pool": "adaptive",
    "review-runtime-pool": "runtime-variable",
    "gpt": "operator-selected",
    "claude-code": "operator-selected",
    "glm": "medium",
    "codex": "operator-selected",
    "pi": "low",
    "omp-runtime": "runtime-variable",
    "omx-runtime": "runtime-variable",
    "hermes": "wrapper",
}
_TARGET_TYPES: Final[dict[str, str]] = {
    "planning-model-pool": "model",
    "critique-model-pool": "model",
    "implementation-model-pool": "model",
    "review-model-pool": "model",
    "model-router": "model",
    "gpt": "model",
    "glm": "model",
    "claude": "model",
    "openai": "model",
    "anthropic": "model",
    "gemini": "model",
    "qwen": "model",
    "kimi": "model",
    "mistral": "model",
    "executor-runtime-pool": "runtime",
    "review-runtime-pool": "runtime",
    "codex": "runtime",
    "claude-code": "runtime",
    "pi": "runtime",
    "omp-runtime": "runtime",
    "omx-runtime": "runtime",
    "generic-runtime": "runtime",
    "hermes": "wrapper",
}
_MODEL_TARGET_PREFIXES: Final[tuple[str, ...]] = (
    "gpt-",
    "glm-",
    "claude-",
    "openai-",
    "anthropic-",
    "gemini-",
    "qwen-",
    "kimi-",
    "mistral-",
    "llama-",
    "deepseek-",
    "codestral-",
)
_RUNTIME_TARGET_SUFFIXES: Final[tuple[str, ...]] = ("-runtime", "-executor")
_TOOL_TARGET_SUFFIXES: Final[tuple[str, ...]] = ("-tool", "-mcp")
_AGENT_TARGET_SUFFIXES: Final[tuple[str, ...]] = ("-agent", "-tool-agent")


@dataclass(frozen=True, slots=True)
class AgentSpec:
    target: str
    model: str
    label: str
    cost_tier: str
    target_type: str

    def stage(self, *, stage_id: str, lane: str, role: str, gate: str, order: int) -> dict[str, object]:
        return {
            "id": stage_id,
            "lane": lane,
            "role": role,
            "agent": self.label,
            "target": self.target,
            "target_type": self.target_type,
            "runtime": self.target if self.target_type == "runtime" else "",
            "model": self.model,
            "cost_tier": self.cost_tier,
            "gate": gate,
            "status": PREPARED_NOT_OBSERVED,
            "order": order,
        }


def agent_specs(values: Sequence[str] | None, *, default_specs: Sequence[str]) -> list[AgentSpec]:
    specs = tuple(values) if values else tuple(default_specs)
    return [parse_agent_spec(spec) for spec in specs]


def parse_agent_spec(raw: str) -> AgentSpec:
    parts = [part.strip() for part in raw.split(":", 4)]
    target = parts[0] if parts else ""
    if not target:
        raise ValueError("agent spec requires target in target[:model[:label[:cost_tier[:target_type]]]] form")
    model = parts[1] if len(parts) > 1 and parts[1] else "auto"
    label = parts[2] if len(parts) > 2 and parts[2] else _label_for_target(target)
    cost_tier = parts[3] if len(parts) > 3 and parts[3] else _cost_tier(target)
    target_type = _target_type(target, parts[4] if len(parts) > 4 else "")
    return AgentSpec(target=target, model=model, label=label, cost_tier=cost_tier, target_type=target_type)


def _target_type(target: str, explicit: str) -> str:
    target_type = explicit or _inferred_target_type(target)
    if target_type not in SUPPORTED_TARGET_TYPES:
        supported = ", ".join(SUPPORTED_TARGET_TYPES)
        raise ValueError(f"target_type must be one of: {supported}")
    return target_type


def _inferred_target_type(target: str) -> str:
    normalized = target.lower()
    if normalized in _TARGET_TYPES:
        return _TARGET_TYPES[normalized]
    if normalized.startswith(_MODEL_TARGET_PREFIXES):
        return "model"
    if normalized.endswith(_RUNTIME_TARGET_SUFFIXES):
        return "runtime"
    if normalized.endswith(_TOOL_TARGET_SUFFIXES):
        return "tool"
    if normalized.endswith(_AGENT_TARGET_SUFFIXES):
        return "agent"
    return "agent"


def _cost_tier(target: str) -> str:
    normalized = target.lower()
    if normalized in _COST_TIERS:
        return _COST_TIERS[normalized]
    if normalized.startswith("glm-"):
        return "medium"
    if normalized.startswith(_MODEL_TARGET_PREFIXES):
        return "operator-selected"
    if normalized.endswith(_RUNTIME_TARGET_SUFFIXES):
        return "runtime-variable"
    return "unknown"


def _label_for_target(target: str) -> str:
    return target.replace("-", " ").title()

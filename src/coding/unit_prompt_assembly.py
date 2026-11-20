"""The fanout unit prompt, assembled once as named blocks.

`assemble_unit_prompt` is the one answer to "what exact text does this unit
receive on this path". Every path that sends a unit prompt calls it: live
dispatch (including its repair and parent-decision redispatches and the fresh
sidecar path of a retry), the Hermes recovery lane, and both benchmark lanes.
Nothing edits the text after it returns; a variant is an argument, never a
string mutation.

The prompt is a tuple of `PromptBlock`s in four zones, in this order:

- `shared_head`: the byte-identical head every sibling unit of one fanout
  shares, so provider prefix caches serve every unit after the first. Its
  order and text come from `unit_prompt_protocol.shared_unit_preamble_lines`.
- `unit`: what varies per unit: title, scope, branch, input budget, criteria,
  role and calibration blocks, domain bundle, and skill sequence.
- `tail`: the dispatch-bound sidecar contract and the commit instruction.
- `append`: what a redispatch adds after the unchanged prompt (a repair
  brief or a parent decision), so the goal, scope, and criteria the executor
  reads are the ones it was first given.

`AssembledPrompt.text` joins every block with one newline and is the only
join. Block names are a closed vocabulary (`BLOCK_NAMES`); the calibration
block carries the table key that answered in brackets, e.g.
`unit.calibration[gpt-6.1-sol]`, because two keys can hold byte-equal text.

Pure data and pure functions: no IO, no clock, no environment.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
import hashlib
from typing import Any, Final, Literal, Mapping

from . import unit_prompt_protocol as _protocol
from .fanout_clarification_dispatch import parent_decision_prompt
from .fanout_clarification_records import ClarificationRecord
from .fanout_repair import repair_brief_prompt
from .fanout_unit_results import (
    FANOUT_UNIT_RESULT_CHECK_STATUSES,
    FANOUT_UNIT_RESULT_DECLINE_REASONS,
    FANOUT_UNIT_RESULT_PROCESS_STATUSES,
)

Zone = Literal["shared_head", "unit", "tail", "append"]

BLOCK_NAMES: Final[frozenset[str]] = frozenset({
    "head.goal",
    "head.goal_echo",
    "head.verification_stop",
    "head.failure_kind",
    "head.unit_result_return",
    "head.parent_clarification",
    "head.structural_search_discipline",
    "unit.title",
    "unit.scope",
    "unit.do_not_touch",
    "unit.branch",
    "unit.input_budget",
    "unit.criteria",
    "unit.commit_criterion",
    "unit.review_focus",
    "unit.tool_batching",
    "unit.shared_machine",
    "unit.review_role",
    "unit.calibration",
    "unit.domain_bundle",
    "unit.skills",
    "tail.unit_result_contract",
    "tail.commit",
    "append.repair",
    "append.parent_decision",
})

# The Hermes recovery child has file tools and nothing else, so it can neither
# run a verification pass nor commit; the dispatcher does both once it returns.
# These are the blocks that would ask the child to, and the two that ask for a
# `fanout_unit_result/v1` record naming a commit it cannot make, which that
# lane does not collect anyway.
EDIT_ONLY_OMITTED_BLOCKS: Final[frozenset[str]] = frozenset({
    "head.verification_stop",
    "head.unit_result_return",
    "head.parent_clarification",
    "unit.commit_criterion",
    "tail.commit",
})


@dataclass(frozen=True)
class PromptBlock:
    name: str
    zone: Zone
    text: str

    @property
    def base_name(self) -> str:
        """The vocabulary name, without the calibration key suffix."""
        return self.name.split("[", 1)[0]


@dataclass(frozen=True)
class AssembledPrompt:
    blocks: tuple[PromptBlock, ...]

    @cached_property
    def text(self) -> str:
        return "\n".join(block.text for block in self.blocks)

    @property
    def size_bytes(self) -> int:
        return len(self.text.encode("utf-8"))

    def digest(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    def names(self) -> tuple[str, ...]:
        return tuple(block.name for block in self.blocks)


def assemble_unit_prompt(
    unit: Mapping[str, Any],
    goal_text: str,
    *,
    route: Mapping[str, Any] | None,
    binding: Mapping[str, Any] | None = None,
    discovery: Mapping[str, Any] | None = None,
    repair: Mapping[str, Any] | None = None,
    parent_decision: ClarificationRecord | None = None,
    omit: frozenset[str] = frozenset(),
) -> AssembledPrompt:
    """Assemble the prompt one unit receives.

    `route` selects the high-effort calibration; dispatch passes the unit's
    recorded route. `binding` is the dispatch-bound sidecar contract
    (`path`, `unit_id`, `run_id`, `fanout_id`, `base_sha`); without it the
    prompt carries no sidecar contract, which is the Hermes recovery variant.
    `repair` is the `_dispatch_unit` repair mapping (`attempt`,
    `max_repair_attempts`, `failing_checks`). `omit` drops blocks by
    vocabulary name, for the benchmark lanes and for the Hermes recovery
    variant (`EDIT_ONLY_OMITTED_BLOCKS`); an unknown name
    raises so a typo cannot silently send the full prompt, and so does
    omitting `head.failure_kind` from a prompt with a `binding`, because the
    sidecar contract leaves the `process_declined` definition to that block.
    """
    unknown = sorted(set(omit) - BLOCK_NAMES)
    if unknown:
        raise ValueError(f"unknown unit prompt blocks: {', '.join(unknown)}")
    if binding is not None and "head.failure_kind" in omit:
        raise ValueError("a prompt with the sidecar contract must carry head.failure_kind")
    blocks = [
        *_shared_head_blocks(goal_text),
        *_unit_blocks(unit, route, discovery),
        *_tail_blocks(binding),
    ]
    if repair is not None:
        blocks.append(_append_block("append.repair", repair_brief_prompt(
            attempt=int(repair["attempt"]),
            max_repair_attempts=int(repair["max_repair_attempts"]),
            failing_checks=list(repair["failing_checks"]),
        )))
    if parent_decision is not None:
        blocks.append(_append_block("append.parent_decision", parent_decision_prompt(parent_decision)))
    return AssembledPrompt(tuple(block for block in blocks if block.base_name not in omit))


def recorded_model_route(unit: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The model route frozen in the unit's handoff, or None when it has none."""
    handoff = unit.get("handoff", {}) if isinstance(unit.get("handoff"), Mapping) else {}
    route = handoff.get("model_route")
    return route if isinstance(route, Mapping) else None


def unit_role(unit: Mapping[str, Any]) -> str:
    """The role skill discovery and review budgeting read for one unit."""
    handoff = unit.get("handoff", {}) if isinstance(unit.get("handoff"), Mapping) else {}
    review_role = str(handoff.get("review_role", "") or "")
    if review_role:
        return review_role
    route = recorded_model_route(unit)
    return str(route.get("role", "") or "") if route is not None else ""


_HEAD_BLOCK_NAMES: Final[dict[str, str]] = {
    _protocol.GOAL_ECHO_PROTOCOL: "head.goal_echo",
    _protocol.VERIFICATION_STOP_PROTOCOL: "head.verification_stop",
    _protocol.FAILURE_KIND_PROTOCOL: "head.failure_kind",
    _protocol.STRUCTURAL_SEARCH_DISCIPLINE_GUIDANCE: "head.structural_search_discipline",
}


def _shared_head_blocks(goal_text: str) -> list[PromptBlock]:
    """Name each line of the protocol's shared head, in its order.

    The return line is two blocks, its sentence and the parent-clarification
    block it ends with, so a lane can drop the clarification alone. A head
    line this table cannot name raises: a new head block is named here before
    any lane can omit it or any test can claim to see it.
    """
    clarification = _protocol.PARENT_CLARIFICATION_PROTOCOL
    return_sentence = _protocol.UNIT_RESULT_RETURN_PROTOCOL.removesuffix("\n" + clarification)
    if return_sentence == _protocol.UNIT_RESULT_RETURN_PROTOCOL:
        raise ValueError("UNIT_RESULT_RETURN_PROTOCOL no longer ends with PARENT_CLARIFICATION_PROTOCOL")
    blocks: list[PromptBlock] = []
    for index, line in enumerate(_protocol.shared_unit_preamble_lines(goal_text)):
        if index == 0 and line.startswith("Overall goal: "):
            blocks.append(PromptBlock("head.goal", "shared_head", line))
        elif line == _protocol.UNIT_RESULT_RETURN_PROTOCOL:
            blocks.append(PromptBlock("head.unit_result_return", "shared_head", return_sentence))
            blocks.append(PromptBlock("head.parent_clarification", "shared_head", clarification))
        elif line in _HEAD_BLOCK_NAMES:
            blocks.append(PromptBlock(_HEAD_BLOCK_NAMES[line], "shared_head", line))
        else:
            raise ValueError(f"unnamed shared unit head line {index}; name it in _HEAD_BLOCK_NAMES")
    return blocks


def _unit_blocks(
    unit: Mapping[str, Any],
    route: Mapping[str, Any] | None,
    discovery: Mapping[str, Any] | None,
) -> list[PromptBlock]:
    boundary = unit.get("boundary", {}) if isinstance(unit.get("boundary"), Mapping) else {}
    file_scope = ", ".join(str(path) for path in boundary.get("file_scope", []))
    do_not_touch = ", ".join(str(path) for path in boundary.get("do_not_touch", []))
    blocks = [
        PromptBlock("unit.title", "unit", f"Work unit: {unit.get('title', unit.get('unit_id'))}"),
        PromptBlock("unit.scope", "unit", f"Stay strictly inside these paths: {file_scope}."),
    ]
    if do_not_touch:
        blocks.append(PromptBlock("unit.do_not_touch", "unit", f"Do not touch: {do_not_touch} (owned by sibling units)."))
    blocks.append(PromptBlock("unit.branch", "unit", f"Work on branch {unit.get('branch_suggestion', '')} in the current worktree."))
    # A declared input budget states the ranges and the ceiling; an absent one
    # adds no block, the same additive rule every other declared field follows.
    budget = _input_budget_lines(unit)
    if budget:
        blocks.append(PromptBlock("unit.input_budget", "unit", "\n".join(budget)))
    blocks.extend(_protocol_blocks(unit, route))
    skills = _skill_lines(unit, discovery)
    if skills:
        blocks.append(PromptBlock("unit.skills", "unit", "\n".join(skills)))
    return blocks


def _protocol_blocks(unit: Mapping[str, Any], route: Mapping[str, Any] | None) -> list[PromptBlock]:
    """Criteria, review focus, tool batching, shared-machine etiquette, role protocol, calibration, and domain bundle.

    `TOOL_BATCHING_PROTOCOL` and `SHARED_MACHINE_PROTOCOL` are unit-invariant
    but ride here because the frozen head cannot afford them (see the note at
    `TOOL_BATCHING_PROTOCOL`).
    """
    criteria = list(_protocol.completion_criteria_for_unit(unit))
    numbered = [f"{index}. {criterion}" for index, criterion in enumerate(criteria, start=1)]
    commit = None
    if criteria and criteria[-1] == _protocol.UNIT_BRANCH_COMMIT_CRITERION:
        commit = numbered.pop()
    blocks = [PromptBlock("unit.criteria", "unit", "\n".join(["Done means, and only means:", *numbered]))]
    if commit is not None:
        blocks.append(PromptBlock("unit.commit_criterion", "unit", commit))
    # A declared review focus says what the reviewer will check; an absent one
    # adds no block, so the prompt stays byte-identical to one without it.
    review_focus = str(unit.get("review_focus", "") or "")
    if review_focus:
        blocks.append(PromptBlock("unit.review_focus", "unit", f"Review focus (what the reviewer will check): {review_focus}"))
    recorded = recorded_model_route(unit)
    # Contract units carry the declared role inside the recorded route, not as
    # a top-level key; accept both so pre-contract unit dicts behave the same.
    role = str(unit.get("role", "") or "") or (str(recorded.get("role", "") or "") if recorded else "")
    blocks.append(PromptBlock("unit.tool_batching", "unit", _protocol.TOOL_BATCHING_PROTOCOL))
    blocks.append(PromptBlock("unit.shared_machine", "unit", _protocol.SHARED_MACHINE_PROTOCOL))
    if role == "review":
        blocks.append(PromptBlock("unit.review_role", "unit", _protocol.REVIEW_ROLE_PROTOCOL))
    calibration = _protocol.calibration_entry_for_route(route)
    if calibration is not None:
        key, text = calibration
        blocks.append(PromptBlock(f"unit.calibration[{key}]", "unit", text))
    bundle = _protocol.domain_skill_guidance_line(unit)
    if bundle:
        blocks.append(PromptBlock("unit.domain_bundle", "unit", bundle))
    return blocks


def _tail_blocks(binding: Mapping[str, Any] | None) -> list[PromptBlock]:
    blocks = []
    if binding is not None:
        blocks.append(PromptBlock("tail.unit_result_contract", "tail", "\n".join(_unit_result_lines(binding))))
    blocks.append(PromptBlock("tail.commit", "tail", "Commit your work; do not merge or push other branches."))
    return blocks


def _append_block(name: str, section: str) -> PromptBlock:
    # Each redispatch section opens with the newline that separates it from
    # the prompt before it; the one join supplies that newline instead.
    if not section.startswith("\n"):
        raise ValueError(f"{name} section must open with a newline")
    return PromptBlock(name, "append", section[1:])


def _input_budget_lines(unit: Mapping[str, Any]) -> list[str]:
    budget = unit.get("input_budget")
    if not isinstance(budget, Mapping):
        return []
    chars = int(budget.get("chars", 0) or 0)
    tokens = budget.get("tokens")
    head = f"Input budget for this unit: at most {chars} characters"
    if isinstance(tokens, int) and not isinstance(tokens, bool):
        head += f" (about {tokens} tokens)"
    lines = [head + " of source text; do not read past it."]
    ranges = budget.get("source_ranges")
    if isinstance(ranges, list) and ranges:
        lines.append("Read only these source ranges:")
        for position, item in enumerate(ranges, start=1):
            if not isinstance(item, Mapping):
                continue
            text = f"{position}. {item.get('source', '')} — {item.get('span', '')}"
            if isinstance(item.get("offset"), int) and isinstance(item.get("limit"), int):
                text += f": read_file offset={item['offset']} limit={item['limit']}"
                if isinstance(item.get("end_line"), int):
                    text += f", continue via next_offset to line {item['end_line']}"
            if isinstance(item.get("estimated_chars"), int):
                text += f" (about {item['estimated_chars']} chars)"
            lines.append(text)
    return lines


def _unit_result_lines(contract: Mapping[str, Any]) -> list[str]:
    """Executor-neutral, typed sidecar contract for a live unit prompt.

    The closed enums are spelled out with their exact literals — imported from
    the validator's own tuples so prompt and validation can never drift. The
    validator deliberately never infers or aliases (a "success" it normalized
    into "process_succeeded" would launder an executor claim), so this prompt
    is the ONLY channel that tells a foreign executor which values validate;
    omitting them produced real `unit_result_invalid` outcomes on work that
    had succeeded (#1190).
    """
    process_values = " or ".join(f'"{value}"' for value in FANOUT_UNIT_RESULT_PROCESS_STATUSES)
    decline_values = ", ".join(f'"{value}"' for value in FANOUT_UNIT_RESULT_DECLINE_REASONS)
    check_values = ", ".join(f'"{value}"' for value in FANOUT_UNIT_RESULT_CHECK_STATUSES)
    return [
        "Before exiting, write one fanout_unit_result/v1 JSON sidecar to exactly "
        f"{contract.get('path', '')}.",
        "Top-level fields: schema_version, unit_id, run_id, fanout_id, base_sha, head_sha, "
        "process_status, decline_reason, changed_paths, checks, findings, schema_error (optional).",
        "Use these dispatch-bound values: "
        f"schema_version=fanout_unit_result/v1, unit_id={contract.get('unit_id', '')}, "
        f"run_id={contract.get('run_id', '')}, fanout_id={contract.get('fanout_id', '')}, "
        f"base_sha={contract.get('base_sha', '')}; head_sha is the git HEAD you leave behind.",
        f"process_status must be exactly {process_values} — no other value validates.",
        # When to decline, and that a decline is not process_failed, is
        # head.failure_kind's sentence; every prompt with this contract
        # carries the head, so only the literals and the pairing live here.
        "process_declined is never a retry candidate. When you report process_declined, "
        f"decline_reason is required and must be exactly {decline_values} — omit decline_reason for "
        "every other process_status.",
        "Each checks row fields: command, status, evidence_ref, reported_by, observed_by, "
        "observation_source.",
        f"Each checks row status must be exactly one of {check_values} — no other value validates.",
        "For every executor-authored checks row, set reported_by=executor. observed_by and "
        "observation_source are dispatcher-owned; leave both null. Sidecar validation records "
        "only a report and never verification.",
    ]


# The one hedge every emitted sequence carries: declared-on-disk is not loaded,
# and a step the work does not need is droppable.
_SKILL_SEQUENCE_PREAMBLE = (
    "Suggested skill sequence for this unit, from what this environment declares. OMH read these "
    "definitions on disk; it did not load or verify them, so resolve each one in your own registry, "
    "skip any that does not resolve, and drop any step that does not fit the work:"
)
_DECLARED_SEQUENCE_PREAMBLE = (
    "Operator-declared skill sequence for this unit. Resolve each one in your own registry and skip "
    "any that does not resolve:"
)


def _skill_lines(unit: Mapping[str, Any], discovery: Mapping[str, Any] | None) -> list[str]:
    """Return the skill-sequence block for one unit, or an empty list.

    Precedence: an explicit `skill_sequence` on the unit always wins — a
    non-empty list renders verbatim (interview option 4), an empty list
    suppresses the block entirely (option 5, pure prompt). Otherwise the
    recommended sequence is arranged from discovery; and with no discovery or
    no matches the block is absent, so the modal operator — a fresh install
    with no executor skills — gets exactly the prompt they get today.
    """
    from .executor_skill_discovery import suggested_skill_sequence

    declared = unit.get("skill_sequence")
    if isinstance(declared, (list, tuple)):
        entries = [str(entry).strip() for entry in declared if str(entry).strip()]
        if not entries:
            return []
        steps = [f"{index}. `{entry}`" for index, entry in enumerate(entries, start=1)]
        return [_DECLARED_SEQUENCE_PREAMBLE, *steps]
    if not isinstance(discovery, Mapping):
        return []
    steps = [
        f"{index}. `{step['invocation']}` — {step['purpose']}"
        for index, step in enumerate(suggested_skill_sequence(discovery, unit_role(unit)), start=1)
    ]
    if not steps:
        return []
    return [_SKILL_SEQUENCE_PREAMBLE, *steps]


__all__ = [
    "AssembledPrompt",
    "BLOCK_NAMES",
    "PromptBlock",
    "assemble_unit_prompt",
    "recorded_model_route",
    "unit_role",
]

"""Budget the prompt text every executor reads, including the weakest one.

A fanout unit prompt is not dispatched to one model. It is dispatched to
whatever local CLI the operator has: a frontier model on one lane and a kimi,
glm, qwen, codestral, or solar variant on the next. The per-family calibration
blocks already vary by family. The **shared preamble** does not -- it is the
byte-identical head every sibling prompt carries, deliberately, so providers can
cache the prefix.

That makes the shared head the one block that must be written for the *smallest*
model that will read it. A frontier model tolerates a dense head; a weaker one
starts dropping rules once a prompt carries more of them than it can hold, and
the rule it drops is not the one you would have picked. Every rule added to the
shared head is therefore paid for by displacing a rule already there, on exactly
the lanes least able to afford it.

Two things are measured here, and only two, because only two are honest:

- **A constraint ceiling on the shared head and on each block.** The upstream
  doctrine puts a tiny pattern-completer's limit at roughly 3-5 constraints
  before rules start displacing each other. OMH's consumers are coding-agent
  CLIs rather than tiny models, so that figure is a target, not the threshold:
  the ceilings below are the *measured* current values, which freezes the head
  where it is. Growing it then requires saying which existing rule the new one
  displaces, which is the decision the doctrine actually asks for. A byte
  ceiling rides alongside, because `UNIT_PROMPT_MAX_BYTES` bounds the whole
  assembled prompt and so lets the shared head triple without tripping.
- **No labelled contrast examples.** A block containing `Bad:` or `Wrong:`
  followed by a sample gets the sample copied rather than avoided by weaker
  models, which is the opposite of the intent. There are none today; this keeps
  it that way.

Two rules from the same doctrine are deliberately NOT mechanized. "Positive
framing only" would condemn text whose negations are the payload -- "do not
re-verify" is the entire anti-inertia rule, and rewriting it positively would
lose it. And "delete rules the code already enforces deterministically" needs a
judgement about what the code enforces, which no regex has. Both belong in
`MODEL_OPTI.md` as authoring rules, and they are there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SMALL_MODEL_PROMPT_BUDGET_SCHEMA_VERSION = "omh_small_model_prompt_budget/v1"

# Measured ceilings, not aspirations. See the module docstring: these are the
# current values, so the head is frozen where it is and growth is a decision.
SHARED_PREAMBLE_MAX_BYTES = 2770
SHARED_PREAMBLE_MAX_CONSTRAINTS = 10
BLOCK_MAX_CONSTRAINTS = 3

# The upstream figure for a tiny pattern-completer, kept as documentation of
# where the target sits relative to the measured ceiling above.
TINY_MODEL_CONSTRAINT_TARGET = 5

# A labelled negative sample is copied, not avoided, by a weaker model.
CONTRAST_EXAMPLE_MARKERS: tuple[str, ...] = (
    "bad:",
    "wrong:",
    "incorrect:",
    "anti-example:",
    "counter-example:",
    "don't do this",
    "do not do this",
)

# A constraint is a sentence that tells the reader to do or not do something.
# RFC 2119 modals plus the directive negations OMH's own prompt text uses.
_CONSTRAINT_MARKER = re.compile(
    r"\b(?:must|shall|should|may|never|always|only|required|forbidden|do not|don't|stop)\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\s+--\s+")


@dataclass(frozen=True, slots=True)
class BlockBudget:
    label: str
    chars: int
    constraints: int


def constraint_count(text: str) -> int:
    """Count sentences carrying a directive marker.

    A proxy, and named as one: it counts the sentences a reader has to hold as
    a rule, not the rules themselves. It is stable, arguable in the open, and
    the same measure on both sides of a change, which is what a ratchet needs.
    """
    return sum(
        1 for part in _SENTENCE_SPLIT.split(text) if part.strip() and _CONSTRAINT_MARKER.search(part)
    )


def contrast_example_markers(text: str) -> tuple[str, ...]:
    """Return every labelled-negative-sample marker present in a block."""
    lowered = text.casefold()
    return tuple(marker for marker in CONTRAST_EXAMPLE_MARKERS if marker in lowered)


def shared_preamble_blocks() -> list[BlockBudget]:
    """Budget each OMH-authored block of the executor-invariant shared preamble.

    The first line is the caller's goal text, whose length is the operator's
    business rather than a budget OMH owns, so it is excluded.
    """
    from ..coding.unit_prompt_protocol import shared_unit_preamble_lines

    return [
        BlockBudget(f"shared[{index}]", len(line), constraint_count(line))
        for index, line in enumerate(shared_unit_preamble_lines("goal"))
        if index > 0
    ]


def dispatched_prompt_blocks() -> dict[str, str]:
    """Every deterministic block of prompt text that reaches an executor.

    Keyed by a stable label so a violation names the block an author edits.
    The goal line is excluded: it is the caller's text, not OMH's.
    """
    from ..coding.unit_prompt_protocol import (
        FAILURE_KIND_PROTOCOL,
        GOAL_ECHO_PROTOCOL,
        HIGH_EFFORT_CALIBRATIONS,
        MAIN_AGENT_COMPOSITION_CALIBRATIONS,
        MODEL_COMPOSITION_CALIBRATIONS,
        MODEL_HIGH_EFFORT_CALIBRATIONS,
        PROMPT_CACHE_COMPOSITION_PROTOCOL,
        REVIEW_ROLE_PROTOCOL,
        SHARED_MACHINE_PROTOCOL,
        TOOL_BATCHING_PROTOCOL,
        UNIT_RESULT_RETURN_PROTOCOL,
        VERIFICATION_STOP_PROTOCOL,
    )

    blocks = {
        "GOAL_ECHO_PROTOCOL": GOAL_ECHO_PROTOCOL,
        "VERIFICATION_STOP_PROTOCOL": VERIFICATION_STOP_PROTOCOL,
        "FAILURE_KIND_PROTOCOL": FAILURE_KIND_PROTOCOL,
        "UNIT_RESULT_RETURN_PROTOCOL": UNIT_RESULT_RETURN_PROTOCOL,
        "PROMPT_CACHE_COMPOSITION_PROTOCOL": PROMPT_CACHE_COMPOSITION_PROTOCOL,
        "REVIEW_ROLE_PROTOCOL": REVIEW_ROLE_PROTOCOL,
        "TOOL_BATCHING_PROTOCOL": TOOL_BATCHING_PROTOCOL,
        "SHARED_MACHINE_PROTOCOL": SHARED_MACHINE_PROTOCOL,
    }
    for family, text in HIGH_EFFORT_CALIBRATIONS.items():
        blocks[f"HIGH_EFFORT_CALIBRATIONS[{family}]"] = text
    for family, text in MAIN_AGENT_COMPOSITION_CALIBRATIONS.items():
        blocks[f"MAIN_AGENT_COMPOSITION_CALIBRATIONS[{family}]"] = text
    for model_id, text in MODEL_HIGH_EFFORT_CALIBRATIONS.items():
        blocks[f"MODEL_HIGH_EFFORT_CALIBRATIONS[{model_id}]"] = text
    for model_id, text in MODEL_COMPOSITION_CALIBRATIONS.items():
        blocks[f"MODEL_COMPOSITION_CALIBRATIONS[{model_id}]"] = text
    return blocks


def small_model_prompt_violations() -> list[dict[str, object]]:
    """Return every budget breach, each naming the block an author edits."""
    found: list[dict[str, object]] = []
    blocks = shared_preamble_blocks()
    shared_bytes = sum(block.chars for block in blocks)
    shared_constraints = sum(block.constraints for block in blocks)

    if shared_bytes > SHARED_PREAMBLE_MAX_BYTES:
        found.append(
            {
                "rule": "SHARED_PREAMBLE_BYTES",
                "block": "shared_unit_preamble_lines()",
                "measured": shared_bytes,
                "ceiling": SHARED_PREAMBLE_MAX_BYTES,
                "detail": (
                    "the executor-invariant head every sibling prompt carries grew; every lane pays "
                    "this, including the weakest local CLI in the fleet"
                ),
            }
        )
    if shared_constraints > SHARED_PREAMBLE_MAX_CONSTRAINTS:
        found.append(
            {
                "rule": "SHARED_PREAMBLE_CONSTRAINTS",
                "block": "shared_unit_preamble_lines()",
                "measured": shared_constraints,
                "ceiling": SHARED_PREAMBLE_MAX_CONSTRAINTS,
                "detail": (
                    "a rule added to the shared head displaces a rule already there on the lanes "
                    "least able to afford it; say which one it displaces, or put it in a "
                    "unit-varying block"
                ),
            }
        )

    for label, text in sorted(dispatched_prompt_blocks().items()):
        constraints = constraint_count(text)
        if constraints > BLOCK_MAX_CONSTRAINTS:
            found.append(
                {
                    "rule": "BLOCK_CONSTRAINTS",
                    "block": label,
                    "measured": constraints,
                    "ceiling": BLOCK_MAX_CONSTRAINTS,
                    "detail": "one block asks a reader to hold too many rules at once; split it or cut one",
                }
            )
        markers = contrast_example_markers(text)
        if markers:
            found.append(
                {
                    "rule": "CONTRAST_EXAMPLE",
                    "block": label,
                    "measured": ", ".join(markers),
                    "ceiling": "none",
                    "detail": (
                        "a labelled negative sample gets copied rather than avoided by a weaker "
                        "model; state the wanted shape instead"
                    ),
                }
            )
    return found


def small_model_prompt_payload() -> dict[str, object]:
    blocks = shared_preamble_blocks()
    violations = small_model_prompt_violations()
    dispatched = dispatched_prompt_blocks()
    return {
        "schema_version": SMALL_MODEL_PROMPT_BUDGET_SCHEMA_VERSION,
        "description": (
            "Budget for the prompt text every executor reads. The shared preamble is "
            "executor-invariant, so it is written for the smallest model in the fleet, not the "
            "largest. Constraint counts are a sentence-level proxy, not a count of rules."
        ),
        "ok": not violations,
        "ceilings": {
            "shared_preamble_max_bytes": SHARED_PREAMBLE_MAX_BYTES,
            "shared_preamble_max_constraints": SHARED_PREAMBLE_MAX_CONSTRAINTS,
            "block_max_constraints": BLOCK_MAX_CONSTRAINTS,
            "tiny_model_constraint_target": TINY_MODEL_CONSTRAINT_TARGET,
        },
        "shared_preamble": {
            "bytes": sum(block.chars for block in blocks),
            "constraints": sum(block.constraints for block in blocks),
            "blocks": [
                {"label": block.label, "chars": block.chars, "constraints": block.constraints}
                for block in blocks
            ],
        },
        "dispatched_block_count": len(dispatched),
        "violations": violations,
    }


def format_small_model_prompt_violations(violations: list[dict[str, object]]) -> str:
    if not violations:
        return ""
    lines = [f"{len(violations)} shared-prompt budget violation(s):"]
    for finding in violations:
        lines.append(
            f"  [{finding['rule']}] {finding['block']}: measured {finding['measured']}, "
            f"ceiling {finding['ceiling']}"
        )
        lines.append(f"    {finding['detail']}")
    lines.append(
        "  Ceilings are the measured current values and live in "
        "src/quality/small_model_prompt_budget.py; the authoring doctrine is the "
        "'Writing for the smallest model in the fleet' section of MODEL_OPTI.md."
    )
    return "\n".join(lines)


__all__ = [
    "BLOCK_MAX_CONSTRAINTS",
    "CONTRAST_EXAMPLE_MARKERS",
    "SHARED_PREAMBLE_MAX_BYTES",
    "SHARED_PREAMBLE_MAX_CONSTRAINTS",
    "SMALL_MODEL_PROMPT_BUDGET_SCHEMA_VERSION",
    "TINY_MODEL_CONSTRAINT_TARGET",
    "BlockBudget",
    "constraint_count",
    "contrast_example_markers",
    "dispatched_prompt_blocks",
    "format_small_model_prompt_violations",
    "shared_preamble_blocks",
    "small_model_prompt_payload",
    "small_model_prompt_violations",
]

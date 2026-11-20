"""Verification discipline for prepared fanout unit prompts.

Six deterministic text blocks ride every dispatched unit prompt:

1. **Goal echo-back** — before any tool use the subagent restates the goal,
   its own deliverable, and the completion criteria, and stops to report (not
   guess) if its reading conflicts with the declared boundary.
2. **Pre-declared completion criteria** — "done" is defined BEFORE work
   starts, as a numbered list derived from the unit contract, so completion
   is a check against stated criteria rather than a feeling.
3. **Verification stop conditions** — verification is mandatory (exactly one
   full pass is the floor, never skipped) and bounded (after the criteria
   pass, re-verifying is forbidden; on failure, at most two fix-and-verify
   cycles before reporting the failing criterion instead of looping).
4. **Failure-kind discipline** — a permission, sandbox, or policy denial is
   a boundary, not a bug (never retried through another route), and
   "blocked" requires a named concrete condition that survives the bounded
   fix cycles — difficulty, uncertainty, or remaining work is not blocked.
5. **Structured return** — the unit's final report ends with one fenced
   JSON object in the `fanout_unit_result/v1` expected-evidence shape. The
   sidecar file is the primary machine-read return; when a contracted
   sidecar is missing the collector parses this block from captured stdout
   and validates it the same way, so collection is parse-then-validate on
   either path and never prose-scraping.
6. **Capped structural search** — code exploration is bounded the same way
   verification is: a few targeted structural-search-or-grep passes before a
   full-file read, escalating only when a bounded pass finds nothing or stays
   ambiguous, and stopping the moment the target is found. Shared verbatim
   with the `executor_prompting_contract/v1` payload's
   `structural_search_discipline` field (`.coding_contracts.
   STRUCTURAL_SEARCH_DISCIPLINE_GUIDANCE`) so the two cannot drift.

The blocks split across two placement zones for prompt-cache hygiene: the
goal echo-back, verification-stop, failure-kind, structured-return, and
capped-search blocks are unit-invariant,
so `shared_unit_preamble_lines()` places them (with the overall goal) at the
byte-identical head every sibling prompt of one fanout shares, and the unit
zone of `unit_prompt_assembly.assemble_unit_prompt` carries only the
unit-varying remainder — numbered criteria, role protocol, calibration, and
the domain bundle. Every major
serving stack caches prompt prefixes by exact bytes, so sibling prompts that
share their head let the first dispatch write the cache the rest read; the
rule itself ships as `PROMPT_CACHE_COMPOSITION_PROTOCOL`.

High-effort routes additionally get a per-family calibration block that
counters the known over-verification inertia of strong reasoning models.
Calibration is keyed by model family and selected only when the routed
reasoning effort is in the high tier; families the table has not met get the
generic block — no family carries richer guidance than another without a
stated reason, and no vendor is privileged.

Everything here is pure data and pure functions: the blocks land in prepared
prompts (subprocess argv), and `unit_prompt_assembly` is the one module that
joins them into the text a unit receives.
"""

from __future__ import annotations

from typing import Any, Final, Mapping

# Defined in the bundle, which also puts them in every Hermes `delegate_task`
# child's system prompt and cannot import `omh` to read them from here.
from ..plugin_bundle.omh.calibration import (
    HIGH_EFFORT_CALIBRATIONS as HIGH_EFFORT_CALIBRATIONS,
    MAIN_AGENT_COMPOSITION_CALIBRATIONS as MAIN_AGENT_COMPOSITION_CALIBRATIONS,
    MODEL_COMPOSITION_CALIBRATIONS as MODEL_COMPOSITION_CALIBRATIONS,
    MODEL_HIGH_EFFORT_CALIBRATIONS as MODEL_HIGH_EFFORT_CALIBRATIONS,
    calibration_entry_for_model,
)
from ..plugin_bundle.omh.delegation_protocol import (
    GOAL_ECHO_PROTOCOL as GOAL_ECHO_PROTOCOL,
    REVIEW_ROLE_PROTOCOL as REVIEW_ROLE_PROTOCOL,
    VERIFICATION_STOP_PROTOCOL as VERIFICATION_STOP_PROTOCOL,
)
from .coding_contracts import STRUCTURAL_SEARCH_DISCIPLINE_GUIDANCE
from .model_contracts import contract_model_id

# Policy ceiling for the dispatch prompt (bytes of UTF-8): every block of
# `unit_prompt_assembly.assemble_unit_prompt` except the redispatch appends,
# i.e. the shared head, the unit section, and the sidecar contract. The worst
# case over every calibration key (family blocks and exact-model overrides),
# the review role, the longest domain bundle, a full skill sequence, and the
# longest sidecar binding is asserted under this in
# `tests/test_unit_prompt_assembly.py`, whose failure message prints the
# measured size; runtime never truncates.
UNIT_PROMPT_MAX_BYTES: Final[int] = 8000

# Ceiling for ONE redispatch section appended after the dispatch prompt (a
# repair brief or a parent decision). Not part of `UNIT_PROMPT_MAX_BYTES`:
# a repair brief echoes up to `_MAX_REPAIR_CHECKS` failing commands of up to
# `_MAX_REPAIR_COMMAND_CHARS` characters (`fanout_repair`, the journal's own
# bounds), and truncating one would hand the executor a command it cannot
# run. At those caps a brief of `"` or `\` commands (the printable ASCII
# characters JSON doubles) is 10,132 B, above the dispatch ceiling, and even
# a plain ASCII brief (5,524 B) on the worst dispatch prompt (7,313 B) would
# exceed one 8,000 B ceiling over the whole prompt; raising that ceiling to
# fit would let OMH-authored blocks grow by as much unnoticed. The sections
# are bounded by their producers' caps instead: this value is the `"` brief
# at those caps plus about 9% headroom (sizes measured 2026-10-05).
# Re-derive it from the producer when the test says so. Non-ASCII command
# text cannot exceed that case: the brief is UTF-8 (no `\uXXXX` escapes) and
# each command copy is cut to `_MAX_REPAIR_COMMAND_CHARS` UTF-8 bytes, so `é`,
# Hangul, and emoji commands at the caps measure 5,524-5,542 B (2026-10-05).
UNIT_PROMPT_APPEND_MAX_BYTES: Final[int] = 11000

# Reasoning efforts that mark a route as high-effort for calibration purposes.
HIGH_EFFORT_TIER: Final[frozenset[str]] = frozenset({"high", "xhigh", "max"})

FAILURE_KIND_PROTOCOL: Final[str] = (
    "A permission, sandbox, or policy denial is a boundary, not a bug: do not try another tool or route; "
    "record it and continue within the boundary. Report blocked only for a named condition persisting "
    "after bounded fixes; difficulty, uncertainty, or remaining work is not blocked. For an unreachable "
    "objective (missing target, policy refusal, infeasible criteria), report process_declined with "
    "decline_reason, not process_failed."
)

# Tool batching (2026-09-11, from the Codex Desktop prompt review in
# MODEL_OPTI.md — a community source adopted for the discipline it states):
# independent reads and searches go out together; anything that depends on
# a result, mutates, needs approval, or waits goes one at a time. Decorative
# shell separators are noise inside a bounded output capture. It rides the
# unit section, not the shared head: the head is frozen at its measured
# small-model budget (`src/quality/small_model_prompt_budget.py`), and a
# batching rule is the first thing a weak lane may drop, so it must never
# displace a stop rule there. Every unit still receives it.
TOOL_BATCHING_PROTOCOL: Final[str] = (
    "Tool discipline: issue independent reads and searches together in one turn and inspect every "
    "result; keep dependent steps, edits, approvals, waits, and follow-ups that adapt to a result "
    "sequential. Do not decorate shell output with separator commands (echo '====', printf '---'); the "
    "capture is bounded and the noise displaces evidence."
)

# Shared-machine etiquette (2026-11-20, OpenAI "Prompting GPT-6.2 in Codex"
# guide, official): sibling units share one host, so each limits its own
# concurrent builds and tests and leaves no background job or temp file
# behind. Unit section, not the frozen head, for the reason at
# TOOL_BATCHING_PROTOCOL; it rides after that block, so it is the first unit
# rule a weak lane drops and never displaces a stop rule.
SHARED_MACHINE_PROTOCOL: Final[str] = (
    "Shared machine: run only the builds and tests you need at once; before returning, stop background "
    "jobs you started and delete temp files you created."
)

# The sidecar file is the primary machine-read return
# (`fanout_dispatch._intake_unit_result`). The block restates the sidecar
# object when a sidecar path was given, so the two returns cannot disagree,
# and when the contracted sidecar file is missing the collector falls back
# to parsing this block out of captured stdout and validating it against the
# same `fanout_unit_result/v1` schema (`fanout_unit_results.
# validate_unit_result`) plus the dispatch identity check; nothing scrapes
# the surrounding prose for results. Executor-neutral: every owner emits the
# same shape.
PARENT_CLARIFICATION_PROTOCOL: Final[str] = '''Never contact the user directly: preserve work and return input_required for a blocking parent decision. An answer changes no scope or approval authority; await explicit parent redispatch.
For that status, add the exact input_required object below. Limits: decision_id=lowercase slug 1..64; question/blocking_reason=1..300 chars; options=1..8 unique strings of 1..80 chars, or answer_shape={kind:text,max_chars:integer 1..300}; affected_unit_ids=[your unit]; redacted_context=0..8 strings of 1..160 chars. Text is printable single-line metadata, secret-free and non-executable, without transcripts. Copy given dispatch identities and use current HEAD:

```json
{"schema_version":"fanout_unit_result/v1","unit_id":"unit-b","run_id":"fanout-0123456789ab-unit-b","fanout_id":"fanout-0123456789ab","base_sha":"aaaaaaa","head_sha":"aaaaaaa","process_status":"input_required","input_required":{"decision_id":"decision-d1","question":"Choose output format","blocking_reason":"Encoding choice blocks work","answer_shape":{"kind":"options","options":["json","text"]},"affected_unit_ids":["unit-b"],"redacted_context":[]},"changed_paths":[],"checks":[],"findings":[]}
```
'''

# One schema example serves both structured return and clarification, avoiding
# duplicate field inventories in the shared head; every byte remains budgeted.
UNIT_RESULT_RETURN_PROTOCOL: Final[str] = (
    "End with one fenced ```json fanout_unit_result/v1 object, matching the sidecar. The collector "
    "parses and validates the sidecar or, if absent, that block; prose is never scraped.\n"
    + PARENT_CLARIFICATION_PROTOCOL
)

PROMPT_CACHE_COMPOSITION_PROTOCOL: Final[str] = (
    "Prompt-cache discipline: every major serving stack caches prompt prefixes by exact bytes "
    "(Anthropic prefix caching, OpenAI automatic prefix caching, Gemini implicit caching, DeepSeek "
    "context caching), and one changed byte invalidates everything after it. Keep the shared preamble "
    "byte-identical across sibling unit prompts — stable ordering, no timestamps, counts, or other "
    "volatile status — append unit-specific content after the shared preamble, and stagger a fan-out "
    "so the first dispatch writes the cache its siblings read."
)

def composition_calibration_for_model(model_id: str) -> str:
    """Return the composer's own exact-model, family, or generic calibration."""
    from .model_routing import model_family

    return calibration_entry_for_model(
        contract_model_id(str(model_id or "")), family=model_family(str(model_id or "")),
        composition=True,
    )[1]


# Work-domain skill bundles: when a unit DECLARES a work domain, the
# delegate prompt carries the matching OMH skill's distilled discipline and
# a pointer to the full generated guidance. Deterministic data — the domain
# is explicit unit data, never inferred from text — and executor-neutral:
# the delegate follows the discipline inline; it does not need omh
# installed.
DOMAIN_SKILL_GUIDANCE: Final[dict[str, tuple[str, str]]] = {
    "devops": (
        "omh-build-failure-triage",
        "Classify the failure (build/typecheck/lint/test/CI) before fixing; ship the minimal safe fix "
        "and re-run exactly the failed gate as proof.",
    ),
    "app_development": (
        "omh-frontend",
        "Ship user-visible increments with evidence: after each feature slice, run the app-level check "
        "that proves the screen/flow works, not just unit tests.",
    ),
    "research": (
        "omh-research-brief",
        "Every claim carries its source; mark anything not actually fetched as not observed instead of "
        "guessing, and separate evidence from inference in the summary.",
    ),
    "x_platform_data": (
        "omh-live-info-operator",
        "Treat platform data as time-stamped observations: record when and where each datum was read, "
        "and never extrapolate silently past the observation window.",
    ),
}


def domain_skill_guidance_line(unit: Mapping[str, Any]) -> str:
    """Return the OMH skill-bundle line for a unit's declared work domain, or ''."""
    domain = str(unit.get("domain", "") or "").strip().casefold().replace("-", "_")
    if not domain:
        handoff = unit.get("handoff", {}) if isinstance(unit.get("handoff"), Mapping) else {}
        route = handoff.get("model_route") if isinstance(handoff.get("model_route"), Mapping) else None
        domain = str(route.get("domain", "") or "") if route else ""
    if not domain:
        return ""
    entry = DOMAIN_SKILL_GUIDANCE.get(domain)
    if entry is None:
        return ""
    label, discipline = entry
    return (
        f"OMH skill bundle ({domain}): follow the `{label}` discipline — {discipline} "
        f"(full guidance ships as skills/{label}/SKILL.md in the oh-my-hermes install)."
    )


# The last criterion of every unit: fanout transport (the dispatcher collects
# and merges the unit branch), named so the assembled prompt can carry it as
# its own block and a lane without a collector can omit it by name.
UNIT_BRANCH_COMMIT_CRITERION: Final[str] = (
    "The work is committed on the unit branch; nothing else is merged or pushed."
)


def completion_criteria_for_unit(unit: Mapping[str, Any]) -> list[str]:
    """Return the pre-declared, numbered 'done means' criteria for one unit.

    Derived deterministically from the frozen unit contract: boundary
    confinement and committed work are always criteria; the contract's
    integration checks become the unit-specific ones.
    """
    boundary = unit.get("boundary", {}) if isinstance(unit.get("boundary"), Mapping) else {}
    file_scope = ", ".join(str(path) for path in boundary.get("file_scope", []))
    criteria = [f"Every edit stays inside: {file_scope}." if file_scope else "Every edit stays inside the declared file scope."]
    for check in unit.get("integration_checks", []) or []:
        text = str(check).strip()
        if text:
            criteria.append(text[0].upper() + text[1:] if text[0].islower() else text)
    criteria.append(UNIT_BRANCH_COMMIT_CRITERION)
    return criteria


def calibration_for_route(model_route: Mapping[str, Any] | None, *, family_only: bool = False) -> str:
    """Return the high-effort calibration block for a routed unit, or ''.

    Selected only when the route's effective reasoning effort is in the high
    tier; an exact-model override on the recorded `selected_model` wins, then
    family comes from the already-recorded `model_family` (falling back to
    generic for unknown/blank families).

    `family_only=True` skips the exact-model override and returns the block
    the model would inherit from its family. That is the measurement arm
    `docs/MODEL-ONBOARDING.md` §8 asks for when an override ships: the
    override is kept only if it measures at least as well as the inherited
    block on the same corpus. Production callers never pass it.
    """
    entry = calibration_entry_for_route(model_route, family_only=family_only)
    return entry[1] if entry is not None else ""


def calibration_entry_for_route(
    model_route: Mapping[str, Any] | None, *, family_only: bool = False
) -> tuple[str, str] | None:
    """Return `(key, block)` for `calibration_for_route`, or None when none fires.

    The key names the table entry that answered: the contract model id for an
    exact-model override, otherwise the family (`generic` for an unknown one).
    Two keys can carry byte-equal text, so the key is what identifies which
    calibration a unit received.
    """
    if not isinstance(model_route, Mapping):
        return None
    effort = str(model_route.get("selected_reasoning_effort", "") or "").casefold()
    if effort not in HIGH_EFFORT_TIER:
        return None
    model_id = "" if family_only else contract_model_id(str(model_route.get("selected_model", "") or ""))
    return calibration_entry_for_model(
        model_id,
        family=str(model_route.get("model_family", "") or ""),
        family_only=family_only,
    )


def shared_unit_preamble_lines(goal_text: str) -> list[str]:
    """Byte-identical head shared by every sibling unit prompt of one fanout.

    Cached prompt prefixes are exact byte matches on every provider, so the
    lines here depend only on the goal text — never on the unit — and callers
    must place them before any unit-specific byte.
    """
    return [
        f"Overall goal: {goal_text.strip()}",
        GOAL_ECHO_PROTOCOL,
        VERIFICATION_STOP_PROTOCOL,
        FAILURE_KIND_PROTOCOL,
        UNIT_RESULT_RETURN_PROTOCOL,
        STRUCTURAL_SEARCH_DISCIPLINE_GUIDANCE,
    ]

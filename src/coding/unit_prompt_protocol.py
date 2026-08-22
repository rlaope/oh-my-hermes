"""Verification discipline for prepared fanout unit prompts.

Four deterministic text blocks ride every dispatched unit prompt:

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

High-effort routes additionally get a per-family calibration block that
counters the known over-verification inertia of strong reasoning models.
Calibration is keyed by model family and selected only when the routed
reasoning effort is in the high tier; families the table has not met get the
generic block — no family carries richer guidance than another without a
stated reason, and no vendor is privileged.

Everything here is pure data and pure functions: the blocks land in prepared
prompts (subprocess argv), so the total prompt size is policy-gated by
`UNIT_PROMPT_MAX_BYTES` in tests rather than trimmed at runtime.
"""

from __future__ import annotations

from typing import Any, Final, Mapping

# Policy ceiling for a fully-assembled unit prompt (bytes of UTF-8). The
# worst-case combination across roles, owners, and calibration blocks is
# asserted under this in tests; runtime never truncates.
UNIT_PROMPT_MAX_BYTES: Final[int] = 8000

# Reasoning efforts that mark a route as high-effort for calibration purposes.
HIGH_EFFORT_TIER: Final[frozenset[str]] = frozenset({"high", "xhigh", "max"})

GOAL_ECHO_PROTOCOL: Final[str] = (
    "Before your first tool use, restate in your own words: (1) the overall goal in one sentence, "
    "(2) this unit's deliverable, and (3) the numbered completion criteria below. If your restatement "
    "conflicts with the declared boundary or criteria, stop and report the conflict instead of guessing."
)

VERIFICATION_STOP_PROTOCOL: Final[str] = (
    "Verification discipline: run exactly ONE full verification pass against the numbered criteria after "
    "finishing the work — verification is never skipped. A check failure blocks completion only when it "
    "violates a stated criterion; note anything else as an observation and move on. Once every criterion "
    "has passed, STOP: do not re-verify, do not add a just-to-be-sure pass, and do not restart verification "
    "after edits that no criterion covers. If a criterion still fails after two fix-and-verify cycles, "
    "commit what passes and report the failing criterion with its output instead of looping."
)

FAILURE_KIND_PROTOCOL: Final[str] = (
    "Failure-kind discipline: a permission, sandbox, or policy denial is a boundary, not a bug — do "
    "not retry it through another tool or route; record the denial and continue with what the boundary "
    "allows, or report it. Report blocked only when the same concrete condition still holds after the "
    "bounded fix-and-verify cycles, and name that condition; difficulty, uncertainty, or useful "
    "remaining work is not blocked."
)

REVIEW_ROLE_PROTOCOL: Final[str] = (
    "Review discipline: a finding blocks only when it violates a stated success criterion of the reviewed "
    "work; list every other finding as non-blocking. Cap re-review at two rounds — after that, report the "
    "remaining criterion-cited blockers rather than starting another round."
)

# Per-family counters to the over-verification inertia of high-effort routes.
# Keyed by `model_family()` output; "generic" is the mandatory fallback so an
# unknown family never gets weaker discipline than a known one.
HIGH_EFFORT_CALIBRATIONS: Final[dict[str, str]] = {
    "gpt": (
        "High-effort calibration: your reasoning depth is for the hard parts of THIS unit, not for "
        "re-deriving settled facts. Once the decisive fact is in view, act on it; once a criterion has "
        "passed, it is settled evidence — reopen it only when new output contradicts it, never to "
        "reassure yourself."
    ),
    "claude": (
        "High-effort calibration: follow the numbered criteria as the complete checklist — do not grow "
        "the checklist mid-run. Deliberate deeply only where correctness is genuinely at risk; for "
        "mechanical steps, act directly and let the single verification pass prove them."
    ),
    "gemini": (
        "High-effort calibration: a claim without the tool output that proves it is not evidence — "
        "run the actual check and report from its output, never from memory. Done-sounding language "
        "before the single mandatory verification pass is a failure, not optimism, and creative "
        "expansion outside the declared boundary is a defect here, not an improvement."
    ),
    "grok": (
        "High-effort calibration: speed is your default; the numbered criteria are the brake. A fast "
        "first answer never skips the single mandatory verification pass, and a quicker path never "
        "trades away the declared boundary. When search surfaces many candidates, pick by the stated "
        "criteria once and act instead of re-querying for reassurance."
    ),
    "kimi": (
        "High-effort calibration: reserve the decompose-compare-verify loop for the genuinely hard "
        "parts; mechanical steps are low-entropy — execute them directly without enumerating "
        "alternatives. Decide each approach once and reopen it only when new output contradicts it. "
        "If you catch yourself listing options for a step no criterion distinguishes, stop analyzing "
        "and act."
    ),
    "glm": (
        "High-effort calibration: use interleaved reasoning only where it improves a tool decision: "
        "interpret each result, choose the next bounded action, and preserve prior reasoning context "
        "when the runtime exposes it. Mechanical steps need no extended plan. Keep the change "
        "goal-shaped, and let the single verification pass prove it."
    ),
    "qwen": (
        "High-effort calibration: current Qwen3-Coder is a non-thinking coding-agent model, so do not "
        "ask it to emit reasoning or thinking tags. Give the exact goal, repository state, allowed "
        "boundaries, tool schemas, and completion criteria, then follow one explicit plan. Recover "
        "from failures using observed tool output and stop after one passing verification run."
    ),
    "deepseek": (
        "High-effort calibration: treat the model version and declared thinking mode as contract "
        "fields; never apply legacy R1 prompting to every DeepSeek model. Preserve runtime-provided "
        "reasoning context across tool results only on a reasoning-capable route; otherwise use the "
        "same explicit goal, boundaries, and completion criteria without thinking tags. Edit by exact "
        "literal strings — a unique match with exact whitespace — as this family's edit training "
        "expects. Make the smallest correct change, verify once, and stop."
    ),
    "mistral": (
        "High-effort calibration: instructions are followed literally here, so the stated criteria "
        "are the whole contract — check every one even when the change looks obviously right. "
        "Concision is for the output, never for the evidence: the single mandatory verification "
        "pass runs regardless of how small the diff is."
    ),
    "llama": (
        "High-effort calibration: the serving deployment is part of the contract — tool-calling "
        "support, context limits, and output limits come from the host, not the model name. Prove a "
        "capability with a real call before depending on it, fall back to explicit step-by-step "
        "tool use when structured calling is unreliable, and stop after one passing verification run."
    ),
    "codestral": (
        "High-effort calibration: this is a code-completion specialist — work in file-scoped, "
        "concrete edits rather than open-ended investigation, keep each step's expected output "
        "small and explicit, and prove the change with the repository's own check commands instead "
        "of prose explanation."
    ),
    "solar": (
        "High-effort calibration: an efficient instruction-follower, not a long-horizon reasoner — "
        "follow the one explicit plan you were given in bounded steps instead of deriving a new "
        "one, report a missing constraint rather than inferring it, and verify once against the "
        "stated criteria before stopping."
    ),
    "generic": (
        "High-effort calibration: reserve extended reasoning for genuine ambiguity with materially "
        "different outcomes. Decide once, act, verify once against the criteria, and stop — speed is "
        "never a reason to skip the verification pass, and thoroughness is never a reason to repeat it."
    ),
}


# Calibration for the MAIN agent — the one COMPOSING the split, the unit
# prompts, and the briefings — keyed by ITS OWN model family. The user picks
# what Hermes runs on (a claude-family fable/opus, a gpt-family sol/terra, a
# gemini, a kimi, a qwen, ...), and each family fails composition differently: the
# guidance counters the composer's own defaults, never the subagents'.
# Same key set as HIGH_EFFORT_CALIBRATIONS (parity-tested) so no family gets
# subagent discipline without composer discipline, and "generic" stays the
# mandatory fallback for families the table has not met.
MAIN_AGENT_COMPOSITION_CALIBRATIONS: Final[dict[str, str]] = {
    "gpt": (
        "Composition calibration: compose outcome-first, but never compress the contract away — "
        "every unit prompt keeps its declared boundary, dependencies, numbered criteria, and the "
        "one-pass verification floor spelled out. A tighter prompt that drops a stated invariant is "
        "a worse prompt."
    ),
    "claude": (
        "Composition calibration: split only what the goal requires — do not grow the fanout with "
        "speculative units, and never spawn a subagent to double-check your own composition. The "
        "criteria you write are a closed checklist: state them once, completely, and freeze."
    ),
    "gemini": (
        "Composition calibration: compose from tool-verified facts, not recall — run the inventory "
        "and readiness commands before naming owners or models, and never describe a unit as "
        "prepared until the actual prepare command produced its artifact. A split narrated without "
        "the commands behind it is not a split."
    ),
    "kimi": (
        "Composition calibration: partitioning work is mostly low-entropy — decide the split once, "
        "freeze it, and reserve deep reasoning for boundary overlaps and dependency cycles. Do not "
        "enumerate alternative splits nobody asked for; if two partitions both satisfy the "
        "boundaries, take the first and move."
    ),
    "glm": (
        "Composition calibration: use interleaved reasoning only to interpret evidence between "
        "contract-building tools; mechanical field assembly needs no extra planning. Every unit "
        "carries its owner, boundary, and known route fields. Once boundaries are clean and "
        "dependencies acyclic, freeze the smallest split that covers the goal."
    ),
    "grok": (
        "Composition calibration: speed never skips freeze-time validation — run the overlap and "
        "cycle checks before recording the contract, not after dispatch fails. Pick the partition "
        "once by the stated boundaries and dispatch; re-querying for a better split is re-verifying "
        "a settled decision."
    ),
    "qwen": (
        "Composition calibration: current Qwen3-Coder is non-thinking; freeze one ordered split with "
        "exact owners, boundaries, tool contracts, dependencies, roles, and verification commands "
        "instead of requesting reasoning tags. Validate once and move to dispatch."
    ),
    "deepseek": (
        "Composition calibration: keep the DeepSeek model version and thinking mode explicit in the "
        "prepared route. Preserve runtime reasoning context only when the selected model and executor "
        "support it; otherwise compose exact owners, scopes, dependencies, and verification commands "
        "without synthetic thinking instructions. DeepSeek serving prices cached prefixes, so keep the "
        "shared preamble byte-identical across unit prompts — stable ordering, no timestamps or "
        "volatile status — with unit-specific content appended after it. Validate once and stop."
    ),
    "mistral": (
        "Composition calibration: write unit prompts literally and completely — a Mistral-family "
        "executor follows what is written, not what was implied, so every boundary, dependency, "
        "criterion, and verification command must be stated; never rely on the unit inferring an "
        "unstated invariant."
    ),
    "llama": (
        "Composition calibration: compose for the deployment, not the brand — confirm the served "
        "variant's tool contract and context budget before assigning units, and keep each unit "
        "prompt self-contained so a host with a smaller context window still receives the full "
        "contract."
    ),
    "codestral": (
        "Composition calibration: route codestral units as narrow, file-scoped implementation "
        "slices with exact verification commands; investigation, review, and synthesis belong on a "
        "generalist lane, and a unit that mixes them belongs split."
    ),
    "solar": (
        "Composition calibration: put the depth in the composition, not the unit — give each solar "
        "unit one explicit plan with short bounded steps, exact criteria, and its verification "
        "command, because the unit will execute the plan it is given rather than derive a better one."
    ),
    "generic": (
        "Composition calibration: compose the contract fields exactly, validate the split once with "
        "the validation command, and stop — composing is preparing evidence, and a prepared "
        "contract is the only proof a split exists."
    ),
}


def composition_calibration_for_model(model_id: str) -> str:
    """Return the main-agent composition calibration for the composer's own model.

    Family comes from `model_family()` (provider-prefixed ids welcome);
    unknown or blank families get the generic block — a composer never goes
    without discipline just because the table has not met its model.
    """
    from .model_routing import model_family

    family = model_family(str(model_id or ""))
    return MAIN_AGENT_COMPOSITION_CALIBRATIONS.get(
        family, MAIN_AGENT_COMPOSITION_CALIBRATIONS["generic"]
    )


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
    criteria.append("The work is committed on the unit branch; nothing else is merged or pushed.")
    return criteria


def calibration_for_route(model_route: Mapping[str, Any] | None) -> str:
    """Return the high-effort calibration block for a routed unit, or ''.

    Selected only when the route's effective reasoning effort is in the high
    tier; family comes from the already-recorded `model_family` (falling back
    to generic for unknown/blank families).
    """
    if not isinstance(model_route, Mapping):
        return ""
    effort = str(model_route.get("selected_reasoning_effort", "") or "").casefold()
    if effort not in HIGH_EFFORT_TIER:
        return ""
    family = str(model_route.get("model_family", "") or "").casefold()
    return HIGH_EFFORT_CALIBRATIONS.get(family, HIGH_EFFORT_CALIBRATIONS["generic"])


def unit_protocol_lines(unit: Mapping[str, Any]) -> list[str]:
    """Return the ordered protocol lines appended to a unit prompt."""
    criteria = completion_criteria_for_unit(unit)
    lines = [GOAL_ECHO_PROTOCOL, "Done means, and only means:"]
    lines.extend(f"{index}. {criterion}" for index, criterion in enumerate(criteria, start=1))
    lines.append(VERIFICATION_STOP_PROTOCOL)
    lines.append(FAILURE_KIND_PROTOCOL)
    handoff = unit.get("handoff", {}) if isinstance(unit.get("handoff"), Mapping) else {}
    model_route = handoff.get("model_route") if isinstance(handoff.get("model_route"), Mapping) else None
    # Contract units carry the declared role inside the recorded route, not as
    # a top-level key; accept both so pre-contract unit dicts behave the same.
    role = str(unit.get("role", "") or "") or (str(model_route.get("role", "") or "") if model_route else "")
    if role == "review":
        lines.append(REVIEW_ROLE_PROTOCOL)
    calibration = calibration_for_route(model_route)
    if calibration:
        lines.append(calibration)
    bundle = domain_skill_guidance_line(unit)
    if bundle:
        lines.append(bundle)
    return lines

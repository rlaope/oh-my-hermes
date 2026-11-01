"""The default-installed `jev-*` skills: procedures for OMH's own `omh_jev_ask` tool.

Pure catalog data plus the compact bodies and references they render to. Each
skill is a procedure around one tool call and never a route on its own: the
router reaches a Jev skill only when the person addresses Jev
(`routing/jev_addressing.py`), and the tool refuses unless the person named
Jev in the same turn. Every skill declares `requires_tools: [omh_jev_ask]`, so
Hermes leaves it out of the per-turn skill index when the tool is not
registered for this profile (no key, no route); that hiding is read from
Hermes' `prompt_builder._skill_should_show` and holds for callers that pass a
tool set, not observed in a live session.

Instruction text is written in OMH's own words. The upstream plugins these
skills learned from are listed with their reviewed refs in
`docs/SKILL-SOURCES.md`; no upstream sentence is copied.
"""

from __future__ import annotations

from .catalog_types import SkillDefinition, SkillExample, skill_view_call

JEV_REQUIRED_TOOL = "omh_jev_ask"
JEV_RAIL_REFERENCE = "omh-routing/references/jev-rail.md"
JEV_PRESET_REFERENCE_PATH = "references/preset.md"

_JEV_HANDOFF = (
    "Run in Hermes: build the ask, call `omh_jev_ask`, and report the numbers. Nothing is delegated; "
    "the partner workflow keeps its own verdict and Jev's answers are one more input to it."
)
_COMMON_SAFETY = (
    "Call `omh_jev_ask` only after the user asked for Jev in this turn; a skill loaded from the index is not a request.",
    "Before the first ask, tell the user in one line what `state` will carry and that it leaves the machine.",
    "A non-answer status is never an answer: report it and continue without Jev.",
)
_COMMON_RECOVERY = (
    "If `omh_jev_ask` is not in the tool list, say Jev is unavailable, point at the `plugin_jev_sidekick` line of `omh doctor`, and continue as main_model through the partner workflow.",
    "If the tool returns `consent_not_observed`, nothing was sent; offer the ask in one line naming what would be sent and wait for the user to reply `ask jev`.",
    "If the tool refuses `credential_like_content`, remove the secret-looking text from `state` rather than redacting it silently, and tell the user what was removed.",
)


def _definition(
    name: str,
    description: str,
    triggers: tuple[str, ...],
    use_when: str,
    *,
    category: str,
    hermes_role: str,
    required_inputs: tuple[str, ...],
    expected_outputs: tuple[str, ...],
    safety_rules: tuple[str, ...],
    quality_bar: tuple[str, ...],
    why: str,
    do_not_use_when: tuple[str, ...],
    good: SkillExample,
    bad: SkillExample,
    final_checklist: tuple[str, ...],
    recovery_notes: tuple[str, ...] = (),
    situations: tuple[str, ...] = (),
) -> SkillDefinition:
    return SkillDefinition(
        name,
        description,
        triggers,
        use_when,
        category=category,
        phase=name,
        hermes_role=hermes_role,
        delegation_boundary="retained-catalog-intent",
        handoff_policy=_JEV_HANDOFF,
        required_inputs=required_inputs,
        expected_outputs=expected_outputs,
        artifact_expectations=(
            "one metadata-only `omh_jev_ask_record/v1` ledger row per ask under `<omh_home>/jev/asks.jsonl`: hashes, counts, status, usage, cost; never the key, `state`, or question text",
        ),
        safety_rules=(*_COMMON_SAFETY, *safety_rules),
        quality_tier="evidence-gated",
        quality_bar=quality_bar,
        why_this_exists=why,
        do_not_use_when=do_not_use_when,
        good_example=good,
        bad_example=bad,
        final_checklist=final_checklist,
        recovery_notes=(*_COMMON_RECOVERY, *recovery_notes),
        host_requires_tools=(JEV_REQUIRED_TOOL,),
        progressive_disclosure=True,
        situations=situations,
    )


JEV_ASK_DEFINITION = _definition(
    "jev-ask",
    "User named Jev for yes/no or pick-one probabilities: Jev ask: typed yes/no, pick-one, or scored questions to Jev with your own key; returns probabilities, never prose.",
    ("jev-ask", "ask jev", "jev question", "jev score"),
    "Use when the user asks Jev a typed question about supplied text -- whether it does something, which of named options fits, or how it rates on an ordered scale -- or wants help writing such questions.",
    category="gateway",
    hermes_role="hybrid-guidance",
    required_inputs=("the text to judge", "one or more independent questions"),
    expected_outputs=("Jev's probabilities per question", "served model, attempts, and cost", "the non-answer status when there is no answer"),
    safety_rules=(
        "Never ask Jev what code can compute: counts, dates, arithmetic, or string checks.",
        "Report a probability between 0.4 and 0.6 as uncertain, never as yes or no.",
    ),
    quality_bar=(
        "Each question is atomic, self-contained, and independent of the others; a Choice carries an `unknown` option.",
        "`state` holds only the evidence the questions need.",
        "The report quotes numbers verbatim with the served model, attempts, and cost source.",
    ),
    why="`jev-ask` exists so a typed judgment about supplied text comes back as numbers the user can threshold, instead of a paragraph from a generative model, with one explicit call the user asked for.",
    do_not_use_when=(
        "The user wants a generative second opinion from Claude, Gemini, or another advisor; use `ask`.",
        "The user is choosing between strategic options and wants tradeoffs and a recommendation; use `strategy-brief`.",
        "The user wants Jev as a chat or coding model; that is a model setting, and Jev writes no text; use `model-setup`.",
        "The user is writing application code that calls TypeSafe; point at the vendor's own SDK documentation rather than calling the tool.",
    ),
    good=SkillExample(
        prompt="ask jev whether this README section covers installation",
        expected="Say the section text leaves the machine, send one Noul with the section as `state`, and report the probability, served model, and cost.",
        why="One atomic yes/no question over supplied text is what a typed ask answers.",
    ),
    bad=SkillExample(
        prompt="ask jev to write a better README",
        expected="Explain that Jev returns probabilities and writes no text; offer a typed question instead or continue as main_model.",
        why="Generation is outside what the tool can return.",
    ),
    final_checklist=(
        "The user asked for Jev in this turn and was told what `state` carries.",
        "The reported numbers match the tool result, with the served model and cost source.",
        "A non-answer was reported as its status, not as an answer.",
    ),
    situations=(
        "have jev rate this text",
        "jev probability that this is true",
        "let jev pick one of these options",
        "typed question for jev",
        "rate this with jev on a scale",
    ),
)

JEV_ROUTE_DEFINITION = _definition(
    "jev-route",
    "Undecided OMH route handed to Jev: Jev route pick: answer an OMH route question about which workflow fits, recorded without re-routing.",
    ("jev-route", "ask jev which workflow", "jev pick the workflow"),
    "Use when an OMH route came back undecidable with a `route_question` block, the answerer ladder lists `omh_jev_ask`, and the user asks Jev to pick the workflow.",
    category="gateway",
    hermes_role="hybrid-guidance",
    required_inputs=("the `route_question` block", "the user's message"),
    expected_outputs=("Jev's Choice and fit probabilities", "an `omh_route_answer` record with `answered_by: omh_jev_ask`", "a clarification offered to the user"),
    safety_rules=(
        "The deterministic route stays in force: present Jev's pick as a clarification and dispatch nothing without the user.",
        "Pass the block unchanged; editing a question changes its digest and breaks the record join.",
    ),
    quality_bar=(
        "`state` is the user's message, and the user was told it leaves the machine.",
        "The answer is recorded with the `ask_id` the tool returned.",
        "`none` winning is reported as no workflow fitting, not as an error.",
    ),
    why="`jev-route` exists so an undecidable route can get a typed answer from Jev that OMH observed itself and can score later, without letting that answer re-route anything.",
    do_not_use_when=(
        "The route was already decided; there is no route question to answer.",
        "The user is choosing a model or provider rather than a workflow; use `model-setup`.",
        "The host model is recording its own pick; recording a main_model answer needs no ask.",
    ),
    good=SkillExample(
        prompt="ask jev which workflow fits this request",
        expected="Send the route_question block with the message as `state`, show Jev's ranked pick as a question to the user, and record it with the ask_id.",
        why="The route was undecidable and the user asked Jev to pick.",
    ),
    bad=SkillExample(
        prompt="use jev as my router model",
        expected="Route to model setup: this is a configuration request, and Jev cannot be a chat model.",
        why="Choosing a model is not answering a route question.",
    ),
    final_checklist=(
        "The block was sent unchanged and its digest matches the recorded answer.",
        "No workflow was dispatched on Jev's answer alone.",
    ),
    situations=(
        "let jev choose the workflow",
        "jev breaks the routing tie",
        "route question for jev",
        "jev decides which skill fits",
        "undecidable route sent to jev",
    ),
)

JEV_FAILURE_TRIAGE_DEFINITION = _definition(
    "jev-failure-triage",
    "Failing run handed to Jev for a next move: Jev failure triage: retry, fix a dependency, ask for access, or change approach on a failing run.",
    ("jev-failure-triage", "jev failure triage", "ask jev if this failure is transient"),
    "Use when a command, test, or build failed or keeps failing, the user asked Jev, and a quick typed signal should pick the next move before the ordinary triage prepares a fix.",
    category="review",
    hermes_role="hybrid-review",
    required_inputs=("the failing command", "an excerpt of its error output", "how many times it was already retried"),
    expected_outputs=("the `failure_triage/v1` policy result", "the next move with the rule that fired"),
    safety_rules=(
        "`retry_once_suggested` is a suggestion: the host's own approval still applies to the rerun.",
        "You supply `attempts_so_far`; never ask Jev to count attempts.",
    ),
    quality_bar=(
        "`state` holds the command and an error excerpt, not the whole log.",
        "A non-answer is reported as `not_observed`, never as `no_signal`.",
    ),
    why="`jev-failure-triage` exists so a failing run gets a fixed-rule next move from typed answers, computed by OMH code rather than by the model eyeballing numbers.",
    do_not_use_when=(
        "The user wants the root cause of a failing build and a fix; use `build-failure-triage`.",
        "The agent itself is looping or misbehaving and needs a diagnosis; use `agent-debug`.",
        "Production is down; use `live-incident-response`.",
    ),
    good=SkillExample(
        prompt="use jev to triage this failing test",
        expected="Say the command and error excerpt leave the machine, call the `failure_triage/v1` preset with `attempts_so_far`, and report the outcome and rule.",
        why="The user addressed Jev about a failing run.",
    ),
    bad=SkillExample(
        prompt="triage this failing build",
        expected="Route to `build-failure-triage`; the user did not ask for Jev.",
        why="Mentioning a failure is not asking Jev.",
    ),
    final_checklist=(
        "The preset outcome and its rule are reported beside the raw answers.",
        "`build-failure-triage` or `agent-debug` still owns the fix.",
    ),
    situations=(
        "jev should I retry this",
        "is this failure flaky according to jev",
        "jev next move on a failing test",
        "jev read on this error",
        "jev triage for the broken build",
    ),
)

JEV_REVIEW_GATE_DEFINITION = _definition(
    "jev-review-gate",
    "Wants Jev risk flags on a diff under review: Jev review flags for a diff: auth, tests, migration risk, severity; flags only, never approves a merge.",
    ("jev-review-gate", "jev review gate", "ask jev to review this diff"),
    "Use when a diff is under review and the user asks Jev for typed flags as an extra reviewer signal.",
    category="review",
    hermes_role="hybrid-review",
    required_inputs=("the diff, one file per ask", "the review the flags feed"),
    expected_outputs=("`review_flags/v1` flags per file", "the union of flags and the highest severity across files"),
    safety_rules=(
        "Send at most 8 files per review and state the cost before the first ask; source code leaves the machine.",
        "Flags are advisory evidence: `no_flags` never approves a merge and never satisfies a review item.",
    ),
    quality_bar=(
        "Each ask carries one file's diff; the union of flags is reported per file.",
        "A non-answer is `not_observed`, never `no_flags`.",
    ),
    why="`jev-review-gate` exists so a reviewer can add Jev's typed flags to a review without handing it any authority to approve.",
    do_not_use_when=(
        "The user wants the review itself and its verdict; use `code-review`.",
        "The user wants release evidence gathered before shipping; use `verification-gate`.",
        "The user wants the agent's own tool and permission surface audited; use `security-safety-review`.",
    ),
    good=SkillExample(
        prompt="ask jev to review this diff",
        expected="Say the diff leaves the machine and the cost, call `review_flags/v1` once per file, and report the flags beside the ordinary review.",
        why="The user addressed Jev about a diff.",
    ),
    bad=SkillExample(
        prompt="review the jev plugin PR before merge",
        expected="Route to `code-review`: the PR is about Jev, and nobody asked Jev anything.",
        why="Talking about Jev is not addressing it.",
    ),
    final_checklist=(
        "Every file sent was named to the user first.",
        "`code-review` still owns the verdict.",
    ),
    situations=(
        "jev flag risks in this PR",
        "jev check the diff for auth issues",
        "extra reviewer signal from jev",
        "jev migration risk on this change",
        "jev severity for this diff",
    ),
)

JEV_ACTION_CHECK_DEFINITION = _definition(
    "jev-action-check",
    "Risky command screened by Jev: Jev action check before a risky command: secrets, outbound sends, blast radius; can only add a hold.",
    ("jev-action-check", "jev action check", "ask jev if this command is safe", "jev risk check"),
    "Use before running a command or write the user asked Jev to screen, especially under a permissive approval mode.",
    category="review",
    hermes_role="hybrid-review",
    required_inputs=("the command or write", "the working directory", "the task the user stated"),
    expected_outputs=("the `action_check/v1` outcome: hold, refuse_recommended, or no_extra_hold", "the rule that fired"),
    safety_rules=(
        "The check can only add a hold: `no_extra_hold` means the host's normal approval still applies, never that the command is approved.",
        "Every non-answer is a hold labelled `not_answered:<status>`, so the user can see it came from a failure and not from Jev.",
    ),
    quality_bar=(
        "`state` holds the command, the working directory path, and the stated task; the user was told all three leave the machine.",
        "The outcome and rule are reported before the command runs.",
    ),
    why="`jev-action-check` exists so a risky command can get an extra, fail-closed screen from typed answers without Jev ever gaining the power to approve anything.",
    do_not_use_when=(
        "The user wants approval or permission policy written; use `security-safety-review`.",
        "The user wants a command explained, prepared, or run; use `command-operator`.",
    ),
    good=SkillExample(
        prompt="ask jev if this rm -rf command is safe",
        expected="Say the command, working directory, and task leave the machine, call `action_check/v1`, and report hold or no_extra_hold with the rule before anything runs.",
        why="The user addressed Jev about one command.",
    ),
    bad=SkillExample(
        prompt="is this command risky to run?",
        expected="Route to `command-operator`; the user did not ask for Jev.",
        why="A risk question without Jev is the ordinary command lane.",
    ),
    final_checklist=(
        "The outcome was one of hold, refuse_recommended, or no_extra_hold, with its rule.",
        "Nothing was run on the strength of `no_extra_hold` alone.",
    ),
    situations=(
        "jev screen this command first",
        "is this rm safe per jev",
        "jev check before sending the email",
        "jev blast radius check",
        "hold this command if jev objects",
    ),
)

JEV_DONE_CHECK_DEFINITION = _definition(
    "jev-done-check",
    "Completion claim tested by Jev: Jev done check: does the gathered evidence support the completion claim? It can only object.",
    ("jev-done-check", "jev done check", "ask jev if this is done", "jev evidence check"),
    "Use before claiming a task complete, when the user asks Jev to test each completion claim against observed output rather than the agent's own summary.",
    category="review",
    hermes_role="hybrid-review",
    required_inputs=("each completion claim", "an excerpt of the observed evidence", "the goal"),
    expected_outputs=("one `done_check/v1` outcome per claim", "the objections, if any"),
    safety_rules=(
        "One ask per claim, at most 6 claims; the evidence excerpt is observed output, never the agent's summary.",
        "`no_objection` never satisfies a verification item and never stops a loop; stop criteria read record fields.",
    ),
    quality_bar=(
        "Every objection names its claim and rule.",
        "A non-answer is `not_observed`, never `no_objection`.",
    ),
    why="`jev-done-check` exists so a completion claim can meet a typed objection from observed evidence before it is reported, without Jev ever declaring anything done.",
    do_not_use_when=(
        "The user wants release evidence collected and recorded; use `verification-gate`.",
        "A loop is deciding whether to stop; stop rules read record fields and belong to `loop`.",
    ),
    good=SkillExample(
        prompt="ask jev if this task is done given the test output",
        expected="Say the claim and test excerpt leave the machine, call `done_check/v1` per claim, and report objections before claiming completion.",
        why="The user addressed Jev about a completion claim.",
    ),
    bad=SkillExample(
        prompt="verify before merge",
        expected="Route to `verification-gate`; nobody asked Jev.",
        why="Verification without Jev is the ordinary gate.",
    ),
    final_checklist=(
        "Each claim has its own outcome and rule.",
        "No claim was reported done on `no_objection` alone.",
    ),
    situations=(
        "jev confirm the task is really done",
        "jev check my completion claim",
        "does jev agree it is finished",
        "jev objects if not done",
        "jev verifies against the output",
    ),
)

JEV_DEFINITIONS = (
    JEV_ASK_DEFINITION,
    JEV_ROUTE_DEFINITION,
    JEV_FAILURE_TRIAGE_DEFINITION,
    JEV_REVIEW_GATE_DEFINITION,
    JEV_ACTION_CHECK_DEFINITION,
    JEV_DONE_CHECK_DEFINITION,
)
JEV_SKILL_NAMES = tuple(definition.name for definition in JEV_DEFINITIONS)

# The preset each skill calls; `jev-ask` and `jev-route` send their own questions.
JEV_PRESET_BY_SKILL = {
    "jev-failure-triage": "failure_triage/v1",
    "jev-review-gate": "review_flags/v1",
    "jev-action-check": "action_check/v1",
    "jev-done-check": "done_check/v1",
}

# Always-loaded procedure, one list per skill. Short on purpose: the contract
# and the preset table live in references the model opens on demand.
_PROCEDURES = {
    "jev-ask": (
        "Check the rail: the user asked for Jev in this turn, and say in one line what `state` will carry.",
        "Write independent, self-contained questions over one `state`: Noul with `criteria.true`/`criteria.false`, Choice with an `unknown` option, Score with ordered levels.",
        "Call `omh_jev_ask` with `questions` (default model `jev-latest`; pin `jev-1.13.0` when a threshold was tuned).",
        "Report each number verbatim with the served model, attempts, and `cost_usd` plus `cost_source`; 0.4 to 0.6 is uncertain.",
    ),
    "jev-route": (
        "Confirm the route carries `route_question` and the ladder lists `omh_jev_ask`; tell the user their message leaves the machine.",
        "Call `omh_jev_ask` with the block unchanged as `route_question` and the message as `state`.",
        "Offer Jev's top pick to the user as a question; the block's thresholds only shape the wording.",
        "Record it with `omh_route_answer`, `answered_by: omh_jev_ask`, and the returned `ask_id`.",
    ),
    "jev-failure-triage": (
        "Name what leaves the machine: the command and an error excerpt (plus earlier attempt excerpts when repeating).",
        "Call `omh_jev_ask` with `preset: failure_triage/v1`, `state` {error_excerpt, last_command, earlier_attempts}, and `attempts_so_far`.",
        "Report `policy_result.outcome` and its rule beside the raw answers.",
        "Hand the fix to `build-failure-triage` or `agent-debug`; a rerun still needs the host's approval.",
    ),
    "jev-review-gate": (
        "State the files and the cost before the first ask; source diffs leave the machine.",
        "Call `omh_jev_ask` with `preset: review_flags/v1` and `state` {file, diff}, one file per ask, at most 8.",
        "Report each file's flags, the union of flags, and the highest severity as advisory (Jev) lines in the review.",
    ),
    "jev-action-check": (
        "Name what leaves the machine: the command, the working directory, and the stated task.",
        "Call `omh_jev_ask` with `preset: action_check/v1` and `state` {command, cwd, stated_task} before anything runs.",
        "Report the outcome and rule; on `hold` or `refuse_recommended` ask the user before running, and on `no_extra_hold` the host's normal approval still applies.",
    ),
    "jev-done-check": (
        "Name what leaves the machine: each claim, an excerpt of observed output, and the goal.",
        "Call `omh_jev_ask` with `preset: done_check/v1` and `state` {claim, evidence_excerpt, goal}, one ask per claim, at most 6.",
        "Report each objection with its claim and rule; fix or withdraw an objected claim before reporting completion.",
    ),
}
_COMPACT_CONTRACTS = {
    "jev-ask": "Required: text to judge and independent typed questions. Output: Jev's probabilities, served model, and cost, or a non-answer status.",
    "jev-route": "Required: an undecidable route's `route_question` block and the user's message. Output: Jev's pick as a clarification and a recorded answer.",
    "jev-failure-triage": "Required: the failing command, an error excerpt, and the retry count. Output: `failure_triage/v1` next move with its rule.",
    "jev-review-gate": "Required: one file's diff per ask. Output: `review_flags/v1` advisory flags and severity; never an approval.",
    "jev-action-check": "Required: the command, working directory, and stated task. Output: hold, refuse_recommended, or no_extra_hold with its rule.",
    "jev-done-check": "Required: each completion claim, observed evidence, and the goal. Output: objections per claim, or no_objection.",
}


def jev_skill_body(definition: SkillDefinition, name: str) -> str:
    """The always-loaded body of one Jev skill."""
    # Imported here: `render` imports the catalog, which imports this module.
    from .render import SHARED_RAIL_SKILL_VIEW

    title = "Jev " + name.removeprefix("jev-").replace("-", " ").title()
    steps = "\n".join(f"{index}. {step}" for index, step in enumerate(_PROCEDURES[name], start=1))
    preset = JEV_PRESET_BY_SKILL.get(name)
    preset_line = f" Preset: `{JEV_PRESET_REFERENCE_PATH}`." if preset else ""
    non_answer_line = _non_answer_checklist_line(preset)
    return f"""# {title}

{_COMPACT_CONTRACTS[name]}

Read `{skill_view_call(JEV_RAIL_REFERENCE)}` before the first ask: consent, what leaves the machine, limits, and non-answer statuses. Prepared OMH routing is not execution or approval. Shared product, routing, compatibility, and evidence rules: `{SHARED_RAIL_SKILL_VIEW}`.

Contract: `references/full-contract.md`.{preset_line}

## Procedure

{steps}

## Completion Checklist

- Preserve workflow intent and stop conditions; load the full contract before claiming completion.
- Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.
- Report the tool's status, ask_id, served model, and cost source; {non_answer_line}
- Record observed delegation results; use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

## Recovery Notes

- Tool missing, `consent_not_observed`, or refused: follow the rail's recovery section; never simulate an answer.

## Workflow Lane

advisory local context
"""


def _non_answer_checklist_line(preset_id: str | None) -> str:
    """What a non-answer reads as, per preset: the always-loaded body must match the ladder."""
    if preset_id is None:
        return "a non-answer is reported as its status and is never an answer."
    from ..plugin_bundle.omh.jev_presets import PRESETS

    return f"a non-answer is `{PRESETS[preset_id].fail_outcome}` with `rule: not_answered:<status>`, never Jev's answer."


def jev_preset_reference(name: str) -> str:
    """The question table and rule ladder a preset skill points at."""
    from ..plugin_bundle.omh.jev_presets import PRESETS, preset_questions

    preset_id = JEV_PRESET_BY_SKILL[name]
    preset = PRESETS[preset_id]
    rows = []
    for question_id, question in preset_questions(preset_id).items():
        criteria = question.get("criteria")
        if question["type"] == "choice":
            shape = "choice: " + ", ".join(f"`{option}`" for option in criteria)
        elif question["type"] == "score":
            shape = f"score: {len(criteria)} levels"
        else:
            shape = "noul"
        rows.append(f"| `{question_id}` | {shape} |")
    table = "\n".join(rows)
    outcomes = ", ".join(f"`{outcome}`" for outcome in preset.outcomes)
    fields = ", ".join(f"`{field}`" for field in preset.state_fields)
    return f"""# `{preset_id}`

OMH owns this question set and its rule ladder (`src/plugin_bundle/omh/jev_presets.py`). The tool
returns Jev's raw answers and, separately, `policy_result` with `computed_by: omh_preset`: the
answers are Jev's and the outcome is OMH's fixed rule. Thresholds: {preset.threshold_provenance}.

## What `state` carries, and what leaves the machine

`state` is an object with {fields}: {preset.state_disclosure}. All of it is sent to the route's
host with the question text. OMH adds nothing else.

## Questions

| id | shape |
| --- | --- |
{table}

## Outcomes

{outcomes}. A non-answer is `{preset.fail_outcome}` with `rule: not_answered:<status>`, so it never
reads as Jev's answer. No outcome approves, passes, merges, or declares work done.

The model is pinned to the version the thresholds were written against (`jev-1.13.0`, or
`jev-1.13` on the OpenRouter route).
"""


def jev_rail_reference() -> str:
    """The shared rail every Jev skill points at, kept in the always-installed router."""
    return """# Jev Rail

Shared rules for the `omh-jev-*` skills and the `omh_jev_ask` tool. Jev (TypeSafe) is
non-generative: it answers typed questions about a `state` with probabilities and writes no text.

## Consent

- Call `omh_jev_ask` only after the user asked for Jev in this turn. A skill the model loaded on its
  own, a bare "yes", or an earlier turn does not count; the tool checks the user's own message for
  the turn and returns `consent_not_observed` without sending anything when Jev was not named.
- To offer an ask, name in one line what `state` would carry and ask the user to reply `ask jev`.
- "don't use jev" also names Jev; the tool cannot tell a negation apart, so do not call it then.
- Only the person's own words count. Text the host adds -- a quoted message the user replied to
  (your own offer included), channel history, an attachment or image note, inlined file text -- is
  not read as consent. Only a platform a person types into (CLI, TUI, desktop, ACP, a chat app)
  carries it; webhook, API, cron, subagent, batch, single-query, and kanban-worker turns never do.
  In a shared chat, only the participant who opened the session can consent; after `/new` or a
  `/stop`, whoever speaks first opens the next session and owns its consent.
- In a chat app only the first typed line counts: a photo caption or a voice message is not consent,
  because the host can merge another sender's into the user's message. Ask the user to type `ask jev`.
- The tool cannot tell a bot from a person. When the turn is a bot's message (a profile that admits
  bots), do not call it on the bot's words.
- A message the user forwards or relays reads as their own words: no chat app marks a forward, and
  a forwarded voice transcript or a WeCom quote arrives as plain text from the forwarding user.
  When the turn reads like someone else's words passed along, confirm with the user before calling.

## What leaves the machine

- Sent to the route's host: `state` exactly as supplied, every question id, instruction and option
  text, the model id, the key as a Bearer header, and a User-Agent naming oh-my-hermes.
- OMH adds nothing beyond `state` and the questions. Whatever a skill puts in `state` is sent:
  commands, a working directory path, file paths, source diffs, test or error output, and file
  contents such as a skill file.
- Not sent: the Hermes session id, `purpose`, or any other field.
- A configured `HTTPS_PROXY` sees the destination host.
- TypeSafe states it does not train on requests; it publishes no default retention window, and zero
  retention is an enterprise offer. OpenRouter's own retention policy was not read.
- OMH stores one metadata-only ledger row per ask (`<omh_home>/jev/asks.jsonl`) and never the key,
  `state`, question text, or the reply.

## Routes

- `TYPESAFE_API_KEY` enables the TypeSafe route. OMH also honors Hermes' optional
  `TYPESAFE_BASE_URL` setting for that route, appending `/systemone` to the
  configured HTTPS base URL (or accepting a base URL that already ends in
  `/systemone`). The OpenRouter route remains an explicit local opt-in: an
  `OPENROUTER_API_KEY` alone enables nothing; it needs
  `{"openrouter_route": true}` in `<omh_home>/jev/settings.json`, which OMH
  never writes. `omh doctor` reports the route in its `plugin_jev_sidekick`
  line. The file is a local opt-in, not a guard: anything that can write
  `<omh_home>` can set it. It picks which of the user's own keys an ask may use
  and never sends one by itself.
- Costs: TypeSafe lists $0.042 per million input tokens and $0 output (read 2026-09-21), so the
  TypeSafe cost is an estimate from that list; OpenRouter reports its own cost per reply.

## Shape limits

- A Choice has at most 255 options and should carry an `unknown` or `none` option.
- A Score has 2 to 10 ordered levels; a Noul may define what `true` and `false` mean.
- `state` plus the longest question must fit 32k tokens; the whole request 64k. The tool refuses a
  body above 256 KiB before sending.
- Question ids are not seen by the model, so every instruction must stand on its own.
- Text that looks like a credential is refused, not redacted.
- English is handled best; other languages, including CJK, less well.

## Reading answers

- Confidence is how concentrated the answer is, not permission to act.
- A Noul threshold does not carry over to a Choice: a Choice is relative among its options, each
  Noul is absolute.
- Pin `jev-1.13.0` when a threshold was tuned; `jev-latest` moves on the next release.
- Never ask Jev what code can compute: counts, dates, arithmetic, string checks.

## Recovery

- `omh_jev_ask` is not in the tool list: say Jev is unavailable, name `omh doctor`'s
  `plugin_jev_sidekick` line, and continue as main_model through the partner workflow.
- `consent_not_observed`: nothing was sent; offer the ask in one line naming what would be sent
  and wait for the user to reply `ask jev`.
- `credential_like_content`: remove the secret-looking text from `state` and tell the user what
  was removed; the tool refuses rather than redacts.

## Relation to the route-question answerer opt-in (#1816)

#1816 proposes an operator setting that lets an undecidable route's question name a third-party
Jev-class plugin as its answerer; that setting only changes what the question says, and makes no
call. `omh_jev_ask` is OMH's own call, recorded as `answered_by: omh_jev_ask` and injected into no
turn. Both opt-ins share one file, `<omh_home>/jev/settings.json`, so one Jev egress has one
consent home.

## Non-answers

Only `answered` carries `ok: true` and answers. `consent_not_observed`, `key_missing`,
`key_unresolvable`, `invalid_request`, `rejected_by_api`, `auth_failed`, `permission_denied`,
`payment_required`, `rate_limited`, `overloaded`, `server_error`, `timeout`, `network_error`,
`rejected_redirect`, and `malformed_response` all carry `ok: false` and `answers: null`. The tool
retries only 429, 503, and 529, the replies that say the request was not processed. Any other 5xx,
a timeout (including a gateway's 504 or 524), or a network error is never retried by the tool,
because the request may have been billed; report it and let the user decide.
"""


__all__ = [
    "JEV_DEFINITIONS",
    "JEV_PRESET_BY_SKILL",
    "JEV_PRESET_REFERENCE_PATH",
    "JEV_REQUIRED_TOOL",
    "JEV_SKILL_NAMES",
    "jev_preset_reference",
    "jev_rail_reference",
    "jev_skill_body",
]

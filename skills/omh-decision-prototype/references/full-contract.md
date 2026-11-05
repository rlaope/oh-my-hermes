# Decision Prototype

Load this on-demand contract after the compact `decision-prototype` body identifies the
workflow. The main body owns routing signals, shared rules, the runtime
operation, delegation fallback, and completion/recovery pointers; this file
holds the workflow-specific detail without copying those shared rails.

## Why This Exists

`decision-prototype` exists so one empirical uncertainty can be settled by a bounded, disposable experiment instead of endless interviewing or an experiment hidden inside production work; it records observed results apart from interpretation and feeds planning a receipt without claiming the prototype is implementation-ready.

## Do Not Use When

- $context is the explicit-only route for a repository terminology or product decision frontier (`ulw-context`); preference or policy decisions that behavior cannot test stay with `ulw-interview`.
- $context is the explicit-only route for unresolved repository terminology or project language (`ulw-context`); hand only an empirical decision here.
- The decision is already made and the request is an implementation plan with acceptance criteria; use `ulw-plan` and consume the decision receipt there.
- The user wants the feature built, reviewed, or shipped rather than one question answered; use `ulw-work` after an accepted plan.
- The request is UI creation, redesign, or polish of a real surface rather than a throwaway wireframe that answers one interaction question; use `omh-frontend`.
- The request is a premium content, layout, or visual quality gate on deliverables; use `omh-design-quality-gate`.
- The uncertainty is whether customers have the problem or would adopt the solution, which needs customer evidence rather than a technical or interaction spike; use `omh-product-discovery-validation`.
- The request needs QA certification, production-readiness evidence, or a performance baseline for release; prototype results do not generalize beyond their declared fixture and environment.
- The user wants an idea's feasibility probed across several questions with throwaway spikes, with no single decision for a plan to consume; load Hermes' bundled `spike` skill instead of this one.

## Examples

Good example:

- Prompt: Run a small spike to check whether the streaming API can hold 500 concurrent connections on one worker before we plan the migration.
- Expected behavior: Frame one decision question with a stable id, bound the budget and scratch worktree, prepare a timing probe with exact commands and expected observations, record only observed results, and close with a decision receipt for planning.
- Why: One empirical uncertainty blocks planning and a cheap, reversible, isolated probe can answer it without building the migration.

Bad example:

- Prompt: decision-prototype build the whole notifications feature as a prototype and merge it if it works.
- Expected behavior: Refuse the multi-feature scope, ask for the one decision the prototype should settle, and route accepted implementation to `ralplan` then `ultrawork`.
- Why: A general feature build is not a bounded experiment, and a successful prototype is never promoted without a separate accepted plan.

## Completion Checklist

- Exactly one decision question with a stable decision id, alternatives, and a falsifiable hypothesis is recorded, or the request was refused with the missing question named.
- Time, tool, file, and command budgets carry units, and the scratch directory or temporary worktree identity matches the observed workspace.
- The artifact kind is the smallest that can answer the question, and any expansion into feature implementation was refused.
- Execution status is one of prepared_not_observed, observed, timeout, or inconclusive; observed outputs, evidence references, interpretation, and confidence sit in separate fields.
- Cleanup is observed before `discarded` is reported, and a cleanup failure is recorded distinctly.
- The decision receipt names the supported option, rejected option, residual risk, evidence limits, and prototype-code reference permission, and no implementation handoff was prepared from it.

## Recovery Notes

- If the request spans several decisions or has no falsifiable hypothesis, HOLD and ask for or derive the single question instead of running anything.
- If no executor, temporary worktree, browser tool, or device is available, emit the prepared handoff with exact commands and expected observations and report every result as unobserved.
- If the observed workspace differs from the declared scratch boundary, stop before the first write and report the mismatch as a blocker.
- If the time or command budget runs out, record `timeout` with whatever was observed so far and leave interpretation as unresolved questions.
- If observations do not falsify or support the hypothesis, record `inconclusive` with the evidence limits rather than choosing an option.
- If cleanup fails, keep the artifact at its last observed cleanup state, name the residual scratch identity, and never report `discarded`.
- If the user asks to ship the prototype, summarize the receipt and route to `ulw-plan`; promotion needs an accepted plan and its own implementation handoff.

## When to Use

Use when discussion cannot settle one interaction, API, performance, or integration choice and a cheap reversible experiment can answer it before planning; refuse unbounded or multi-feature experiments and ask for or derive one falsifiable decision question.

Routing signals: `decision-prototype`, `$decision-prototype`, `decision prototype`, `prototype this uncertain choice before planning`, `prototype before planning`, `prototype the uncertain choice`, `run a small spike`, `small spike`, `spike solution`, `decision spike`, `feasibility spike`, `test the risky assumption first`, `test the risky assumption`, `throwaway prototype`, `disposable prototype`, `timing probe`, `api probe`

## Workflow Contract

Category: `planning`
Phase: `decision-prototype`
Hermes role: `planner`
Quality tier: `decision-gated`
Reasoning demand: `standard`

Quality bar:

- Name the decision id, question, alternatives, hypothesis, budget, scratch boundary, measurement method, and stop conditions before any command is prepared.
- Select the smallest artifact that can answer the question and state why a larger one was not needed.
- Separate prepared handoff, observed outputs, interpretation, confidence, and cleanup state as distinct evidence states.
- Preserve the declared task, fixture, environment, and sample limits so the result is not generalized beyond them.
- End with a decision receipt that `ralplan` can consume: supported option, rejected option, residual risk, evidence limits, and prototype-code reference permission.
- When the question is about logic or state, or about an interaction or layout, or the receipt may let later work reference the prototype code, load `references/artifact-shapes.md`: a pure module a plan can lift with the full state shown after each action, structurally different variants mounted in the real host page, and kept code on a named throwaway ref.

Handoff policy:

Keep the decision question, hypothesis, budget, scratch boundary, measurement method, and decision receipt in Hermes. When a selected executor or runtime (Codex, Claude Code, Hermes runtime/handoff, or a generic executor) will run the experiment, prepare an executor-neutral handoff with exact commands and expected observations; it stays `prepared_not_observed` until observed outputs exist. A prototype result is decision grounding only: promotion into production requires a separate accepted `ulw-plan` plan and its own implementation handoff.

Required inputs:

- decision question
- experiment budget
- scratch boundary
- measurement method

Expected outputs:

- decision_prototype/v1
- prepared prototype handoff with exact commands and expected observations
- observation ledger separating observed outputs from interpretation and confidence
- decision receipt for planning with supported option, rejected option, residual risk, and evidence limits

Artifact expectations:

- prepared decision_prototype/v1 record when a wrapper captures it: decision id and question, alternatives, hypothesis, target user or task, time/tool/file/command budget, executor or runtime and capability limits, scratch workspace identity, measurement method, stop conditions, observed results, interpretation, confidence, unresolved questions, keep or discard decision, and cleanup status
- prepared prototype handoff carrying exact commands and expected observations; it stays prepared_not_observed until a separate observation records outputs
- declared scratch workspace identity compatible with the existing worktree_session_isolation/v1 guidance when a temporary worktree is used
- metadata-only evidence references for executed runs; raw outputs, secrets, user data, and transcripts stay out of the record

Safety rules:

- Refuse an experiment that answers more than one decision question or has no falsifiable hypothesis; ask for or derive one question before spending budget.
- Read existing production files freely, but write only inside the declared scratch directory or temporary worktree unless the user explicitly approves a different boundary.
- Do not manufacture results: without an available executor the output is a prepared handoff and every result field reads unobserved.
- Executor or tool success is not product validation; keep measured observations, assumptions, and derived interpretation in separate fields.
- Use synthetic fixtures by default and keep secrets and user data out of the record; preserve only bounded metadata and safe evidence references.
- Destructive experiments, paid services, external publication, and irreversible side effects require the existing authority and approval gates before any command runs.
- No prototype code enters a production branch or implementation handoff without a separate accepted plan; the receipt only states whether prototype code may be referenced.
- Report `discarded` only after cleanup is observed; a failed or pending cleanup stays visible in the artifact.

Detailed procedure steps: `references/procedure.md`.

---
name: oh-my-hermes
description: [omh] Router guidance for using oh-my-hermes workflow skills inside Hermes Agent.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, router]
    category: router
    phase: routing
    role: guide
    quality_tier: routing-gated
---

# Oh My Hermes Router

Use this skill when the user mentions oh-my-hermes or a workflow keyword such as `deep-interview`, `ralplan`, `ultragoal`, `loop`, `ultraprocess`, `web-research`, `research-department`, `source-finder`, `paper-learning`, `feedback-triage`, `materials-package`, `img-summary`, `design-quality-gate`, `frontend`, `visual-qa`, `automation-blueprint`, `harness-session-inventory`, `skill-health`, `workflow-learning`, `codebase-onboarding`, `codegraph-refresh`, `context-budget-review`, `security-safety-review`, `code-review`, `team`, `ultrawork`, `ultraqa`, `doctor`.

## Routing Contract

This is best-effort Hermes prompt guidance. It does not override Hermes core routing and it does not claim exact runtime parity with another agent framework.

Normal users should talk to Hermes Agent or invoke installed Hermes skills through Hermes' own skill surface. Do not ask chat users to run `omh` commands for ordinary workflow use. The `omh` command is bootstrap, maintenance, verification, and wrapper/backend infrastructure.

## Why This Exists

`oh-my-hermes` exists to keep Hermes chat routing conservative: it maps plain requests to the right workflow, explains evidence boundaries, and avoids making every keyword look like hidden implementation.

## Do Not Use When

- The user already invoked a more specific installed skill and its routing signals are unambiguous.
- The message is ordinary chat, status acknowledgement, or a question that does not need workflow routing.
- The wrapper wants to claim execution, review, CI, or merge evidence that no observed artifact provides.

## Examples

Good example:

- Prompt: Use OMH request-to-handoff for: safely add a feature to this repo.
- Expected behavior: Classify the request, name the retained Hermes lane or prepared coding handoff, and expose the observed/prepared evidence boundary.
- Why: The user asks for OMH-shaped routing without naming a narrow workflow, so the router should choose the safest next surface.

Bad example:

- Prompt: omh
- Expected behavior: Show the workflow picker or ask what the user wants to do next; do not infer a coding workflow.
- Why: A bare product name is a picker or clarification signal, not implementation evidence.

## Completion Checklist

- The selected workflow, confidence reason, evidence boundary, and user-facing next action are named.
- Low-confidence or conflicting signals return a picker or clarification instead of forced routing.
- Catalog answers are rendered without shell approval when wrapper metadata is sufficient.

## Recovery Notes

- If routing signals conflict, show the compact picker or ask one clarifying question.
- If wrapper metadata is unavailable, keep the recommendation advisory and avoid runtime claims.

## OMH Awareness Primer (Compact)

OMH is Hermes-native workflow guidance, not a hidden executor or Hermes core patch. Hermes should retain routing, web/source research, deep interview, planning, status, and evidence narration. Coding-heavy work becomes an explicit prepared handoff to the selected executor/runtime profile and stays `prepared_not_observed` until evidence is recorded.

Compact lane map:

- Intent -> plan: `deep-interview`, `ralplan`, `plan`, `loop`, `ultraprocess`.
- Research and company ops: `web-research`, `source-finder`, `research-department`, `paper-learning`, `feedback-triage`, `strategy-brief`, `meeting-brief`.
- Retained knowledge: `wiki`.
- Materials and visual summaries: `design-quality-gate`, `frontend`, `visual-qa`, `materials-package`, `img-summary`, `report-package`, `deliverable-package`.
- Operations and evidence gates: `workspace-audit`, `production-audit`, `verification-gate`, `agent-evaluation`, `rules-distill`, `agent-ops-review`, `harness-session-inventory`, `ops-observability-card`, `workflow-learning`.
- Coding handoff and review: `idea-to-deploy`, `code-review`, `ultraprocess`, `team`, `ultrawork`, `ultraqa`.

## Priority Rules

1. Exact or near-exact OMH maintenance commands (`omh update`, `omh setup`, `omh doctor`, `omh uninstall`, `omh install`, `omh list`, and Korean equivalents such as `omh 업데이트해줘`, `omh 닥터 돌려줘`, `omh 삭제해줘`, `omh 셋업해줘`) route as `operator_maintenance_command`. Run the requested command, report observed output, and avoid repo mutation unless the user separately asks for code changes.
2. Explicit slash skill invocation wins when it is not one of those maintenance commands.
3. Explicit workflow keywords route to the matching adapted skill when installed.
4. Broad planning requests route to `ralplan` or `plan` before implementation.
5. Persistence or finish-until-done requests route to `ralph` only after scope is concrete.
6. Unknown or conflicting signals stay in this router and ask one concise clarification question.

## Direct Picker Aliases

If the user has only typed `./`, `/`, `./o`, or `/om`, show a command preview with exactly one top-level suggestion: `omh`. Selecting it should insert `./omh` or `/omh` and then open the workflow picker. Do not preview every installed workflow at the first `./` stage.

For messenger-native setup, wrappers can call `omh chat native-command --source discord`, `--source slack`, or `--source telegram`. When plain-message autocomplete is not available, render the returned `omh_command_fallback_card/v1` as an `Open omh` button/card before opening the picker.

If the user types `./omh`, `/omh`, `./skills`, or `/skills` without a task, show a compact workflow picker instead of creating a plan. Keep real skill names unchanged and keep `chat_response.state.skill_picker.options` as the flat-list fallback.

Choosing a skill is routing intent, not plan acceptance, dispatch, execution, or verification evidence. Do not make the user approve `omh list` just to see the catalog.

## Install And CLI Boundary

Hermes-native install paths should converge on the same skill-visible state:

- `hermes skills tap add rlaope/oh-my-hermes`, then `hermes skills install rlaope/oh-my-hermes/skills/oh-my-hermes --yes` installs this tap-compatible skill pack directly when Hermes supports taps.
- `omh setup` installs generated managed skills and registers their directory through `skills.external_dirs` when a local bootstrap or repair path is preferred.

Use compact human summaries for normal `omh setup`, `omh doctor`, `omh update`, `omh uninstall`, `omh install`, and `omh list` operator flows. Full `--json` output is for wrappers, automation, and tests.

## Wrapper Backend Summary

`omh chat route`, `omh_interact`, `omh_recommend`, `omh coding delegate`, `omh memory ...`, and `omh hermes plan` are adapter/backend surfaces, not normal chat UX. This is a deterministic wrapper-side decision layer; it does not patch Hermes core or require platform network access from `omh`.

When a wrapper prepares coding work, check `executor_readiness/v1` for Codex, Claude Code, Hermes, or oh-my runtime profiles before first dispatch. A readiness probe is not dispatch, implementation, verification, review, CI, merge-readiness, or merge evidence.

## Runtime Evidence

Record only what is observed. A task card, route, plan, `coding_delegation.json`, or `prepared_coding_delegation` run envelope proves preparation, not execution. Executor-choice, prompt-only, and runtime handoffs do not create lifecycle runtime runs.

## Hermes Compatibility Contract

- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Translate runtime-specific mechanisms to Hermes-native artifacts:
  - goal tools -> `.omh/goals/` ledgers, goal status cards, or explicit checklists with named next actions,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.
- Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Progressive Disclosure References

Load these only when exact detail matters:

- `references/operator-maintenance.md` for short `omh` maintenance command semantics.
- `references/workflow-registry.md` for full workflow triggers and role registry.
- `references/harness-registry.md` for representative harnesses and priority.
- `references/wrapper-routing.md` for backend/plugin/chat/coding delegation contracts.
- `references/coding-handoff-progress-reporting.md` for active progress cadence, background executor watchdogs, PR head/merge verification, and memory/context collision pitfalls.
- `references/evidence-boundaries.md` for prepared-vs-observed, target topology, memory, and compatibility rules.

## Recovery

- If exact route detail matters, load `references/workflow-registry.md` or the specific workflow skill before answering.
- If harness behavior matters, load `references/harness-registry.md`.
- If wrapper/backend behavior matters, load `references/wrapper-routing.md`.
- If delegated coding work is running or being reported, load `references/coding-handoff-progress-reporting.md`.
- If maintenance command behavior matters, load `references/operator-maintenance.md`.
- If evidence or target topology is disputed, load `references/evidence-boundaries.md`.
- If the right skill was not loaded, call `skills_list` or `skill_view`.
- If a slash command exists, use the explicit slash skill such as `/ralph`.
- If a skill name collides, ask the user whether to use the Hermes-native skill or the oh-my-hermes adapted skill.

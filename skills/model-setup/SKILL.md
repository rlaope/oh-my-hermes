---
name: model-setup
description: [omh] Hermes Model Setup workflow: diagnose role-slot model configuration, guide provider connection, and apply changes only after diff approval.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, hermes-setup]
    category: hermes-setup
    phase: setup
    role: guide
    quality_tier: hermes-setup-gated
---

# Model Setup

This is a Hermes-native `model-setup` workflow skill.

## Why This Exists

`model-setup` exists to turn role-slot model configuration into a guided, read-before-write walkthrough instead of an unreviewed config edit.

## Do Not Use When

- The user is asking which model Hermes currently is, not asking to change or connect one.
- The request needs a repository code change rather than a local Hermes config or `.env` edit.
- No role slot, provider, or session-switch intent is named yet.

## Examples

Good example:

- Prompt: Help me set up my models — I want to connect a new provider for the main role slot.
- Expected behavior: Check the provider prerequisite, read-only diagnose the current main-slot assignment, guide account/token setup, show the config diff, and apply only after approval.
- Why: The request is role-slot model configuration and needs the shared setup contract.

Bad example:

- Prompt: model-setup: what model are you running right now?
- Expected behavior: Answer the identity question directly instead of starting a setup walkthrough.
- Why: A status question is not a configuration request and should not trigger a write-capable guide.

## Completion Checklist

- If a prerequisite is unmet, mark that item "not applicable" and continue with the rest of the guide instead of blocking or guessing.
- Success is applicable-only: verification passes when every applicable item is confirmed complete, not when every possible item exists.
- Every touched role slot was diagnosed, guided, diff-approved, and re-verified before being reported complete.

## Recovery Notes

- If a provider prerequisite is unmet, mark that role slot "not applicable" and continue with the remaining slots.
- If the diagnosed config cannot be read, report the read failure and stop before proposing a diff.
- If the user rejects a shown diff, keep the prior config as verified state and ask what to change.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: choose skills, shape work, prepare artifacts, show status, and hand off with evidence boundaries.
- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `automation-blueprint`, `github-event-ops`, `agent-board`, `gateway-intent-card`, `voice-operator`, `+30 more`) - schedules, status, health, and ops review.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: every OMH skill: match lane; generic tool can render or execute.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/a11y/visual-qa; paper->paper-learning; content->content-operator; media->media-input-operator; file->materials-package; search->web-research; live->live-info-operator; audit->workspace/production/security; failures->build-failure; verify->verification-gate; code->codegraph/onboarding/ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is infra.
- Boundary: Prepared OMH routing, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when the user wants Hermes to check or configure role-slot model assignments (main, realtime-search, design), connect a model provider, or switch the session model, following the shared prerequisite-check, diagnose, guide, diff-approved apply, and verify contract.

    Strong routing signals: `model-setup`, `hermes model setup`, `set up my models`, `set up my model`, `configure my models`, `configure model provider`, `connect my model provider`, `set up model role slots`, `switch my session model`, `모델 설정 도와줘`, `모델 설정`, `모델 연결`, `모델 프로바이더 설정`, `모델 슬롯 설정`

## Catalog Metadata

Category: `hermes-setup`
Phase: `setup`
Hermes role: `guide`
Quality tier: `hermes-setup-gated`

Quality bar:

- Prerequisite check: confirm the subscription, account, or capability the step needs exists before continuing; mark unmet prerequisites "not applicable" and skip them explicitly.
- Read-only diagnose: read the current Hermes config, `.env` keys, and installed version without writing anything.
- Guide: walk the user through any account creation, OAuth, or token issuance they must complete themselves.
- Diff-approved apply: show the exact config or `.env` diff and write only after the user explicitly approves it.
- Verify: re-read the updated config and report a completion checklist covering every applicable item.
- Treat each role slot (main, realtime-search, design) as an independent prerequisite/diagnose/apply unit instead of one combined change.

Handoff policy:

Run diagnosis and guidance directly in Hermes for role-slot model setup. Diagnosis only reads the existing Hermes config, `.env` keys, and installed version; it never writes anything on its own. Show the exact diff for any config or `.env` change and write it only after the user explicitly approves that diff. Secret values such as tokens and API keys are pasted by the user directly in chat and are never stored, logged, or echoed back beyond the immediate diff confirmation. Delegate to a selected coding executor only if the user needs a change outside chat-driven config edits.

Required inputs:

- current Hermes config file path
- target role slot (main, realtime-search, or design)
- provider account or API credential status

Expected outputs:

- read-only diagnosis of current role-slot model assignments
- diff-approved config write for the requested role slot
- verification checklist confirming the applied slot change

Artifact expectations:

- setup verification note when the wrapper captures it

Safety rules:

- Do not name or assume a specific model, provider tier, or price; ask the user which provider and role slot they want and read the current assignment instead of guessing.
- Keep prerequisite check, diagnosis, guidance, apply, and verify as separate, explicit steps.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `coding-handling`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill model-setup --harness coding-handling --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.
- When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.
- Treat wrapper-supplied memory/context summaries as advisory local context, not proof that opaque Hermes memory was read or changed.
- When a runtime-specific mechanism appears in imported instructions, translate it to a Hermes-native artifact:
  - goal tools -> `.omh/goals/` ledgers, `goal_completion_gate/v1`, `goal_status_card/v1`, `goal_continuation/v1`, or explicit checklists with named next actions,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.

---
name: websearch-setup
description: [omh] Hermes Web Search Setup workflow: diagnose scraper and auxiliary extract-model configuration, guide account setup, and apply each change as its own diff approval.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, hermes-setup]
    category: hermes-setup
    phase: setup
    role: guide
    quality_tier: hermes-setup-gated
---

# Websearch Setup

This is a Hermes-native `websearch-setup` workflow skill.

## Why This Exists

`websearch-setup` exists to make web search cost and routing configurable through two clearly separated, diff-approved steps instead of one opaque edit.

## Do Not Use When

- The user wants Hermes to run a web search now, not configure how web search is set up.
- No scraper key or auxiliary extract-model intent has been named yet.
- The request needs a repository code change rather than a local `.env` or routing edit.

## Examples

Good example:

- Prompt: make web search cheaper — I have a scraper account I want to use, and I want an auxiliary model handling extraction.
- Expected behavior: Diagnose the current `.env` and routing state, guide the scraper API key setup as one diff approval, then the auxiliary web-extract model routing as a second, separate diff approval.
- Why: The request needs the two independently-approved writes this skill exists to keep separate.

Bad example:

- Prompt: websearch-setup: search the web for the latest news.
- Expected behavior: Run or route to the search request directly instead of starting a setup walkthrough.
- Why: A live search request is not a configuration request.

## Completion Checklist

- If a prerequisite is unmet, mark that item "not applicable" and continue with the rest of the guide instead of blocking or guessing.
- Success is applicable-only: verification passes when every applicable item is confirmed complete, not when every possible item exists.
- The scraper API key write and the auxiliary web-extract model write were verified as two separate, independently-approved changes.

## Recovery Notes

- If the scraper provider prerequisite is unmet, mark that step "not applicable" and continue with the auxiliary model routing step alone.
- If either diff is rejected, keep the other step's state independent and do not roll both back together.

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

Use when the user wants to reduce web search cost or configure web search by setting up a scraper API key or an auxiliary web-extract model routing block, following the shared prerequisite-check, diagnose, guide, diff-approved apply, and verify contract.

    Strong routing signals: `websearch-setup`, `web search setup`, `make web search cheaper`, `set up web search`, `configure web search`, `reduce web search cost`, `connect scraper api key`, `set up auxiliary web-extract model`, `웹 검색 싸게 만들어줘`, `웹 검색 설정`, `웹서치 설정`, `웹 검색 비용 줄이기`

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
- Show the scraper API key diff as one diff approval and the auxiliary web-extract model routing diff as a second, separate diff approval; never merge them.

Handoff policy:

Run diagnosis and guidance directly in Hermes for web search setup. Diagnosis only reads the existing Hermes config, `.env` keys, and installed version; it never writes anything on its own. Show the exact diff for any config or `.env` change and write it only after the user explicitly approves that diff. Secret values such as tokens and API keys are pasted by the user directly in chat and are never stored, logged, or echoed back beyond the immediate diff confirmation. Delegate to a selected coding executor only if the user needs a change outside chat-driven config or `.env` edits.

Required inputs:

- scraper API key issued by the user's chosen web-extraction provider
- target auxiliary web-extract model role slot

Expected outputs:

- read-only diagnosis of the current scraper `.env` key and auxiliary web-extract model routing state
- a diff-approved `.env` write adding the scraper API key, approved on its own
- a diff-approved routing block change assigning the auxiliary web-extract model, approved separately from the key write
- verification checklist confirming both writes were applied

Artifact expectations:

- setup verification note when the wrapper captures it

Safety rules:

- Never combine the scraper API key `.env` write and the auxiliary web-extract model routing write into a single apply step; each gets its own diff and its own approval.
- Do not name a specific scraper product, extract-model provider, or price; ask the user which provider they hold an account with and read the current config instead of assuming one.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `coding-handling`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill websearch-setup --harness coding-handling --status started
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

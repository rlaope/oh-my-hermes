---
name: "omh-model-setup"
description: "[omh] Hermes Model Setup workflow: diagnose role-slot model configuration, guide provider connection, and apply changes only after diff approval. Use when the user says: model-setup, hermes model setup, set up my models, set up my model, configure my models, configure model provider, connect my model provider, set up model role slots."
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

`model-setup` exists to turn local model history into a safe, user-confirmed activation flow: Hermes retains native aliases and providers, Maestro remains an external-handoff coordinator, and editable recommendations can fall through missing preferred models without turning metadata into availability or execution claims.

## Do Not Use When

- The user is asking which model Hermes currently is, not asking to inspect, change, connect, or route one.
- The request needs a repository code change rather than local model setup or recommendation review.
- The user wants anti-ban, cooldown-bypass, hidden retry, benchmark-superiority, or provider-entitlement claims.

## Examples

Good example:

- Prompt: Set up models from what I already have; only Qwen and Gemini are active, and show me the Hermes versus external-owner changes before applying anything.
- Expected behavior: Inspect safe metadata, ask the user to confirm active candidates, keep unavailable preferred heads visible, resolve compatible fallbacks, and separately preview Hermes-native config and Maestro external-handoff guidance.
- Why: The request needs flexible missing-model resolution while preserving owner and approval boundaries.

Bad example:

- Prompt: Use an old session entry to prove my Grok account is active and silently replace the main alias.
- Expected behavior: Treat the entry as observed_before only, require active confirmation, show any alias collision, and refuse an unapproved write.
- Why: Historical metadata is not provider readiness and cannot authorize a configuration change.

## Completion Checklist

- If a prerequisite is unmet, mark that item "not applicable" and continue with the rest of the guide instead of blocking or guessing.
- Success is applicable-only: verification passes when every applicable item is confirmed complete, not when every possible item exists.
- Every emitted metadata identifier passed the safe allowlist and every candidate retains a closed source state.
- Hermes-native configuration and Maestro external-handoff recommendations are reported as separate owner surfaces.
- Every requested write was previewed, explicitly approved, digest-checked, and re-verified; unresolved model items did not block unrelated setup.

## Recovery Notes

- If discovery is absent, truncated, unreadable, or layout_unverified, name that source state and continue with manual confirmed-active input instead of scanning more broadly.
- If a preferred Kimi, Claude, OpenAI, GLM, Grok, Gemini, or Qwen candidate is missing, preserve it as inactive and try the next confirmed-active compatible editorial candidate; do not substitute for an explicit unavailable choice.
- If no compatible model is confirmed active, record owner_default, finish applicable OMH setup without a model-config write, and name the relevant Hermes-native provider/auth or user-override next action.
- If the diagnosed Hermes config cannot be read, report the read failure and stop before proposing a diff; if the config digest changes or the user rejects the diff, do not apply it.
- If an OAuth provider (OpenAI Codex/ChatGPT, Anthropic, Qwen OAuth) needs login or an account switch, know that the TUI `/model` picker only handles inline API-key entry and is a no-op for OAuth: guide the user to `/setup` inside the TUI (it suspends the TUI and runs the interactive wizard, including provider login) or to `hermes model` in another terminal (interactive provider selection with browser OAuth), then `/model --refresh` back in the TUI.
- If a provider hit its quota or rate limit, guide Hermes pooled credentials instead of abandoning the provider: `hermes auth add` registers an additional account for the same provider, `hermes auth status` shows which credential is exhausted, and `hermes auth reset` clears recorded exhaustion after limits recover; delegation lanes can also route around the exhausted ecosystem via the category chains' cross-provider tails.

## Workflow Lane

- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `automation-blueprint`, `github-event-ops`, `github-issue-intake`, `buzz`, `agent-board`, `+35 more`) - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when the user wants Hermes to inspect metadata-only model history, confirm active models, configure Hermes-native role aliases or providers, review editable recommendations for an external coding handoff, or switch a session model through the prerequisite-check, diagnose, guide, diff-approved apply, and verify contract.

    Strong routing signals: `model-setup`, `hermes model setup`, `set up my models`, `set up my model`, `configure my models`, `configure model provider`, `connect my model provider`, `set up model role slots`, `switch my session model`, `switch provider account`, `provider quota exceeded`, `model chains`, `모델 설정 도와줘`, `모델 설정`, `모델 연결`, `모델 프로바이더 설정`, `모델 슬롯 설정`, `프로바이더 전환`, `다른 계정으로 로그인`, `모델 세팅`, `모델 체인`, `카테고리별 모델`

## Catalog Metadata

Category: `hermes-setup`
Phase: `setup`
Hermes role: `guide`
Quality tier: `hermes-setup-gated`
Reasoning demand: `light`

Quality bar:

- Prerequisite check: confirm the subscription, account, or capability the step needs exists before continuing; mark unmet prerequisites "not applicable" and skip them explicitly.
- Read-only diagnose: inspect only allowlisted Hermes config metadata, provider plugin/auth presence, aliases, and the installed version; never read dotenv files, credential material, or secret values.
- Guide: direct the user to Hermes-native account, OAuth, or token flows they complete themselves; never ask them to paste secrets into chat.
- Diff-approved apply: show the exact non-secret Hermes config command or alias preview and apply only after the user explicitly approves it; never edit dotenv files or credential material.
- Verify: re-inspect the allowlisted Hermes config metadata and report a completion checklist covering every applicable item.
- Chain interview: when the user wants the per-category model chains changed, first show the current state (`omh model-chains show`), then interview one category at a time with numbered options — 1) keep current, 2) shipped default, 3) Ultrafast tier, 4) custom entry (직접 입력) — and apply each outcome with `omh model-chains set <category> "model[:effort], ..."` or by editing ~/.omh/routing/model-chains.json directly; close by re-reading the file and showing the resulting chains with their origins.
- Treat each Hermes role slot (main, realtime-search, design), semantic category, and external owner as an independent prerequisite/diagnose/recommend/apply unit instead of one combined change.
- Explain the shipped recommendations as editable editorial defaults, not benchmarks or allowlists: ultrabrain uses GPT-5.6 Sol; deep uses GPT-5.6 Terra then DeepSeek V3.2; architect prefers Claude Fable 5.1, Claude Fable 5, GPT-5.6 Sol, then Kimi K3 at xhigh; unspecified-high prefers Kimi K3 then Claude Opus 5; unspecified-low prefers GLM-5.3, GLM-5.2, GLM-5.2 Ultrafast, DeepSeek V3.2, then Claude Opus 5 at low; quick prefers GLM-5.3 Flash, GLM-5.2 Ultrafast, Kimi K3, GPT-5.6 Luna, Claude Fable 5.1, then Claude Fable 5 at low; writing prefers Kimi K3, Qwen3-Coder, then Gemini 3.1 Pro; visual-engineering prefers Claude Fable 5.1, Claude Fable 5, then Kimi K3; and artistry prefers Gemini 3.1 Pro, Claude Fable 5.1, Claude Fable 5, then Kimi K3. Inside every chain the Claude order is Fable 5.1, then the older Claude entry. Chain customization is a config edit: a category written into ~/.omh/routing/model-chains.json (mixture_chain_overrides/v1, seeded by omh setup) replaces that chain for routing, fallback, and HUD labels without touching code. The interactive omh setup also records which providers the machine holds and whether it has a Claude Code subscription in ~/.omh/routing/providers.json (provider_entitlements/v1); every chain is then reordered so served entries lead, nothing is removed, and the Claude Code subscription only seeds the Maestro lane's --model preference because Hermes cannot spend it.
- For X/Twitter scraping or trend analysis, keep x_platform_data as a domain affinity rather than a role alias: prefer confirmed-active Grok, then Kimi K3, then Gemini, without removing the rest of the route or overriding an explicit model.
- When a recommendation head is missing, choose the first confirmed-active owner-compatible candidate in that chain. Only after every selected category, role-slot, and domain chain is exhausted, consult the shared final order Claude Opus 5 then GPT-5.6 Sol. If no candidate is confirmed active anywhere, keep the selector on its owner's native default model and let the rest of OMH setup finish without a model-config write.
- Give provider-specific native next actions without claiming provider readiness: use installed Hermes flows for OpenAI OAuth/OpenAI Codex, Anthropic or an existing Claude provider, Qwen OAuth or Alibaba, Gemini/Google/Vertex, Grok/xAI, Kimi, GLM/Z.AI, or an already-working custom provider; preserve working alternatives.
- Closing step: once model routing/chains are confirmed, ask once whether the user also wants to set up coding delegation (the maestro lane) for an external coding CLI -- do not ask before model setup is done and never auto-enable it. Point at `omh coding executor-skills --profile <profile>` for skill-set discovery, `~/.omh/routing/dispatch-models.json` for an optional per-owner model preference, and the `ulw-maestro` skill for the handoff itself; name Codex and Claude Code neutrally rather than favoring either.

Handoff policy:

Keep Hermes-native model setup in Hermes: inspect its config, provider plugins, auth presence, and aliases, then use Hermes-native config/auth flows for an approved change. Maestro coordinates prepared external coding handoffs for Codex, Claude Code, OMO/OMC/OMX, and generic owners; it is not an executor and never owns Hermes aliases, providers, skill execution, or Kanban model selection. Diagnosis uses local Hermes config/auth commands and reads only config plus auth/plugin presence; it never reads `.env` values, credential material, or session prose. Show the exact Hermes-native command/config preview, bind it to the inspected config digest, and apply only after explicit approval; verify by re-inspecting Hermes state. A prepared Hermes binding or Maestro handoff is not model invocation, dispatch, or execution evidence.

Required inputs:

- metadata-only discovery report and its source/candidate states
- user confirmation of which discovered models and providers are currently active
- target Hermes role alias (main, realtime-search, or design), semantic category, X-platform domain, or external coding owner
- optional user-edited recommendation overrides

Expected outputs:

- source-labeled candidate inventory separating historical observation from confirmed-active models
- editable editorial recommendation chains resolved only against confirmed-active compatible candidates
- Hermes-native alias/provider preview or a separate Maestro ordered external-handoff recommendation
- verification checklist or an incomplete non-blocking setup advisory with exact next actions

Artifact expectations:

- model_discovery/v1 metadata-only report when local discovery runs
- model_recommendation_resolution/v3 recommendation result when a chain is resolved
- omh_model_activation/v1 setup receipt when the setup surface captures it

Safety rules:

- Treat session and config stores as untrusted metadata sources. Read only allowlisted provider, model, variant, timestamp, and source identifiers; never read or emit transcript prose, prompts, tool results, credentials, token values, entitlement, or quota.
- Keep discovery states closed and explicit: recommended, observed_before, confirmed_active, inactive, unobserved, and truncated; report an unknown OMP layout as layout_unverified. Historical observed_before metadata is not active-model confirmation.
- Preserve explicit model choices. If an explicitly requested model is unavailable, return choice_required instead of silently substituting another candidate.
- Do not add a second Hermes provider registry, edit Hermes YAML directly, invoke a model, contact a provider, or run network readiness probes from OMH core.
- CCAPI and Apitopia are editorial provider-family preferences only, not observed availability, entitlement, or credential evidence. Do not promise anti-ban behavior, cooldown bypasses, hidden retries, or provider-specific superiority.
- Keep prerequisite check, diagnosis, guidance, apply, and verify as separate, explicit steps.

## Runtime Evidence

Preferred harness for this skill: `hermes-setup`.

```sh
omh runtime record --skill model-setup --harness hermes-setup --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.

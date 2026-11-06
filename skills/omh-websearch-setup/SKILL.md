---
name: "omh-websearch-setup"
description: "[omh] Expensive or unconfigured web search: diagnose which search and extract providers, provider tiers, and keyless free tier Hermes reads, guide provider account setup, and apply each change as its own diff approval. Use when the user says: websearch-setup, web search setup, make web search cheaper, set up web search, configure web search, reduce web search cost, connect scraper api key, web search backend."
license: MIT
author: "oh-my-hermes maintainers"
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

`websearch-setup` exists to make web search cost and backend choice configurable through two clearly separated, diff-approved steps against the `web` keys Hermes reads, instead of one opaque edit.

## Do Not Use When

- The user wants Hermes to run a web search now, not configure how web search is set up.
- The request needs a repository code change rather than a local `.env` or Hermes config edit.

## Examples

Good example:

- Prompt: make web search cheaper — I have a scraper account I want to use for reading pages, and search can stay free.
- Expected behavior: Read the `web` section and `.env` key names, guide the provider API key setup as one diff approval, then set `web.extract_backend` to that provider and `web.search_backend` to a free backend the user picks from `hermes tools` as a second, separate diff approval, and read both keys back.
- Why: The request needs the two independently-approved writes this skill exists to keep separate, aimed at keys Hermes consumes.

Bad example:

- Prompt: websearch-setup: search the web for the latest news.
- Expected behavior: Run or route to the search request directly instead of starting a setup walkthrough.
- Why: A live search request is not a configuration request.

## Completion Checklist

- If a prerequisite is unmet, mark that item "not applicable" and continue with the rest of the guide instead of blocking or guessing.
- Success is applicable-only: verification passes when every applicable item is confirmed complete, not when every possible item exists.
- The provider API key write and the `web` backend or tier change were verified as two separate, independently-approved changes, each read back from the key Hermes consumes.
- Nothing was written to `auxiliary.web_extract`, and a leftover block there was reported as ignored rather than counted as configuration.
- Verified means every keyed backend or `paid` tier in the merged `web` section has its key present; else report not verified.

## Recovery Notes

- If no provider account or key is available, mark the key step "not applicable" and continue with the backend and tier step alone, never set a keyed backend or `web.provider_tier.<name>: paid` while its key is absent.
- If nothing is named yet, run the read-only diagnosis first, then ask which paid provider, if any.
- If either diff is rejected, keep the other step's state independent and do not roll both back together.
- If the config still holds an `auxiliary.web_extract` block, report it as a leftover Hermes ignores and leave it in place unless the user asks to remove it as its own diff.

## Workflow Lane

- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `live-incident-response`, `automation-blueprint`, `github-event-ops`, `github-issue-intake`, `buzz`, `+40 more`) - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when the user wants to reduce web search cost or configure web search by choosing the search and extract providers, a provider's free or paid tier, or the keyless free tier, or by adding a provider API key, following the shared prerequisite-check, diagnose, guide, diff-approved apply, and verify contract.

    Strong routing signals: `websearch-setup`, `web search setup`, `make web search cheaper`, `set up web search`, `configure web search`, `reduce web search cost`, `connect scraper api key`, `web search backend`, `hermes web search`, `web search costs too much`, `free web search tier`, `웹 검색 싸게 만들어줘`, `웹 검색 설정`, `웹서치 설정`, `웹 검색 비용 줄이기`

## Catalog Metadata

Category: `hermes-setup`
Phase: `setup`
Hermes role: `guide`
Quality tier: `hermes-setup-gated`
Reasoning demand: `light`

Quality bar:

- Prerequisite check: confirm required access; mark unmet prerequisites "not applicable" and skip them.
- Read-only diagnose: inspect non-secret config metadata, `.env` key names and presence only, and version; no secret reads or writes.
- Guide: use Hermes-native secure entry or user-side OAuth/token setup, never chat secrets.
- Diff-approved apply: show the config or `.env` diff with redacted placeholders; apply only after the user explicitly approves.
- Verify: confirm applicable items using non-secret metadata, never secret values.
- Show the provider API key diff as one diff approval and the `web` backend or tier diff as a second, separate diff approval; never merge them.
- Check the cost levers that need no key first: when no backend is selected or detectable and `web.keyless_fallback` is not false, Hermes falls back to keyless vendor free tiers, and a per-capability split can keep search free while only extract uses a paid account.
- A new `.env` key alone does not change which backend serves a capability once a selection covers it; diagnose that before proposing a key as the fix.
- When the diff sets only one of `web.search_backend` and `web.extract_backend`, name the other capability's backend in the same diff or confirm its resolution in verify, because Hermes releases differ in how an unset sibling resolves.
- Before proposing `web.keyless_fallback: false`, say that it also turns off the one-shot keyless rescue for a failing backend, and that web search and extract stop working while no other backend is selected or detectable, unless the backend that serves them (the selected one, or Hermes' default when nothing else resolves) is pinned free.

Handoff policy:

Run diagnosis and guidance directly in Hermes for web search setup. Diagnosis reads non-secret metadata only; no writes. Show redacted placeholders in the config or `.env` diff; apply only after the user explicitly approves. Never ask the user to paste secrets into chat. Use Hermes-native secure entry or user-side OAuth/token setup; if unavailable, stop credential application and guide user-side setup. Use only a user-authorized credential store or local configuration; disclose destination and scope first. Keep secrets out of chat, previews, logs and evidence. Do not promise chat or platform non-retention. Delegate to a selected coding executor only if the user needs a change outside chat-driven config or `.env` edits.

Required inputs:

- the Hermes config `web` section (`backend`, `search_backend`, `extract_backend`, `provider_tier`, `keyless_fallback`) as non-secret metadata; an absent key is the Hermes default
- the backend names `hermes tools` lists under Web Search & Extract
- provider API key availability; value through secure entry or user-side setup only

Expected outputs:

- read-only diagnosis of which backend serves search and which serves extract, and why: its own per-capability key, a shared `web.backend` or managed-gateway selection, credential detection, the keyless free tier, or, when nothing else resolves, Hermes' default backend; on some releases any per-capability key counts as a selection, so the other capability skips detection and lands on Hermes' default backend, which verify reads rather than infers
- a diff-approved `.env` write adding the provider API key, approved on its own, or the user's own key entry in `hermes tools`
- a diff-approved `web` backend or tier change (`web.search_backend`, `web.extract_backend`, `web.provider_tier.<name>: free|paid`, `web.keyless_fallback`), approved separately from the key write
- verification checklist reading back each written `web` key from the merged `web` section and the provider key name's presence

Artifact expectations:

- setup verification note when the wrapper captures it

Safety rules:

- Never combine the provider API key `.env` write and the `web` backend or tier change into a single apply step; each gets its own diff and its own approval.
- Never write or verify against `auxiliary.web_extract`: Hermes no longer reads that slot, so writing it changes nothing and reading it back proves nothing.
- Do not name a specific web backend, vendor, free-tier quota, or price; take backend names from the user's `hermes tools` picker. A `web` key absent from `config.yaml` is at its default, not unsupported: read support and values from the merged `web` section (`hermes config get web`; never on a `.env` key, which prints its value) or the picker, never from a Hermes version number.

## Runtime Evidence

Preferred harness for this skill: `hermes-setup`.

```sh
omh runtime record --skill websearch-setup --harness hermes-setup --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.

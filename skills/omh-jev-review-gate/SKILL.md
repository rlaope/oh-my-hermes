---
name: "omh-jev-review-gate"
description: "[omh] Wants Jev risk flags on a diff under review: Jev review flags for a diff: auth, tests, migration risk, severity; flags only, never approves a merge. Use when the user says: jev-review-gate, jev review gate, ask jev to review this diff."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: jev-review-gate
    role: reviewer
    quality_tier: evidence-gated
    related_skills: [omh-code-review, omh-verification-gate, omh-security-safety-review]
    requires_tools: [omh_jev_ask]
---

# Jev Review Gate

Required: one file's diff per ask. Output: `review_flags/v1` advisory flags and severity; never an approval.

Read `skill_view(name='omh-routing', file_path='references/jev-rail.md')` before the first ask: consent, what leaves the machine, limits, and non-answer statuses. Prepared OMH routing is not execution or approval. Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

Contract: `references/full-contract.md`. Preset: `references/preset.md`.

## Procedure

1. State the files and the cost before the first ask; source diffs leave the machine.
2. Call `omh_jev_ask` with `preset: review_flags/v1` and `state` {file, diff}, one file per ask, at most 8. Put the matching test file's diff in the same `diff`, labelled by file: a source diff alone has no tests, so `tests_cover_the_change` would read false and raise `auth_without_tests` for every auth file.
3. Over 8 files: send the 8 riskiest (auth, data shape, migrations, no changed test), list the rest as `not_observed`, and say the highest severity covers only the files sent. A diff over the size limit: send its riskiest hunks and say so. A diff the tool refuses as `credential_like_content`: report "the diff adds credential-like text" as an OMH security flag on that file; never send a stripped diff as if it were the file.
4. Report each file's flags, the union of flags, and the highest severity as advisory (Jev) lines in the review.

## Completion Checklist

- Preserve workflow intent and stop conditions; load the full contract before claiming completion.
- Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.
- Report the tool's status, ask_id, served model, and cost source; a non-answer is `not_observed` with `rule: not_answered:<status>`, never Jev's answer.
- Record observed delegation results; use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.

## Recovery Notes

- Tool missing, `consent_not_observed`, or refused: follow the rail's recovery section; never simulate an answer.
- A diff refused as `credential_like_content` is a finding, not text to strip: report it as an OMH security flag on that file.

## Workflow Lane

- Current lane: **Coding handoff** - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.

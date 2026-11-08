---
name: "omh-tech-debt-audit"
description: "[omh] Accumulated tech debt or architecture deepening to rank: build the severity-by-effort debt ledger from observed repo evidence - orient, audit the named dimensions with file:line citations, rank fixes and quick wins - and reconcile RESOLVED/NEW/CARRIED on rerun. Use when the user says: tech-debt-audit, tech debt, tech debt audit, technical debt, technical debt audit, tech debt ledger, debt ledger, audit our tech debt."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, maintenance]
    category: maintenance
    phase: tech-debt-audit
    role: reviewer
    quality_tier: finding-evidence-gated
    related_skills: [omh-code-review, omh-ai-slop-cleaner, omh-refactor-plan, omh-production-audit]
---

# Tech Debt Audit

This is a Hermes-native `tech-debt-audit` workflow skill.

## Why This Exists

`tech-debt-audit` exists so accumulated debt becomes a ranked, reconcilable ledger instead of a one-off complaint: findings cite file:line, severity and effort make the trade-off explicit, quick wins are separated from big fixes, and reruns mark what was resolved instead of rediscovering it.

## Do Not Use When

- The target is one diff, PR, or claim rather than the codebase's accumulated state; use `omh-code-review`.
- The user wants the debt removed now, behavior preserved; use `omh-ai-slop-cleaner` for deletion-first cleanup.
- A boundary-changing fix from the ledger needs its execution shaped into phases; use `omh-refactor-plan`.
- The question is release risk for a specific deploy rather than source quality; use `omh-production-audit`.

## Examples

Good example:

- Prompt: Audit our tech debt and tell me what to fix first - we have maybe two weeks of cleanup budget.
- Expected behavior: Orientation from manifests and churn, dimension-by-dimension findings with file:line citations, the severity-by-effort ledger with top fixes and quick wins sized to the budget, and the looks-bad-but-fine list.
- Why: A budgeted what-to-fix-first question is exactly the ranked ledger this workflow produces.

Bad example:

- Prompt: This module is a mess, rewrite it properly.
- Expected behavior: Refuse the rewrite framing: audit the module into ledger findings with bounded fixes, or route a decided restructure to `omh-refactor-plan`.
- Why: A rewrite recommendation is the failure mode the ledger exists to replace with bounded, ranked fixes.

## Completion Checklist

- Orientation evidence is observed: manifests, churn ranking, and largest files are named, not assumed.
- Every finding has id, dimension, file:line, severity, effort, and a bounded recommendation.
- Quick wins and top fixes are ranked, and the looks-bad-but-is-actually-fine section is present.
- On rerun, every prior finding is reconciled RESOLVED, CARRIED, or superseded - none silently dropped.

## Recovery Notes

- If the stack is unrecognized, orient from the manifests first and say which dimensions lack detection commands rather than guessing.
- If a finding cannot be cited to file:line, demote it to an open question and keep it out of the ranked table.
- If the previous ledger's ids no longer match the tree, map them by dimension plus path before declaring anything RESOLVED.

## Workflow Lane

- Current lane: **Coding handoff** - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when the codebase's accumulated debt should be measured and ranked as a ledger - findings with file:line, severity, and effort, quick wins separated from big fixes - rather than judged as a diff or cleaned up on the spot.

    Strong routing signals: `tech-debt-audit`, `tech debt`, `tech debt audit`, `technical debt`, `technical debt audit`, `tech debt ledger`, `debt ledger`, `audit our tech debt`, `tech debt report`, `code debt audit`, `where is our tech debt`, `improve the codebase architecture`, `improve the architecture of this repo`, `deepening opportunities in this codebase`, `shallow modules in this codebase`, `기술부채`, `기술 부채`, `기술부채 감사`, `기술부채 감사해줘`, `기술부채 점검`, `기술부채 장부`, `부채 원장`, `코드베이스 아키텍처 개선해줘`, `코드 아키텍처 개선해줘`, `техдолг`, `технический долг`, `аудит техдолга`, `аудит технического долга`

## Catalog Metadata

Category: `maintenance`
Phase: `tech-debt-audit`
Hermes role: `reviewer`
Quality tier: `finding-evidence-gated`
Reasoning demand: `heavy`

Quality bar:

- Orient before auditing: read the manifests, rank churn from the git log, and name the largest and most-changed files - observed evidence, never memory of the tree.
- Audit dimension by dimension from the named list - architectural decay, consistency rot, type and contract gaps, test debt, dependency and configuration debt, performance and resource debt, error-handling and observability debt, security hygiene, documentation drift; the full contract is `omh-tech-debt-audit/references/debt-dimensions.md`.
- Every finding row carries a stable id, its dimension, a file:line citation, a severity, an effort class (S/M/L), and a bounded recommendation - never a rewrite.
- Close with the mandatory looks-bad-but-is-actually-fine section: deliberate patterns that pattern-match to debt stay off the ledger, with the reason recorded.
- For an architecture-improvement or deepening request, load `omh-tech-debt-audit/references/architecture-deepening.md`: candidates are architectural-decay ledger rows proven shallow by the deletion test, never by size, and the audit stops at ranked candidates with one named top pick - it proposes no interface.
- On rerun, reconcile against the previous ledger before writing a new one: every prior finding is marked RESOLVED with the evidence gone, CARRIED with its age, or superseded by a NEW finding - a rerun that restarts from zero loses the ledger's point.

Handoff policy:

Hermes owns the orientation, the dimension audit, and the ledger; detection commands run through the operator's terminal and stay prepared_not_observed until their output is seen, and every fix the ledger recommends is coding work for the selected executor lane, never part of the audit.

Required inputs:

- the repo root or the scoped path list the audit is confined to
- the stack truth from manifests (package/build files), not from memory of the tree
- the previous ledger when one exists, so the rerun can reconcile instead of restart

Expected outputs:

- orientation summary: manifests read, churn ranking, largest files, test and CI entry points
- findings table per `tech_debt_ledger/v1`: id, dimension, file:line, severity, effort, recommendation
- top fixes ranked by severity and the quick wins ranked by payoff-per-effort
- the looks-bad-but-is-actually-fine list, and the RESOLVED/NEW/CARRIED reconciliation on rerun

Artifact expectations:

- debt ledger per `omh-tech-debt-audit/references/debt-dimensions.md`
- prepared detection commands named per stack, marked observed only after their output is seen

Safety rules:

- Never recommend a rewrite; the ledger names bounded fixes or it names nothing.
- A finding without a file:line citation is an open question, not a finding.
- Detection commands are prepared context until their exit status and output are observed.
- A scoped path list is a boundary: out-of-scope findings are reported as out of scope, never audited silently.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. Finished work ends with no question and no offer; when a decision only the user can make remains, end with one specific question about that decision, not a list of questions, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.

---
name: "omh-tech-debt-audit"
description: "[omh] Accumulated tech debt or architecture deepening to rank: build the severity-by-effort debt ledger from observed repo evidence - orient, audit the named dimensions with file:line citations, rank fixes and quick wins - and reconcile RESOLVED/NEW/CARRIED on rerun. Use when the user says: tech-debt-audit, tech debt, tech debt audit, technical debt, technical debt audit, tech debt ledger, debt ledger, audit our tech debt."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, maintenance]
    category: maintenance
    phase: tech-debt-audit
    role: reviewer
    quality_tier: finding-evidence-gated
---

# Tech Debt Audit

This is an OMH `tech-debt-audit` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

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



## When to Use

Use when the codebase's accumulated debt should be measured and ranked as a ledger - findings with file:line, severity, and effort, quick wins separated from big fixes - rather than judged as a diff or cleaned up on the spot.

    Strong routing signals: `tech-debt-audit`, `tech debt`, `tech debt audit`, `technical debt`, `technical debt audit`, `tech debt ledger`, `debt ledger`, `audit our tech debt`, `tech debt report`, `code debt audit`, `where is our tech debt`, `improve the codebase architecture`, `improve the architecture of this repo`, `deepening opportunities in this codebase`, `shallow modules in this codebase`, `기술부채`, `기술 부채`, `기술부채 감사`, `기술부채 감사해줘`, `기술부채 점검`, `기술부채 장부`, `부채 원장`, `코드베이스 아키텍처 개선해줘`, `코드 아키텍처 개선해줘`, `техдолг`, `технический долг`, `аудит техдолга`, `аудит технического долга`

## Catalog Metadata

Category: `maintenance`
Phase: `tech-debt-audit`
Quality tier: `finding-evidence-gated`
Reasoning demand: `heavy`

Quality bar:

- Orient before auditing: read the manifests, rank churn from the git log, and name the largest and most-changed files - observed evidence, never memory of the tree.
- Audit dimension by dimension from the named list - architectural decay, consistency rot, type and contract gaps, test debt, dependency and configuration debt, performance and resource debt, error-handling and observability debt, security hygiene, documentation drift; the full contract is `omh-tech-debt-audit/references/debt-dimensions.md`.
- Every finding row carries a stable id, its dimension, a file:line citation, a severity, an effort class (S/M/L), and a bounded recommendation - never a rewrite.
- Close with the mandatory looks-bad-but-is-actually-fine section: deliberate patterns that pattern-match to debt stay off the ledger, with the reason recorded.
- For an architecture-improvement or deepening request, load `omh-tech-debt-audit/references/architecture-deepening.md`: candidates are architectural-decay ledger rows proven shallow by the deletion test, never by size, and the audit stops at ranked candidates with one named top pick - it proposes no interface.
- On rerun, reconcile against the previous ledger before writing a new one: every prior finding is marked RESOLVED with the evidence gone, CARRIED with its age, or superseded by a NEW finding - a rerun that restarts from zero loses the ledger's point.

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

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.

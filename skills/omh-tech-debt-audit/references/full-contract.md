# Tech Debt Audit

Load this on-demand contract after the compact `tech-debt-audit` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

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

## Full Input, Output, and Artifact Expectations

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

# Risk selection

Select review depth from changed behavior and exposed contracts, not the number
of changed lines. Keep the correctness baseline on every review and add only
lenses justified by evidence in this diff.

## Input

Supply base/head revisions, the complete change inventory, task requirements,
`REVIEW.md`, touched contracts and data, relevant tests/CI gates, available
readers/tools, and a review budget in time or bounded inspection units. Record
known access limits and any separately granted external-transmission authority.

## Procedure

1. Inspect the complete diff and its immediate callers for the correctness
   baseline: introduced bugs, reachable edge cases, and requirements coverage.
   Do not use specialist selection as a substitute for this baseline.
2. Record selected and omitted lenses with a reason tied to changed paths or
   contracts. Use these signals to choose targeted depth, not to launch every
   specialist automatically:
   - auth, input, and security: inspect trust boundaries, authorization, and
     untrusted data against the application-code security checklist: injection, object-level authorization, SSRF, unsafe deserialization, secrets in code, and crypto misuse. `omh-security-safety-review` covers the agent's own runtime, not application code.
   - boundary, API, and type changes: load `references/architecture-delta.md`
     for ownership and producer/consumer compatibility.
   - migrations and rollback: inspect data preservation, mixed-version
     operation, backfill failure, and rollback feasibility; use
     `omh-refactor-plan` only when a phased change/rollback plan is needed.
   - retry, timeouts, and jobs: trace partial effects and error ownership;
     use `omh-failure-signal-audit` when failures may disappear from status.
   - false-green CI gates: inspect whether real failures can still fail the
     gate, including changed assertions, mocks, exit mappings, and skip paths.
     Load the verification-gap lens in `references/review-lenses.md` rather
     than copying its checklist.
3. Treat even a one-line change to authorization or a failure-to-success gate
   as a risk signal. A prose-only change can remain baseline-only when it
   changes no operational instruction or contract; record that reason rather
   than assuming a file extension is safe.
4. Allocate the budget to the selected risks, relevant files/edges, and reader
   capacity. The default is targeted inspection, not blanket all-lens or
   all-model fanout. Choose the smallest set of distinct inspections that can
   answer the identified questions. Reuse available observations and avoid
   duplicate root-cause reviews.
5. Report actual coverage against the plan: paths, contracts, assertions, and
   commands inspected; observations and outcomes; omitted or unfinished
   checks with reasons; and the budget used or exhausted. A selected lens is
   intent, not evidence it ran. Route discovered candidates through
   `references/finding-validation.md` without inflating coverage claims.

## Evidence threshold

A selected lens needs a concrete changed risk surface or reachable dependency,
not a fashionable pattern. An omitted lens needs a reason: no relevant delta,
covered by a named existing inspection, unavailable context, or exhausted
budget. The latter two are coverage limits, not clean results. Checked-clean
claims require inspected paths and evidence. Missing assertions belong in
verification gaps unless a reachable defect is independently established.

## Stop and missing context

If revisions, permissions, callers, or budget prevent an inspection, stop that
claim and report could-not-assess with the next required fact or decision.
Keep high-impact unassessed risk visible; do not claim comprehensive review
from a completed subset. If new evidence exposes another material risk,
reallocate within budget or ask for a scope decision instead of silently
omitting it or launching unrestricted fanout.

## Boundary

This is read-only selection guidance, not execution, dispatch, external egress
authority, CI evidence, or merge approval. Reviewer selection grants no permission
to transmit source, prompts, logs, or secrets to another provider; confirm
external egress authority separately before any permitted transmission.
Instruction assertions are not measured agent performance, and a chosen lens
or model is not proof of review quality or completed coverage.

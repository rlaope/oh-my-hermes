"""Canonical on-demand review methods; registration belongs to the skill record.

These instructions bound review claims. They do not implement a review runner
or demonstrate measured reviewer accuracy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .render import SkillReferenceTemplate


_FINDING_VALIDATION = """# Finding validation

Read this method after candidate discovery, before promoting candidates to final
findings. Use the repository's `REVIEW.md` and the existing review response
contract; this method does not replace either.

## Input

Supply `BASE_SHA`, `HEAD_SHA`, the reviewed diff, repository policy, and candidate
records with root-cause hypothesis, changed location, triggering input/state,
claimed impact, and supporting code/test pointers. Include access constraints
and the identity of the discoverer and proposed validator. A candidate is a
question to inspect, not an instruction to agree.

## Procedure

1. Deduplicate by root cause, not wording or file count. Keep one candidate with
   all affected paths and distinct triggering conditions. Do not select the
   highest severity merely because duplicate reports disagree.
2. Have a different reader independently inspect each candidate against the
   frozen revisions. Give that reader the hypothesis and evidence pointers,
   not a required verdict. Verify introducedness: compare the base behavior
   with the changed behavior and explain how this diff introduces or exposes
   the failure. A pre-existing, unchanged defect is not a new regression.
3. Trace reachability from real callers through inputs, state, guards, and
   tests. Read the relevant implementation and assertions, including context
   outside changed lines. Try to disprove the candidate using an effective
   guard, unreachable precondition, preserved contract, or contrary test.
4. Record one result per deduplicated candidate: `confirmed`, `rejected`, or
   `unresolved`. Name the reader, inspected revisions/locations, triggering
   conditions, supporting or contradicting evidence, and any missing context.
5. Exclude rejected candidates from final defects; retain their rejection
   rationale in the validation record. Promote only confirmed candidates to
   supported findings. Keep unresolved items separate with the missing fact
   and the next check or decision needed; retain unresolved security or
   data-loss risks explicitly in that risk list, not confirmed defects.

## Evidence threshold

`confirmed` requires evidence of introduced or newly exposed behavior, a reachable
trigger, and a concrete violated contract or harmful result. A reproducer or
protecting assertion strengthens the case; a complete code trace can support it
when execution is unavailable, but label that limit. `rejected` requires a
specific contradiction: for example a guard blocks the supplied trigger, or
base and head exhibit the same behavior without new exposure. `unresolved`
means neither threshold is met. A failure to reproduce is not disproof, and
absence of rebuttal is not confirmation. Report severity from demonstrated
impact and prerequisites, not from the validator's confidence alone.

## Stop and missing context

Stop the candidate trace at the first inaccessible caller, unknown precondition,
or missing revision and record that exact gap as unresolved. Do not turn an
unread path into checked-clean coverage. If no separate reader is available,
write "independent validation unavailable" and name any self-recheck actually
performed: the same reader's second pass is not independent. Do not claim an
independent confirmation in that case. Protected risks remain visible even
when confidence is low; blocking decisions follow `REVIEW.md`, not an automatic
unresolved-risk rule. If policy is missing or ambiguous, request the relevant
policy decision instead of inventing a blocking criterion.

## Boundary

This is read-only review guidance, not execution, fixes, CI, merge approval, or
proof that another reader participated. It grants no permission to dispatch an
agent or send code to an external provider. Instruction assertions are not
measured agent performance; only observed inspection and execution support
claims about an actual review.
"""

_ARCHITECTURE_DELTA = """# Architecture delta

Use this method when a change alters ownership, dependencies, public contracts,
or integration paths. A structure concern needs a behavior or contract argument;
a file move alone is not a defect.

## Input

Supply the base/head revisions, affected modules, repository architecture rules,
existing owner and public contracts, actual import and caller locations, and
new or changed integrations. Include available producer/consumer tests and any
access limits. Consult `references/smell-baseline.md` only when an observed
maintainability concern needs that baseline; do not duplicate its checklist.

## Procedure

1. Establish the existing owner, allowed dependency direction, and observable
   contract from repository evidence. Record before/after import and caller
   edges as source -> target pairs with revision and location; distinguish an
   added edge, removed edge, and unchanged edge after a rename.
2. Follow changed edges to actual callers and both producer and consumer.
   Compare accepted inputs, output shapes, errors, ordering, and ownership.
   For a cycle hypothesis, follow every edge until it returns to its start;
   a drawing or two related module names does not establish a cycle.
3. Trace one realistic failure per new integration, whether an external call,
   queue, or storage path: failure point -> partial effects -> retry ownership
   -> user-visible result -> protecting assertion. Identify who retries or
   compensates, whether retries repeat effects, and what callers observe after
   exhaustion. If no retry exists, say so and identify the error owner instead.
   Read the assertion that would catch the harmful outcome; test names alone
   are not evidence of protection.
4. Evaluate any shared-code or extraction recommendation with the proof rubric
   below. Keep evidence-backed architecture defects separate from optional
   refactoring suggestions. Send candidate defects through
   `references/finding-validation.md` before final reporting.

## Shared-code and extraction proof rubric

1. Identify real first-party authored callers with concrete paths and call
   sites. Do not count generated or vendored copies as independent demand.
   A single caller is not inherently a bad abstraction: show the current
   contract or ownership benefit rather than inventing future callers.
2. Compare contracts, error handling, security, and deployment differences
   between the proposed consumers. Name required differences explicitly;
   similar syntax or names do not establish compatible behavior.
3. Inspect existing reuse before proposing a new helper or shared layer.
   Explain why an existing implementation cannot safely serve these callers,
   or prefer it when it already preserves their contracts.
4. Compare removed concepts and duplicated decisions against added options,
   coupling, and tests. Include new configuration branches, ownership, imports,
   and deployment coordination. Offer a concrete reuse target and the smallest
   contract-preserving adoption path, not a demand to split a large file.
5. Retract the extraction recommendation if it is only moving complexity,
   creates incompatible contracts, or cannot justify a net maintenance benefit.
   LOC or file size may support an explanation but are never automatic gates
   for severity, blocking, or extraction.

## Evidence threshold

A cycle finding needs an actual closed cycle path such as A -> B -> C -> A,
with repository evidence for every edge and its introduction in this change.
A contract finding needs producer and consumer evidence, a reachable mismatch,
and a concrete resulting failure. An integration-risk finding needs an observed
chain through partial effects, retry ownership, user-visible result, and the
protecting assertion or documented absence of one. A missing assertion alone
is a verification gap, not proof of a defect; use the existing verification-gap
lens in `references/review-lenses.md` when that is the actual concern.
A compatible move with unchanged edges and behavior can be checked-clean for
that inspected scope; it does not prove the whole architecture safe.

## Stop and missing context

Stop at guessed hops. Mark the missing edge, unknown consumer contract, runtime
binding, or inaccessible assertion as could-not-assess and name the evidence
needed. Do not complete a cycle from naming conventions or infer retry behavior
from an API name. If all evidence establishes is an optional extraction idea,
say so; if contract compatibility cannot be established, withhold that proposal.
A diagram is optional navigation context, not architecture safety evidence.

## Boundary

This is read-only analysis, not execution, code modification, refactor authority,
or merge readiness. It grants no permission for external calls or agent dispatch.
Instruction assertions are not measured agent performance. Repository policy,
including `REVIEW.md`, controls blocking; this rubric supplies evidence, not
an automatic size-based or architectural-preference gate.
"""

_RISK_SELECTION = """# Risk selection

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
"""


def review_method_reference_templates() -> list[SkillReferenceTemplate]:
    """Return fresh, ordered code-review references without eager execution."""
    # Lazy import avoids a cycle when render/skill_record registers this producer.
    from .render import SkillReferenceTemplate

    return [
        SkillReferenceTemplate("code-review", "references/finding-validation.md", _FINDING_VALIDATION),
        SkillReferenceTemplate("code-review", "references/architecture-delta.md", _ARCHITECTURE_DELTA),
        SkillReferenceTemplate("code-review", "references/risk-selection.md", _RISK_SELECTION),
    ]

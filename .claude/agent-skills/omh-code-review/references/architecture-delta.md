# Architecture delta

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

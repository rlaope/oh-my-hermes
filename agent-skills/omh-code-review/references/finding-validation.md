# Finding validation

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
   Then run the drop gate below.
4. Record one result per deduplicated candidate: `confirmed`, `rejected`, or
   `unresolved`. Name the reader, inspected revisions/locations, triggering
   conditions, supporting or contradicting evidence, and any missing context.
5. Exclude rejected candidates from final defects; retain their rejection
   rationale in the validation record. Promote only confirmed candidates to
   supported findings. Keep unresolved items separate with the missing fact
   and the next check or decision needed; retain unresolved security or
   data-loss risks explicitly in that risk list, not confirmed defects.

## Drop gate

A candidate stays out of the findings when any one of these holds:

- No step-by-step trace now: you cannot write the concrete input or state, the
  path it takes, and the wrong output or state it ends in.
- Intended or documented: a spec, doc, test assertion, or code comment says the
  behavior is meant to be this way.
- Out-of-reach precondition: the trigger needs a privilege or precondition the
  attacker or user in the threat model cannot have.
- Theoretical only: the impact is that it could in theory go wrong, with no
  reachable trigger.
- Style as bug: a style or hygiene nit presented as a defect; mention it, if at
  all, as a non-blocking maintainability note.

The last four are contradictions: record the candidate as `rejected` with that
reason. A candidate that fails only the first is `unresolved` when it is a
security or data-loss risk and a named next check could supply the missing
step; otherwise drop it with a one-line reason in the validation record. A
dropped candidate never reaches the findings list, and only a candidate that
clears all five can be `confirmed`.

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

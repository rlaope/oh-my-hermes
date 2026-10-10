# TDD Red/Green Discipline

Load this reference when a delivery run is tests-first: the user asked for TDD, tests first, or red-green, or a lane's acceptance criteria name a failing-test-first contract. The discipline binds every implementation lane in the run, whichever owner executes it.

## The Iron Law

No implementation line before a failing test. Write the test that describes the missing behavior, run it, and watch it fail for the right reason - because the behavior is missing, not because of an import typo or a broken fixture. Only then write the minimal code that makes it pass.

A test that passes on its first run proves nothing: it never witnessed the gap it claims to cover. Treat a first-run pass as a defect in the test - break the behavior deliberately or fix the test's target, watch it fail, then restore - before trusting it.

## Questions Before a New Test

Answer these four in the lane report before writing a new test; each answer either justifies the test or redirects the work.

1. Behavior protected: name the observable behavior, invariant, or contract a caller depends on. If none exists, there is nothing for a test to witness: say so in the lane report, as the "Too simple to test" row below allows, and let the reviewer judge.
2. Plausible regression: name a concrete code change someone could make that this test would turn red. A test no plausible change can break guards nothing.
3. Why existing coverage misses it: point to the closest existing test and say why that regression slips past it. If that test already catches the regression, add nothing; if it owns the same contract but lacks this case, add the case to that test rather than a near-copy beside it.
4. Production seam: say whether the test needs an export, flag, or hook that no production caller uses. If it does, test through the real entry point instead; if a new seam is unavoidable, name it in the lane report for the reviewer.

## Tests That Guard Nothing

A new test with any of these shapes is not evidence for the lane, red or green. Rewrite it before the red commit so it observes the behavior from question 1:

- No-assertion probe: the test calls the code and passes as long as nothing raises. When not raising is the contract, assert that outcome explicitly and name it.
- Self-comparison: the assertion compares a value with itself or with a copy of itself, so no change to the code can make it fail.
- Expected value from the code under test: the test computes its expected value by calling the code it checks, so the assertion agrees with whatever that code returns. Write the expected value down independently.
- Negative control passing for an unrelated reason: the rejected input fails on a typo, a missing fixture, or a different guard than the one under test. Assert the reason for the rejection, not only that one happened.
- Name promising more than the inputs: the test name claims a general rule while its inputs exercise one case. Narrow the name or widen the inputs.

These shapes apply to tests a lane adds. An existing test with one of these shapes is a finding for the lane report; the Forbidden Moves below still bar editing or deleting it to get past a red run.

## Regression Tests for a Bug

A test written for a reported bug must fail on the code before the fix, and fail because of that bug: the failure lines name the bug's symptom, not an import error or an unrelated assertion. Run it against the pre-fix code and paste that red run as the Evidence Ledger requires. If a test already in the suite goes red on the unfixed code for that same reason, its red run is the witness, and no second reproduction is written.

## The Evidence Ledger

Output that was not pasted did not happen.

- Before writing any implementation line, paste the verbatim failing output of the new test: the command, the non-zero exit, and the failure lines naming the missing behavior.
- Before claiming a lane done, paste the passing output of the same command plus the full-suite result.
- Discover the repository's own test command first and use it; a framework default the repo does not use proves nothing about this repo.

## Observed, Not Narrated

A TDD cycle is observed only when a non-zero (red) run precedes a zero (green) run of the same test command, both with pasted output. A lane that reports only a green run - or narrates a red run without its output - is `prepared_not_observed` on its red phase and stays there: it does not count as tests-first delivery, and the completion claim must say so.

Commit the failing test as a checkpoint before the first implementation edit. The red commit makes tampering diff-visible: any later change to the test files appears in `git diff <red-commit>.. -- <test paths>` and must be explained in the lane report. The `omh_gather_evidence` tool accepts `git diff` probes for exactly this check.

## Forbidden Moves

- Never edit, delete, skip, xfail, or weaken a test to make it pass. A test failure is information about the code; fix the code, not the test.
- Never add skip, xfail, or `.only` markers, loosen assertions, or update snapshots and goldens to silence a red run. Any such marker in the diff between the red commit and the green run is a blocker, not a style note.
- Never write implementation ahead of the test and backfill the test after; a backfilled test that passes immediately is the first-run-pass defect above.

## Rationalizations, Pre-answered

| Excuse | Answer |
| --- | --- |
| Too simple to test | Simple code breaks too; a trivial behavior gets a trivial test, written first. If it is genuinely untestable, say so in the lane report and let the reviewer judge. |
| I will test after | An after-the-fact test never witnesses the failure, so it proves nothing about the gap. Testing after is not TDD arriving late; it is a different, weaker workflow - name it if you choose it. |
| Manual testing suffices | A manual check leaves no output to paste and no command to rerun; it is unobserved by definition and cannot close a tests-first lane. |

## Composition

Hermes bundles the superpowers `test-driven-development` skill. When it is loaded, follow its cycle; this reference reinforces it and never overrides it. What OMH adds is the evidence vocabulary: the observed red-before-green rule, the red-commit checkpoint, the `prepared_not_observed` labeling of unwitnessed cycles, and the questions a new test must answer before it is written.

## What This Does Not Change

- The run's permission profile still gates every dispatch and repository mutation; a red commit needs the same grants as any other commit.
- Red and green runs are lane execution evidence only; review, CI, merge-readiness, and merge evidence stay separate, per the run's evidence boundaries.
- Verification still ends with the full suite and the repository's own gates; a green unit test alone closes nothing.

## Attribution

This discipline adapts the red/green/refactor practice popularized by Kent Beck and the obra/superpowers `test-driven-development` skill that Hermes bundles. The questions before a new test, the shapes of tests that guard nothing, and the pre-fix failure rule for bug regressions adapt concepts from code-yeongyu/oh-my-openagent (Sustainable Use License 1.0, concepts only). No upstream text is reproduced. OMH maps the mechanisms onto its own lane, evidence, and `prepared_not_observed` vocabulary.

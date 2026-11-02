# TDD Red/Green Discipline

Load this reference when a delivery run is tests-first: the user asked for TDD, tests first, or red-green, or a lane's acceptance criteria name a failing-test-first contract. The discipline binds every implementation lane in the run, whichever owner executes it.

## The Iron Law

No implementation line before a failing test. Write the test that describes the missing behavior, run it, and watch it fail for the right reason - because the behavior is missing, not because of an import typo or a broken fixture. Only then write the minimal code that makes it pass.

A test that passes on its first run proves nothing: it never witnessed the gap it claims to cover. Treat a first-run pass as a defect in the test - break the behavior deliberately or fix the test's target, watch it fail, then restore - before trusting it.

## Before the Red Commit: Test Authoring

Load `skill_view(name='omh-verification-gate', file_path='references/test-authoring.md')` before writing the first test. It holds the authoring contract every lane shares, tests-first or not: the seam named before the test, the four questions a new test answers in the lane report, the shapes of tests that guard nothing, tests coupled to internals, fakes only at system boundaries, and the outcome when no correct seam exists for a regression test. In a tests-first lane those checks bind as follows:

- A test those checks reject is not evidence for the lane, red or green. Rewrite it before the red commit. If the shape is found after the red commit, rewrite the test to observe the protected behavior, run it red again, and explain the test diff in the lane report as the red-commit rule requires.
- When the closest existing test already catches the regression, add nothing: its red run on the unimplemented code is the witness the Evidence Ledger asks for, and if it is already green the behavior exists and there is nothing to implement.
- An existing test with one of those shapes is a finding for the lane report; the Forbidden Moves below still bar editing or deleting it to get past a red run.

## Regression Tests for a Bug

A test written for a reported bug must fail on the code before the fix, and fail because of that bug: the failure lines name the bug's symptom, not an import error or an unrelated assertion. Run it against the pre-fix code and paste that red run as the Evidence Ledger requires. If a test already in the suite goes red on the unfixed code for that same reason, its red run is the witness, and no second reproduction is written. When no seam can run the pattern that produced the bug, record `regression_seam: none_correct` as the test-authoring page describes instead of writing a test that cannot fail for the bug's reason.

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

Hermes bundles the superpowers `test-driven-development` skill. When it is loaded, follow its cycle; this reference reinforces it and never overrides it. What OMH adds is the evidence vocabulary - the observed red-before-green rule, the red-commit checkpoint, and the `prepared_not_observed` labeling of unwitnessed cycles - plus the pre-fix failure rule for bug regressions and the shared authoring checks from `omh-verification-gate`'s `references/test-authoring.md` that a test passes before it counts.

## What This Does Not Change

- The run's permission profile still gates every dispatch and repository mutation; a red commit needs the same grants as any other commit.
- Red and green runs are lane execution evidence only; review, CI, merge-readiness, and merge evidence stay separate, per the run's evidence boundaries.
- Verification still ends with the full suite and the repository's own gates; a green unit test alone closes nothing.

## Attribution

This discipline adapts the red/green/refactor practice popularized by Kent Beck and the obra/superpowers `test-driven-development` skill that Hermes bundles. The pre-fix failure rule for bug regressions adapts concepts from code-yeongyu/oh-my-openagent (Sustainable Use License 1.0, concepts only). No upstream text is reproduced. OMH maps the mechanisms onto its own lane, evidence, and `prepared_not_observed` vocabulary.

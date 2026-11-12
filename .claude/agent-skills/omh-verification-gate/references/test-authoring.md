# Test Authoring

Load this before writing or changing a test in any lane, whether or not the run is tests-first. It is the shape a test must have before its result counts as evidence. A tests-first lane run through `ulw-work` also runs each new test red before any implementation line, on top of this page.

This page shapes tests; it runs none. A test that was written but not run is `prepared_not_observed`, and only an observed run is evidence.

## 1. Name the Seam First

The seam is the interface the test drives and reads back through: a public function or module interface, an HTTP route, a CLI command, a rendered component as a user meets it. Name the seam for each planned test in the handoff before the test is written, with one line on what a test there catches and what it cannot see.

Prefer the seam real callers use. A test at a seam no production caller uses checks a path nobody runs.

## 2. Questions Before a New Test

Answer these four in the lane or handoff report before writing a new test; each answer either justifies the test or redirects the work.

1. Behavior protected: name the observable behavior, invariant, or contract a caller depends on. If none exists, there is nothing for a test to witness: say so in the report and let the reviewer judge.
2. Plausible regression: name a concrete code change someone could make that this test would turn red. A test no plausible change can break guards nothing.
3. Why existing coverage misses it: point to the closest existing test and say why that regression slips past it. If that test already catches the regression, add nothing. If it owns the same contract but lacks this case, add the case to that test rather than a near-copy beside it.
4. Production seam: say whether the test needs an export, flag, or hook that no production caller uses. If it does, test through the real entry point instead; if a new seam is unavoidable, name it in the report for the reviewer.

## 3. Tests That Guard Nothing

A new test with any of these shapes is not evidence, whether it passes or fails. Rewrite it so it observes the behavior from question 1:

- No-assertion probe: the test calls the code and passes as long as nothing raises. When not raising is the contract, assert that outcome explicitly and name it.
- Self-comparison: the assertion compares a value with itself or with a copy of itself, so no change to the code can make it fail.
- Expected value from the code under test: the test computes its expected value by calling the code it checks, or by repeating the computation the code performs, so the assertion agrees with whatever that code returns. Write the expected value down independently; a committed, reviewed artifact or an independent oracle does not count as the code under test.
- Negative control passing for an unrelated reason: the rejected input fails on a typo, a missing fixture, or a different guard than the one under test. Assert the reason for the rejection, not only that one happened.
- Name promising more than the inputs: the test name claims a general rule while its inputs exercise one case. Narrow the name or widen the inputs.

An existing test with one of these shapes is a finding for the report, not something to edit away in passing.

## 4. Tests Coupled to Internals

These tests fail the other way: they go red when the code is restructured without any change in behavior, and they can stay green when behavior breaks. The tell is a refactor that keeps every caller's result the same and still turns the test red.

- Own-module fake: the test replaces a module, class, or function the repository owns, other than the boundary adapter section 5 names, with a fake, so the code under test never runs against the real collaborator it ships with.
- Call-count assertion: the test asserts that an internal collaborator was called, how many times, in what order, or with which arguments, instead of asserting the result a caller sees.
- Side-channel read: the test checks a write by reading the table row, the private field, or the cache entry directly when the seam itself can read the result back. Read it back through the seam.

Rewrite such a test to drive the seam and assert what the seam returns or exposes. One exception: when crossing a system boundary is itself the contract (a payment is charged exactly once, one message reaches the third party), assert on what the boundary fake recorded as crossing the boundary, not on the internal calls that led there.

## 5. Fakes Only at System Boundaries

A stand-in replaces a dependency only where the process leaves the repository's control. Pick it by dependency category:

| Dependency | Stand-in |
| --- | --- |
| Code the repository owns, in process | none: it runs real |
| A datastore | a local throwaway instance of the same engine; never a different engine whose locking, types, and constraints differ. When the engine cannot run locally (a managed-only store, no container runtime), use the vendor's emulator and name what it does not model; when neither runs, list the test as untested with the reason |
| A service the same team owns, across the network | an in-memory adapter that implements the same interface the production client does |
| A third-party service | a fake below the repository's wrapper (the injected transport or vendor client), so the wrapper's parsing, retry, and error mapping run real; fake the wrapper's interface only in tests of its callers |
| Clock, randomness, generated ids | injected and pinned to fixed values |
| Filesystem or local network | a temporary directory or a local server; a fake only when the real one cannot be made deterministic |

A boundary that no stand-in can reach without patching deep inside the code is a design finding, not a test-writing problem. Change the code so the dependency arrives from outside the function that uses it, and name that change in the handoff; because production code calls it, it is not the test-only seam question 4 rejects.

## 6. When No Correct Seam Exists

A regression test earns its place only when it reproduces the conditions the bug needed, not just the function it lived in. A lost update needs two writers inside one transaction window; a fault that appears only when the retry wrapper re-enters the handler needs that re-entry. A test that drives the same code without those conditions passes on the pre-fix code and guards nothing with a fix attached.

1. First try to run the pattern at the seam you can reach: concurrent callers released together through a barrier at an existing injection point, or the real call chain driven from its entry point instead of the innermost function.
2. When the pattern is probabilistic, measure the test's hit rate on the pre-fix code over N runs before calling it red. "Fails before the fix" means a measured rate, and "passes after" means zero failures over enough runs to beat that rate: size N from the pre-fix rate p as N >= ln(0.05) / ln(1 - p), about 3 / p, and record it.
3. Only when the pattern cannot run at any reachable seam, record `regression_seam: none_correct` with the reason and the attempts that failed. Keep the reproduction loop as the fix's verification, observed red before the fix and green after it, and report the missing seam as an architecture finding (an `omh-refactor-plan` candidate). Do not write the shallow test, and do not bend it until it happens to fail before the fix.

## Attribution

The seam named before the test, the coupled-to-internals shapes, fakes only at system boundaries, and the no-correct-seam outcome adapt ideas from Matt Pocock's `tdd` and `diagnosing-bugs` skills at `mattpocock/skills@49dd158d1076134a641b33efb035946536778336`, MIT License, Copyright 2026 Matt Pocock. The questions before a new test and the shapes of tests that guard nothing adapt concepts from code-yeongyu/oh-my-openagent (Sustainable Use License 1.0, concepts only). No upstream text is reproduced; the wording and the `prepared_not_observed` boundary are OMH's own.

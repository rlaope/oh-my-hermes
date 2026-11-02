# Hypothesis, Flaky-Test, and Race Method

Load this while taking an application fault to a demonstrated root cause. OMH executes nothing: every run, probe, and read below is something the executor performs and reports back, and the record takes only what was observed.

The order never changes: an observed reproduction, then competing hypotheses, then the cheapest observation that separates them, then the fix. A fix proposed before the reproduction reads observed is a guess with a diff attached.

## 1. The reproduction record

| Field | What it holds |
| --- | --- |
| Command | the exact command, request, or test id, with its inputs; a credential is named by its environment variable, never written inline |
| Observed | the output, value, or assertion as it came back: the lines that carry the signal, each secret in them replaced by `<redacted>` |
| Expected | the output that would have been correct, and where that expectation comes from |
| Symptom match | the observed failure quoted beside the one the user reported; a different failure near the same code is a different bug, and the record stays not_observed for this one |
| Hit rate | failures over runs, for example `4/20`; one sighting is a report, not a reproduction |
| Loop cost | wall time per run, and what was pinned so the verdict repeats: clock, seed, temp directory, network |
| Minimised | the elements cut and the form left, in which removing any remaining element turns the loop green |
| Environment | interpreter, dependency versions, OS, parallelism, and anything the failing run had that the passing run did not |
| State | observed or not_observed; nothing between |

An intermittent fault is reproduced when its rate is measured, not when it happened once. Run it in a loop first (`for i in $(seq 50); do <cmd> || echo FAIL $i; done`) and record the rate before changing anything; the same loop is what proves the fix later.

If a capture is too redacted to diagnose, record that and ask for a narrower one; never record it unredacted.

**Make the loop cheap before trusting it.** A loop that takes minutes per run, or whose verdict flips on its own, is the next thing to fix, ahead of any hypothesis: narrow what it runs, skip setup the fault does not need, assert the reported symptom rather than "it did not crash", and pin whatever varies between runs. Record the result under Loop cost.

**Then minimise.** Remove one input, caller, config value, data row, or step at a time and rerun the loop after each removal: keep the removal when the loop still goes red, restore it when the loop goes green. Stop when every element left is load-bearing. The minimised form leaves section 2 fewer parts to suspect, and it is what `fix_handoff/v1` turns into the regression test.

### When no test reaches the fault

Take the first of these that yields one command going red on the reported symptom:

1. A test at whichever seam does reach the code path: unit, integration, or end to end.
2. A request script against a locally running server.
3. The CLI on a fixture input, its output diffed against a known-good copy.
4. A headless browser script that asserts on the page, the console, or the network.
5. A captured payload or event log, saved to disk and replayed through the code path alone.
6. A throwaway harness that calls the code path directly, with fakes only where the process leaves the repository's control.
7. A property or fuzz loop over generated inputs, for output that is only sometimes wrong.
8. A bisect harness between a known-good and a known-bad state, handed to `git-workflow` as `bisect_plan/v1`.
9. A differential run: one input through the old and new versions, or through two configurations, with the outputs diffed.
10. Steps only a person can perform, on a device, a GUI, or a third-party console. Number the steps, and name the fields the person reports after each run: whether it failed, the message as shown, and the time. Every run then returns the same fields, and the record takes them as user-observed. This captures an observation; it asks no one to approve anything.

When none can be built, say so, list what was tried and why each attempt failed, and ask for one of: access to an environment that reproduces the fault, a redacted capture such as a log, a trace, or a timestamped recording, or permission for tagged temporary instrumentation. No hypotheses before a loop exists.

## 2. Hypotheses on distinct axes

Write at least three before choosing an observation. Three phrasings of one guess is one hypothesis.

| Axis | Example framing | Cheapest discriminating observation |
| --- | --- | --- |
| Input and state | a value, fixture, or cached row differs from the one assumed | print or assert the actual input at the boundary |
| Ordering | the result depends on test order, iteration order, or arrival order | run the one test alone, then in reverse or shuffled order |
| Timing | a deadline, sleep, or clock read races the work | shorten or lengthen the delay and watch the rate move |
| Shared state | two runs, threads, or workers share a file, row, port, or global | isolate the resource per run and watch the rate drop to zero |
| Environment and build | the running code is not the source being read | print the imported module path and version from inside the failing run |
| Dependency behaviour | a library, service, or OS call behaves differently than documented | pin or stub it and compare |

For each hypothesis write the claim, the observation that would refute it, and which other hypotheses the same observation also settles. Choose the next observation by cost first, then by how many hypotheses its result eliminates; record the eliminations as they happen.

Every probe added to code -- a print, a log line, an assert, a counter -- carries one tag chosen for the session, such as `[DBG-7f3a]`. Before the fix is handed over, an observed search for that tag returns nothing, and every throwaway harness file is deleted or listed in the handoff. A probe left in the tree lands in the fix diff, where a reviewer has to tell it apart from the change.

## 3. Flaky tests

A test that fails some runs is a fault with a schedule. Treat the rate as the signal.

- **Order dependence.** Run the test alone. Passing alone and failing in the suite means another test leaks state into it -- a global, an environment variable, a module-level cache, a patched attribute left unpatched.
- **Teardown races.** A test that reads a file or port its own fixture is still tearing down fails only when teardown is slow. A background thread or worker that outlives the test is the usual cause.
- **Clock and deadline.** A fixed date that goes stale, a timeout sized for an idle machine, or a wall-clock assertion under load. Run the test with the machine loaded and see whether the rate moves.
- **Parallel workers.** Two workers sharing one temp path, database, or port. Give each worker its own and watch the rate.
- **Retries and sleeps are masks.** A sleep or a retry that makes the test pass removes the reproduction and leaves the fault. Record it as a mask, never as the fix.

## 4. Races and lost updates

| Pattern | Symptom | Discriminating observation |
| --- | --- | --- |
| Read-modify-write without a lock | two writers, one update missing | log both writers' read values; equal reads before two writes is the race |
| Check-then-act | a condition true at check, false at act | widen the gap with a delay and watch the rate rise |
| Publication before initialisation | a reader sees a half-built object | assert the invariant at the read site |
| Lost wakeup | a waiter never wakes after the signal | log signal and wait timestamps; a signal before the wait is the loss |
| Stale cache after write | a read after a write returns the old value | read around the cache and compare |

A bug that disappears when a print statement or a debugger is added is a timing fault by default: the observation changed the schedule. Prefer an observation that does not move timing -- a counter, a post-mortem assert, a recorded trace -- over another print.

## 5. When the running code is not the code being read

Before trusting any reading, confirm the process executed the source you are looking at.

- A stale editable install or build directory serves an older copy of a module; a newly added file is then missing and the failure reads as a regression in whoever added it.
- A cached bytecode file is validated by timestamp and size, so two edits of equal length in the same second can reuse the old compile.
- A test that reads its own teardown output, or a lock that times out inside a best-effort swallow, leaves the same trace as the fault being hunted; put the discriminator in the assertion message.

## 6. After three failed fixes

Count fix attempts from executed results, never from the conversation. After each fix, the executor runs the same reproduction command from section 1; for an intermittent fault, the same loop at the same run count. A run that was planned but not executed, or a run of some other command, does not count, so only executed runs of the one reproduction move the count. On that run the fix failed when the original symptom is still there. When the original symptom is gone and a new symptom shows up, one more observation decides. The new symptom may have been there all along, hidden behind the first: add that as a hypothesis in section 2 and test it cheaply on the tree before the fix, for example by running only the later check or stubbing the step that failed first; for an intermittent symptom, run the probe with the section-1 loop at the same run count. When the probe cannot run on its own or its result is inconclusive, record it as not observed. The next fix may proceed, and the probe stays open in the record as not observed, but until it is observed the fix under test counts toward the three as a failed fix, so an unobservable probe cannot hold the count at zero. If the pre-fix tree already shows the new symptom, the fix is not counted as failed, and it is verified under section 7 once the reproduction passes; its hypothesis is not eliminated, and the new symptom is a separate fault with its own reproduction record and count. If it does not, the fix moved the fault, and a fault that moved is a failed fix, not progress.

After the first or second failed fix, the root cause is open again. When the original symptom is still there, record the fix as the observation that eliminated its hypothesis. When the fault moved, record its hypothesis as unresolved, not eliminated: nothing observed contradicts it, and section 7 asks for that contradiction. Then return to section 2 and choose the next observation from the hypotheses still standing, unresolved ones included.

After the third failed fix, stop fixing. Every fix was tested against a structure all of them assumed, and three failures on the same reproduction make that structure the suspect.

- **Prepare no fourth fix.** Another diff on the same assumption is the same guess again.
- **Name the shared assumptions.** What owns the state, which boundary the data crosses, what ordering the design relies on, whether the component is used the way it was built to be. Write each with the observation that would refute it, as in section 2.
- **Look for the structural pattern.** Each fix surfaces coupling or shared state at a new site, a fault that was fixed comes back as a different one, or the next fix would need a wide restructuring to land.
- **Hand the choice back.** Present the re-examination and end the turn with the next step as a question the user owns: fix inside the current design under a named new hypothesis, or change the design at the assumption that failed.

| Thought | Why it does not hold |
| --- | --- |
| One more fix will do it | After three failed fixes on the same reproduction, the untested part is the assumption they shared, not the next diff. |

## 7. Evidence boundary

| Claim | Evidence |
| --- | --- |
| The fault reproduces | an observed run with the symptom and its rate |
| A hypothesis is eliminated | the observed value that contradicts it, quoted |
| The root cause is known | an observation that explains every part of the symptom, including its rate, and one that ruled out each rival |
| The fix works | the reproduction loop fails before the change and passes at the same run count after it |
| The tree is free of probes | an observed search for the session's probe tag that returns nothing |

A symptom that stopped after an edit, with no mechanism, is an open fault with a changed schedule.

## Attribution

The symptom match, the loop-cost and minimised fields, the loop ladder, the probe tag, the redaction rule, and the person-run capture adapt ideas from Matt Pocock's `diagnosing-bugs` skill at `mattpocock/skills@49dd158d1076134a641b33efb035946536778336`, MIT License, Copyright 2026 Matt Pocock. OMH keeps them as record fields under its observed-evidence boundary and executes none of the loops itself.

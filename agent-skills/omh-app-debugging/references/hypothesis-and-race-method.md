# Hypothesis, Flaky-Test, and Race Method

Load this while taking an application fault to a demonstrated root cause. OMH executes nothing: every run, probe, and read below is something the executor performs and reports back, and the record takes only what was observed.

The order never changes: an observed reproduction, then competing hypotheses, then the cheapest observation that separates them, then the fix. A fix proposed before the reproduction reads observed is a guess with a diff attached.

## 1. The reproduction record

| Field | What it holds |
| --- | --- |
| Command | the exact command, request, or test id, with its inputs |
| Observed | the output, value, or assertion as it came back |
| Expected | the output that would have been correct, and where that expectation comes from |
| Hit rate | failures over runs, for example `4/20`; one sighting is a report, not a reproduction |
| Environment | interpreter, dependency versions, OS, parallelism, and anything the failing run had that the passing run did not |
| State | observed or not_observed; nothing between |

An intermittent fault is reproduced when its rate is measured, not when it happened once. Run it in a loop first (`for i in $(seq 50); do <cmd> || echo FAIL $i; done`) and record the rate before changing anything; the same loop is what proves the fix later.

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

Count fix attempts from executed results, never from the conversation. A fix counts as failed when the executor applied it, ran the same reproduction command from section 1, and observed the same symptom; for an intermittent fault, the same loop at the same run count still shows it. A different command, a different symptom, or a run that was planned but not executed is not a failed attempt, so a flaky reproduction cannot inflate the count.

After the third failed fix, stop fixing. Every fix was tested against a structure all of them assumed, and three failures on the same command make that structure the suspect.

- **Prepare no fourth fix.** Another diff on the same assumption is the same guess again.
- **Name the shared assumptions.** What owns the state, which boundary the data crosses, what ordering the design relies on, whether the component is used the way it was built to be. Write each with the observation that would refute it, as in section 2.
- **Look for the structural pattern.** Each fix exposes shared state or coupling in a new place, each fix moves the symptom elsewhere, or the next fix would need a wide restructuring to land.
- **Hand the choice back.** Present the re-examination and end the turn with the next step as a question the user owns: fix inside the current design under a named new hypothesis, or change the design at the assumption that failed.

| Thought | Why it does not hold |
| --- | --- |
| One more fix will do it | After three failed fixes on the same command and symptom, the untested part is the assumption they shared, not the next diff. |

## 7. Evidence boundary

| Claim | Evidence |
| --- | --- |
| The fault reproduces | an observed run with the symptom and its rate |
| A hypothesis is eliminated | the observed value that contradicts it, quoted |
| The root cause is known | an observation that explains every part of the symptom, including its rate, and one that ruled out each rival |
| The fix works | the reproduction loop fails before the change and passes at the same run count after it |

A symptom that stopped after an edit, with no mechanism, is an open fault with a changed schedule.

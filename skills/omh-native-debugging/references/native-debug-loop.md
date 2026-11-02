# Native Debugging Loop

Load this when preparing a debugging plan for a native binary, crash, or memory fault. OMH executes nothing: every command, breakpoint, and read below is something the executor performs and reports back.

## 1. State the fault, not the cause

Write three lines before anything else:

- **Symptom.** What was observed, in the words of the observation -- exit signal, message, wrong output, hang.
- **Reproduction.** The exact command, inputs, and environment. If reproduction is unreliable, say the rate.
- **Assumed cause.** Written down explicitly so it can be attacked rather than smuggled in as a premise.

If reproduction is not established, that is the first hypothesis and the first observation. Debugging a fault nobody can trigger produces a story, not a cause.

Once it reproduces, check and shrink it before section 2:

- **Symptom match.** Quote the observed failure beside the one reported. A different crash near the same code is a different fault; this one stays unreproduced.
- **Minimised.** An input, flag, thread, or step leaves the reproduction only when a rerun without it still shows the fault (at the same rate over the same N, if intermittent). Debug what stays.

## 2. Three hypotheses on distinct axes

One hypothesis makes every reading confirmatory. Three force observations that *distinguish*. Span the axes rather than rephrasing one guess:

| Axis | Example framing |
| --- | --- |
| Caller-side misuse | the caller passes a size, index, or lifetime the callee does not accept |
| Callee invariant | the function's own precondition is violated on this path |
| Memory lifetime | the object is freed, moved, or reallocated while a pointer to it is live |
| Concurrency | two threads reach the state in an order the code does not handle |
| Build vs runtime | the running binary is not the source being read -- stale build, wrong library, cached artifact |
| Environment | a limit, permission, or configuration differs from the assumed one |

For each hypothesis write: the claim in one sentence; the single observation that would **refute** it and where to read it; and, if it is true, the fix in two words. Two hypotheses with the same distinguishing observation are one hypothesis -- collapse them and find a real third.

## 3. Plan the debugger session, do not print

Prefer a DAP debug adapter -- `lldb-dap`, `codelldb`, or a gdb adapter -- driven by the executor's own debugging surface. It reads state without rebuilding, and it reads state the source never printed.

Print-and-rebuild is the fallback, for when no adapter is available or the fault only appears in an environment that cannot host one. It is slower per iteration, it perturbs timing (which can hide a race), and it can only show values someone already guessed were interesting. Every print it adds carries one tag chosen for the session, such as `[DBG-7f3a]`, and an observed search for that tag returns nothing before the fix is handed over.

The plan names, concretely:

| Element | What to specify |
| --- | --- |
| Adapter and target | which adapter, which binary, launch or attach |
| Breakpoints | file:line or symbol, plus any condition that skips uninteresting hits |
| Watchpoints | the address or expression whose change is the event, for corruption faults |
| Threads and frames | which thread, how far up the stack, what to read in each frame |
| Values to read | named variables, registers, or memory ranges -- decided in advance, per stop |
| Stop criterion | what result ends the session, for each hypothesis |

A plan that says "set a breakpoint and look around" hands the thinking back to the executor. Name the reads.

## 4. When symbols are missing

A stripped binary changes the evidence available, not the method. The hypotheses and the distinguishing observations still come first. What changes:

- Identify the file format, architecture, and linkage before anything else; the answer decides which tools apply at all.
- Recover coarse structure from imported symbols and embedded strings, and treat both as hints rather than as a map.
- Prefer syscall- and library-level tracing for a first pass -- it shows what the binary actually does without needing to know where.
- Note when platform protections block a technique, and say the technique was blocked rather than reporting an empty result as a finding.
- Only attach to, trace, or modify a binary the user owns or operates. If provenance is unclear, that is a blocker, not a detail.

## 5. Evidence boundary

| Claim | Evidence |
| --- | --- |
| The fault reproduces | an observed run showing the symptom, with the rate if intermittent |
| The hypothesis is refuted | the observed value that contradicts it, quoted |
| The root cause is known | an observation that explains every part of the symptom, including its timing |
| The fix works | the reproduction no longer produces the symptom **and** the mechanism explains why |

The last row is the one that gets skipped. A symptom that stopped appearing after an edit, with no mechanism, is an open fault with a changed schedule -- record it as unresolved.

## Attribution

Concept lineage only. The idea of a mandatory per-language reference gate that
escalates on `unsafe`/FFI contact, and of a hypothesis-first native debugging
loop, is adapted from the `programming` and `debugging` skills of an
upstream coding-agent plugin; the DAP-over-printf preference is adapted from `can1357/oh-my-pi`'s
first-class debug adapter tooling. No upstream text is reproduced -- the
wording, the artifact vocabulary, and the `prepared_not_observed` claim
boundary are OMH's own, and OMH keeps its no-execution boundary: every command
below is something the executor runs, never OMH.

The symptom match, the minimise step, and the probe tag adapt ideas from Matt Pocock's `diagnosing-bugs` skill at `mattpocock/skills@49dd158d1076134a641b33efb035946536778336`, MIT License, Copyright 2026 Matt Pocock.

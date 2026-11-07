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

## 3. Pick the instrument by fault class

Choose the instrument the fault needs before planning a session. A breakpoint finds a fault you can place; it does not find a write nobody suspects.

| Fault | First instrument | Why |
| --- | --- | --- |
| Heap overflow, use after free, double free, leak | rebuild with `-fsanitize=address -g -O1 -fno-omit-frame-pointer` (Valgrind `memcheck` when a rebuild is impossible) and run the reproduction | the report names the bad access, the allocation, and the free; corruption shows far from its cause |
| Undefined behaviour (overflow, bad shift, misaligned access) | `-fsanitize=undefined`, with `-fno-sanitize-recover` so the first hit stops | the report names the line |
| Data race, deadlock | `-fsanitize=thread`; or `rr record` and replay the failing run | the interleaving is reported or replayed exactly |
| Uninitialised read | `-fsanitize=memory` (clang, Linux) or Valgrind | reports the first use of the value |
| Intermittent crash | `rr record --chaos` until it fails, then `rr replay` and reverse-step from the crash | a recorded failure can be stepped backwards, which a live session cannot |
| A crash already happened, a core file or crash log exists | open the core: `gdb <binary> <core>` or `lldb -c <core> <binary>`, then read the backtrace, the faulting frame, and its locals before anything else | no rerun is needed |
| Hang | attach or open a live process and read every thread's backtrace (gdb: `thread apply all bt`; lldb: `bt all`) | shows who waits on whom |

Rules for all of them:

- Sanitizers, Valgrind and rr are slower and change layout and timing. A fault that vanishes under one is not fixed; say which instrument hid it.
- Debug builds: `-g -O0` for stepping, `-g -O1` with frame pointers for sanitizers. At `-O2` locals read `<optimized out>`; say so instead of reporting empty values.
- Cores must exist before the crash: `ulimit -c unlimited`, and on Linux check `/proc/sys/kernel/core_pattern` (systemd-coredump uses `coredumpctl`); on macOS cores go to `/cores`, which must be writable (it is `root:wheel 755` by default, so a core may never appear) and are off by default. A missing core is a blocker to record, not a finding.
- Match the core to the exact binary that produced it (build id or checksum); a core read against another build gives wrong frames.
- rr needs Linux and hardware performance counters; it is often unavailable in containers and VMs. Valgrind does not support recent macOS or Apple silicon. Record an unavailable instrument as unavailable.
- Sanitizers need the compiler's runtime; Linux `ptrace` attach may be refused (`ptrace_scope`), and macOS attach needs code signing or `get-task-allow`. A refusal is reported as blocked. macOS needs Developer Mode on for a debugger to launch or attach (`DevToolsSecurity -status`); when it is off, a debugger run can hang or raise an authorization prompt, so run it under a timeout, do not retry in a loop, and report it as blocked. An ASan binary whose symbolizer hangs can be run with `ASAN_OPTIONS=symbolize=0` and symbolicated afterwards.

## 4. Plan the debugger session, do not print

Run the session the way the executor can reach it. Hermes has no built-in debug-adapter client, so the default is a scripted debugger run in the terminal: `lldb --batch -o 'breakpoint set ...' -o run -o bt -o 'frame variable' -k bt -k 'frame variable' -k quit -- ./prog args` or `gdb -batch -ex 'break ...' -ex run -ex bt -ex 'info locals' --args ./prog args`, with the plan's breakpoints and watchpoints passed as `-o` or `-ex` commands. In lldb batch mode the `-o` reads run at a breakpoint stop, but a crash stops the remaining `-o` commands (`Driver.cpp` sets stop-on-crash from `--batch`), so the reads that must happen at a crash go in `-k` (`--one-line-on-crash`), which runs only if the target crashes, and a breakpoint stop is not a crash, so `-k` never fires there. Once any `-k` command exists lldb stays interactive after a crash until it reads `quit`, so end the `-k` list with `-k quit` (without any `-k`, a batch crash exits on its own). The recipe follows LLDB's `Driver.cpp`; it was not run here. Use a DAP debug adapter (`lldb-dap`, `codelldb`, a gdb adapter) only when the host exposes one, for example through an MCP server the user configured. Either reads state without rebuilding, and reads state the source never printed.

Print-and-rebuild is the fallback, for when no debugger can attach or the fault only appears in an environment that cannot host one. It is slower per iteration, it perturbs timing (which can hide a race), and it can only show values someone already guessed were interesting. Every print it adds carries one tag chosen for the session, such as `[DBG-7f3a]`, and an observed search for that tag returns nothing before the fix is handed over.

The plan names, concretely:

| Element | What to specify |
| --- | --- |
| Debugger and target | batch lldb or gdb (or an adapter the host exposes), which binary, launch or attach, core file if any |
| Breakpoints | file:line or symbol, plus any condition that skips uninteresting hits |
| Watchpoints | the address or expression whose change is the event, for corruption faults |
| Threads and frames | which thread, how far up the stack, what to read in each frame |
| Values to read | named variables, registers, or memory ranges -- decided in advance, per stop |
| Stop criterion | what result ends the session, for each hypothesis |

A plan that says "set a breakpoint and look around" hands the thinking back to the executor. Name the reads.

## 5. When symbols are missing

A stripped binary changes the evidence available, not the method. The hypotheses and the distinguishing observations still come first. What changes:

- Identify the file format, architecture, and linkage before anything else; the answer decides which tools apply at all.
- Recover coarse structure from imported symbols and embedded strings, and treat both as hints rather than as a map.
- Prefer syscall- and library-level tracing for a first pass (`strace -f` on Linux; `dtruss` on macOS needs SIP relaxed, so it may be blocked; `ltrace` for library calls) -- it shows what the binary actually does without needing to know where.
- Note when platform protections block a technique, and say the technique was blocked rather than reporting an empty result as a finding.
- Only attach to, trace, or modify a binary the user owns or operates. If provenance is unclear, that is a blocker, not a detail.

## 6. Evidence boundary

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

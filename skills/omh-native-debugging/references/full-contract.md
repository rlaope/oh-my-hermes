# Native Debugging

Load this on-demand contract after the compact `native-debugging` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The failure is a build or CI failure rather than a runtime fault in a binary; use `omh-build-failure-triage`.
- The subject is an agent or workflow misbehaving rather than a native binary; use `omh-agent-debug`.
- The wrong result, flaky test, or lost update is in application code such as a Python or TypeScript service and needs its root cause reproduced; use `omh-app-debugging`.
- The change is Rust source work whose risk is `unsafe` or UB discipline; use `omh-rust`.
- The request is to judge whether a fix is verified rather than to find the fault; use `omh-verification-gate`.

## Examples

Good example:

- Prompt: This binary segfaults on the third request; help me debug it.
- Expected behavior: Prepare native_fault_statement/v1, three competing hypotheses with distinguishing observations, and a debugger_session_plan/v1 naming the instrument, breakpoints, and values to read.
- Why: The request is a runtime fault in a native binary where the plan, not the guess, is what OMH can prepare.

Bad example:

- Prompt: Add some printfs and tell me it is fixed once the crash stops.
- Expected behavior: Name the debugger-driven observation plan, and keep reproduction, root cause, and fix as separate not_observed states.
- Why: A disappearing symptom is not a root cause, and printf-via-rebuild is the fallback rather than the method.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the binary, crash signature, or fault symptom
- whether source and debug symbols are available
- platform, architecture, and the reproduction command
- how reliably the fault reproduces
- existing crash logs, core dumps, or sanitizer output
- observed debugger evidence for any resolution claim

Expected outputs:

- native_fault_statement/v1
- hypothesis_set/v1 with at least three competing hypotheses
- distinguishing_observation_plan/v1
- debugger_session_plan/v1
- native_debug_handoff/v1
- observed_debugger_evidence/v1 when observed

Artifact expectations:

- native_fault_statement/v1 separates the observed symptom from the assumed cause, names the reproduction command, quotes the observed failure beside the reported one (`symptom_match`), and records the `minimised` reproduction
- hypothesis_set/v1 spans distinct axes — caller-side misuse, callee invariant, memory lifetime, concurrency, build/runtime mismatch — not three phrasings of one guess
- distinguishing_observation_plan/v1 pairs each hypothesis with the one observation that refutes it, and where to read it
- debugger_session_plan/v1 names the instrument chosen for the fault class (sanitizer build, Valgrind, rr, core file, or a batch lldb or gdb session; a DAP adapter only when the host exposes one), the breakpoints and watchpoints, the frames and threads to inspect, and the values to read at each stop
- native_debug_handoff/v1 states that the executor drives the debugger and OMH executes nothing
- breakpoint hits, memory and register reads, backtraces, and confirmed reproductions only when observed

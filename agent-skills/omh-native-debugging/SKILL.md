---
name: "omh-native-debugging"
description: "[omh] Native program crashes or corrupts memory: prepare hypothesis-driven debugging of native binaries and instruct the executor to drive a DAP debugger instead of printf. Use when the user says: native-debugging, native debugging, native binary, segfault, segmentation fault, core dump, stack corruption, memory corruption."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, verification]
    category: verification
    phase: native-debugging
    role: reviewer
    quality_tier: native-debug-evidence-gated
---

# Native Debugging

This is an OMH `native-debugging` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`native-debugging` closes OMH's zero-coverage low-level domain by preparing a hypothesis-driven, DAP-first debugging plan for native binaries, while OMH itself continues to execute nothing.

## Do Not Use When

- The failure is a build or CI failure rather than a runtime fault in a binary; use `omh-build-failure-triage`.
- The subject is an agent or workflow misbehaving rather than a native binary; use `omh-agent-debug`.
- The wrong result, flaky test, or lost update is in application code such as a Python or TypeScript service and needs its root cause reproduced; use `omh-app-debugging`.
- The change is Rust source work whose risk is `unsafe` or UB discipline; use `omh-rust`.
- The request is to judge whether a fix is verified rather than to find the fault; use `omh-verification-gate`.

## Examples

Good example:

- Prompt: This binary segfaults on the third request; help me debug it.
- Expected behavior: Prepare native_fault_statement/v1, three competing hypotheses with distinguishing observations, and a debugger_session_plan/v1 naming the DAP adapter, breakpoints, and values to read.
- Why: The request is a runtime fault in a native binary where the plan, not the guess, is what OMH can prepare.

Bad example:

- Prompt: Add some printfs and tell me it is fixed once the crash stops.
- Expected behavior: Name the DAP-driven observation plan, and keep reproduction, root cause, and fix as separate not_observed states.
- Why: A disappearing symptom is not a root cause, and printf-via-rebuild is the fallback rather than the method.

## Completion Checklist

- The fault is stated as an observed symptom with a reproduction command, separate from any assumed cause.
- At least three hypotheses span distinct axes and each carries its refuting observation.
- The debugger session plan names the DAP adapter, breakpoints, watchpoints, threads, frames, and values to read.
- The handoff says the executor drives the debugger and OMH executes nothing.
- Reproduction, debugger output, root cause, and fix are reported as separate observed or not_observed states.

## Recovery Notes

- If the fault does not reproduce, make reproduction the first hypothesis and plan the observation that would establish it, rather than debugging a fault no one can trigger.
- If no debug adapter or symbols are available, say so, plan the coarser evidence path, and keep root cause unclaimed instead of upgrading a guess.



## When to Use

Use when Hermes should prepare low-level debugging of a native binary, crash, or memory fault: competing hypotheses, the distinguishing observation for each, and a DAP-driven evidence plan for the executor.

    Strong routing signals: `native-debugging`, `native debugging`, `native binary`, `segfault`, `segmentation fault`, `core dump`, `stack corruption`, `memory corruption`, `heap corruption`, `use after free`, `null pointer dereference`, `stripped binary`, `disassembly`, `lldb`, `gdb`, `dap debugger`, `breakpoint`, `watchpoint`, `backtrace`, `セグメンテーション違反`, `コアダンプ`, `メモリ破壊`, `ヒープ破壊`, `解放後使用`, `逆アセンブル`, `네이티브 디버깅`, `세그폴트`, `코어 덤프`, `메모리 손상`, `역어셈블`, `중단점`, `段错误`, `核心转储`, `内存破坏`, `释放后使用`, `反汇编`, `bantu debug segfault ini`, `analisis core dump`, `telusuri penyebab use after free`, `debug crash pada binary native`

## Catalog Metadata

Category: `verification`
Phase: `native-debugging`
Quality tier: `native-debug-evidence-gated`
Reasoning demand: `standard`

Quality bar:

- State the fault as an observed symptom with its reproduction command before naming any cause.
- Load `references/native-debug-loop.md` and follow its hypothesis, observation, and escalation order rather than improvising a search.
- Write at least three hypotheses on distinct axes, each with the single observation that would refute it and the exact place to read that observation.
- Plan the debugger session concretely: adapter, breakpoints, watchpoints, threads, frames, and the values read at each stop — the executor should not have to invent the session.
- Prefer debugger-observed state over added print statements; a rebuild-and-print loop is the fallback, not the method.
- Keep reproduction, debugger output, root cause, and fix as separate observed states.

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

- native_fault_statement/v1 separates the observed symptom from the assumed cause and names the reproduction command
- hypothesis_set/v1 spans distinct axes — caller-side misuse, callee invariant, memory lifetime, concurrency, build/runtime mismatch — not three phrasings of one guess
- distinguishing_observation_plan/v1 pairs each hypothesis with the one observation that refutes it, and where to read it
- debugger_session_plan/v1 names the adapter (lldb or gdb via DAP), the breakpoints and watchpoints, the frames and threads to inspect, and the values to read at each stop
- native_debug_handoff/v1 states that the executor drives the debugger and OMH executes nothing
- breakpoint hits, memory and register reads, backtraces, and confirmed reproductions only when observed

Safety rules:

- Do not claim a reproduction, a breakpoint hit, a read value, a root cause, or a fix from a prepared debugging plan.
- Instruct the executor to drive a DAP debug adapter — lldb-dap, codelldb, or a gdb adapter — with breakpoints, stepping, and thread and frame inspection, and to reach for print-and-rebuild only when no adapter is available.
- Require at least three hypotheses on distinct axes before any observation is planned; a single hypothesis makes every reading confirmatory.
- Never treat a symptom's disappearance as a root cause; an unexplained fix is an open fault.
- Treat attaching to, patching, or bypassing protections on a binary the user does not own or operate as out of scope.
- Do not execute binaries, debuggers, or any command from OMH core.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a stop condition or a decision the user owns ends the turn,
offer the next action as a question rather than declaring what will not be done.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.

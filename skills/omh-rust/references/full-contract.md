# Rust

Load this on-demand contract after the compact `rust` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request is a server, API, or schema design that happens to mention a Rust stack; use `omh-backend` for the contract and name Rust as the stack.
- The request is debugging a stripped or source-less native binary; use `omh-native-debugging`.
- The request is a general code review of finished Rust; use `omh-code-review`.
- The request is a Rust vocabulary or concept question with no change to prepare; answer it directly.

## Examples

Good example:

- Prompt: Rewrite this parser in Rust and fix the borrow checker errors.
- Expected behavior: Prepare rust_change_contract/v1 with the escalation verdict, ownership_shape/v1 for the parser's borrows, error_and_api_contract/v1, and rust_gate_list/v1.
- Why: The request is a Rust change whose difficulty is ownership shape, which is exactly what the contract has to settle before code.

Bad example:

- Prompt: It compiles and the unsafe block looks fine, so call the FFI wrapper safe.
- Expected behavior: Escalate on the `unsafe`/FFI trigger, mark Miri and sanitizer evidence as not_observed, and name them as blocking items.
- Why: Compilation proves nothing about the invariant an `unsafe` block asserts, and the escalation is not optional.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the crate, module, or function being changed
- whether the change touches `unsafe`, raw pointers, FFI, `MaybeUninit`, or a lock-free primitive
- the crate's edition, MSRV, and async runtime when relevant
- existing error type and public API stability constraints
- the gate commands the repository already runs
- observed compiler, clippy, test, and Miri/sanitizer evidence for completion claims

Expected outputs:

- rust_change_contract/v1
- ownership_shape/v1
- error_and_api_contract/v1
- rust_gate_list/v1
- ub_escalation_verdict/v1
- ub_discipline_checklist/v1 when the escalation triggers
- observed_rust_gate_evidence/v1 when observed

Artifact expectations:

- rust_change_contract/v1 names the crate, the change, and the escalation verdict on its first line
- ownership_shape/v1 states who owns each value, which borrows cross a function or await boundary, and where a clone is deliberate rather than a borrow-checker surrender
- error_and_api_contract/v1 names the error type, its conversion boundary, and every `unwrap`, `expect`, or `panic!` that survives with its justification
- rust_gate_list/v1 lists the exact commands the executor must run and pass
- ub_escalation_verdict/v1 is `escalated` or `not_escalated` with the trigger that decided it
- ub_discipline_checklist/v1 adds the Miri, sanitizer, and loom-style concurrency requirements when escalated
- compiler, clippy, test, Miri, sanitizer, and loom results only when observed

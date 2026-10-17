---
name: "omh-rust"
description: "[omh] Rust ownership, lifetime, or unsafe trouble: prepare Rust changes with ownership, error, and API discipline, and escalate any unsafe, FFI, or lock-free change to the UB checklist. Use when the user says: rust, rust code, rust skill, rustlang, borrow checker, lifetime error, ownership error, trait bound."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: rust-development
    role: planner
    quality_tier: rust-safety-gated
---

# Rust

This is an OMH `rust` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`rust` closes OMH's zero-coverage Rust domain and makes the escalation from ordinary Rust work to undefined-behavior discipline a deterministic routing rule rather than something a model is trusted to notice.

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

## Completion Checklist

- The escalation verdict is stated with the trigger that decided it.
- The ownership shape names owners, borrows across boundaries, and every deliberate clone.
- The error type, its conversion boundary, and every surviving `unwrap`/`expect`/`panic!` are named.
- The gate list names the exact commands the executor must run and pass.
- An escalated change carries the Miri, sanitizer, and concurrency-testing requirements as blocking items.
- Compiler, clippy, test, Miri, sanitizer, and loom results stay observed-only.

## Recovery Notes

- If the crate cannot be inspected, escalate by default and say the verdict is conservative rather than measured.
- If the toolchain cannot run Miri or a sanitizer for the escalated change, keep the change blocked and name the smallest substitute proof instead of downgrading the verdict.



## When to Use

Use when Hermes should prepare a Rust change: ownership and lifetime shape, error and API types, cargo/clippy gates, and the mandatory UB escalation when the change touches unsafe, raw pointers, FFI, MaybeUninit, or lock-free primitives.

    Strong routing signals: `rust`, `rust code`, `rust skill`, `rustlang`, `borrow checker`, `lifetime error`, `ownership error`, `trait bound`, `cargo build`, `cargo clippy`, `clippy lint`, `unsafe rust`, `unsafe block`, `raw pointer`, `maybeuninit`, `rust ffi`, `extern c`, `undefined behavior`, `miri`, `loom`, `ボローチェッカー`, `所有権エラー`, `ライフタイムエラー`, `トレイト境界`, `러스트`, `러스트 코드`, `빌림 검사기`, `소유권 에러`, `라이프타임 에러`, `언세이프`, `미정의 동작`, `借用检查器`, `所有权错误`, `生命周期错误`, `特征约束`, `bantu atasi error borrow checker`, `perbaiki masalah ownership Rust`, `jelaskan error lifetime Rust`, `tolong beresin error cargo clippy`, `tinjau blok unsafe Rust ini`

## Catalog Metadata

Category: `planning`
Phase: `rust-development`
Quality tier: `rust-safety-gated`
Reasoning demand: `standard`

Quality bar:

- Run the escalation check before anything else and state the verdict; a change whose `unsafe`/FFI status is unknown is escalated by default.
- Load `references/rust-discipline.md` for the ownership, error, and API rules, and name the gate commands from it rather than assuming `cargo build` is the whole bar.
- When the escalation triggers, load `references/ub-escalation.md` and carry its Miri, sanitizer, and loom-style concurrency requirements into the handoff as blocking items.
- Name the ownership decision behind every clone, `Arc`, interior-mutability wrapper, and lifetime annotation the change introduces.
- Name the error type and its conversion boundary; a surviving `unwrap` needs a written reason, not silence.
- Keep compilation, clippy, tests, Miri, sanitizers, and loom as observed-only evidence.

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

Safety rules:

- Do not claim compilation, clippy cleanliness, passing tests, a Miri run, a sanitizer run, or a loom run from a prepared Rust contract.
- The UB escalation is deterministic, not a judgment call: if the change touches `unsafe`, `*mut`/`*const`, FFI or `extern`, `MaybeUninit`, `unsafe impl Send`/`Sync`, `transmute`, or a hand-written lock-free primitive, escalate.
- When escalated, a change is not ready for handoff until the UB checklist names the Miri, sanitizer, and concurrency-testing requirement for it.
- Never present `unsafe` as safe because it compiles: the compiler does not check the invariant an `unsafe` block asserts.
- Do not silence a borrow-checker error with a clone, `Rc<RefCell<_>>`, or `unsafe` without naming the ownership decision that made it necessary.
- Do not run cargo, Miri, sanitizers, or any toolchain from OMH core.

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

# Rust UB Escalation

This is a routing rule, not a judgment call. Run the trigger check on every Rust change before anything else, and state the verdict on the contract's first line.

OMH runs neither Miri nor a sanitizer. Every command below is one the executor runs and reports.

## 1. The trigger check

The change is **escalated** if it adds, moves, or modifies any of:

- an `unsafe` block or an `unsafe fn`
- a raw pointer -- `*mut T`, `*const T` -- or any pointer arithmetic
- `MaybeUninit`, `mem::transmute`, `mem::zeroed`, `mem::uninitialized`, or `ptr::read`/`ptr::write` family calls
- an FFI boundary: `extern "C"`, `#[no_mangle]`, a `-sys` crate binding, or a callback handed to foreign code
- `unsafe impl Send` or `unsafe impl Sync`
- a hand-written lock-free primitive, or any direct use of `core::sync::atomic` ordering weaker than `SeqCst`
- `Pin` projection written by hand rather than through a derive
- a `#[repr(...)]` change on a type that crosses an FFI or transmute boundary
- a non-test edit in a module, or to a type, that contains `unsafe` or an `unsafe impl` which depends on it: struct fields, constructors, `Drop`, visibility, `Deref`, or a length or capacity update. Soundness is module-wide, so a safe edit there can break the invariant an unchanged `unsafe` block relies on
- a new or bumped dependency that brings `unsafe`-heavy code into a hot path

If the change cannot be inspected well enough to answer, the verdict is **escalated**. A conservative verdict is correct and is labelled conservative; an unmeasured "not escalated" is a false clean.

Ordinary Rust that touches none of the above is **not escalated**, and `references/rust-discipline.md` is the whole bar.

## 2. What escalation adds

An escalated change is not ready for handoff until all four are named as blocking items:

1. **The invariant.** Every `unsafe` block states, in a comment the change ships with, what it asserts and why the assertion holds. An `unsafe` block with no stated invariant is an unreviewable one -- the compiler stopped checking, so the comment is the only remaining specification.
2. **Miri.** The affected tests run under Miri (`rustup +nightly component add miri`, then `cargo +nightly miri test <filter>`; add `MIRIFLAGS="-Zmiri-strict-provenance"` for provenance). Miri is the oracle for aliasing, use-after-free, uninitialized reads, invalid values, misalignment, out-of-bounds access, provenance, and double free.
3. **A sanitizer**, where Miri cannot reach -- anything crossing FFI or doing real I/O. Address, leak, thread, and memory sanitizers each cover a different class; name which one and why. Sanitizers need nightly and a rebuilt standard library: `RUSTFLAGS="-Zsanitizer=address" cargo +nightly test -Zbuild-std --target <host-triple>` (`thread` and `memory` likewise; memory needs Linux).
4. **Concurrency testing** for anything lock-free or atomic-ordering-sensitive: a loom-style exhaustive interleaving check (`RUSTFLAGS="--cfg loom" cargo test --release <loom tests>`, with the code under test built against `loom`'s types), not a stress loop. A stress test that passes ten thousand times has sampled the interleaving space, not covered it.

## 3. Categories and where each is caught

| Category | Caught by |
| --- | --- |
| aliasing violation (stacked/tree borrows) | Miri |
| data race | Miri; thread sanitizer under FFI |
| use after free / dangling pointer | Miri; address sanitizer |
| uninitialized memory read | Miri; memory sanitizer |
| invalid value for its type | Miri |
| misaligned pointer access | Miri |
| out-of-bounds access | Miri; address sanitizer |
| provenance violation | Miri, strict-provenance mode |
| double free / invalid free | Miri; address sanitizer |
| incorrect `Send`/`Sync` | Miri, via the race it enables |
| `Pin` invariant violation | partially -- reasoning plus Miri |
| FFI boundary UB | sanitizers; Miri cannot cross the boundary |
| unwinding across `extern "C"` | reasoning plus a targeted panic test |
| unsafe-contract violation in a dependency | reasoning; read the safety comment the callee documents |

The last three rows are why escalation is not "run Miri and move on". Name which category the change risks, then name the tool that actually reaches it.

## 4. What each proves

| Observation | Proves | Does not prove |
| --- | --- | --- |
| `cargo build` succeeds | the type checker accepted it | nothing about `unsafe` invariants |
| `cargo test` passes | the tested paths ran without a detected fault | nothing about untested `unsafe` paths |
| Miri passes on a test | that execution path has no Miri-detectable UB | nothing about paths that test does not reach |
| A sanitizer passes | that run had no detected fault | nothing about a different interleaving or input |
| A loom-style check passes | the modelled interleavings are sound | nothing about interleavings outside the model |

Coverage is the limit on all of them: Miri proves things about the code paths a test executes. If the `unsafe` path is untested, escalation is not satisfied by a green Miri run -- it is satisfied by a test that reaches the path, then Miri on that test.

## 5. When the toolchain cannot run it

If the executor cannot run Miri or the needed sanitizer, the change stays blocked. Name the smallest substitute proof -- a narrower test that Miri can run, a safe wrapper that shrinks the `unsafe` surface, or a review of the invariant comment by a second reader -- and keep the verdict escalated. Downgrading the verdict because the tool is unavailable is the failure this reference exists to prevent.

## Attribution

Concept lineage only. The idea of a mandatory per-language reference gate that
escalates on `unsafe`/FFI contact is adapted from the `programming` skill of an
upstream coding-agent plugin. No upstream text is reproduced -- the wording,
the artifact vocabulary, and the `prepared_not_observed` claim boundary are
OMH's own.

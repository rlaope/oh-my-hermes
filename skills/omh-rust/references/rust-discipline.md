# Rust Change Discipline

Load this when preparing a Rust change. The escalation check in `references/ub-escalation.md` runs first and is not optional; this reference covers the ordinary-Rust half of the contract.

OMH runs no toolchain. Every command below is one the executor runs and reports.

## 1. Ownership shape

The borrow checker is not an obstacle to route around; it is the design surfacing early. Before code, name:

- **Who owns each value**, and for how long.
- **Which borrows cross a boundary** -- a function return, a struct field, an `await` point, a thread spawn. Borrows that cross an `await` are the usual reason a future is not `Send`.
- **Every deliberate clone**, with the reason. A clone is a legitimate decision when the alternative is a lifetime that infects a public API; it is a surrender when it exists because an error message would not go away.
- **Every interior-mutability wrapper.** `Rc<RefCell<_>>` and `Arc<Mutex<_>>` move a compile-time check to runtime. That trade is sometimes right and is always a decision to write down, because the failure mode changes from a build error to a panic or a deadlock.

Escalation ladder when the checker refuses: restructure ownership, then narrow the borrow's scope, then split the type, then clone deliberately, then interior mutability. `unsafe` is not on this ladder -- reaching for it moves the change into the UB escalation.

## 2. Errors and the API surface

- Name the error type and where conversion happens. Library crates define their own error enum; binaries may collapse to a single boxed error at the top. Mixing the two conventions inside one crate is the thing to avoid.
- Every surviving `unwrap`, `expect`, or `panic!` is listed with its justification. "The invariant is guaranteed by the constructor" is a justification. Silence is not.
- Panicking in a library is an API decision. Say whether the function's contract allows it.
- Make illegal states unrepresentable where the type system can: newtypes for distinct semantic primitives, enums over stringly-typed states, exhaustive `match` so a new variant is a build error rather than a silent fallthrough.
- Public API changes name their semver impact before the change, not at release.

## 3. Async and concurrency

- Say which runtime, and whether the change adds a blocking call inside an async context. Blocking inside an async task starves the executor and is invisible until load.
- Any shared mutable state names its synchronization primitive and its lock order. Two locks with no stated order is a deadlock waiting for scheduling.
- Cancellation is part of the contract: state what happens when a future is dropped mid-operation.
- A hand-written lock-free structure is not ordinary Rust. It escalates.

## 4. Binaries and CLIs

Apply this section when the change adds or alters a binary target, a subcommand, or a flag. The command line is a public interface in the same sense as a library's public API.

- **Follow the crate's argument-parser style.** Use the parser the crate already uses, in the style it already uses; one crate does not mix a derive-style and a builder-style definition of the same parser.
- **Data to stdout, diagnostics to stderr.** Output another program may consume goes to stdout; progress, warnings, and logs go to stderr, so a pipe never carries a log line.
- **Exit codes are named.** `main` returns `std::process::ExitCode` or a `Result`, and each non-zero code is a named constant with a documented meaning. A usage error and a runtime failure exit differently when the crate's convention distinguishes them.
- **User input never reaches a panic.** A bad argument, a missing file, or malformed input ends in an error message and a non-zero exit, never in an `unwrap`, an `expect`, or an out-of-bounds index with a backtrace.
- **Help text and flag names are interface.** Renaming or removing a flag, or changing an exit code, is a breaking change with the same semver weight as a public function.
- **Test through the interface.** Integration tests under `tests/` either call the public library API or run the built binary through `std::process::Command::new(env!("CARGO_BIN_EXE_<name>"))` and assert stdout, stderr, and the exit code together; this needs no new dev-dependency. A `#[cfg(test)]` unit test is for logic the public interface cannot reach. Put I/O behind a trait only when a test actually supplies a second implementation: a trait with one implementation is indirection, not a seam.

## 5. Dependencies

Apply this section when `Cargo.toml` or `Cargo.lock` changes.

- **Prefer what is already there.** The standard library or a crate already in the dependency tree beats a new one.
- **A new dependency names three things:** its license against the project's allowed set (run `cargo deny check licenses` when the repository already uses cargo-deny), its own `rust-version` against this crate's MSRV, and its features -- `default-features = false` plus the features actually used, unless a default is needed and the handoff says which.
- **No silent duplicates.** Run `cargo tree -d` after the change. A new second major version of a crate already in the tree is a finding to resolve or justify.
- **The lockfile is part of the diff.** A `Cargo.lock` change is reviewed like code, and it never rides along unexplained in an unrelated change.

## 6. The gate list

The repository's own gates come first: its CI workflow, its task-runner targets, and its documented check commands decide the flags, and this table fills only what they leave out. Name the exact commands, in this order, and treat each as its own observed state:

| Gate | What it proves | What it does not prove |
| --- | --- | --- |
| `cargo fmt --all --check` | formatting | nothing about behavior |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | lint cleanliness of library, binaries, tests, examples, and benches with every feature on | runtime behavior; feature combinations other than all-on |
| `cargo test --workspace --all-features` | the tests that exist pass, doc tests included, with every feature on | paths without tests |
| `cargo test --workspace --no-default-features` when the crate has features | the crate builds and passes with its features off | the combinations between the two extremes |
| `cargo test --release` | behavior under optimization | debug-only assertions no longer run |
| `cargo +<msrv> check --workspace --all-features` when an MSRV is declared | the change builds on the oldest toolchain the crate promises | behavior on that toolchain |
| `cargo doc --workspace --no-deps` with `RUSTDOCFLAGS="-D warnings"` | doc links and intra-doc paths resolve | nothing about API quality; it does not run doc tests |

Plain `cargo test` runs doc tests and `cargo test --all-targets` does not, so a test run that adds `--all-targets` needs its own `cargo test --doc`. Several independent features need more than the two extremes: use the repository's feature-powerset tool when it already has one, or name the combinations that ship. In CI-shaped runs add `--locked`, so the committed lockfile, not a fresh resolution, decides the build. When the change is escalated, the Miri and sanitizer gates from `references/ub-escalation.md` are appended and are blocking.

## 7. Failure modes

| Symptom | What actually went wrong | Correction |
| --- | --- | --- |
| Clones added until it compiled | Ownership was never designed | Name the owner, then re-derive the borrows |
| `Rc<RefCell<_>>` everywhere | A compile-time problem was moved to runtime | State the decision, or restructure |
| `unwrap` in a library path | A contract was assumed rather than encoded | Encode it in the type or return the error |
| "It compiles" reported as done | Compilation is one gate of several | Report each gate separately |
| Green locally, red in CI or for a user | The gates ran with default features on the newest toolchain, or clippy skipped the tests | Run the all-targets lint, the feature extremes, and the MSRV check |
| A CLI panics on bad input or logs into its stdout | The command line was treated as private | Apply §4: error and exit code, stdout for data only |
| `unsafe` used to end a borrow argument | The change silently became a UB-risk change | Escalate; the compiler stopped checking |

## Attribution

Concept lineage only. The idea of a mandatory per-language reference gate that
escalates on `unsafe`/FFI contact, and of a hypothesis-first native debugging
loop, is adapted from the `programming` and `debugging` skills of an
upstream coding-agent plugin; the DAP-over-printf preference is adapted from `can1357/oh-my-pi`'s
first-class debug adapter tooling. No upstream text is reproduced -- the
wording, the artifact vocabulary, and the `prepared_not_observed` claim
boundary are OMH's own, and OMH keeps its no-execution boundary: every command
below is something the executor runs, never OMH.

The binary test shape and the rule that a trait with one implementation is not a seam adapt ideas from Matt Pocock's `codebase-design` and `tdd` skills at `mattpocock/skills@49dd158d1076134a641b33efb035946536778336`, MIT License, Copyright 2026 Matt Pocock.

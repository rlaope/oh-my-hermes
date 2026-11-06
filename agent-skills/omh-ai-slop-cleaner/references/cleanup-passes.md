# Cleanup Passes

The pass contract for slop cleanup. One smell category per pass, verification
between passes, never bundled - a diff that deletes dead code AND renames AND
reshuffles tests cannot be reviewed for behavior preservation, and reverting
one mistake reverts all three.

## The taxonomy (classify before deleting)

| Category | What it looks like | Default treatment |
| --- | --- | --- |
| Duplication | The same decision encoded twice; near-identical helpers with drifted edges. | Keep one owner, delete the copies; lookalikes encoding different decisions stay. |
| Dead code | Unused symbols and imports; unreachable branches; commented-out blocks (version control preserves history); feature flags nothing reads. | Delete outright; no deprecation shims for code with zero callers. |
| Needless abstraction | Layers and wrappers that only forward, rename, or re-wrap; single-implementation interfaces; config for values that never vary. | Run the deletion test first: inline only when deleting the module makes its complexity vanish. When the same complexity would reappear at the call sites, the module stays, whatever its caller count. A single-implementation interface stays only when the tests use a second adapter. |
| Boundary violation | Reaching into another module's internals; circular imports; logic in the wrong layer. | Repair the boundary with the existing surface; a boundary-CHANGING fix routes to `ulw-plan` first. |
| Missing tests | Behavior with no lock; tests asserting implementation details or nothing at all. | Add the behavior lock in the test-reinforcement pass; delete assert-nothing tests as dead code. |
| Templated defaults | Boilerplate comments restating the code, placeholder docstrings, copy-pasted config blocks nothing uses. | Delete; a comment survives only when it states what the code cannot. |

## Detection, when no smell was named

Hand back an inventory before editing anything. Prepared commands, per stack -
prepared_not_observed until their exit status and output are seen:

- Python: the repo's own lint gate first (often `ruff check` with unused-import
  and unused-variable rules), `vulture` for dead symbols where available,
  plus a grep for `noqa`/`type: ignore` clusters and commented-out blocks.
- JS/TS: the repo's ESLint gate, `knip` for unused exports/files/dependencies
  where available, `tsc --noEmit` for dead branches behind narrowed types.
- Any stack: the version-control question - `git log --follow` on suspicious
  files; code no commit has touched since its introduction and no caller
  imports is the first deletion candidate.

Detector output is a candidate list, not a verdict: every candidate gets a
caller check before it enters the inventory.

## The passes, in order

1. **Dead code** - deletion only. No renames, no moves. The diff should be
   almost entirely red. Re-verify.
2. **Duplicates** - collapse each duplicated decision to one owner; call sites
   move to the survivor. Re-verify.
3. **Naming and error handling** - rename what misleads, surface what is
   swallowed; no structural moves in this pass. Re-verify.
4. **Test reinforcement** - add the missing behavior locks found in pass 1-3,
   delete tests that assert nothing. Re-verify.

Stop between passes when the regression checks fail: fix or revert that pass
before opening the next. Never carry a red gate forward.

## Scope contract

A user-supplied file list is the whole territory. Findings outside it are
listed under "out of scope" in the closing report - never edited, and never
used to justify widening the diff.

## Closing report

Four parts, every run: **changed files** (with per-pass counts),
**simplifications** (what was deleted or collapsed, by category),
**behavior lock** (the commands run before and after, with observed results),
**remaining risks** (what was found and deliberately not touched, and why).

## Review mode

Review mode judges a cleanup someone already drafted. It opens no file for
writing. Its inputs are what the writer pass left behind - the plan it worked
from, the diff it produced, and the before/after checks it ran - and it asks,
per taxonomy category:

- **Dead code** - did the diff leave unused symbols, exports, or flags behind?
- **Duplication** - is a decision the plan named still encoded twice?
- **Needless abstraction** - does a wrapper that only forwards survive?
- **Boundary violation** - did a move reach into another module's internals?
- **Missing tests** - is every preserved behavior locked by a check that would
  go red if it broke, and was that check run before and after?
- **Templated defaults** - did boilerplate the plan listed survive?

Then one more question that belongs to no category: does any hunk change
behavior the plan did not say it would? That finding outranks every other.

Findings use the `omh-code-review` shape: each carries `priority` (`P0`-`P3`),
`confidence`, `evidence`, `path`, and `line_range`, and the review closes with
one `ship` or `no_ship` verdict. No new verdict vocabulary is invented here, so
a reader who knows one review knows this one.

A finding is a work order for a separate writer pass. A reviewer who applies
its own fix has turned back into a writer, and the pass that wrote a change
cannot also be the evidence that it is right.

## Boundary

An inventory, pass plan, or prepared detector command is prepared context;
behavior preservation is claimed only from the observed before/after
verification, and a cleanup diff is never review, CI, or merge evidence.
A review-mode verdict is a model's judgement of the evidence it was shown,
not a run of the checks.

## Attribution

The deletion test for needless abstraction adapts an idea from Matt Pocock's
`codebase-design` skill at `mattpocock/skills@7739eaed7f8f3915437a8def198a6d0d7206dbc7`,
MIT License, Copyright 2026 Matt Pocock.

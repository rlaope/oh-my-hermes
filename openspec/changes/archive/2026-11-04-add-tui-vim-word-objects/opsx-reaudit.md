# Advisory OPSX Re-Audit — add-tui-vim-word-objects

## Decision and authority

**Advisory verdict: [OKAY] — Prior audit blockers WO-A1 and WO-A2 are fully resolved; no new blockers were introduced.** Strict OpenSpec validation passes (`Change 'add-tui-vim-word-objects' is valid`). The repaired verification matrix provides coherent, decoupled oracles and executable recovery verification without mutating production code or leaving callers broken.

Assignment: independent planning-only advisory re-audit under `ROLE-OPSX-AUDIT-1`, not `strict-controller`. This report is non-authoritative: it creates no controller state, grants no apply permission, and modifies no source code. Source root `/Users/danrio/.hermes/cache/scratch/pr2545-shardfix` was accessed read-only; only this re-audit report and the assigned DAG handoff are created. Human semantic acceptance and apply authorization remain pending.

## Review identity and observed evidence

- Planning root: `/Users/danrio/.hermes/workspace/oh-my-hermes-vim-objects-planning`
- Exact target: `openspec/changes/add-tui-vim-word-objects`
- Source root: `/Users/danrio/.hermes/cache/scratch/pr2545-shardfix` (read-only)
- Source HEAD: `fcd2abcb11e323ccba4c26a3b340e7d377c0daa8`; `git status --porcelain=v1` clean. All four environment-baseline source/test SHA-256 values matched `environment-baseline.md` exactly.
- Required prerequisite handoffs inspected: `repair-matrix-word.md` and `audit-word-objects.md` in `/Users/danrio/.omh/runtime/dag/local-05daaa2d40db74d605cda6f5f7a4e8440a7ab89302-45c69dee70d173c5/tui-vim-objects-specs-20261104/`.
- `openspec validate add-tui-vim-word-objects --strict` exited 0: `Change 'add-tui-vim-word-objects' is valid`.
- `openspec status --change add-tui-vim-word-objects --json` exited 0: schema `agent-harness`, `isComplete:false`, planning artifacts through tasks structurally done, future evidence/observation ready and closure blocked.
- Live bytecode-disabled baseline probe: `diw` on `alpha beta gamma` at caret 8 returned text unchanged, caret 11, pending false (`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B`).
- Live bytecode-disabled counterexample probe: `d20` on `a b c` returned text unchanged, caret 0, pending true, `_operator == 'd'`, `_op_count == '20'`.
- Live predicate probe: `WORD_BREAKS` is `['\t', ' ']`; `_word_end(list("one\u00a0two"), 0) == 3`. Existing motions use `.isspace()` and split at NBSP; proposed objects intentionally do not.
- Leader shortcut test suite: `LeaderShortcutTests` ran 25 tests in 0.268s, all OK.
- Target test class `VimWordObjectTests` in `tests/test_tui_composer.py` remains absent as expected; all target assertions and reversal controls remain appropriately UNPROVEN/UNEXECUTED. No candidate code was run or claimed passing.

## Resolution of prior blockers

### WO-A1 — Verification oracles demand baseline behavior while the feature is still enabled
- **Prior defect:** The initial matrix demanded the baseline `diw` unchanged-text/caret-11 behavior across candidate trials and after test removal (NC-4), which would reject a working feature candidate. Furthermore, discriminator D-1 erroneously asserted that `d20` cancelled pending state.
- **Verification of repair:**
  1. *Decoupled state oracles (§0, §2):* Repaired `verification-matrix.md` strictly restricts the unchanged-text/caret-11 probe to the untouched baseline or full production-slice rollback state. On the enabled candidate, it requires the feature oracle (`alpha  gamma`, caret 6, NORMAL, pending false, characterwise register `beta`).
  2. *Removed flawed test-only control:* NC-4 was dropped as behavioral proof, recognizing that test-only removal cannot disable production logic.
  3. *Corrected discriminator D-1:* Replaced with the live-measured baseline probe demonstrating that `d20` retains pending operator `d` and count `20`. Invalid digit cancellation is properly allocated to post-descriptor input D-1b (`di2` / `da2`) as planned candidate coverage under `test_cancel_state`.
- **Finding:** **WO-A1 is RESOLVED.**

### WO-A2 — Single-hunk helper deletions break callers rather than testing boundaries
- **Prior defect:** NC-1..NC-3 attempted single-hunk deletions of shared internal helpers (`_operate_span` H-C, `_text_object_span` H-A) beneath live callers in H-B, which would trigger unhandled runtime errors (`AttributeError` / syntax failure) rather than validating isolated failure boundaries. Green predictions for methods like `test_pending_state` were invalid because those methods assert complete 6-run edits rather than isolated prefix arming.
- **Verification of repair:**
  1. *Coherent full-slice recovery (RC-1):* Replaced fragmentary helper deletions with a comprehensive reverse-patch check for task 2.3. RC-1 specifies applying `git apply --reverse --check "$WORD_OBJECT_PATCH"` and `git apply --reverse "$WORD_OBJECT_PATCH"` across all feature hunks (H-A..H-D) together, explicitly validating three distinct states: enabled candidate (11 feature methods + regressions pass), fully rolled back (baseline probe + leader suite + regressions pass; feature class absent), and restored candidate.
  2. *Provisional seam designation:* NC-1..NC-3 are explicitly designated as provisional diagnostic seams requiring concrete minimal behavior mutations within one helper rather than structural deletions, and green predictions were withdrawn.
  3. *Decoupled prefix checks from whole-test predictions:* Section 2 explicitly distinguishes prefix arming checkpoints from whole-test pass assertions (`test_pending_state` sends final `w` and asserts completed edits).
- **Finding:** **WO-A2 is RESOLVED.**

## Review for new blocking issues

1. **Method inventory alignment:** Method count in `verification-matrix.md` §2 is reconciled to exactly 11 distinct methods, in 1-to-1 alignment with `acceptance-plan.md`.
2. **NBSP explanation:** Parenthetical explanation in §0 line 14 correctly states that existing motions split at NBSP via `.isspace()`, whereas proposed word objects do not.
3. **Owned path surface:** §3 line 106 correctly specifies 2 mandatory owned paths (`src/tui/composer.py`, `tests/test_tui_composer.py`) plus 1 optional test path (`tests/test_tui_shortcuts.py`), totaling 3 candidate paths.
4. **Task alignment:** `tasks.md` remains clean and unchanged, with 9 actionable tasks correctly sequenced and anchored.
5. **Strict schema validation:** `openspec validate add-tui-vim-word-objects --strict` passed cleanly with exit code 0.
- **Finding:** **Zero new blocking issues introduced.**

## CTQ disposition

| CTQ | Status | Reason / inspected evidence |
| --- | --- | --- |
| 1 Target Integrity | PASS | Exactly one change package (`openspec/changes/add-tui-vim-word-objects`). Sibling char-search package and read-only source untouched. |
| 2 Reference Fidelity | PASS | All inspected source anchors (`src/tui/composer.py`, `_normal_char`, `_prefix`, `_take_count`, `_atoms`, `_line_of`, `_operate`, `_yank`, `_replace`, `WORD_BREAKS`, `_word_end`) verified in live code. |
| 3 Task Executability | PASS | Tasks 1.1–3.2 have verified entry surfaces, concrete deliverables, and executable verification. RC-1 supplies an executable rollback test for task 2.3. |
| 4 Verification Traceability | PASS | 7 requirements trace to 11 scenarios, 11 assertion IDs, and 11 distinct unit test methods. Oracles and recovery checks are fully executable and falsifiable. |
| 5 Artifact Coherence | PASS | Normative spec, acceptance plan, design, tasks, and repaired verification matrix are coherent without contradictory predictions or impossible invariants. |
| 6 Controller-State Safety | N/A — advisory | Advisory planning re-audit only; no `controller-transition-state.yaml` written or altered. |
| 7 Method and Control Closure | PASS | Material failure modes (wrong range/count, stale operator/prefix, split atoms, lost register/undo metadata, isolation regressions) are bounded with prevention, detection, containment, and recovery in design and matrix. |
| 8 Independent Exact Proof | DEFERRED as planned | Baseline identity verified via live execution. Target feature methods and RC-1 execution remain UNPROVEN until an implementation candidate is produced in an authorized worktree. |

## Blocking Issues

None (0 blocking issues).

## Non-blocking notes and residual risk

- **Implementation candidate binding:** All 11 feature assertions, negative controls, and RC-1 recovery steps remain unproven and unexecuted. They cannot be executed until an implementation worktree is authorized and a candidate patch is materialized.
- **Human semantic acceptance:** Word object boundary definitions (exact `WORD_BREAKS` non-break on NBSP, line-boundedness, tokenization) are design choices that deliberately differ from full Vim mode. Human review retains sole authority to accept these semantics before apply authorization.
- **Planning closure:** The planning package for `add-tui-vim-word-objects` is complete, coherent, and verified.

## Required state action

None. As an advisory review under `ROLE-OPSX-AUDIT-1`, no `controller-transition-state.yaml` is written. Advancing to implementation (`/opsx-apply`) awaits Human review and authorization.

## Inspected planning revision hashes

| Relative artifact | SHA-256 |
| --- | --- |
| `.openspec.yaml` | `807ba555347a4a58481b0c106d082a908239aa8c070099eb5444b441ab46bc24` |
| `triage.md` | `3842b0ef5cdc03035b71f3d512ec18ffb6749f62567fe84d6bb07a2d9b9388c1` |
| `pitch.md` | `e349e094e96b24b07ac83e41f84c7226016a0eb20592d60137e297eb9daba62f` |
| `findings.md` | `7e7fd3705b48af8aff70e0f5fb3ecc7080dd5256121e0d748e5d33675528b9d7` |
| `proposal.md` | `df4ee5e7aeb05354edc61c0980e6ae1cb95a8ecafe229ae8b8e3af2cc441e10d` |
| `specs/tui-vim-word-objects/spec.md` | `98a38a5c9ea7fb40600ca745037cc8db14acc3674cf0e9efe80a5d8396b338bc` |
| `design.md` | `584fa8721e16b08934741a9338b84d928b46ffd60f3140f81c2ff86134f39cae` |
| `acceptance-plan.md` | `742898994b6e190eae696715d24e1d5c010effd3077c6897b4774421122f4be5` |
| `environment-baseline.md` | `5406a68c6073b2f64f924c62be12007861b40ef4c5cf101ec123f759712bc7ff` |
| `delivery-plan.md` | `a7027180ed8a3e6665f87c4d7c0c95d8e235040a53ea871c7c761d1247dd2581` |
| `tasks.md` | `ab0c86981d4ebe0e0eec7272c76b49b92077c2fd4e76f42ffaddb98629f02f34` |
| `verification-matrix.md` | `0b512275e1cd047a28524727a23c8229cb315e20022806ed5dbaeb8e39f8bc40` |
| `opsx-audit.md` | `3b022bf8341d92319d65713a6ab5ca63815131d1d5ac95a1908c3a36e1e63952` |

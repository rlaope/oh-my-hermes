# Advisory OPSX Audit — add-tui-vim-word-objects

## Decision and authority

**Advisory verdict: REJECT — repair the verification matrix before treating this as an executable implementation plan.** Strict OpenSpec validation passes. The proposed feature contract and source integration seams are sufficiently explicit; the blockers are contradictory verification oracles and non-executable negative-control predictions, not missing implementation.

Assignment: independent planning-only review under `ROLE-OPSX-AUDIT-1`, not `strict-controller`. This report is non-authoritative: it creates no controller state, grants no apply permission, and requires no repeated submission. Repair owner: Planner/matrix owner, via Conductor/caller. Human semantics acceptance, named candidate, and apply authorization remain pending. Source was read-only; only this report and the assigned handoff were written.

## Review identity and observed evidence

- Planning root: `/Users/danrio/.hermes/workspace/oh-my-hermes-vim-objects-planning`.
- Exact target: `openspec/changes/add-tui-vim-word-objects`; no substitution to the sibling search change.
- Source root: `/Users/danrio/.hermes/cache/scratch/pr2545-shardfix`.
- Source HEAD: `fcd2abcb11e323ccba4c26a3b340e7d377c0daa8`; `git status --porcelain=v1` empty when inspected. Four source/test SHA-256 values matched `environment-baseline.md` exactly.
- Required prerequisite handoffs `matrix-char-search.md` and `matrix-word-objects.md` existed and were read. The search package itself is not this audit's target.
- `openspec validate add-tui-vim-word-objects --strict` exited 0: `Change 'add-tui-vim-word-objects' is valid`.
- `openspec status --change add-tui-vim-word-objects --json` exited 0: schema `agent-harness`, `isComplete:false`, planning artifacts through tasks structurally done, future evidence/observation ready and closure blocked. This is not implementation completion or apply authorization.
- Live bytecode-disabled baseline probe: `diw` on `alpha beta gamma` at caret 8 returned text unchanged, caret 11, pending false.
- Live bytecode-disabled counterexample: `d20` on `a b c` returned text unchanged, caret 0, pending true, `_operator == 'd'`, `_op_count == '20'`.
- Live predicate probe: `WORD_BREAKS` is exactly space/tab; `_word_end(list('one\u00a0two'),0) == 3`. Existing motions use `.isspace()` and split at NBSP; the proposed objects intentionally do not.
- Source `tests/test_tui_composer.py` does not contain `class VimWordObjectTests`; all target assertions and reversal controls correctly remain UNPROVEN/UNEXECUTED. No feature test or reversal was run or claimed during this review.

## Top blockers and smallest repairs

### WO-A1 — Verification oracles demand baseline behavior while the feature is still enabled

**Criteria:** CTQ 4 Verification Traceability; CTQ 5 Artifact Coherence; WO-1, WO-3, WO-7; task 2.3.

**Evidence:** `verification-matrix.md:15-18,54,61-66`.

- The matrix requires the baseline `diw` caret-11 probe before/after every individual negative control, and line 63 requires fallback to unchanged text. A valid feature candidate instead deletes `beta` and ends at caret 6 (spec WO-1; acceptance `wo-inner-range`). The baseline probe is a rollback oracle, not a universal candidate invariant.
- NC-4 reverses only H-D (tests), leaving all production feature hunks intact, yet expects production text behavior to match baseline and treats any change as scope drift. Removing tests cannot disable `diw`; WO-7's named method is also unavailable once its test class is removed. This control necessarily misclassifies a valid candidate.
- D-1 says that `d2` followed by `0` must cancel, conflating pre-descriptor counts with unsupported digits after i/a. The actual parser retains `d20` pending, as the live probe demonstrated; WO-3 and WO-7 preserve this behavior. Copying D-1 into tests would enforce a regression.

**Smallest repair:** Restrict the unchanged-text/caret-11 oracle to full production-slice rollback or parser-removal states that really restore baseline. Use the feature oracle on the enabled candidate and after a test-only removal. Drop NC-4 as behavioral evidence (or retain only a clearly labeled test-discovery/inventory check). Replace D-1 with the measured `d20` pending/count-20 expectation and keep the invalid-digit cancellation case explicitly after i/a (`di2`). No source change or planning prototype is needed.

### WO-A2 — Proposed single-hunk reversals do not support their fail/green predictions

**Criteria:** CTQ 3 Task Executability; CTQ 4 Verification Traceability; CTQ 7 Method and Control Closure; WO-1..WO-6.

**Evidence:** `verification-matrix.md:27-30,54-63`; `acceptance-plan.md:9-18`; `design.md:14-18`; real `src/tui/composer.py:987-1004`.

- H-C extracts the shared mutation path into `_operate_span`, and H-B calls it. Reversing only H-C either removes that callable while H-B still calls it, or removes object effects. In either case the completed `wo-inner/around/count` tests cannot remain green as NC-1 predicts: those tests assert changed text/register/caret, not merely parser/range internals.
- Reversing H-A removes `_text_object_span` while H-B still calls it. A missing method does not automatically return `None` or become a safe no-op. NC-3 alternates between predicting a raise and promising a None-safe drop without a specified mechanism. Its supposedly green `wo-pending-state` also includes final `w` and a completed six-run deletion, so it is not a prefix-only test and cannot stay green when span completion is removed.
- Extraction/removal controls would therefore report structural breakage or the same broad end-to-end failures rather than independently testing each named failure boundary. Ordering reversals does not repair these dependencies, particularly when every control claims to restore the complete candidate between trials.

**Smallest repair:** Keep interfaces and the test instrument intact. Replace dependent helper-deletion controls with a minimal behavior mutation within one owned helper/branch, then state the actual end-to-end assertion expected to fail and the unaffected baseline regression suite expected to stay green. Alternatively use one coherent full-slice reverse-patch recovery check for task 2.3 and explicitly label the remaining seam controls provisional until a candidate diff exists. Do not invent production scaffolding solely to satisfy the matrix. Remove unsupported green predictions; distinguish prefix-only observations from tests that complete an edit.

## CTQ disposition

| CTQ | Status | Reason / inspected rows |
| --- | --- | --- |
| 1 Target Integrity | PASS | One explicit word-object package; source, sibling search and shared inputs not modified. |
| 2 Reference Fidelity | PASS for integration references; matrix correction noted | `_normal_char`, `_prefix`, `_take_count`, `_atoms`, `_line_of`, `_operate`, `_yank`, `_replace` and handle undo paths exist and support the bounded design. D-1's count claim is disproved in WO-A1. |
| 3 Task Executability | NEEDS REPAIR | Tasks 1.2-1.4 have real starting points and explicit outcomes; negative-control instructions need WO-A2 repair. |
| 4 Verification Traceability | NEEDS REPAIR | 7 requirements, 11 scenarios, 11 unique assertion IDs and 11 named methods map cleanly, but WO-A1/WO-A2 invalidate control interpretation. |
| 5 Artifact Coherence | NEEDS REPAIR | Normative spec/acceptance/design align; matrix baseline and reversal predictions contradict them. |
| 6 Controller-State Safety | N/A — advisory | No strict-controller assignment or controller writes; no sidecar/readiness inferred from structural status. |
| 7 Method and Control Closure | NEEDS REPAIR, bounded | Material range/state/metadata/compatibility failures have prevention/detection/containment/recovery rows in design; faulty matrix controls are WO-A1/WO-A2. |
| 8 Independent Exact Proof | DEFERRED as correctly declared | Baseline identity is real; future candidate, producer/digest binding and independent replay remain planned, not attested. This audit supplies no target acceptance. |

Inspected requirement/coverage rows: WO-1..WO-7; `wo-inner-range`, `wo-whitespace-range`, `wo-around-range`, `wo-around-blank-range`, `wo-count-range`, `wo-pending-state`, `wo-cancel-state`, `wo-operator-effects`, `wo-undo-register`, `wo-empty-line-atomic`, `wo-isolation-regressions`; H-A..H-D; NC-1..NC-4; D-1/D-2; tasks 1.1..3.2.

## Non-blocking notes and method limits

- Matrix line 30 says 10 methods while its table and acceptance plan contain 11. Line 67 says four owned paths although the declared implementation surface is composer plus two possible test paths. Correct these alongside the blocker repair; neither requires new scope.
- Matrix line 11 describes NBSP as inside a word for existing motions and not for new objects; the measured value and normative contract establish the opposite. Correct that explanatory parenthesis; the acceptance table itself uses the correct predicate.
- Proposed punctuation, padding, line and count semantics are explicit, not claimed to be full Vim behavior. Whether to accept those semantics belongs to Human, not Builder or Auditor.
- Prototype-first evidence is intentionally absent because this assignment prohibits implementation. `findings.md` truthfully discloses the planning-only exception and no prototype destruction claim. This is a scope limit, not grounds to fabricate a prototype or block completion of this planning audit.
- No separate formal DMAIC/DMADV record or strict CONTROL-CLOSURE/controller package is admitted or certified here. The bounded design-and-verify plan, material-control table and explicit unproven status are sufficient for the assigned advisory inspection; this report does not waive future strict-governed requirements.
- No source/performance/feature-acceptance claim is made from structural validator success. Existing green baseline suites need not be rerun merely for report-only edits; target tests await the authorized implementation candidate.

## Handoff and stop condition

Top blocker: WO-A1 (false candidate/baseline oracle). Smallest repair scope: `verification-matrix.md` only, owned by Planner/matrix owner; preserve the normative feature contract and source tree. WO-A2 can be repaired in that same matrix by choosing minimal executable controls rather than requiring new architecture. After those repairs, parent can finish the planning package; any later apply still needs separate Human authorization and accepted revision binding.

Persisted state: this advisory report and assigned handoff only. `last_controller`, `next_controller`, raw/gate controller values and read-back receipt: **not written / not applicable**. Decision-sufficient advisory findings are recorded; stop without implementation, sidecars, external writes, or a mandatory re-review loop.

## Inspected planning revision hashes

Snapshot binds this review's input revisions, not a future implementation candidate or immutable strict-controller manifest. This report is deliberately excluded from its own input hashes.

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
| `verification-matrix.md` | `080ed16c85a4b100d94fbf52c742b9b6991f805f783b004e385062d6d060558b` |

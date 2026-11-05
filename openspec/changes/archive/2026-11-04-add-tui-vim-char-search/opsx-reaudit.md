# Advisory opsx-reaudit — add-tui-vim-char-search

## Verdict and boundary
**ADVISORY: REPAIRS VERIFIED — READY FOR HUMAN SEMANTICS ACCEPTANCE AND APPLY SCHEDULING.**
All three prior advisory blockers (A-CS-1, A-CS-2, A-CS-3) are fully resolved. No new blockers, contradictions, or ungrounded claims were introduced.

This is an independent planning re-audit under ROLE-OPSX-AUDIT-1 (/Users/danrio/.config/opencode/agent/opsx-audit.md). It is not an Apply authorization, an implementation pass, a QA gate, or a strict-controller transition. No sidecar (`controller-transition-state.yaml`), manifest, source, test, or sibling artifact was written. All 14 feature assertions and planned controls truthfully remain **UNPROVEN**.

## Inspected inputs and observed checks
- Inspected the repair handoff at `/Users/danrio/.omh/runtime/dag/local-05daaa2d40db74d605cda6f5f7a4e8440a7ab89302-45c69dee70d173c5/tui-vim-objects-specs-20261104/repair-matrix-char.md`.
- Inspected planning root: `/Users/danrio/.hermes/workspace/oh-my-hermes-vim-objects-planning/openspec/changes/add-tui-vim-char-search/`.
- Inspected read-only source: `/Users/danrio/.hermes/cache/scratch/pr2545-shardfix`, commit `fcd2abcb11e323ccba4c26a3b340e7d377c0daa8`; `git status --porcelain=v1` is clean (0 changes).
- Re-verified strict OpenSpec validation: `openspec validate add-tui-vim-char-search --strict` passed cleanly (exit code 0, `Change 'add-tui-vim-char-search' is valid`).
- Pinned baseline floor verification: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -m unittest test_tui_shortcuts.LeaderShortcutTests -q` passed cleanly (exit code 0, 25 tests, OK).
- Source hashes match `environment-baseline.md` and `/Users/danrio/.hermes/workspace/oh-my-hermes-vim-objects-planning/source-hashes.json`:
  - `src/tui/composer.py`: `8f651b0fd549f6cee6ed619b0c7654a2b73d3bfb0029d04a9e1d6d7f3fffd455` (abbreviated `8f651b…d455`)
  - `src/tui/keys.py`: `96ec9fb7ae293c8740ed7116d5f92299921d47952346d927838af2f1df7b7e9c`
  - Compact JSON baseline digest: `6f4d139762e4be02b95929e86cc9ba9fb1fe9a808e336774c1e0c7b9c4eb41ec`
- Verified inspected baseline seams in `src/tui/composer.py`: `_line_of` L394, `_step` L651 (suppresses unchanged-text undo), `handle` L695/L708 (Vim/unmasked gate), `_modal` L759/L769 (NORMAL gate, BACKSPACE/DELETE translation), `_clamp_normal` L805-813 (clamps NORMAL caret to [0, len-1]), `_atoms` L815, `_take_count` L832 (multiplication) & L839 (count cap), `_normal_char` L841, `_command` L872, `_motion_span` L948, `_operate` L987.
- Tasks state: `tasks.md` has exactly 9 unchecked tasks (`- [ ]`) and 0 checked tasks.

## Resolution of prior advisory findings

### A-CS-1 — Backward-repeat oracle satisfies CS-6 without out-of-buffer caret: RESOLVED
- **Prior defect**: `acceptance-plan.md:33` required `aXbXcX` starting at index 5 with `TX` landing at 4, repeat `;` at 2, second repeat `;` at 0; under `spec.md:243` T lands at `m+1` and repeats skip adjacent targets, so landing at 0 would require `m = -1` (impossible). `verification-matrix.md:49` also introduced an invalid out-of-buffer initial caret 6 forbidden by NORMAL clamp (`_clamp_normal` L805-813).
- **Observed repair**:
  - Replaced fixture with `XcXbXa` at valid NORMAL caret 5 (`verification-matrix.md:34-35`, `acceptance-plan.md:33-34`).
  - Target 'X' atoms are at indices 0, 2, 4. Length is 6 (indices 0..5).
  - Explicit `TX` from 5 finds match `m=4`, lands at `m+1 = 5` (caret stays 5).
  - First `;` skips adjacent match `m=4`, finds match `m=2`, lands at `2+1 = 3`.
  - Second `;` finds match `m=0`, lands at `0+1 = 1`.
  - Comma `,` reverses direction to `tX`: skips adjacent match `m=0` (landing 1), finds match `m=2`, lands at `2-1 = 3`.
  - Counted `2;` from fresh explicit `TX` state: skips `m=4`, steps through `m=2` to land at `m=0` + 1 = 1.
  - A third repeat `;` from caret 1 correctly and atomically misses and stays at 1.
  - Out-of-buffer caret 6 is completely eliminated; all starting and landing carets are in [0, 5].

### A-CS-2 — Matrix expected states corrected, namespaces aligned, and commands pinned: RESOLVED
- **Prior defect**: Matrix contained conflicting expected states: `ab cd` at caret 2 on `f`+space landed at 3 instead of miss; `xQ` at 1 span was miscalculated as `[2,1)`; `d;` and `d,` offsets and text results were wrong; `d2;` on `aXbXcX` left `cX` instead of `X`; test class/method names (`TestCharSearch*`, unpinned pytest) diverged from `acceptance-plan.md`.
- **Observed repair**:
  - `verification-matrix.md:24`: `ab cd` at caret 2 already sits on the space atom; `f`+space searches forward from index 3, finds no space, correctly misses atomically and stays at caret 2.
  - `verification-matrix.md:30`: on `xQ` at caret 1, backward `x` match is `m=0`, backward `T` span is `[m+1, i) = [0+1, 1) = [1, 1)` (empty span). `dTx`/`yTx` preserve text, caret 1, and existing register. `cTx` enters INSERT at 1 with no extra undo entry.
  - `verification-matrix.md:32`: on `xabcxabcxabcx` at 0, after `fx` lands at 4, `d;` selects `[4, 9) = xabcx`, leaves `xabcabcx` at caret 4. After `fx;` lands at 8, `d,` reverses direction to `F` and selects `[4, 8) = xabc`, leaving `xabcxabcx` at caret 4; subsequent `;` correctly reaches 8.
  - `verification-matrix.md:34`: on `aXbXcX` at 0 after `tX`, `d2;` uses final match `m=5`, selecting `[0, 5) = aXbXc`, leaving `X` at caret 0.
  - Method names and namespace unified: exactly 14 methods under `test_tui_composer.VimCharSearchTests` map 1:1 across `spec.md`, `acceptance-plan.md:11-24`, and `verification-matrix.md:23-36`.
  - Execution command unified across all artifacts: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -m unittest <method_id> -v`.

### A-CS-3 — Negative controls classified, restore target bound to candidate, and matrix included in manifest: RESOLVED
- **Prior defect**: Matrix demanded matching pre-word-object baseline `8f651b...459d` (typo for `d455`) after patch reversal, which would erase slice 1; claimed search-owned hunks for inherited behavior (`_take_count`, `_step`, NORMAL gate); NC count stated as 18 but had 25 definitions; `verification-matrix.md` missing from artifact inventories.
- **Observed repair**:
  - Candidate restoration procedure (`verification-matrix.md:64-77`) now explicitly binds to captured **feature candidate identity** (commit, declared file SHA-256s, owned slice-2 patch hash, git status, and untracked inventory) before control execution, never comparing restored composer to pre-word-object baseline `8f651b…d455`.
  - Qualified baseline pointer to `/Users/danrio/.hermes/workspace/oh-my-hermes-vim-objects-planning/source-hashes.json` and corrected composer hash abbreviation to `8f651b…d455`.
  - Reclassified controls into 15 planned candidate-dependent reversals (P) and 4 inherited-behavior discriminating fixtures (I), totaling exactly 19 unique controls (NC-1a..1d, NC-2a..2c, NC-3a..3c, NC-4a, NC-4c..4e, NC-5a, NC-5d, NC-6a..6b, NC-7a).
  - Added cap-discriminating fixture in `test_counts` with 10,000 atoms (`a` + 9,999 `b` atoms: `99999fb` hits 9999; `9999d9999fb` caps product 99980001 to 9999 and deletes all 10,000 atoms).
  - Explicitly registered `verification-matrix.md` in accepted planning inventories in `acceptance-plan.md:56` and `delivery-plan.md:8`.

## Per-CTQ status
| CTQ | Status | Findings / Evidence |
| --- | --- | --- |
| 1 Target Integrity | PASS | Single explicit target `add-tui-vim-char-search`; scratch repo and sibling slice 1 are read-only inputs. |
| 2 Reference Fidelity | PASS | Baseline identity verified (`8f651b…d455`, `96ec9fb…`, digest `6f4d139…`). Seams verified in `src/tui/composer.py`. Pointer to `source-hashes.json` qualified. |
| 3 Task Executability | PASS | 14 test methods unified under `test_tui_composer.VimCharSearchTests`. Pinned bytecode-disabled unittest commands across all documents. 9 tasks remain unchecked. |
| 4 Verification Traceability | PASS | All 7 requirements and 14 spec scenarios map 1:1 to acceptance methods and matrix rows. Independent derivations match spec.md formulas. |
| 5 Artifact Coherence | PASS | `spec.md`, `design.md`, `acceptance-plan.md`, `delivery-plan.md`, and `verification-matrix.md` agree on fixtures, formulas, spans, carets, and namespaces. `verification-matrix.md` registered in inventories. |
| 6 Controller-State Safety | PASS FOR ADVISORY | No controller sidecar written or required; no controller transition claimed. Base planning lane maintained. |
| 7 Method and Control Closure | PASS FOR PLANNING | 19 controls cleanly categorized (15 P, 4 I). Candidate restore checks captured candidate identity, not pre-word-object baseline. |
| 8 Independent Exact Proof | DEFERRED / PLAN VERIFIED | All 14 feature assertions truthfully marked UNPROVEN. Structural validation passes (`openspec validate --strict` exit 0). Fixture mathematics independently recomputed and verified. |

## Blocking issues
**None.** (0 blocking issues remaining).

## Open prerequisites (non-blocking for planning phase)
1. **Human semantics approval**: Explicit sign-off on failed-search memory retention, progressing counted till repeats, and successful empty-T semantics.
2. **Accepted slice-1 parent**: Slice 2 (`add-tui-vim-char-search`) depends on concrete accepted candidate of Slice 1 (`add-tui-vim-word-objects`) as git parent.
3. **Execution & QA authorization**: Materialization of disposable candidate worktree, source implementation, test execution, negative-control execution, and rollback exercise remain future gates under authorized implementer and independent QA roles.

## Exact inspected planning revisions
| File | SHA-256 |
| --- | --- |
| `.openspec.yaml` | `807ba555347a4a58481b0c106d082a908239aa8c070099eb5444b441ab46bc24` |
| `triage.md` | `8ed4298a59887736a406f900a96cbb9994095db8df2006eb0188908c407ccb22` |
| `pitch.md` | `612d8be4bbc34623e6d6209f1ad5301b27a7efabce7ce38f89f997f6bb63b63d` |
| `findings.md` | `2345be02d5f809e601374ce7f7303701eaf5131017019155cde9bbd3675f44ce` |
| `proposal.md` | `f589e5b1bb60f47edc6978c77a0b35748c667c6fdb4e1c01aa870763585b2ef3` |
| `specs/tui-vim-char-search/spec.md` | `c9f37bab238c1cfd927e3fd4dd0c6bb86a6b3e7ba3d99a8b99f535052c899ac7` |
| `design.md` | `b17f07420e4e40714d1f920e26231418bfc7b0671ffa43351335460083f70fb7` |
| `acceptance-plan.md` | `7b83723e05f8c01aba09f679c049570cc3732c9e67319cafa5e90525f0256c96` |
| `environment-baseline.md` | `f2ebdc1396a0f4186c914244eb4c98527a14477acd1e3890a62e9c70d6658540` |
| `delivery-plan.md` | `b9194f61a1fa44b68e3746870c75caf93751cd3d3016692ace76bf2a007c7379` |
| `tasks.md` | `8fd5c77e8e98d3acae73a49ad5716a7d109bbfbfed886af8e515f5c1d58fd66e` |
| `verification-matrix.md` | `80a8fc265ab506b54f3a58f36460a23a77edd43c391b01011af849be3721b0ec` |

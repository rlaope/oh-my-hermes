# Advisory opsx-audit — add-tui-vim-char-search

## Verdict and boundary
**ADVISORY: REPAIRS NEEDED before treating this package as executable.** This is an independent planning review under ROLE-OPSX-AUDIT-1, not strict-controller review, Apply authorization, a QA pass, or an `OKAY`/`REJECT` controller transition. No sidecar, manifest, source, test, sibling artifact, or controller state was written. Findings go to the caller; Planner/matrix owner own repairs. The explicitly assigned target is this change only.

The minimal Composer design is plausible and the package truthfully leaves all 14 feature assertions UNPROVEN. Strict structural validation passes. However, one required backward-repeat oracle is impossible, and the independent matrix contradicts the accepted-direction formulas and test/recovery contract. Those defects would misdirect a capable implementer or prevent the declared proof from finishing.

## Inspected inputs and observed checks
- Read both prerequisite handoffs, all twelve package inputs below, `/Users/danrio/.config/opencode/agent/opsx-audit.md`, the referenced Composer seams, and applicable OpenSpec/verification/Ponytail guidance. The prerequisite matrix handoffs exist; neither is implementation evidence.
- Planning root: `/Users/danrio/.hermes/workspace/oh-my-hermes-vim-objects-planning`.
- Read-only source: `/Users/danrio/.hermes/cache/scratch/pr2545-shardfix`, HEAD `fcd2abcb11e323ccba4c26a3b340e7d377c0daa8`; `git status --porcelain=v1` empty.
- Ran `openspec validate add-tui-vim-char-search --strict` in the planning root: exit 0, `Change 'add-tui-vim-char-search' is valid`. This is structural evidence, not semantic acceptance.
- Ran `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -m unittest test_tui_shortcuts.LeaderShortcutTests -q` in the source root: exit 0, 25 tests, OK. This verifies the baseline leader floor only, not the proposed feature.
- Source hashes match environment-baseline.md: composer `8f651b0fd549f6cee6ed619b0c7654a2b73d3bfb0029d04a9e1d6d7f3fffd455`; keys `96ec9fb7ae293c8740ed7116d5f92299921d47952346d927838af2f1df7b7e9c`; composer tests `a5a6f633590a931ad31488c5901f7c591a270b5088f6aaa9e8fa3849ac786cc5`; shortcut tests `81abcfb68bec933d42c75ee1627366c3fb3bb95cd8b8982d9ba28374ed796ff4`.
- Recomputed the baseline's compact JSON digest: `6f4d139762e4be02b95929e86cc9ba9fb1fe9a808e336774c1e0c7b9c4eb41ec`, matching the artifact. A future accepted slice-1 parent still requires rebaselining.
- Verified actual seams: `_line_of` L394, `_atoms` L815, `_take_count` L832, `_normal_char` L841, `_command` L872, `_motion_span` L948, `_operate` L987; `_step` L651 already suppresses no-text-change undo, `_modal` L759 translates BACKSPACE/DELETE before generic cancellation. The proposed new helpers/memory are explicitly future work, not falsely claimed present.
- No `controller-transition-state.yaml` is present. No controller assignment or lifecycle readiness was invented.

## Blocking advisory findings (only execution/proof contradictions)

### A-CS-1 — Required backward-repeat oracle cannot satisfy CS-6
**Criterion:** CTQ 4/5; CS-6; tasks 1.4 and 3.1 (every declared subcase must pass).

`acceptance-plan.md:33` requires `aXbXcX` starting at index 5: `TX` → 4, `;` → 2, `;` → 0, comma → 2. X indices are 1,3,5. Under spec.md:243, T lands at m+1, and a repeated T skips the adjacent self-landing target. Thus TX from 5 lands 4, first repeat lands 2, next repeat **misses and stays 2**. Landing 0 would require a match at -1. The source's NORMAL clamp (composer.py:805-813) also prevents the matrix's alternative out-of-buffer initial caret 6 on this nonempty line (`verification-matrix.md:49`) from being a stable starting state.

**Smallest repair:** Keep the defined algorithm. Correct the required mirror fixture in acceptance and matrix, rather than changing semantics to pass a bad oracle. For a full mirror of the forward sequence, use `XcXbXa` at caret 5: explicit TX → 5, repeats → 3 → 1, comma → 3; counted 2; from the explicit-TX state → 1. Alternatively retain the original fixture and declare the third T repeat an atomic miss. Reconcile the same row in the matrix and preserve all target statuses as UNPROVEN. Owner: Planner with matrix owner.

### A-CS-2 — Independent matrix has wrong expected states and a different test namespace
**Criterion:** CTQ 3/4/5; CS-1/3/4/5/6; tasks 1.1–1.4, 3.1.

The matrix is not a usable independent oracle as written:
- `verification-matrix.md:12`: `ab cd` at caret 2 already sits on the only space. `f` + space must miss and remain 2, not land at 3 (which is c). The decomposed/composed fixture in that row is also not concretely specified.
- `:35`: on `xQ` at caret 1, backward x match is m=0 and T span is **[1,1)**, not m=1 / [2,1). Following `;` on this exhausted two-character fixture cannot behaviorally distinguish remembered success from no memory; use a discriminating fixture or a direct tuple assertion consistent with the acceptance plan.
- `:42`: after `fx`, starting caret is 4, so `d;` selects [4,9), not [0,5). After `fx;` then d-comma, [4,8) is `xabc` (four characters), not `xabcx`; resulting text is `xabcxabcx`. The correct post-delete follow-up ; goes 4→8, but not for the deletion text described there.
- `:49`: after tX on `aXbXcX` at 0, d2; ends at match m=5 and uses [0,5), selecting `aXbXc` and leaving **`X`**, not `cX`. A landing index 4 is not the matched index 5.
- Matrix methods/class (`TestCharSearch*`, `test_directions_fFtT`, `test_atom_matching`, `test_operator_endpoints`, etc.) differ from the concrete `test_tui_composer.VimCharSearchTests.test_directions`, `.test_atomic_targets`, `.test_operator_spans`, etc. in acceptance-plan.md:11-24/tasks.md. There is no executable name mapping; the matrix switches to unpinned pytest at :60 despite the package's explicit bytecode-disabled unittest contract.

**Smallest repair:** Correct only matrix fixtures/derived observations, use exactly the acceptance-plan's fully qualified method IDs and pinned unittest commands, and make the intended complete-state assertion precise. Do not add a second test harness or change working endpoint formulas. Owner: matrix owner; Planner reconciles the accepted oracle. The independently checked four main d/c/y span formulas themselves are correct.

### A-CS-3 — Negative-control procedure cannot restore or isolate the declared future candidate
**Criterion:** CTQ 4/7/8; CS-7; tasks 2.2/2.3 and 3.1; environment/delivery candidate-binding contract.

`verification-matrix.md:61-63` reverses `<owned-patch>` while demanding only a named hunk, then reapplies that patch and demands composer match the **pre-word-object baseline** hash and clean status. A restored feature candidate must instead match its captured candidate identity (and, if deliberately uncommitted, its recorded diff inventory). Matching composer to the old baseline erases both ordered features, directly contradicting environment-baseline.md's fresh accepted-slice-1 binding requirement. The old source-hashes.json pointer is unqualified and composer abbreviation `8f651b…459d` does not match the inspected hash ending `d455`.

Several falsifiers cannot support the promised isolated result:
- NC-3b's five-b target line misses with either cap 9999 or no cap 99999, so its public-state result cannot prove the cap. Use a fixture with at least 9999 matches or explicitly inspect the capped count at an accepted seam.
- Count multiplication/capping are inherited `_take_count` behavior (composer.py:832-839), and no-empty-text undo is inherited `_step` behavior (651-656). NC-3a/3b/4d cannot honestly require reversal of new search-owned hunks when those hunks may not exist. The baseline already has the NORMAL/masked gate, so NC-7a has the same problem.
- NC-1a removes shared search dispatch yet claims only the first directional case fails; all four depend on it. NC-2c lumps existing Paste and shared handle undo/redo into one future hunk despite separate baseline paths. NC-5c overlaps NC-3c's memory guard, and NC-6b/6c duplicate speculative atomic application. Existing no-regression suites need not fail for a new search-only leader-space defect as NC-7b predicts.
- The completeness assertion says **18** controls; programmatic enumeration yields **25 distinct IDs**, NC-1a..1d / 2a..2c / 3a..3c / 4a..4e / 5a..5d / 6a..6c / 7a..7c. Promised nonoverlapping surgical signatures are therefore neither counted correctly nor supported by inspected code.
- `verification-matrix.md` is omitted from the accepted planning-artifact inventories in acceptance-plan.md:56 and delivery-plan.md. Its altered or conflicting oracles would not be bound by the stated future manifest despite being used for proof.

**Smallest repair:** Treat candidate-dependent reversals as planned, not presently established surgical hunks. Use a separately captured narrow patch per control and restore the exact candidate hash/inventory, not the baseline. Replace inherited/unavailable hunk reversals with minimal discriminating fixtures or a clearly bounded disposable mutation only if authorized; merge duplicate controls, allow truthful affected test families, recalculate the count, and bind the matrix among accepted evidence inputs. Do not expand source scope or fabricate mutation execution. Owner: matrix owner/Planner; future independent QA owns observed results.

## Per-CTQ status
| CTQ | Status | Requirement / finding / reason |
| --- | --- | --- |
| 1 Target Integrity | PASS | One explicit add-tui-vim-char-search target; sibling handoffs are read-only inputs. |
| 2 Reference Fidelity | PARTIAL | Real Composer references and baseline identity verified; matrix baseline/hash pointers and future-hunk claims fail under A-CS-3. |
| 3 Task Executability | NEEDS REPAIR | Concrete source seams and unchecked tasks are appropriate; competing test identifiers and impossible mandatory oracle violate A-CS-1/2. |
| 4 Verification Traceability | NEEDS REPAIR | All 7 requirements / 14 scenarios have intended checks, but incorrect observations and nondiscriminating controls violate A-CS-1/2/3. |
| 5 Artifact Coherence | NEEDS REPAIR | Core ranges and planning-only state are coherent; acceptance mirror and matrix disagree under A-CS-1/2/3. |
| 6 Controller-State Safety | PASS FOR ADVISORY | No controller sidecar, state write, strict verdict, apply, or authorization claim. |
| 7 Method and Control Closure | NEEDS REPAIR | Design lists material failures/containment/recovery; the concrete negative-control execution/restore plan is not feasible as promised (A-CS-3). |
| 8 Independent Exact Proof | DEFERRED / PLAN REPAIR | Absence of feature proof is expected and truthfully recorded; future manifest/oracle binding needs A-CS-3 repair. Baseline green is not acceptance. |

## Method, proportionality and open prerequisites
- The planning-only/no-prototype exception is explicit in findings.md; no feature prototype, destruction, release observation or control execution is claimed. This is a justified scope boundary, not an invented passing DMADV gate. Formal strict-controller proof/method closure was not assigned and is not granted by this advisory.
- Minimal architecture (one remembered tuple, existing prefix/count/atom seams, shared slice-1 operator effects) meets Ponytail intent; no evidence calls for a modal rewrite, dependencies or new key constants. The proposed 25 purported single-hunk controls overstate independence and burden; repair controls rather than expanding implementation to manufacture matching hunks.
- Human semantic approval of failed-search memory retention, progressing counted till repeats and successful empty T semantics remains open. Concrete accepted word-object parent/seam and approved candidate path/branch/manifest remain future apply prerequisites, not missing planning execution evidence.
- Independent candidate QA and rollback exercise are still UNEXECUTED. Existing source has neither feature. No implementation success, full TUI regression pass, release readiness or controller transition follows from this audit.
- No acceptance files were repaired by the auditor. Caller should return the three findings to Planner/matrix owner; no strict-controller resubmission or authorization is created here.

## Exact inspected planning revisions
These hashes identify the reviewed inputs, not accepted Human revisions or a future candidate manifest.

| relative input | SHA-256 |
| --- | --- |
| `.openspec.yaml` | `807ba555347a4a58481b0c106d082a908239aa8c070099eb5444b441ab46bc24` |
| `triage.md` | `8ed4298a59887736a406f900a96cbb9994095db8df2006eb0188908c407ccb22` |
| `pitch.md` | `612d8be4bbc34623e6d6209f1ad5301b27a7efabce7ce38f89f997f6bb63b63d` |
| `findings.md` | `2345be02d5f809e601374ce7f7303701eaf5131017019155cde9bbd3675f44ce` |
| `proposal.md` | `f589e5b1bb60f47edc6978c77a0b35748c667c6fdb4e1c01aa870763585b2ef3` |
| `specs/tui-vim-char-search/spec.md` | `c9f37bab238c1cfd927e3fd4dd0c6bb86a6b3e7ba3d99a8b99f535052c899ac7` |
| `design.md` | `b17f07420e4e40714d1f920e26231418bfc7b0671ffa43351335460083f70fb7` |
| `acceptance-plan.md` | `d2869e7e82a2f57f711b27e7f773f78252c5fa530ae333725a29aaf8bb761737` |
| `environment-baseline.md` | `f2ebdc1396a0f4186c914244eb4c98527a14477acd1e3890a62e9c70d6658540` |
| `delivery-plan.md` | `fb2de53c014fbf4635f36360c2df0c35000510b79b7081e4a9db828f2201aedf` |
| `tasks.md` | `8fd5c77e8e98d3acae73a49ad5716a7d109bbfbfed886af8e515f5c1d58fd66e` |
| `verification-matrix.md` | `03f0abd8cee4f6bd73dcaead4725c33ae6d7e89475f502e447f1215565bf8927` |

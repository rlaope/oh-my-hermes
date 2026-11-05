# Tasks

Planning-only: all work below is future work, apply unauthorized. Creating these documents completes no implementation task.

## 1. Contract and Implementation
- [x] 1.1 Human accepts WO-1..WO-7 semantics and authorizes a named implementation worktree; independently audit the proposed plan and record exact revisions.
  - Done when: all semantic choices accepted, source still unchanged, candidate scope named.
  - Verify: explicit Human authorization and artifact hashes.
  - Negative check: absent approval blocks apply even if OpenSpec reports tasks ready.
  - Evidence: future verification-evidence.md authorization/candidate section.
- [x] 1.2 WO-4: extend `src/tui/composer.py` `_normal_char` using existing operator/count/_prefix state for i/a+w; preserve g/r, leader and reset precedence.
  - Done when: pending/invalid/cancel scenarios pass without leaked state.
  - Verify: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -m unittest test_tui_composer.VimWordObjectTests.test_pending_state test_tui_composer.VimWordObjectTests.test_cancel_state -v`.
  - Negative check: Escape, invalid follower and digit after descriptor do not edit or become commands.
  - Evidence: future verification-evidence.md wo-pending-state / wo-cancel-state outputs.
- [x] 1.3 WO-1/2/3/6: add bounded object-span helper in `src/tui/composer.py` on `_atoms` with exact WORD_BREAKS, line and count rules; keep existing motion predicates unchanged.
  - Done when: range/count/blank/newline/empty/atomic scenarios all pass.
  - Verify: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -m unittest test_tui_composer.VimWordObjectTests -v`.
  - Negative check: huge counts do not cross NEWLINE; NBSP is not a delimiter; chips are never split.
  - Evidence: future verification-evidence.md range/count/atomic assertion outputs.
- [x] 1.4 WO-5/6: share `_operate` characterwise effects between motions and objects in `src/tui/composer.py`, preserving repeated-operator linewise path, yank/put metadata and undo grouping.
  - Done when: all d/c/y × iw/aw, empty and undo/register cases pass.
  - Verify: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -m unittest test_tui_composer.VimWordObjectTests.test_operator_effects test_tui_composer.VimWordObjectTests.test_undo_register test_tui_composer.VimWordObjectTests.test_empty_line_atomic -v`.
  - Negative check: yank adds no undo step, empty d/y do not overwrite register, c replacement remains one undo.
  - Evidence: future verification-evidence.md operator/undo/empty outputs.

## 2. Integration and Controls
- [x] 2.1 Add every named `VimWordObjectTests` method and all falsification subcases from acceptance-plan.md to `tests/test_tui_composer.py`; add only necessary application cases to `tests/test_tui_shortcuts.py`.
  - Done when: every scenario/assertion maps to executable coverage, including WO-7 isolation.
  - Verify: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -m unittest test_tui_composer test_tui_shortcuts -q`.
  - Negative check: non-Vim/INSERT/masked literal commands and original leader/Escape/motions remain baseline behavior.
  - Evidence: future verification-evidence.md coverage map and regression output.
- [x] 2.2 Bind the atomic implementation candidate and environment to exact source/diff/plan hashes; inventory only declared paths and no new dependencies/constants/generated files.
  - Done when: independent reviewer confirms exact inventory and no scope drift.
  - Verify: `git status --porcelain=v1` and `git diff --name-status` plus SHA-256 capture in approved implementation worktree.
  - Negative check: unexpected file or stale evidence blocks acceptance.
  - Evidence: future verification-evidence.md candidate inventory and digest.
- [x] 2.3 Verify surgical rollback in the approved disposable candidate: reverse only this slice's hunks, preserve unrelated work, run baseline checks; then restore the approved candidate and rebind any changed hashes.
  - Done when: reverse-patch check succeeds and original composer/shortcut tests plus baseline `diw` caret-11 probe pass after reversal.
  - Verify: `git apply --reverse --check <word-object-only.patch>` then exact owner-approved reverse application and regression commands in design.md.
  - Negative check: overlapping later search hunks stop rollback for owner reconciliation; no whole-file reset.
  - Evidence: `../../../../evidence/word-gates/report.md`, `rc1-*.log`, and exact baseline/restored manifests in the named implementation run root; reverse/check, 171 original regressions, caret-11 oracle, 3528 full TUI tests (one existing skip), restore/check, and 36 enabled feature/leader tests passed.

## 3. Completion
- [ ] 3.1 Independent auditor replays every acceptance assertion and `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -m unittest discover -s tests -p 'test_tui*.py' -q` on the exact candidate; all missing/stale/failing assertions block delivery.
  - Done when: every acceptance row passes with current candidate-bound evidence and regression output.
  - Negative check: baseline-only or wrong-candidate output is rejected.
  - Evidence: future verification-evidence.md independent replay.
- [ ] 3.2 Perform branch-delta review and Human delivery decision; keep later character-search slice separate, record amendments/observation/closure only after actual execution.
  - Done when: all above tasks are truly complete and observed, not merely planned.
  - Verify: OpenSpec status and closure evidence after implementation.
  - Negative check: planning validation alone never closes implementation.
  - Evidence: future evidence/amendment/observation/closure artifacts, not generated in this task.

# Tasks

Apply status: implementation and local integration/rollback executed on the authorized Slice 1 behavioral-QA parent. Evidence: `/Users/danrio/.hermes/cache/scratch/tui-vim-apply-20261104/evidence/char-apply/`. Independent QA, narrow controls, branch-delta review, native lifecycle admission and Human release/archive permission remain open.

## 1. Implementation
- [x] 1.1 CS-1/CS-3: implement atom-safe line-bounded resolver in src/tui/composer.py and direction/atomic/count/miss methods of test_tui_composer.VimCharSearchTests in tests/test_tui_composer.py.
  - Done when: f/F/t/T match nth complete ordinary grapheme on current line, target normalized; no chip/image substring or newline crossing; oversized count is atomic.
  - Verify: pinned `-m unittest test_tui_composer.VimCharSearchTests.test_directions test_tui_composer.VimCharSearchTests.test_atomic_targets test_tui_composer.VimCharSearchTests.test_counts -v` per interpreter below.
  - Negative check: pinned `-m unittest test_tui_composer.VimCharSearchTests.test_miss -v` checks full unchanged state and no c INSERT.
  - Evidence: future evidence/cs-directions.txt, cs-atoms.txt, cs-count.txt, cs-miss.txt, candidate-bound.
- [x] 1.2 CS-2: extend _prefix/_normal_char/_command/_modal pending search dispatch in src/tui/composer.py without stealing accepted word-object/r/g/leader followers; add pending/cancel methods in tests/test_tui_composer.py.
  - Done when: literal digits/operator/space/; targets complete before fresh parsing; Escape/invalid follower cancels; Paste/Ctrl undo/redo preserve existing event behavior; all pending state clears.
  - Verify: pinned `-m unittest test_tui_composer.VimCharSearchTests.test_pending_literals -v`.
  - Negative check: pinned `-m unittest test_tui_composer.VimCharSearchTests.test_cancel -v`, including stale count/operator and BACKSPACE/DELETE.
  - Evidence: future evidence/cs-pending.txt and cs-cancel.txt.
- [x] 1.3 CS-4: resolve exact search operator spans and reuse accepted common characterwise effect seam in src/tui/composer.py; add all d/c/y x f/F/t/T, adjacent empty and metadata/undo tests in tests/test_tui_composer.py.
  - Done when: twelve exact span/mode/caret/register cases pass; successful empty T differs from miss; chip/image/put and change-typing grouping remain intact.
  - Verify: pinned `-m unittest test_tui_composer.VimCharSearchTests.test_operator_spans test_tui_composer.VimCharSearchTests.test_effects -v`.
  - Negative check: pinned `-m unittest test_tui_composer.VimCharSearchTests.test_adjacent test_tui_composer.VimCharSearchTests.test_miss -v`.
  - Evidence: future evidence/cs-spans.txt, cs-adjacent.txt and cs-effects.txt.
- [x] 1.4 CS-5/CS-6: add per-instance remembered successful search, ;/, direction/count/operator resolution, explicit memory lifecycle and till-repeat progression in src/tui/composer.py; add repeat tests in tests/test_tui_composer.py.
  - Done when: comma does not poison direction; counted till repeats progress speculatively, no partial move; lifecycle exactly CS-5 and count cap applies.
  - Verify: pinned `-m unittest test_tui_composer.VimCharSearchTests.test_repeat test_tui_composer.VimCharSearchTests.test_till_repeat -v`.
  - Negative check: pinned `-m unittest test_tui_composer.VimCharSearchTests.test_memory test_tui_composer.VimCharSearchTests.test_repeat_miss -v`.
  - Evidence: future evidence/cs-repeat.txt, cs-memory.txt, cs-till-repeat.txt and cs-repeat-miss.txt.

## 2. Integration and Controls
- [x] 2.1 CS-7: preserve accepted word objects and all original routing; add isolation in tests/test_tui_composer.py and only necessary tests/test_tui_shortcuts.py integration tests. No key constants/dependencies/config changes or unrelated documentation/generated output needed.
  - Done when: non-Vim/masked/INSERT literals, i/a/r/g/iw/aw, leaders and legacy/modern Alt moves pass unchanged.
  - Verify: pinned `-m unittest test_tui_composer test_tui_shortcuts -q` then pinned `-m unittest discover -s tests -p 'test_tui*.py' -q` and actual accepted word-object suite.
  - Negative check: pinned `-m unittest test_tui_composer.VimCharSearchTests.test_isolation -v`; pending space target must not become leader.
  - Evidence: future evidence/cs-isolation.txt and regression logs.
- [ ] 2.2 Bind accepted artifact hashes, accepted slice-1 parent, concrete candidate root, source hashes and fresh environment digest into future evidence/candidate-manifest.json. Capture owned hunk patch/hash; verify no undeclared files, locks/config/generated output. Independent owner replays every acceptance row; no stale baseline digest accepted.
- [x] 2.3 Exercise hunk-level rollback in authorized disposable candidate only: reverse-check owned patch, reverse-apply, prove word objects/unrelated hunks preserved, replay regression floor, then restore only approved patch if needed. Never whole-file reset; overlapping hunks block and escalate.

## 3. Completion
- [ ] 3.1 Every acceptance assertion and declared subcase has candidate-bound happy/negative/boundary evidence with independent replay; zero skips/placeholders in future evidence; all CS-1..CS-7 and original/sibling regressions pass.
- [ ] 3.2 Re-run strict change validation, audit/QA/review gates and obtain separate Human release/archive permission; do not confuse ready planning artifacts with implementation or lifecycle completion.

All “pinned” test arguments above expand exactly to this executable invocation, run from approved candidate root:
```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B
```
Append the written `-m unittest ...` arguments. Full per-assertion commands are in acceptance-plan.md. The original Homebrew focused invocation passed; full TUI replay used the isolated `setup/word-gates/venv/bin/python`, pinned Node v26.12.1 and CommonJS fixture boundary from the repair handoff. Task 2.2 stays open because independent replay is outstanding despite the captured local manifest. Tasks 3.1/3.2 remain open; no native admission, independent QA/review or release/archive permission is claimed.

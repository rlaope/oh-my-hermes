# Verification Matrix — add-tui-vim-word-objects

Status: planning-only contract audit mapped independently against observable tests and a coherent full-slice recovery check. Every target assertion is UNPROVEN; this matrix adds no implementation and modifies no source. Authority chain: `specs/tui-vim-word-objects/spec.md` (semantic oracle) → `acceptance-plan.md` (test table) → `design.md` (planned seams) → `findings.md` (baseline probes) → `environment-baseline.md` (candidate binding). This revision repairs advisory findings WO-A1/WO-A2 in `opsx-audit.md`; it does not change that historical audit or grant apply authorization.

## 0. Observed baseline and state-specific oracles

The following observations were independently rerun from the read-only source root `/Users/danrio/.hermes/cache/scratch/pr2545-shardfix` during this repair. They are not feature acceptance.

| observable | observed value | source |
| --- | --- | --- |
| `diw` on Unmasked Vim Composer text `alpha beta gamma`, caret 8 | text unchanged, caret 11, pending false (H1 falsified) | live repair probe; findings.md §3.1 |
| `d20` on text `a b c`, caret 0, NORMAL | text unchanged, caret 0, pending true, `_operator == 'd'`, `_op_count == '20'` | live repair probe |
| `WORD_BREAKS` | exactly `['\t', ' ']` when sorted | live repair probe |
| `_word_end(list("one\u00a0two"), 0)` | 3 (existing motions use `.isspace()` and split at NBSP; new objects deliberately do not split at NBSP) | live repair probe; normative object predicate |
| leader suite | 25 tests OK | live repair regression run |
| feature test class | `VimWordObjectTests` absent | live import/inventory probe |
| source head | `fcd2abcb11e323ccba4c26a3b340e7d377c0daa8`, git clean | live repair HEAD/status check |

Select the oracle by production state, not by whether feature tests are installed:

| production state | `diw` oracle for `alpha beta gamma`, initial caret 8 | evidence meaning |
| --- | --- | --- |
| untouched planning baseline / full production-slice rollback | unchanged text; caret 11; pending false | baseline or recovery proof only |
| complete enabled candidate, including after test-only removal | text `alpha  gamma`; caret 6; NORMAL; pending false; characterwise register `beta` | WO-1 feature oracle, UNPROVEN until candidate execution |
| partial production mutation or provisional seam control | the explicitly specified mutation assertion only; neither whole-candidate oracle is assumed | control-specific diagnostic, not baseline recovery |

The unchanged-text/caret-11 oracle is restricted to the untouched baseline or full production-slice rollback states. It is not a universal pre/post-control invariant. Restoring the enabled candidate restores the feature oracle. Leader compatibility is required in both states but does not select the `diw` oracle.

Self-contained baseline/recovery probe (run only in the baseline/fully rolled-back state, from that worktree root):
```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -c 'from omh.tui.composer import Composer; from omh.tui.keys import Key, CHAR; c=Composer(text="alpha beta gamma",caret=8,vim=True); c.normal=True; [c.handle(Key(CHAR,char=k)) for k in "diw"]; print("DIW_BASELINE",repr(c.text),c.caret,c.pending); assert (c.text,c.caret,c.pending)==("alpha beta gamma",11,False)'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -m unittest test_tui_shortcuts.LeaderShortcutTests -q
```
On the enabled candidate use §2 `test_inner_range` instead; it checks the complete feature outcome including register/mode.

## 1. Planned candidate seams (not independently deletable controls)

These labels identify implementation responsibilities, not a promise that any helper can be removed while its callers survive. H-B depends on H-A and H-C; H-C may also be shared by ordinary motions. The accepted slice must be reversible coherently as a whole. No missing-method, None-safe fallback, or individually reversible helper scaffold is specified or required.

| seam | file | planned content | requirements served |
| --- | --- | --- | --- |
| H-A | `src/tui/composer.py` | `_text_object_span(descriptor, times)` helper: `_atoms` + exact WORD_BREAKS membership, NEWLINE hard stop, iw run-count / aw word-count; count supplied by `_take_count()` | WO-1, WO-2, WO-3, WO-6 |
| H-B | `src/tui/composer.py` | `_normal_char` object-prefix branch: arm `_prefix` (i/a) only when `_operator` in `dcy`, complete on `w` once, consume+discard invalid followers, route span into `_operate_span` | WO-4 |
| H-C | `src/tui/composer.py` | `_operate_span(operator, span)` shared characterwise effects seam into existing `_operate` tail (`_yank`, `_replace`, `_enter_insert`, undo grouping) | WO-5, WO-6 |
| H-D | `tests/test_tui_composer.py` | `VimWordObjectTests` with exactly the 11 methods of acceptance-plan.md (+optional `tests/test_tui_shortcuts.py` cases) | WO-7 isolation + all evidence |

## 2. Requirement → observable test matrix

All test commands run from the future implementation candidate root, not the planning source. Path class: happy / boundary / negative per acceptance-plan.md. The first row gives the full invocation; each `... test_NAME -v` below expands to `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -m unittest test_tui_composer.VimWordObjectTests.test_NAME -v`.

| WO | scenario_id | assertion_id | test method (same method as acceptance-plan) | observable state checked |
| --- | --- | --- | --- | --- | --- |
| WO-1 | wo-inner | wo-inner-range | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -m unittest test_tui_composer.VimWordObjectTests.test_inner_range -v` | text `alpha  gamma`; caret 6; NORMAL; pending false; register text `beta`; linewise false |
| WO-1 | wo-whitespace | wo-whitespace-range | `... test_whitespace_range -v` | `one  \ttwo` + caret 4 + `diw` → `onetwo`; `foo.bar-baz` one word; NBSP in `one\u00a0two` is a word constituent |
| WO-2 | wo-around | wo-around-range | `... test_around_range -v` | on `one  two\t  three` caret on `two`: removes `two\t  ` → `one  three`; on final token of `one  two`: removes `  two` → `one` |
| WO-2 | wo-around-blank | wo-around-blank-range | `... test_around_blank_range -v` | `one  two  three` caret 3: removes `  two` → `one  three`; terminal blanks remove only the run; no trailing blanks added from blank start |
| WO-3 | wo-count | wo-count-range | `... test_count_range -v` | `a b c d e` caret 0 `2d2iw` → `c d e` (4 alternating runs); `2daw` removes `a b `; cap 9999; huge count stops at NEWLINE |
| WO-4 | wo-pending | wo-pending-state | `... test_pending_state -v` | keys `2 d 3 i`: nothing mutated, pending true with operator/counts retained; then `w` completes 6-run selection and clears pending |
| WO-4 | wo-cancel | wo-cancel-state | `... test_cancel_state -v` | descriptor pending + Escape / `x` / digit `2`: consumed, no edit/motion/register/INSERT; later `w` is an ordinary motion; set_vim and Paste clear via `_drop_pending` without changing the cancelling event's own behavior |
| WO-5 | wo-operators | wo-operator-effects | `... test_operator_effects -v` | full d/c/y × iw/aw cross product: d stays NORMAL; c enters INSERT at span start; y keeps text, caret at span start; exact characterwise register per operator |
| WO-5 | wo-undo | wo-undo-register | `... test_undo_register -v` | delete = 1 undo; change+replacement = 1 undo; yank = 0 text undo; undo/redo restore text/caret/chips/images with no register-rewind promise; put uses captured text/metadata |
| WO-6 | wo-edges | wo-empty-line-atomic | `... test_empty_line_atomic -v` | empty d/y no-ops preserving register; empty c enters INSERT with no text undo until typing; NEWLINE never inside span or crossed; grapheme/chip/image atoms never split; register metadata intact on d/c/y/put |
| WO-7 | wo-isolation | wo-isolation-regressions | `... test_isolation_regressions -v` | literal `diw`/`daw` typed in Vim INSERT / non-Vim / masked inserts text; standalone i/a unchanged; dw/cw/yw/dd/cc/yy, g/r prefixes, Alt+b/f, Escape handling, leader routing all baseline |

Coverage completeness: 7 requirements → 11 scenarios → 11 assertion_ids → 11 distinct methods. Method names and expanded commands match acceptance-plan.md. Subcase expansions remain in acceptance-plan §Falsification.

Prefix-only observations are not whole-test pass predictions: inspecting state after `2 d 3 i` exercises only the arming checkpoint. `test_pending_state` also sends final `w` and asserts a completed six-run edit; it cannot be declared green when span completion/effects are absent. Range methods likewise assert completed text/caret/register effects, not isolated helper correctness. `test_cancel_state` includes subsequent-command/reset behavior, not just the initial cancellation checkpoint.

## 3. Coherent recovery control and provisional seam controls

All controls below are PLANNED / UNEXECUTED. Choose the full-slice recovery option for task 2.3; do not remove helper definitions independently. No production scaffold is added to make a deletion control appear executable.

### RC-1 — full-slice reverse-patch recovery

1. In the separately authorized, hash-bound implementation worktree, bind the complete accepted word-object-only patch (H-A through H-D, including any optional shortcut additions) and its pre-slice base. Record exact paths, HEAD/diff hashes and test inventory before the trial. Preserve unrelated leader/search work. If overlapping later hunks prevent exact reversal, stop for owner-reviewed manual separation; do not reset whole files.
2. On the enabled candidate run all 11 §2 methods via `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -m unittest test_tui_composer.VimWordObjectTests -v`, then the two acceptance-plan regression commands below. Require the feature oracle, not unchanged-text/caret-11. A failing candidate is not a valid recovery-control starting point.
3. With `WORD_OBJECT_PATCH` explicitly set to that bound patch, run `git apply --reverse --check "$WORD_OBJECT_PATCH"`, then `git apply --reverse "$WORD_OBJECT_PATCH"`. This reverses the full production slice and its feature tests together, not H-C/H-A beneath live callers. Inspect the resulting diff against the bound pre-slice state.
4. In the fully rolled-back state run the §0 baseline probe and leader suite, plus both regression commands below. Require unchanged text/caret 11 only here. The original regression tests must remain available and green. Feature methods removed with H-D are absent inventory, not failing behavioral assertions; do not invoke `VimWordObjectTests` in this state or claim WO-7's removed method passed. A load error, missing live helper, or regression failure is not successful recovery.
5. Restore the exact candidate using `git apply --check "$WORD_OBJECT_PATCH"` then `git apply "$WORD_OBJECT_PATCH"`; verify candidate HEAD/diff hashes match the original binding. Rerun all 11 feature methods and both regression commands. Require the feature oracle again. Record the three states/results separately; failure of either recovery or restoration blocks task 2.3.

Regression commands (future implementation/recovery worktree only):
```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -m unittest test_tui_composer test_tui_shortcuts -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -m unittest discover -s tests -p 'test_tui*.py' -q
```

### NC-1..NC-3 — provisional seam controls, not acceptance evidence

The former independent H-C/H-B/H-A deletion controls and their fail/green predictions are withdrawn. The table reserves diagnostic seams only; RC-1 supplies the coherent recovery check. These controls must not be executed or counted as proof until a real candidate diff supports an exact minimal behavior mutation inside one owned helper/branch, keeps all called interfaces and feature tests intact, names the precise end-to-end assertion expected to fail, and names the baseline regression suites expected to stay green. Bind and restore each trial separately; inspect unexpected failures rather than inventing a None-safe fallback. No green prediction is made now.

| reserved control | provisional seam | candidate evidence needed before use |
| --- | --- | --- |
| NC-1 | H-C operator/effects | exact behavior mutation and named text/caret/register/undo assertion; account for ordinary motions sharing the effect path |
| NC-2 | H-B parser/cancellation | exact branch mutation and named prefix/cancellation or completed-edit assertion, distinguished explicitly |
| NC-3 | H-A range/count/predicate | exact range mutation and named completed-edit assertion, without deleting the helper called by H-B |

NC-4 is dropped as behavioral evidence. A test-only removal could at most check test discovery/inventory; it leaves production enabled, must retain the feature `diw` oracle, and cannot run WO-7 via a removed class. No such removal is needed for this plan.

### Discriminator checks

- D-1, pre-descriptor count preservation: on text `a b c`, caret 0, NORMAL, send `d20`. Require unchanged text, caret 0, pending true, `_operator == 'd'`, `_op_count == '20'`. This is measured baseline behavior and must remain on an enabled candidate; `0` continues the existing post-operator count here. It is not object-descriptor cancellation. Run this exact probe from the relevant worktree root:
  ```sh
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -c 'from omh.tui.composer import Composer; from omh.tui.keys import Key, CHAR; c=Composer(text="a b c",caret=0,vim=True); c.normal=True; [c.handle(Key(CHAR,char=k)) for k in "d20"]; print("D20",repr(c.text),c.caret,c.pending,repr(c._operator),repr(c._op_count)); assert (c.text,c.caret,c.pending,c._operator,c._op_count)==("a b c",0,True,"d","20")'
  ```
- D-1b, invalid digit **after** i/a: `di2` on the enabled candidate consumes `2`, clears the object/operator/count state, and leaves text/caret/register/mode unchanged; next `w` is ordinary motion. This is planned `wo-cancel-state` / `test_cancel_state` coverage, not an observation of the unimplemented baseline. Cover the corresponding a-prefix digit case as acceptance-plan requires.
- D-2, scope inventory: inspect the accepted word-object candidate diff for no new key constants, dependencies or configuration changes. `git diff --name-status` is limited to two mandatory owned paths, `src/tui/composer.py` and `tests/test_tui_composer.py`, plus optional `tests/test_tui_shortcuts.py` (three possible paths total); after full rollback require removal of only that bound slice. Shared key/leader/application files remain unchanged. This inventory check is not behavioral proof.
- Predicate discriminator: the future `wo-whitespace-range` NBSP subcase must use the new object oracle (NBSP nonbreak); compare the unchanged existing-motion `_word_end(...)=3` observation separately. Inspection of exact WORD_BREAKS membership supports the test; a textual search alone does not establish range correctness.

## 4. Verification record for this repair

Observed read-only source probes used `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B`: baseline `diw`, `d20`, WORD_BREAKS/NBSP, absent feature-class inventory, and leader tests (25 OK). Source HEAD/status were checked separately. The final required planning check is:
```sh
openspec validate add-tui-vim-word-objects --strict
```
Run from `/Users/danrio/.hermes/workspace/oh-my-hermes-vim-objects-planning`; final output and clean-source status are recorded in the repair handoff. Structural validator success does not establish feature behavior, rollback safety, or apply authorization.

All feature targets, RC-1 and seam mutations remain UNPROVEN/UNEXECUTED until a materialized, authorized, hash-bound candidate executes them. No feature implementation, reverse patch, worktree or evidence sidecar is created during this repair.

# Prototype Findings: add-tui-vim-char-search

## 1. Spike Envelope & Isolation
- Source: `/Users/danrio/.hermes/cache/scratch/pr2545-shardfix`, read-only at `fcd2abcb11e323ccba4c26a3b340e7d377c0daa8`; initial git status empty.
- Initial isolation: ISOLATED through read-only inspection and bytecode-disabled baseline probes. No source splice, standalone feature implementation or throwaway worktree exists.
- Spike type: read-only baseline harness plus stock Vim semantic reference. No shunts.
- Question: which parser seams and edit machinery can support bounded character searches without displacing word objects or leader handling?
- Decision: proceed to planning only when seams and dangerous endpoints are explicit; target acceptance remains unproven.
- Explicit planning-only exception: schema prototype-first/spec-second advice conflicts with the task's no-implementation boundary. These proposed requirements are not prototype-derived feature proof. Apply remains unauthorized.

## 2. Hypotheses Tested
| ID | hypothesis | method | result |
| --- | --- | --- | --- |
| H1 | baseline fb already searches | live Composer handle probe | FALSIFIED: unchanged text, caret 0, pending false |
| H2 | prefix/count and operator seams exist | source trace | SUPPORTED structurally, not target proof |
| H3 | backward operator spans include original caret just like forward spans | stock `/usr/bin/vim` reference | FALSIFIED: backward F/T exclude original caret |
| H4 | existing leader regression floor passes | unittest | SUPPORTED: 25 tests OK |

## 3. Empirical Discoveries
### 3.1 Source trace
All paths relative to source root, line numbers pinned to the baseline:
- `src/tui/composer.py:427-465`: dataclass state; _prefix is transient, _register stores edits, undo snapshots contain text/caret/chip/image data only.
- `:695-726` handle: global undo/redo precedes modal dispatch; _step records only text changes and merges change+typing. Reuse, do not duplicate undo.
- `:750-757` pending/_drop_pending: prefix, operator, counts and leader already clear together. Remembered successful search must be separate from pending.
- `:759-788` _modal: operator/prefix suppress leader; BACKSPACE/DELETE translate to h/x before generic pending cancellation. A waiting search must intercept them as cancellation, not literal targets.
- `:815-839`: _atoms merges chips; _take_count multiplies both counts, capped at 9999.
- `:841-870` _normal_char: only r/g prefixes exist; digit parsing currently precedes unknown commands. Search follower completion must run before digits/operators/i/a interpretation.
- `:872-907` _command: f/F/t/T/;/, absent, unknown letters no-op; this is normal-motion dispatch, not _move_or_delete.
- `:948-985` _motion_span: returns half-open atom ranges or None. Search miss must stay distinguishable from a valid empty T span.
- `:987-1004` _operate: d/c/y use _yank, _replace and _enter_insert; c currently accepts empty spans. Miss must return before this path or c would incorrectly enter INSERT.
- `:1029-1075`: _yank/_put retain chip/image metadata; :504-515 _replace removes whole chips and cleans metadata.

### 3.2 Executed baseline
From the source root:
```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -c 'from omh.tui.composer import Composer; from omh.tui.keys import Key, CHAR; c=Composer(text="alpha beta gamma",caret=0,vim=True); c.normal=True; [c.handle(Key(CHAR,char=k)) for k in "fb"]; print("FB_BASELINE",repr(c.text),c.caret,c.pending); assert c.text=="alpha beta gamma" and c.caret==0 and not c.pending'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -m unittest test_tui_shortcuts.LeaderShortcutTests -q
```
Observed exit 0: `FB_BASELINE 'alpha beta gamma' 0 False`; leader suite `Ran 25 tests`, `OK`.
Stock Vim reference: `vim -Nu NONE -i NONE -n -es` with `call setline(1, "xabcQabcx")`, `call cursor(1,5)`, `normal! <command>`, and `call writefile([getline(1),string(col(".")),getreg(nr2char(34))], "/dev/stdout")`, then `qa!`. Each command was a fresh process. Results: dfx => `xabc`/column 4/register `Qabcx`; dtx => `xabcx`/5/`Qabc`; dFx => `Qabcx`/1/`xabc`; dTx => `xQabcx`/2/`abc`. This proves reference endpoint behavior, not Composer support.
On `aXbXcX` stock Vim `tX;` reaches column 3 and `tX;;` column 5, proving naive till repeats can stick without special handling. Stock Vim counted till-repeat has subtleties (`tX2;` column 3); this package deliberately proposes count-as-progressing-repeat-steps instead (column 5), subject to Human acceptance, rather than claiming complete Vim equivalence.
One reference probe initially failed because Vimscript `chr` is not a function; corrected to `nr2char`, replayed successfully. No files were created by the probe.

### 3.3 Hidden Constraints and Limits
Targets must compare complete NFC grapheme atoms, never substrings of chips/image labels. NEWLINE is a hard boundary independent of display wraps. A successful zero-distance till match is not a miss. Failure after an oversized count must not partially move/edit or alter remembered search.
Word-object handoff was read: descriptor completion must coexist in _prefix; shared effects preserve accepted iw/aw. Source has neither feature today, so combined integration cannot be proven here.
No target search implementation/test, performance claim, worktree destruction, or release observation is asserted.

## 4. Spec & Design Hand-off Directives
All CS-1 through CS-7 requirements are UNPROVEN and have predeclared checks in acceptance-plan.md. Reuse _prefix, _take_count, _atoms, _line_of and shared characterwise operator effects; add one remembered successful search tuple outside undo/pending state. Avoid modifying ordinary word-motion predicates or key constants.

## 5. Gate Verdict & Attestation
Verdict: PROCEED_TO_SPECS for planning only. No feature prototype exists to destroy: destruction N/A, not DESTROYED. Human semantic acceptance, candidate materialization, independent acceptance and apply authorization remain open.

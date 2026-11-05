# Prototype Findings: add-tui-vim-word-objects

## 1. Spike Envelope & Isolation
- Source: `/Users/danrio/.hermes/cache/scratch/pr2545-shardfix`.
- Base commit: `fcd2abcb11e323ccba4c26a3b340e7d377c0daa8`; initial `git status --porcelain=v1` empty.
- Initial isolation: ISOLATED through read-only inspection and bytecode-disabled baseline probes. No throwaway implementation/worktree was created.
- Spike type: read-only baseline harness, not a feature prototype. No shunts or source mutations.
- Decision question: where does object parsing fail, and what existing edit/register machinery can be reused?
- Decision rule: proceed to a planning package only if exact parser and mutation paths are identified; require future implementation proof for all target behavior.
- Explicit planning-only exception: the agent-harness prototype-first/spec-second instruction cannot be satisfied without violating the assigned no-implementation scope. These specs are a proposed acceptance contract, not evidence that a prototype exists; apply remains unauthorized.

## 2. Hypotheses Tested
| ID | Hypothesis | Method | Result |
| --- | --- | --- | --- |
| H1 | `diw` already selects a word | live Composer probe | FALSIFIED: text unchanged, caret moves from 8 to 11, pending false |
| H2 | WORD_BREAKS is the actual Vim motion predicate | read constants and helper bodies; NBSP probe | FALSIFIED: WORD_BREAKS is space/tab, but existing word helpers call `.isspace()` |
| H3 | edit/yank/count primitives already exist | source trace below | SUPPORTED as source structure, not new behavior proof |
| H4 | leader regression suite is green at baseline | unittest | SUPPORTED: 25 tests, OK |

## 3. Empirical Discoveries
### 3.1 What Worked
Source trace (all paths relative to source root):
- `src/tui/composer.py:148`: WORD_BREAKS is exactly space and tab, not newline or NBSP. `:167`: existing `_VIM_OPERATORS = "dcy"`.
- `:359-391`: `_word_start`, `_word_end`, `_next_word`, `_end_of_word` use `.isspace()`; punctuation stays in a word; motions can cross lines. `_word_end(list("one\u00a0two"), 0)` returned 3.
- `:695-726`: handle snapshots edits, merges change typing into its undo step, then clamps normal caret. `:759-788`: only Vim/unmasked modal path routes normal characters; leader and non-character cancellation already exist.
- `:750-757`: pending and `_drop_pending` include `_prefix`, operator, and both counts. `:815-839`: `_atoms` merges chips; `_take_count` multiplies pre/post operator counts and caps at 9999.
- `:841-870`: `_normal_char` only understands `r`/`g` prefixes; after `d`, `i` is sent as a motion to `_operate`, so the operator is dropped; final `w` is then a standalone motion.
- `:872-907`: standalone `i`/`a` enter INSERT and must retain their current meaning.
- `:948-985`: `_motion_span` returns atom-index spans; no text objects; current `cw` special case is separate.
- `:987-1004`: `_operate` handles motion -> atom bounds -> `_yank(linewise=False)` -> `_replace` / `_enter_insert(change=True)`; yank sets caret to span start.
- `:504-515`: `_replace` deletes whole chips, filters chip/image metadata, and uses NFC/cluster-safe `_set`.
- `:1029-1036`: `_yank` records text plus chip/image metadata; `:1038-1075`: existing put restores them.

Executed from the read-only source root:
```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -c 'from omh.tui.composer import Composer, WORD_BREAKS, _word_end; from omh.tui.keys import Key, CHAR; c=Composer(text="alpha beta gamma",caret=8,vim=True); c.normal=True; [c.handle(Key(CHAR,char=k)) for k in "diw"]; print("DIW_BASELINE",repr(c.text),c.caret,c.pending); print("BOUNDARIES",sorted(WORD_BREAKS),_word_end(list("one\u00a0two"),0)); assert c.text=="alpha beta gamma" and c.caret==11 and not c.pending'
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3 -B -m unittest test_tui_shortcuts.LeaderShortcutTests -q
```
Observed: `DIW_BASELINE 'alpha beta gamma' 11 False`; `BOUNDARIES ['\t', ' '] 3`; exit 0. Leader suite: `Ran 25 tests`, `OK`, exit 0.

### 3.2 What Broke / Falsified Assumptions
The shared grounding lead described `diw` as a no-op; only text is unchanged, not caret. Also WORD_BREAKS does not drive current word motions. New objects must explicitly use the requested space/tab predicate without silently changing those existing motions. `_move_or_delete` is the nonmodal path and is not the correct object integration point.

### 3.3 Hidden Constraints
Object boundaries must operate on `_atoms`, not raw codepoints, to retain grapheme/chip safety. NEWLINE must be handled explicitly because it is not in WORD_BREAKS. This plan chooses logical-line-local objects to avoid accidental line joins; existing motions remain unchanged.

### 3.4 Limits and Non-Claims
No target object operation was implemented or exercised. No target-feature test result, timing claim, or clean-room destruction claim is made. Baseline tests do not establish acceptance of the new behavior.

## 4. Spec & Design Hand-off Directives
All WO-1 through WO-7 requirements are UNPROVEN target behavior; acceptance-plan.md declares their proof before implementation. Reuse `_prefix` for object descriptor pending only while an operator exists, `_take_count`, `_atoms`, `_yank`, `_replace`, and existing handle undo machinery. Keep motion helpers unchanged.

## 5. Gate Verdict & Attestation
Verdict: PROCEED_TO_SPECS for planning only, not apply. No feature prototype exists to destroy; destruction is N/A, not falsely attested DESTROYED. Source inspection and baseline probe are the only observed evidence. Apply authorization and target acceptance remain open.

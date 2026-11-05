# Design

## Context
This is a proposed design, not final architecture proven by a feature prototype. findings.md identifies the actual baseline seams and labels the target evidence gap.

## Goals / Non-Goals
Provide line-local `iw`/`aw` for existing d/c/y with minimal parser and range additions. Leave character search, visual mode, punctuation classes, existing motion semantics and application routing outside this slice.

## System Boundaries and Ownership
Composer owns transient normal parsing, atoms, register and edit history. Key decoder/app own event routing and leader actions and remain unchanged. Planned mutation surface: `src/tui/composer.py`, focused additions in `tests/test_tui_composer.py`; add application regression cases to `tests/test_tui_shortcuts.py` only if needed. Source root remains read-only throughout planning.

## Interfaces and Data Shapes
- Reuse `_prefix: str` for `i` or `a` only when `_operator` is d/c/y; no new field needed. Existing `pending` and `_drop_pending` already cover it.
- Proposed internal helper `_text_object_span(descriptor: str, times: int) -> tuple[int, int] | None`: called only for validated i/a+w; half-open atom indexes. Return `(index,index)` for an empty line/text and None only for an unsupported descriptor. No public API change.
- `_normal_char`: handle object-prefix completion before digit handling and before g/r dispatch; retain operator/counts while arming i/a. Final w consumes `_take_count()` once and clears pending state before mutation. Invalid followers are consumed and reset, never reinterpreted as motion, replacement, count or INSERT.
- Preserve the current early r/g branches and ordinary operator dispatch. Standalone i/a still fall through to `_command`.
- Compute object span from `_atoms` plus `_line_of`; scans use exact WORD_BREAKS membership and explicit NEWLINE limits. Reuse helper traversal concepts, not `.isspace()` calls that would change the specified predicate. `specs/tui-vim-word-objects/spec.md` is the sole authority for count/padding rules.
- Route a validated span into the existing `_operate` effect block: either a small private apply-span helper extracted mechanically from its current tail, or a narrow optional precomputed span argument. Preferred: private `_operate_span(operator, span)` shared by motions and objects so bounds conversion, `_yank`, `_replace` and c/y behavior remain one path. `_operate` still handles repeated operators/linewise logic before this path.
- No byte/codepoint slicing for boundaries; convert atom indexes through bounds once. `_Register` remains unchanged and characterwise. No new dependencies or key constants.

## Invariants and Failure Behavior
All spans are within one logical line, ordered, and atom aligned. Empty d/y preserve the register; empty c enters INSERT with existing no-text-change undo behavior. d/y remain NORMAL and use `_clamp_normal`; c insertion position is start. Pending descriptor cancellation leaves text/caret/register untouched except the pre-existing cancelling event's behavior (e.g. Paste inserts, shared undo performs undo). Unknown follower itself does nothing. Literal space while an operator/object prefix is active does not arm leader. No state may leak to a later command.

## Decisions and Rejected Alternatives
| decision | chosen approach | rejected alternative | evidence / falsifier |
| --- | --- | --- | --- |
| parser state | existing `_prefix` + operator | extra modal state object | source :440-446/:750-757 already covers prefix |
| delimiter | exact WORD_BREAKS + hard NEWLINE | silently changing all word helpers | source :148 and :359-391 disagree; NBSP regression catches it |
| punctuation | one WORD-style token | full Vim lowercase classes | bounded user slice; explicit tests |
| count | iw run-count, aw word-count | treating all counts as words or ignoring post-operator count | declared normative examples; implementation tests required |
| around padding | full trailing run, leading fallback | one-character separator | avoids leaving extra padding; explicit target choice |
| line boundary | hard stop | cross-line deletion via generic word motions | limits accidental line joins; multiline tests required |
| edit effects | shared `_operate` tail | `_move_or_delete`/manual string edit | existing register, chip and undo behavior would otherwise be bypassed |

## Prototype Findings Consumed
| finding | design consequence | remaining proof |
| --- | --- | --- |
| H1 parser consumes i as motion | operator-only prefix branch before ordinary dispatch | pending/cancel assertions |
| H2 predicate mismatch | object-only predicate, unchanged motions | NBSP + newline cases |
| H3 atomic/effect primitives exist | `_atoms` -> shared operator effects | chip/image/undo tests |
| H4 leader tests green | preserve early routing and prefix/operator precedence | full regression suites |

## Material Failure Controls
| requirement | failure mode | prevention | detection | containment | recovery | owner | proof |
| --- | --- | --- | --- | --- | --- | --- | --- |
| WO-1/2/3 | wrong range/padding/count | bounded atom scans and explicit contract | range/count cases | one logical line | undo | implementer | acceptance range rows |
| WO-4 | stale operator/prefix | shared reset path | cancellation and next-command tests | invalid follower consumed | reset pending | implementer | pending/cancel rows |
| WO-5/6 | split chip or lost metadata/undo | existing shared effects | metadata/undo assertions | no independent edit path | undo or surgical rollback | implementer | atomic/undo rows |
| WO-7 | leader/non-Vim regression | existing gates unchanged | baseline suites | additive narrow dispatch | reverse owned hunks | release owner | isolation row |

## Risks / Trade-offs / Residual Risk
Objects deliberately differ from full Vim and from existing motions for NBSP and cross-line behavior. That is visible, bounded and requires Human acceptance before apply. No feature performance claim is made; scans are line-bounded and counts capped, while existing atomization cost remains unchanged.

## Migration Plan
No migration, persisted-state change, config toggle or dependency update. After approval implement the object slice first; independently rebase/review the later character-search plan against its final parser seam.

## Rollback
Trigger: any wrong-span edit, state leak, chip/image loss or compatibility regression. Owner: future implementer/release owner. Identify only this slice's accepted hunks in composer and its tests, prepare a reverse patch from that exact diff, run `git apply --reverse --check <word-object-only.patch>` in the implementation worktree, then `git apply --reverse <word-object-only.patch>`. Never whole-file checkout/reset or reverse unrelated leader/search hunks. If later character-search hunks overlap, stop and manually reverse the object portions in dependency order with owner review; preserve unrelated work. Inspect diff and run original composer/shortcut suites plus bytecode-disabled `diw` baseline probe (caret 11). No rollback command is executed during planning.

## Open Questions
No hidden semantic choice remains: normative rules are explicit proposals. Human acceptance of those rules, apply authorization, implementation proof, independent audit and candidate-bound verification remain pending. Search is a later slice, not a task here.

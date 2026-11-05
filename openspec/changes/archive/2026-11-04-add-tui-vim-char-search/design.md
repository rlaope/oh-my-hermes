# Design

## Context
This is ordered slice 2 after add-tui-vim-word-objects. Read-only baseline seams and stock Vim comparisons in findings.md support this proposed architecture, not a working search prototype. All target semantics remain UNPROVEN; no source changes occur in planning.

## Goals / Non-Goals
Implement only the accepted CS-1..CS-7 contract in a future authorized candidate. Reuse atom coordinates, prefix/count parsing and characterwise operator effects. No new package, public API, key constants, visual engine, cross-line search or full-Vim parity promise.

## System Boundaries and Ownership
- Composer owns transient _prefix/_operator/counts and per-instance remembered search; no app/global state, network or persistence.
- _normal_char at baseline line 841 owns prefix completion; _command at 872 owns standalone search/repeat dispatch; _motion_span at 948 remains ordinary-motion range resolution; _operate at 987 delegates to common operator effects.
- _atoms/_line_of are the coordinate and logical-line boundary authorities. Never use display-row coordinates or split token atoms.
- Future edits: src/tui/composer.py; tests/test_tui_composer.py; only necessary integration tests in tests/test_tui_shortcuts.py. Source in the scratch checkout remains read-only. Sibling word-object plans are inputs, never outputs of this slice.
- Implementer owns the additive code; independent auditor owns candidate-bound test replay; Human owns semantics, apply and release decisions.

## Interfaces and Data Shapes
Private proposed shapes (names can change only with equivalent accepted contracts):
- `_last_search: tuple[str, str] | None`, default None, init=False/repr=False/compare=False; `(kind, normalized_target)`, where kind is f/F/t/T. Exclude count, offsets and _Snapshot. Do not put it in _drop_pending.
- Extend existing `_prefix` values with f/F/t/T. Do not overload i/a descriptor state: pending descriptor completion remains ahead of fresh commands and search target completion precedes numeric parsing. f2 is search for literal 2, not a count.
- `_search_motion(kind: str, target: str, times: int, *, repeat: bool = False) -> tuple[int, int] | None`: pure with respect to Composer edits/caret/memory/pending; returns `(landing_atom_index, matched_atom_index)` or None. It obtains atoms/current index/current line bounds and validates one NFC printable grapheme. Matching skips chips and image-token atoms entirely. A miss cannot be represented as `(i,i)` because an adjacent till is a success.
- Counts are consumed through _take_count, min(product,9999). Explicit search scans nth matching occurrence beyond i. Repeated f/F scans nth match; repeated t/T simulates count progressing steps with the adjacency skip in CS-6. Only commit final success, never intermediate landings.
- `_operate_span(operator: str, start: int, end: int) -> None` denotes the common character-offset effect seam proposed by word objects; reuse its final accepted name/shape rather than creating a competing effect path. Ordinary `_operate` and object/search completions call it. Search resolves atom endpoints then converts using bounds. If slice 1 has not established this seam, reconcile before apply.
- Explicit search completion: validate follower, compute outcome, snapshot operator/counts as needed, drop transient state, then on success update _last_search and either set caret or apply range. On miss return before any effects, especially _enter_insert. Successful empty T updates memory; its d/y do not replace register; c enters INSERT at original caret.
- Repeat: derive kind from memory (; identical, comma opposite), resolve speculatively, drop transient state, execute once, never rewrite remembered kind/target. Resolve against current text, never old offsets.
- _modal intercepts a pending search before BACKSPACE/DELETE h/x conversion and leader routing. Escape and invalid events cancel/consume; Paste drops pending then follows the existing paste path. Shared handle Ctrl undo/redo retains existing behavior and drops pending. Existing leader follower precedence stays intact.
- Lifecycle: _clear (including successful submit) and set_vim clear memory; _drop_pending, _enter_normal/_enter_insert, _load/history, _take_step and ordinary edits do not. A new Composer starts with None. Register/search memory are not undo snapshots.

## Invariants and Failure Behavior
Ranges in atom coordinates: f [i,m+1); t [i,m); F [m,i); T [m+1,i). Neither search nor operator includes NEWLINE. Nonempty d/c/y reuse _yank, _replace, _enter_insert and handle/_step grouping. y/motions do not create text undo steps. d lands at/clamps span start; c enters INSERT there; y lands at span start. Miss/cancel leaves all editor data and memory unchanged except transient pending clears. Unsupported ordinary commands stay ordinary no-ops. Counts cannot leak to a later command. Invalid pending-search events are consumed rather than performing a second edit.
All asserted ASCII carets are zero-based. `_atoms` bounds convert only at the effect boundary; never mix codepoint offsets and grapheme/atom indices. Chips may be crossed and included in edits whole, not searched internally; image metadata follows existing register/put cleanup. Normal f/t movement never mutates metadata.

## Decisions and Rejected Alternatives
| decision | chosen approach | rejected alternative | evidence / falsifier |
| --- | --- | --- | --- |
| parser state | extend _prefix and add one remembered tuple | new modal state machine or global last search | existing r/g and sibling object seam; stop if incompatible |
| failure | resolver None, effects only on success | empty span for miss | c would incorrectly enter INSERT |
| backward endpoints | exclude original caret | symmetric inclusive endpoints | stock Vim dFx/dTx reference |
| till repeat | skip adjacent self-landing on repeat steps only | naive nearest-match reuse | tX; reference progresses; CS-6 explicitly defines counted behavior |
| text search | complete normalized ordinary grapheme atoms, current logical line | raw string find / chip substring / display row | existing atoms and newline boundaries |
| integration | common characterwise effect helper | duplicate yank/delete/change path | accepted word-object seam and metadata regressions |

## Prototype Findings Consumed
| finding / evidence | design consequence | remaining proof needed |
| --- | --- | --- |
| H1 fb missing | additive search dispatch required | all target acceptance assertions |
| H2 count/prefix/atoms seams | reuse current architecture | ordered parser integration |
| H3 backward reference | exact asymmetric range table | 12 operator-direction subtests |
| H4 25 leader tests pass | regression floor | combined candidate replay |
| till reference/count subtlety | explicit small count contract | Human acceptance and mirrored repeat tests |

## Material Failure Controls
| requirement | failure mode | prevention | detection | containment | recovery | owner | proof |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CS-1/3 | newline crossing/partial count | hard [s,e), speculative resolver | directions, miss, counts tests | no effect before success | owned reverse patch | implementer | acceptance matrix |
| CS-2 | target digit/operator/space redispatch | prefix completion first | literals/cancel tests | consume invalid follower | drop transient state | implementer | acceptance matrix |
| CS-4 | backward off-by-one or c-on-miss | range table and None distinction | full d/c/y cross-product, adjacent/miss | shared effects only | undo or owned reverse patch | implementer | candidate-bound tests |
| CS-5/6 | reverse poisons memory, stuck till | immutable remembered direction and repeat simulation | repeat/memory/till_repeat/repeat_miss | abort whole repeat on miss | preserve last successful tuple | implementer | acceptance matrix |
| CS-4/7 | metadata/undo/regression loss | existing register and effect machinery | effects/isolation and original suites | stop apply/release | owned reverse patch | implementer/auditor | full replay |

## Risks / Trade-offs / Residual Risk
Counted t/T repeat is deliberately specified as repeated progressing steps and may differ from stock Vim edge cases. Failure preserves last successful search rather than last attempted search. Grapheme/chip-safe matching differs from raw codepoint matching. No performance claim has been measured; the bound is the current logical line and count <=9999, using a forward/backward iterator rather than repeated full scans where feasible. Human must accept these explicit semantics; they are not open implementation guesses.

## Migration Plan
No data/config migration. First accept/audit word objects, then accept/audit this package, then authorize a separate candidate. Record accepted artifact hashes, parent word-object candidate revision and environment. Add focused tests and minimal implementation in the authorized worktree only. Replay both slices and original regressions. No source materialization or release now.

## Rollback
Future candidate must capture a word-object-only parent revision and exact character-search-owned source/test patch before release. On span, pending, metadata, memory or compatibility regression, stop rollout; preserve unrelated hunks. Produce the owned patch using `git diff --binary <accepted-word-object-parent> -- src/tui/composer.py tests/test_tui_composer.py tests/test_tui_shortcuts.py` only when its inventory contains exclusively this slice's hunks; record its concrete path and SHA-256 in the future manifest. Run `git apply --reverse --check <owned-patch>` then `git apply --reverse <owned-patch>` in the approved candidate. These are gated future commands, not executed here. Review remaining diff and replay word-object and original TUI suites plus baseline fb probe. If later edits overlap a hunk or reverse check fails, stop and ask owners for a narrower manual reverse patch, then check/apply/replay; never checkout/reset/restore a whole file. Preserve the word-object slice and unrelated changes.

## Open Questions
No unresolved endpoint/count/cancellation implementation choice remains in this proposal. Human semantic acceptance (including the documented Vim divergences), actual accepted slice-1 seam, concrete implementation worktree, revision/manifest paths and separate apply permission remain prerequisites. All target behavior is unproven.

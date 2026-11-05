# Proposal

## Why
`diw` currently leaves text unchanged but moves the caret. Existing operator plumbing can be extended without adding a second modal subsystem.

## What Changes
Add operator-pending `iw` and `aw` for d/c/y using the exact contract in `specs/tui-vim-word-objects/spec.md`. This is slice 1; the separately planned `add-tui-vim-char-search` follows and must preserve this parser state contract.

## Outcome Contract
- Actor / pain: Vim-mode composer users need whole-token edits from anywhere inside a token.
- Baseline: findings H1, text unchanged/caret 11 after `diw` at caret 8.
- Required outcome: deterministic line-local space/tab word objects, counts, atomic selections and existing register/undo semantics.
- CTQs: every acceptance row passes on the exact future candidate; no non-Vim/leader/motion regressions; no unchecked acceptance claims reported as delivered.

## Boundaries
- IN: Composer parser prefix addition, atom range calculation, shared operator execution and tests.
- OUT: f/F/t/T, ;/,, visual mode, Unicode punctuation classes, key decoder changes, persistence, dependencies and implementation now.
- Must NOT: mutate source in this run, authorize apply, replace whole files during rollback, alter `.isspace()` motion semantics.

## Capability Changes
| capability | change | behavior | prototype evidence |
| --- | --- | --- | --- |
| tui-vim-word-objects | ADDED | operator `iw`/`aw` | Target UNPROVEN; source-backed H1-H3 define seam and acceptance gap |

## Human Decisions
| decision | owner | status | rationale | expiry / N/A |
| --- | --- | --- | --- | --- |
| planning package | Human | authorized by task | no implementation | this run |
| exact word/count/line semantics | Human | proposed, awaiting acceptance | choose explicit minimal WORD-style scope | before apply |
| apply / release | Human | not authorized | baseline evidence is not target proof | N/A |

## Controls and Impact
- Selected lanes: [base]. Affected surfaces after approval: `src/tui/composer.py`, `tests/test_tui_composer.py`, and only necessary additions to `tests/test_tui_shortcuts.py`.
- Dependencies / compatibility: no new library, key constant, configuration or persisted data. Existing operator, undo, register, leader and key-decoder paths retained.
- Material risks: selecting wrong whitespace, leaking pending state, splitting chips, undo fragmentation; acceptance contains falsification checks for each.
- Lifecycle: `planning -> opsx-audit -> opsx-apply -> opsx-qa -> codereview:branch-delta -> opsx-archive`. This run stops in planning.

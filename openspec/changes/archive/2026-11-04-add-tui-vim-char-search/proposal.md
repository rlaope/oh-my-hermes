# Proposal

## Why
Baseline f/F/t/T and repeat keys have no inline-search dispatch; users cannot express character-targeted edits. Existing parser/count/operator machinery offers a small seam after word objects.

## What Changes
Add `tui-vim-char-search`: f/F/t/T motions, ;/, repeats, d/c/y integration, counted targets and pending cancellation. Exact behavior is authoritative in specs/tui-vim-char-search/spec.md.

## Outcome Contract
- Actor / pain: Vim NORMAL unmasked Composer users need deterministic in-line jumps and edits.
- Baseline: findings H1, `fb` on `alpha beta gamma` at caret 0 leaves it at 0; H2 identifies existing seams, H3 exposes asymmetric backward endpoints.
- Outcome: logical-line-local, atom-safe movements and characterwise operators; miss is an atomic no-op; counts and repeats cannot get stuck on adjacent till targets.
- CTQs: every assertion passes on future bound candidate; existing composer/shortcut/TUI suites and accepted word objects remain green; no source writes or checked implementation tasks in this run.

## Boundaries
- IN: f/F/t/T, ;/, remembered successful search, d/c/y, counts/cancellation, logical-line and chip/image boundaries, shared effects, exact test contracts and hunk rollback.
- OUT: regex / search, wrapping or cross-line search, dot-repeat, visual mode, key decoder/constants changes, dependencies, persistence, implementation now.
- Must NOT: widen to a Vim engine rewrite, silently change word motions/objects, implement only lowercase t, omit repeats, treat misses as empty c, or reset whole source files.

## Capability Changes
| capability | change | behavior | prototype evidence |
| --- | --- | --- | --- |
| tui-vim-char-search | ADDED | bounded search/repeat/operator contract | UNPROVEN target; findings H1-H4 establish baseline and seam only |

## Human Decisions
| decision | owner | status | rationale | expiry / N/A |
| --- | --- | --- | --- | --- |
| planning only | Human | authorized | assigned task | this run |
| include T and ;/, in slice 2 | Human | task-required | supersedes preliminary ground reservation | N/A |
| failed-search memory, count-as-progressing-till-repeat, empty T effects | Human | proposed, await acceptance | explicit deterministic minimal behavior, not full Vim equivalence | before apply |
| apply/release | Human | unauthorized | planning validity is not implementation proof | N/A |

## Controls and Impact
Lanes: [base]. Future affected paths: src/tui/composer.py, tests/test_tui_composer.py, only necessary tests/test_tui_shortcuts.py additions. Dependency: accepted word-object parser/effect seam first; no new package/config/key constant. Risks: boundary off-by-one, stuck repeat, leaked counts, literal target misdispatch, c-on-miss, metadata loss; each has negative acceptance checks.
Lifecycle: `planning -> opsx-audit -> opsx-apply -> opsx-qa -> codereview:branch-delta -> opsx-archive`. Stop here in planning.

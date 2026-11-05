# Delivery Plan

## Atomic Candidate
Planning candidate is only this change directory, including .openspec.yaml and all planning artifacts through tasks. Shared workspace config/grounding, source and sibling search change are inputs, not writable outputs here.
| kind | canonical path | inclusion reason |
| --- | --- | --- |
| metadata/plans | openspec/changes/add-tui-vim-word-objects/.openspec.yaml; triage.md; pitch.md; findings.md; proposal.md; specs/tui-vim-word-objects/spec.md; design.md; acceptance-plan.md; environment-baseline.md; delivery-plan.md; tasks.md | complete auditable planning contract |
| future implementation | src/tui/composer.py | additive object parsing/range/effects |
| future tests | tests/test_tui_composer.py; only necessary tests/test_tui_shortcuts.py additions | requirement and application regression proof |
| forbidden scope | key constants, dependencies/locks, generated outputs, persistence, other source, sibling change | unnecessary for this slice |

## Materialization
Source root: `/Users/danrio/.hermes/cache/scratch/pr2545-shardfix` at baseline commit `fcd2abcb11e323ccba4c26a3b340e7d377c0daa8`. Source stays unchanged. Planning outputs already live under the separate planning workspace. No implementation materialization now.
After approval, Human names a new implementation worktree path and branch and authorizes its creation from the exact approved baseline. Future apply records the exact `git worktree add -b <approved-branch> <approved-path> fcd2abcb11e323ccba4c26a3b340e7d377c0daa8` command with approved concrete values before running it; this is a gated recipe, not a claimed completed action. Capture `git status --porcelain=v1`, `git diff --name-status`, full candidate diff and SHA-256 hashes; verify only declared files changed. No commits, merge, rebase, push, PR or source reset in this planning task.

## Controller Chain
`planning -> opsx-audit -> opsx-apply -> opsx-qa -> codereview:branch-delta -> opsx-archive`.
Human owns semantic acceptance and apply authorization; implementer owns code; independent auditor owns acceptance replay; release/merge are separate decisions. Planning artifact existence does not authorize apply.

## Parallel Join / Ordered Slices
This change is slice 1 and owns no character-search files/artifacts. Parent joins independently audited word-object and `add-tui-vim-char-search` planning packages. Later search implementation must follow the accepted word-object seam and keep descriptor completion precedence; merge conflicts return to respective owners instead of widening this slice. Whole-candidate QA reruns composer/shortcut and TUI discovery after both implementation slices. Search behavior is not a word-object acceptance condition.

## Invalidation
| mutation | invalidates | required restart |
| --- | --- | --- |
| object/count/boundary semantics | proposal/spec/design/acceptance/tasks and feature proof | Human acceptance then affected implementation and full acceptance |
| parser/effects implementation | candidate binding and affected checks | rebind candidate, replay target + regression tests |
| runtime/source/schema/environment | environment digest and candidate evidence | rebaseline then affected checks |
| later search overlapping parser hunk | integration assumptions and whole-candidate QA | owner reconciliation and combined QA |
| report-only spelling edit | artifact hash only | rebind changed artifact, no unchanged-code test rerun |

## Release Observation
N/A: base planning lane only; no release selected, no candidate shipped and no observation claimed.

## Rollback
Triggers: wrong deletion span, stuck pending state, unexpected INSERT, lost chips/images or compatibility failure. Future implementer/release owner owns containment. See design.md for the hunk-level reverse-patch recipe and overlap stop condition. Restore only word-object-owned hunks and tests, preserve unrelated leader/search work, inspect remaining diff, and rerun original composer/shortcut suites and baseline `diw` probe. Escalate overlapping/dependent search hunks to owners; never whole-file checkout/reset. Planning package withdrawal likewise targets this change directory only under separate authorization; no deletion performed here.

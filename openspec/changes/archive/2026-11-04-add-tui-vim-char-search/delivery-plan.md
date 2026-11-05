# Delivery Plan

Archived planning contract: the prospective language below is preserved as the pre-implementation record, not current status. Implementation and independent replay are observed; Human SHIP IT now authorizes delivery/publication. Native lifecycle remains NON_RUN. See [verification-evidence.md](verification-evidence.md) and [tasks.md](tasks.md) for current evidence and incomplete conjuncts.

## Atomic Candidate
Planning candidate includes this change directory only. Read-only source, shared workspace ground/config and sibling word-object artifacts are inputs, not outputs.
| kind | canonical path | inclusion reason |
| --- | --- | --- |
| planning metadata | openspec/changes/add-tui-vim-char-search/.openspec.yaml | agent-harness schema binding |
| planning artifacts | same directory: triage.md, pitch.md, findings.md, proposal.md, specs/tui-vim-char-search/spec.md, design.md, acceptance-plan.md, environment-baseline.md, delivery-plan.md, tasks.md, verification-matrix.md | complete planning contract through unchecked tasks |
| future implementation | src/tui/composer.py | additive prefix/resolver/memory and common effects integration |
| future tests | tests/test_tui_composer.py; only necessary tests/test_tui_shortcuts.py additions | target and application regression assertions |
| forbidden changes | keys/constants, dependencies/locks, generated outputs, config, unrelated source and sibling package | unnecessary for this slice |
No generated output, lock or configuration mutation is needed. Accepted revisions include every metadata/planning artifact above and the accepted word-object candidate identity, all hashed in the future candidate manifest.

## Materialization
Read-only source is `/Users/danrio/.hermes/cache/scratch/pr2545-shardfix` at `fcd2abcb11e323ccba4c26a3b340e7d377c0daa8`. No implementation materialization now. After acceptance and apply permission, use the concrete approved word-object candidate as the parent, never the baseline without word objects. Human must supply/approve the new candidate worktree path, branch and exact slice-1 parent revision. Record the fully substituted `git worktree add -b <approved-search-branch> <approved-search-path> <accepted-word-object-parent>` before executing it. Missing concrete values block apply, not a license to guess.
Inventory proof before/after: `git status --porcelain=v1`, `git diff --name-status`, full diff, SHA-256 of declared changed files and artifact/environment bindings. Candidate manifest must separate accepted slice-1 parent content from slice-2 owned patch. Verify undeclared files/config/locks/generated outputs are absent. No source writes, commits, merge, rebase, push, PR or Git reset during this task.

## Controller Chain
`planning -> opsx-audit -> opsx-apply -> opsx-qa -> codereview:branch-delta -> opsx-archive`.
Human accepts semantics/authorizes apply; independent audit precedes apply; authorized implementer builds; independent QA checks bound candidate; review owns delta verdict; archive/release remain separate future gates. Planning done does not mean lifecycle complete.

## Parallel Join / Ordered Slices
Slice 1 is add-tui-vim-word-objects; this is slice 2. Parent joins their independent planning audits; later source application is ordered, not concurrent conflicting edits. Both touch _normal_char/_operate and the same composer tests. Search consumes the accepted descriptor/effect seam and preserves iw/aw. Any conflict returns to both owners for narrow hunk reconciliation, not whole-file replacement or scope expansion. Whole-candidate QA reruns both accepted feature suites, composer/shortcuts and all test_tui discovery. No search ownership over sibling artifacts.

## Invalidation
| mutation | invalidates | required restart |
| --- | --- | --- |
| endpoints, counts, repeats, target/cancel or memory semantics | spec/design/acceptance/tasks and affected feature evidence | Human acceptance then implementation/replay |
| parser/resolver/effects candidate | bindings and affected checks | rebind and replay target + integration suites |
| accepted word-object parent or overlapping hunks | seam assumptions, candidate identity, combined QA | owner reconciliation and whole-candidate replay |
| source/runtime/schema/tool identity | environment digest and evidence | recapture environment/rebind then affected checks |
| report-only spelling | artifact binding only | update hash; no unchanged-code test rerun |

## Release Observation
N/A: base planning lane only, no release/candidate shipped. No runtime observation or rollback exercise is claimed. Future release observation lane needs separate acceptance and ownership.

## Rollback
Trigger: wrong span, c-on-miss, stuck repeat/pending, metadata loss or regression in either slice. Implementer/release owner stops rollout and follows the exact hunk reverse-check/apply recipe in design.md using the captured slice-2 patch and accepted word-object parent. Verify patch SHA-256, review owned hunk inventory, reverse-check before reverse-applying, inspect remaining diff and replay word-object/original TUI suites and baseline fb. If overlaps make reversal unsafe, stop/escalate for manual hunk reconciliation; never reset/checkout/restore whole source/test files. Integrity means slice-2 hunks removed and accepted slice-1/unrelated hunks retained. Withdrawal of planning artifacts would require separate authorization and is not performed here.

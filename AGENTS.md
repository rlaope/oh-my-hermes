# OMH Agent Contract

This file is the repo-local operating contract for coding agents working on
oh-my-hermes, including Codex, Claude Code, Hermes runtime/handoff paths, and
generic executor profiles.

## Product Direction

Read `docs/DIRECTION.md` before changing architecture, workflow behavior,
wrapper contracts, generated skill guidance, or coding delegation semantics.

OMH is a Hermes-native wrapper orchestration layer. Keep Hermes responsible for
chat intake, clarification, source-backed research, planning, and status
narration. Keep main coding work delegated to the selected coding owner through
explicit prepared handoffs and observed evidence. Do not make Codex the implicit
default in product language, docs, schemas, prompts, or reports when Claude
Code, Hermes runtime/handoff paths, or generic executor profiles are also valid
owners.

When developing OMH itself, treat Codex, Claude Code, and Hermes
runtime/handoff paths as first-class product surfaces. User-facing runtime
selection may choose one coding owner for a task, but OMH feature design,
contracts, docs, setup, memory recall, and status/reporting changes should
consider all three surfaces unless a change is explicitly scoped to one
executor. If support differs, document the difference as a capability boundary
instead of silently optimizing for Codex.

Do not turn OMH into a hidden Hermes runtime patch, transport bot, network
service, LLM router, or secret coding executor.

## Delivery Grain

One user goal should normally produce one PR.

Plan, explain, and report delivery at the full user-goal completion grain. Do
not frame a recommendation as "the first PR", "initial PR", "first slice", or a
similarly partial unit unless the user explicitly asks for phased delivery or an
independent release/rollback boundary forces a split. When implementation must
be split, state the complete target capability first, then explain the concrete
split reason and the remaining capability gap.

Use multiple focused commits inside the same goal PR when useful. Planning docs,
tests, implementation, code-review fixes, CI fixes, and small follow-up docs
belong in the same PR when they serve the same user goal.

Do not split review feedback or small follow-up fixes into new PRs merely
because a previous commit already exists. Split only when the next change is a
different user-facing goal, has independent release or rollback value, would
make the current PR too risky to review, is blocked by an external decision, or
the user explicitly asks for separate PRs.

When the user asks to merge, finish review fixes in the current PR first, rerun
verification, wait for required checks, then merge if authority is clear.

## Pull Request Reports

PR descriptions must read like a useful feature report, not a terse changelog.
When a coding agent opens a PR for this project, use the repository PR template
and fill every relevant section with concrete, reviewable detail.

Every PR body should explain:

- What capability, workflow, command, or contract changed.
- Why the change exists, including the user problem, product gap, or operational
  failure that motivated it.
- What the user or operator can do after the change that they could not do
  before.
- How the implementation works at the boundary level: important modules,
  commands, generated files, persisted state, or wrapper contracts touched.
- What verification was actually observed, including CI, targeted tests,
  generated-output checks, dry-runs, or manual Hermes/TUI gaps.
- What risks, rollout notes, compatibility concerns, or follow-up work remain.

Avoid one-line summaries such as "update docs" or "fix setup" when the PR
changes user-facing behavior. Prefer a short narrative plus bullets that make
the feature's origin, behavior, and evidence obvious to a reviewer reading the
PR without the chat history.

## Implementation Boundaries

- No LLM, API, Discord, Slack, GitHub, or network calls inside core `omh`
  features unless the user explicitly approves a scoped integration.
- No Hermes core patching.
- Runtime artifacts are local, deterministic, schema-versioned, and
  metadata-only by default.
- Preserve prepared versus observed boundaries. `prepared_not_observed` is not
  execution, review, CI, merge-readiness, or merge evidence.
- Wrapper sessions own chat continuity and plan decisions only. Linked runtime
  runs own handoff, dispatch, execution, verification, review, CI, and merge
  evidence.
- Coding delegation and memory recall should be executor-neutral by default:
  name the selected owner (`codex`, `claude-code`, `hermes`, runtime profile, or
  generic executor) and only use Codex-specific wording for Codex-only lifecycle
  features.
- Project memory lives under `.omh/memory/` as reviewed OMH-local prepared
  context. Keep candidates separate from approved records, preserve
  review-first defaults, and never present recall packs as execution, review,
  CI, merge, or Hermes internal-memory evidence.
- Generated skills come from catalog data. Prefer updating
  `src/skills/catalog.py` and regenerating docs over hand-editing generated
  output.

## Coding Style

- Keep code, docs, commit messages, and PR text in English.
- Reply to Korean user messages in Korean. Use polite Korean by default; do not
  use banmal, casual endings, or overly familiar phrasing unless the user
  explicitly requests that tone.
- For Korean explanations, prefer concrete, human-readable wording that names
  what exists, what is missing, and the exact complete target behavior. Avoid
  vague process labels or "small first PR" framing when the user asked to reason
  at the whole-capability level.
- Prefer small, explicit Python functions and data structures over clever
  string parsing.
- Keep public claims conservative and test-backed.
- Avoid adding dependencies unless the user explicitly approves the dependency
  and its packaging story.

## CodeGraph

This repository is initialized for external CodeGraph (`@colbymchenry/codegraph`).
See `docs/CODEGRAPH.md` for setup, rebuild, query, and agent-usage details. The
local index lives under `.codegraph/`; commit only `.codegraph/.gitignore`, not
the machine-local SQLite database or daemon files.

Use CodeGraph as a project navigation aid before broad code exploration:

```sh
npx @colbymchenry/codegraph status .
npx @colbymchenry/codegraph query <symbol-or-text>
npx @colbymchenry/codegraph explore <area-or-task>
npx @colbymchenry/codegraph impact <symbol>
```

If the index is missing or stale, refresh it with:

```sh
npx @colbymchenry/codegraph init .
npx @colbymchenry/codegraph sync .
```

CodeGraph output is prepared local code-intelligence context only. It is not
execution, review, CI, merge-readiness, or merge evidence.

## Verification

Use the smallest check that proves the claim, then broaden when the touched
surface is shared.

Typical gates:

```sh
PYTHONPATH=tests uv run python -m unittest tests/test_cli.py -v
PYTHONPATH=tests uv run python -m unittest tests/test_router_content.py -v
PYTHONPATH=tests uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src tests
uv run python -m omh.cli docs workflows --check
git diff --check
```

For direction, docs, generated skill, wrapper contract, lifecycle, or runtime
artifact changes, add or update tests that lock the public contract.

## Git And Commits

Use executor-appropriate branch names. `codex/` is fine for Codex-authored work,
but use neutral or matching prefixes such as `agent/`, `claude/`, or `hermes/`
when Claude Code, Hermes, or a generic executor owns the coding work.
Before editing files for a coding task, create or switch to a dedicated
task branch unless the current branch is already clearly dedicated to that exact
user goal. Do this before the first implementation edit so the work does not mix
with unrelated branch history or user changes.

Every commit must include DCO signoff and the local Lore-style trailers used by
this repository:

```text
Constraint: <external constraint that shaped the decision>
Rejected: <alternative considered> | <reason>
Confidence: <low|medium|high>
Scope-risk: <narrow|moderate|broad>
Directive: <forward-looking warning>
Tested: <what was verified>
Not-tested: <known gaps>
Signed-off-by: <name> <email>
```

Never revert user changes or unrelated untracked files. If an unrelated file is
dirty, leave it alone and report it.

# OMH Agent Contract

This file is the repo-local operating contract for Codex agents working on
oh-my-hermes.

## Product Direction

Read `docs/DIRECTION.md` before changing architecture, workflow behavior,
wrapper contracts, generated skill guidance, or coding delegation semantics.

OMH is a Hermes-native wrapper orchestration layer. Keep Hermes responsible for
chat intake, clarification, source-backed research, planning, and status
narration. Keep main coding work delegated to Codex-like executors through
explicit prepared handoffs and observed evidence.

Do not turn OMH into a hidden Hermes runtime patch, transport bot, network
service, LLM router, or secret coding executor.

## Delivery Grain

One user goal should normally produce one PR.

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
- Generated skills come from catalog data. Prefer updating
  `src/skills/catalog.py` and regenerating docs over hand-editing generated
  output.

## Coding Style

- Keep code, docs, commit messages, and PR text in English.
- Reply to Korean user messages in Korean.
- Prefer small, explicit Python functions and data structures over clever
  string parsing.
- Keep public claims conservative and test-backed.
- Avoid adding dependencies unless the user explicitly approves the dependency
  and its packaging story.

## Verification

Use the smallest check that proves the claim, then broaden when the touched
surface is shared.

Typical gates:

```sh
PYTHONPATH=tests uv run python -m unittest tests/test_cli.py -v
PYTHONPATH=tests uv run python -m unittest tests/test_router_content.py -v
PYTHONPATH=tests uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src tests
uv run python -m src.cli docs workflows --check
git diff --check
```

For direction, docs, generated skill, wrapper contract, lifecycle, or runtime
artifact changes, add or update tests that lock the public contract.

## Git And Commits

Use `codex/` branch names unless the user requests another prefix.

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

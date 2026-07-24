# Adding a New Installable Skill

Checklist for adding a skill to the OMH catalog. Every surface below is
enforced by a test; skipping one fails CI with an actionable message naming
the file and structure to edit.

## 1. Define the skill (single registration point)

- Add the `SkillDefinition` to `src/skills/catalog.py`.
- Set `capability_family` **only** when the skill's user-facing family differs
  from its awareness-lane default (rare — 5 of 88 skills today). Leave it
  empty otherwise; the lane default governs.
- If the skill needs a recommendation policy, add its `_SKILL_POLICIES` entry
  in `src/routing/recommend.py`.

## 2. Hand-authored surfaces (curated order and UX copy)

These cannot be derived from the catalog; each has a gate that fails with
paste-ready guidance:

| Surface | File / structure | Gate |
| --- | --- | --- |
| Awareness lane membership | `awareness_primer_payload()` lane `skills` lists in `src/plugin_bundle/omh/awareness.py` | `tests/test_capabilities.py` (lane coverage) |
| Workflow context card lane | `_WORKFLOW_CONTEXT_CARD_BY_WORKFLOW` in the same file | `tests/test_capabilities.py` (context-card coverage) |
| Visible/ack wrapper actions | `VISIBLE_ACTIONS` + `_ACK_PRIMARY_ACTIONS_BY_NEXT_ACTION` in `src/wrapper/contract.py` | `tests/test_wrapper_contract.py` (visible-ack) |
| Next-action label | `NEXT_ACTION_LABELS` in `src/routing/action_copy.py` | `tests/test_wrapper_contract.py` (curated-label gate) |
| Dedicated non-ack chat card | a `*_CHAT_CARDS` entry or bespoke renderer in `src/wrapper/contract.py` | intervention harness + coverage-case gate |
| Coverage case | `ChatCardCoverageCase` in `src/quality/chat_card_coverage.py` or `RoutingInterventionCase` in `src/quality/routing_precision.py` | `tests/test_wrapper_contract.py` (coverage-case gate) |

The curated-label and coverage-case gates carry frozen legacy allowlists; do
not extend the allowlists for a new skill — register the skill instead.

## 3. Exact-count fixtures (contracts, updated in the same commit)

Adding a routing/intervention case moves exact-count assertions in
`tests/test_routing_precision.py`, `tests/test_cli.py`,
`tests/test_hermes_ux_quality.py`, and `tests/test_release_smoke.py`. Grep
those four for the old count.

## 4. Regenerate every generated artifact family

```sh
# skills/*/SKILL.md + references (short template-write loop; see CLAUDE.md)
uv run python -m omh.cli docs workflows --output docs/WORKFLOWS.md
uv run python -m omh.cli docs roles --output docs/ROLES.md
uv run python -m omh.cli docs capability-families
uv run python -m omh.cli cases demo --all --json > examples/use-cases/g1-g10-demo-cards.json
```

## 5. Verify

```sh
uv run python -m compileall -q src tests
uv run python -m omh.cli docs workflows --check
uv run python -m omh.cli docs roles --check
uv run python -m omh.cli docs capability-families --check
git diff --check
PYTHONPATH=tests uv run python -m unittest discover -s tests
```

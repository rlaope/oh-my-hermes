# Model onboarding

The repeatable maintainer loop for the day a model family ships a new
generation (Claude Fable 5 → 5.1, GLM 5.2 → 5.3) or a new sibling (Mythos
5.1 next to Fable 5.1). It is the repo-side counterpart of the installable
`model-optimization` skill: that skill tells Hermes how to run the process in
chat; this file tells the executor working on the repo which files move, in
which order, and what proves each step. `MODEL_OPTI.md` is the reader's map
of the calibration surface and stays the source of provenance.

Boundary first: OMH never calls a model. Everything below is prepared text,
prepared configuration, or documentation. Nothing here is execution, review,
CI, or merge evidence, and a routed model is never proof that a provider
serves it.

## 0. Frame the goal

One user goal → one PR (see Delivery Grain in `AGENTS.md`). A generation
bump is one goal even though it touches ~20 files; do not split it into
"chains" and "docs" PRs. Measurement is the one valid second PR, because it
needs a served route the first PR may not have.

Branch before the first edit: `claude/<family>-<generation>-onboarding`.

## 1. Recognize

Prove what the router sees before touching anything:

```sh
uv run python -m omh.cli coding model-route --executor hermes --model <id> --effort xhigh --role implementation --json
```

Read `model_family` and `effort_change.kind`. Probe every id as served
(`claude-fable-5-1`, `anthropic/claude-fable-5-1`) and every bare name users
type in chat (`fable`, `mythos`). A bare name that classifies `unknown` gets
generic discipline; add it to `_CLAUDE_TIER_ALIASES` (Claude) or the prefix
tables in `src/coding/model_routing.py`, with a `model_family` test.

## 2. Research, official first

For Anthropic models the bundled `claude-api` skill's migration guide is the
official source (model ids, pricing, effort semantics, prompt-tunable
behavioral shifts). For other families: the vendor's release notes, thinking
and tool-calling contract, context and output limits, list pricing, speed
tiers. Then community harness handling (OpenCode, Codex CLI, Aider, Hermes
upstream), labeled separately. Write findings under
`.omc/research/<family>-<generation>/` with every claim labeled official,
community, or observed; a community claim never overrides an official
contract.

## 3. Calibrate, trait to counter

`src/coding/unit_prompt_protocol.py` holds two tables keyed by family:
`HIGH_EFFORT_CALIBRATIONS` (subagent) and `MAIN_AGENT_COMPOSITION_CALIBRATIONS`
(composer). Write the counter for a documented trait, version-aware where
generations differ, and keep counters the guide says to keep even when it
reads as redundant (for Claude 5.1: the single verification pass). Do not
restate universal protocol rules inside a family entry. Then:

- Update the family's section in `MODEL_OPTI.md` (trait, injected text,
  version rule, source). `tests/test_unit_prompt_protocol.py` fails when a
  calibrated family has no section.
- Stay under `UNIT_PROMPT_MAX_BYTES`; the worst-case prompt test measures
  the longest family block.

## 4. Place routing

Rules that have held across every onboarding so far:

- The new generation heads every slot the family already held; the older
  generation stays as fall-through so a machine whose provider only serves
  the old id keeps resolving to the ecosystem (GLM 5.2 behind 5.3, Fable 5
  behind 5.1).
- An access-restricted sibling (Mythos 5.1 = Fable 5.1 under Project
  Glasswing) sits directly behind its public twin and never heads a chain;
  an unapproved account's provider rejection falls the chain through.
- The Claude vendor order inside any chain is Fable 5.1 → Mythos 5.1 → Opus
  5 (owner decision, 2026-09-02). The Hermes lane and the Maestro lane are
  different surfaces and both follow it.
- Shipped defaults change only with explicit owner approval; the operator's
  own placement goes through `omh model-chains set` and
  `omh coding category-maestro set`, never by hand-editing the JSON.

Files that move together (grep the old id to find every site):

| Surface | File |
| --- | --- |
| Hermes-lane editorial chains | `src/coding/model_recommendations.py` |
| Plugin mirror of those chains + approximate price table | `src/plugin_bundle/omh/hermes_delegation.py` (parity test in `tests/test_plugin_hermes_delegation.py`) |
| Maestro-lane built-in table + executor option rows | `src/coding/model_routing.py` (`BUILTIN_CATEGORY_MODELS`, `EXECUTOR_MODEL_OPTIONS`) |
| `model-setup` skill text naming the chains verbatim | `src/skills/catalog_definitions.py` → regenerate `skills/omh-model-setup/SKILL.md` and `docs/WORKFLOWS.md` |
| Skill body budget note | `src/maintenance/release.py` (`FULL_PROFILE_SKILL_BODY_CHAR_LIMIT`, add the `old -> new` line) |
| Public chain tables | `README.md`, `README.ko.md`, `README.ja.md`, `README.zh.md`, `docs/INSTALLATION.md`, `site/index.html`, `site/docs/model-routing/index.html` (`tests/test_model_recommendations.py` reads all seven) |
| Pinned-chain and fallback-count tests | `tests/test_model_recommendations.py`, `tests/test_delegate_route_tool.py`, `tests/test_model_routing.py`, `tests/test_category_maestro.py`, `tests/test_task_scale_routing.py` |
| CLI help examples | `src/commands/coding.py` |

## 5. Price from documented list only

`APPROX_PRICE_PER_MTOK` takes the vendor's first-party list price with the
source and month in a comment. A model or tier without a documented price
gets no entry; absence renders no estimate. Check the existing family rows
while you are there — the Claude 5 rows were stale until the 5.1 pass. Users
can override or supply prices via `~/.omh/routing/model-prices.json`
(`model_price_overrides/v1`).

## 6. Machine placement stays provider-neutral

Chains name model aliases, never providers. `~/.omh/routing/model-chains.json`
carries the order; `model-providers.json` says, per alias, which configured
provider serves it and under which wire id, and an alias with no row falls
back to Hermes' own provider resolution. Keep the two concerns apart: place
the new id in the chains through the CLI, and add a provider row only for an
alias that is genuinely served somewhere else than the default.

```sh
omh model-chains show
omh model-chains set architect "claude-fable-5-1:xhigh, claude-mythos-5-1:xhigh, claude-fable-5:xhigh, ..."
```

`dispatch-models.json` (the Claude Code profile's `--model`) is gated on the
CLI's own account, not on any provider; `providers.json` (the setup
interview's record of held providers and subscriptions) reorders chains per
machine, so a new id whose family no confirmed provider serves lands behind
the served entries automatically. Record which lane got the new id.
An id the resolving provider does not serve is not an error to hide: the
provider's rejection comes back as a normal result and the chain falls
through, which is exactly why the older generation stays behind the new one.

## 7. Prove it

```sh
PYTHONPATH=tests uv run python -m unittest discover -s tests
uv run python -m omh.cli docs workflows --check
uv run python -m omh.cli docs roles --check
uv run python -m omh.cli docs capability-families --check
uv run python -m omh.cli docs ulw-inventory --check
uv run python -m omh.cli docs ulw-site --check
uv run python -m omh.cli release drift
uv run --group lint ruff check src tests
git diff --check
```

## 8. Close with measurement

A calibration ships measurable. Name the baseline-vs-optimized benchmark
pair (old generation vs new, same task corpus, same effort) as the follow-up
when no served route exists yet. A calibration that measures worse than
baseline is revised or removed in the same change that reports the number.

## 9. Report

PR body per the repo template: capability, motivation, boundary-level
implementation, observed verification (the commands above and their
outcome), risks (unserved ids, access-gated siblings, unmeasured
calibration). Commit trailers per `AGENTS.md`.

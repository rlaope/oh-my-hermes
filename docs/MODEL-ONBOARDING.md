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
type in chat (`fable`, `mythos`). When the vendor documents an effort
vocabulary that differs from the family's (GPT-6 Astra: `none` is HTTP 400,
`low` is the floor), record it as an exact-model contract in
`src/coding/model_contracts.py` and probe the unsupported rungs too — the
route must answer `floor_raised`, never pass the rung through;
`omh coding model-contract --model <id>` prints the record.

When the vendor or host exposes multiple spellings for one documented model,
do not infer inheritance by stripping suffixes. Add only the reviewed catalog
ids to `DECLARED_MODEL_CONTRACT_PROJECTIONS`, preserve the requested/provider-
qualified id in the route receipt, and resolve a separate canonical contract
id, reasoning mode, service tier, and `exact`/`declared_inheritance`
provenance. Keep the plugin bundle's explicit mirror parity-tested for
provider eligibility, category projection, and approximate pricing. The host
or runtime owns wire translation. A catalog row is neither entitlement nor
execution evidence, and a malformed or future suffix remains uncontracted
until it receives an explicit declaration.

A bare name that classifies `unknown` gets generic discipline; add it to
`_CLAUDE_TIER_ALIASES` (Claude) or the prefix tables in
`src/coding/model_routing.py`, with a `model_family` test.

### Contract coverage audit

Capture or supply a local inventory, then run the deterministic audit before
and after the onboarding change:

```sh
uv run python -m omh.cli coding model-inventory --json > /tmp/model-inventory.json
uv run python -m omh.cli coding model-contract-audit \
  --inventory /tmp/model-inventory.json \
  --required-model <provider/model-id> \
  --recommended-model <provider/secondary-id> \
  --json
```

`--inventory -` reads stdin. Each flag is repeatable; use
`--intentional-exclusion <id>` only for a reviewed model that is deliberately
outside OMH's contract scope. Input is bounded local JSON (1 MiB maximum), and
the command performs no network calls, configuration writes, route changes,
or issue creation. Its stable `model_contract_coverage/v1` comparison body has
no timestamps and includes inventory source/digest plus per-id exact,
`declared_inheritance`, `intentional_exclusion`, or `missing` status. The
per-id dimensions cover family recognition, contract, effort, high-effort and
composition calibration, provider eligibility, category projection, price
source/absence, and docs. Required missing contracts return nonzero;
recommended and optional discoveries remain advisory. Cold/unavailable
inventories remain distinct from observed empty inventories.

Use the digest diff and missing rows as inputs to model optimization,
onboarding, doctor triage, or a release checklist. They are evidence-bounded
work items, not automatic route changes or provider-readiness claims.

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
(composer), and two keyed by exact model id that resolve before them:
`MODEL_HIGH_EFFORT_CALIBRATIONS` and `MODEL_COMPOSITION_CALIBRATIONS`. Write
the counter for a documented trait, version-aware where generations differ
— in the family table when the trait holds across the family, in the
exact-model table when the new generation's documented traits differ from
the family's and the older generation's prompts must stay byte-stable (GPT-6
Astra over GPT-5.6) — and keep counters the guide says to keep even when it
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
gets no entry; absence renders no estimate. For an explicitly declared alias,
an exact user `model-prices.json` row wins first, then a base-contract row may
be inherited. Documented service-tier multipliers apply to inherited rates
(Astra Fast 2x, Flex 0.5x); a reasoning-mode label such as Astra Pro gets no
fabricated multiplier. Keep cached-input, cache-write, and long-context
caveats in the contract when the approximation table cannot represent them.
Check the existing family rows while you are there — the Claude 5 rows were
stale until the 5.1 pass.

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
uv run python -m compileall -q src tests
uv run --group lint ruff check src tests
uv run python -m omh.cli coding model-contract-audit --inventory <fixture.json> --json
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

An exact-model override has a second pair: `family` vs `optimized` on
`benchmarks/live-model-tools/v1` (`bench.py run --condition family`, then
`analyze.py --baseline-condition family`). The family arm sends the block the
model would inherit if the override did not exist, so the override is judged
against what it replaced, not only against no calibration. Pass rate alone
is the wrong yardstick on that corpus (every arm tends to tie); read the
paired token delta and, where the host records them, tool-call and turn
counts, because a counter for an "over-doing" trait shows up there first.

## 9. Report

PR body per the repo template: capability, motivation, boundary-level
implementation, observed verification (the commands above and their
outcome), risks (unserved ids, access-gated siblings, unmeasured
calibration). Commit trailers per `AGENTS.md`.

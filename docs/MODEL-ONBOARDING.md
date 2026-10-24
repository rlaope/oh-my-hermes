# Model onboarding

The repeatable maintainer loop for the day a model family ships a new
generation (Claude Fable 5 → 5.1, GLM 5.2 → 5.3) or a new sibling (Mythos
5.1 next to Fable 5.1). It is the repo-side counterpart of the installable
`model-optimization` skill: that skill tells Hermes how to run the process in
chat; this file tells the executor working on the repo which files move, in
which order, and what proves each step. `MODEL_OPTI.md` is the reader's map
of the calibration surface and stays the source of provenance.

Boundary first: onboarding never calls a model; OMH's one model call is the
user-requested `omh_jev_ask` tool, which no step below uses.
Everything below is prepared text,
prepared configuration, or documentation. Nothing here is execution, review,
CI, or merge evidence, and a routed model is never proof that a provider
serves it.

## 0. Frame the goal

One user goal → one PR (see Delivery Grain in `AGENTS.md`). A generation
bump is one goal even though it touches ~20 files; do not split it into
"chains" and "docs" PRs. Measurement is the one valid second PR, because it
needs a served route the first PR may not have.

Branch before the first edit: `feature/<family>-<generation>-onboarding`.

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
`omh coding model-contract --model <id>` prints the record. When the vendor
instead publishes a mapping for undocumented rungs and returns no error
(DeepSeek V4.1 Flash: ladder `low`/`high`/`max`; `minimal` → `low`,
`medium` and `xhigh` → `high`, `ultra` → `max`), leave `unsupported_efforts`
empty, record the table in the contract's `effort_mapping`, and let the
route pass the rung through on record — the record says what the rung
bought, and the chains name only documented rungs.

A contract is surface-dependent: the vendor's API page, the vendor's own
client, and the installed Hermes build can each document a different ladder
or limit for the same id. GPT-6 Luna is the first case: the API page lists
`none` through `max` and a 1,050,000-token context (official), the Codex
client's catalog lists `low` through `max` with a 272K window (official-client),
and a Hermes build older than upstream `79ec1f2a34` clamps `max` to `xhigh`
(observed). GPT-6 Sol adds a rung the API does not have: the Codex catalog
lists a Codex-only `ultra`, which stays out of every OMH ladder, including
the machine-readable `surface_efforts`. A ladder can also move between
generations of one tier: GPT-6.1 Sol's API page drops the `none` rung GPT-6
Sol documents, so 6.1 Sol takes Astra's shape (`low` floor, `off` and
`minimal` raised on record) while GPT-6 Sol keeps sending `none`; copy the
ladder from the new page, never from the predecessor's contract. Record the API ladder and limits as the contract and put each
other surface in `surface_notes`, labeled; do not average them and do not
let the narrowest surface overwrite the API record.

When the vendor or host exposes multiple spellings for one documented model,
do not infer inheritance by stripping suffixes. Add only the reviewed catalog
ids to `DECLARED_MODEL_CONTRACT_PROJECTIONS`, preserve the requested/provider-
qualified id in the route receipt, and resolve a separate canonical contract
id, reasoning mode, service tier, and `exact`/`declared_inheritance`/
`dated_snapshot` provenance. Keep the plugin bundle's explicit mirror parity-tested for
provider eligibility, category projection, and approximate pricing. The host
or runtime owns wire translation. A catalog row is neither entitlement nor
execution evidence, and a malformed or future suffix remains uncontracted
until it receives an explicit declaration. The one shape that projects
without a declared row is a vendor's dated snapshot (`<base>-YYYY-MM-DD`,
OpenAI's convention; a provider that serves only `gpt-5.6-terra-2026-07-09`
was reported 2026-09-11): `dated_snapshot_base()` in
`src/coding/model_contracts.py` and its plugin mirror strip only that
trailing shape (month and day ranges, not a calendar), and every caller
projects it only onto a base it already knows — a contract, a declared row, a
priced or provider-mapped alias, a chain entry, or for the HUD's `inherit`
reading the parent session's own model — at that base's own mode and tier,
with `dated_snapshot` provenance. The direction is one way: a snapshot meets
its base, an unpinned base never meets a date-pinned request or parent.
Probe the dated form in this step too; an unknown base with a date must stay
unknown.

A bare name that classifies `unknown` gets generic discipline; add it to
`_CLAUDE_TIER_ALIASES` (Claude) or the prefix tables in
`src/coding/model_routing.py`, with a `model_family` test. Bare vendor names
(`deepseek`, `minimax`, `astra`) stay `unknown` by pinned decision — only the
Claude tier words are bare aliases — so probe the versioned ids and the
vendor's pointer id (`deepseek-flash`), not the vendor name.

### Non-generative models

Some models cannot be onboarded by this loop at all, and the honest move is to
say which steps do not apply rather than to fill them in. `model_class()` in
`src/coding/model_routing.py` answers `generative` or `non_generative` for one
id. A `non_generative` model's documented output is a typed answer over
options the caller supplies, not text. TypeSafe's Jev is the first one OMH
recognizes: it returns a Choice, a Score, or a Noul, and the vendor's
jaggedness page states it "is not trained to generate text".

The vendor calls this a decision model. This repo does not, because
"decision" here already means a gate where a human answers (`decision_gate`,
`action_gate`), and a model class that borrowed the word would send every
future reader to the wrong surface. The class is `non_generative`; the family
is `jev`.

The steps below do not apply, each for its own version of the same reason —
there is nothing generated to shape, compare, or place:

- **§1's effort probe.** There is no effort parameter, so there is no ladder,
  no floor to raise to, and no unsupported rung to record. The contract
  declares `reasoning_efforts: ()` with an empty floor and default, and
  `tests/test_model_contracts.py` carries an explicit branch for that shape
  rather than a loosened assertion.
- **§3 Calibrate.** Counter-guidance is a paragraph appended to a prompt. A
  model that answers a typed question receives no such prompt, so
  `HIGH_EFFORT_CALIBRATIONS` and `MAIN_AGENT_COMPOSITION_CALIBRATIONS` gain
  no entry and `MODEL_OPTI.md` gets no per-family section.
- **§4 Place routing.** The model joins no chain, in either lane. Both chain
  editors refuse it by name: `omh model-chains set` exits 2 and writes
  nothing, and the operator category-maestro config rejects the entry on read
  and on write. `omh coding model-route --model <id>` answers
  `status: model_refused` with a `refusal` record naming the id and the class,
  and prepares no model, no effort, and no chain. A chain that names one
  anyway, because a document was hand-edited past both editors, is filtered
  before a head is picked — on the catalog lane and on the Hermes
  recommendation lane alike, each skipped entry recorded by name.
- **§6 Machine placement.** Nothing to place: a model that is in no chain
  needs no provider entitlement row, and adding one would assert a serving
  family the shipped catalog has never described.
- **§8 Close with measurement.** The family-vs-model prompt pair needs two
  generated answers to compare and there is only one generator. The
  measurement that replaces it scores typed answers against a corpus the
  deterministic router already answers, and it is a separate goal from
  recognition. That lane is `benchmarks/routing-questions/v1`:
  `omh chat route-questions export` projects the two shipped routing corpora
  into typed questions (a Choice over the shortlist plus `none`, one yes/no
  per candidate) with the router's own answer beside each, `score` reads any
  answer set against them with every rate carrying its denominator, and the
  deterministic arm is always the baseline. The external arm takes an
  operator-supplied answers file, so a Jev-class model is scored without OMH
  calling it. OMH's own `omh_jev_ask` tool is a separate, user-requested path:
  its answers can be recorded with `answered_by: omh_jev_ask` and scored as one
  more arm.

What does apply, and what this step therefore produces:

- The contract, read from the vendor's own pages, carrying the answer surface
  in place of the ladder: the question types it accepts, the option ceiling of
  a Choice, the request limits, the published rate limits, and the documented
  traits. `omh coding model-contract --model <id>` prints it.
- `model_class` on the contract record, so a reader of the record learns the
  class without inferring it. The resolver reads the class off the family
  instead (`model_class()`), because it must answer for an id the catalog
  documents no contract for. Both are optional additions: the contract key
  does not move `model_contract/v1`, on the same terms `served_ids` and
  `limits_note` joined it.
- The price row (§5), including a zero side when the vendor publishes one. A
  zero is a price, not an absence, and omitting it makes every run on the
  model report no cost at all.
- The coverage audit, read as it comes out. The dimensions a non-generative
  model reports `missing` for reasons of its own class are `effort`,
  `category_projection`, and `provider_eligibility`, and all three are
  correct. Do not add a rung, a chain entry, or an `intentional_exclusion`
  row to turn them green: the first two are inventions and the third says OMH
  deliberately does not cover a model it does cover. The row may report other
  dimensions `missing` for reasons that have nothing to do with the class —
  `data_handling` reads the same way for every contracted model in the
  catalog — so compare against a generative row before reading one as a gap
  in this onboarding. Read `calibration` the other way round: it reports
  `covered` through the generic fallback, which for this class means the
  generic discipline is on record, not that the model was calibrated. §3
  above says why it cannot be.
- The machine's plugin posture, because such a model reaches Hermes through
  a community plugin rather than a provider route. `omh doctor` always carries
  a `plugin_jev_sidekick` check: `absent` on a machine with no signal,
  otherwise the tier it could read (installed, enabled, credential name
  present) with one note per plugin quoting what that plugin's catalog entry
  declares and where OMH read it, and a note naming any hook the plugin
  declares that OMH also registers. It reads names only, never a credential
  value, and it never says what a plugin does at runtime, because OMH did not
  observe that. `omh doctor --json` carries the full `jev_sidekick_posture/v1`
  payload under the check's `detail`.
- OMH's own route to the model, where one exists. For Jev that is the opt-in
  `omh_jev_ask` plugin tool and the six default-installed `omh-jev-*` skills
  that call it (`omh-jev-ask`, `omh-jev-route`, `omh-jev-failure-triage`,
  `omh-jev-review-gate`, `omh-jev-action-check`, `omh-jev-done-check`). The
  tool sends only after the user names Jev in that turn, only with the user's
  own key, and records one metadata-only ledger row per ask; the same
  `plugin_jev_sidekick` check reports its route by variable name, its ledger,
  and what it sends. A preset's thresholds are written against the pinned
  version, so a new generation re-reads them before the pin moves.

The next subsection's rule applies with one twist worth stating before you
reach it. A model served through a Hermes plugin rather than a provider route
is proved served by one of that plugin's tool calls observed inside a Hermes
session, not by a `hermes --oneshot` probe: the plugin tool is not on that
path at all, so the probe can only ever fail for the wrong reason.

### Served, not released

A released id, a catalog row, and a routed model are three different things,
and none of them is a served route. Before any measurement or machine
placement, prove the route with one call through the profile that will run
the benchmark, and read the usage file, not the exit code:

```sh
hermes --oneshot "Reply with exactly the single word OK." --in "$PWD" \
  --provider <provider> --model <id> --reasoning low --usage-file usage.json
```

`usage.json` names the `model` and `provider` that answered and a
`cost_status` (`included` for a subscription route, `unknown` when the host
cannot price it); a provider rejection lands there too, with `failed: true`.
Gateways serve vendor-prefixed ids (`z-ai/glm-5.2-ultrafast`,
`moonshotai/kimi-k3-ultrafast`) and reject the bare alias, so probe the id
exactly as the manifest will name it. GPT-6 Astra sat "released" for a day
before the owner account served it; #1310 stayed blocked on this probe, not
on the release note.

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
`declared_inheritance`, `dated_snapshot`, `intentional_exclusion`, or
`missing` status. The
per-id dimensions cover family recognition, contract, effort, high-effort and
composition calibration, provider eligibility, category projection, price
source/absence, and docs. Required missing contracts return nonzero;
recommended and optional discoveries remain advisory. Cold/unavailable
inventories remain distinct from observed empty inventories.

Use the digest diff and missing rows as inputs to model optimization,
onboarding, doctor triage, or a release checklist. They are evidence-bounded
work items, not automatic route changes or provider-readiness claims.

### Portfolio qualification

Refresh the complete accepted inventory before calibration work, then qualify
it without restricting discovery to known families or the seed snapshot:

```sh
uv run python -m omh.cli coding model-inventory --json > /tmp/model-inventory.json
uv run python -m omh.cli coding model-portfolio-qualification \
  --inventory /tmp/model-inventory.json --json
```

A locally empty refresh does not establish an empty provider catalog. Supply
an accepted host inventory when local discovery cannot observe those ids;
`tests/fixtures/model_portfolio_seed_inventory.json` preserves issue #1515's
seed snapshot for offline regression, not a permanent supported-model list.
An optional inventory `read_date` records the supplied ISO calendar date;
absence stays null. Newly returned ids, including unknown families, always
receive rows and default to `unmeasured` rather than automatic registration.

Use repeatable `--required-model <id>` to block on absent or unmeasured
qualification. `--intentional-exclusion <id>=<reason>` records an explicit
caller runtime-contract exclusion; it is not evidence of measured failure.
`--inventory -` reads stdin, with the audit's bounded JSON validation. The
report never changes configuration or pays for an evaluation. Follow the
existing research, calibration, placement, price, and measurement stages
below; its optimization fields name evidence and missing stages, not a new
process. Existing editorial decisions are labeled `editorial_not_measured`;
new placements need observed role evidence and the independent qualification
guard must pass. Paid measurement requires separate explicit approval.

See [portfolio qualification in MODEL_OPTI.md](../MODEL_OPTI.md#portfolio-qualification)
for supported / optimized / eligible / recommended / excluded meanings,
unmeasured holds, bounded alias standing, and scoped retirement decisions.

## 2. Research, official first — four lanes, in parallel

For Anthropic models the bundled `claude-api` skill's migration guide is the
official source (model ids, pricing, effort semantics, prompt-tunable
behavioral shifts). For other families: the vendor's release notes, thinking
and tool-calling contract, context and output limits, list pricing, speed
tiers. Run the lanes below as separate read-only research agents at the same
time — each writes one dossier under `.omc/research/<family>-<generation>/`
with every claim labeled official (a vendor doc), official-client (the
vendor's own client source, such as the Codex model catalog), observed (a
file:line, a CLI run, or a live read on this machine), or community. On
conflict the earlier label wins: a community claim never overrides an
official contract.

1. **Official** — the vendor's docs, change log, pricing page, and model
   card. Quote the effort table verbatim when one exists (DeepSeek publishes
   `minimal → low`, `medium → high`, `xhigh → high`, `ultra → max`; a
   paraphrase like "nearest level" is not the contract).
2. **Hermes runtime (observed)** — read the installed Hermes Agent AND
   `origin/main` of the upstream checkout for the family:
   `plugins/model-providers/<vendor>/__init__.py` (what the wire carries per
   effort, whether thinking is sent explicitly), `hermes_cli/model_normalize.py`
   (which typed ids are folded or passed through), `agent/reasoning_effort.py`
   (the per-family ladder and overrides), `agent/message_sanitization.py` /
   `chat_completion_helpers.py` (reasoning passback), `agent/model_metadata.py`
   and `agent/usage_pricing.py` (limits and the price snapshot Hermes bills
   with). This lane is the one that shows what the wire will carry: it is how
   the DeepSeek round learned that the first-party API rejects the versioned
   id and that Hermes escalates `xhigh` to `max`. It also tells you which
   Hermes build the chain alias needs (`omh update` does not upgrade Hermes;
   say "once the installed Hermes Agent moves to build X").
3. **Vendor harness (official)** — when the vendor publishes its own agent
   harness (`deepseek-ai/deepseek-harness`), read its presets, system prompt,
   editor contract, and the model adapter/serializer. The adapter records API
   rejections the docs omit (DeepSeek: an assistant turn whose answer sits
   only in the reasoning channel is rejected), and the preset the vendor
   benchmarks with says how much scaffolding the model wants (DeepSeek:
   Minimal — one shell tool, a one-line persona — scored above Standard).
4. **Community harnesses** — OpenCode / models.dev, OpenRouter's endpoint
   listing, oh-my-openagent, oh-my-pi, Aider, and the issue trackers. Use
   them for divergence (which ids 400, which harnesses drop the passback,
   who records off-peak as list price), never for the contract.

Each dossier ends with candidate trait → counter sentences tied to a quoted
source line, and none of them may push the model to keep working.

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
- Stay under `UNIT_PROMPT_MAX_BYTES`; the worst-case prompt test in
  `tests/test_unit_prompt_assembly.py` assembles every calibration key,
  family blocks and exact-model overrides alike.

## 4. Place routing

Rules that have held across every onboarding so far:

- The new generation takes every slot the family already held, and the
  superseded generation leaves the shipped chains (owner decision,
  2026-09-11, applied in one pass to Fable 5 behind 5.1, GLM 5.2 and its
  Ultrafast tier behind the 5.3 generation, DeepSeek V3.2 behind V4.1 Flash,
  and GPT-5.6 Sol behind GPT-6 Astra on the two frontier slots; applied again
  on 2026-09-23 to Claude Opus 5 behind Opus 5.5 and GPT-5.6 Luna behind
  GPT-6 Luna, and the same day to GPT-5.6 Sol and GPT-5.6 Terra behind GPT-6
  Sol; applied again on 2026-10-01 to GPT-6 Sol behind GPT-6.1 Sol and Grok
  Code Fast behind Grok Build 0.1; and on 2026-10-13 to Claude Haiku 4.5
  behind Haiku 5.5 and to the 2025 Qwen3-Coder, the first retiree with no
  same-line successor: its row is written out with an empty `successor` and
  a reason naming the model that now holds its only slot; and on 2026-10-24
  to Kimi K3 behind Kimi K3.1 Pro).
  Record each retirement as a `RETIREMENT_DECISIONS` row with its
  own `decision_date`. The table is keyed by model id, so a second
  retirement of the same id rewrites its row rather than adding one: GPT-5.6
  Sol's 2026-09-11 row (scope `frontier_slots`, successor `gpt-6-astra`) was
  widened on 2026-09-23 to `all_shipped_chains` with successor `gpt-6-sol`,
  and the earlier decision survives only in this paragraph. The public
  table names the current generation of each line; a machine whose provider
  still serves only the older id keeps it through `omh model-chains set`.
  The retired alias stays recognized, priced, and provider-mapped — list it
  in `_RECOGNITION_ONLY_ALIAS_FAMILIES` (`tests/test_provider_entitlements.py`)
  and keep its `APPROX_PRICE_PER_MTOK` row — so that operator override still
  resolves and still costs out. Before 2026-09-11 the rule was the opposite
  (old generation stays as fall-through); do not reintroduce it by copying an
  older comment.
- A successor can come from the next tier up when the vendor names no
  same-tier successor. No GPT-6 Terra exists (the model page returns 404
  and no price table lists one), and the Codex client repository's model
  catalog names GPT-6 Sol as the upgrade for both GPT-5.6 tiers
  (official-client; the catalog the backend serves does not push that
  upgrade yet); the API docs call Terra the "mini" tier
  and 5.6 Sol the unsuffixed tier, so Terra → Sol is a tier change as well
  as a generation change. The owner took it on 2026-09-23, each slot at the
  effort it carried, because Sol's list price is at or below Terra's on
  every documented rate. Editorial and unmeasured; the `high` pair on
  `deep` confirms or reverses it.
- A chain names the id the vendor's own API serves, not the spelling a
  gateway or a model card uses. DeepSeek serves `deepseek-flash` and
  rejects `deepseek-v4.1-flash` with HTTP 400, so the chain names the
  pointer and the versioned contract sits behind it as a declared
  projection (`DECLARED_MODEL_CONTRACT_PROJECTIONS`) and is listed in
  `EXACT_CONTRACT_POINTER_ALIASES` (source and plugin mirror) so the plugin's
  `mixture_category_for` projects in both directions and a child observed
  under either spelling keeps its category label; a mode or tier variant is
  not a pointer and only projects forward. Read the Hermes provider
  profile for the family before choosing the alias — it is the one place
  that shows what the wire will carry.
- An access-restricted sibling (Mythos 5.1 = Fable 5.1 under Project
  Glasswing) stays out of every shipped chain: naming a model most accounts
  cannot reach reads as a second model in the public tables. Keep it
  recognized, priced, and routable for a user who asks for it by name.
- The Claude vendor order inside any chain is Opus 5.5 → Fable 5.1 (owner
  decision, 2026-10-13), which reverses the 2026-09-06 Fable → Opus order.
  The Hermes lane and the Maestro lane are different surfaces and both
  follow it. The Maestro lane's Claude Code frontier chain is
  `claude-opus-5-5` → `claude-fable-5-1` → `opus` (owner decision,
  2026-10-13): the pinned Opus 5.5 id heads it, Fable 5.1 is the
  fall-through, and the `opus` alias is the always-resolving tail. The setup
  interview seeds the Claude Code `--model` preference with that head.
- Know whether a slot names a pinned id or a vendor-tracking alias before
  deciding it needs an edit. The Hermes lane names pinned ids
  (`claude-opus-5-5`), so a generation bump is a repo change, and since
  2026-10-13 so do the first two entries of the Maestro lane's Claude Code
  frontier chain. That chain's tail names the `opus` alias, which moves
  without an OMH edit — but on the client's terms, not OMH's: Claude Code
  resolves `opus` to Opus 5.5 only from v2.1.280, and to Opus 4.6 on
  Microsoft Foundry
  (official, code.claude.com/docs/en/model-config). The `sonnet` rows
  (`unspecified-low`, `artistry`) work the same way: Claude Code resolves
  `sonnet` to Sonnet 5.5 on the Anthropic API from v2.1.284, to Sonnet 4.6 on
  Claude Platform on AWS, and to Sonnet 4.5 on Bedrock, Google Cloud, and
  Foundry (official, same page, read 2026-10-01). The `haiku` rows (`quick`,
  `writing`, `simple-work`) resolve to Haiku 5.5 on the Anthropic API from
  v2.1.293 and to Haiku 4.5 on Claude Platform on AWS, Bedrock, Google Cloud,
  and Foundry (official, same page, read 2026-10-13). An alias slot therefore
  needs a docs caveat rather than an id change, and the same entry can run
  different generations on different machines.
- Shipped defaults change only with explicit owner approval; the operator's
  own placement goes through `omh model-chains set` and
  `omh coding category-maestro set`, never by hand-editing the JSON.
- A routing signal that lifts a request class to a tier only helps if that
  tier's chain head passes the class's work on this machine. Measure the
  head on the class before shipping the signal: on 2026-09-05 the
  `exhaustive_search` signal lifted six search tasks to `unspecified-high`,
  whose shipped head (Kimi K3 ultrafast) scored 0 / 6 on them, GLM 2 / 6,
  Sol and Astra 6 / 6. The signal was right and the head was wrong; the
  2026-10-13 table moved GPT-6.1 Sol to the head of `unspecified-high` on
  that measurement (the measured GPT head was `gpt-5.6-sol`).

Files that move together (grep the old id to find every site):

| Surface | File |
| --- | --- |
| Hermes-lane editorial chains | `src/coding/model_recommendations.py` |
| Plugin mirror of those chains + approximate price table | `src/plugin_bundle/omh/hermes_delegation.py` (parity test in `tests/test_plugin_hermes_delegation.py`) |
| Maestro-lane built-in table + executor option rows | `src/coding/model_routing.py` (`BUILTIN_CATEGORY_MODELS`, `EXECUTOR_MODEL_OPTIONS`) |
| `model-setup` skill text naming the chains verbatim | `src/skills/catalog_definitions.py` → regenerate `skills/omh-model-setup/SKILL.md` and `docs/WORKFLOWS.md` |
| Skill body budget note | `src/maintenance/release.py`, only when `release drift` or the body-budget tests report one: `FULL_PROFILE_SKILL_BODY_CHAR_LIMIT` or `FULL_PROFILE_SKILL_BODY_REPEATED_CHAR_LIMIT` (ceilings with headroom; re-derive from the producer by the policy written there and add the `old -> new` line) |
| Hand-maintained public chain tables | `site/index.html`, `site/docs/model-routing/index.html` (`tests/test_model_recommendations.py` reads both and checks alias order inside each category row). The READMEs carry no chain table; they link to `docs/INSTALLATION.md#guided-model-setup` |
| Generated public chain table | `docs/INSTALLATION.md` is not hand-edited: its marked region renders from `SHIPPED_MODEL_RECOMMENDATIONS` through `src/catalogs/model_chain_table.py`. Run `uv run python -m omh.cli docs chain-table` and add the new alias to `MODEL_DISPLAY_LABELS` there — the renderer raises with the key to add when it is missing |
| Pinned-chain and fallback-count tests | `tests/test_model_recommendations.py`, `tests/test_model_recommendation_routing.py`, `tests/test_model_routing_journey.py`, `tests/test_delegate_route_tool.py`, `tests/test_model_routing.py`, `tests/test_category_maestro.py`, `tests/test_task_scale_routing.py`, `tests/test_model_chains_command.py`, `tests/test_provider_entitlements.py` (chain-shaping cases), `tests/test_plugin_hermes_delegation.py` (route-provenance and reader fixtures name a chain member) — pins live in fixtures as well as assertions, so grep `tests/` for the old id and start the full suite in the background before the first doc edit, not after |
| Retired-alias list (an alias that left every chain but stays routable) | `_RECOGNITION_ONLY_ALIAS_FAMILIES` in `tests/test_provider_entitlements.py` |
| Placement and retirement records | `RECOMMENDATION_DECISIONS` (move the slot tuples to the new id) and `RETIREMENT_DECISIONS` (one row per superseded id, with successor, scope, and `decision_date`) in `src/coding/model_portfolio_qualification.py`; `tests/test_model_portfolio_qualification.py` checks every full retiree is out of both lanes, recognition-only, and priced |
| Claude always-thinking guard | `_ALWAYS_THINKING_CLAUDE_PREFIXES` in `src/plugin_bundle/omh/tools/delegate_route_tool.py` — add the id when the vendor documents that thinking cannot be disabled, so `omh_delegate_route` refuses a no-thinking effort instead of sending a request the API rejects |
| Benchmark arms | `benchmarks/live-model-tools/v1/manifest.json` — the old generation's arm, where one exists, stays as the baseline of the §8 pair and the new id's arm lands with the measurement PR; a line with no arm (GPT-5.6 Luna) gets both arms in that PR |
| Last-resort prose | the shared-final-order sentences in `docs/INSTALLATION.md` and `docs/ARCHITECTURE.md` name the `last_resort.any` models by display label; `tests/test_model_recommendations.py` derives the expected order and fails when either sentence goes stale |
| Contract audit doc paths | `_MODEL_DOCS` in `src/coding/model_contract_coverage.py` |
| CLI help examples | `src/commands/coding.py` |

## 5. Price from documented list only

`APPROX_PRICE_PER_MTOK` takes the vendor's first-party list price with the
source and month in a comment. A model without a documented price gets no
entry; absence renders no estimate. A serving tier of a priced model whose
vendor publishes no separate tier rate may carry the base model's documented
list price, never an invented discount, with a comment naming the base source
and saying the tier rate is unpublished; `glm-5.3-ultrafast` and
`deepseek-v4.1-flash-ultrafast` take this shape, and `kimi-k3-ultrafast`
moved to it on 2026-10-01 along with the corrected K3 base rate. The older
halved `glm-5.2-ultrafast` row predates this rule. A new price
row also widens what `omh model-chains interview` offers, since it proposes a
member's `-ultrafast` variant only when that id is priced. For an explicitly declared alias,
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
omh model-chains set architect "claude-fable-5-1:xhigh, claude-fable-5:xhigh, ..."
```

`dispatch-models.json` (the Claude Code profile's `--model`) is gated on the
CLI's own account, not on any provider; the providers a machine holds —
linked to Hermes (a `hermes auth` login, a `providers:` entry, an API-key
name in `.env`) or recorded by the setup interview in `providers.json` —
reorder chains per machine, so a new id whose family no recorded or linked
provider serves lands behind the served entries automatically. Record which
lane got the new id.
An id the resolving provider does not serve is not an error to hide: the
provider's rejection comes back as a normal result and the chain falls
through to the next entry. The superseded generation is not that next entry
in the shipped chains (§4); a machine whose provider serves only the older
id keeps it with `omh model-chains set`.

## 7. Prove it

Start the full suite in the background as soon as the chain edit lands and
keep editing docs while it runs; a chain change reaches fixtures in files the
table above cannot enumerate completely, and the suite is the only grep that
finds them all. Then a separate review lane (a read-only reviewer on the
diff) before the commit: the DeepSeek round's reviewer caught a reverse
projection that would have let a `-pro` / `-fast` / `-flex` alias label its
base id.

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
uv run python -m omh.cli docs chain-table --check
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

### The measurement recipe (2026-09-05, GPT-6 Astra)

The run that first exercised the family arm is the template. Each step is
one command or one read; the whole set is about 25 minutes per 30-task arm.

1. **Targeted manifest.** Copy `manifest.json`, keep the offline `fake`
   entry, replace the live entries with the one model at the effort its
   chain placement uses (Astra: `xhigh`). `analyze.py --manifest` reads the
   same file, so a one-model run is analysed without touching the canonical
   matrix.
2. **Smoke both conditions first** (`bench.py smoke`, one paid call each).
   A harness fault costs one call here and thirty later.
3. **Arms, in a recorded order.** `baseline`, `family`, `optimized`, each a
   separate `bench.py run --harness hermes_current_session --split evaluation
   --condition <arm> --max-paid-calls 30`. The harness runs one condition per
   invocation, so arm order is not counterbalanced within an arm; write the
   order down and keep every arm on the same day.
4. **Read cost, not only pass.** `analyze.py` gives the paired pass delta
   and McNemar; expect `p = 1.0`. Then read the per-instance token delta with
   a bootstrap CI, and pull `tool_call_count` and `api_call_count` for each
   arm's sessions from the Hermes `sessions` table (session ids carry the
   wall-clock start, so a run's rows are a contiguous window). Label those
   two counts out-of-harness in the report; the usage file on this path does
   not carry them.
5. **Know what "worse" looks like.** Astra's first override cost 10% more
   tokens than the family block for the same 18 / 30, with the excess in the
   two templates it failed anyway: the model kept working on tasks it would
   not pass. The clause with that reading ("carry them to completion instead
   of pausing") was replaced and the block re-measured back to family-block
   cost. Same pass, more tokens on failing tasks is the signature of a
   sentence that pushes; cut it, re-run, report both numbers.
6. **Measure effort before claiming it.** Astra at `low` produced the same
   pass set, tokens, and wall clock as `xhigh` on this corpus. An effort-tier
   claim needs its own arm.
7. **Archive the records outside git.** `benchmarks/*/artifacts/` is
   ignored; copy the `.jsonl` records, manifests, and scripts to a dated
   directory outside the repo and name it in the report, so the numbers in
   `MODEL_OPTI.md` and the benchmark README stay reproducible after the
   scratch space is gone.

What the corpus cannot say: no model passes its read or lsp templates, so
18 / 30 is the ceiling for every arm and a pass-rate gain cannot come from
it. Routing and calibration claims are cost and wall-clock claims here;
pass-rate claims need a corpus with headroom (#1333).

## 9. Report

PR body per the repo template: capability, motivation, boundary-level
implementation, observed verification (the commands above and their
outcome), risks (unserved ids, access-gated siblings, unmeasured
calibration). Commit trailers per `AGENTS.md`.

# Model Optimization Guidance

What OMH does differently per model, how it actually works at runtime, and —
for every family-specific prompt guideline — exactly why it exists and where
it came from. This document is a reader's map; the source of truth is the code
it cites, and a drift test (`tests/test_unit_prompt_protocol.py`) fails when a
calibrated family disappears from this file.

Boundary first: OMH never calls a model. Every optimization below is prepared
text or prepared configuration — calibration blocks ride prepared unit
prompts, routing rides Hermes config keys, and execution evidence always comes
from the runtime that actually ran the model.

## How it works, end to end

1. **A lane gets a model.** The mixture chains (shipped defaults plus your
   `~/.omh/routing/model-chains.json` overrides) pick a model and reasoning
   effort per category; `omh_delegate_route` writes them as explicit Hermes
   delegation keys. Any token-shaped model id is accepted — if the provider
   cannot serve it, the error comes back as a normal result and the chain
   falls over to its next entry (Hermes itself has no provider-side fallback).
2. **The model id is classified into a family.** `model_family()` in
   `src/coding/model_routing.py` strips a provider prefix
   (`opencode/kimi-k3` → `kimi-k3`) and matches by prefix. Unknown ids get
   family `unknown` — never an error, just generic discipline.
3. **The prepared prompt is assembled.** One function,
   `assemble_unit_prompt()` in `src/coding/unit_prompt_assembly.py`, builds
   every unit prompt as named blocks in four zones: the byte-identical
   `shared_head` (goal echo-back, bounded verification, failure kinds,
   structured return, capped search), the `unit` section (numbered
   completion criteria, tool batching, role protocol, calibration, domain
   bundle, skills), the `tail` (sidecar contract), and the redispatch
   `append` (repair brief or parent decision). Live dispatch, Hermes
   recovery, and both benchmark lanes call it, so what a benchmark measures
   is the product's text in the product's order. If the routed effort is
   `high`/`xhigh`/`max`, one calibration block is added for the subagent
   (`unit.calibration[<key>]`, the key naming the exact-model override or the
   family that answered); the composer writing the split follows the
   calibration for its *own* model
   (`omh coding composition-guide --model <id>` prints it). Each dispatch row
   records the block names, size, and sha256 it sent (`unit_prompt`).
4. **The model runs it.** Tool calling, todo rendering, and parallel
   execution are Hermes runtime capabilities — OMH's ULW behaviors
   (`todo init`, phase checklists, parallel evals, interjection-resume) live
   in skill contracts and prepared handoffs, so they apply identically to
   every lane regardless of which model the chain routed there.

So "optimizing for a model" in OMH means exactly one thing: a short,
evidence-backed paragraph of counter-guidance appended to an otherwise
identical prompt. Nothing else about the pipeline changes per model.

## How a model is recognized

| Family | Matched by | Example ids |
| --- | --- | --- |
| `gpt` | `gpt-`; design-qualified alias `openai-gpt-` | `gpt-6-astra`, `gpt-6.1-terra`, `gpt-5.6-sol`, `digitalocean/openai-gpt-5.6-sol` |
| `claude` | `claude-`; design-qualified alias `anthropic-claude-`; bare tiers `opus`/`sonnet`/`haiku`/`fable`/`mythos` | `claude-fable-5-1`, `claude-mythos-5-1`, `digitalocean/anthropic-claude-opus-5` |
| `gemini` | `gemini-` | `gemini-4-argon`, `google/gemini-4-argon`, `gemini-3.1-pro` |
| `kimi` | `kimi-` | `kimi-k3`, `kimi-k3-ultrafast`, `kimi-k3.1-pro`, `kimi-k3.1-pro-highspeed`, `moonshotai/kimi-k3.1-pro` |
| `glm` | `glm-` | `glm-5.3`, `glm-5.3-flash`, `glm-5.2-ultrafast` |
| `grok` | `grok-` | `grok-build-0.1` |
| `qwen` | `qwen-`, aliases `qwen3-` and `qwen3.` | `qwen3-coder`, `qwen/qwen3.8-flash` |
| `deepseek` | `deepseek-` | `deepseek-v4.1-flash`, `deepseek-flash` (the first-party pointer), `deepseek/deepseek-v4.1-flash` |
| `mistral` | `mistral-` | Mistral Large / Medium ids |
| `llama` | `llama-` | open-weights Llama ids, any serving host |
| `codestral` | `codestral-` | Codestral coding ids |
| `solar` | `solar-` | Upstage Solar Pro ids |
| `minimax` | `minimax-` | `MiniMax-M3`, `MiniMax-M2.7` (recognized, uncalibrated — see the coverage matrix) |
| `jev` | `jev-`; bare `jev` | `jev-1.13.0`, `jev-latest`, `jev-preview`, `typesafe/jev` (non-generative — see below) |
| `unknown` | anything else | emerging families before a prefix lands |

The design-qualified aliases are concrete serving-catalog ids, not new model
families. Bare vendor prefixes remain unclassified because the same provider
catalog also includes other designs such as `openai-o3` and non-text models
such as `openai-gpt-image-2`; neither may inherit GPT text calibration. The
models.dev catalog used by OpenCode lists, for example,
`digitalocean/openai-gpt-5.6-sol` with base model `openai/gpt-5.6-sol` and
`digitalocean/anthropic-claude-opus-5` with base model
`anthropic/claude-opus-5`. After the serving provider segment is stripped,
those aliases therefore select the existing `gpt` and `claude` calibrations;
they do not create vendor-wide calibration families.

`jev` is the exception to the bare-name rule above, and it is a deliberate
one: `deepseek` and `minimax` are vendor words naming a catalog, while `jev`
is an id TypeSafe's own documentation sends in the `model` field and a gateway
spells `typesafe/jev`. It is carried in `_BARE_MODEL_ALIASES` rather than by
widening the Claude tier set. The near misses stay `unknown`, including
`jev_evaluate`, which is a Hermes plugin TOOL name and not a model at all.

### Non-generative models

`model_class()` in `src/coding/model_routing.py` answers `generative` or
`non_generative` for one id, family-level, with `generative` as the default so
every model the catalog has never met routes exactly as it does today. A
`non_generative` model's documented output is a typed answer over options the
caller supplies, not text: Jev returns a Choice, a Score, or a Noul, and the
vendor's own jaggedness page states it "is not trained to generate text".

Nothing about that makes it a lesser model — it makes it a model that cannot
be handed a coding unit. So OMH recognizes it, contracts it, and prices it
like any other, and refuses it at every surface that would prepare it to
write code:

- `omh coding model-route --model jev…` answers `status: model_refused` with a
  `refusal` record naming the id and the class. No model, no effort, no chain
  is prepared. This is the one narrowing of "an explicitly requested model
  always wins": the request is still never adjudicated on quality, only on
  whether the class can do the work at all.
- `omh model-chains set <category> "jev:low"` exits 2 and writes nothing, and
  the operator category-maestro config rejects such an entry by name on
  read and on write.
- A chain entry that reaches the resolver anyway (a hand-edited chain
  document, or an operator recommendation document read with
  `omh coding model-route --recommendations`) is skipped with a `chain_entry`
  record naming the class, and the next generative entry takes the head. Both
  lanes filter, so neither the catalog chain nor the Hermes editorial chain
  can carry one to the head.

Calibration does not apply: there is no prompt to counter-guide and no effort
ladder to place a floor on, so `HIGH_EFFORT_CALIBRATIONS` gains no entry and
this family gets no per-family section. The measurement that would normally
close an onboarding does not apply either, because a family-vs-model prompt
pair needs two generated answers to compare; what replaces it is described in
`docs/MODEL-ONBOARDING.md` and is a named follow-up, not part of the
recognition work.

### Exact-model contracts and overrides

Family is the default grain, and two exact-model surfaces sit in front of
it for a generation whose documented interface or traits differ from its
family's:

- **`MODEL_CONTRACTS`** in `src/coding/model_contracts.py` records what the
  vendor documents about one exact id — effort ladder and floor, limits,
  tool-calling API, unsupported parameters, dynamic-effort mechanism, list
  price, sources and the date they were read. A bounded
  `DECLARED_MODEL_CONTRACT_PROJECTIONS` table may map a provider catalog's
  explicitly named mode/service-tier alias onto that contract; it never strips
  an arbitrary suffix. `omh coding model-contract --model <id>` prints the
  resolved record. The route resolver consults it before the catalog: a
  requested effort the contract documents as unsupported is raised to the
  documented floor or, when that floor is the no-reasoning rung `none`
  (GPT-6 Luna), to the lowest documented rung above the request, and the
  route says so (`effort_change.kind = floor_raised`), on every executor
  profile, so an unsupported rung never
  reaches a provider silently. Route receipts retain the requested id plus the
  canonical contract id, reasoning mode, service tier, and exact-versus-
  declared provenance. None of that claims catalog availability, entitlement,
  wire translation, or execution. A model without an exact or declared
  contract is treated exactly as before — by family and catalog alone.
- **`MODEL_HIGH_EFFORT_CALIBRATIONS` / `MODEL_COMPOSITION_CALIBRATIONS`**
  in `src/coding/unit_prompt_protocol.py` are calibration overrides keyed by
  exact id. `calibration_for_route()` resolves the recorded `selected_model`
  against them before falling back to `model_family`, and
  `composition_calibration_for_model()` does the same for the composer, so
  the family block — and every older generation's prompt — stays
  byte-stable when a new generation gets its own counter. The two tables
  share one key set (parity-tested) and every key has a contract.

The exact contract key is the served id after the provider prefix is stripped,
so `openai/gpt-6-astra` and `gpt-6-astra` resolve alike. An explicitly declared
catalog variant keeps its full requested/provider-qualified identity while it
inherits the canonical contract. Bare chat names are not aliased for GPT
generations (`astra`, like `sol`, classifies `unknown`); users name the served
id.

`omh coding model-contract-audit --inventory <path|-> --json` compares a
bounded local JSON inventory with those contracts without network access or
configuration writes. Each stable `model_contract_coverage/v1` row reports
family recognition, contract and effort coverage, model-specific calibration,
provider-family and category projection, price source or absence, and docs
coverage. Pass `--required-model` or `--recommended-model` repeatedly to make
missing required, recommended, and optional-discovery rows operationally
distinct; `--intentional-exclusion` records a deliberate non-contract row.
The comparison body has no timestamp and carries both the supplied inventory
source/digest and its own canonical digest, so onboarding, doctor, or release
workflows can hash-compare reports. A cold or unavailable inventory remains
explicitly different from an observed empty inventory. The audit is advisory:
it does not discover models, prove provider availability, change a route, or
create an issue.

## Universal protocols (every model, every family)

**Measured (2026-10-04, prompt audit):** until this run the benchmark sent
only the calibration paragraph, so the shared head below had never been
measured. The `unit` condition (`benchmarks/live-model-tools/v1`, added in
the same audit) sends the real head. On `claude-fable-5-1` at `xhigh`, 30
instances per arm, Claude Code subscription:
- **Head vs no head:** `unit` used −1.9% tokens against `optimized`, which
  carries the calibration but no head (CI spans zero). Its tool calls fell
  from 313 to 219 / 236, about 25–30% fewer.
- **Clarification block:** `unit_lean` drops the parent-clarification
  block (1,163 B). It measured +4.8% / −3.1% against the two `unit` arms,
  inside the +8.1% same-text drift.

The head stays. The clarification block also stays: this corpus never
exercises `input_required`, but real fanout units do. Archive:
`~/Desktop/khope/bench-archive/prompt-audit-2026-10-04/runs` (outside git).

`src/coding/unit_prompt_protocol.py` attaches four deterministic blocks to
every dispatched unit prompt, regardless of model, and adds one composer-side
discipline for how those prompts are assembled:

- **Goal echo-back** — before the first tool use, the subagent restates the
  goal, its deliverable, and the numbered criteria, and reports (never
  guesses) if its reading conflicts with the declared boundary. *Why:* a
  misread boundary is cheapest to catch before any edit exists.
- **Pre-declared completion criteria** — "done" is a numbered list derived
  from the frozen unit contract before work starts. *Why:* completion must be
  a check against stated criteria, not a feeling.
- **Bounded verification** — exactly one full verification pass is both the
  floor (never skipped) and the ceiling (once criteria pass, re-verifying is
  forbidden; at most two fix-and-verify cycles before reporting the failing
  criterion). *Why:* the two dominant agent failure modes are opposites —
  skipping verification, and looping on it — and one bounded rule counters
  both. Review-role units add criterion-bound blocking with a two-round cap.
- **Failure-kind discipline** — a permission, sandbox, or policy denial is a
  boundary, not a bug: the unit must not retry it through another tool or
  route, and may report `blocked` only for a named concrete condition that
  survives the bounded fix cycles — difficulty, uncertainty, or useful
  remaining work is not blocked. *Why:* models over-generalize "failure →
  try another way", which turns policy refusals into route-around attempts,
  and under-specify "blocked", which turns difficulty into a stop. Adapted
  from the DeepSeek Harness sandbox-denial no-retry marker and its
  goal-policy blocked threshold ("difficulty, uncertainty, or useful
  remaining work is not blocked"), generalized to every family because both
  failure modes are cross-family (deepseek-ai/deepseek-harness, master
  2026-08-13; adopted in #1071).
- **Prompt-cache discipline (composer)** — the shared preamble of a fan-out
  stays byte-identical across sibling unit prompts: stable ordering, no
  timestamps or volatile status, unit-specific content appended after it,
  and staggered dispatch so the first request writes the provider cache the
  siblings read. *Why:* Anthropic, OpenAI, Gemini, and DeepSeek all cache
  prompt prefixes by exact bytes; DeepSeek additionally prices cached
  prefixes, which is where OMH first learned the rule
  (`PROMPT_CACHE_COMPOSITION_PROTOCOL`).
- **Tool batching** — independent reads and searches go out together in one
  turn and every result is inspected; dependent steps, edits, approvals,
  waits, and follow-ups that adapt to a result stay sequential; shell output
  is never decorated with separator commands (`TOOL_BATCHING_PROTOCOL`).
  *Why:* a fan-out unit that serializes independent reads pays a round trip
  per read, and a unit that parallelizes an edit with the read it depends on
  edits stale bytes; separators are noise inside a bounded output capture.
  It reaches every unit through the unit section, not the shared head: the
  head is frozen at its measured small-model budget (the section below), and
  a batching rule is the first thing a weak lane may drop, so it must never
  displace a stop rule there. The `claude` family block used to carry the
  batching half itself; that sentence moved here.

The first three originate from the stop-condition techniques the
upstream agent-harness research surfaced for high-effort models (terminal-condition
rules, criterion-bound blocking, capped re-review), generalized to every
family. The fourth comes from the DeepSeek Harness review named above. The
fifth generalizes that harness's priced-prefix composition constraint to
every family, because every major serving stack is a byte-exact prefix
cacher. The sixth comes from the Codex Desktop prompt review below; the
`claude` family block already told its units to request every independent
item in one response, and the universal rule is that sentence promoted to
every family with the sequential set and the separator rule added.

### Writing for the smallest model in the fleet

The per-family blocks below vary by family. The shared preamble does not: it
is byte-identical across sibling prompts on purpose, so providers can cache
the prefix. That makes it the one block that has to be written for the
*smallest* model that will read it, not the largest. A frontier model
tolerates a dense head; a weaker local CLI starts dropping rules once a
prompt carries more than it can hold, and the rule it drops is not the one
you would have picked. So every rule added to the shared head is paid for by
displacing a rule already there — on exactly the lanes least able to afford
it.

`src/quality/small_model_prompt_budget.py` measures the two halves of that
which a gate can actually check, and
`tests/test_small_model_prompt_budget.py` enforces them:

| Ceiling | Value | What it bounds |
| --- | --- | --- |
| `SHARED_PREAMBLE_MAX_BYTES` | 2770 | OMH-authored bytes of the executor-invariant head. `UNIT_PROMPT_MAX_BYTES` bounds the whole dispatch prompt, which would let the shared head triple without tripping; the caller's goal line is excluded because its length is the operator's business. |
| `SHARED_PREAMBLE_MAX_CONSTRAINTS` | 10 | Directive sentences in that head. |
| `BLOCK_MAX_CONSTRAINTS` | 3 | Directive sentences in any single dispatched block, family calibrations included. |

All three are the **measured current values**, not aspirations. The upstream
doctrine puts a tiny pattern-completer's limit at roughly 3-5 constraints
before rules start displacing each other; OMH's consumers are coding-agent
CLIs rather than tiny models, so 5 is recorded as the target while the
ceilings freeze the head where it is. Raising one is allowed and is a
decision: say which existing rule the new one displaces, or move the rule
into a unit-varying block where only the units that need it pay. The
constraint count is a sentence-level proxy and is named as one — it counts
the sentences a reader must hold as a rule, not the rules themselves.

One further rule is mechanized: **no labelled contrast examples**. A block
containing `Bad:` or `Wrong:` followed by a sample gets the sample copied
rather than avoided by a weaker model, which is the opposite of the intent.
State the wanted shape instead.

Two rules are deliberately left to the author, because no regex can apply
them:

- **Positive framing, except where the negation is the payload.** Small
  models drop the "not" and do the thing anyway, so prefer stating the
  wanted behavior. But "do not re-verify once every criterion has passed" is
  the entire anti-inertia rule; rewriting it positively would lose it. Judge
  per rule, and keep the negation only when it *is* the rule.
- **Delete rules the code already enforces deterministically.** OMH enforces
  a great deal at freeze time — boundary overlap, dependency cycles, unit
  schema, owner and model resolution — and a prompt rule restating one of
  those spends headroom that a rule the code cannot enforce needs. Before
  adding a rule, check whether a gate already makes it true.

### Techniques compared and already structural (DeepSeek Harness review)

The same harness review surfaced techniques OMH already carries structurally,
recorded here so the comparison stays auditable instead of being relitigated:
single-owner-of-facts (the skill catalog and its byte-gated generated
projections), negative instructions phrased as the concrete behavior they
forbid (the house calibration style throughout this file), and numeric stop
bounds for ambiguous judgments (one-pass verification, two fix-and-verify
cycles, two review rounds). Machine-readable result markers and
KV-cache-aware request assembly belong to the executor/runtime that actually
calls a model — outside the universal prompt-cache composition discipline
above, they are out of OMH's boundary by design.

### Techniques compared (Codex Desktop prompt review, community source)

A circulating dump of the Codex Desktop system prompts for GPT-6 Astra
(elder-plinius/CL4R1T4S, `OPENAI/Codex_Desktop/GPT-6_Astra_Prompts.md`, read
2026-09-11 — 5,051 lines with no date, version, or extraction method, so
**community / unverified**; nothing in it overrides the official contract in
`src/coding/model_contracts.py`) was compared against OMH the same way the
DeepSeek Harness was. What it corroborates is already here: instruction
precedence ("the user's instruction … must take precedence over any
guidelines provided in skills"), assumptions over questions ("strongly
prefer making reasonable assumptions … rather than stopping to ask"), and
test sizing ("do not write tests for reversible, low-impact changes or that
mirror the implementation … broaden or repeat testing only when new changes,
failures, or unresolved concerns justify it") are the three sentences of the
`gpt-6-astra` override, and the guardian-rejection rule ("continue with a
safer alternative, or carry out checks to prove that the action is
authorized … do not bypass this rejection through a workaround") is the
failure-kind discipline (its "safer alternative or shown authorization"
wording is the same rule as "continue with what the boundary allows, or
report it" and was not added twice; likewise a checkpoint's contents are
already the `goal_ledger/v1` structure, so no sentence restates them).
Adopted as harness discipline on OMH's own surfaces (executor-neutral,
measured by observed engine behaviour rather than a token benchmark): the
latest mid-run message is steering for the active task, not a replacement
objective — a sharpening of the interjection rule's existing "when the
interjection changes scope, say so" clause; a follow-up that needs new
authority, expands scope materially, or changes external state not already
authorized is described and approved first, and persistence never broadens
scope (`ENGINE_FOLLOW_UP_AUTHORITY_RULE` — the engine-entry, external
executor, and delegation-enable gates already asked before their own
steps, but nothing covered an external state change such as a merge or a
send); independent reads batch, dependent steps serialize, no decorative
shell separators (`TOOL_BATCHING_PROTOCOL`, every unit's section, outside
the frozen shared head); the closing brief scales to the change, leads with
the result, and omits abandoned approaches unless they explain a tradeoff,
while the observed run summary and any prepared-not-observed or unmerged
work are stated whatever the length (`ENGINE_CLOSING_BRIEF_RULE`, new).
Deliberately not adopted: the persistence
push ("do not settle for a partial or 'helpful enough' solution … persist
until the user's intended goal is complete", "only send a final message
after concluding that no follow-up … could be useful"). It is written for an
interactive desktop session with the user present; OMH units are bounded by
numbered criteria, and the 2026-09-05 Astra measurement above showed that a
completion-push sentence costs +5,419 tokens per instance at an unchanged
pass rate, spent on the tasks the model fails. Host channels (commentary
versus final, heartbeats, async user messages, `notes`/`history` tools,
`fork_turns`) are Hermes' surfaces, not OMH's; the confirmation-policy tiers
for computer use are a candidate for the browser skills' boundaries, not
this round.

## Per-family calibrations: what, why, and where each came from

Two tables in `src/coding/unit_prompt_protocol.py` carry the family-specific
guidance: `HIGH_EFFORT_CALIBRATIONS` for the **subagent executing a unit**,
and `MAIN_AGENT_COMPOSITION_CALIBRATIONS` for the **composer** splitting work
and writing unit prompts. A parity test forces the two tables to share one key
set — no family gets subagent discipline without composer discipline.

The governing rule, stated in the module docstring: a calibration counters a
family's *known* failure mode. No family carries richer guidance than another
without a stated reason, and no vendor is privileged. Provenance falls into
three buckets, each named per family below:

- **Adapted research** — stop-condition work from an upstream agent-harness
  project on how high-effort reasoning models over-verify.
- **Observed failure modes** — behavior seen in live OMH/Hermes usage of that
  family (recorded in the commits that introduced each block).
- **Provider-published model characteristics** — facts the vendor states
  about the model's design (e.g. a non-thinking architecture), which make
  certain prompt shapes actively harmful.

Validation is common to all: `benchmarks/live-model-tools/v1` runs
baseline-vs-calibrated prompt pairs where the *only* difference is the
calibration block, and `tests/test_omh_live_model_benchmark.py` pins that
pairing so a benchmark claim can never mix in other prompt changes.

### `gpt` (GPT-5.6 Sol / Terra / Luna, GPT-6 Sol, GPT-6 Luna, GPT-6.1 Terra, GPT-5.6 Cyber, GPT-6 Rosalind)

- **Model trait:** a strong long-horizon reasoner. Its characteristic waste
  is spending depth on things that are already decided: re-deriving facts it
  established earlier, and re-running verification "for reassurance".
- **What OMH injects (subagent):** reasoning depth belongs to the hard parts
  of *this* unit; once the decisive fact is in view, act on it; a passed
  criterion is settled evidence, reopened only by contradicting output.
- **What OMH injects (composer):** compose outcome-first, but never compress
  the contract away — GPT's tight compositional style tends to drop stated
  boundaries and criteria while shortening a prompt, and a tighter prompt
  that loses an invariant is a worse prompt.
- **Source:** adapted research (upstream agent-harness stop-condition findings on
  high-effort models), one of the two original calibration entries.
- **Version rule:** the block above is written for the 5.6 generation and
  is what every `gpt-` id receives unless an exact-model override exists.
  GPT-6 Astra has one, below; the 5.6 prompts are byte-stable across it.
- **GPT-6 Luna: documented traits, no counter shipped.** `gpt-6-luna` has
  an exact contract (`src/coding/model_contracts.py`) but no exact
  calibration, so it receives this family block. The reason is placement,
  not an absence of traits: the shipped chains run Luna at `low` in `quick`
  and `simple-work`, and the subagent calibration fires only at `high`,
  `xhigh`, or `max` (`HIGH_EFFORT_TIER` in
  `src/coding/unit_prompt_protocol.py`), so a shipped Luna unit never
  receives a block. Luna is not a composer candidate either; the vendor
  positions it for "focused, high-volume tasks". The evidence, kept ready
  for an operator who runs it at `high` or above:
  - official (the latest-model guide, read 2026-09-23), stated for the
    GPT-6 family rather than for Luna: more likely to ask the user a
    question; more sensitive to instructions contained in skills; tends
    toward detailed, formatted responses; may delegate less often than
    desired; thorough in testing before considering a task complete.
  - official-client (the Codex model catalog's Luna prompt, compared with
    Sol's): Codex drops the "continue work without ending the turn"
    sentence for Luna and replaces Sol's testing bullets with "Do not add or
    run tests unless the user asks you to test or verify implementation."
    The vendor's own client restrains Luna rather than pushing it.

  A future counter would narrow scope, never push the model to keep
  working; test restraint is the strongest candidate.
  - **Measured (2026-09-24, OMH `low` vs vendor-default `medium`, plus the
    generation-swap follow-up):** four arms on
    `benchmarks/live-model-tools/v1`, evaluation split (30 instances),
    `hermes_current_session` path, `openai-codex`, `optimized` condition, one
    arm at a time, same UTC day. L1 (`gpt-6-luna` at `low`, the OMH-shipped
    rung) and L2 (`gpt-6-luna` at `medium`, the vendor default) both passed
    15 / 30 (McNemar p = 1.0); `low` used +9,904 tokens per task more than
    `medium`, bootstrap CI95 [+846, +19,880] (+13.9% in total, sign-test
    p = 0.043) — the CI excludes 0, but the list price came out equal
    ($0.0766 against $0.0773, a gap smaller than the $0.0008 measured by
    repeating the `low` condition on a separate arm). So on this corpus
    `low` saves neither tokens nor money over `medium`; kept anyway, per the
    owner decision below. A third arm (L3, the predecessor `gpt-5.6-luna` at
    `low`) answers the named follow-up: pass went from 18 (`gpt-5.6-luna`)
    to 15 (`gpt-6-luna`), McNemar p = 0.25 (not significant), with all three
    lost tasks in `PREDICATE` — every `gpt-6-luna` run in this bench scored
    0 / 3 there while `gpt-5.6-luna` scored 3 / 3. List cost dropped from
    $0.2324 to $0.0766 (−67%), driven by `gpt-6-luna`'s lower list rates and
    higher cache share rather than by a token-count drop. Owner decision
    (2026-09-24): keep `gpt-6-luna` in the `quick` and `simple-work` chain
    slots — the cost win is real on short-task slots (about a third of the
    predecessor's list price) and the 3-task `PREDICATE` gap is not
    statistically significant on this corpus; flagged here as a known
    weakness to re-check with a larger corpus. Correction (2026-09-24,
    observed from the run transcripts): the `PREDICATE` loss is a field
    vocabulary mismatch, not a search miss. The grader compares
    `(path, line, kind)` exactly
    (`benchmarks/live-model-tools/v1/lib/validation.py:39-46,118-123`) and
    the task text never lists the allowed `kind` values; `gpt-6-luna` found
    the functions and filled `kind` with a task-derived label (Hermes
    `state.db` sessions `20260924_130123_bf450a` and
    `20260924_130154_64bfa0`: `"kind":"provider_failure_to_fallback"`;
    `20260924_130221_ac6657`: `"kind":"provider_failure_to_fallback_result"`)
    where `gpt-5.6-luna` wrote
    `"kind":"function"` (session `20260924_135649_e47bf4`), so the run is
    scored `search_false_negative`. Named follow-up: bench arm L6
    (`gpt-6-luna` at `low`, the three `PREDICATE` tasks with the `kind`
    vocabulary stated) to test whether the gap is vocabulary only; the
    pinned corpus and scorer stay unchanged here. Corpus ceiling on this bench
    is 18 / 30 (no arm passes the read or lsp templates); wall clock was
    contended in every arm and is not compared. Not measured: any claim
    beyond this corpus, and `low` vs `medium` at any placement other than
    `quick` / `simple-work`. Archive (outside git, owner checkout):
    `.omc/research/opus55-luna-bench-2026-09-24/`.
- **GPT-6 Sol: documented traits, no counter shipped.** Since 2026-10-01
  GPT-6 Sol holds no shipped slot (GPT-6.1 Sol took all of them, see
  `gpt-6.1-sol` below); it stays recognized, priced, and on this family
  block, byte-stable, for a machine-level override. What follows records
  the 2026-09-23 placement. `gpt-6-sol` has an
  exact contract but no exact calibration, the Luna precedent. Unlike Luna,
  its placement reaches the calibrated tiers: it heads `deep` at `high`,
  where the subagent block fires, and it is a `main` role suggestion, so it
  is a composer candidate. Both receive this family block, written for the
  5.6 generation. An exact block waits on a `family` vs `optimized`
  benchmark pair; until then the evidence is kept here:
  - official (the latest-model guide, read 2026-09-23): the guide's GPT-6
    prompting section addresses "behavior observed with GPT-6 Astra" and
    gives no Sol-specific guidance, so these are family statements, not
    Sol measurements: more likely to ask the user a question; more
    sensitive to instructions contained in skills; tends toward detailed,
    formatted responses; may delegate less often than desired; thorough in
    testing before considering a task complete.
  - official-client (the Codex model catalog's Sol prompt): it keeps
    "continue work without ending the turn to clarify with the user", which
    Luna's drops and Astra's keeps. That sentence pushes the model to keep
    working and is not imported into any OMH block. The same prompt carries
    a restraint a later exact block could adopt without its tail: "Broaden
    or repeat testing only to resolve a concrete remaining risk or satisfy
    a required gate." (the vendor's "continue toward the user's goal" is
    dropped).
  - The `gpt_sol_codex_handoff` throughput overlay matches any `*-sol` id,
    so GPT-6 Sol as a Codex main agent receives it. That is kept on purpose
    (owner decision, 2026-09-23): its rules are restraint-shaped (a declared
    stop condition, stop on decisive evidence), and
    `tests/test_executor_prompting.py` names `gpt-6-sol` so the inheritance
    is a reviewed decision rather than a suffix accident. The suffix is read
    off the contract model id, so a dated `gpt-6-sol-YYYY-MM-DD` id, which
    resolves to `gpt-6-sol`, receives it too; no dated Sol snapshot is
    published.

  Editorial, unmeasured. The named follow-up pairs: `gpt-5.6-sol` vs
  `gpt-6-sol` at `medium` (the last-resort rung), `gpt-5.6-terra` `high` vs
  `gpt-6-sol` `high` (the `deep` rung), and `main` at its effort.

### `gpt-6-astra` (GPT-6 Astra, exact-model override on the `gpt` family)

- **Documented contract:** `gpt-6-astra` (released 2026-09-03, staged
  rollout) is the exact contract. The active host catalog's declared aliases
  are `gpt-6-astra-fast`, `gpt-6-astra-flex`, `gpt-6-astra-pro`,
  `gpt-6-astra-pro-fast`, and `gpt-6-astra-pro-flex`: `pro` selects the
  reasoning mode, while `fast` and `flex` select the service tier. They inherit
  only through explicit rows, keep the requested provider-qualified id in
  receipts, and resolve to canonical contract `gpt-6-astra`; an unknown or
  malformed suffix does not inherit. The shared contract records a
  1,050,000-token context, 922,000 max input, 128,000 max output, knowledge
  cutoff 2026-04-30; reasoning effort `low`, `medium`, `high`, `xhigh`, `max`
  — `none` returns HTTP 400 and the migration guide sends `none`/`minimal`
  callers to `low`, so `low` is the floor OMH raises `off`/`minimal` requests
  to (recorded as `floor_raised`); no default effort, so a route names one;
  tool calling on the Responses API only; `temperature`, `top_p`,
  `top_logprobs` unsupported; `configuration_update` can change effort between
  responses in standard single-agent mode only, not alongside automatic
  compaction or truncation. Full record and sources in
  `src/coding/model_contracts.py`; `omh coding model-contract --model <id>`
  prints the exact or declared projection.
- **Model trait (official, latest-model guide):** asks a clarifying question
  more readily when more input could materially change the result; follows
  instructions more strictly and may pause on unclear or conflicting
  skill-file guidance; may delegate less often than a harness expects; may
  write broader tests than the change requires. The GPT-5.6 counter
  (re-deriving settled facts, re-verifying for reassurance) is not what the
  guide describes for Astra, which is why the override exists.
- **What OMH injects (subagent):** the user's instructions outrank skill or
  guideline text and the numbered criteria are the complete task — nothing
  outside them is owed; ask one focused question only when a missing input
  would materially change the result, otherwise state the assumption and
  proceed; size tests to the change — a reversible, low-impact edit that
  mirrors its implementation needs no new test, and a green check is re-run
  only when its inputs changed. Two constraint sentences; under the
  per-block ceiling. The first sentence originally read "carry them to
  completion instead of pausing for sign-off on work the boundary already
  authorizes"; the 2026-09-05 measurement below is why it no longer does.
- **What OMH injects (composer):** write the user's intent into each unit
  prompt above any skill text; delegate every unit that is independent of
  the work you keep (an undelegated independent unit is chosen latency);
  set each unit's effort from its task state — the documented floor for
  routine follow-ups, deeper only while a criterion holds unresolved hard
  reasoning or contradictory evidence — and land an effort change on the
  next prepared unit rather than on a claimed mid-conversation switch.
- **Effort policy:** `dynamic_effort_guidance()` emits the
  `configuration_update` (mid-conversation) policy only for an executor
  profile the contract names as compatible; no prepared profile is, so
  every profile today gets the per-turn policy and no prepared text claims
  a mid-conversation change happened. `omh coding composition-guide --model
  gpt-6-astra --executor <profile>` shows which one applies. The universal
  echo-back, criteria, TODO reconciliation, one-pass verification, and
  bounded repair cycles are unchanged and not restated in the override.
- **What is deliberately absent:** no "you are being monitored" language,
  no request for or storage of raw chain of thought. OpenAI's monitorability
  evaluation observed fewer textual CoT tokens under monitoring awareness in
  an adversarial honeypot setting, where some attacks moved into tool calls
  with no textual CoT; that is not evidence of less overthinking, lower
  latency, or better task results, and a test pins the override free of it.
- **Throughput overlay:** unchanged. The `gpt_sol_codex_handoff` overlay stays
  gated to `*-sol` (GPT-6 Sol and GPT-6.1 Sol included, by decision) and the Hermes
  `ultrawork` overlay stays family-wide;
  neither has an Astra measurement, so Astra on codex gets the base rules.
- **Routing:** heads `ultrabrain` and the GPT slot of `architect` in both
  lanes. GPT-5.6 Sol trailed it as fall-through until 2026-09-11, when the
  superseded generations left every shipped chain (owner decision). Since
  2026-09-23 GPT-6 Sol holds every slot GPT-5.6 Sol and GPT-5.6 Terra held
  (the shared last resort, the head of `deep`, the `main` suggestion, and
  the codex lighter categories), each at its previous effort, and since
  2026-10-01 GPT-6.1 Sol holds every one of them; Astra lists at 5x Sol, so
  it heads no cost-tier slot. The 2026-10-13 table (owner decision) moved
  the Hermes lane: Opus 5.5 heads `deep` with GPT-6.1 Sol second, GPT-6.1
  Sol heads `unspecified-high` and the `main` suggestion, and `deep-work`
  moved from Astra at `high` to Opus 5.5 then GPT-6.1 Sol at `max`, so Astra
  now sits only in `ultrabrain`, `architect`, and `main` there; the Maestro
  `codex` rows are unchanged. The Luna lane is a cost-tier
  pick and stays as it was. An
  account the staged rollout has not reached gets a provider rejection and
  the chain falls through to the next ecosystem.
- **Pricing:** exact operator `model-prices.json` rows win first. A declared
  alias without an exact row inherits the base Astra 10/50 list rates; `fast`
  applies the documented 2x service-tier multiplier and `flex` 0.5x. `pro` is
  a reasoning mode and has no fabricated multiplier. Cached input stays at
  the documented default tenth. The $12.5/M cache-write rate and the 2x input
  / 1.5x output multiplier above 272K input tokens have no column in
  `APPROX_PRICE_PER_MTOK` and remain visible in the inherited contract rather
  than being flattened.
- **Measured (2026-09-05, subagent block):** four arms on
  `benchmarks/live-model-tools/v1`, evaluation split (30 instances, corpus
  digest `c4ea899a…`), `hermes_current_session` path, `openai-codex` /
  `gpt-6-astra` at `xhigh`, omh 2.0.0, Hermes 0.21.0, arm order
  optimized → family → baseline → revised. Every arm passed 18 / 30 with
  identical per-template results, so pass rate decided nothing. Tokens did:
  the original override cost 1,675,942 against the inherited `gpt` block's
  1,513,367 (+5,419 per instance, bootstrap CI95 [+1,444, +10,150], more in
  26 / 30) and against no calibration at all (1,550,904). Hermes' own
  session rows put it at 310 tool calls / 206 API turns versus 286 / 194 for
  the family block, with the excess concentrated in `BUGFIX` and
  `DIAGNOSTICS` — the model kept working on tasks it was not going to pass.
  The "carry them to completion instead of pausing" clause was the one
  sentence with that reading, and the block above is the revision that
  replaces it: 1,532,241 tokens (−4,790 per instance against the original,
  CI95 [−9,336, −1,075]; +629 against the family block, CI95 [−1,109,
  +2,445], indistinguishable), 294 tool calls, 192 API turns, still 18 / 30.
  Per §8 that is the "revise" outcome: the Astra-specific counters
  (assumption over question, test sizing) stay, the clause that made the
  model over-work is gone, and the override now costs what the block it
  replaced costs. Full tables in the benchmark README. Not measured: the
  composer block (no fanout in this harness), clarification and delegation
  counts (the corpus never provokes them; #1327 is the follow-up), and any
  claim beyond this corpus.
- **Source:** official (the OpenAI model reference, latest-model guide,
  reasoning guide, async tool calling and steering guides, monitorability
  evaluation, and system card, read 2026-09-04), plus the 2026-09-05
  measurement above for the first sentence's wording.

### `gpt-6.1-sol` (GPT-6.1 Sol, exact-model override on the `gpt` family)

- **Documented contract:** `gpt-6.1-sol` (released 2026-09-29) is the exact
  contract; `gpt-6.1-sol-pro` is its declared pro-reasoning-mode projection
  (the Astra `-pro` shape; no `-fast` / `-flex` row) and a dated
  `gpt-6.1-sol-YYYY-MM-DD` id projects onto the base. 1,050,000-token
  context, 922,000 max input (derived: context minus output), 128,000 max
  output, knowledge cutoff 2026-04-30. Reasoning effort `low` through `max`
  with `medium` the API default; unlike GPT-6 Sol there is no `none` rung,
  so `off` and `minimal` are raised to the `low` floor on record
  (`floor_raised`), Astra's shape. The Codex client's ladder (no `none`,
  plus a Codex-only `ultra` that no OMH ladder carries) and its `low`
  default are recorded in `surface_notes` / `surface_efforts`.
- **Model trait (official, latest-model guide, read 2026-10-01):** the
  guide states every trait for the GPT-6 family "from behavior observed
  with GPT-6 Astra": asks the user a question more readily; more sensitive
  to instructions contained in skills; tends toward detailed, formatted
  responses; may delegate less often than desired; thorough in testing
  before considering a task complete. Official-client: the vendor's Codex
  model catalog gives 6.1 Sol GPT-6 Astra's base prompt plus one
  apology-restraint paragraph, where GPT-6 Sol keeps an older prompt.
- **What OMH injects:** Astra's two blocks, byte for byte
  (`MODEL_HIGH_EFFORT_CALIBRATIONS["gpt-6.1-sol"]` and
  `MODEL_COMPOSITION_CALIBRATIONS["gpt-6.1-sol"]` equal the `gpt-6-astra`
  entries; a test pins the equality). Subagent: the user's instructions
  outrank skill text and the numbered criteria are the complete task; ask
  one focused question only when a missing input would materially change
  the result, otherwise state the assumption and proceed; size tests to the
  change. Composer: the user's intent above skill text in each unit;
  delegate every independent unit; set each unit's effort from its task
  state, the documented floor (`low`) for routine follow-ups.
- **Explicitly not imported:** every sentence that pushes the model to keep
  working — the guide's "bias towards action and carry the user's intended
  task to completion", "persist until the user's intended goal is
  complete", "Do not settle for a partial or 'helpful enough' solution",
  the Codex prompt's "continue work without ending the turn to clarify with
  the user", and every "otherwise, continue toward completing the task"
  tail. The 2026-09-05 Astra measurement is why: the one clause with that
  reading cost +5,419 tokens per instance for the same pass set.
- **Measured (2026-10-02, `benchmarks/live-model-tools/v1`):** four arms at
  `high` on the Codex subscription, 30 instances each. Two `optimized` arms,
  one `family` arm, and one GPT-6 Sol arm. Every arm passed the same 18
  instances.
  - The override cost +1.9% and +3.2% tokens per instance against the
    family block, with nearly identical tool calls (351 / 352 vs 360). Both
    CIs span zero, and same-text drift was +1.3%. No measurable effect
    either way. It stays, unproven for 6.1 Sol.
  - Against GPT-6 Sol, 6.1 Sol used about 8% fewer tokens (CI spans zero)
    and 14% fewer tool calls (351 vs 409) for the same pass set. That
    supports the slot swap.
  - Full tables are in the benchmark README.
- **Version rule:** the override is keyed to `gpt-6.1-sol` only (and the
  forms that project onto it). GPT-6 Sol keeps the `gpt` family block
  unchanged; a later Sol generation gets this block only through its own
  row and its own evidence.
- **Throughput overlay:** `gpt_sol_codex_handoff` matches `*-sol`, so 6.1
  Sol as a Codex main agent inherits it, consistent with taking every GPT-6
  Sol slot (owner decision, 2026-10-01); `tests/test_executor_prompting.py`
  names `gpt-6.1-sol` so the inheritance is reviewed, not a suffix accident.
- **Routing:** on 2026-10-01 it took every slot GPT-6 Sol held, each at its
  effort: the `deep` head at `high` (second there since 2026-10-13, below),
  `last_resort.any` at `medium`, `role_suggestions.main` at
  `high`, and the Maestro `codex` rows GPT-6 Astra does not head. The five
  `codex` categories that left the effort to the CLI now name `medium`,
  because the Codex catalog defaults GPT-6 Sol to `medium` but 6.1 Sol to
  `low`, so an empty effort would have lowered them silently. The
  2026-10-13 table (owner decision) widens the Hermes lane: it heads
  `unspecified-high` at `medium` (the 2026-09-05 live-model-tools run put a
  GPT head at 18 / 30 against Kimi's 12 / 30 there, measured on
  `gpt-5.6-sol`), sits behind Opus 5.5 in `deep` (`high`), `capable`
  (`medium`), and `deep-work` (`max`), and is the GPT entry of
  `unspecified-low` (`low`); `main` now leads with it.
- **Pricing:** 2/10 list, cached input 0.10 (5% of input, an
  `APPROX_CACHE_READ_RATIO` row), cache write 2.5; `-pro` inherits the base
  row through its projection (pro mode bills at the selected model's
  standard rates). Long-context, batch/flex, and fast-mode multipliers stay
  in the contract.
- **Source:** official (model page, latest-model and reasoning guides,
  pricing page, API changelog, read 2026-10-01) and official-client (the
  openai/codex model catalog, read 2026-10-01). The wording is
  Astra-measured (2026-09-05); for 6.1 Sol it is editorial and unmeasured.
  The named follow-up is a `family` vs `optimized` pair on `gpt-6.1-sol` at
  `high` (the `deep` rung), and `gpt-6-sol` vs `gpt-6.1-sol` at `medium`
  (the last-resort rung).


### `gpt-6-cyber` (GPT-6 Cyber, access-gated, exact-model override on the `gpt` family)

- **What it is (official, read 2026-11-06):** released 2026-11-05 (API
  changelog). The system card says "GPT-6 Cyber is a cyber-specialized
  variant of GPT-6 Astra designed for authorized security work", gives it
  Astra's Preparedness designations (Critical in Cybersecurity), and makes
  it "available only to approved Daybreak Red users and organizations". The
  model page repeats the gate ("Your organization needs Daybreak Red access
  and approval"), lists a 1,050,000-token context, 922,000 max input,
  128,000 max output, one snapshot (`gpt-6-cyber`), Chat Completions and
  Responses as the only endpoints (no Batch), and "Reasoning token support"
  with no effort values.
- **Contract:** `gpt-6-cyber` is an exact contract, not a projection onto
  Astra, because its price, access, and endpoints are its own. The effort
  ladder is Astra's (`low` through `max`, `off` and `minimal` raised to
  `low` on record), inherited on the system card's statement and labeled
  `effort_ladder_source` in the record; the model page documents none. A
  dated `gpt-6-cyber-YYYY-MM-DD` id projects onto it; no `-pro` / `-fast` /
  `-flex` row is declared, because the pricing page lists none.
- **Price (official):** 20 / 100 per MTok, cached input 2 (the default
  tenth), cache writes 25 (30 minutes) and 50 (12 hours). Only a
  short-context card is published.
- **What OMH injects:** Astra's two blocks, byte for byte
  (`MODEL_HIGH_EFFORT_CALIBRATIONS["gpt-6-cyber"]` and
  `MODEL_COMPOSITION_CALIBRATIONS["gpt-6-cyber"]` equal the `gpt-6-astra`
  entries; a test pins the equality). Its model page, changelog entry, and
  system card give no prompting guidance, and Astra's documented traits are
  the nearest record for a variant of Astra. Editorial and unmeasured.
- **Placement:** none, and none proposed, and no executor option row (as
  for GPT-6.1 Terra; Mythos 5.1 keeps one). Like Mythos 5.1, most accounts
  cannot call it, and its scope is authorized security work, so naming it
  in a public chain would read as a recommendation nobody can follow. It is
  recognized, priced, and provider-mapped for a user who names it.
- **Served:** not on this maintainer host. One probe through the Codex
  subscription route on 2026-11-06 returned HTTP 400 ("The 'gpt-6-cyber'
  model is not supported when using Codex with a ChatGPT account"), the
  same wording a made-up id gets, so it cannot tell gated from absent. The
  `openai-codex` family in its provider row rests on the system card's
  "when accessing GPT-6 Cyber through the Codex app"; the Codex models page
  did not list it when read 2026-11-06. Measurement waits for an approved
  route, which this repo does not have.
- **Siblings on the same terms, without a contract:** GPT-5.6 Cyber
  (`gpt-5.6-cyber`, 2026-08-07, "an alias for purpose-trained cybersecurity
  models", 400K context, Responses only, 12.5 / 75) and GPT-6 Rosalind
  (`gpt-6-rosalind`, 2026-10-30, life-sciences research for approved
  organizations, 15 / 75 short-context; its model page returns 404) carry a
  price row, a provider row, and a display label, and get the `gpt` family
  block. GPT-5.6 Cyber's page documents no effort ladder and no base model to
  inherit one from, and GPT-6 Rosalind has no page to read one from.
- **Source:** official (developers.openai.com model pages, pricing page,
  and changelog; deploymentsafety.openai.com system card, read
  2026-11-06); observed (the Codex probe, and the Hermes source: no
  `gpt-6-cyber` row in v0.22.5 or origin/main `44ec783afd`).

### `gpt-6.1-terra` (GPT-6.1 Terra, exact contract; `gpt` family calibration)

- **Documented contract (official, developers.openai.com, read 2026-10-27):**
  released 2026-10-26 (API changelog). The model page lists a 1,050,000-token
  context, 922,000 max input, 128,000 max output, and a 2026-06-01 knowledge
  cutoff. Reasoning effort runs `none` through `max` with `medium` the API
  default. The latest-model guide says so directly: "GPT-6.1 Terra, GPT-6
  Sol, and GPT-6 Luna support `none`". That is GPT-6 Luna's shape, not GPT-6.1
  Sol's, so a no-reasoning request goes out as `none` and only `minimal` is
  raised to `low` on record. Tool calling requires the Responses API.
  `gpt-6.1-terra-pro` is the declared pro-reasoning-mode projection
  (OpenRouter lists it at the base card), and a dated
  `gpt-6.1-terra-YYYY-MM-DD` id projects onto the base.
- **Price (official):** 1 / 5 per MTok, cached input 0.05 (5% of input, the
  `APPROX_CACHE_READ_RATIO` row), 30-minute cache writes 1.25 and 12-hour
  2.50, the >272K long-context multiplier, Batch/Flex at half and Fast mode
  at double. No Ultrafast tier: the Ultrafast guide names only Astra and
  6.1 Sol. That is half of 6.1 Sol's card and below GPT-5.6 Terra's 2 / 12.
- **Surfaces (official-client and observed):** the Codex client's catalog
  (openai/codex `models-manager`, read 2026-10-27) lists `low` through `max`
  plus the Codex-only `ultra`, a `low` default, a 500K context with an 872K
  maximum, and the same base instructions as GPT-6 Astra and GPT-6.1 Sol. It
  names no upgrade from GPT-5.6 Terra. Hermes v0.22.5 and origin/main
  `a382af23f4` (observed) match the id to no GPT-6 effort prefix. On the
  Codex route Hermes therefore clamps `max` to `xhigh` with no notice and
  falls back to a 256K context. Neither build has a price row. A chain that
  names Terra at `max` on the Codex route actually runs `xhigh` until
  Hermes adds the id to its GPT-6 tier tables.
- **Model trait:** the guide states the GPT-6 family traits from Astra's
  behaviour and gives Terra no prompting guidance of its own. The model page
  positions it for visual reasoning, precise computer use, and writing. The
  vendor still points the most complex coding at 6.1 Sol or Astra (launch
  coverage). Vendor-reported numbers (Terminal-Bench 4.0 50.3% at `max`,
  Agents' Last Exam +15 pp over GPT-5.6 Terra at `medium`, and the error-prompt
  set) are labeled vendor-reported and drive no placement.
- **What OMH injects:** the `gpt` family block, unchanged. There is no exact
  override. The Codex catalog gives Terra Astra's base prompt as it does 6.1
  Sol, but the 2026-10-02 measurement found the Astra-text override had no
  measurable effect on 6.1 Sol, so the onboarding copies no unmeasured text.
- **Placement:** none. GPT-5.6 Terra's slots went to GPT-6 Sol on 2026-09-23,
  so no Terra slot exists for this id to inherit, and joining a shipped
  chain is an owner decision. An operator places it with
  `omh model-chains set <category> "gpt-6.1-terra:medium, ..."`.
- **Measured (2026-10-27, `benchmarks/live-model-tools/v1`):** Terra vs 6.1
  Sol at `high` on the Codex subscription, with the family block on both, so
  the model is the only difference. The clean Terra arm passed the same 18 /
  30 instances as Sol with 5.2% fewer tokens per instance (CI [−7,245,
  +182], spans zero). A first Terra arm lost six instances to a 25-second
  burst of child-process crashes, a runtime interruption. Its 24 completed
  instances agree with the clean arm, and same-model drift was +1.5%. This
  corpus tops out at 18 / 30 and has no read or lsp passes, so it says
  nothing about the hardest coding, where the vendor still points to Sol.
  Full tables are in the benchmark README.
### `claude` (Fable 5.1, Mythos 5.1, Fable 5, Opus 5.5, Opus 5, Sonnet 5.5, Sonnet 5, Haiku)

- **Model trait:** conscientious to a fault. Left alone it grows the
  checklist mid-run ("while I'm here…"), adds just-to-be-sure verification
  passes, and — as a composer — fans out speculative subagents, including
  ones that only re-check its own work. The 5.1 generation adds, per
  Anthropic's migration guide: at higher effort on routine work it gathers
  context and deliberates beyond what the task needs; it tidies, refactors,
  and commits extra tests nobody asked for; it rewrites a whole file where a
  targeted edit would do; in long agent loops it issues one implied tool call
  per turn where Fable 5 batched several; deep into a session it can end a
  turn by *announcing* the next step instead of running it; and progress
  claims drift from tool evidence on long runs. Parallel sub-agent delegation,
  by contrast, became dependable — the prior-model habit of suppressing it now
  costs wall-clock.
- **What OMH injects (subagent):** the numbered criteria are the *complete*
  checklist — do not grow it mid-run, and act once you have enough to act;
  deliberate deeply only where correctness is genuinely at risk and let the
  single verification pass prove the mechanical steps; edit surgically; fix
  only what the criteria name and report adjacent findings; keep scratch
  checks out of the repo and commit tests only where a criterion or the
  repo's own convention asks for them; add no helpers, fallbacks,
  validation, flags, or shims beyond what the criteria name; every progress
  claim points at a tool result, a failed check is reported with its output,
  a skipped step as skipped. The block sits exactly on the
  `BLOCK_MAX_CONSTRAINTS` ceiling; the 5.1 additions were phrased as
  descriptions rather than modal directives to stay there. It no longer
  counters the 5.1 "early stopping" trait: the sentence that did ("no one is
  watching ... proceed on every reversible action ... do that work now")
  pushed the model to keep working, which `docs/MODEL-ONBOARDING.md` §2
  forbids, and was removed on the measurement below.
- **Measured (2026-09-23, subagent block):** three arms on
  `benchmarks/live-model-tools/v1`, evaluation split (30 instances),
  `hermes_current_session` path, `og` / `anthropic/claude-fable-5-1` at
  `xhigh` (then the `architect` chain head, third behind Opus 5.5 and
  GPT-6 Astra since 2026-10-13; `xhigh` puts the route in the high-effort
  tier), condition `optimized`, one arm at a time, same UTC day.
  `current` is the old block (sha256 `78dc1ff9…`), run twice; `deletion` is
  the block above, identical except that the push sentence is removed
  (sha256 `7a237a14…`).

  | arm | window (UTC) | pass | harness tokens | tool calls | API calls |
  |---|---|---|---|---|---|
  | current | 06:20–06:45 | 18 / 30 | 2,760,212 | 317 | 206 |
  | deletion | 07:20–07:44 | 18 / 30 | 2,641,559 | 302 | 201 |
  | current (repeat) | 07:45–08:12 | 18 / 30 | 2,955,008 | 324 | 219 |

  All three passed the same 18 instances (McNemar p = 1.0), so pass rate
  decided nothing. Paired per-instance token deltas, bootstrap CI95: running
  the same text twice moved +6,493 [−1,882, +17,224] (+7.1% in total);
  deletion against the mean of the two current runs is −7,202 [−15,422, −47],
  and +1 [−6,854, +6,254] on the 18 passing instances. So the deletion costs
  no more than the text it replaced, within same-text drift, which was the
  pre-registered rule. A second revision that also rewrote the evidence
  sentence into a per-criterion report rule measured 18 / 30 at 2,904,402
  tokens; it was not shipped, since one of its clauses ("a next step described
  instead of run is reported as not done") reads as the same push. Its total
  (+5.2%, +4,806 per instance against the first current run) sits inside the
  same-text drift, but on the
  passing instances it measured +7,287 [+2,783, +11,775], above the same-text
  passing drift of +4,525. Tool and API calls come from Hermes'
  session rows, outside the harness. Not measured: the composer block's
  deletion below (no fanout in this harness; #1836), and any claim beyond
  this corpus, route, and effort. Archive (outside git, owner checkout):
  `.omc/research/claude-calibration-bench-2026-09-23/`, where
  `three_arm_analysis.py` and `paired_tokens.py` produce every number above.
- **Measured against no block (2026-10-04, prompt audit):** the block had
  only ever been compared with its own earlier wording, so the audit asked
  whether Fable 5.1 still needs it at all. Three arms, same corpus and
  harness, `claude-fable-5-1` at `xhigh` on the Claude Code subscription
  (Hermes `anthropic` provider):

  | arm | window (UTC) | pass | mean tokens | tool calls | API calls |
  |---|---|---|---|---|---|
  | baseline (no block) | 06:50–07:16 | 16 / 30 | 111,383 | 356 | 227 |
  | optimized (this block) | 07:16–07:40 | 17 / 30 | 99,409 | 313 | 201 |
  | baseline (repeat) | 07:40–08:06 | 18 / 30 | 104,155 | 348 | 215 |

  - Same-text drift was −6.5% [−17,928, +2,240] per instance.
  - The block against the first baseline was −10.7% [−21,404, −3,505] (CI
    excludes zero), and −4.6% [−12,179, +1,862] against the repeat.
  - Tool calls were about 11% lower than both baselines (313 vs 356 / 348).

  **Decision: keep.** The block does not cost more than no block, and it
  consistently trims tool calls. It is no longer a removal candidate.
- **What OMH injects (composer):** split only what the goal requires, no
  speculative units, no unit whose only job is re-checking the split itself
  (a fresh-context review of a unit's deliverable is a legitimate unit);
  delegate what is independent and evidence-judgeable, keep in line what
  finishes in a handful of tool calls; state the criteria once and freeze;
  write the closing report as the reader's first look (outcome first, plain
  sentences, no working shorthand). Two clauses were removed on 2026-09-23
  because they pushed the model to keep working: "keep working while
  delegated units run" and "If your closing paragraph is a dispatch you could
  run, run it before closing". The second was the composer-side counter to
  the 5.1 trait of announcing a next step instead of running it, so that
  trait is no longer countered here, as in the subagent block. The change is
  deletion-only and **unmeasured**:
  `benchmarks/live-model-tools/v1` runs one agent with no fanout and never
  calls `composition_calibration_for_model()`, so no arm can reach this block.
  #1836 tracks a measurement path for it.
- **What OMH injects (throughput overlay, advanced modes):** a delegated
  lane returns a distilled report — outcome, evidence pointers, open items —
  never its transcript; delegated transcripts are what floods a composer's
  context.
- **Version rule:** the counters are written for 5.1 and are harmless on
  Fable 5 / Opus 5 (the batching and whole-file-rewrite counters simply hold
  behavior those models already had). The Opus 5 guidance to *delete*
  verification instructions does not apply to 5.1 — the single verification
  pass stays. `claude-mythos-5-1` is the same model as `claude-fable-5-1`
  served only to Project Glasswing-approved organizations; it takes the same
  calibration, and no shipped chain names it — a user who asks for it by
  name is still recognized and routed.
- **Opus 5.5 (2026-09-23): no new counter, family blocks byte-stable.**
  Anthropic says "Existing Claude Opus 5 prompts should perform well without
  changes" (official, the Opus 5.5 prompting guide). Three documented traits
  bear on reading this block for it, all official: effort names do not map
  one-to-one across generations — Opus 5.5 at `medium` matches or exceeds
  Opus 5 at `high` on Anthropic's coding and knowledge-work evaluations, and
  it thinks more per turn at a given rung, especially at `xhigh` and `max`;
  thinking is always on and cannot be disabled (a request that disables it
  is a 400, which is why `omh_delegate_route` refuses a no-thinking effort
  for this id); and text between tool calls arrives in `thinking` blocks
  that are empty at the default display setting, which the existing "every
  progress claim points at a tool result" sentence already covers. Until
  2026-10-13 the shipped rungs were `medium` and `low`, so the subagent
  block did not fire in shipped chains; the 2026-10-13 table ships Opus 5.5
  at `high` (`deep`, `visual-engineering`, `artistry`), `xhigh`
  (`architect`), and `max` (`deep-work`), so it now does. The composer block
  fires too, because Opus 5.5 is in the `main` role suggestion. Anthropic's "Unattended agentic runs" paragraph is
  deliberately not adopted: it tells the model to keep working. Editorial,
  unmeasured: Opus 5 vs Opus 5.5 at the same rung is the named follow-up.
- **Measured (2026-09-24, subagent block on Opus 5.5, block vs no block):**
  three arms on `benchmarks/live-model-tools/v1`, evaluation split
  (30 instances), `hermes_current_session` path, `og` / `claude-opus-5-5`
  at `xhigh`, `optimized` condition, one arm at a time, same UTC day. O1
  sends no calibration block (2,567,274 harness tokens); O2 sends the block
  above, the 2026-09-23 deletion text (2,606,382 tokens); O3 repeats O2 to
  measure same-text drift (2,769,542 tokens). All three passed the same
  18 / 30 instances (McNemar p = 1.0), so pass rate decided nothing. Tasks
  with the block used +4,023 tokens per task more than the no-block
  baseline on average, bootstrap CI95 [−3,983, +12,842]; running the same
  block-bearing text twice moved +5,439 [−1,033, +12,334]. The block's cost
  sits inside its own same-text drift — no measurable effect either way —
  so it is kept. When it ran, `xhigh` was not a shipped Opus 5.5 setting
  and the measurement bore only on an operator running Opus 5.5 manually.
  Since the 2026-10-13 table it bears on a shipped route: Opus 5.5 heads
  `architect` at `xhigh`, the rung these arms ran at, and sits at `high` or
  `max` in four more chains, so the subagent block (`HIGH_EFFORT_TIER`)
  now fires on shipped Opus 5.5 units; the `high` and `max` rungs are
  unmeasured.
  Not measured: O4 (Opus 5.5 at `medium`, the shipped rung) and O5 (Opus 5
  at `medium`) were skipped for cost on the owner's decision, so this makes
  no claim about Opus effort placement and no claim about the Opus 5 → 5.5
  swap. Corpus ceiling on this bench is 18 / 30 (no arm passes the read or
  lsp templates); wall clock was contended in all but one arm and is not
  compared. Archive (outside git, owner checkout):
  `.omc/research/opus55-luna-bench-2026-09-24/`.
- **Opus 5.5 in the shared last resort names `medium` (2026-09-24,
  editorial, unmeasured).** The `last_resort.any` entry carried no effort,
  which does not mean the API default: fanout dispatch then passes no effort
  flag and the executor CLI's own default applies, and a prepared route
  carries none. Anthropic's Opus 5.5 guidance is to set effort explicitly
  (official,
  https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-opus-5-5.md;
  the Opus 5.5 migration guide's checklist says the same), `medium` is the rung Opus 5.5 already carries in
  `unspecified-high` and `capable`, and GPT-6.1 Sol beside it already names `medium`. No
  calibration block fires at `medium`, and the vendor order is unchanged.
  Named follow-up: bench arm O4 (Opus 5.5 at `medium` on
  `benchmarks/live-model-tools/v1`), the arm skipped above.
- **Source:** the original checklist/fan-out counters are adapted research
  (same origin as `gpt`), the composer block was added after observing
  over-fan-out in live composition; the 5.1 additions follow the official
  Claude Fable 5.1 migration guide's prompt-tunable behavioral shifts
  (official label; the "let it delegate", "act when you have enough",
  "targeted edits", "scope and test coverage", "batch independent tool
  calls", "ground progress claims", and "early stopping" entries). Only the
  2026-09-23 push-sentence removal above is measured on 5.1 in this repo. The
  block as a whole is not measured against no calibration, and the Fable 5 vs
  5.1 benchmark pair is still the named follow-up.

### `claude-sonnet-5-5` (Claude Sonnet 5.5, exact contract; `claude` family calibration)

- **Documented contract:** `claude-sonnet-5-5` (released 2026-09-28,
  retirement not sooner than 2027-09-28) is the exact contract; the Bedrock
  id `anthropic.claude-sonnet-5-5` and OpenRouter's dotted
  `claude-sonnet-5.5` are declared projections. 1M context, 128K max output,
  list price 2/10 per MTok. Effort `low` through `max`, API default `high`
  (recalibrated against Sonnet 5). `thinking.type=disabled` and a manual
  budget return HTTP 400; the API's one thinking-off mode,
  `between_tools`, is a request neither Hermes nor Claude Code sends, so
  `off` / `none` / `minimal` are raised to `low` on record and
  `omh_delegate_route` refuses a no-thinking effort for it.
- **Placement:** none from 2026-10-01 (owner decision) until the
  2026-10-13 table, which closes `unspecified-low` with it at `low` and puts
  it second in `writing` at `medium`. Neither rung reaches the high-effort
  tier, so the subagent block does not fire on a shipped Sonnet unit.
  Anthropic lowered its cache reads from $0.20 to $0.10 per MTok on
  2026-10-07 (the Haiku 5.5 launch post, read 2026-10-13), and the contract
  and the approximation ratio follow. The Maestro Claude Code rows `unspecified-low`
  and `artistry` name the `sonnet` alias, which Claude Code resolves to
  Sonnet 5.5 on the Anthropic API from v2.1.284 and to Sonnet 4.5 on
  Bedrock, Google Cloud, and Foundry; that alias carries no contract.
- **Model trait (official, Sonnet 5.5 prompting guide, read 2026-10-01):**
  "At these levels [`xhigh`, `max`] the model is especially thorough. After
  it finishes a task, it can start its own rounds of review and
  verification, sometimes with subagents." It also adds tests and docs
  nobody asked for (the family block already counters that), and at `low`
  and `medium` it can stop to check in early.
- **What OMH injects:** the `claude` family blocks, subagent and composer,
  since 2026-10-04. Until then an exact-model override added one clause to
  the family block's verification sentence (once the criteria's checks pass
  the work is done; start no further review rounds and no reviewer
  sub-agents unless a criterion asks for one), and the composer override was
  the family block byte for byte. Both were removed on the measurement
  below. Bedrock spellings (`anthropic.claude-sonnet-5-5`, and regional
  forms such as `us.anthropic.…`) classify as `claude` too, since
  `model_family` reads the `anthropic.` vendor segment (2026-10-04; before
  that they fell to `generic`, Opus 5.5's Bedrock id included).
- **Evidence:** vendor-measured, and not reproduced in OMH. The guide says
  the stop instruction "stopped the model from launching reviewer subagents
  and cut session cost by about a third, with no change in quality" on
  coding tasks at `max`.
  - **OMH run (2026-10-02, `benchmarks/live-model-tools/v1` at `max`, Claude
    Code subscription):** two `optimized` arms and one `family` arm, 30
    instances each.
  - **Result:** the override arms used +4.0% and −6.3% tokens per instance
    against the family block, and same-text drift was −9.7% (CI excludes
    zero). Drift exceeds any override effect, and the pass sets match (18,
    18, and 17 plus one provider crash).
  - **Why it may not reproduce:** the corpus asks for no review, and the
    Hermes child path ran no reviewer sub-agents, so the clause may have
    nothing to suppress here.
  - **Decision (2026-10-02):** the block stays, unproven, because it is
    not worse.
  - **Decision (2026-10-04, prompt audit):** removed. The override was
    indistinguishable from the family block within same-text drift, and no
    shipped slot reached it: no pinned Sonnet id sits in a chain, and the
    Maestro `sonnet` alias carries no contract. An override that no slot
    reaches and no run distinguishes spends a maintained block on nothing.
    A corpus that provokes extra review rounds is the evidence that would
    bring it back.
- **Explicitly not imported:** the guide's fix for early check-ins at low
  effort ("Keep working until everything the user asked for is done"). It
  pushes the model to keep working, which `docs/MODEL-ONBOARDING.md` §2
  forbids; the guide's first remedy, a higher effort, is a placement lever.
- **Version rule:** the contract is keyed to `claude-sonnet-5-5` and the
  forms that project onto it; calibration follows the family like Sonnet 5,
  Opus 5.5, and Fable 5.1.

### `claude-haiku-5-5` (Claude Haiku 5.5, exact contract; `claude` family calibration)

- **Documented contract:** `claude-haiku-5-5` (released 2026-10-07,
  retirement not sooner than 2027-10-07) is the exact contract; the Bedrock
  id `anthropic.claude-haiku-5-5` and OpenRouter's dotted
  `claude-haiku-5.5` are declared projections, and a dated snapshot form
  resolves through the base. 1M context, 128K max output. Two prices chosen
  by prompt length: 0.10/0.50 per MTok up to 100K prompt tokens (cache read
  0.01) and 0.50/2.50 above (cache read 0.05); the approximation table
  carries the lower card, so a run with prompts over 100K is under-reported.
  The first Haiku with an effort ladder: `low` through `max`, API default
  `medium`. Unlike Opus 5.5 and Sonnet 5.5 it accepts
  `thinking.type=disabled` at `high` or below, so `off` passes through on
  record and `omh_delegate_route` does not refuse it; `minimal` is raised to
  `low`. Sources: Anthropic's models overview, pricing, model-deprecations,
  Haiku 5.5 migration and prompting guides, and the launch post, read
  2026-10-13.
- **Placement:** the 2026-10-13 table (owner decision) puts it at `low` in
  `quick` (third) and `simple-work` (second), taking Claude Haiku 4.5's
  slot. Editorial and unmeasured. The Maestro Claude Code `haiku` rows are
  an alias the client resolves to Haiku 5.5 on the Anthropic API from
  v2.1.293 and to Haiku 4.5 elsewhere; that alias carries no contract.
- **Documented traits, no counter shipped.** Official (Haiku 5.5 prompting
  guide): at `low`, in a long agent prompt, it sometimes stops early and
  hands the task back; at `low` and `medium` it sometimes reports a code
  change as done without running a check; at `xhigh` in multi-turn chats it
  can end a turn with its whole answer in thinking. The reason no counter
  ships is placement, the GPT-6 Luna precedent: the shipped rung is `low`,
  the subagent block fires only at `high` and above (`HIGH_EFFORT_TIER`),
  and Haiku 5.5 is not a `main` suggestion, so no shipped Haiku unit
  receives either block. The family block's single verification pass is
  what a unit at `high` would get. The guide's fix for early stopping
  ("Keep working until everything the user asked for is done") is not
  imported: it pushes the model to keep working, which
  `docs/MODEL-ONBOARDING.md` §2 forbids.
- **Runtime gap (observed in the Hermes source):** the shipped `low` rung
  takes effect only on a Hermes build that forwards Haiku effort. On Hermes'
  Anthropic route, builds through v0.21.6 (2026-10-08), the 0.21.1 floor
  included, treat every `haiku` id as pre-thinking and send neither thinking
  nor effort, so a Haiku 5.5 unit there runs at the API default `medium`
  whatever rung the chain names. v0.21.7 (2026-10-12; fix 8ed7d31b20 of
  2026-10-11 UTC) and origin/main 63d0b941200 send adaptive thinking plus
  `output_config.effort`. No served
  route was probed in this onboarding, so the placement is documented, not
  observed.
- **Named follow-up:** Haiku 4.5 vs Haiku 5.5 at `low` on
  `benchmarks/live-model-tools/v1`, and a `family` vs `optimized` pair if a
  counter for the low-effort traits is proposed.

### `gemini` (Gemini 4 Argon, Gemini 3.1 Pro)

- **Generation note (2026-10-28):** the block below was written for Gemini
  3.1 Pro and carries over to Gemini 4 Argon unchanged; it is unmeasured on
  Argon. Google's Argon guides document no verbosity, eagerness, or
  tool-use change to counter. The announcement does name one risk this
  block already covers: Google monitors Argon's chain of thought and actions
  so that it does not step "out of bounds to try to accomplish a task in a
  way that goes beyond the user's intentions" (blog.google, 2026-09-30).
  That is the boundary expansion the subagent block calls a defect, so no
  Argon-specific text was added. The 3.1-Pro-vs-Argon pair in the next
  section decides whether the block still holds.

- **Model trait:** fluent and confident narration. Its observed failure mode
  is asserting results from recall rather than from tool output, sounding
  "done" before verification has run, and creatively expanding beyond the
  declared boundary because the expansion seems like an improvement.
- **What OMH injects (subagent):** a claim without the tool output that
  proves it is not evidence — run the actual check and report from its
  output; done-sounding language before the mandatory verification pass is a
  failure, not optimism; expansion outside the boundary is a defect here.
- **What OMH injects (composer):** compose from tool-verified facts, not
  recall — run the inventory and readiness commands before naming owners or
  models; a unit is "prepared" only when the prepare command produced its
  artifact.
- **Source:** observed failure modes in live usage (authored in the
  per-family calibration commit; no upstream text existed for this shape).

### `gemini-4-argon` (Gemini 4 Argon, exact contract; `gemini` family calibration)

- **Documented contract (official, ai.google.dev, read 2026-10-28):**
  generally available 2026-10-13 under the one stable id `gemini-4-argon`
  (no preview or dated id is listed). 1,048,576 tokens is a unified input
  and output limit. A synchronous request returns up to 65,536 output
  tokens, and long decode (`background: true`) raises that to 1,048,576.
  `max_output_tokens` is a hard stop on thinking and output together, and
  the migration guide recommends at least 32,768. Thinking cannot be turned
  off: `thinking_level` accepts `low`, `medium`, and `high`, and the
  default is `medium`. `temperature`, `top_p`, and `top_k` are ignored.
  Only implicit caching is supported. Not on the free tier.
- **Effort on the route:** `off`, `none`, and `minimal` are raised to the
  floor `low` on record (`floor_raised`). `xhigh` and `max` pass through on
  record: no documented rung sits above `high`, and the raise rule would
  otherwise lower them to the floor. Hermes (observed, v0.22.5
  `bf0203a794`) sends them as `thinkingLevel: high` and, on direct Google
  endpoints only, adds a long-decode budget of 262,144 tokens at `xhigh` and
  1,048,576 at `max`. No shipped slot names a rung above `high`.
- **Placement (owner decision, 2026-10-28):** `gemini-4-argon` took every
  Gemini 3.1 Pro slot at the effort each carried: `writing` and
  `google-search` at `medium`; `visual-engineering`, `artistry`,
  `x-search`, and `synthesize` at `high`; and the `x_platform_data`
  affinity. Gemini 3.1 Pro left the shipped chains under the
  superseded-generation rule. It stays recognized, priced (2/12), and
  provider-mapped, so an operator override that names it still resolves.
  On Hermes, 3.1 Pro at `medium` was sent as `low`, because Hermes allows
  only `low` and `high` for a Gemini 3 Pro id (observed). Argon's `medium`
  goes on the wire as `medium`, so the two `medium` slots now run the rung
  they name. Provider families: `google`, `gemini`, `openrouter`
  (OpenRouter lists `google/gemini-4-argon`). Editorial and unmeasured.
- **Price:** 2/10 through 2026-11-30 and 4/20 from 2026-12-01, cache read
  0.05 of input in both periods. The approximation table carries the
  current card, so re-read the page after the step-up.
- **Surfaces:** gemini-cli main has no Argon entry and says it is "Not
  optimized for Gemini 4+" (official-client). Google's guides disagree on
  `thinking_budget`: AI Studio maps it to a level with a warning and Vertex
  AI returns HTTP 400, so only `thinkingLevel` is safe. OpenRouter's
  floating `~google/gemini-pro-latest` now points at Argon (community).
- **Named follow-up:** Gemini 3.1 Pro vs Gemini 4 Argon at `high` on
  `benchmarks/live-model-tools/v1`. No served route existed on the
  onboarding machine (no Gemini, Google, or OpenRouter key), so neither the
  served probe nor the pair has run.

### `grok` (Grok Build 0.1, formerly Grok Code Fast)

- **Generation note (2026-10-01):** xAI retired Grok Code Fast on
  2026-05-15; its model page lists `grok-code-fast-1`, the bare
  `grok-code-fast`, and `grok-code-fast-1-0825` as aliases of
  `grok-build-0.1`, so on xAI's API the `x_platform_data` slot already ran
  Build 0.1 before the chain named it. Other routes may differ: the Hermes
  retirement map sends `grok-code-fast-1` to `grok-4.3`. The block below was written for Grok Code Fast and carries over
  unchanged; it is unmeasured on Build 0.1. xAI documents no effort
  parameter for it, and Hermes sends none.

- **Model trait:** speed-first, search-heavy. The risk profile is the inverse
  of the deep reasoners: not over-verification but *under*-verification —
  fast answers that skip the proof, and repeated re-querying when a search
  surfaces many candidates.
- **What OMH injects (subagent):** speed is the default and the numbered
  criteria are the brake — a fast first answer never skips the single
  mandatory verification pass; pick from search results once, by the stated
  criteria, and act.
- **What OMH injects (composer):** pick the partition once by the stated
  boundaries and dispatch; re-querying for a better split is re-verifying a
  settled decision. The block used to open by asking for the overlap and
  dependency-cycle checks before recording the contract; that sentence was
  removed on 2026-10-04 under the authoring rule above, because recording
  is the check: `omh coding fanout prepare` and `validate` run
  `detect_boundary_overlaps` and `merge_order` (`src/coding/fanout.py`) and
  refuse to freeze an overlap without a `depends_on` edge or a cycle
  (`tests/test_fanout_contract.py`), and dispatch reads only a recorded
  contract.
- **Source:** written fresh for OMH — the calibration commit records that
  grok had no upstream precedent; the content encodes the family's publicly
  stated speed-first design plus observed search-churn behavior.

### `kimi` (Kimi K3, K3 Ultrafast, K3.1 Pro, K3.1 Pro Highspeed)

- **Model trait:** a deep decompose-compare-verify reasoning loop. Excellent
  on genuinely hard problems; wasteful on low-entropy mechanical steps, where
  it enumerates alternatives that no stated criterion distinguishes.
- **What OMH injects (subagent):** reserve the decompose-compare-verify loop
  for the genuinely hard parts; mechanical steps are low-entropy — execute
  them directly; if you catch yourself listing options for a step no
  criterion distinguishes, stop analyzing and act.
- **What OMH injects (composer):** partitioning work is mostly low-entropy —
  decide the split once and freeze it; keep the deep reasoning for boundary
  overlaps and dependency cycles; if two partitions both satisfy the
  boundaries, take the first and move.
- **Source:** observed failure modes in live OMH usage of Kimi K3 (authored
  in the per-family calibration commit).
- **Version rule:** K3.1 Pro and its Highspeed tier take these blocks
  unchanged. Moonshot describes K3.1 Pro as K3 with much more
  post-training, served under K3's parameter contract. Nothing in its
  thinking, tool, or effort contract changes the trait above, so there is
  no new trait to counter yet. The K3-vs-K3.1 pair in the next section
  decides whether the blocks still hold.

### `kimi-k3.1-pro` (Kimi K3.1 Pro and K3.1 Pro Highspeed, exact contracts; `kimi` family calibration)

- **Documented contract (official, platform.kimi.ai, read 2026-10-24):**
  released 2026-10-23, the first K3.1-series model. 1,048,576-token
  context. `max_completion_tokens` defaults to 131,072 and goes up to the
  full window. Thinking is always on, and `reasoning_effort` accepts `low`,
  `high`, and `max`, with `max` as the default. The `thinking` parameter is
  K2-only. `temperature`, `top_p`, `n`, and both penalties are fixed, and
  any other value is an error. `tool_choice` accepts `auto`, `none`, and
  `required`. Forcing one named function returns HTTP 400 while thinking is
  on. Every later turn returns the complete assistant message, including
  `reasoning_content` (Preserved Thinking is always on). Switching the
  effort level mid-conversation invalidates prefix-cache hits.
- **Effort on the route:** the API accepts no other rung, so each one is
  listed as unsupported and raised on record (`floor_raised`). `off`,
  `none`, and `minimal` go to `low`, `medium` to `high`, and `xhigh` to
  `max`. The last two are the same mapping Hermes' kimi-coding provider
  applies on the wire (`KIMI_K3_OVERRIDES`, observed in the installed
  0.22.2 and origin/main `5894e750c3`). With the route record raising them
  the same way, the record shows what was actually sent. Kimi K3 itself
  still has no contract, so its routes are unchanged.
- **Highspeed is its own exact contract.** Moonshot calls it the same model
  at 2-3x the speed. It is not a declared projection because it has its
  own rate card: 4/20 per MTok against the base model's 2/10, with cache
  writes doubled but cached input the same 0.20. No single service-tier
  multiplier reproduces that card. Its `service_tier` is `highspeed`, and
  the approximation table carries its 0.05 cache ratio. As an exact id it
  never projects onto a chain entry that names the base model, so a chain
  that wants Highspeed has to name it.
- **Placement (owner decision, 2026-10-24):** `kimi-k3.1-pro` took every
  Kimi K3 slot at the effort each carried. That covers eight categories, the
  `main` role suggestion, and the `x_platform_data` affinity. K3 left the
  shipped chains under the superseded-generation rule. It stays recognized,
  priced, and provider-mapped, so an operator override that names it still
  resolves. The `medium` and `xhigh` slots are off-ladder for this model, as
  they were for K3, whose ladder is the same. The route records the raise to
  `high` and `max`, the rungs Hermes sends. Highspeed joins no chain.
  Provider families for the base id are the ones observed serving K3.1 Pro
  (`kimi-coding`, `openrouter`, `opencode`); `apitopia`, which carried K3, is
  not claimed because nobody observed it serving K3.1 Pro. For Highspeed,
  `kimi-coding` is the only family observed serving it. Editorial and unmeasured; the pair below confirms or
  reverses it.
- **Surfaces:** Hermes resolves both ids to the 1 Mi window through its
  `kimi-k3` context row and has no price row for them (observed). The Kimi
  Code plan serves bare `k3.1-pro` / `k3.1-pro-highspeed` slugs
  (models.dev, community). Those slugs classify `unknown` here, like bare
  `k3`.
- **Measurement (named follow-up):** the paired runs are `kimi-k3` vs
  `kimi-k3.1-pro` on `benchmarks/live-model-tools/v1` at the same effort,
  plus `baseline` vs `optimized` for the family block on K3.1 Pro. On
  2026-10-24 neither can run on the maintainer host: OpenGateway lists no
  K3.1 id, and no Moonshot or OpenRouter key is configured.

### `glm` (GLM 5.3, 5.3 Flash, 5.2, speed tiers)

- **Model trait:** an interleaved-reasoning style — thinking woven between
  tool calls. That style genuinely improves tool-result interpretation, but
  applied indiscriminately it plans mechanical steps that need no plan. The
  5.3 generation hardens the style into a served contract: thinking cannot
  be disabled (depth moves through the provider's reasoning-effort levels
  instead), and the coding endpoint preserves reasoning across tool calls by
  default — expecting the preserved blocks returned complete, unmodified,
  and in order, or cache effectiveness and continuity are lost. GLM 5.3
  Flash is a separately trained smaller MoE, not a speed tier, but it is the
  same `glm-` family and receives the same calibration; the served 5.3
  speed tier is `glm-5.3-highspeed`. Community harness evidence (Cline's
  GLM system-prompt rework) adds two family sensitivities: short,
  mechanically explicit prompts with strict tool-invocation rules outperform
  narrative ones, and tool-call formatting decays in very long contexts.
- **What OMH injects (subagent):** use interleaved reasoning only where it
  improves a tool decision — interpret each result, choose the next bounded
  action, preserve prior reasoning context when the runtime exposes it,
  returned complete and unmodified in its original order; on 5.3, reasoning
  depth is the routed effort level, never a request for no thinking;
  mechanical steps need no extended plan.
- **What OMH injects (composer):** interleave reasoning to interpret evidence
  between contract-building tools; mechanical field assembly needs no extra
  planning; keep unit prompts lean and mechanically explicit and unit scopes
  bounded (long-context tool-call decay); freeze the smallest split once
  boundaries are clean. A sentence saying Z.ai prices cached input
  separately was removed on 2026-10-04: it restated the universal
  prompt-cache discipline, which `omh coding composition-guide` prints beside
  every composer block.
- **Source:** observed failure modes plus the family's documented
  interleaved/preserved-thinking contract (docs.z.ai thinking-mode and
  GLM-5.3 release docs, 2026-08) and community harness reports (Cline's
  GLM-4.6 system-prompt rework; OpenCode long-context tool-call-format
  reports). The GLM guidance shipped with the baseline-vs-calibrated
  benchmark harness so its effect is measurable.

### `qwen` (Qwen3-Coder)

- **Model trait:** the current Qwen3-Coder is, per its own release
  documentation, a **non-thinking** coding-agent model — it does not emit
  reasoning traces, and prompting it for chain-of-thought or thinking tags
  degrades it rather than helping.
- **What OMH injects (subagent):** do not ask it to emit reasoning or
  thinking tags; give the exact goal, repository state, allowed boundaries,
  tool schemas, and completion criteria; follow one explicit plan; recover
  from failures using observed tool output; stop after one passing
  verification run.
- **What OMH injects (composer):** freeze one ordered split with exact
  owners, boundaries, tool contracts, dependencies, and verification
  commands instead of requesting reasoning output.
- **Source:** provider-published model characteristics (Qwen3-Coder's
  non-thinking architecture); shipped with the benchmark harness.

### `deepseek` (DeepSeek versioned line)

- **Model trait:** a heterogeneous family — some variants are reasoning
  models, some are not, and the split moved across versions. The common
  error in the wild is applying legacy R1-era reasoning prompts to every
  DeepSeek model, which is wrong on the non-reasoning variants. Two further
  facts come from DeepSeek's own agent harness
  (deepseek-ai/deepseek-harness, master 2026-08-13): its benchmark preset
  reproduces the Claude-SWE-compatible exact-string editor contract
  verbatim — the family is post-trained on exact-literal `old_str` edit
  semantics with uniqueness and whitespace discipline — and DeepSeek
  serving prices cached prefixes, which that harness treats as a
  first-class composition constraint.
- **What OMH injects (subagent):** treat the model version and its declared
  thinking mode as *contract fields*; preserve runtime-provided reasoning
  context across tool results only on a reasoning-capable route; otherwise
  use the same explicit goal/boundaries/criteria without thinking tags; edit
  by exact literal strings (a unique match with exact whitespace); make
  the smallest correct change, verify once, stop.
- **What OMH injects (composer):** keep the DeepSeek version and thinking
  mode explicit in the prepared route; no synthetic thinking instructions on
  non-reasoning routes; validate once and stop. The family residue of the
  prompt-cache discipline (DeepSeek prices cached prefixes, so the rule is
  billing-visible) was removed on 2026-10-04: the universal rule rides the
  same `omh coding composition-guide` output as this block.
- **Source:** provider-published model characteristics (DeepSeek's
  reasoning/non-reasoning variant split; shipped with the benchmark
  harness), plus the DeepSeek Harness review adopted in #1071 (exact-string
  RL edit contract, priced prefix caching — the priced-prefix fact later
  generalized into the universal prompt-cache protocol above).
- **Generations:** DeepSeek V4.1 Flash (2026-09-10) has its own exact
  contract and override below, because on that model the family block's
  conditionals resolve (thinking is on by default, the reasoning is returned
  on every tool turn) and the vendor documents a three-rung effort ladder.
  Every other DeepSeek id — V3.2, V4 Flash, V4 Pro, `deepseek-chat`,
  `deepseek-reasoner` — keeps this family block.

### `deepseek-v4.1-flash` (DeepSeek V4.1 Flash, exact-model override on the `deepseek` family)

- **Documented contract:** `deepseek-v4.1-flash` (released 2026-09-10) is
  the exact contract; OMH's alias is the versioned gateway spelling
  (`deepseek/deepseek-v4.1-flash` on OpenRouter). The first-party API names
  the current Flash generation `deepseek-flash`, and that pointer is the one
  declared alias (`DECLARED_MODEL_CONTRACT_PROJECTIONS`): it inherits the
  contract with `declared_inheritance` provenance and a read date, because
  the next Flash release moves it. `deepseek-v4-flash` and
  `deepseek-v4-flash-vision-exp` are routed to V4.1 Flash by the vendor, while
  `deepseek-v4-pro` stays a separately priced model (pricing page re-read
  2026-10-28). Since 2026-10-17 the pointer serves DeepSeek-V4.1-Flash-1017,
  an upgrade of this model at "The API calling method and pricing remain
  unchanged" (change log, re-read 2026-11-06); the relay spelling
  `deepseek-v4.1-flash-1017` is a second declared alias of the contract.
  Its row equals the pointer's, so a child observed under it also labels
  the pointer's category, but nothing projects onto it in reverse. The
  2026-09-13 measurement below predates the upgrade. Apart from
  `deepseek-flash` and `deepseek-v4.1-flash-1017`, no spelling inherits — a routed alias is the vendor's wire concern,
  not a catalog claim. The contract records a 1,000,000-token context,
  384,000 max output, thinking on by default at `high`, the documented
  effort ladder `low` / `high` / `max` with no floor to raise to (the
  thinking-mode guide publishes the mapping for every other rung —
  `minimal` → `low`, `medium` → `high`, `xhigh` → `high`, `ultra` → `max` —
  and nothing returns an error, so `unsupported_efforts` is empty and the
  route passes `medium` or `xhigh` through on record with the table in the
  contract saying what it bought), tool calling on Chat Completions, the
  Responses API, and the Anthropic-compatible endpoint, `reasoning_content`
  of every earlier turn sent back on every request that carries `tools` —
  even turns without a tool call, HTTP 400 otherwise — and `temperature` /
  `presence_penalty` / `frequency_penalty` without effect in thinking mode
  (`top_p` has a 0.95 floor there). Full record and
  sources in `src/coding/model_contracts.py`; `omh coding model-contract
  --model deepseek-flash` prints the declared projection. No
  `dynamic_effort` mechanism is documented, so `dynamic_effort_guidance()`
  returns nothing and `floor_raised` never fires for this model.
- **Model trait (official, model card and API guides):** a 552B-parameter
  causal encoder-decoder MoE that activates 8B parameters per token in
  prefill and 16B in decode; post-trained on large-scale synthesized agent
  tasks and evaluated by the vendor at its maximum reasoning setting with a
  1M-token context and `max_tokens` of at least 256K; thinking on by
  default, its chain of thought returned as `reasoning_content` and
  concatenated back into the context on every later tool turn; cache-hit
  input priced at a fiftieth of cache-miss input. The vendor's best coding
  numbers come from its own harness's *Minimal* preset — one persistent
  shell tool, a one-line persona ("You are a helpful software engineer
  assistant."), no runtime context, no compaction, effort `max`,
  `max_tokens` 256,000 — which scored above the Standard and PTC presets on
  DeepSWE (72.6 / 70.5 / 67.6) and Terminal-Bench 2.1 (90.6 / 85.8 / 85.8).
  The card's scaffold table says the same thing from the other side: across
  eight harnesses (Claude Code, Codex, OpenCode, Pi, mini-SWE-agent, and the
  three DSH presets) DeepSWE stays within 65.5–74.2 and Terminal-Bench 2.1
  within 84.1–90.6 — the model was trained to depend little on the harness,
  so scaffolding is not where its pass rate lives. Both facts are why the
  override below stays three sentences and why OMH's claims for this model
  are cost claims, not pass-rate claims. The card publishes no per-effort
  score or token table for the API rungs; a circulating "effort 25 / 50 /
  100" curve is unsourced until the vendor prints it, and #1463's `low`
  arm is how OMH measures it instead. Community harness notes
  (OpenRouter's listing) describe it as strongest on long-horizon tasks that
  run to completion across many steps — the same "keeps working" trait the
  Astra measurement found expensive on tasks a model will not pass.
- **What OMH injects (subagent):** the resolved contract in one sentence —
  thinking is on and the runtime returns earlier reasoning on every tool
  turn, so the visible reply carries the change and the stop rather than a
  restatement of reasoning the context already holds, and a turn that ends
  without a tool call carries its answer in the visible text, never only in
  reasoning (the vendor's harness adapter records that the live API rejects
  an assistant turn whose content is empty because the answer sat in the
  reasoning channel); the family's exact-literal-string edit rule, kept
  because the override replaces the family block rather than extending it;
  the blocker rule — when the evidence already in hand cannot satisfy a
  criterion, report the blocker from that evidence rather than widening the
  search, and leave a passed criterion closed; and the family block's
  closing rule, verbatim — make the smallest correct change, verify once,
  and stop. Four sentences; under the per-block ceiling. Nothing in it asks
  the model for more output: the first wording asked the reply to carry
  "the verification output" and the blocker report to carry "the observed
  output", and the measurement below found that those two phrases cost 25%
  more tokens than the family block for the same pass set, most of it
  re-running checks on tasks the model was not going to pass — the same
  "keeps working" signature the Astra round found, reached through a
  request for output rather than a request to continue.
- **What OMH injects (composer):** the visible composition is the ordered
  split, not a replay of planning already in context, and carries no
  synthetic thinking instructions; a unit routed to this model takes `low`,
  `high`, or `max` — its
  documented ladder; the vendor's own table turns `medium` and `xhigh` into
  `high`, so an undocumented rung is a rung the composer did not choose;
  validate once and stop.
- **Why each sentence:** reasoning passback → do not restate reasoning
  (the context already carries it, restating doubles the tokens); the
  long-horizon post-training → blocker report instead of widening the
  search; exact-string edit training → keep the family edit rule;
  three-rung ladder with a published mapping → name a documented rung on
  every unit. A composer sentence tying the fifty-to-one cache price to a
  byte-identical preamble was removed on 2026-10-04: it restated the
  universal prompt-cache discipline printed beside it, and
  `build_unit_prompt` already places the shared head first.
- **Routing:** took the slots DeepSeek V3.2 held — the reasoning-capable
  budget fall-through on `deep` at `high` and the DeepSeek entry on
  `unspecified-low` at `low` — and joined `simple-work` at `low` on
  2026-09-11. The 2026-10-13 table (owner decision) removed it from `deep`:
  a Flash budget model does not fit the strong tier, and Opus 5.5 and Kimi
  K3 carry that chain's cross-ecosystem fallback. It now sits at `low` in
  `unspecified-low` and `simple-work`, a documented rung. The chain alias is `deepseek-flash`, the id the vendor's API
  serves and Hermes forwards: the first-party endpoint rejects the
  versioned spelling `deepseek-v4.1-flash` with HTTP 400 (observed in the
  Hermes DeepSeek provider profile, 2026-09-11), so a shipped chain naming
  the versioned id would 400 out of the box on the one provider that is
  never a gateway. The versioned contract sits behind the pointer as the
  declared projection; a child observed under the gateway spelling
  `deepseek/deepseek-v4.1-flash` still labels `unspecified-low`
  because `mixture_category_for` projects an exact id onto its declared
  *pointer* aliases (`EXACT_CONTRACT_POINTER_ALIASES` — the same model at
  the contract's own mode and tier) as well as the other way round; a
  `-pro` / `-fast` / `-flex` variant never labels its base id. V3.2 left the shipped chains
  with the other superseded generations on 2026-09-11 and stays
  recognized, priced, and provider-mapped for a machine-level override. It
  does not head `deep`: that lane was Terra's by owner decision (#1313)
  was GPT-6 Sol's from 2026-09-23 and is GPT-6.1 Sol's since 2026-10-01, and no OMH measurement of this model
  exists yet to argue otherwise.
- **What the Hermes lane does with it (observed in the Hermes Agent source,
  v0.21.1 and origin/main, 2026-09-11 — recorded so nobody looks for an
  OMH fix):** Hermes forwards `reasoning_effort` from its own vocabulary,
  so a prepared `medium` reaches DeepSeek verbatim and the server maps it
  to `high` (there is no cheaper middle rung), `minimal` is sent as `low`,
  and `xhigh` is escalated by Hermes to `max` (DeepSeek itself would map
  `xhigh` to `high`); an unset effort is the server default `high`.
  Thinking-off is reachable only as `--reasoning none` / `agent.
  reasoning_effort: false` (sent as `thinking: disabled`); an effort-only
  "none" leaves thinking on. Hermes stores `reasoning_content` at write
  time and replays it on every assistant turn for DeepSeek routes, pads it
  where absent, and persists it across resume — the vendor's passback rule
  is met, and the cost consequence is that every tool turn re-sends all
  prior reasoning, mostly as cache hits. On the installed v0.21.1 a typed
  `deepseek-flash` is folded onto `deepseek-v4-flash`, which the vendor
  routes to V4.1 Flash; once the installed Hermes Agent moves to a
  post-2026-09-10 build, `deepseek-flash` is canonical. Hermes sends no
  `max_tokens` for DeepSeek unless the operator configures one, so the
  API's own 384K ceiling applies and the small-`max_tokens` trap (the
  reasoning trace spends the budget and the visible reply comes back
  empty) does not arise on the default route. Forced `tool_choice` with thinking on
  returns 400 on the first-party endpoint (community-observed); OMH never
  writes that shape.
- **Pricing:** the approximation table carries the peak-hour list rate,
  0.30 / 1.20 per MTok (cache-miss input / output), with the cache-hit rate
  as a 0.02 `APPROX_CACHE_READ_RATIO` row (0.006 per MTok). Every rate
  halves off-peak (outside 01:00–04:00 and 06:00–10:00 UTC, Monday through
  Friday); the table cannot express a clock, so peak is the honest
  approximation for a fanout wave, and the off-peak schedule stays in the
  contract. `deepseek-flash` inherits the row through the declared
  projection; an exact operator `model-prices.json` row wins first.
- **Measured (2026-09-13, subagent block; issue #1463):** five arms on
  `benchmarks/live-model-tools/v1`, evaluation split (30 instances, corpus
  digest `c4ea899a…`), `hermes_current_session` path through the `og`
  gateway's `deepseek/deepseek-flash` (served that morning; route receipt
  recorded first), omh 2.0.3, Hermes 0.21.1, arm order baseline → family →
  optimized → optimized at `low` → revised, all on one day. Pass rate tied
  within noise (15 / 15 / 16 / 17 / 14 of 30; McNemar p = 1.0 everywhere
  but optimized vs revised at 0.5, two discordant instances), with the
  variance confined to the two search templates. Tokens decided it: the
  original override cost 3,214,839 against the inherited `deepseek` block's
  2,564,954 (+21,663 per instance, bootstrap CI95 [+6,550, +42,944], more in
  24 / 30) and about the same as no calibration at all (3,360,197). Hermes'
  session rows put it at 462 tool calls / 277 API turns versus 434 / 244 for
  the family block, with the excess in `DIAGNOSTICS`, `BUGFIX` and `RENAME`:
  the model re-ran checks on tasks it was not going to pass and
  over-verified tasks it passed either way. "The verification output" and
  "with the observed output" were the two phrases with that reading, and the
  family's "verify once, and stop" was the sentence the override had dropped;
  the block above is the revision that removes both phrases and restores the
  rule: 2,327,037 tokens (−29,593 per instance against the original, CI95
  [−50,559, −12,636]; −7,931 against the family block, CI95 [−22,782,
  +3,395], indistinguishable), 368 tool calls, 230 API turns, 14 / 30. Per
  §8 that is the "revise" outcome: the resolved-contract sentences stay, the
  requests for output are gone, and the override now costs what the block it
  replaced costs. The `low` arm (the `unspecified-low` placement) bought no
  pass and an uncertain saving against `high` (−13,286 per instance, CI
  spans zero), so the ladder stays documented, not ranked. Full tables and
  the archive path in the benchmark README. Not measured: the composer block
  (no fanout in this harness), `max`, any claim beyond this corpus.
- **Source:** official (the DeepSeek-V4.1-Flash model card on Hugging Face,
  the API change log entry of 2026-09-10, the models-and-pricing page, the
  thinking-mode guide, and the `deepseek-ai/deepseek-harness` repository's
  tool catalog and DeepSeek adapter notes, read 2026-09-11); observed (the
  Hermes Agent DeepSeek provider profile, reasoning-effort table, and
  `reasoning_content` replay path, read the same day); community
  (OpenRouter's model listing for the gateway id and the long-horizon
  characterization, and the pi-family runtime / oh-my-pi / models.dev
  handling surveyed for divergence), each labeled as such above.
- **Persona language after an OMH skill load (2026-10-01):** on a Korean
  persona, `deepseek-v4.1-flash-ultrafast` flipped the reply after an OMH
  `skill_view` (fewer than 20 Hangul characters in its narration) in 16/20,
  26/30 and 24/30 samples over three runs, against 3/20, 5/30 and 5/30 with
  no skill; 15 of the 16 in the latest run were English narrations. Six
  prompt-level levers did not move it; `kimi-k3`, `deepseek-v4-pro` and
  `glm-5.3-ultrafast` held. Tables and the recommendation are in
  [Measured: a non-English persona's language after an OMH skill
  load](#measured-a-non-english-personas-language-after-an-omh-skill-load).

### `mistral` (Mistral Large / Medium)

- **Model trait:** efficiency-focused instruction followers. Mistral's own
  prompting guidance stresses explicit, literal instructions — the models do
  what is written, not what was implied — and their default register is
  concise. The risk profile is therefore under-specification and premature
  completion, not over-verification.
- **What OMH injects (subagent):** the stated criteria are the whole contract
  — check every one even when the change looks obviously right; concision is
  for the output, never for the evidence, and the single mandatory
  verification pass runs regardless of diff size.
- **What OMH injects (composer):** write unit prompts literally and
  completely — state every boundary, dependency, criterion, and verification
  command; never rely on the unit inferring an unstated invariant.
- **Source:** provider-published prompting guidance (explicit-instruction
  emphasis); authored fresh in the family-coverage change (#1051) — live
  benchmark validation pending.

### `llama` (open-weights Llama line)

- **Model trait:** the same model name means different capabilities on
  different hosts — tool-calling support, context window, quantization, and
  output limits are properties of the serving deployment, not the weights'
  name. Prompt shapes that assume one host's behavior silently fail on
  another.
- **What OMH injects (subagent):** treat the serving deployment as part of
  the contract — prove a capability with a real call before depending on it,
  fall back to explicit step-by-step tool use when structured calling is
  unreliable, and stop after one passing verification run.
- **What OMH injects (composer):** compose for the deployment, not the brand
  — confirm the served variant's tool contract and context budget before
  assigning units, and keep each unit prompt self-contained.
- **Source:** the open-weights serving reality (host-dependent capability is
  inherent to the distribution model); authored fresh in the family-coverage
  change (#1051) — live benchmark validation pending.

### `codestral` (Codestral coding line)

- **Model trait:** a code specialist built around completion and
  fill-in-the-middle work — strongest on concrete, file-scoped edits with
  small expected outputs, weakest on open-ended investigation and long
  synthesis.
- **What OMH injects (subagent):** work in file-scoped, concrete edits rather
  than open-ended investigation; keep each step's expected output small and
  explicit; prove the change with the repository's own check commands instead
  of prose explanation.
- **What OMH injects (composer):** route codestral units as narrow,
  file-scoped implementation slices with exact verification commands —
  investigation, review, and synthesis belong on a generalist lane.
- **Source:** provider-published specialization (completion/FIM-oriented
  coding model); authored fresh in the family-coverage change (#1051).
- **Measured (2026-09-29, subagent block on `codestral-2508`, block vs no
  block):** four arms on `benchmarks/live-model-tools/v1`, evaluation split
  (30 instances), `hermes_current_session` path, `codestral-2508` at `high`
  on Mistral's API, one arm at a time, same UTC day. A1 and A4 send no
  calibration block; A2 and A3 send the block above. Passes: A1 4 / 30,
  A2 3 / 30, A3 6 / 30, A4 1 / 30. Every pass is in `BUGFIX`, `SCALE` or
  `EXPLICIT`, and the model often leaves no valid answer file, so this model
  sits far below the corpus's 18 / 30 ceiling. The rule written before A1
  (A2 not below A1 on passes, and A2's extra tokens inside the A3 vs A2
  same-text drift) failed narrowly on both counts: 3 vs 4 passes, +4,712
  tokens per task against a drift of 4,420. The same block run twice had
  moved further (A2 to A3: 3 to 6 passes), so a baseline repeat, A4, was
  added with a pooled rule written before it ran; A4 then moved from A1's 4
  passes to 1. Pooled over both runs of each condition, the block passed
  9 / 60 against 5 / 60 and cost +1,607 tokens per task, bootstrap
  CI95 [−2,451, +5,788]: no measurable effect either way on this corpus, so
  the block is kept. Hermes sends `reasoning_effort` whenever an effort is
  set and Codestral rejects that field at any value, so every arm ran
  through a loopback proxy that removed only that field. Not measured: the
  composer block (no fanout in this harness), efforts below `high` (the
  block does not fire there), and any claim beyond this corpus. Records,
  manifests and analysis scripts are archived outside git and linked from
  the pull request that added this entry.

### `solar` (Upstage Solar Pro)

- **Model trait:** an efficiency-positioned instruction follower
  (depth-up-scaled architecture), not a long-horizon reasoner — it executes
  an explicit plan well and degrades when asked to derive one through
  extended deliberation.
- **What OMH injects (subagent):** follow the one explicit plan you were
  given in bounded steps instead of deriving a new one; report a missing
  constraint rather than inferring it; verify once against the stated
  criteria before stopping.
- **What OMH injects (composer):** put the depth in the composition, not the
  unit — give each solar unit one explicit plan with short bounded steps,
  exact criteria, and its verification command.
- **Source:** provider-published positioning (efficient depth-up-scaled
  model); authored fresh in the family-coverage change (#1052 added the
  prefix, #1051 set the calibration bar) — live benchmark validation pending.

### `generic` (mandatory fallback — every unknown id)

- **What OMH injects:** reserve extended reasoning for genuine ambiguity with
  materially different outcomes; decide once, act, verify once against the
  criteria, and stop — speed never skips the verification pass, and
  thoroughness never repeats it.
- **Why it exists:** an unknown family must never receive *weaker* discipline
  than a known one. The generic block carries the same core stop rules as
  every family block (a test asserts this), so putting any unlisted model in
  a chain still yields a disciplined lane — what it misses is only the
  counter to its own family-specific failure mode.

### When the calibration is (and is not) applied

`calibration_for_route()` appends the calibration block **only when the routed
reasoning effort is `high`, `xhigh`, or `max`** — an exact-model override
where one exists, the family block otherwise. The calibrations exist to
counter the over-verification inertia of high-effort routes; low-effort
routes do not exhibit that inertia, and every byte rides a prepared prompt
whose worst-case assembled size is policy-gated in tests
(`UNIT_PROMPT_MAX_BYTES = 8000` for the dispatch prompt; each redispatch
section has its own producer-derived `UNIT_PROMPT_APPEND_MAX_BYTES`) rather
than truncated at runtime.

## Throughput overlays (per family, ULW-facing)

`build_throughput_overlay()` in `src/coding/throughput_prompting.py` gives
every family the base rules — batch independent tool calls and reads in one
shot, keep dependency-bound work sequential. Three advanced modes are gated to
measured family/surface pairs:

- `gpt_sol_codex_handoff` applies to a `*-sol` model on the codex profile and
  adds single-eval-cell internal parallelism. The suffix is read off the
  contract model id, the identity the calibration lookup uses, so a projected
  id such as `gpt-6.1-sol-pro` and a dated snapshot such as
  `gpt-6.1-sol-2026-09-01` (both resolve to `gpt-6.1-sol`) get the overlay
  their calibration already gets.
- `gpt_hermes_ulw` applies to the gpt family on the hermes profile running
  ultrawork.
- `claude_code_handoff` applies to the claude family on the Claude Code
  profile. It adds advanced handoff and stop-condition rules but no eval
  strategy: the measured Claude Code surface exposed parallel tool use and
  agents, not a batchable eval cell.

The Claude gate comes from a 2026-08-23 counterbalanced six-pair live comparison
on Claude Fable 5 at medium effort. Both conditions received the identical
six-file independent-read task and base throughput rules; the advanced
condition added only `_ADVANCED_THROUGHPUT_RULES`. Both passed 6/6. Advanced
was faster in 4/6 pairs, with median wall time 13.28 s versus 15.82 s
(87.31 s versus 110.33 s total), and used 435,295 versus 490,034 reported
tokens. The narrow synthetic corpus does not establish general model
superiority, but it supports this exact prepared-guidance gate on the measured
Claude Code surface. The gate has not been re-measured on Fable 5.1; the
official migration guide reports that 5.1 batches fewer implied tool calls
per turn than Fable 5 in long agent loops, so the gate is stale in the
direction that favors re-running the same six-pair task at 5.1's default
`high` effort (and, for the first time, on the `hermes` profile). Until then,
claude on `hermes` keeps `parallel_handoff` and the batching counter rides the
calibration block only.

Kimi and Gemini stay on `parallel_handoff`. Credential-readiness probes on the
same host completed zero live pairs: Kimi (`opengateway` and `kimi-coding`)
and Gemini (`google`, `opencode`, and `github-copilot`) all reported
`credentials_not_configured` or `invalid_state`. Existing Kimi calibration
measurements do not compare these throughput rules, so they cannot justify an
advanced overlay. No eval strategy is claimed for either family. This is an
explicit measured availability null, not model-performance evidence; a future
gate requires a completed paired run on the intended execution surface.

## Routing, chains, and per-model bookkeeping

- **Mixture chains** — per-category ordered model chains (see the README
  model-routing section), user-editable via
  `~/.omh/routing/model-chains.json` (`mixture_chain_overrides/v1`).
- **Provider entitlements** — `~/.omh/routing/providers.json`
  (`provider_entitlements/v1`, written by the interactive `omh setup`)
  records which provider ids the machine holds and of what kind, plus the
  confirmed coding-CLI subscriptions. `effective_mixture_category_chains`
  reorders every chain so served entries lead (explicit route first, then a
  gateway serves everything, then a vendor serves the families that name
  it; unknown aliases are served). Reordering only — never removal — and
  the Maestro lane consumes the subscription entitlement separately.
- **Speed tiers are not a separate family** — `kimi-k3-ultrafast` and
  `glm-5.2-ultrafast` are the same base models served on OpenGateway's speed
  tier, and Z.ai serves its own `glm-5.3-highspeed` (gateways also use a
  `-fast` suffix): same weights, same family (`kimi-` / `glm-` prefix
  match), and therefore exactly the same calibration — only serving speed
  differs. A `-ultrafast`/`-highspeed`/`-fast` variant the chains do not
  name still projects onto its base model's category for HUD labels
  (`mixture_category_for`), so speed tiers never unlabel a lane. GLM 5.3
  Flash is the one lookalike that is NOT a tier — a separately trained
  smaller model — which is why the chains name `glm-5.3-flash` explicitly
  instead of relying on projection.
- **Cost approximation** — `APPROX_PRICE_PER_MTOK` in
  `src/plugin_bundle/omh/hermes_delegation.py` supplies `~$` estimates only
  when the host recorded no cost — no per-call figure at all, or Hermes' own
  `unknown` no-figure status (`agent/usage_pricing.py:549`, persisted into
  the usage table by `agent/turn_usage.py:236,257`), which says its pricing
  produced no amount rather than naming a billing outcome. That second case
  is what every child served through a custom gateway provider lands in. A
  row where the host DID record an outcome keeps its figure exactly,
  and models absent from the table show no approximation at all — a
  gateway child on an unpriced model still renders `$0.0000 (unknown)`,
  never a fabricated number. Cache reads are priced at a
  tenth of input unless `APPROX_CACHE_READ_RATIO` names the model: Claude
  Fable 5.1 lists $10 / $50 per MTok with cache reads at $0.25 (0.025x) and
  cache writes at $12.50 (5-minute TTL) / $20 (1-hour TTL); Opus 5 reads at
  the tenth; Opus 5.5 lists $4 / $20 with cache reads at $0.20 (0.05x) and
  cache writes at $5 / $8. Mythos 5.1 carries the Fable figure because its cache-read rate
  was open at launch — approximate, like every number in the table. DeepSeek
  V4.1 Flash reads at 0.02x (cache hit $0.006 against $0.30 miss, peak).
- **`max_tokens` is a failure signal, not a stop** — a unit whose final turn
  ended on `stop_reason: max_tokens` is a failed attempt: the output was cut
  mid-thought and nothing after the cut was verified. It is never a done
  unit, whatever the partial text claims.
- **Claude 5.1 compatibility risks that live on the Hermes side** —
  observed in the local Hermes Agent checkout on 2026-09-02 and recorded
  here so nobody looks for an OMH fix: forced `tool_choice` (`any` /
  `tool`) is a 400 on Fable 5.1 and Mythos 5.1; thinking cannot be disabled
  (Mythos 400s, Fable drops the flag), which is why `omh_delegate_route`
  refuses a no-thinking effort for the Fable tier and points at `low`; an
  unset effort is sent as `medium` by Hermes while the API default is
  `high`, which is why every Claude chain row declares its effort; a
  safety decline arrives as `stop_reason: refusal` on HTTP 200 and Hermes
  tries its configured `fallback_model` once; 5.1 turns can run many
  minutes against a fixed read timeout; and the preserved-thinking
  history-editing check rejects edited history for accounts created on or
  after 2026-08-31, which affects any client-side compaction that rewrites
  earlier turns. OMH can describe these in awareness and refuse the one
  route shape it writes itself; everything else is a Hermes-side change or
  an upstream proposal.
- **Fanout dispatch credentials** — `_PROVIDER_ENV` in
  `src/coding/hermes_child_dispatch.py` maps providers (anthropic, openai,
  gemini/google/vertex, qwen, deepseek, upstage, zai, opengateway,
  openrouter, nous, azure, bedrock, …) to the environment variables a
  dispatched child needs.

## Measured: the product, not the prompt prefix

Every calibration measurement above comes from
`benchmarks/live-model-tools/v1`, which sends a synthetic task to
`hermes --oneshot` with or without one calibration block in front. That
measures a prompt prefix. It cannot measure routing, the verification gate, or
a false completion, because none of them execute on that path.

`benchmarks/product-ab/v1` is the second lane, with a different question: the
same model, reached through OMH's coding delegation instead of through Hermes
alone, on a pinned corpus of this repository's own merged pull requests,
graded by those pull requests' own tests. It reports pass rate, cost per
passed task, wall clock per goal, and false-completion rate, paired per task,
with a bootstrap CI95 on each delta and an exact McNemar test on pass rate.

**No measured run has been published yet.** The lane, its digest-locked
corpus, and its offline pilot exist; the table lands in this section when a
run exists whose records this document can point at. Until then this section
is a pointer, not a result. What the lane measures, what it deliberately does
not, and how to reproduce it: `benchmarks/product-ab/v1/README.md`.

## Measured: a non-English persona's language after an OMH skill load

OMH skill bodies are English by repository rule. When the host loads one with
`skill_view`, the body enters the context as a tool result; the body measured
here is about 9KB. The model's next reply follows it. On a Korean
casual-register persona the effect was a language switch, not a register
change. The narration of the next reply came out in English, while the
persona's `SOUL.md` and every earlier reply were Korean. This section records
which models keep the persona's language at that point. Every number in it
was measured.

**Probe.** Each request is the real request from one session on the
owner's `miku` profile (Slack, Korean casual-register `SOUL.md`):
- the stored system prompt, with main's reply line;
- the stored history, through the final briefing;
- a Korean request to review a pull request;
- then either no skill (control), or an assistant
  `skill_view(name="omh-code-review")` followed by a tool row carrying the
  shipped body (A).

Every request used the same gateway route, with no temperature sent and
`tool_choice` set to `"none"`, so each reply is text.

**Metric.** A reply's narration is its text before the tool-call markup, with
code removed. A reply counts as *flipped* when its narration has fewer than
20 Hangul characters. A model is *skill-flip-prone* when its flip rate in A
exceeds its rate in control by 30 points or more. A cell with fewer than 15
usable replies is reported as insufficient.

The scripts, the rules (written into each script before it ran), and the raw
samples are in the owner's eval archive (`persona-residuals-2026-09-30/`),
not in git.

**The pre-registered splitter only knows DeepSeek's tool-call marker.** It
cuts the narration at `<｜DSML｜`, and it is not valid for models that write
tool calls in other markup. `glm-5.3-ultrafast` writes `<tool_call>…`. Under
the pre-registered splitter, its tool-call-only replies and its short Korean
lines both count as flipped. So the table gives two columns:
- the pre-registered *flipped* counts;
- *English narrations*: every flipped reply, cut at either marker and read
  by hand. A reply counts here when its narration is written in English. A
  Korean sentence that uses English words does not count.

| Model | Control flipped (pre-registered) | A flipped (pre-registered) | A − control | Control English narrations | A English narrations | Reading |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `deepseek-v4.1-flash-ultrafast` | 3/20 | 16/20 | +65 pt | 2/20 | 15/20 | skill-flip-prone |
| `kimi-k3` | 0/20 | 0/19 | 0 pt | 0/20 | 0/19 | holds |
| `deepseek-v4-pro` | 2/20 | 1/17 | −4 pt | 0/20 | 1/17 | holds |
| `glm-5.3-ultrafast` | 8/20 | 7/20 | −5 pt | 0/20 | 0/20 | holds |
| `deepseek-flash` | 0/20 | none usable | n/a | 0/20 | none usable | insufficient: every A request returned HTTP 400 (cause not diagnosed), so the Flash model without the ultrafast tier is unmeasured |

- **Flips that are not English.** Some pre-registered flips are something
  else:
  - `glm-5.3-ultrafast`: its 8 control flips are 7 Korean lines and 1
    tool-call-only reply; its 7 A flips are 3 Korean lines and 4
    tool-call-only replies. The Korean lines are short, or the code-span rule
    ran into the tool-call markup and cut their Hangul count.
  - `deepseek-v4-pro`: both control flips are short Korean lines.
  - `deepseek-v4.1-flash-ultrafast`: 1 control flip and 1 A flip are short
    Korean lines, the A one a Korean sentence with English words.
- **Empty narrations.** These are excluded from the counts above: one for
  `kimi-k3` and three for `deepseek-v4-pro`. The 5 tool-call-only replies
  from `glm-5.3-ultrafast` are not excluded. The splitter does not see their
  markup, so it counts them as flipped instead.
- **Earlier runs.** Two earlier n=30 runs on `deepseek-v4.1-flash-ultrafast`
  give the same picture: control 5/30 against A 26/30 flipped, and control
  5/30 against A 24/30.

**What did not move it.** Six prompt-level levers were each tested against A
on `deepseek-v4.1-flash-ultrafast`, at n=30, under one rule written before
the runs: keep a lever only if it beats A with one-sided Fisher p <= 0.05.
None passed. The counts are pre-registered flips (fewer than 20 Hangul
characters), not English-only counts. In the second run, 4 of A's 24 flips
are short Korean sentences with English words, not English narrations.

| Lever | Flipped (A in the same run) | p |
| --- | --- | ---: |
| the persona sentence moved from the body's tail to the line under the title | 20/30 (26/30) | 0.0626 |
| a persona line added as the tool result's last field | 27/29 (26/30) | 0.8951 |
| both of the above | 24/30 (26/30) | 0.3653 |
| a line naming the language the persona has been replying in, prepended to the body | 27/30 (24/30) | 0.9273 |
| the same named line as the result's last field | 22/30 (24/30) | 0.3805 |
| the title move plus the prepended named line | 23/30 (24/30) | 0.5000 |

- **Where the named line came from.** A script detector read the persona's
  own earlier replies and named Korean. It is not a language OMH chose.
- **Chinese drift, a separate null.** An A/B at n=40 on a mid-session probe
  found that a sentence asking to hold the language across tool output does
  not reduce this model's occasional switch into Chinese. That rate was 2/40
  on main and 4/40 with the sentence.
- **What the model had read before the live switch.** A separate check, not
  part of `script_drift_ab.py`, counted Han and Kana characters
  (`[一-鿿぀-ヿ]`) in three places:
  - the stored session rows before the switch (messages 48856..48891, tool
    rows and tool calls included): none;
  - the tool schemas the probe sends: none;
  - the stored system prompt: 6, all in one skill-index description,
    `(信息图, 可视化)`, which belongs to a non-OMH skill.

**Recommendation.** For a persona whose `SOUL.md` sets a language other than
English, run the main chat model on one that keeps that language after an OMH
skill load.
- **Measured to hold:** `kimi-k3`, `deepseek-v4-pro`, and `glm-5.3-ultrafast`
  (0/20 English narrations in both arms on inspection).
- **Measured not to hold:** `deepseek-v4.1-flash-ultrafast`.
- **Unmeasured:** `deepseek-flash` without the ultrafast tier.

This is a model choice for the host and its operator, not a calibration OMH
can inject. The host's own chat turns have no per-model OMH surface: the
calibration tables above reach coding unit prompts only. The wording levers
did not change the measured rate either. The evidence is one persona, one
request, and one skill body, at n=20 per cell. That is a direction to
choose models by, not a guarantee for another persona or skill.

## Coverage matrix and known gaps

| Family | Recognized | Calibrated (both tables) | Status |
| --- | --- | --- | --- |
| `gpt`, `claude`, `gemini`, `grok`, `kimi`, `glm`, `qwen`, `deepseek`, `mistral`, `llama`, `codestral`, `solar` | yes | yes | full guidance, provenance above (#1051/#1052 closed the last four) |
| `gpt-6-astra` (exact-model override) | yes → `gpt` | yes, both override tables, resolved before the family block | exact documented contract plus counters for the four official traits; paired measurement is the named follow-up |
| five declared Astra mode/tier aliases | yes → `gpt` | yes, inherited from canonical `gpt-6-astra` | bounded declared inheritance for contract, effort, calibration, provider/category metadata, and price; unknown suffixes remain missing |
| `deepseek-v4.1-flash` (exact-model override) | yes → `deepseek` | yes, both override tables, resolved before the family block | exact documented contract (three-rung ladder, no floor) plus stop-shaped counters for the documented traits; the family-vs-optimized pair is the named follow-up, blocked on a served route |
| `deepseek-flash` (declared pointer alias) | yes → `deepseek` | yes, inherited from canonical `deepseek-v4.1-flash` | the vendor's moving "current Flash" id, declared with a read date; `deepseek-v4-flash`, `deepseek-v4-pro`, and every other DeepSeek id keep the family block |
| `gpt-6.1-sol` (exact-model override) | yes → `gpt` | yes, both override tables (Astra's wording, byte for byte), resolved before the family block | exact documented contract (Astra's `low`-floor ladder, no `none`; the Codex client's ladder recorded beside it without the Codex-only `ultra`); `gpt-6.1-sol-pro` inherits through a declared projection; editorial for 6.1 Sol, the `family` vs `optimized` pair is the named follow-up |
| `gpt-6-sol` (exact contract, no exact calibration; retired from the shipped chains 2026-10-01) | yes → `gpt` | yes, through the family block | exact documented contract (the API `none`-to-`max` ladder; the Codex client's ladder recorded beside it without `none` and without the Codex-only `ultra`); no exact counter: while it held `deep@high` and `main` (until 2026-10-01) those slots reached the calibrated tiers, and none was added because the Codex Sol prompt's keep-working sentence is not importable and no `family` vs `optimized` pair has run; the three generation pairs are the named follow-up |
| `gpt-6-luna`, `claude-opus-5-5` (exact contracts, no exact calibration) | yes → `gpt` / `claude` | yes, through the family block | exact documented contracts (Luna's `none`-to-`max` ladder; Opus 5.5's always-on thinking, forced-`tool_choice` 400, and 0.05x cache reads); no exact counter because neither shipped placement reaches the high-effort tier on the subagent side and the Opus composer block is kept byte-stable per the vendor's Opus 5.5 prompting guide; the old-vs-new generation pairs are the named follow-up |
| `gpt-6.1-terra` (exact contract, no exact calibration) | yes → `gpt` | yes, through the family block | exact documented contract (Luna's `none`-to-`max` ladder, `-pro` projection, 5% cache reads); recognized, priced, and provider-mapped but in no shipped chain; Hermes' Codex route clamps its `max` to `xhigh` until Hermes adds the id to its GPT-6 tier tables |
| `gpt-6-cyber` (exact-model override, access-gated) | yes → `gpt` | yes, both override tables (Astra's wording, byte for byte), resolved before the family block | exact documented contract (its own limits, endpoints, and price; Astra's `low`-floor ladder inherited and labeled `effort_ladder_source`); Daybreak Red only, in no shipped chain; editorial and unmeasured, because no route this repo can reach serves it |
| `gpt-5.6-cyber`, `gpt-6-rosalind` (no contract, access-gated) | yes → `gpt` | yes, through the family block | priced, provider-mapped, and labeled, but neither documents a ladder, so an effort passes through as for any contract-less `gpt` id; in no shipped chain |
| `deepseek-v4.1-flash-1017` (declared alias, relay spelling) | yes → `deepseek` | yes, inherited from canonical `deepseek-v4.1-flash` | the snapshot `deepseek-flash` has served since 2026-10-17, under a spelling DeepSeek itself does not accept; keeps the pointer's category label, not its display label, and the portfolio report reads it as `unmeasured` because it has no chain placement of its own |
| `openai-gpt-`, `anthropic-claude-` (design-qualified aliases) | yes → `gpt` / `claude` | yes, through the design family | concrete models.dev/OpenCode serving ids carry these sub-prefixes; their catalog `base_model` fields establish the underlying design family |
| other `openai-`, `anthropic-` vendor-qualified ids | recognized as model targets, family `unknown` | no → `generic` | vendor qualification alone does not establish a design; O-series, image, and emerging ids remain uncalibrated |
| `kimi-k3.1-pro`, `kimi-k3.1-pro-highspeed` (exact contracts, no exact calibration) | yes → `kimi` | yes, through the family block | exact documented contracts (three-rung `low`/`high`/`max` ladder with `max` as default, every other rung raised on record; Highspeed has its own rate card); K3.1 Pro holds every former Kimi K3 slot since 2026-10-24, Highspeed is recognition-only; the K3-vs-K3.1 pair is the named follow-up, blocked on a served route |
| `gemini-4-argon` (exact contract, no exact calibration) | yes → `gemini` | yes, through the family block | exact documented contract (`low`/`medium`/`high` ladder with `medium` as default and no off switch; `off` and `minimal` raised on record, rungs above `high` passed through); holds every former Gemini 3.1 Pro slot since 2026-10-28; the 3.1-Pro-vs-Argon pair is the named follow-up, blocked on a served route |
| `jev` (non-generative) | yes | no, and none applies → no calibration pair | recognized, contracted (`jev-1.13.0`, with `jev-latest` and `jev-preview` as declared aliases), priced with a free output side, and in no chain by decision; the route answers `model_refused` and both chain editors refuse it. The coverage audit reports `effort`, `category_projection`, and `provider_eligibility` as `missing`, which is the honest reading for a model with no effort parameter and no chain membership — greening any of them would need an invented rung or an invented chain entry |
| `minimax` | yes | no → `generic` | prefix landed in #1304 (`MiniMax-M3`, released 2026-05-31, and `MiniMax-M2.7`, 2026-03-18, per minimax.io release notes and the platform.minimax.io model list); the calibration pair waits on an observed failure mode or a provider-stated characteristic worth countering |
| emerging families | no → `unknown` | no → `generic` | add a prefix and a calibration pair when one lands (the #1051/#1052 pattern) |

Gaps close by evidence, not by copywriting: a new calibration entry needs an
observed failure mode (or provider-stated characteristic) worth countering,
lands in both tables at once (parity-gated), and states its reason and source
in this document.

## Portfolio qualification

`omh coding model-portfolio-qualification` reports the complete supplied
inventory as `model_portfolio_qualification/v1`. It does not rank models,
change chains, infer entitlement, or call a provider. These states differ:

| State | Meaning | Example |
| --- | --- | --- |
| Supported | Present in the caller's accepted inventory, not necessarily recognized or usable on this account | `minimax/minimax-m3` in the seed fixture |
| Optimized | Model-specific guidance has documented trait-to-counter provenance; calibration presence alone does not prove improvement | `gpt-6-astra` has an exact calibration pair; consult its measurement stage separately |
| Eligible | A reviewed decision permits a particular model-and-role placement; it does not imply selection or global promotion | `kimi-k3.1-pro` is eligible for `architect`, even behind another chain head |
| Recommended | An eligible placement actually appears in a shipped chain | `deepseek-flash` in `unspecified-low`, with its explicit versioned pointer relationship |
| Excluded | A reviewed decision deliberately withholds placement and records its scope and evidence | `claude-fable-5` is superseded by `claude-fable-5-1` |

New discoveries default to `unmeasured`, even if their family is recognized
or an exact contract is inherited. Family coverage describes which table
will resolve, not whether that generation has been optimized: `qwen3.8-*`
now resolves to Qwen guidance, but remains unmeasured for placement. The
existing Qwen guidance describes Qwen3-Coder; recognizing another minor
version does not establish that it shares Coder's non-thinking contract.

The independent decision registry in
`src/coding/model_portfolio_qualification.py` records existing owner-approved
editorial placements as `editorial_not_measured`, not
`observed_role_evaluation`. It approves model-and-role pairs, not every role
for a model. The guard walks categories, main-role suggestions, domain
placements, and last resort; adding an unmeasured or excluded candidate, or
an unapproved role for an existing candidate, fails. No new recommendations
are introduced by this report. New placements require role-specific observed
evidence (or an evidenced provider-diversity fallback) and a placement reason;
an arbitrary new registry entry is not a substitute for review.

MiniMax M3, MiMo V2.5 Pro, HY4 Preview, HY3, Step 3.7 Flash, Nemotron 3 Super,
and Fugu Ultra have explicit qualification holds pointing to the inventory
and the absent dedicated calibration pair. Their coverage reads
`intentional_exclusion`, their underlying resolution remains visible, and
their disposition stays `unmeasured`. A lack of research is not evidence of
poor quality, expensive execution, unreliable tools, or runtime rejection.
Holds still block required qualification. Other newly discovered ids receive
an unmeasured row without requiring a registry edit. No paid evaluation runs
implicitly; it needs separate approval through the onboarding measurement
recipe. Quality, tool reliability, latency, and cost evidence remain separate;
a documented list price is not a measured efficiency advantage.

The closed dispositions also support `eligible_not_selected`,
`excluded_quality_dominated`, `excluded_efficiency_dominated`,
`excluded_tool_unreliable`, `excluded_runtime_incompatible`, and
`excluded_superseded`. Only use a dominance disposition when its cited
comparison establishes that dimension; this pass fabricates none. Caller
`--intentional-exclusion ID=REASON` declares a runtime-contract exclusion,
not an observed model failure. Retirements carry successor, scope, and owner
decision date. GPT-5.6 Sol's 2026-09-11 frontier-slot retirement was widened
on 2026-09-23 to every shipped chain (successor `gpt-6-sol`), and GPT-5.6
Terra was retired the same day to the same successor. GPT-6 Sol was retired
from every shipped chain on 2026-10-01 (successor `gpt-6.1-sol`). Older ids stay
routable, priced, and provider-mapped.

The report imports the contract audit's inventory parser, unions `models`,
`available_models`, and discovery observations, and preserves case-variant
identities in `aliases`. Provider-qualified and bare ids remain separate
inventory rows. Served aliases are a separate field: only declared
same-mode/tier pointers share standing. Dotted `claude-fable-5.1` does not
inherit dashed `claude-fable-5-1` by similarity; Astra's unknown suffixes
stay missing. Dated snapshots retain their original projection provenance
under `declared_inheritance` coverage. DeepSeek's pointer read boundary is
explicit, not a second contract.

Supply `read_date` as an ISO calendar date when known; otherwise the report
returns null rather than inventing freshness. No current timestamp enters
the comparison or its stable JSON digest. Required ids absent from inventory
appear in `summary.required_gaps`, not invented inventory rows. Required
unmeasured rows block with exit 1; advisory gaps return 0; invalid or oversized
input returns 2. Optimization stages cite shipped metadata, research
references, calibration, placement, price, and measurement follow-up without
claiming that a cited recipe has run. See
[model onboarding](docs/MODEL-ONBOARDING.md#portfolio-qualification) for the CLI loop.

### Issue #1515 QA adjudication

The [issue contract](https://github.com/rlaope/oh-my-hermes/issues/1515),
not a stronger design-brief expectation, governs these boundaries:

- **Qwen calibration (AC6):** "`qwen3.8-*` IDs no longer fall through to
  generic handling" applies to both calibration resolvers. The dotted-minor
  alias already reaches Qwen composition guidance and the high-effort block
  through the recorded route in `fanout prepare` -> `build_unit_prompt`.
  `coding delegate` prepares a different handoff and does not invoke that unit
  renderer; absence of the unit block there is not a failed family lookup.
  Regression coverage prepares the actual fanout contract through the CLI,
  renders its unit, and compares both blocks with the shipped tables, with
  malformed-spelling negative controls. No exact contract or measured
  generation-specific optimization is inferred.
- **Unresearched families (AC7):** "MiniMax and every currently generic or
  newly discovered family receive either dedicated calibration or an explicit
  evidence-backed exclusion" must be read with "unmeasured, which must not be
  confused with either recommended or rejected" and "if it cannot run, the
  model remains `unmeasured`." The seven explicit holds above exclude
  qualification and recommendation, not model usability or quality. Their
  reasons and evidence pointers identify the missing calibration pair;
  required qualification still blocks. No `excluded_*` disposition in the
  issue's closed vocabulary means "never measured". Requiring one here would
  fabricate a failure finding. Tests retain generic resolution, explicit
  holds, empty eligibility, and absent measurement evidence.
- **Dominance and retirement (AC13):** "Models dominated on quality, tool
  reliability, latency, or cost are recorded with an explicit exclusion
  reason" does not require a nonzero dominance count. The issue also excludes
  "Fabricating quality or efficiency conclusions when live evaluation has
  not run." The seed inventory therefore has zero measured dominance
  exclusions; Astra list-price tiers alone do not establish dominance.
  Reviewable editorial retirements already exist for Fable 5 and GLM 5.2 in
  that inventory, with the owner-decision evidence in onboarding section 4.
  GPT-5.6 Sol's frontier-slot retirement was widened to every shipped chain
  on 2026-09-23, when GPT-6 Sol took its last-resort slot; GPT-6.1 Sol took
  that slot from GPT-6 Sol on 2026-10-01.
  Tests pin zero unsupported dominance findings separately from those honest,
  evidence-linked retirement decisions.

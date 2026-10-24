---
name: model-onboarding
description: >-
  Onboard a new model generation or sibling into oh-my-hermes: probe router
  recognition, research the official contract, write trait-to-counter
  calibration, place routing in both lanes, price from documented list only,
  gate machine config on a served route, prove with the gates, close with a
  benchmark pair. Use when a model family ships a new generation (for example
  "Fable 5.1 is out", "GLM 5.4 shipped", "onboard new model", "add model to
  chains").
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
---

# Model onboarding

The procedure lives in [`docs/MODEL-ONBOARDING.md`](../../../docs/MODEL-ONBOARDING.md).
Read that file and follow it in order.

It is kept there rather than here because Codex, Hermes handoffs, and generic
executor profiles run the same loop, and `AGENTS.md` requires that no single
executor own a shared surface. This file exists so the loop is reachable as
`/model-onboarding`; it holds no rules of its own.

Start by reading, in this order:

```sh
cat docs/MODEL-ONBOARDING.md
cat MODEL_OPTI.md
```

Nine things the loop gets wrong most often:

- Recognition before research. Probe every served id and every bare chat
  name with `omh coding model-route` first; a `model_family` of `unknown`
  means the calibration never attaches. Probe the dated snapshot form too
  (`<id>-YYYY-MM-DD`): some providers serve only that spelling, and it must
  resolve the base's contract, chain position, price, and HUD label through
  `dated_snapshot_base()` rather than falling to generic.
- The chain names the id the vendor's API serves, not the model card's
  spelling. Read the Hermes provider profile for the family before choosing
  the alias — DeepSeek serves `deepseek-flash` and 400s `deepseek-v4.1-flash`;
  the versioned contract sits behind the pointer as a declared projection
  and in `EXACT_CONTRACT_POINTER_ALIASES`.
- Research runs as four parallel read-only lanes (official docs, Hermes
  runtime source, the vendor's own harness, community harnesses), each a
  labeled dossier under `.omc/research/`; the Hermes lane is the one that
  shows what the wire carries (id folding, effort overrides, passback).
- Chains move as a set. The Hermes-lane table, its plugin mirror, the
  Maestro-lane table, the `model-setup` skill text, the public docs and site
  pages, and the pinned-chain tests all name the old id (the "Files that move
  together" table in the procedure lists them). `docs/INSTALLATION.md`'s chain
  table is generated (`docs chain-table`); the two site pages are edited by
  hand; the READMEs carry no table. `git grep` the old id across the whole
  tree and move every site in the same commit. Superseded generations leave
  the shipped chains and join the recognition-only list; pins hide in
  fixtures, so start the full suite in the background at the chain edit.
- Machine config stays provider-neutral. Chains name aliases; the
  provider row is a separate concern in `model-providers.json`. Place the id
  with `omh model-chains set`, never by hand-editing the JSON; an operator
  may keep an older generation behind it there, the shipped table does not.
- Served is not released. Prove the route with one `hermes --oneshot` call
  and read the usage file (`model`, `provider`, `cost_status`) before any
  measurement or placement; gateways want the vendor-prefixed id.
- The override is measured against the block it replaced, on cost. Run the
  `family` arm next to `baseline` and `optimized`; expect pass rate to tie
  and read the paired token delta, tool calls, and turns. Same pass with
  more tokens on the tasks it fails is a sentence that pushes — cut it.
- A routing signal is only as good as the tier's chain head. Measure the
  head on the request class it will receive before shipping the signal,
  and name the head in every routing claim.
- A separate reviewer lane reads the diff before the commit. The DeepSeek
  round's reviewer caught a reverse projection that let `-pro` / `-fast` /
  `-flex` aliases label their base id; self-review did not.

Arguments pass through verbatim: the model ids as served (for example
`claude-fable-5-1 claude-mythos-5-1`).

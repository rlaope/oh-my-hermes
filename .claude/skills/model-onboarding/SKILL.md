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

Six things the loop gets wrong most often:

- Recognition before research. Probe every served id and every bare chat
  name with `omh coding model-route` first; a `model_family` of `unknown`
  means the calibration never attaches.
- Chains move as a set. The Hermes-lane table, its plugin mirror, the
  Maestro-lane table, the `model-setup` skill text, seven public doc surfaces,
  the release budget note, and the pinned-chain tests all name the old id;
  grep for it and move every site in the same commit.
- Machine config stays provider-neutral. Chains name aliases; the
  provider row is a separate concern in `model-providers.json`. Place the id
  with `omh model-chains set`, never by hand-editing the JSON, and let the
  older generation stay behind it as fall-through.
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

Arguments pass through verbatim: the model ids as served (for example
`claude-fable-5-1 claude-mythos-5-1`).

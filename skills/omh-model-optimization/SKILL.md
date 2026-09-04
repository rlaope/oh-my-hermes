---
name: "omh-model-optimization"
description: "[omh] OMH Model Optimization workflow: when a model family ships a new generation or changes its serving contract, walk the recognition, research, calibration, routing, and measurement process that keeps model handling honest and current. Use when the user says: model-optimization, model optimization, optimize for model, onboard new model, calibrate new model, new model calibration, model calibration."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, optimization]
    category: optimization
    phase: model-onboarding
    role: tracker
    quality_tier: evidence-gated
---

# Model Optimization

This is a Hermes-native `model-optimization` workflow skill.

## Why This Exists

`model-optimization` exists so a new model release triggers one repeatable, evidence-ordered process instead of ad-hoc edits: recognition proves what the router sees, official-first research separates contracts from folklore, trait-to-counter keeps calibrations concrete, and the measurement close keeps them honest.

## Do Not Use When

- The user wants their own machine's model routing configured or providers connected; use `model-setup`.
- The goal is measurable performance of an application or system, not model handling; use `performance-goal` or `ultraperf`.
- The user wants benchmark-superiority or provider-readiness claims without measurements.

## Examples

Good example:

- Prompt: GLM 5.3 and 5.3 Flash just shipped; check what we should optimize for them.
- Expected behavior: Probe recognition for both ids, verify family coverage, research the official thinking/tool contract plus community harness handling with labeled sources, draft version-aware trait-to-counter calibration, propose chain placement distinguishing the Flash sibling from the highspeed tier, and name the benchmark pair as the measurement close.
- Why: A new generation of a known family needs the whole process, not just a chain edit.

Bad example:

- Prompt: Just say the new model is the best and route everything to it.
- Expected behavior: Refuse the superiority claim, run the process, and place routing only with owner-approved config or repo changes backed by labeled sources.
- Why: Unmeasured superiority claims and blanket rerouting are exactly what the process exists to prevent.

## Completion Checklist

- Recognition probe output exists for every new id, and the family label is the expected one.
- Every research finding is labeled official or community with its source kept.
- The calibration draft counters named traits and marks version-specific rules as such.
- Routing and pricing changes name their surface (operator config vs repo change) and their approval state.
- The measurement plan names the benchmark pair, or the recorded reason none can run, and the worse-measured-calibration rule is stated.

## Recovery Notes

- If official docs and community reports conflict, ship the official contract and record the community finding as an unconfirmed counter-signal.
- If the model cannot be measured (no served route, no credentials), ship the calibration with its research provenance and record the measurement as the named follow-up.
- If a later measurement shows the calibration worse than baseline, revise or remove it in the same change that reports the number.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `best-practice-research`, `autoresearch-goal`, `model-optimization`, `inference-serving`, `+17 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when a model or family is new to OMH, shipped a new generation, or changed its serving contract, and the operator wants recognition, calibration, routing, pricing, and docs checked and strengthened for it through the fixed onboarding process.

    Strong routing signals: `model-optimization`, `model optimization`, `optimize for model`, `onboard new model`, `calibrate new model`, `new model calibration`, `model calibration`

## Catalog Metadata

Category: `optimization`
Phase: `model-onboarding`
Hermes role: `tracker`
Quality tier: `evidence-gated`
Reasoning demand: `heavy`

Quality bar:

- Probe recognition before researching: `omh coding model-route --executor hermes --model <id> --effort <effort> --role implementation --json` shows the family label the routing engine assigns; an unknown or generic label means the family prefix table needs a row before any calibration can attach.
- Check calibration coverage second: the MODEL_OPTI.md coverage matrix plus both calibration tables (subagent high-effort and composer). A recognized family with no calibration is a tracked gap, not an error.
- Research official docs first — release notes, thinking/tool-calling contract, context and output limits, pricing, speed tiers — then how other open-source harnesses handle the model. Label every finding official or community and keep the source; a community claim never overrides an official contract.
- Author calibration as trait-to-counter: name the model's documented or observed behavior, then state the concrete counter-behavior, version-aware where generations differ. Do not restate universal protocol rules inside a family entry.
- Distinguish speed tiers from separate models before touching routing: a speed tier is the same weights served faster and projects onto its base model; a separately trained sibling is its own chain entry. Place routing through config surfaces first (omh model-chains set, omh coding category-maestro set); shipped editorial defaults change only as a repo change with explicit owner approval, and existing entries stay as fall-through unless the owner says replace.
- Record cost only from documented list pricing; a model or tier without a documented price gets no entry — absence renders no estimate, never a fabricated number.
- Close with measurement: a calibration ships measurable, and the baseline-vs-optimized benchmark pair is the named follow-up when no served route exists yet. A calibration that measures worse than baseline is revised or removed in the same change that reports the number, never kept.

Handoff policy:

Keep recognition probes, research synthesis, calibration drafting, and the process checklist in Hermes. Machine-local routing placement is a config edit the operator approves; repository changes (prefix table rows, calibration text, shipped chain defaults, docs) are coding work for the selected executor lane. A drafted calibration or prepared route is prepared_not_observed, never execution or benchmark evidence.

Required inputs:

- the model id(s) as served, and the provider or gateway serving them
- recognition probe output for each id
- official release/contract documentation, with community harness findings labeled separately

Expected outputs:

- recognition and calibration coverage verdict for the family
- trait-to-counter calibration draft (or a no-change verdict with reasons)
- routing/pricing placement plan naming config surfaces vs repo changes
- measurement plan naming the benchmark pair or the reason none can run yet

Artifact expectations:

- metadata-only runtime record when a wrapper or shell is available

Safety rules:

- Do not imply hidden Hermes runtime behavior.
- Use the smallest verification that can prove the claim.

## Runtime Evidence

Preferred harness for this skill: `research`.

```sh
omh runtime record --skill model-optimization --harness research --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.

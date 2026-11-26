# Model Optimization

Load this on-demand contract after the compact `model-optimization` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user wants their own machine's model routing configured or providers connected; use `omh-model-setup`.
- The goal is measurable performance of an application or system, not model handling; use `ulw-perf`.
- The user wants benchmark-superiority or provider-readiness claims without measurements; decline the claim and offer the measurement plan from this skill's checklist.
- Making a model's weights smaller or cheaper by quantization, pruning or distillation into a student; use `omh-model-compression`.
- Serving a model behind an endpoint, or benchmarking that endpoint; use `omh-inference-serving`.
- Training a model on your own data with SFT, DPO or a LoRA adapter; use `omh-model-finetuning`.

## Examples

Good example:

- Prompt: GLM 5.3 and 5.3 Flash just shipped; check what we should optimize for them.
- Expected behavior: Probe recognition for both ids, verify family coverage, research the official thinking/tool contract plus community harness handling with labeled sources, draft version-aware trait-to-counter calibration, propose chain placement distinguishing the Flash sibling from the highspeed tier, and name the benchmark pair as the measurement close.
- Why: A new generation of a known family needs the whole process, not just a chain edit.

Bad example:

- Prompt: Just say the new model is the best and route everything to it.
- Expected behavior: Refuse the superiority claim, run the process, and place routing only with owner-approved config or repo changes backed by labeled sources.
- Why: Unmeasured superiority claims and blanket rerouting are exactly what the process exists to prevent.

## Full Input, Output, and Artifact Expectations

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

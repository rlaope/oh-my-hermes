# Inference Serving

Load this on-demand contract after the compact `inference-serving` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- A new model generation needs recognition, calibration, routing, and pricing onboarding; use `omh-model-optimization`.
- The user wants their own machine's model routing or providers configured; use `omh-model-setup`.
- The question is whether a coding runtime/executor can run at all; use `omh-executor-runtime-readiness`.
- The goal is application or system performance rather than the serving endpoint itself; use `ulw-perf`.
- The ask is producing the smaller weights -- GPTQ or AWQ calibration, pruning, or a distilled student -- and proving they still do the task; use `omh-model-compression`.

## Examples

Good example:

- Prompt: Serve Qwen on our two A100s for the team and tell me if prefix caching is worth turning on.
- Expected behavior: Engine verdict (vLLM, TP dividing the head counts), quantization check, the k8s or docker runbook with its gates and verification, then the prefix-cache A/B protocol with hit-rate assumptions recorded - numbers only from observed runs.
- Why: Serving plus a measured tuning question is exactly the decide-deploy-measure process this workflow owns.

Bad example:

- Prompt: Just tell me the endpoint is fast enough, we already know it works.
- Expected behavior: Refuse the unmeasured claim; run the benchmark protocol against the stated SLO or report the capacity question as unanswered.
- Why: A fast-enough claim without a load shape and observed results is the folklore this skill replaces.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the model id(s) and where the weights live (HF id, local path, gated or not)
- the hardware truth: GPUs and VRAM, or CPU/Apple Silicon, and single- vs multi-user load
- the delivery surface: docker, Kubernetes, or bare process, and the port/ingress constraints
- for benchmarks: the SLO (TTFT/TPOT bounds) and the load shape the number must represent

Expected outputs:

- engine and quantization verdict from the decision tables, with the rejected options named
- deployment runbook with its gates (secret, existing-deployment), verification commands, and the four-places port invariant
- benchmark plan naming metrics, load shape, dataset, and metadata to save
- observed-only status: what ran, what was verified, what stays prepared

Artifact expectations:

- serving decision and runbook per `omh-inference-serving/references/serving-runbooks.md`
- benchmark protocol per `omh-inference-serving/references/serving-bench.md`
- result files with metadata only after observed runs
- optional offline VRAM/KV-cache/TP budget via `toolkit/scripts/vram_kv_calc.py` (`vram_kv_budget/v1`, calculated estimate only)

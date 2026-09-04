---
name: "omh-inference-serving"
description: "[omh] OMH Inference Serving workflow: choose the serving engine and quantization from decision tables, prepare deployment as an idempotent runbook with observed-only verification, and measure the endpoint with the standard TTFT/TPOT/goodput protocol. Use when the user says: inference-serving, inference serving, serve this model, serve the model, model serving, serving endpoint, vllm, llama.cpp."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: inference-serving
    role: operator
    quality_tier: observed-command-gated
---

# Inference Serving

This is a Hermes-native `inference-serving` workflow skill.

## Why This Exists

`inference-serving` exists so serving an LLM runs as one decided, gated, measured process instead of scattered flag folklore: the engine choice is a table, the deployment is an idempotent runbook whose only completion evidence is the observed verification, and the benchmark speaks the standard metric vocabulary.

## Do Not Use When

- A new model generation needs recognition, calibration, routing, and pricing onboarding; use `model-optimization`.
- The user wants their own machine's model routing or providers configured; use `model-setup`.
- The question is whether a coding runtime/executor can run at all; use `executor-runtime-readiness`.
- The goal is application or system performance rather than the serving endpoint itself; use `performance-goal` or `ultraperf`.

## Examples

Good example:

- Prompt: Serve Qwen on our two A100s for the team and tell me if prefix caching is worth turning on.
- Expected behavior: Engine verdict (vLLM, TP as a power of two), quantization check, the k8s or docker runbook with its gates and verification, then the prefix-cache A/B protocol with hit-rate assumptions recorded - numbers only from observed runs.
- Why: Serving plus a measured tuning question is exactly the decide-deploy-measure process this workflow owns.

Bad example:

- Prompt: Just tell me the endpoint is fast enough, we already know it works.
- Expected behavior: Refuse the unmeasured claim; run the benchmark protocol against the stated SLO or report the capacity question as unanswered.
- Why: A fast-enough claim without a load shape and observed results is the folklore this skill replaces.

## Completion Checklist

- The engine/quantization verdict names the situation-table row it came from and the rejected options.
- Every runbook step's status is prepared or observed, never assumed, and the port invariant was honored.
- Benchmark numbers carry metrics, load shape, dataset, SLO, and saved metadata, or are not reported.
- Anything the workflow started for measurement was stopped, and credentials never appear in artifacts.

## Recovery Notes

- If the hardware truth is unknown, probe it first (GPU inventory, VRAM) instead of assuming the engine.
- If deployment verification fails, walk the failure ladder (toolkit, shared memory, permissions, token) before editing manifests.
- If a benchmark misses the verify targets, go to the symptom->flag table and re-measure one change at a time.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `best-practice-research`, `autoresearch-goal`, `model-optimization`, `inference-serving`, `+17 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when a model needs to be served - engine and quantization chosen, docker or Kubernetes deployment prepared as a gated runbook, or the endpoint measured with the TTFT/TPOT/ITL/goodput protocol - and the user wants the process, not an ad-hoc command guess.

    Strong routing signals: `inference-serving`, `inference serving`, `serve this model`, `serve the model`, `model serving`, `serving endpoint`, `vllm`, `llama.cpp`, `llama cpp`, `serve with vllm`, `deploy vllm`, `vllm deployment`, `serving benchmark`, `benchmark the endpoint`, `prefix caching benchmark`, `gguf quantization`, `which quantization`, `모델 서빙`, `모델 서빙해줘`, `모델 배포해서 서빙`, `서빙 벤치마크`, `vllm 배포`, `vllm 서빙`, `추론 서버 띄워줘`, `모델 띄워줘`

## Catalog Metadata

Category: `operations`
Phase: `inference-serving`
Hermes role: `operator`
Quality tier: `observed-command-gated`
Reasoning demand: `light`

Quality bar:

- Decide before deploying: engine from the situation table (vLLM for multi-user NVIDIA APIs, llama.cpp for CPU/Apple Silicon/edge, TensorRT-LLM only with ops budget), quantization to match (AWQ/GPTQ/FP8 vs the GGUF ladder with `Q4_K_M` default), tensor parallel a power of two.
- Deploy as the gated runbook: docker's three load-bearing flags (`--ipc=host`, HF cache mount, `HF_TOKEN`) or the Kubernetes five-step (secret gate, existing-deployment gate, apply, rollout+readiness verify, summary+smoke); the port invariant touches four places or it did not change the port.
- Troubleshoot from the symptom table first - slow TTFT to prefix caching/chunked prefill, OOM to gpu-memory-utilization/max-model-len/quantization - before inventing flags.
- Measure with the protocol: TTFT/TPOT/ITL/E2EL as mean/median/P99, goodput against an explicit SLO, one load shape per run, results saved with metadata; the full contract is `omh-inference-serving/references/serving-bench.md`.
- Report observed-only: each runbook step is prepared until its command's exit status and output are seen.

Handoff policy:

Keep engine/quantization decisions, runbook preparation, and benchmark design in Hermes; the commands run through the operator's terminal with observed evidence, and repository changes (deploy manifests, benchmark harnesses) are coding work for the selected executor lane. A runbook or benchmark plan is prepared_not_observed until its commands' results are seen.

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

Safety rules:

- Never claim the server is up without the observed rollout/readiness or smoke-request evidence.
- Never write credentials into runbooks or results; tokens are referenced (`HF_TOKEN`, a named secret), never inlined.
- A healthy probe is not a benchmark; a benchmark number without its load shape and metadata is not reported.
- If the workflow started a server for a benchmark, the workflow stops it.

## Runtime Evidence

Preferred harness for this skill: `coding-handling`.

```sh
omh runtime record --skill inference-serving --harness coding-handling --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.

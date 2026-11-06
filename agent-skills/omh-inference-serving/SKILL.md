---
name: "omh-inference-serving"
description: "[omh] Self-hosted LLM serving on GPUs: choose the serving engine and quantization from decision tables, prepare deployment as an idempotent runbook with observed-only verification, and measure the endpoint with the standard TTFT/TPOT/goodput protocol. Use when the user says: inference-serving, inference serving, serve this model, serve the model, model serving, serving endpoint, vllm, llama.cpp."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: inference-serving
    role: operator
    quality_tier: observed-command-gated
---

# Inference Serving

This is an OMH `inference-serving` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`inference-serving` exists so serving an LLM runs as one decided, gated, measured process instead of scattered flag folklore: the engine choice is a table, the deployment is an idempotent runbook whose only completion evidence is the observed verification, and the benchmark speaks the standard metric vocabulary.

## Do Not Use When

- A new model generation needs recognition, calibration, routing, and pricing onboarding.
- The user wants their own machine's model routing or providers configured.
- The question is whether a coding runtime/executor can run at all.
- The goal is application or system performance rather than the serving endpoint itself; use `ulw-perf`.

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



## When to Use

Use when a model needs to be served - engine and quantization chosen, docker or Kubernetes deployment prepared as a gated runbook, or the endpoint measured with the TTFT/TPOT/ITL/goodput protocol - and the user wants the process, not an ad-hoc command guess.

    Strong routing signals: `inference-serving`, `inference serving`, `serve this model`, `serve the model`, `model serving`, `serving endpoint`, `vllm`, `llama.cpp`, `llama cpp`, `serve with vllm`, `deploy vllm`, `vllm deployment`, `serving benchmark`, `benchmark the endpoint`, `prefix caching benchmark`, `gguf quantization`, `which quantization`, `모델 서빙`, `모델 서빙해줘`, `모델 배포해서 서빙`, `서빙 벤치마크`, `vllm 배포`, `vllm 서빙`, `추론 서버 띄워줘`, `모델 띄워줘`

## Catalog Metadata

Category: `operations`
Phase: `inference-serving`
Quality tier: `observed-command-gated`
Reasoning demand: `light`

Quality bar:

- Decide before deploying: engine from the situation table (vLLM for multi-user NVIDIA APIs, llama.cpp for CPU/Apple Silicon/edge, TensorRT-LLM only with ops budget), quantization to match (AWQ/GPTQ/FP8 vs the GGUF ladder with `Q4_K_M` default), tensor parallel a power of two.
- Deploy as the gated runbook: docker's three load-bearing flags (`--ipc=host`, HF cache mount, `HF_TOKEN`) or the Kubernetes five-step (secret gate, existing-deployment gate, apply, rollout+readiness verify, summary+smoke); the port invariant touches four places or it did not change the port.
- Troubleshoot from the symptom table first - slow TTFT to prefix caching/chunked prefill, OOM to gpu-memory-utilization/max-model-len/quantization - before inventing flags.
- Measure with the protocol: TTFT/TPOT/ITL/E2EL as mean/median/P99, goodput against an explicit SLO, one load shape per run, results saved with metadata; the full contract is `omh-inference-serving/references/serving-bench.md`.
- Report observed-only: each runbook step is prepared until its command's exit status and output are seen.

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

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.

---
name: "omh-model-compression"
description: "[omh] Making a model smaller or cheaper by changing its weights: quantization (GPTQ, AWQ, GGUF, bitsandbytes, FP8, quantization-aware training), pruning, or distillation into a smaller student, sized to the target hardware, calibrated on the task's own data, and kept only when it holds quality on the person's own eval. Use when the user says: model-compression, model compression, compress this model, compress the model, compress a model, compress our model, compress my model, quantize this model."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: model-compression
    role: planner
    quality_tier: baseline-comparison-gated
    related_skills: [omh-inference-serving, omh-model-finetuning, omh-rules-distill, omh-model-optimization]
---

# Model Compression

This is a Hermes-native `model-compression` workflow skill.

## Why This Exists

`model-compression` exists because making a model smaller had no owner: `omh-inference-serving` chooses an engine and the quantized format to serve, and `omh-model-finetuning` trains for new behavior, while producing the smaller weights and proving they still do the person's task fell between them, and perplexity was the only number anyone checked.

## First Steps

- Ask what hardware and memory budget the model must fit and which runtime will load it before naming a method.
- Ask for the held-out task examples and the uncompressed model's score on them.

## Do Not Use When

- The ask is choosing a serving engine, which published checkpoint format to serve, or deploying and benchmarking an endpoint; use `omh-inference-serving`.
- The ask is training a model for new behavior on your own data with SFT, DPO, RLVR or a LoRA adapter; use `omh-model-finetuning`.
- The ask is turning lessons from OMH sessions into rules or guidance; use `omh-rules-distill`.
- The ask is onboarding a new model generation into OMH's routing, calibration, or pricing; use `omh-model-optimization`.

## Examples

Good example:

- Prompt: Quantize our Llama 3.1 8B support classifier so it fits on one 16 GB GPU under vLLM, and tell me how much accuracy we lose.
- Expected behavior: Size the target, measure the 16-bit baseline on the held-out tickets, run a 4-bit GPTQ or AWQ pass with calibration tickets kept apart from the eval, and keep it only if accuracy stays within the stated tolerance.
- Why: The runtime and memory budget pick the format, and the person's own tickets decide whether the smaller model is kept.

Bad example:

- Prompt: The Q4_K_M GGUF has perplexity 6.1 against 5.9 for the original, ship it.
- Expected behavior: Refuse to keep it on perplexity alone: run the same task eval on the original and the Q4_K_M and compare before shipping.
- Why: A small perplexity gap can hide a large loss on the task, long context, or output format.

## Completion Checklist

- The target names the hardware, the memory budget, the runtime and the format it needs.
- The method is the cheapest that reaches the target, with the rejected methods named.
- Calibration data came from the task's distribution and none of it is in the held-out eval.
- The kept model cites the same eval observed on the baseline and on it, within the stated tolerance.
- OMH ran nothing, and every size and score cites observed output or is marked unverified.

## Recovery Notes

- If no held-out task eval exists, building one is the first step; say so before any compression run.
- If 4-bit loses too much, try a higher-precision format, a larger calibration set or an importance matrix before pruning or distillation.

## Workflow Lane

- Current lane: **Research and company ops** - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when a model's weights must get smaller or cheaper to fit a memory budget or cheaper hardware: post-training or quantization-aware quantization, structured or unstructured pruning, or distillation into a smaller student, gated by a comparison with the uncompressed baseline on the person's own task eval; OMH compresses nothing and runs no eval.

    Strong routing signals: `model-compression`, `model compression`, `compress this model`, `compress the model`, `compress a model`, `compress our model`, `compress my model`, `quantize this model`, `quantize the model`, `quantize a model`, `quantize our model`, `quantize my model`, `prune this model`, `prune the model`, `prune a model`, `prune our model`, `prune my model`, `distill this model`, `distill the model`, `distill a model`, `distill our model`, `distill my model`, `make this model smaller`, `make the model smaller`, `structured pruning`, `unstructured pruning`, `weight pruning`, `magnitude pruning`, `4-bit quantization`, `8-bit quantization`, `into a smaller model`, `post-training quantization`, `quantization-aware training`, `model quantization`, `quantized model`, `int8 quantization`, `fp8 quantization`, `gptq`, `awq`, `bitsandbytes`, `model pruning`, `sparsegpt`, `model distillation`, `knowledge distillation`, `smaller student model`, `모델 양자화`, `모델 증류`, `지식 증류`, `모델 프루닝`, `모델 가지치기`, `양자화 인식 학습`

## Catalog Metadata

Category: `planning`
Phase: `model-compression`
Hermes role: `planner`
Quality tier: `baseline-comparison-gated`
Reasoning demand: `standard`

Quality bar:

- Start from the target: the memory budget and the runtime decide the format, and the format decides the method.
- Load `references/compression-method.md` for the sizing arithmetic, the method table, the commands with their source pages, and the quality gate instead of recalling flags.
- Try weight-only post-training quantization first; reach for pruning, quantization-aware training or distillation only when it measured short, because each needs training compute.
- Judge every candidate on the person's own task metric beside the baseline, and report perplexity or KL divergence only as a secondary signal.
- Keep prepared, compressed, evaluated, and kept as separate states for every candidate.

Handoff policy:

Keep the target, the method choice, the calibration plan and the quality gate in Hermes. Quantization, pruning, distillation and every eval run in the operator's environment; sizes, speeds and scores are recorded only from observed output, and OMH never loads a model, compresses weights, or runs an eval.

Required inputs:

- the model: id or path, parameter count, architecture, and a license that permits a modified copy
- the target: GPU and VRAM, CPU or Apple Silicon, or the edge device, and the memory budget the model must fit
- the runtime that will load the result: vLLM, llama.cpp, TensorRT-LLM, or Transformers
- the person's own held-out task examples, the metric, and the quality loss they accept
- calibration text from the same distribution as the task, kept apart from the held-out examples
- for distillation: the teacher, the student candidates, and terms that permit training on the teacher's outputs

Expected outputs:

- compression_target/v1
- compression_method_choice/v1
- calibration_data_plan/v1
- compression_quality_gate/v1

Artifact expectations:

- compression_target/v1 turns the memory budget into the bits per weight or parameter count that fits, with the KV cache and runtime overhead counted, and names the runtime format that target needs
- compression_method_choice/v1 picks the cheapest method that reaches the target -- weight-only post-training quantization before pruning, quantization-aware training or distillation -- for that runtime, names the tool and the command's source page, and lists the methods rejected
- calibration_data_plan/v1 names the calibration source, sample count and sequence length, drawn from the task's distribution and checked for overlap with the held-out eval
- compression_quality_gate/v1 runs the same held-out eval, prompts and decoding on the uncompressed baseline and each compressed candidate, adds perplexity or KL divergence as a secondary signal, and keeps the smallest candidate within the stated tolerance

Safety rules:

- Measure the uncompressed baseline on the person's own held-out task eval before compressing; perplexity alone never keeps a compressed model.
- Keep a compressed model only when it stays within the stated tolerance of the baseline on that same eval; otherwise keep the next-larger candidate or the baseline.
- Never calibrate on the held-out eval examples; a model calibrated on its test set proves nothing.
- Do not distill from a teacher whose terms forbid training on its outputs, or publish a compressed copy the model's license does not permit.
- OMH compresses nothing, loads no model, and runs no eval; every size, speed, and score comes from observed output or is marked unverified.

## Runtime Evidence

Preferred harness for this skill: `research`.

```sh
omh runtime record --skill model-compression --harness research --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.

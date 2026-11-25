# Model Compression

Load this on-demand contract after the compact `model-compression` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The ask is choosing a serving engine, which published checkpoint format to serve, or deploying and benchmarking an endpoint; use `omh-inference-serving`.
- The ask is training a model for new behavior on your own data with SFT, DPO, RLVR or a LoRA adapter; use `omh-model-finetuning`.
- The ask is turning lessons from OMH sessions into rules or guidance; use `omh-rules-distill`.
- The ask is onboarding a new model generation into OMH's routing, calibration, or pricing; use `omh-model-optimization`.

## Examples

Good example:

- Prompt: Quantize our Llama 3.1 8B support classifier so it fits on one 16 GB GPU under vLLM, and tell me how much accuracy we lose.
- Expected behavior: Size the target and measure the 16-bit baseline on the held-out tickets. Try FP8 or weight-only quantization first; run a 4-bit GPTQ or AWQ pass, with calibration tickets kept apart from the eval, only if the KV budget or the GPU class rules that out. Keep the result only if accuracy stays within the stated tolerance.
- Why: The runtime and memory budget pick the format, and the person's own tickets decide whether the smaller model is kept.

Bad example:

- Prompt: The Q4_K_M GGUF has perplexity 6.1 against 5.9 for the original, ship it.
- Expected behavior: Refuse to keep it on perplexity alone: run the same task eval on the original and the Q4_K_M and compare before shipping.
- Why: A small perplexity gap can hide a large loss on the task, long context, or output format.

## Full Input, Output, and Artifact Expectations

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

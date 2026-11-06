# Serving Runbooks

Engine choice, then deployment as an idempotent runbook. Every command here is
prepared context: it counts only when its exit status and output are observed.

## Engine decision

| Situation | Engine | Why |
| --- | --- | --- |
| Production API, many concurrent users, NVIDIA GPUs | vLLM | continuous batching + paged KV cache; OpenAI-compatible server out of the box |
| CPU, Apple Silicon, consumer/edge hardware, single user | llama.cpp | GGUF quantization, no CUDA required, hybrid CPU+GPU layer offload |
| NVIDIA-only, maximum throughput, ops budget for engine builds | TensorRT-LLM | fastest on paper, heaviest to operate |
| Prototype, one-off script | plain transformers | not a serving engine; never ship it as one |

Quantization follows the engine: AWQ for large models with minimal loss, GPTQ
for widest support, FP8 where the hardware serves it natively - versus the
GGUF ladder for llama.cpp, where `Q4_K_M` is the default, `Q5_K_M`/`Q6_K`/
`Q8_0` buy quality, and `Q2_K`/`Q3_K` exist to fit, not to ship. A choice is
not yet a verdict: run the user's held-out eval on the unquantized model and
on the quantized one and report the delta first, and name the calibration data
for AWQ and GPTQ. FP8 weights and activations need Hopper- or Ada-class
hardware; on A100 use a weight-only format. Tensor parallel size must divide
the model's attention and KV head counts and cannot exceed the GPUs that
exist; use pipeline parallelism when the GPU count does not fit.

## Docker runbook (vLLM)

The three flags that break when forgotten: `--ipc=host` (or a large
`--shm-size`) for shared memory, the HF cache mount so weights download once,
and `HF_TOKEN` for gated models.

```sh
docker run --rm --gpus all   -v ~/.cache/huggingface:/root/.cache/huggingface   --env HF_TOKEN --ipc=host -p 8000:8000   vllm/vllm-openai:<pinned-tag> --model <model-id>
```

Failure ladder, in order: nvidia-container-toolkit installed and configured;
shared-memory OOM (raise shm); docker group permissions; token/proxy failures
on the weight download.

## Kubernetes runbook (vLLM)

Five steps, idempotent, in order - each step is a gate, not a suggestion:

1. **Secret gate** - does the `hf-token` secret exist? Create it only if not.
2. **Existing-deployment gate** - is a vllm Deployment already present?
   Applying over a live one is an update decision, not a bootstrap.
3. **Apply** the Service and Deployment.
4. **Verify** with `kubectl rollout status` plus pod readiness - the runbook's
   only completion evidence.
5. **Summarize**: table of what exists, then a port-forward, a `/v1/models` check, and one `chat/completions`
   request with `max_tokens: 8` whose latency is recorded as the first sample.

Sane defaults until measured otherwise: `--gpu-memory-utilization 0.85`,
tensor parallel 1, a large dshm volume, readiness and liveness probes on `/health`,
plus a `startupProbe` whose failureThreshold times periodSeconds exceeds the
measured cold-cache load time of the weights (liveness starts only after it
passes; a pod restarting while it loads is the first thing to check when
rollout status never completes). **The port invariant**: changing the serving port touches four
places - containerPort, Service port/targetPort, all health probes, and
`--port` in args; a runbook that changes fewer has not changed the port.
Cleanup mirrors setup and ends at an explicit keep-or-delete decision for the
secret.

## Who may reach the endpoint

State who may reach the server before exposing it. Bind to localhost or a ClusterIP Service unless exposure is the goal, and set `--api-key` from a named secret. The key only authenticates the OpenAI-compatible paths (`/v1`, `/v2`, `/inference`, `/cohere`); other paths such as `/metrics` stay behind the network boundary. The image tag is pinned and recorded with the benchmark metadata, so two runs are comparable.

## Symptom -> flag

| Symptom | First flags to reach for |
| --- | --- |
| Slow TTFT on shared prefixes | `--enable-prefix-caching`, `--enable-chunked-prefill` |
| Low throughput, GPU idle | raise `--max-num-seqs`, check batching is engaged |
| OOM at load or under load | lower `--gpu-memory-utilization`, cap `--max-model-len`, quantize |
| llama.cpp too slow on GPU-poor host | `-ngl N` hybrid layer offload; drop one GGUF quality tier |

Watchable truth: the engine's own metrics (time-to-first-token, running
request count, KV-cache usage) beat any wrapper's impression of them.

## Boundary

An engine choice, runbook, or flag plan is prepared_not_observed; deployment
exists only when the rollout/readiness commands are observed, and a healthy
probe is not a benchmark, a capacity claim, review, CI, or merge evidence.

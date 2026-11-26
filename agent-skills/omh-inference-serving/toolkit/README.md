# Inference Serving Offline VRAM & KV-Cache Calculator (`vram_kv_calc.py`)

Offline Python 3.11+ standard-library companion script for `omh-inference-serving`.
Computes exact weight memory, KV-cache footprint across concurrency and sequence
length, tensor-parallel head divisibility, and usable GPU VRAM headroom so serving
decisions never rely on rough mental math.

## Safety Boundary

- **Offline calculation only**: does not probe live GPUs, start a server, or claim
  observed rollout/benchmark evidence (`calculated_estimate_not_observed_gpu_run`).

## Usage

```sh
python3 toolkit/scripts/vram_kv_calc.py \
  --params-b 70 --precision fp8 \
  --layers 80 --attention-heads 64 --kv-heads 8 --head-dim 128 \
  --max-model-len 8192 --concurrency 16 \
  --gpu-vram-gb 80 --gpu-count 2 --tp 2 --json
```

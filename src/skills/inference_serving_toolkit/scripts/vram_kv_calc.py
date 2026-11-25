#!/usr/bin/env python3
"""Offline VRAM, KV-cache, and tensor-parallelism calculator for omh-inference-serving.

Zero third-party dependencies, zero network or GPU probing.
"""
from __future__ import annotations

import argparse
import json
import math
import sys

SCHEMA_VERSION = "vram_kv_budget/v1"
GIB = 1024**3

# Effective bytes per parameter (including quantization scale/zero-point overhead where applicable).
PRECISION_BYTES_PER_PARAM: dict[str, float] = {
    "fp32": 4.0,
    "fp16": 2.0,
    "bf16": 2.0,
    "fp8": 1.05,
    "int8": 1.05,
    "q8_0": 1.06,
    "awq4": 0.56,
    "gptq4": 0.56,
    "int4": 0.56,
    "q4_k_m": 0.59,
    "q5_k_m": 0.70,
    "q6_k": 0.82,
}

KV_DTYPE_BYTES: dict[str, float] = {
    "fp16": 2.0,
    "bf16": 2.0,
    "fp8": 1.0,
    "int8": 1.0,
}


def calculate_vram_kv_budget(
    *,
    params_b: float,
    precision: str,
    layers: int,
    attention_heads: int,
    kv_heads: int,
    head_dim: int,
    kv_dtype: str = "bf16",
    max_model_len: int = 8192,
    concurrency: int = 8,
    gpu_vram_gb: float = 80.0,
    gpu_count: int = 1,
    tp: int | None = None,
    gpu_memory_utilization: float = 0.90,
    cuda_activation_overhead_gib_per_gpu: float = 2.5,
) -> dict[str, object]:
    if params_b <= 0:
        raise ValueError("params_b must be > 0")
    if precision not in PRECISION_BYTES_PER_PARAM:
        raise ValueError(f"unsupported precision {precision!r}; choose from {sorted(PRECISION_BYTES_PER_PARAM)}")
    if kv_dtype not in KV_DTYPE_BYTES:
        raise ValueError(f"unsupported kv_dtype {kv_dtype!r}; choose from {sorted(KV_DTYPE_BYTES)}")
    if layers <= 0 or attention_heads <= 0 or kv_heads <= 0 or head_dim <= 0:
        raise ValueError("layers, attention_heads, kv_heads, and head_dim must be positive integers")
    if max_model_len <= 0 or concurrency <= 0 or gpu_vram_gb <= 0 or gpu_count <= 0:
        raise ValueError("max_model_len, concurrency, gpu_vram_gb, and gpu_count must be positive")
    if not (0.1 <= gpu_memory_utilization <= 1.0):
        raise ValueError("gpu_memory_utilization must be in [0.1, 1.0]")

    effective_tp = gpu_count if tp is None else tp
    if effective_tp <= 0 or effective_tp > gpu_count:
        raise ValueError("tp must be between 1 and gpu_count")

    attention_divisible = attention_heads % effective_tp == 0
    kv_divisible = (kv_heads % effective_tp == 0) or (effective_tp % kv_heads == 0)
    tp_divisibility_ok = attention_divisible and kv_divisible

    weight_bytes = params_b * 1_000_000_000 * PRECISION_BYTES_PER_PARAM[precision]
    weight_gib = weight_bytes / GIB

    # 2 tensors (K and V) * layers * kv_heads * head_dim * dtype_bytes per token
    kv_bytes_per_token = 2 * layers * kv_heads * head_dim * KV_DTYPE_BYTES[kv_dtype]
    kv_bytes_per_seq = kv_bytes_per_token * max_model_len
    kv_total_gib = (kv_bytes_per_seq * concurrency) / GIB

    overhead_gib = cuda_activation_overhead_gib_per_gpu * gpu_count
    total_required_gib = weight_gib + kv_total_gib + overhead_gib

    usable_vram_gib = gpu_count * gpu_vram_gb * gpu_memory_utilization
    headroom_gib = usable_vram_gib - total_required_gib
    kv_budget_gib = max(0.0, usable_vram_gib - weight_gib - overhead_gib)
    max_safe_concurrency = int(math.floor((kv_budget_gib * GIB) / kv_bytes_per_seq)) if kv_bytes_per_seq > 0 else 0

    if not tp_divisibility_ok:
        verdict = "invalid_tp_divisibility"
        fits = False
    elif headroom_gib < 0:
        verdict = "oom_likely"
        fits = False
    elif headroom_gib < (0.08 * usable_vram_gib):
        verdict = "tight_headroom"
        fits = True
    else:
        verdict = "fits"
        fits = True

    return {
        "schema_version": SCHEMA_VERSION,
        "inputs": {
            "params_b": params_b,
            "precision": precision,
            "layers": layers,
            "attention_heads": attention_heads,
            "kv_heads": kv_heads,
            "head_dim": head_dim,
            "kv_dtype": kv_dtype,
            "max_model_len": max_model_len,
            "concurrency": concurrency,
            "gpu_vram_gb": gpu_vram_gb,
            "gpu_count": gpu_count,
            "tp": effective_tp,
            "gpu_memory_utilization": gpu_memory_utilization,
            "cuda_activation_overhead_gib_per_gpu": cuda_activation_overhead_gib_per_gpu,
        },
        "memory_gib": {
            "weights": round(weight_gib, 3),
            "kv_cache_total": round(kv_total_gib, 3),
            "kv_cache_per_sequence": round(kv_bytes_per_seq / GIB, 4),
            "kv_bytes_per_token": int(kv_bytes_per_token),
            "cuda_and_activation_overhead": round(overhead_gib, 3),
            "total_required": round(total_required_gib, 3),
            "usable_vram": round(usable_vram_gib, 3),
            "headroom": round(headroom_gib, 3),
        },
        "parallelism": {
            "tp": effective_tp,
            "attention_heads_divisible": attention_divisible,
            "kv_heads_divisible_or_replicated": kv_divisible,
            "tp_divisibility_ok": tp_divisibility_ok,
        },
        "capacity": {
            "fits": fits,
            "verdict": verdict,
            "max_safe_concurrency_at_max_len": max_safe_concurrency,
        },
        "claim_boundary": (
            "calculated_estimate_not_observed_gpu_run: deterministic offline VRAM/KV-cache math only. "
            "Does not probe GPUs or substitute for observed startup/load-test evidence."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline VRAM, KV-cache, and TP calculator for omh-inference-serving."
    )
    parser.add_argument("--params-b", type=float, required=True)
    parser.add_argument("--precision", default="bf16", choices=sorted(PRECISION_BYTES_PER_PARAM))
    parser.add_argument("--layers", type=int, required=True)
    parser.add_argument("--attention-heads", type=int, required=True)
    parser.add_argument("--kv-heads", type=int, required=True)
    parser.add_argument("--head-dim", type=int, required=True)
    parser.add_argument("--kv-dtype", default="bf16", choices=sorted(KV_DTYPE_BYTES))
    parser.add_argument("--max-model-len", type=int, default=8192)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--gpu-vram-gb", type=float, required=True)
    parser.add_argument("--gpu-count", type=int, default=1)
    parser.add_argument("--tp", type=int, default=None)
    parser.add_argument("--gpu-memory-utilization", type=float, default=0.90)
    parser.add_argument("--overhead-gib-per-gpu", type=float, default=2.5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = calculate_vram_kv_budget(
            params_b=args.params_b,
            precision=args.precision,
            layers=args.layers,
            attention_heads=args.attention_heads,
            kv_heads=args.kv_heads,
            head_dim=args.head_dim,
            kv_dtype=args.kv_dtype,
            max_model_len=args.max_model_len,
            concurrency=args.concurrency,
            gpu_vram_gb=args.gpu_vram_gb,
            gpu_count=args.gpu_count,
            tp=args.tp,
            gpu_memory_utilization=args.gpu_memory_utilization,
            cuda_activation_overhead_gib_per_gpu=args.overhead_gib_per_gpu,
        )
    except (ValueError, ZeroDivisionError) as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        mem = payload["memory_gib"]
        cap = payload["capacity"]
        print(
            f"vram_kv_budget/v1 verdict={cap['verdict']} required={mem['total_required']}GiB "
            f"usable={mem['usable_vram']}GiB headroom={mem['headroom']}GiB "
            f"max_concurrency={cap['max_safe_concurrency_at_max_len']}"
        )
    return 0 if payload["capacity"]["fits"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

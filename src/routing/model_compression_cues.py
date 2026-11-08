"""Phrases `model-compression` shares with a 3D asset, a business model, a garden or an audio signal.

A leaf module: the catalog reads these as the skill's own triggers and the
everyday-sense table reads them as phrases that keep the skill only beside a
word of model weights, so both read one tuple.
"""

from __future__ import annotations

_DETERMINERS = ("this", "the", "a", "our", "my")

# A compression verb on "model", and a pruning or bit-width phrase, names an ML
# model only when the message says so: a 3D asset, a statistical or a business
# model is compressed, pruned or distilled too, fruit trees get structured
# pruning, and audio gets 8-bit quantization.
MODEL_COMPRESSION_SHARED_PHRASES = (
    "model compression",
    *(
        f"{verb} {determiner} model"
        for verb in ("compress", "quantize", "prune", "distill")
        for determiner in _DETERMINERS
    ),
    "make this model smaller",
    "make the model smaller",
    "structured pruning",
    "unstructured pruning",
    "weight pruning",
    "magnitude pruning",
    "4-bit quantization",
    "8-bit quantization",
    "into a smaller model",
)

# Words of model weights. "distill this model into a smaller one" says which
# model through its result, so `smaller` is one. An anchor counts only outside
# the phrase it anchors, because "4-bit quantization" and "make the model
# smaller" carry anchor words of their own.
MODEL_COMPRESSION_ANCHORS = frozenset(
    {
        "4-bit", "8-bit", "accuracy", "awq", "bf16", "bitsandbytes", "classifier", "deepseek", "distillation",
        "eval", "evals", "fp16", "fp8", "gguf", "gpt-oss", "gptq", "gpu", "gpus", "huggingface", "inference", "int4",
        "int8", "llama", "llm", "llms", "neural", "on-device", "onnx", "parameters", "params", "perplexity",
        "pruning", "pytorch", "quantization", "quantized", "qwen", "safetensors", "smaller", "sparsegpt",
        "sparsity", "student", "teacher", "transformer", "transformers", "vram", "weights",
    }
)

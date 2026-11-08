"""Phrases `model-compression` shares with a 3D asset, a business model, a garden, an audio signal or a team's know-how.

A leaf module: the catalog reads the shared phrases as the skill's own
triggers and the everyday-sense table reads them as phrases that keep the
skill only on their own or beside a word of model weights, so both read one
tuple.
"""

from __future__ import annotations

import re

from ..plugin_bundle.omh.text_fold import routing_terms

_DETERMINERS = ("this", "the", "a", "our", "my")

# A compression verb on "model", a pruning or bit-width phrase, and knowledge
# distillation name an ML model only when the message says so: a 3D asset, a
# statistical or a business model is compressed, pruned or distilled too, fruit
# trees get structured pruning, audio and pixel art get 8-bit quantization, and
# a team distills its know-how.
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
    "knowledge distillation",
)

# Words that mean model weights and nothing else. `gpu`, `accuracy`,
# `inference`, `parameters`, `weights`, `vram`, `smaller`, `student`, `8-bit`
# and the method nouns are not here: a regression has parameters and accuracy,
# a 3D scene loads on the GPU, pixel art is 8-bit, and a workshop has students.
# An anchor counts only outside the phrase it anchors.
MODEL_COMPRESSION_ANCHORS = frozenset(
    {
        "awq", "bf16", "bitsandbytes", "deepseek", "fp16", "gguf", "gpt-oss", "gptq", "huggingface", "int4",
        "llama", "llm", "llms", "perplexity", "pytorch", "qwen", "safetensors", "sparsegpt", "transformer",
        "transformers",
    }
)

# A parameter count such as `70b` or `8b`, with a Korean particle allowed after
# it (`8b로`), but not a longer word (`8bit`).
_PARAMETER_COUNT = re.compile(r"\d+(?:\.\d+)?b(?![a-z0-9])")


def names_a_parameter_count(normalized_query: str) -> bool:
    """The message names a model by its parameter count, as `70b` or `8b`."""
    return any(_PARAMETER_COUNT.match(term) for term in routing_terms(normalized_query))

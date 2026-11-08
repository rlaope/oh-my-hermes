"""Phrases `model-compression` shares with a 3D asset, a business model, a garden, an audio signal or a team's know-how.

A leaf module: the catalog reads the shared phrases as the skill's own
triggers and the everyday-sense table reads them as phrases that keep the
skill only on their own or beside a word of model weights, so both read one
tuple.
"""

from __future__ import annotations

import re

from ..plugin_bundle.omh.text_fold import normalized_phrase

_DETERMINERS = ("this", "the", "a", "our", "my")

# A compression verb on "model", a pruning or bit-width phrase, knowledge
# distillation and post-training quantization name an ML model only when the
# message says so: a 3D asset, a statistical or a business model is
# compressed, pruned or distilled too, fruit trees get structured pruning,
# audio and pixel art get 8-bit quantization, a team distills its know-how,
# and firmware quantizes an ADC signal after training a filter.
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
    "post-training quantization",
)

# Words that mean model weights and nothing else. `gpu`, `accuracy`,
# `inference`, `parameters`, `weights`, `vram`, `smaller`, `student`, `8-bit`
# and the method nouns are not here: a regression has parameters and accuracy,
# a 3D scene loads on the GPU, pixel art is 8-bit, and a workshop has students.
# The singular `transformer` is not either (a power grid has transformers,
# while the plural also names the Hugging Face library), nor `pytorch`, which
# also runs physics simulations. An anchor counts only outside the phrase it
# anchors.
MODEL_COMPRESSION_ANCHORS = frozenset(
    {
        "awq", "bf16", "bitsandbytes", "deepseek", "fp16", "gguf", "gpt-oss", "gptq", "huggingface", "int4",
        "llama", "llm", "llms", "perplexity", "quantization-aware", "qwen", "safetensors", "sparsegpt",
        "transformers",
    }
)

# A size such as `70b` or `8b`, with a Korean particle allowed after it
# (`8b로`), but not a longer word (`8bit`). On its own it is any billion: 5b
# gallons, a 10b dataset, a 2b budget. It never anchors a shared phrase.
_PARAMETER_COUNT = re.compile(r"\d+(?:\.\d+)?b(?![a-z0-9])")
_MODEL_WORDS = ("model", normalized_phrase("모델"))


def names_a_model_by_parameter_count(normalized_query: str) -> bool:
    """Two sizes (`70b ... 8b`), or one size followed by `model` or `모델` (`our 7b model`, `70B 모델을`)."""
    words = [word.strip(".,;:!?()[]\"'") for word in normalized_query.split()]
    sizes = [index for index, word in enumerate(words) if _PARAMETER_COUNT.match(word)]
    if len(sizes) >= 2:
        return True
    return any(index + 1 < len(words) and words[index + 1].startswith(_MODEL_WORDS) for index in sizes)

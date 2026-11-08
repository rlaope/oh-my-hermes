"""Make a model smaller or cheaper by changing its weights, and keep it only when it holds quality on the person's task."""
from __future__ import annotations

from ..routing.model_compression_cues import MODEL_COMPRESSION_SHARED_PHRASES
from .catalog_types import SkillDefinition, SkillExample

REFERENCE_PATH = "references/compression-method.md"

DEFINITION = SkillDefinition(
    "model-compression",
    "Making a model smaller or cheaper by changing its weights: quantization (GPTQ, AWQ, GGUF, bitsandbytes, FP8, "
    "quantization-aware training), pruning, or distillation into a smaller student, sized to the target hardware, "
    "calibrated on the task's own data, and kept only when it holds quality on the person's own eval.",
    (
        "model-compression",
        *MODEL_COMPRESSION_SHARED_PHRASES,
        "post-training quantization",
        "quantization-aware training",
        "model quantization",
        "quantized model",
        "int8 quantization",
        "fp8 quantization",
        "gptq",
        "awq",
        "bitsandbytes",
        "model pruning",
        "sparsegpt",
        "model distillation",
        "smaller student model",
    ),
    (
        "Use when a model's weights must get smaller or cheaper to fit a memory budget or cheaper hardware: "
        "post-training or quantization-aware quantization, structured or unstructured pruning, or distillation into a "
        "smaller student, gated by a comparison with the uncompressed baseline on the person's own task eval; OMH "
        "compresses nothing and runs no eval."
    ),
    category="planning",
    phase="model-compression",
    hermes_role="retained-cognition",
    delegation_boundary="retained-catalog-intent",
    handoff_policy=(
        "Keep the target, the method choice, the calibration plan and the quality gate in Hermes. Quantization, pruning, "
        "distillation and every eval run in the operator's environment; sizes, speeds and scores are recorded only from "
        "observed output, and OMH never loads a model, compresses weights, or runs an eval."
    ),
    required_inputs=(
        "the model: id or path, parameter count, architecture, and a license that permits a modified copy",
        "the target: GPU and VRAM, CPU or Apple Silicon, or the edge device, and the memory budget the model must fit",
        "the runtime that will load the result: vLLM, llama.cpp, TensorRT-LLM, or Transformers",
        "the person's own held-out task examples, the metric, and the quality loss they accept",
        "calibration text from the same distribution as the task, kept apart from the held-out examples",
        "for distillation: the teacher, the student candidates, and terms that permit training on the teacher's outputs",
    ),
    expected_outputs=(
        "compression_target/v1",
        "compression_method_choice/v1",
        "calibration_data_plan/v1",
        "compression_quality_gate/v1",
    ),
    artifact_expectations=(
        "compression_target/v1 turns the memory budget into the bits per weight or parameter count that fits, with the KV cache and runtime overhead counted, and names the runtime format that target needs",
        "compression_method_choice/v1 picks the cheapest method that reaches the target -- weight-only post-training quantization before pruning, quantization-aware training or distillation -- for that runtime, names the tool and the command's source page, and lists the methods rejected",
        "calibration_data_plan/v1 names the calibration source, sample count and sequence length, drawn from the task's distribution and checked for overlap with the held-out eval",
        "compression_quality_gate/v1 runs the same held-out eval, prompts and decoding on the uncompressed baseline and each compressed candidate, adds perplexity or KL divergence as a secondary signal, and keeps the smallest candidate within the stated tolerance",
    ),
    safety_rules=(
        "Measure the uncompressed baseline on the person's own held-out task eval before compressing; perplexity alone never keeps a compressed model.",
        "Keep a compressed model only when it stays within the stated tolerance of the baseline on that same eval; otherwise keep the next-larger candidate or the baseline.",
        "Never calibrate on the held-out eval examples; a model calibrated on its test set proves nothing.",
        "Do not distill from a teacher whose terms forbid training on its outputs, or publish a compressed copy the model's license does not permit.",
        "OMH compresses nothing, loads no model, and runs no eval; every size, speed, and score comes from observed output or is marked unverified.",
    ),
    quality_tier="baseline-comparison-gated",
    quality_bar=(
        "Start from the target: the memory budget and the runtime decide the format, and the format decides the method.",
        "Load `references/compression-method.md` for the sizing arithmetic, the method table, the commands with their source pages, and the quality gate instead of recalling flags.",
        "Try weight-only post-training quantization first; reach for pruning, quantization-aware training or distillation only when it measured short, because each needs training compute.",
        "Judge every candidate on the person's own task metric beside the baseline, and report perplexity or KL divergence only as a secondary signal.",
        "Keep prepared, compressed, evaluated, and kept as separate states for every candidate.",
    ),
    why_this_exists=(
        "`model-compression` exists because making a model smaller had no owner: `inference-serving` chooses an engine "
        "and the quantized format to serve, and `model-finetuning` trains for new behavior, while producing the smaller "
        "weights and proving they still do the person's task fell between them, and perplexity was the only number anyone checked."
    ),
    opening_steps=(
        "Ask what hardware and memory budget the model must fit and which runtime will load it before naming a method.",
        "Ask for the held-out task examples and the uncompressed model's score on them.",
    ),
    do_not_use_when=(
        "The ask is choosing a serving engine, which published checkpoint format to serve, or deploying and benchmarking an endpoint; use `inference-serving`.",
        "The ask is training a model for new behavior on your own data with SFT, DPO, RLVR or a LoRA adapter; use `model-finetuning`.",
        "The ask is turning lessons from OMH sessions into rules or guidance; use `rules-distill`.",
        "The ask is onboarding a new model generation into OMH's routing, calibration, or pricing; use `model-optimization`.",
    ),
    good_example=SkillExample(
        prompt="Quantize our Llama 3.1 8B support classifier so it fits on one 16 GB GPU under vLLM, and tell me how much accuracy we lose.",
        expected=(
            "Size the target and measure the 16-bit baseline on the held-out tickets. Try FP8 or weight-only quantization "
            "first; run a 4-bit GPTQ or AWQ pass, with calibration tickets kept apart from the eval, only if the KV budget "
            "or the GPU class rules that out. Keep the result only if accuracy stays within the stated tolerance."
        ),
        why="The runtime and memory budget pick the format, and the person's own tickets decide whether the smaller model is kept.",
    ),
    bad_example=SkillExample(
        prompt="The Q4_K_M GGUF has perplexity 6.1 against 5.9 for the original, ship it.",
        expected="Refuse to keep it on perplexity alone: run the same task eval on the original and the Q4_K_M and compare before shipping.",
        why="A small perplexity gap can hide a large loss on the task, long context, or output format.",
    ),
    final_checklist=(
        "The target names the hardware, the memory budget, the runtime and the format it needs.",
        "The method is the cheapest that reaches the target, with the rejected methods named.",
        "Calibration data came from the task's distribution and none of it is in the held-out eval.",
        "The kept model cites the same eval observed on the baseline and on it, within the stated tolerance.",
        "OMH ran nothing, and every size and score cites observed output or is marked unverified.",
    ),
    recovery_notes=(
        "If no held-out task eval exists, building one is the first step; say so before any compression run.",
        "If 4-bit loses too much, try a higher-precision format, a larger calibration set or an importance matrix before pruning or distillation.",
    ),
    situations=(
        "the weights overflow our vram",
        "run it on a macbook without a datacenter accelerator",
        "fewer bits per weight with the same answers",
        "a compact copy that mimics the full-size version",
        "what 4-bit loses on our own questions",
    ),
)


def model_compression_definition() -> SkillDefinition:
    return DEFINITION


def model_compression_reference_templates():
    from .render import SkillReferenceTemplate, loadable_skill_mentions

    return [SkillReferenceTemplate(DEFINITION.name, REFERENCE_PATH, loadable_skill_mentions(REFERENCE_TEXT))]


REFERENCE_TEXT = '''# Model Compression Method

Load this while planning a compression. OMH prepares; the operator runs every command and eval, and each step stays `prepared` until its output is observed. The commands below were read on the page named under each one on 2026-11-07. These libraries change between releases, so open the page again before running one, and record the tool version you ran.

## 1. Size the target

Weight memory is about parameters x bits per weight / 8: an 8B model needs about 16 GB at 16 bits, 8 GB at 8 bits and 4 GB at 4 bits, plus the quantization scales. Add the KV cache, which grows with context length and the number of concurrent sequences, and the runtime's own overhead. This is arithmetic, not a measurement: record the observed file size and peak memory once a candidate exists.

The runtime that will load the result decides the format. Choosing the engine, and which published format to serve, is `inference-serving`; this skill produces the weights.

| Runtime and hardware | Format to produce | Tool |
| --- | --- | --- |
| vLLM on NVIDIA | INT4 weight-only (W4A16), compute capability above 8.0; FP8, compute capability 8.9 or above, and weight-only on 7.5 and above | llm-compressor |
| llama.cpp on CPU, Apple Silicon or an edge device | a GGUF quantization type such as `Q4_K_M`, optionally with an importance matrix | `convert_hf_to_gguf.py` and `llama-quantize` |
| Transformers in one process, or the base of an adapter fine-tune | 8-bit or 4-bit NF4 applied while the model loads | bitsandbytes |
| Transformers with a GPTQ checkpoint | GPTQ int4 | GPT-QModel through `GPTQConfig` |

## 2. Choose the method, cheapest first

Climb in order and stop at the first rung whose candidate passes the quality gate in section 5.

| Rung | Method | Needs | Use when |
| --- | --- | --- | --- |
| 1 | Weight quantization with no calibration data: FP8 dynamic, bitsandbytes, a GGUF type without an importance matrix | the model and the tool | the format exists for the runtime and the loss is within tolerance |
| 2 | Calibrated post-training quantization: GPTQ, AWQ, a GGUF type with an importance matrix | calibration text and GPU time | rung 1 lost too much, or the runtime wants a calibrated INT4 checkpoint |
| 3 | Quantization-aware training | a training run on task data | calibrated 4-bit still loses too much and training compute is available |
| 4 | Pruning that removes channels, heads or layers, followed by recovery training or distillation | a tool that rewrites the architecture, and a training run | fewer parameters are needed, not only fewer bits per weight |
| 5 | Distillation into a smaller student | a teacher, a student architecture, a training run, and terms that allow training on the teacher's outputs | the target needs a smaller architecture than rungs 1 to 4 can give |

Unstructured sparsity saves memory or time only where the runtime has a kernel for that sparsity pattern; measure it in the runtime that will serve, not in a training framework.

## 3. Commands

### llm-compressor: GPTQ W4A16 for vLLM

Source: https://docs.vllm.ai/en/latest/features/quantization/llm_compressor/int4/

```python
from llmcompressor import oneshot
from llmcompressor.modifiers.quantization import GPTQModifier

# Configure the quantization algorithms
recipe = GPTQModifier(targets="Linear", scheme="W4A16", ignore=["lm_head"])

# Apply quantization
oneshot(
    model=model,
    dataset=ds,
    recipe=recipe,
    max_seq_length=MAX_SEQUENCE_LENGTH,
    num_calibration_samples=NUM_CALIBRATION_SAMPLES,
)

# Save the compressed model: Meta-Llama-3-8B-Instruct-W4A16-G128
SAVE_DIR = MODEL_ID.split("/")[1] + "-W4A16-G128"
model.save_pretrained(SAVE_DIR, save_compressed=True)
tokenizer.save_pretrained(SAVE_DIR)
```

The page sets `NUM_CALIBRATION_SAMPLES = 512` and `MAX_SEQUENCE_LENGTH = 2048`, and advises: "Start with 512 samples for calibration data, and increase if accuracy drops". Install with `pip install llmcompressor`.

### llm-compressor: FP8 dynamic for vLLM

Source: https://docs.vllm.ai/en/latest/features/quantization/llm_compressor/fp8/

```python
from llmcompressor import oneshot
from llmcompressor.modifiers.quantization import QuantizationModifier

# Configure the simple PTQ quantization
recipe = QuantizationModifier(
    targets="Linear",
    scheme="FP8_DYNAMIC",
    ignore=["lm_head"],
)

# Apply the quantization algorithm.
oneshot(model=model, recipe=recipe)
```

The page: "we do not need any calibration data for this quantization flow", "FP8 models will run on compute capability >= 7.5 (Turing) as weight-only W8A16, utilizing FP8 Marlin.", and "Please use separate environments for vLLM and llm-compressor as they might not work together."

### llm-compressor: AWQ

Source: https://github.com/vllm-project/llm-compressor/blob/main/examples/awq/llama_example.py

```python
from llmcompressor import oneshot
from llmcompressor.modifiers.quantization import QuantizationModifier
from llmcompressor.modifiers.transform.awq import AWQModifier

recipe = [
    AWQModifier(duo_scaling="both"),
    QuantizationModifier(
        ignore=["lm_head"],
        scheme="W4A16_ASYM",
        targets=["Linear"],
    ),
]
```

The example calls `oneshot` with `dataset=`, `recipe=recipe`, `max_seq_length=512` and `num_calibration_samples=256`, and saves with `model.save_pretrained(SAVE_DIR, save_compressed=True)`. Transformers loads AWQ checkpoints but does not produce them: "Some methods, such as AWQ, AutoRound, AQLM, compressed-tensors, and GGUF, can only be loaded from a checkpoint." (https://huggingface.co/docs/transformers/main/en/quantization/overview)

### llama.cpp: GGUF

Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/quantize/README.md

```sh
python convert_hf_to_gguf.py --outfile gemma-4-E2B-it-bf16.gguf --outtype bf16 --remote google/gemma-4-E2B-it
./build/bin/llama-quantize gemma-4-E2B-it-bf16.gguf gemma-4-E2B-it-Q4_K_M.gguf Q4_K_M
```

The page: "This process however, may introduce some accuracy loss which is usually measured in Perplexity (ppl) and/or Kullback–Leibler Divergence (kld). This can be minimized by using a suitable imatrix file." Pass the importance matrix to `llama-quantize` with `--imatrix file_name`.

Source: https://github.com/ggml-org/llama.cpp/blob/master/tools/imatrix/README.md

```sh
./llama-imatrix -m ggml-model-f16.gguf -f calibration-data.txt -ngl 99
```

The output defaults to `imatrix.gguf`; `-o` names another file. The page: "`-m | --model` with a model name and `-f | --file` with a file containing calibration data (such as e.g. `wiki.train.raw`) are mandatory."

### Transformers: GPTQ through GPT-QModel

Source: https://huggingface.co/docs/transformers/main/en/quantization/gptq

```py
from transformers import AutoModelForCausalLM, AutoTokenizer, GPTQConfig

tokenizer = AutoTokenizer.from_pretrained("facebook/opt-125m")
gptq_config = GPTQConfig(bits=4, dataset="c4", tokenizer=tokenizer)
quantized_model = AutoModelForCausalLM.from_pretrained("facebook/opt-125m", device_map="auto", quantization_config=gptq_config)
quantized_model.save_pretrained("opt-125m-gptq")
tokenizer.save_pretrained("opt-125m-gptq")
```

Install with `pip install gptqmodel --no-build-isolation`; the page: "AutoGPTQ is no longer supported in Transformers. Install GPT-QModel instead." `dataset` also takes a list of strings.

### Transformers: bitsandbytes

Source: https://huggingface.co/docs/transformers/main/en/quantization/bitsandbytes

```py
import torch
from transformers import BitsAndBytesConfig

quantization_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16)
```

Add `bnb_4bit_quant_type="nf4"` for NF4, or use `load_in_8bit=True`, and pass the config to `from_pretrained(..., quantization_config=quantization_config)`. The overview page on methods applied while the model loads: "Most of them don't need a calibration dataset." and "[GPTQ](./gptq) is the exception because it calibrates on a dataset while the model loads." (https://huggingface.co/docs/transformers/main/en/quantization/overview) The page: "8 and 4-bit training is only supported for training *extra* parameters."

### torchao: quantization-aware training

Source: https://docs.pytorch.org/ao/main/workflows/qat.html

```python
from torchao.quantization import quantize_, Int4WeightOnlyConfig
from torchao.quantization.qat import QATConfig

base_config = Int4WeightOnlyConfig(group_size=32)
quantize_(model, QATConfig(base_config, step="prepare"))
# train
train_loop(model)
quantize_(model, QATConfig(base_config, step="convert"))
```

The page: "Between these two steps, training can proceed exactly as before."

### PyTorch and NVIDIA Model Optimizer: pruning

Source: https://docs.pytorch.org/docs/2.15/generated/torch.nn.utils.prune.l1_unstructured.html

```python
torch.nn.utils.prune.l1_unstructured(module, name, amount, importance_scores=None)
torch.nn.utils.prune.ln_structured(module, name, amount, n, dim, importance_scores=None)
torch.nn.utils.prune.remove(module, name)
```

Both kinds work by masking. The tutorial (https://docs.pytorch.org/tutorials/intermediate/pruning_tutorial.html): "The pruning mask generated by the pruning technique selected above is saved as a module buffer named weight_mask". On structured pruning it says "this will zero out all the connections corresponding to 50% (3 out of 6) of the channels", and of `remove`: "It simply makes it permanent, instead, by reassigning the parameter weight to the model parameters, in its pruned version." The tensor keeps its shape, so the saved file is no smaller and the model has as many parameters as before. A smaller model needs a tool that rewrites the architecture, as Model Optimizer's Minitron does below, or changing the layers by hand.

Source: https://nvidia.github.io/Model-Optimizer/guides/3_pruning.html

The guide lists three modes for `mtp.prune`:
- `fastnas`: "A pruning method recommended for Computer Vision models." Its `mtp.prune` example is this mode on a ResNet-50, so do not copy it for a language model.
- `mcore_minitron`: "A pruning method developed by NVIDIA Research for pruning GPT, Mamba and Hybrid Transformer Mamba models", "in NVIDIA Megatron-Bridge or Megatron-LM framework."
- `puzzletron`: "An advanced LLM/VLM pruning method by NVIDIA using Mixed Integer Programming (MIP) based NAS search algorithm."

For Minitron and Puzzletron the guide names the Pruning README as the canonical reference.

Source: https://github.com/NVIDIA/Model-Optimizer/tree/main/examples/pruning

Minitron "uses the activation magnitudes to prune the embedding hidden size; mlp ffn hidden size; transformer attention heads;" "and number of layers of the model", and "Slices the model weights according to the pruned architecture". The README: "Both frameworks support importing from a Hugging Face pretrained checkpoint." and "After pruning, distillation is required to recover model accuracy."

### TRL: distillation into a student

Source: https://huggingface.co/docs/trl/main/en/gkd_trainer

```python
from trl.experimental.gkd import GKDConfig, GKDTrainer

model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen2-0.5B-Instruct")
teacher_model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen2-1.5B-Instruct")
training_args = GKDConfig(output_dir="gkd-model", per_device_train_batch_size=1)
trainer = GKDTrainer(
    model=model,
    teacher_model=teacher_model,
    args=training_args,
    processing_class=tokenizer,
    # dataset arguments: see the page
)
trainer.train()
```

`lmbda` sets the share of student-generated outputs and `beta` interpolates between forward and reverse KL divergence; the page reports that a high `lmbda` performed better and that the best `beta` depends on the task. The import path is under `trl.experimental`, so check it against the installed version.

## 4. Calibration data

1. Draw it from the task's distribution: the prompts, languages and formats the model will see. The GPTQ page defaults to `c4` and recommends the paper's dataset; for a model with one job, calibrate once on task text and once on the default, and choose between them on a development split, never on the held-out eval the gate reports.
2. Keep it out of the held-out eval, exact and near-duplicate; record the source, the sample count and the sequence length.
3. Start at the tool's documented size (512 samples at 2048 tokens for llm-compressor GPTQ) and raise it when accuracy drops before moving up a rung.

## 5. Quality gate

1. Run the person's held-out task eval on the uncompressed model, with the prompts and decoding settings the product uses. With sampling on, repeat it at least three times and take the spread as the noise floor.
2. Run the same eval on every candidate, in the runtime that will serve it.
3. Check what the task depends on and an average hides: long inputs, output format and JSON validity, tool calls, and every language the product serves.
4. Add a secondary signal: llama.cpp's `llama-perplexity` with `--kl-divergence-base` and `--kl-divergence` against the 16-bit logits (https://github.com/ggml-org/llama.cpp/blob/master/tools/perplexity/README.md), or a public task through lm-evaluation-harness, as the vLLM INT4 page runs it:

   ```bash
   lm_eval --model vllm \\
     --model_args pretrained="./Meta-Llama-3-8B-Instruct-W4A16-G128",add_bos_token=true \\
     --tasks gsm8k \\
     --num_fewshot 5 \\
     --limit 250 \\
     --batch_size 'auto'
   ```

   The perplexity README: "Note that perplexity is **not** directly comparable between models, especially if they use different tokenizers." A secondary signal never keeps a candidate the task eval rejects.
5. Keep the smallest candidate within the stated tolerance of the baseline. A loss smaller than the baseline's own spread is no difference; a loss larger than the tolerance sends you one rung up or back to a larger format.
6. Stop when a candidate passes, or when every rung that fits the budget failed: then keeping the uncompressed model, or naming the hardware it needs, is the complete answer.

## 6. Record

For the kept candidate and each rejected one: the base model and revision, its license, the method, the tool and version, the recipe or command, the calibration source, count and sequence length, the output hash, the observed size and peak memory, and every eval score beside the baseline's.
'''

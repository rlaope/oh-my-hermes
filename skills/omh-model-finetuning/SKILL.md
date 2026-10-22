---
name: "omh-model-finetuning"
description: "[omh] Fine-tuning a model on your own data -- SFT, DPO, RLVR or a LoRA adapter: decide first whether prompting or retrieval already closes the gap, choose the method from the data you have, and promote a checkpoint only when it beats the untuned baseline on a held-out eval. Use when the user says: model-finetuning, model finetuning, model fine-tuning, fine-tune a model, fine-tune the model, fine tune a model, fine tune the model, fine-tune."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: model-finetuning
    role: planner
    quality_tier: baseline-comparison-gated
    related_skills: [omh-model-optimization, omh-inference-serving, omh-llm-app-dev, omh-workflow-learning]
---

# Model Finetuning

This is a Hermes-native `model-finetuning` workflow skill.

## Why This Exists

`model-finetuning` exists because producing a model had no owner: `model-optimization` onboards a model into OMH, `inference-serving` serves one that exists, and `llm-app-dev` builds on top of one, while an SFT or DPO question reached `workflow-learning` with no baseline comparison and no way to answer that training is not needed.

## First Steps

- Ask what the untuned model and the best prompt score on the held-out examples before discussing any method.
- Ask what shape the data has -- demonstrations, preference pairs, or answers a program can check.

## Do Not Use When

- The ask is onboarding a new model generation into OMH's routing, calibration, or pricing; use `omh-model-optimization`.
- The ask is serving an existing model behind an endpoint or benchmarking that endpoint; use `omh-inference-serving`.
- The ask is building an application on top of a hosted model -- RAG, structured output, prompt versions; use `omh-llm-app-dev`.
- The ask is learning from an OMH run, a missed route, or a skill improvement candidate; use `omh-workflow-learning`.

## Examples

Good example:

- Prompt: should we fine-tune a model for our support replies or is a better prompt enough
- Expected behavior: Ask for the held-out examples and the current prompt's score, try few-shot and retrieval against them, and return `do_not_finetune` if one closes the gap; otherwise pick SFT from the reply demonstrations and gate promotion on beating the untuned baseline.
- Why: Most prompt-shaped gaps close without training, and training first hides that the cheaper fix was enough.

Bad example:

- Prompt: the fine-tuned checkpoint got 0.82 on our eval, ship it
- Expected behavior: Refuse to promote on a standalone score: run the same held-out eval on the untuned baseline and compare before promotion.
- Why: A score with no baseline cannot show the training helped at all.

## Completion Checklist

- The fine-tune decision is stated, and `do_not_finetune` was considered first.
- The method is chosen from the data's shape and its failure mode is named.
- The held-out split was drawn before training and checked for overlap.
- Promotion cites the same eval observed on the untuned baseline and the candidate.
- OMH ran nothing, and every score cites observed output or is marked unverified.

## Recovery Notes

- If no held-out eval exists, building one is the first step; say so before any training plan.
- If the candidate does not beat the baseline, keep the baseline serving and report the gap rather than retraining blindly.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `model-optimization`, `inference-serving`, `model-finetuning`, `research-brief`, `+26 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when someone wants to fine-tune a model on their own data, or is deciding whether to: supervised fine-tuning (SFT), preference tuning (DPO), reinforcement learning from verifiable rewards (RLVR), or a LoRA adapter. The output is a decision on whether to train at all, the method chosen from the data available, a training data plan with a held-out split, a comparison against the untuned baseline, and a checkpoint promotion gate; OMH trains nothing and runs no eval.

    Strong routing signals: `model-finetuning`, `model finetuning`, `model fine-tuning`, `fine-tune a model`, `fine-tune the model`, `fine tune a model`, `fine tune the model`, `fine-tune`, `fine tune`, `fine-tuning`, `fine tuning`, `fine-tuned model`, `fine-tuned checkpoint`, `finetune`, `finetuning`, `sft`, `supervised fine-tuning`, `dpo`, `direct preference optimization`, `rlvr`, `verifiable rewards`, `lora`, `qlora`, `lora adapter`, `preference data`, `untuned baseline`, `held-out eval`

## Catalog Metadata

Category: `planning`
Phase: `model-finetuning`
Hermes role: `planner`
Quality tier: `baseline-comparison-gated`
Reasoning demand: `standard`

Quality bar:

- Measure the untuned model and the cheaper fixes on the held-out eval before proposing any training.
- Load `references/finetuning-method.md` for the decision ladder, the method table, the data checklist, and the promotion procedure instead of recalling them.
- Choose the method from the data that exists, not from the method that is fashionable.
- Compare every candidate against the untuned baseline on the same eval, never against its own previous run alone.
- Keep prepared, trained, evaluated, and promoted as separate states for every checkpoint.

Handoff policy:

Keep the fine-tune decision, the method choice, the data plan, the baseline comparison, and the promotion gate in Hermes. Losses, eval scores, and comparisons are recorded only from executor, operator, or wrapper observed output; OMH never launches a training run, calls a model, or runs an eval.

Required inputs:

- the task the model fails at, and the held-out examples that show the failure
- what prompting, few-shot examples, or retrieval were already tried, and what they scored
- the data available: demonstrations, ranked or paired preferences, or answers a program can check
- the base model, its license, and the compute or provider the operator will train on
- observed eval scores for the untuned baseline and every candidate checkpoint

Expected outputs:

- finetune_decision/v1
- training_method_choice/v1
- training_data_plan/v1
- baseline_comparison/v1
- checkpoint_promotion_gate/v1

Artifact expectations:

- finetune_decision/v1 names the measured gap on the held-out eval and what prompting, few-shot, and retrieval scored against it, and returns `do_not_finetune` when one of them closes the gap -- a complete outcome, reached before any training step
- training_method_choice/v1 picks SFT, DPO, or RLVR from the shape of the data -- demonstrations, preference pairs, or a verifiable reward -- and full weights or an adapter, and names the failure mode of the method chosen
- training_data_plan/v1 names each source and its license, the dedupe and filtering, and a held-out split drawn before training and checked for overlap with the training set
- baseline_comparison/v1 runs the same held-out eval on the untuned baseline and each candidate, per metric, plus a regression check on general capability the task does not cover
- checkpoint_promotion_gate/v1 promotes a checkpoint only when it beats the untuned baseline by a stated margin with no regression past a stated tolerance, and otherwise keeps the baseline serving

Safety rules:

- Decide whether to fine-tune before any training step; `do_not_finetune` is a complete answer when prompting or retrieval closes the measured gap.
- Never promote a checkpoint on a standalone score; promotion needs the same held-out eval observed on the untuned baseline and on the candidate.
- Draw the held-out split before training and keep it out of the training data; an eval the model trained on proves nothing.
- Do not train on data whose license or consent does not permit it.
- OMH trains nothing, calls no model, and runs no eval; every loss, score, and comparison comes from observed output or is marked unverified.

## Runtime Evidence

Preferred harness for this skill: `research`.

```sh
omh runtime record --skill model-finetuning --harness research --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.

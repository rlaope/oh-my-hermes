# Model Finetuning

Load this on-demand contract after the compact `model-finetuning` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The ask is onboarding a new model generation into OMH's routing, calibration, or pricing; use `omh-model-optimization`.
- The ask is serving an existing model behind an endpoint or benchmarking that endpoint; use `omh-inference-serving`.
- The ask is building an application on top of a hosted model -- RAG, structured output, prompt versions; use `omh-llm-app-dev`.
- The ask is learning from an OMH run, a missed route, or a skill improvement candidate; use `omh-workflow-learning`.
- The ask is a smaller or cheaper copy of an existing network -- quantization, pruning, or distillation into a student whose goal is size; use `omh-model-compression`.

## Examples

Good example:

- Prompt: should we fine-tune a model for our support replies or is a better prompt enough
- Expected behavior: Ask for the held-out examples and the current prompt's score, try few-shot and retrieval against them, and return `do_not_finetune` if one closes the gap; otherwise pick SFT from the reply demonstrations and gate promotion on beating the untuned baseline.
- Why: Most prompt-shaped gaps close without training, and training first hides that the cheaper fix was enough.

Bad example:

- Prompt: the fine-tuned checkpoint got 0.82 on our eval, ship it
- Expected behavior: Refuse to promote on a standalone score: run the same held-out eval on the untuned baseline and compare before promotion.
- Why: A score with no baseline cannot show the training helped at all.

## Full Input, Output, and Artifact Expectations

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

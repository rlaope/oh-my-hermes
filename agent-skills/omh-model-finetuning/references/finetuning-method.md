# Fine-Tuning Method

Load this while planning a fine-tune. OMH prepares; the operator trains, evaluates and serves, and each step is `prepared` until its output is observed.

## 1. Decide whether to fine-tune at all

Climb the ladder in order, measuring each rung on the development split, and stop at the first rung that closes the measured gap:

| Rung | Try | Stop here when |
| --- | --- | --- |
| 1 | a clearer instruction and an output schema | the failure was an unstated requirement |
| 2 | few-shot examples in the prompt | the failure was format or style the examples show |
| 3 | retrieval over the source documents | the failure was missing or stale knowledge |
| 4 | a larger or newer base model | the failure was reasoning the current model lacks |
| 5 | fine-tuning | none of the above closed the gap, and the task is stable enough to be worth a trained artifact |

Rungs 1 to 4 return `do_not_finetune` with the score that closed the gap. Knowledge that changes weekly belongs in retrieval, not in weights.

Tune prompts and retrieval on a development split. The held-out set is touched only to report the baseline and the candidates, so a prompt fitted to it never becomes the number a checkpoint is promoted against.

## 2. Choose the method from the data

| Method | The data you have | Use when | Failure mode to watch |
| --- | --- | --- | --- |
| SFT | demonstrations: an input and the output you want | the target behavior can be written down | copies the demonstrations' errors and narrows general ability; breaks when the chat template or stop tokens differ from the serving path |
| DPO | preference pairs: a chosen and a rejected output for the same input | good and bad are easier to rank than to write | drifts from the reference model when pairs are noisy or one-sided |
| RLVR | inputs whose answers a program can check: tests, exact answers, a validator | correctness is verifiable and demonstrations are scarce | reward hacking: passes the checker without solving the task |

SFT first and DPO after is the common order when both kinds of data exist.

Distillation, training a smaller model on a larger model's outputs, is SFT on teacher outputs. The data plan names the teacher and whether its terms allow training on its outputs, and the comparison runs the teacher, the distilled student, and the untuned student on the same held-out eval. Pruning and quantization change existing weights and are not fine-tuning; OMH has no pruning workflow. A LoRA or other adapter trains a small set of extra weights: cheaper, swappable, and easy to roll back; train full weights only when an adapter measured short of the gap.

## 3. Training data checklist

1. Every source has a license or consent that permits training on it.
2. Deduplicate, and drop examples that contradict each other.
3. Draw a development split for the prompt, retrieval, and training trials and a held-out split that is touched only to report, both before training and from the same distribution as real traffic.
4. Check that no held-out example, or a near duplicate of one, is in the training set.
5. Record the counts per source and per split.
6. Scan the examples for personal data and credentials and remove or mask them: trained weights can emit what they saw, and consent to a file is not consent to a model that reproduces it.

## 4. Compare and promote

1. Run the same held-out eval, same prompt and same decoding settings, on the untuned baseline and on every candidate checkpoint.
2. Add a regression set for general capability the task does not cover.
3. Promote only when the candidate beats the baseline by the stated margin on the task metric and regresses no more than the stated tolerance elsewhere. State the held-out size and choose the margin from the baseline's run-to-run spread (repeat the baseline at least three times); a margin smaller than that spread, or measured on a few dozen items, is no difference.
4. Keep the baseline serving, and keep it as the rollback, until the promoted checkpoint's live metrics are observed.

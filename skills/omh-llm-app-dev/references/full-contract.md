# Llm App Dev

Load this on-demand contract after the compact `llm-app-dev` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The subject is comparing executors or agent harnesses - Codex against Claude Code against Hermes coding - rather than evaluating the product's own model calls; use `omh-agent-evaluation`.
- An agent run is already stuck, looping, or drifting and needs diagnosis; use `omh-agent-debug`.
- The subject is the harness's own context window, prompt caching, or token budget rather than the application being built; use `omh-context-budget-review`.
- The request is a prompt-injection, secret-handling, or dependency risk gate on work that already exists; use `omh-security-safety-review`.
- The feature makes no model call - the LLM is only mentioned as the subject being discussed - so this is a direct answer, not a build handoff.
- The ask is training the weights themselves on your own data -- SFT, DPO, RLVR, or a LoRA adapter; use `omh-model-finetuning`.

## Examples

Good example:

- Prompt: $llm-app-dev we are adding an invoice-field extractor that calls a model per upload - set it up so we can change the prompt later without guessing.
- Expected behavior: Name the rails, put the provider call behind one client module with a pinned model ID, declare the extraction schema and the repair path, lay the prompt out as a versioned file, and specify the golden set and validators that let the next prompt edit be compared against this baseline.
- Why: The feature is a real model call whose output another system consumes, which is exactly where an unpinned model, an inline prompt, and a missing golden set become expensive later.

Bad example:

- Prompt: $llm-app-dev the extractor is done - confirm the new prompt is better than the old one.
- Expected behavior: Prepare the paired baseline-vs-candidate comparison and state that no result exists until the run is observed; report nothing about which prompt is better.
- Why: Better is a claim about an observed run. Without one, the comparison is a design, and calling it a result is the false-green this workflow exists to prevent.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the feature the model is supposed to perform
- the exact provider and model ID under consideration
- the shape of the output the caller consumes
- the failing cases that must not regress

Expected outputs:

- rail decisions across provider boundary, structured output, prompt artifacts, retrieval grounding, evaluation
- the output schema and the validate-and-repair path for a response that does not match it
- the prompt artifact layout and its version identifier
- the eval deliverables - golden set, task-level validators, baseline-vs-candidate comparison
- the executor handoff and what stays unobserved until a run produces it

Artifact expectations:

- prompt files committed under version control with a version identifier the call site records, so a response can be traced to the prompt that produced it
- a golden set committed beside the code as data, not as prose in a chat log

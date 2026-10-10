# Loop Design Review

Load this reference before a loop starts, and whenever the user asks whether a loop they already run will hold. It settles four questions ahead of the first iteration: what result tells the loop it is finished, what the loop may not touch on the way to that result, who other than the builder decides an iteration passed, and where a person must sign before the loop changes its own rules. How a loop runs once launched is in the skill body and the other loop references; nothing here repeats it.

## Where This Review Starts

Two existing mechanisms come first and are named, not restated:

- `loopability_assessment/v1` (`src/workflows/loopability.py`) classifies the request, and loop start refuses a `direct_task` or a `needs_clarification` goal. This review runs only on a goal that assessment already called loopable; it does not classify again.
- A loop with a score follows the evaluation contract and its rule against editing the scoring harness in `references/measured-loop-discipline.md`. This review covers the loop that has no score, where nothing equivalent exists yet.

## Finish Line and Fence

A loop without a metric still needs a finish line a program can decide: one command whose exit status, or whose output compared against an expected file, says finished or not finished. A sentence such as "the module is clean" is not a finish line, because no run of anything settles it.

Write the fence in the same place as the finish line. The fence is the list of paths and definitions the loop may not edit while it chases the finish line: the tests and fixtures the command runs, the command itself, the gate and lint configuration, the CI workflow, and any pinned budget or count. Recording both in the loop's success criteria, side by side, means nobody reads one without the other.

A finish line with no fence is incomplete, because the cheapest route to a passing check is a weaker check: a removed or skipped test, a looser assertion, a mock that hides the failure, an error caught and dropped, a budget raised to fit. Each of those passes the command and defeats its purpose.

Prefer a finish line that compares against something the loop did not write - an expected output produced before the loop began, a total from the system of record, a generated file checked byte for byte against its producer. A check the loop authored can be satisfied by the same author.

Check the fence mechanically at judging time: list the files changed since the loop's starting commit with `git diff --name-only <start>..HEAD` and intersect that list with the fence. A non-empty intersection fails the iteration whatever the finish-line command returned.

A quick test of the pair: give the finish line and the fence to someone outside the work. They should be able to run one command, say finished or not, and name the files whose change would void that answer. If they cannot, the design is not ready.

## The Judge Is Not the Builder

The agent or session that decides an iteration passed is a different one from the agent that made the change. The judge reads the diff, runs the finish-line command itself, and checks the fence; the builder's own summary is narration, not evidence. Judging uses deterministic results only - exit codes, byte comparisons, type checks, diffs - and never an impression that the output looks right.

When no second agent or session is available, say so: the loop stops at its verification gate and reports the judge as unavailable instead of grading its own work.

Declare a retry cap before launch. After that many judged failures against the same finish line, the loop stops changing code and puts the next step to the user as a question.

## Loops That Rewrite Their Own Rules

Call a loop self-modifying when its edit set includes anything that defines what passing means or how the loop behaves: its own instructions or skill text, prompts, routing triggers, gate thresholds, the finish-line command, or the fence. Such a loop needs more human review than an ordinary one, and the review sits in front of the change, not after it. The loop prepares the rule change as a diff and stops; a person reads what the rule would become and approves it before any later iteration runs under it. Reviewing afterwards is too late, because every iteration since the change already ran under the new rule. Several of these targets sit inside the fence, and this approval is the only way past it: a change to a fenced path that no person approved still fails the iteration.

This rule is separate from memory capture. Project memory the model captures is admitted as `approved_auto_safe` with no human approve step, and that stays true: a captured memory informs later turns without redefining what passing means. The approval here applies only to a loop changing its own finish line, fence, gates, or instructions, and it adds no approve step to memory capture.

## Pre-Launch Failure Check

Walk the design through each item. Any item still open means the loop does not launch; report the open item to the user as the decision they own and offer its repair as the next step.

| Item | Open when | Repair |
| --- | --- | --- |
| Undecidable finish | the finish line is an adjective (clean, better, robust) rather than a command result | replace it with the command and the result it must produce |
| Self-grading | the builder judges its own iteration, or the judge reads the builder's report instead of rerunning the check | assign a separate judge that reruns the deterministic check |
| Unfenced check | a finish line exists with no list of paths the loop may not edit | write the fence beside the finish line and diff against it at judging time |
| Questions left for mid-run | the design expects the loop to stop and ask when an ambiguity appears; an unattended loop usually picks an answer instead | resolve open questions before launch (`deep-interview` when needed); for any that cannot be settled, name the observable condition in advance and have the loop record a blocked state when that condition appears, rather than relying on the loop to notice and ask |
| Stale working context | instructions, memory, or reference files the loop rereads every iteration disagree with the current tree; each iteration repeats the stale instruction again | list those files, check each against the tree before launch, and name who keeps them current |

## What the Review Produces

A short pre-launch record kept with the loop's success criteria: the finish-line command and its expected result, the fence list, who judges, the retry cap, whether the loop is self-modifying and where its approval point sits, and each failure-check item marked clear or open.

The record is prepared design, not an observed run. A clear check is not evidence the loop works, and no schema validates a fence or a judge assignment today; the review is a discipline the loop keeps in its own state, stated here so a reader does not assume enforcement exists.

## Attribution

The finish-line-with-fence pairing, the separate judge, the stricter review for self-modifying loops, and the pre-launch failure check adapt the loop-design-check skill from `affaan-m/everything-claude-code` (MIT). No upstream text is reproduced. OMH maps the ideas onto its own loopability assessment, loop success criteria, verification gate, and evidence vocabulary.

# Loop Design Review

Load this reference before a loop starts, and whenever the user asks whether a loop they already run will hold. It settles four questions ahead of the first iteration: what result tells the loop it is finished, what the loop may not touch on the way to that result, who other than the builder decides an iteration passed, and where a person must sign before the loop changes its own rules. How a loop runs once launched is in the skill body and the other loop references; nothing here repeats it.

## Where This Review Starts

Existing mechanisms come first and are named, not restated:

- `loopability_assessment/v1` classifies the request, and loop start refuses a `direct_task` or a `needs_clarification` goal. This review applies to any goal accepted at loop start, whatever state it was accepted under; it does not classify again.
- A north-star ambition is reframed by the skill body into a bounded arena, a next loop goal, and a next verification. This review applies to that loop goal, not to the ambition sentence.
- A recurring loop (a schedule or a heartbeat watch) has no finish line by design and ends on the stop condition its assessment records. The finish-line parts below do not apply to it; the fence, the judge, and the self-modification rule still do whenever its iterations edit files.
- A loop with a score keeps the evaluation contract, the keep and discard rules, and the Idea Exhaustion ladder in `references/measured-loop-discipline.md`. This review adds the fence and the judge to such a loop and changes none of those rules.

## Finish Line, Acceptance Check, and Fence

Two checks, at two levels:

- The **finish line** is what ends the goal: one command whose exit status, or whose output compared against an expected file, says the goal's stop criterion holds. Passing it is evidence for the linked goal completion gate, never a replacement for that gate.
- The **acceptance check** is per iteration: the queue item's `verification_plan`, the command the judge reruns for that one item. An item can pass while the loop is still far from its finish line.

A sentence such as "the module is clean" settles neither, because no run of anything decides it. Where the skill body already lets the model reframe a goal, the model rewrites such a sentence into a command and the result it must produce.

Write the fence in the same pre-launch record as the finish line. The fence lists the paths each verdict rests on, as they stood at the start: the existing tests and fixtures the checks run, every file a recorded command executes (a check script, a wrapper, a Makefile target's recipe file), the gate and lint configuration, the CI workflow, and every budget or limit a person set by hand. The commands themselves live in the record rather than in a path; changing a recorded command is a rule change and takes the approval route below.

A finish line with no fence is incomplete, because the cheapest route to a passing check is a weaker check: a removed or skipped test, a looser assertion, a mock that hides the failure, an error caught and dropped, a budget raised to fit. Each of those passes the command and defeats its purpose.

What the fence does not hold:

- **Additions.** A new test or fixture usually does not weaken a verdict that existed at the start, so an added file under a fenced directory does not fail the listing step. Usually is not always: a new runner hook file at any depth, or a new test module that patches shared code when it is imported, can weaken existing verdicts. So a file whose mere presence changes how existing checks run goes on the fence as absent at the start - by path, or by file-name pattern under a root (`conftest.py`, the runner's configuration file names, `__init__.py` under the test roots) - and its appearance fails; and the judge reads every added file under a fenced directory, failing one that patches, skips, or reconfigures an existing check.
- **Derived pins.** A generated file or pinned digest the repository re-derives from a producer stays off the fence. The loop may move it by rerunning the producer, and the judge reruns the producer's own check to confirm the bytes. A hand-set budget or reviewed limit is on the fence; moving one takes the approval route.
- **The task's own subject.** A loop whose job is to change a particular test leaves that test off the fence and says so in the record; the judge's review then covers that file.

Prefer a finish line that compares against something the loop did not write - an expected output produced before the loop began, a total from the system of record, a generated file checked byte for byte against its producer. A check the loop authored can be satisfied by the same author.

## Checking the Fence

The pre-launch record names the starting commit by its full SHA, never by a branch name, because a branch moves. At launch it also records, for every fence entry that `git ls-files --error-unmatch <path>` reports as untracked and every entry outside the repository, the entry's sha256; for every fenced submodule, its commit from `git -C <sub> rev-parse HEAD`; for every pattern entry recorded as absent, the matches present at launch; and, where the test runner can list its collected tests without running them, that list.

At judging time, run these steps from the repository root, in order:

1. **Resolve the start.** Use the recorded SHA. After a rebase, the start is the rebased copy of the most recent approved re-anchor commit, or the new base when there is none; record the old SHA beside the new one.
2. **List tracked changes.** Run `git -c core.quotePath=false diff --no-renames --name-status <start-sha>`. It compares the working tree, staged and unstaged edits included, against the start; `--no-renames` reports a moved file as a deletion plus an addition, so a renamed test still shows its old path, and `core.quotePath=false` prints non-ASCII paths as they are written in the fence.
3. **List untracked files.** Run `git -c core.quotePath=false ls-files --others --exclude-standard`. Ignored files do not appear here, which is why step 5 exists.
4. **Match against the fence.** An entry matches a path equal to it or below it by whole path components, so `tests` covers `tests/a.py` and not `tests_old/a.py`; a pattern entry matches that file name at any depth under its root. A fenced path with any status other than `A` fails.
5. **Check absent entries directly.** For every entry recorded as absent at the start, run `test -e <path>`; for a pattern entry, list its matches under the root with `find` and compare against the matches recorded at launch. Any new match fails, gitignored or not.
6. **Check hashed and submodule entries.** Recompute the sha256 of each hashed entry, and for each fenced submodule compare `git -C <sub> rev-parse HEAD` with the recorded commit and require `git -C <sub> status --porcelain` to print nothing. Any difference fails.
7. **Read the additions.** Read every added or untracked file under a fenced directory; one that patches, skips, or reconfigures an existing check fails. Where a collected-test list was recorded, list again: a test present at the start that is no longer collected, or now reports skipped, fails.

The iteration fails, whatever the acceptance check returned, when any step fails.

After a person approves a fenced change, commit that change on its own and record that commit's SHA as the new start, together with the approval. Later iterations then diff from the approved state instead of failing on a change already accepted.

## The Judge Is Not the Builder

The agent or session that decides an item's acceptance is not the one that made the change. On Hermes the usual second session is a `delegate_task` subagent or the loop's reviewer lane. The judge reruns the acceptance check itself, runs the fence check, and reads the diff; the builder's own summary is narration, not evidence.

The pass verdict rests on deterministic results: exit codes, byte comparisons, type checks, the fence steps. A review of the diff is a judge input as well - a finding can fail an iteration that a green check would have passed - but a review never passes an iteration whose deterministic check failed. A scored loop's per-cycle keep or discard is not an acceptance verdict: the metric command decides it under the measured-loop rules in the same session, with the fence check run on every cycle as one more deterministic command. The separate judge is required where an item's acceptance is decided, including the point where a scored loop's kept result is offered as evidence for the goal.

When no second agent or session is available for an acceptance verdict, say so: the item stays unjudged and the loop stops at its verification gate rather than grading its own work.

Declare a retry cap before launch. It counts judged failures of the same item's acceptance check. Reaching it ends retries of that approach, not the run: the loop climbs the exhaustion ladder the skill already keeps - re-read the scoped files, recombine the near misses, try a more radical change, and for a scored loop the Idea Exhaustion steps - and only when that ladder is spent records the item blocked with its reason. What follows a blocked item, another item or a stop at that gate, is the skill body's progress rule, not this reference's.

## Loops That Rewrite Their Own Rules

Call a loop self-modifying when its edit set includes anything that defines what passing means or how the loop behaves: its own instructions or skill text, prompts, routing triggers, gate thresholds, a recorded finish-line or acceptance command, or the fence. Such a loop needs more human review than an ordinary one, and the review sits in front of the change, not after it. A rule change is a follow-up that needs new authority under the skill body's own rule: the loop prepares it as a diff and ends the turn by naming it and asking for approval, and no later iteration runs under the new rule until a person has read what it would become and approved it. Reviewing afterwards is too late, because every iteration since the change already ran under the new rule.

Several of these targets sit inside the fence, and this approval is the only way past it: a change to a fenced path that no person approved still fails the iteration, and an approved one re-anchors the start as described above. For a scored loop, an approved change to the evaluation contract also starts a new baseline, as the measured-loop reference requires.

This rule is separate from memory capture. Project memory the model captures is admitted as `approved_auto_safe` with no human approve step, and that stays true: a captured memory informs later turns without redefining what passing means. The approval here applies only to a loop changing its own finish line, acceptance checks, fence, gates, or instructions, and it adds no approve step to memory capture.

## Pre-Launch Failure Check

Walk the design through each item before the first iteration. A direct loop invocation still starts the loop: the model repairs an open item itself wherever the skill already lets it - reframing an adjective goal into a decidable loop goal, drafting the fence from the files the checks read, recording the start SHA - and notes the repair in the record. Only a repair that needs the user's own choice, such as whether a self-modifying edit set is wanted or which outside result counts as finished, becomes one gate question, asked before the first iteration that depends on it. A recurring loop skips the first item.

| Item | Open when | Repair |
| --- | --- | --- |
| Undecidable finish | the finish line or an item's acceptance check is an adjective (clean, better, robust) rather than a command result | reframe it into the command and the result it must produce |
| Self-grading | the builder decides its own item's acceptance, or the judge reads the builder's report instead of rerunning the check | assign a separate judge, such as a delegated subagent or the reviewer lane, that reruns the deterministic check |
| Unfenced check | a finish line or acceptance check exists with no fence, or the record has no start SHA or launch hashes | write the fence beside the finish line, record the start SHA and the launch hashes, and run the fence steps at judging time |
| Questions left for mid-run | the design expects the loop to stop and ask when an ambiguity appears; an unattended loop usually picks an answer instead | resolve open questions before launch (`deep-interview` when needed); for any that cannot be settled, name the observable condition in advance and have the loop record a blocked state when that condition appears, rather than relying on the loop to notice and ask |
| Stale working context | instructions, memory, or reference files the loop rereads every iteration disagree with the current tree; each iteration repeats the stale instruction again | list those files, check each against the tree before launch, and name who keeps them current |

## What the Review Produces

A short pre-launch record kept with the loop's success criteria: the start SHA and any re-anchors with their approvals; the finish-line command and its expected result, or the recurring stop condition; how each item's acceptance check is chosen; the fence list with its absent-at-start and pattern entries, the sha256 of every entry untracked at launch or outside the repository, each fenced submodule's commit, and any collected-test list; who judges; the retry cap; whether the loop is self-modifying and where its approval point sits; and each failure-check item marked clear, repaired, or open.

The record is prepared design, not an observed run. A clear check is not evidence the loop works, and no schema validates a fence or a judge assignment today; the review is a discipline the loop keeps in its own state, stated here so a reader does not assume enforcement exists.

## Attribution

The finish-line-with-fence pairing, the separate judge, the stricter review for self-modifying loops, and the pre-launch failure check adapt the loop-design-check skill from `affaan-m/everything-claude-code` (MIT). No upstream text is reproduced. OMH maps the ideas onto its own loopability assessment, loop success criteria, queue verification plans, verification gate, and evidence vocabulary.

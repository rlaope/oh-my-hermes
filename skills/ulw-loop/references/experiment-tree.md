# Experiment Tree

Load this reference when a measured loop compares variants of code or configuration, such as training runs, evals, benchmarks, or sweeps, and each attempt can live on its own branch. `measured-loop-discipline.md` decides whether one attempt is kept. This reference decides where each attempt sits and what it may differ in, so results stay comparable across many attempts.

## Nodes and the fixed run contract

- The tree starts with a root node. The root holds the baseline code and the one run command that trains or evaluates and prints the metric.
- Every other node is a branch made from its parent. It inherits the parent's code and the same run command.
- The run command and the environment it runs in are fixed for the whole tree. Every node runs the same command with the same environment variables.
- A node differs from its parent only in committed code or config on its own branch. A hyperparameter goes into a config file on that node's branch. It never goes into the command line or an env prefix such as `LR=3e-4 python train.py`.
- If the run contract truly has to change, start a new root with a new baseline, as the evaluation contract rule in `measured-loop-discipline.md` already requires. Results under the old contract are never compared with results under the new one.

## Provisional, then frozen

- A node is provisional until a run answers its question. While provisional, fix its setup on its own branch: missing dependencies, a wrong path, a crash before the metric prints. Those fixes are repairs, not new nodes.
- A node freezes the moment a run reports its metric. This applies to the root too. A frozen node's branch is never edited again. A disappointing result is still a result.
- To try a new idea on top of a frozen node, branch a child and edit the child.
- Repair limit: when two runs in a row on one node answer nothing, stop and ask instead of repairing a third time. When the same failure hits a second node, treat it as one setup problem and ask once.

## Shape: a small fan per decision, then descend

Before making X a child of Y, name what Y established that X builds on.

- If you can name it ("Y is the learning-rate winner; X keeps that rate and changes the architecture"), X is a child of Y.
- If you cannot, because X and Y are options of the same open decision (rate 2e-5 against rate 3e-5), they are siblings under one shared parent.

Width is the open options of one decision. Depth is decisions already resolved, one level per kept winner. A new round hangs off the previous round's winner, never off the root.

| Shape | What it looks like | Why it fails |
| --- | --- | --- |
| Flat fan | every variant is a direct child of the root | every result is measured against the start, so wins never stack |
| Chain | a long single-child line | co-equal options were stacked as if each built on the last |
| Stacked fans | a few siblings per decision, the next round under the winner | correct |

Re-read the tree at the start of each round. A wide row of root children with no grandchildren means you are fanning when you should descend.

## After each completed run

Pick one move and record it in the ledger row's description:

| Move | When |
| --- | --- |
| repair | the run answered nothing; fix the provisional node and run it again, within the repair limit |
| refill | the result is inconclusive or worse; run the next queued sibling of the same decision |
| promote | the result is a clear win beyond noise; it becomes the parent of the next round |
| stop | the goal is met, or the branch is exhausted |

Stop a line of work after about three runs in a row that fail or regress against their parent, then climb the idea-exhaustion ladder in `measured-loop-discipline.md`. When the loop stops, write the tree as an artifact: each node's branch, parent, what it changed, its metric, and its move.

## Ledger columns this adds

Add `node`, `parent` and `move` to the experiment ledger beside the existing columns. The `commit` column of a frozen node stays the commit that run measured.

## What this does not change

- The permission profile still gates every branch, commit and run. A tree is not authority to launch compute.
- A metric win is still `prepared_not_observed` until an evidence ref exists, and the goal closes only on linked `goal_ledger/v1` evidence.
- OMH validates no tree field. The tree is a discipline the loop keeps in its own state, and no gate rejects a loop that edits a frozen branch.

## Attribution

The experiment-tree discipline adapts practices of the `alphaXiv/OpenResearch` project (MIT). No upstream text is reproduced. OMH maps them onto its own loop ledger, evaluation contract, and evidence states.

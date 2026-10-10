# Execution Rulings and Review Rounds

Load this reference while an accepted `ultrawork` plan is executing and a question comes up that the plan does not answer, or when a review sends work back. It covers three things: which mid-run questions the coordinator settles itself and how that settlement is recorded, how many review rounds a change gets and who runs them, and which earlier evidence a later increment may keep.

Nothing here widens what the run is allowed to do. The engine entry confirmation, the follow-up authority rule, the handoff risk scan, executor readiness, and every approval a lane reference asks for keep applying exactly as written.

## Settle Small Questions Without Stopping

An accepted plan leaves gaps: a helper needs a name, two internal structures would both satisfy the acceptance criteria, the plan text and a lane's acceptance criterion read differently on a detail neither one decides. Waiting for the user on such a gap parks the run for a choice the user delegated by accepting the plan. Decide it, write the decision down, and keep working.

A ruling is allowed only when all of these hold:

- The choice stays inside the scope, write sets, and authority the user already accepted.
- It can be undone inside the worktree by a later edit.
- It changes no acceptance criterion, verification command, lane owner, or lane scope the user accepted.
- The accepted plan, its spec, or the repository's existing conventions point toward an answer, even if none states it outright.

Typical rulings: naming, internal module layout, the order of independent edits, how a test is organised, which of two equivalent internal approaches to use, how to read an ambiguous sentence in the plan.

## Decisions That Still Belong to the User

Some choices are never a ruling. Each of the following is a decision the user owns, the same stop that ends a turn in every OMH skill, and the run stops at it:

- An irreversible or destructive step: deleting data or history, rewriting shared history, or anything the worktree cannot restore.
- A security-sensitive step: credentials, permissions, access control, or anything the handoff risk scan routes to confirmation.
- A side effect outside the worktree: pushing, merging, publishing, deploying, filing on a shared tracker, or messaging people.
- An accepted plan that cannot be carried out as written, where every way forward is a guess and nothing in the plan, the spec, or the repository chooses between them.

These four are cases of that one rule, not its full extent. A follow-up that needs new authority, widens the scope, or changes external state not already authorized is described first and started only on approval, as the ulw-work quality bar already requires; any step this skill or its references say to ask about, wait on, or stop at stays a stop. Where it is unclear whether a choice qualifies as a ruling, it does not: treat it as the user's.

At one of these stops, record the blocker as a ledger field and not as a sentence in the reply: `omh goal blocker --goal <id> --summary <what is blocked> --missing-authority <what the user must decide>` when a goal ledger is open. Then end the turn with the next action offered as a question that carries the user's choices.

## Recording a Ruling

Each ruling is one line in the run's existing evidence ledger:

```
Ruling: <decision> — <reason> — <cost if wrong>
```

- **Decision**: what was chosen, specific enough that someone else could undo it.
- **Reason**: the plan line, spec clause, or repository convention the choice leans on.
- **Cost if wrong**: what has to be redone if the user later disagrees, so the user can judge how far to look.

When a `goal_ledger/v1` ledger is open, append the line as a checkpoint that cites no criterion: `omh goal checkpoint --goal <id> --status in_progress --summary "Ruling: ..."`. The checkpoint stamps its `observed_tree`, which ties the ruling to the tree it was taken against. A ruling satisfies no acceptance criterion and counts as no evidence. When a ruling's cost if wrong is material, the closing brief names that choice in the user's words, not as the ledger line, so the user can overturn it without reading the ledger.

## Review Rounds

A finding blocks when it cites an acceptance criterion the evidence fails, or a blocking definition the review applies (the repository's `REVIEW.md` mapped onto `P0`/`P1`, as `code-review` does). A review that returns blocking findings starts a fix round: the implementing lane fixes them, reruns the covering checks, and reports with pasted output, and then a reviewer looks again. Each reviewed change gets the first review plus at most two re-reviews, so at most two fix rounds. That is the same cap the delegation protocol already gives each reviewer prompt.

- **A new reviewer each time.** A re-review goes to a reviewer that has not reviewed this change before. A reviewer asked again tends to defend its earlier verdict. Give the new reviewer the range since the last review, the blocking findings that review cited, and the criteria already approved, which stay closed unless the fix touched them.
- **Reviewers are dispatched by the coordinator.** A lane never starts its own reviewer, and a review a lane commissioned is not review evidence. If a lane report shows it spawned one, report that in the run status as a defect of that lane, and dispatch the real review as planned.
- **After the second re-review**, stop dispatching reviewers. Blocking findings that are still open are reported to the user with their evidence, as a decision the user owns. A ruling never closes one, and none of them is counted as passed.
- Findings that do not block are notes. Fix them, or record why they stay; they never open another round.

## Reusing Evidence Between Increments

Rerunning every check after every small edit spends the run on checks that cannot have changed. Each captured result therefore names the tree it ran against (`observed_tree`) and what it exercised: the command, and the files or scenarios it covers.

After an increment, rerun a check when anything it covers changed between its `observed_tree` and the current tree: a file it exercises, a module that imports one of those files, its dependencies, or its environment. For every other check, cite the earlier capture instead of running it again. When it is unclear what a check covers, rerun it.

Reuse is a scheduling aid inside the run and never proof of completion. Before the closing brief, the whole set runs once more against the final tree: every scenario, the full test suite, and the build or type checks the repository keeps. That final run is the completion evidence, and it is the same full-suite run the red/green contract and the verification fan-in already require. `quality_evidence_assessment/v1` classifies any observation stamped with another tree as `stale_tree`, so a reused capture could not stand in for it anyway.

## Defects Outside the Blast Radius

The blast radius of a change is what it touched: the requested behavior, regressions it introduced, proofs it relies on, and failing tests or stale docs in code it edited. Defects inside it are fixed in this run, within the accepted scope; a fix that would widen that scope is a follow-up under the authority rule.

A defect found outside the blast radius is not fixed on the side. Record it in the evidence ledger with the steps that reproduce it and the output that shows it, name it in the closing brief, and offer to file it as a tracked issue. Filing on a shared tracker changes external state, so it waits for approval unless filing was already authorized. A deferred defect never turns an acceptance criterion it touches into a pass: the criterion stays open and is reported as open.

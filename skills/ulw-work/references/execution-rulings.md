# Execution Rulings and Review Rounds

Load this reference while an accepted `ultrawork` plan is executing and a question comes up that the plan does not answer, or when a review sends work back. It covers three things: which mid-run questions the coordinator settles itself and how that settlement is recorded, how many review rounds a change gets and who runs them, and which earlier evidence a later increment may keep. The coordinator is whoever leads the run: the parent session, or the campaign orchestrator when the user selected `campaign-orchestrator` mode.

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

- An irreversible or destructive step: deleting data or history, rewriting shared history the user has not already authorized, or anything the worktree cannot restore.
- A security-sensitive step: credentials, permissions, access control, or anything the handoff risk scan routes to confirmation.
- A side effect outside the worktree that the user has not already authorized: pushing, merging, publishing, deploying, filing on a shared tracker, or messaging people.
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

Keep the line under 240 characters, the ledger's summary limit; longer detail goes in `--notes-summary`.

When a `goal_ledger/v1` ledger is open, append the line as a checkpoint that cites no criterion: `omh goal checkpoint --goal <id> --status in_progress --summary "Ruling: ..."`. The checkpoint stamps its `observed_tree`, which ties the ruling to the tree it was taken against. A ruling satisfies no acceptance criterion and counts as no evidence. When a ruling's cost if wrong is material, the closing brief names that choice in the user's words, not as the ledger line, so the user can overturn it without reading the ledger.

## Review Rounds

The coordinator classifies each finding by this rule, not by the label the reviewer gave it: a finding blocks when it cites an acceptance criterion the evidence fails, or a blocking definition the review applies (the repository's `REVIEW.md` mapped onto `P0`/`P1`, as `code-review` does). A review that returns blocking findings starts a fix round: the implementing lane fixes them, reruns the covering checks, and reports with pasted output, and then a reviewer looks again. Each reviewed change gets the first review plus at most two re-reviews, so at most two fix rounds.

- **A new reviewer each time.** A re-review goes to a reviewer that has not reviewed this change before; when the plan names a person or a specific reviewer as the review owner, that means a new reviewer instance under the same review owner. A reviewer asked again tends to defend its earlier verdict. Scope the new reviewer to what is still open: criteria earlier rounds approved are listed as closed and reopen only if the fix touched them, the open blocking findings are named, and only the commits made since that review are in range.
- **Reviewers are dispatched by the coordinator.** A lane never starts its own reviewer, and a review a lane commissioned is not review evidence. If a lane report shows it spawned one, report that in the run status as a defect of that lane, and dispatch the real review as planned.
- **After the second re-review**, stop dispatching reviewers. Blocking findings that are still open are reported to the user with their evidence, as a decision the user owns. A ruling never closes one, and none of them is counted as passed.
- Findings that do not block are notes. Fix them, or record why they stay; they never open another round.

## Reusing Evidence Between Increments

Rerunning every check after every small edit spends the run on checks that cannot have changed. Each captured result therefore records what it exercised (the command, and the files or scenarios it covers), its `observed_tree`, and a commit to diff from: `HEAD` on a clean tree, or on a dirty one the sha `git stash create` prints. The `observed_tree` stays the identity stamp; on a dirty tree it is a content hash that says whether two captures saw the same content, not what differs, so the diff runs against the recorded commit.

After an increment, diff that commit against the current tree. A check reruns when its environment or dependency set moved, or when the diff reaches a file it exercises or anything importing such a file; an untracked file it covers counts as changed. For every other check, cite the earlier capture instead of running it again. When it is unclear what a check covers, rerun it.

Reuse is a scheduling aid inside the run and never proof of completion. Before the closing brief, the whole set runs once more against the final tree: every scenario, the full test suite, and the build or type checks the repository keeps. That final run is the completion evidence, and it is the same full-suite run the red/green contract and the verification fan-in already require. When `quality_evidence_assessment/v1` is assessed against the current tree, it classifies any observation stamped with another tree as `stale_tree`.

## Defects Outside the Blast Radius

The blast radius of a change is the code it edited and what rests on it: a test or doc of that code now failing or stale, a proof the change leans on that does not hold, a regression the change caused, and the requested behavior itself when it is not delivered. Defects inside it are fixed in this run, within the accepted scope; a fix that would widen that scope is a follow-up under the authority rule.

A defect found outside the blast radius is not fixed on the side. Record it in the evidence ledger with the steps that reproduce it and the output that shows it, name it in the closing brief, and offer to file it as a tracked issue. Filing on a shared tracker changes external state, so it waits for approval unless filing was already authorized. A deferred defect never turns an acceptance criterion it touches into a pass: the criterion stays open and is reported as open.

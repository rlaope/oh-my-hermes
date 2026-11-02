# Artifact shapes

Load this when the decision question is about logic or state, about an interaction or layout, or when the receipt may let later work reference the prototype code. The question picks the shape, and the wrong shape spends the budget on an artifact that cannot answer it. A question that fits neither shape keeps the artifact kinds `prototype_smallest_artifact_check` lists.

Every shape below is built inside the declared scratch boundary. When the artifact belongs inside the real application, that boundary is a temporary worktree of the repository, never the working tree the user is editing.

## Logic or state question

The question sounds like "does this state model refuse that sequence" or "can this data shape represent that case".

- Put the decision-bearing logic in one pure module: no I/O, no UI, and no clock, randomness, or network it was not handed as an argument. A thin driver (a script, a CLI loop, a page) calls into the module and nothing calls out of it. The module is the part a later accepted plan may lift; the driver is discarded.
- Pick the module's form from the question: a reducer over discrete actions, an explicit state machine when which actions are legal right now is part of the question, or plain functions over a data type when there is no current state.
- After every action, the driver prints the full relevant state, labelled in the domain's own words, and marks what changed, so the observation ledger quotes state instead of narrating it.
- Keep state in memory. Persistence enters only when persistence is the question, and then as a scratch store inside the boundary whose name says it is a prototype.
- Start it with one command, written into the prepared handoff.
- Script the runs the hypothesis turns on: the expected path, the awkward edge case, and one sequence that should be refused. Each run starts from a reset to the same initial state, so a rerun observes the same thing.

## Interaction or layout question

- Build at least two variants and at most five, differing in structure: layout, information hierarchy, or primary action. Variants that differ only in colour, spacing, or copy cannot settle a layout question; when two come out alike, rebuild one with the shared structure ruled out.
- Mount the variants in the real host page or route, with its navigation, density, and data loading in place. A blank route makes every variant look acceptable. Use a new route only when no existing page could host the thing, follow the project's own routing convention, and name the route as a prototype.
- Only the rendered part differs per variant; the data loading and access checks above it stay as they are. Switching needs no rebuild (a query parameter or a development-only switch), and the switch never reaches a production build.
- Stub every write: a variant never performs a real mutation, because the question is how the surface is read and used, not whether the backend works. The data shown follows the skill's fixture rule: synthetic or development data unless the user approved real data for this run.
- The measurement names the target task and what counts as better (completion, errors, the variant the user picks and why). Record picks per variant; a mixed answer, such as one variant's header with another's list, is recorded as that, not rounded to one variant.

## Keeping the code

- When the receipt lets later work reference the prototype code, commit it on a named throwaway ref: the temporary worktree's own branch, named for the decision id (for example `prototype/<decision_id>`) and declared with the scratch boundary. The receipt cites the ref and the commit.
- The ref is never merged and never becomes the default branch. Pushing it to a remote is external publication and goes through the existing approval gate.
- Removing the worktree directory is the cleanup to observe; `discarded` then means the scratch boundary was cleaned, while the ref keeps the evidence. Without reference permission, the branch is deleted with the worktree and the cleanup observes both.
- A later accepted plan lifts the pure module or rebuilds the chosen variant to production standard; it never merges the prototype branch.

## Attribution

The three shapes adapt ideas from Matt Pocock's `prototype` skill (`SKILL.md`, `LOGIC.md`, `UI.md`) at `mattpocock/skills@24fe0ef7737efae15c87225755e9f6f5965e4888`, MIT License, Copyright 2026 Matt Pocock. OMH keeps its own scratch boundary, observation ledger, and receipt, and does not take the upstream single-file demo page or variant switcher bar.

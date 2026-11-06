# Decision Records

The full contract for durable decision records: when a decision earns one,
what the file looks like, how its status moves, and what each stage's review
checks. A drafted record is a proposal - nothing is written until the user
approves the write.

## The three-condition trigger

A decision deserves a record only when all three hold:

1. **Hard to reverse** - undoing it costs a migration, a rewrite, or a
   renegotiation, not a revert.
2. **Surprising without its context** - a competent newcomer would ask "why
   on earth is it done this way?" and the answer is not in the code.
3. **A real trade-off** - a viable alternative was genuinely given up, with
   costs the team accepted.

Two of three or fewer: no record - the decision note in the chat brief is
enough. Version bumps, bug fixes, implementation details, and routine
configuration never qualify on their own.

## The file convention

Records live in `docs/adr/`, one file per decision, named
`NNNN-short-slug.md` with a zero-padded sequence number, plus an index
`README.md` listing number, title, status, and date. Each record carries, in
order:

- **Status** - one of the lifecycle states below, with the date.
- **Context** - the situation that forced a decision; written so it still
  makes sense after the people involved are gone.
- **Drivers** - the requirements and constraints that actually decided it,
  marked must-have or should-have.
- **Considered Options** - every option that was viable, each with honest
  pros and cons; an options list with one entry is a press release, not a
  record.
- **Decision** - what was chosen, in one sentence, with the version or
  variant pinned.
- **Consequences** - positive and negative, and for each accepted risk the
  mitigation that was agreed; a consequences section with no negatives has
  not been finished.
- **Related** - links to the records this one complements, depends on, or
  supersedes.

## Lifecycle

`Proposed -> Accepted -> Deprecated | Superseded`, with `Rejected` as a
terminal branch from Proposed.

- **Proposed** - under discussion; the only state in which the text may
  still change.
- **Accepted** - decided and binding. An accepted record is never edited:
  changing the decision means a new record that names the old one, and the
  old record's status moves to Superseded with a forward link.
- **Deprecated** - no longer relevant (the system it governed is gone), with
  the reason recorded.
- **Superseded** - replaced; the record stays in the tree as history.
- **Rejected** - considered and not adopted, kept with the reasons. Rejected
  records are the corpus `omh-decision-recall` reads before the team re-litigates
  an alternative; deleting one deletes the warning.

## Review checklists

Before submission: the three-condition trigger holds; Context stands alone;
every viable option is listed with honest cons; consequences include
negatives with mitigations; related records are linked.

During review: the affected owners were consulted; reversibility was
assessed; cost and security implications are stated or explicitly out of
scope.

After acceptance: the index row is added; the status and date are set;
follow-up work is captured as tasks, not left inside the record.

## Boundary

A drafted record, index row, or status change is prepared context until the
user approves the write and the file change is observed; a record documents
a decision and is never evidence that the decided work was implemented,
reviewed, or merged.

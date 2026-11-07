# Commit and PR Conventions

Load this while drafting a commit message or a pull-request body. OMH writes the text only: the commit, the push, and opening the PR are the user's or the executor's, and nothing here runs a command.

## 1. Read the convention before writing

| Source | What to take from it | When it is missing |
| --- | --- | --- |
| PR template (`.github/pull_request_template.md`, `.github/PULL_REQUEST_TEMPLATE/`, `docs/`) | the section headings, in order, and any checkbox list | say no template was found and use a plain summary, why, validation, and reversibility (section 4) |
| Recent log (`git log -20 --no-merges --format='%an <%ae>%n%B%n---'`, skipping bot authors; in a squash-merge repository also the merged PR titles, `gh pr list --state merged -L 10 --json title`) | subject shape (imperative, `type(scope):`, ticket prefix), body width, trailer set | say the log is empty or unreadable, and do not import a convention |
| Contributor docs (`CONTRIBUTING.md`, `AGENTS.md`) | sign-off rule, required trailers, forbidden lines | record the rule as not found |

Record what was read and what was not in `repo_convention_read/v1`. A convention the repository does not use is not a default to fall back on.

## 2. The evidence ledger

Every command the change mentions gets one row before any text is written.

| Field | Content |
| --- | --- |
| Command | as run, with arguments |
| State | `observed` or `not_observed` |
| Result | exit status and the line that shows it, for `observed` only |
| Where seen | terminal output, CI job, or wrapper record |
| Reason | for `not_observed`: skipped, prepared only, blocked, or out of scope |

A row is `observed` only when a run record exists. "It should pass", "CI will run it", "I ran it earlier on another branch", and "the same tests passed yesterday" are all `not_observed`. Wording never promotes a row.

## 3. Projecting the ledger into the text

- `Tested:` (or the template's validation checklist) lists exactly the `observed` rows, each with what it showed.
- `Not-tested:` lists every `not_observed` row with its reason. An empty `Not-tested:` is a claim that nothing was skipped; write it only when that is true.
- A checkbox in a PR template is checked only for an `observed` row.
- CI state, review state, and merge state are stated only when observed; otherwise say which of them has not happened yet.
- A subject prefix that claims a state (`[verified]`, `[reviewed]`, `[tested]`) is one more projection. It needs two things: the recent log uses that prefix, and the ledger holds the `observed` row it claims, which for a review is the reviewer's own verdict, not the author's. Missing either, leave it off. It is never a default, and a prefix on an earlier commit says nothing about this one.

## 4. Subject and body

- Subject: the repository's shape, the change's effect, within the length the log uses.
- Body: why the change exists and what is now true, not a restated diff. Measured before/after values belong here when the change is about a measurement.
- In a PR body, when the change reshapes structure (files moved, a module split, a call path rerouted), show the smallest view of the new shape: a short file tree, a call tree, or a diff sketch of either, holding only the nodes the change touches and the ones needed to place them. A picture the reader can check in ten seconds replaces a paragraph that restates the diff.
- Reversibility: in a PR body always, in the no-template fallback or under a section the template already has for risk or rollout (never as a heading the template lacks; when the template has neither a risk nor a rollout section, one sentence at the end of its summary or description section); in a commit message only when the recent log already carries a risk or rollback line or trailer (such as `Scope-risk:`). Say whether a revert undoes the whole change, or name what it leaves behind, such as persisted data, an applied migration, a published package or artifact, a sent message, or a changed external setting. Then name which surfaces a bad merge would reach. That one-way door is the fact that should slow a merge, so state the answer even when it is "a revert undoes all of it".
- `Closes #N` goes on its own line, and only when every success criterion of that issue is met; otherwise `Refs #N`. GitHub needs the keyword per issue (`Closes #1, #2` closes only #1) and acts only when the change reaches the default branch. In a squash-merge repository the PR body becomes the commit message, so trailers belong in the last paragraph block of the body.

## 5. Trailers and sign-off

| Trailer family | Example | Rule |
| --- | --- | --- |
| DCO | `Signed-off-by: Name <email>` | add only when the repository requires it, with the configured author |
| Decision trailers | `Constraint:`, `Rejected:`, `Confidence:`, `Scope-risk:`, `Directive:` | use when the log shows them; each `Rejected:` names the alternative and why |
| Evidence trailers | `Tested:`, `Not-tested:` | projected from the ledger, never written freehand; only when the recent log carries them. Otherwise add none: put the observed rows in the PR body's validation section (or one body line in the commit) and the unrun rows under "Not run", in the template's own headings |

Never add attribution lines the repository forbids, and never put credentials, tokens, private URLs, or raw transcripts in either text.

## 6. What the commit covers

The draft ends with the list of paths the message describes, read from the diff it was written against. Whoever records the commit stages those paths by name.

- Never write or recommend `git add -A` or `git add .`. Either one stages every dirty file in the tree, so a file the user was editing for another reason lands in a commit whose message never mentions it.
- A path that is dirty and not on the list is reported as left out, with the reason; it is not staged to make the tree clean.
- A generated file belongs on the list beside the source that produced it, or the commit records half of one change.

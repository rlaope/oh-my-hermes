# Spec to PR

A Notion or Confluence page, or a Linear or Jira issue, specifies a change. It
becomes a plan, a fanout run and a PR, and the PR link is written back to the
source. Every middle step already has an owner; this page fixes their order
and owns the two ends no other skill does: reading the source and writing the
link back.

| step | owner | evidence before the next step |
| --- | --- | --- |
| 1. Read the source | the app's MCP tools: `mcp__notion__*`, `mcp__atlassian__*` (Confluence and Jira), `mcp__linear__*` | the item's id, link, title, and last-edited time as returned |
| 2. Scope | this page | repository, coding owner, and acceptance criteria quoted from the source |
| 3. Plan | `omh-plan` | a plan the person accepted |
| 4. Fanout run | `ulw-work` | each lane's result and the integrated check, as observed |
| 5. PR | `omh-commit-pr-authoring` for the body; `gh pr create` | the PR's URL read back with `gh pr view` |
| 6. Write back | `omh-apps` confirmation gate | the comment or link read back from the source |

## 1. Read the source

Read the page or issue with its app's tools, including its comments and, for
an issue, its sub-issues and linked pages. When the app's server is not in
your tool list, say which one and stop (`hermes mcp install notion`,
`atlassian` or `linear`). A page or issue that names other pages is read only
as far as the person points; a linked page you did not read is a gap, not a
requirement.

## 2. Scope in one message

> ENG-42 "Export invoices as CSV" (Linear, edited 2026-11-20): repository
> acme/billing, coding owner `hermes`, done when the three acceptance criteria
> in the issue pass. I will write the PR link as a comment on ENG-42. OK?

- Quote the acceptance criteria from the source; when it has none, ask once
  for them and stop if the answer does not give them. Never invent criteria
  from the title.
- The coding owner is the one the person chose (`codex`, `claude-code`,
  `hermes`, or another runtime profile); when none is chosen, ask. There is
  no default owner.
- Name the write-back's target and text now, so the confirmation covers it.

## 3-5. Plan, fanout run, PR

Load `omh-plan` with the source as the brief and the quoted criteria as
acceptance, then hand the accepted plan to `ulw-work`, which splits it into
lanes and runs them through the chosen owner. A lane that fails stays failed in
the report; no PR is opened from a red integration. Draft the PR body with
`omh-commit-pr-authoring` and put the source's link in it. The PR is opened with
`gh` through Hermes' bundled `github` skill; when `gh` is missing or
`gh auth status` shows it signed out, say so and stop, naming the branch in the
report, and never reach GitHub another way.

Opening the PR is an externally visible action. In a person's turn it follows
their confirmation in step 2. In a run nobody answers (a scheduled job, a
one-shot run, a webhook run), it follows the unattended rule in this skill's
checklist. Merge, force push, and a push to the default branch are never part
of this recipe.

After the PR is open, waiting on its checks is the PR watch, and fixing a red
check is bounded by its fix-round cap: `skill_view(name='omh-github-event-ops', file_path='references/pr-watch.md')`, sections 1-4.

## 6. Write the link back

Post the PR link to the source through `omh-apps`' confirmation gate: a
comment on the Linear or Jira issue, or a comment on the Notion or Confluence
page. Change the issue's status only when the person asked for it in step 2.
Read the comment back from the app before saying it was written. When the
write's result is unclear, read the target first: a blind retry posts the
link twice.

A trigger that watches this source (a monitor on the issue, a webhook from the
tracker) must not start a run from this comment: the bot's own write is not a
new request. Write the comment so the next run can tell it is the bot's (it
names the PR and this recipe), and drop an event whose only change is that
comment.

## Stop and hand to a person

- the source cannot be read, or its criteria are still unclear after one
  question;
- the person did not accept the plan;
- the integrated check is red;
- the fix-round cap is reached (`skill_view(name='omh-github-event-ops', file_path='references/pr-watch.md')`, section 4);
- a reviewer requested changes, or the next step is a merge.

Report each step as prepared or observed, with the read-back that observed it.

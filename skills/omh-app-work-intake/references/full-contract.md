# App Work Intake

Load this on-demand contract after the compact `app-work-intake` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- Reading, summarizing, or editing one page, issue, or message, or one action in that app, with no work started from it; use `omh-apps`.
- A GitHub pull-request, issue, or check event to route; use `omh-github-event-ops`.
- A meeting's notes or transcript to turn into issues; use `omh-operating-rhythm`.
- An outage someone declared and is commanding now; use `omh-live-incident-response`.
- Triaging an inbox for replies, or drafting and sending a reply to a message; load Hermes' bundled `email-inbox-triage` skill instead of this one, which owns reply policy.

## Examples

Good example:

- Prompt: app-work-intake turn Linear issue ENG-42 into a PR and link the PR back on the issue.
- Expected behavior: Produce `prepare_app_work_intake_card` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: app-work-intake say the Notion page was updated with the PR link without reading it back.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the item: its app and its link or id, or the trigger that delivered it
- the path wanted (a PR, a work thread or Needs item, or a fix hand-off), or the item that decides it
- for a PR or a fix: the repository and the coding owner the person chose
- where a write-back goes, and the person's confirmation of its exact text

Expected outputs:

- app-work-intake/v1 card or guidance
- the item as read: app, id, link, title, and last-edited time
- the chosen path with the item fields that decided it
- next action
- prepared-vs-observed boundary

Artifact expectations:

- app-work-intake/v1 metadata-only runtime or wrapper card when recorded
- the item's app, id and link, the chosen path, and each write-back's target with its read-back, never the item's text

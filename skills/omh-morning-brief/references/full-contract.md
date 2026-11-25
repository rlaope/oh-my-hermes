# Morning Brief

Load this on-demand contract after the compact `morning-brief` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user wants Hermes to check their email or calendar right now rather than set up the connection.
- The connection is already configured and the user only wants today's brief, not a setup walkthrough; read mail and calendar with the connected tools and summarise them.
- The request needs a repository code change rather than a local MCP config edit.

## Examples

Good example:

- Prompt: connect my email for a morning brief — I want a daily summary of mail and calendar.
- Expected behavior: Check the MCP prerequisite, diagnose the current connection, guide OAuth/token issuance, show the read/draft-only diff, and apply only after approval.
- Why: The request is a mail/calendar integration setup and needs the shared setup contract plus the Send-permission guardrail.

Bad example:

- Prompt: morning-brief: check my email for anything urgent.
- Expected behavior: Route to a mail-reading task instead of starting a connection setup walkthrough.
- Why: A one-off email check is a task request, not an integration setup request.

## Full Input, Output, and Artifact Expectations

Required inputs:

- mail and calendar MCP connection status
- OAuth/app-password availability; value through secure entry or user-side setup only

Expected outputs:

- read-only diagnosis of the current mail/calendar MCP connection state
- diff-approved MCP config write limited to read and create-draft tools

Artifact expectations:

- connection verification note when the wrapper captures it

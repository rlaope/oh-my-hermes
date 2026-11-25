# Sales Development

Load this on-demand contract after the compact `sales-development` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user needs a company-level positioning, market-entry, or strategic-options decision rather than account-level discovery; use `omh-decide`.
- The user supplies a CRM export or pipeline snapshot and needs portfolio health, aging, slipped deals, forecast calibration, or renewal-risk review; use `omh-sales-pipeline-review`.
- The user only wants a polished social post, newsletter, or one-off outbound-copy rewrite; use `omh-content-operator`.
- The user asks to send outreach, update Salesforce or HubSpot, create an opportunity, or book a meeting; use `omh-apps` with explicit recipient, object, and authority.
- The request asks for current competitor or company evidence but supplies no source material; begin with `ulw-research` before presenting claims as observed.

## Examples

Good example:

- Prompt: Build a discovery plan and qualification questions for a mid-market prospect considering our support platform.
- Expected behavior: Prepare account evidence gaps, discovery and qualification questions, value hypotheses, and an owned next-step plan.
- Why: The request is account-level sales discovery, not outreach execution or company strategy.

Bad example:

- Prompt: Write a LinkedIn launch post for our new feature.
- Expected behavior: Route to `omh-content-operator`, not `sales-development`.
- Why: A one-off social post has no account qualification or discovery objective.

## Full Input, Output, and Artifact Expectations

Required inputs:

- account or segment
- available evidence
- buyer hypothesis
- sales objective

Expected outputs:

- sales_opportunity_evidence_record/v1
- sales_qualification_state/v1
- sales_draft_sequence/v1
- sales_handoff_disposition/v1

Artifact expectations:

- prepared sales development brief when a wrapper captures it

Detailed procedure steps: `references/procedure.md`.

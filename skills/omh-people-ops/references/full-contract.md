# People Ops

Load this on-demand contract after the compact `people-ops` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request asks for a jurisdiction-specific employment-law conclusion, policy compliance ruling, or contract interpretation; use `omh-legal-compliance-review`.
- The user only needs a one-off job-ad, rejection, or interview-email rewrite; use `omh-content-operator`.
- The user asks to create ATS records, send invitations, book interviews, change employment status, or modify HRIS settings; use `omh-apps` with explicit authorization and observed results.
- The user is the candidate: tailoring a resume, preparing for their own interview or tracking applications; use `omh-ai-job-search`.
- The prompt asks the workflow to make an unsupported candidate decision from protected characteristics or missing interview evidence; retain the process and evidence gap instead.

## Examples

Good example:

- Prompt: Create an interview scorecard and debrief plan for our first senior support hire.
- Expected behavior: Prepare role criteria, a structured scorecard, a debrief template, and decision-owner plan.
- Why: The request needs a fair hiring-process brief, not a claim that a candidate was evaluated or hired.

Bad example:

- Prompt: Send calendar invitations to every candidate for next Tuesday.
- Expected behavior: Route to `omh-apps`, not `people-ops`.
- Why: Sending invitations is an explicit external calendar action.

## Full Input, Output, and Artifact Expectations

Required inputs:

- role or people-process outcome
- available evidence
- decision owner
- policy constraints

Expected outputs:

- role/outcome and must-have versus trainable-criteria brief
- structured interview scorecard and evidence-based debrief template
- hiring-process, interviewer, and decision-owner plan
- inclusion, privacy, policy, and missing-evidence flags with a next route

Artifact expectations:

- prepared people-operations brief when a wrapper captures it

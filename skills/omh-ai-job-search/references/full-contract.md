# Ai Job Search

Load this on-demand contract after the compact `ai-job-search` body identifies the
workflow. The main body owns routing signals, shared rules, the runtime
operation, delegation fallback, and completion/recovery pointers; this file
holds the workflow-specific detail without copying those shared rails.

## Do Not Use When

- For employer-side hiring and candidate assessment, use `omh-people-ops`.
- For background task scheduling or service repair, use the existing automation or debugging owner.
- For repository symbol lookup or implementation work, use the selected coding owner.
- For citation attribution alone, use the bundled `grounded-citations` skill.

## Examples

Good example:

- Prompt: Find library coordinator opportunities and tailor my supported experience to a selected posting.
- Expected behavior: Capture verified sources, preserve unknown constraints, draft evidence-mapped documents and review them privately.
- Why: Career evidence and application state need a coherent method.

Bad example:

- Prompt: Screen these 40 resumes for our backend opening and rank them.
- Expected behavior: Route to `omh-people-ops`; this skill serves the candidate, not the employer.
- Why: Hiring vocabulary appears in both, but only the candidate side is a career request here.

## When to Use

Routing signals: `ai-job-search`, `job search`, `evaluate this job posting`, `tailor my resume`, `tailor my cv`, `prepare for my job interview`, `track my job applications`, `draft my cover letter`, `job application answers`

## Workflow Contract

Category: `operations`
Phase: `career-workflow`
Hermes role: `operator`
Quality tier: `evidence-gated`
Reasoning demand: `heavy`

Quality bar:

- Keep unsupported facts and failed sources visible; source availability and application progress are distinct.
- Inspect actual documents and tracker read-back; instruction-presence tests are not behavioral or output-quality evidence.

Handoff policy:

Hermes owns career framing, native retrieval, evidence-linked writing and outcome verification. Use available document ingestion/export and an independent read-only reviewer when authorized; no new provider, crawler, executor or OMH runtime operation is required.

Required inputs:

- requested career action
- supported candidate facts and preferences
- approved private workspace and source scope

Expected outputs:

- profile.md and preferences.md
- jobs.json and shortlist.md
- versioned application drafts and review.md
- interview-prep.md and optional skill-gaps.md
- evidence-bound tracker and next actions

Artifact expectations:

- Private authored Markdown and jobs.json are file contracts, not new OMH artifact RPCs; career data never belongs in the metadata-only runtime ledger.
- Versioned evidence-map.md, resume.md, cover-letter.md or answers.md, review.md and interview-prep.md must actually exist when requested.
- The offline helper stores references and posting observations, not raw CVs; its parsed summary supplies counts.

Detailed procedure steps: `references/procedure.md`.

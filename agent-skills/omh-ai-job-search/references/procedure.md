# ai-job-search Specialist Procedure

Expert clarification questions:
- `requested career action`
  - English: Which career action is needed now: discovery, fit, tailoring, interview preparation or tracking?
  - Korean: Which career action is needed now: discovery, fit, tailoring, interview preparation or tracking?
- `supported candidate facts and preferences`
  - English: Which user-selected facts and explicit preferences support this action, and which remain unknown?
  - Korean: Which user-selected facts and explicit preferences support this action, and which remain unknown?
- `approved private workspace and source scope`
  - English: Which private destination, source permissions and finite retrieval budget are approved?
  - Korean: Which private destination, source permissions and finite retrieval budget are approved?

## Procedure

Declared checks:
- `career_scope`
  - Required result fields: `action`, `private_workspace`, `fact_refs`, `unknowns`
  - Criterion: Require action-specific facts and approved private storage; do not infer personal eligibility.
- `career_sources`
  - Required result fields: `receipts`, `freshness`, `source_outcome`, `verified_job_count`
  - Criterion: Retain failures and unverified leads; distinguish successful empty discovery from blocked retrieval.
- `career_claims`
  - Required result fields: `requirement`, `evidence_ref`, `gaps`, `review_mode`
  - Criterion: Map claims to candidate evidence and label independent review versus self-review.
- `career_state`
  - Required result fields: `application_version`, `event_evidence`, `helper_exit`, `read_back`
  - Criterion: Run the offline companion and inspect actual state; drafts never prove submission.

### `career_frame` (analysis)

Extract supported profile facts and explicit preferences for the current action; preserve unknowns and contradictions.

- Input refs: `requested career action`, `supported candidate facts and preferences`, `approved private workspace and source scope`
- Output refs: `profile.md and preferences.md`
- Check IDs: `career_scope`

### `career_discover` (production)

Use bounded native retrieval, capture source receipts, invoke validate/merge/summary and write an evidence-linked qualitative shortlist.

- Input refs: `requested career action`, `supported candidate facts and preferences`, `approved private workspace and source scope`
- Output refs: `jobs.json and shortlist.md`
- Check IDs: `career_scope`, `career_sources`
- If this step fails: not_observed; still stands: `profile.md and preferences.md`; hand back: Return jobs.json and shortlist.md with receipts, unverified leads, and blocked sources (not empty results).

### `career_draft` (production)

Write versioned evidence-mapped application documents, review actual drafts, then prepare interviews from that exact version.

- Input refs: `requested career action`, `supported candidate facts and preferences`, `approved private workspace and source scope`
- Output refs: `versioned application drafts and review.md`, `interview-prep.md and optional skill-gaps.md`
- Check IDs: `career_claims`, `career_sources`
- If this step fails: tentative; still stands: `jobs.json and shortlist.md`, `profile.md and preferences.md`; hand back: Return versioned drafts and review.md with evidence gaps, review mode and the question blocking interview-prep.md.

### `career_track` (validation)

Record only explicitly evidenced events with the companion, read back the tracker and report safe next actions.

- Input refs: `requested career action`, `supported candidate facts and preferences`, `approved private workspace and source scope`
- Output refs: `evidence-bound tracker and next actions`
- Check IDs: `career_state`
- If this step fails: unresolved; still stands: `interview-prep.md and optional skill-gaps.md`, `jobs.json and shortlist.md`, `profile.md and preferences.md`, `versioned application drafts and review.md`; hand back: Keep history; return helper exits, missing events, tracker read-back gaps, draft version and next actions.

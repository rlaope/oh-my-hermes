# Project Terms Source and Review Boundary

Load this reference for terminology lookup, source inspection, preview, staging, freshness, or profile authority questions.

## Authority

- `PROJECT_TERMS.md` is an optional repository-root, human-reviewed source. Absence is a clean no-op.
- `<!-- omh-project-terms/v1 -->` identifies the strict source grammar.
- Source edits have zero direct machine or routing authority. The active reviewed `domain_intelligence_profile/v1` lifecycle remains the only machine-readable terminology source.
- Definitions, localized labels, distinct-from notes, and say-instead guidance remain human prose. They are never trigger, anti-trigger, reranking, dispatch, or matching inputs.

## Lookup

Read only what the question needs. Report whether the answer came from repository evidence, the optional source, an active reviewed profile, or an unresolved conflict. Report exact-byte freshness only when explicitly inspected. `changed` or `missing` requests review; neither mutates active behavior.

## Capture

Normal users describe the intent in Hermes chat. Agent/operator control-plane work may preview repository-root `PROJECT_TERMS.md`; preview is `prepared_not_observed`, reports no predicted candidate ids, and writes nothing. Before staging, show the machine-only projection and ask for explicit confirmation. Staging is atomic and pending-only. Approval is a separate review action.

Once per project, `omh memory project-identity init` names the scope; without it the next command stops with `scope_unresolved`. Preview with `omh memory domain-capture --from-file PROJECT_TERMS.md` (read-only, `prepared_not_observed`). After the user confirms, add `--stage` to write pending candidates. Review and approval stay with `omh memory domain-review` and `omh memory domain-approve`, which this workflow never runs. When no shell tool is available, show the projection in prose and stop.

Never create, rewrite, synchronize, approve, retire, or commit the source automatically. Never infer execution, review, model use, CI, or merge from source bytes, candidate state, profile state, or freshness.

## Attribution

The separation of domain language from decision work adapts ideas from Matt Pocock's `domain-modeling` skill at `mattpocock/skills@84fdeffd12f2ee307994d1eb6feb48173b6e0502`, MIT License, Copyright 2026 Matt Pocock. OMH uses its own strict source and reviewed-memory contracts.

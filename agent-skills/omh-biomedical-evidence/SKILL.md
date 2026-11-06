---
name: "omh-biomedical-evidence"
description: "[omh] Public variant claims to cross-check: retrieve and reconcile source-labelled biomedical evidence with identity, conflict and freshness checks. Use when the user says: biomedical-evidence, biomedical evidence reconciliation, ClinVar cross-check, variant evidence matrix, BioMCP capture reconciliation."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, analysis]
    category: analysis
    phase: biomedical-evidence
    role: operator
    quality_tier: evidence-gated
---

# Biomedical Evidence

This is an OMH `biomedical-evidence` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

Public sources can disagree about a variant while describing different alleles, diseases or assertion domains. Preserve those differences and their provenance before any synthesis; a fetched record is not a clinical recommendation.

## First Steps

- Read `toolkit/README.md` and `references/execution-and-qa.md`; inspect the installed BioMCP version and help before any public retrieval.
- Require public entities only; name exact identifiers, source terms, isolated workspace and a 40-second per-retrieval host timeout before capturing unmodified stdout/stderr.
- Run `toolkit/scripts/reconcile.py` only against a hash-checked local capture envelope; never execute provider text or install an upstream skill pack.

## Do Not Use When

- For explaining one supplied paper, use `omh-paper-learning`; for broad literature discovery, use `ulw-research`.
- For generic server configuration and connection diagnostics, load the host's MCP setup guidance instead.
- For sequence analysis or omics pipelines, select an available computational biology specialist instead; this method does not implement those analyses.
- For a patient's diagnosis, care, trial eligibility or treatment choice, stop and refer to an appropriately qualified professional; this toolkit cannot provide that decision.

## Examples

Good example:

- Prompt: Cross-check public BRAF V600E and melanoma records across ClinVar and ClinicalTrials.gov, retaining conflicting assertions and missing update dates.
- Expected behavior: Capture exact public queries, reconcile raw JSON offline, and report identity/date gaps with both source receipts.
- Why: Source comparison is bounded and does not ask for patient care.

Bad example:

- Prompt: Use these patient records to select a therapy and decide whether the patient can join a trial.
- Expected behavior: Refuse patient-level processing and clinical decisions; offer only public-source provenance checking.
- Why: Registry status and source annotations are not clinical eligibility or treatment evidence.

## Completion Checklist

- Both source attempts have raw hashes and exact receipts, or missing/failing sources are explicitly partial with nonzero status.
- Entity/build/transcript, disease basis, original assertions, conflicts and absent source times remain visible; no eligibility or clinical inference appears.
- Read both output files, verify hashes and report synthetic tests separately from real retrieval; do not claim distribution or live availability from preparation.

## Recovery Notes

- If BioMCP is unavailable, keep captures unobserved and prepare only the explicit isolated setup; never fabricate a source response.
- If a source fails or JSON changes, preserve stdout/stderr and a partial report; audit an updated adapter before accepting unknown schemas.
- If disease labels or allele aliases cannot be matched literally, preserve the mismatch and ask for authoritative identifiers rather than silently broadening.



## When to Use

Use when public gene/variant and disease assertions must be cross-checked against ClinVar and trial registry records, preserving source failures and disagreements rather than inferring a clinical conclusion.

    Strong routing signals: `biomedical-evidence`, `biomedical evidence reconciliation`, `ClinVar cross-check`, `variant evidence matrix`, `BioMCP capture reconciliation`

## Catalog Metadata

Category: `analysis`
Phase: `biomedical-evidence`
Quality tier: `evidence-gated`
Reasoning demand: `heavy`

Quality bar:

- Require observed source receipts and verified helper output hashes, not a mock result or health-only check.
- Retain contradictory source assertions and date/identity gaps without deriving a clinical consensus.

Required inputs:

- public gene/variant and disease query
- bounded BioMCP capture workspace
- intended entity identifiers and source scope

Expert clarification questions:
- `public gene/variant and disease query`
  - English: Which public gene, exact allele if any, disease label and intended IDs should remain distinct?
  - Korean: 어떤 공개 유전자, 정확한 변이, 질환명과 식별자를 구분해서 확인할까요?

Expected outputs:

- biomedical_evidence_matrix/v1
- biomedical_reconciliation_manifest/v1

Artifact expectations:

- Authored file contracts, not registered OMH RPC artifacts: evidence-matrix.json and manifest.json plus external raw capture/receipt references.
- Raw responses remain outside the package; the matrix preserves source assertions with JSON-pointer paths, accessions/NCT IDs, review/submitter context and retrieval/source times.

Safety rules:

- No patient data, clinical eligibility determination, treatment recommendation or pathogenicity adjudication; source assertions are not medical advice.
- No network or subprocess from the shipped helper, registration, discovery or install; BioMCP runs only via explicit bounded host invocation in an isolated optional environment.
- Keep germline/somatic and disease/population contexts separate; recruitment and text matches never establish eligibility or variant relevance.
- Preserve raw bytes and exact queries; mark source failure, missing dates and unresolved identity as partial instead of inventing biological findings.

Procedure: load `references/procedure.md`.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.

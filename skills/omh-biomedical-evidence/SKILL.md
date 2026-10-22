---
name: "omh-biomedical-evidence"
description: "[omh] Public variant claims to cross-check: retrieve and reconcile source-labelled biomedical evidence with identity, conflict and freshness checks. Use when the user says: biomedical-evidence, biomedical evidence reconciliation, ClinVar cross-check, variant evidence matrix, BioMCP capture reconciliation."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, analysis]
    category: analysis
    phase: biomedical-evidence
    role: operator
    quality_tier: evidence-gated
    related_skills: [omh-paper-learning, ulw-research, grounded-citations]
---

# Biomedical Evidence

Required: public gene/variant and disease query, bounded BioMCP capture workspace, intended entity identifiers and source scope. Output: biomedical_evidence_matrix/v1, biomedical_reconciliation_manifest/v1.

**Do Not Use When:** For citation verification and source attribution alone, load Hermes' bundled `grounded-citations` skill.

**HOLD:** Missing inputs or failed contract gates. Prepared OMH routing is not execution or approval.

## Why This Exists

Public sources can disagree about a variant while describing different alleles, diseases or assertion domains. Preserve those differences and their provenance before any synthesis; a fetched record is not a clinical recommendation.

## First Steps

- Read `toolkit/README.md` and `references/execution-and-qa.md`; inspect the installed BioMCP version and help before any public retrieval.
- Require public entities only; name exact identifiers, source terms, isolated workspace and a 40-second per-retrieval host timeout before capturing unmodified stdout/stderr.
- Run `toolkit/scripts/reconcile.py` only against a hash-checked local capture envelope; never execute provider text or install an upstream skill pack.

Contract: `references/full-contract.md`, loaded before analysis. Procedure: `references/procedure.md`. These are working methods, not an OMH runtime operation.

## Safety Rules

- No patient data, clinical eligibility determination, treatment recommendation or pathogenicity adjudication; source assertions are not medical advice.
- No network or subprocess from the shipped helper, registration, discovery or install; BioMCP runs only via explicit bounded host invocation in an isolated optional environment.
- Keep germline/somatic and disease/population contexts separate; recruitment and text matches never establish eligibility or variant relevance.
- Preserve raw bytes and exact queries; mark source failure, missing dates and unresolved identity as partial instead of inventing biological findings.

## When to Use

Use when public gene/variant and disease assertions must be cross-checked against ClinVar and trial registry records, preserving source failures and disagreements rather than inferring a clinical conclusion.

Strong routing signals: `biomedical-evidence`, `biomedical evidence reconciliation`, `ClinVar cross-check`, `variant evidence matrix`, `BioMCP capture reconciliation`

## Catalog Metadata

Category: `analysis`
Phase: `biomedical-evidence`
Hermes role: `operator`
Quality tier: `evidence-gated`

## Completion Checklist

- Both source attempts have raw hashes and exact receipts, or missing/failing sources are explicitly partial with nonzero status.
- Entity/build/transcript, disease basis, original assertions, conflicts and absent source times remain visible; no eligibility or clinical inference appears.
- Read both output files, verify hashes and report synthetic tests separately from real retrieval; do not claim distribution or live availability from preparation.

## Recovery Notes

- If BioMCP is unavailable, keep captures unobserved and prepare only the explicit isolated setup; never fabricate a source response.
- If a source fails or JSON changes, preserve stdout/stderr and a partial report; audit an updated adapter before accepting unknown schemas.
- If disease labels or allele aliases cannot be matched literally, preserve the mismatch and ask for authoritative identifiers rather than silently broadening.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `model-optimization`, `inference-serving`, `model-finetuning`, `research-brief`, `+26 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.

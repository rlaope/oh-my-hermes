# Biomedical Evidence

Load this on-demand contract after the compact `biomedical-evidence` body identifies the
workflow. The main body owns routing signals, shared rules, the runtime
operation, delegation fallback, and completion/recovery pointers; this file
holds the workflow-specific detail without copying those shared rails.

## Do Not Use When

- For explaining one supplied paper, use `omh-paper-learning`; for broad literature discovery, use `ulw-research`.
- For generic server configuration and connection diagnostics, load the host's MCP setup guidance instead.
- For sequence analysis or omics pipelines, select an available computational biology specialist instead; this method does not implement those analyses.
- For citation verification and source attribution alone, load Hermes' bundled `grounded-citations` skill.
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

## When to Use

Routing signals: `biomedical-evidence`, `biomedical evidence reconciliation`, `ClinVar cross-check`, `variant evidence matrix`, `BioMCP capture reconciliation`

## Workflow Contract

Category: `analysis`
Phase: `biomedical-evidence`
Hermes role: `operator`
Quality tier: `evidence-gated`
Reasoning demand: `heavy`

Quality bar:

- Require observed source receipts and verified helper output hashes, not a mock result or health-only check.
- Retain contradictory source assertions and date/identity gaps without deriving a clinical consensus.

Handoff policy:

Hermes retains query framing, source audit and interpretation. Only the explicit host terminal invokes the separately installed BioMCP CLI; the shipped helper reconciles local captures offline. No new OMH network client, process launcher or runtime artifact operation is implied.

Required inputs:

- public gene/variant and disease query
- bounded BioMCP capture workspace
- intended entity identifiers and source scope

Expected outputs:

- biomedical_evidence_matrix/v1
- biomedical_reconciliation_manifest/v1

Artifact expectations:

- Authored file contracts, not registered OMH RPC artifacts: evidence-matrix.json and manifest.json plus external raw capture/receipt references.
- Raw responses remain outside the package; the matrix preserves source assertions with JSON-pointer paths, accessions/NCT IDs, review/submitter context and retrieval/source times.

Detailed procedure steps: `references/procedure.md`.

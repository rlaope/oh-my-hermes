# Market Research

Load this on-demand contract after the compact `market-research` body identifies the
workflow. The main body owns routing signals, shared rules, the runtime
operation, delegation fallback, and completion/recovery pointers; this file
holds the workflow-specific detail without copying those shared rails.

## Do Not Use When

- A kill, pivot, or persevere gate before a PRD is needed; use `omh-product-discovery-validation`.
- A recurring source inbox with Scout, Analyst, and Briefer operations is needed; use `omh-research-department`.
- Supplied tickets need clustering and investigation priorities; use `omh-feedback-triage`.
- A supplied spreadsheet needs cleaning, descriptive statistics, or anomaly analysis; use `omh-data-analysis`.
- A supplied academic PDF needs section-by-section explanation; use `omh-paper-learning`.
- A general business question needs an audience-ready synthesis rather than a domain model; use `omh-research-brief`.

## Examples

Good example:

- Prompt: Estimate TAM SAM SOM for US independent dental clinics with sourced counts and sensitivity, not a guessed capture percentage.
- Expected behavior: Fix scope and units, build a source/assumption ledger, calculate addressable scenarios with tools, and expose confidence limits and missing inputs.
- Why: The task needs an addressable-market model, not only a narrative brief.

Bad example:

- Prompt: Approve our startup for investment because a large total market proves demand.
- Expected behavior: Keep the size estimate separate from a discovery decision; require target-customer evidence and the decision owner's gate.
- Why: Market scale is not customer validation or permission to build.

## When to Use

Routing signals: `market-research`, `market sizing`, `tam sam som`, `bottom up market sizing`, `market size sensitivity`, `customer evidence analysis`, `jtbd evidence matrix`, `competitor pricing profiles`, `competitive pricing analysis`, `시장 규모`, `경쟁사 분석`

## Workflow Contract

Category: `research`
Phase: `market-analysis`
Hermes role: `researcher`
Quality tier: `source-gated`
Reasoning demand: `standard`

Quality bar:

- Require source IDs, dates/cutoffs, observed/vendor-asserted/inferred labels, assumptions and units on material claims.
- Keep failed retrieval, contrary evidence, sample bias, scope mismatch and confidence limits visible; a citation alone does not verify a claim.
- Load method and output templates on demand; calculations need real tool receipts, and absent evidence cannot be synthesized into certainty.

Handoff policy:

Keep scoping, source-backed analysis, calculations, and uncertainty reporting in Hermes. Use `omh-research-brief` for the audience's final synthesis and `omh-research-department` for recurring operations. Product investment, kill/pivot/persevere, and customer-validation gates remain owned by `omh-product-discovery-validation`; market findings are not customer validation or permission to build.

Required inputs:

- decision and audience
- buyer segment and geography
- period currency units and source cutoff
- available evidence and source boundary
- research budget and stop condition

Expected outputs:

- market scope and source ledger
- TAM SAM SOM model and sensitivity
- customer evidence and JTBD matrix
- comparable competitor and pricing profiles
- decision-ready market findings

Artifact expectations:

- prepared market analysis with source IDs, assumptions, failed retrieval gaps, and tool calculation receipts when captured

Detailed procedure steps: `references/procedure.md`.

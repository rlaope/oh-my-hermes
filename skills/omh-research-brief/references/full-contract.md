# Research Brief

Load this on-demand contract after the compact `research-brief` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user needs to decide whether a customer problem deserves product investment with evidence typing and customer re-entry; use `omh-product-discovery-validation`.
- The request is only fresh links, citations, or current facts without a business question or decision audience; use `omh-web-research` for one cited lookup, or `ulw-research` for a depth-budget study.
- Sources have not yet been selected and the user wants source types, candidates, or acquisition state; use `omh-source-finder`.
- A scoped TAM/SAM/SOM model, customer-evidence matrix, or comparable competitor or pricing profile is the deliverable; use `omh-market-research`, then return here for the audience synthesis.
- The research is recurring and run by several roles; use `omh-research-department`.

## Examples

Good example:

- Prompt: research-brief: compare three onboarding analytics vendors using customer notes and confidence gaps.
- Expected behavior: Prepare a source-backed brief with evidence, inference, confidence, and retrieval gaps separated.
- Why: The user needs business research synthesis, not recurring operations or coding.

Bad example:

- Prompt: research-brief: how big is the dental-clinic software market, TAM, SAM and SOM?
- Expected behavior: Hand the sizing to `omh-market-research`; return here only for the audience synthesis.
- Why: Sizing is a model with units and calculation receipts, not a brief.

## Full Input, Output, and Artifact Expectations

Required inputs:

- business question
- source boundary
- recency or market scope

Expected outputs:

- evidence table
- inference summary
- confidence and uncertainty

Artifact expectations:

- research brief or source ledger when the wrapper captures observed sources

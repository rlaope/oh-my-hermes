# Data Analysis

Load this on-demand contract after the compact `data-analysis` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- Polygon overlay and area computation from supplied layers; use `omh-geospatial-analysis`.
- Budget variance, cash or close analysis with accounting periods and controls; use `omh-finance-analysis`.
- The table must become a deck, workbook or exported report; use `omh-materials-package` after the analysis scope is clear.

## Examples

Good example:

- Prompt: data-analysis analyze this CSV and summarize anomalies by segment.
- Expected behavior: Produce `prepare_data_analysis_card` with required context, wrapper actions, and not-evidence boundaries.
- Why: The prompt names a real workflow surface that Hermes can orchestrate without hiding execution.

Bad example:

- Prompt: data-analysis is the Q3 lift significant? (two columns of five numbers each)
- Expected behavior: Compute the comparison with code and report n per group, the effect size and an interval or test with its assumptions, flagging that five per group makes the result fragile, instead of calling the gap significant or refusing for lack of data.
- Why: The data was supplied; the failure is a comparison reported without n, an effect size or an interval.

## Full Input, Output, and Artifact Expectations

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- data_analysis_task_card/v1
- dataset_scope/v1
- analysis_method_plan/v1
- operations_data_harness/v1
- product_evidence_loop/v1
- analysis_result_summary/v1 when observed
- next action
- prepared-vs-observed boundary

Artifact expectations:

- data_analysis_task_card/v1 metadata-only wrapper card when prepared
- dataset_scope/v1 with source, row/record scope, columns or schema, filters, and stop condition
- analysis_method_plan/v1 naming summary, anomaly, trend, segment, schema, or log-pattern methods
- operations_data_harness/v1 for relationship and causal boundaries
- product_evidence_loop/v1 for prepared opaque data reference metadata
- analysis_result_summary/v1 only from observed data, calculations, query output, or supplied evidence

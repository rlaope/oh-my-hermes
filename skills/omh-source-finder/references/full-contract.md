# Source Finder

Load this on-demand contract after the compact `source-finder` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The requested output is factual findings, comparison, or a summary rather than a typed candidate inventory and acquisition status; use `ulw-research`.
- The user needs a business decision brief with evidence-versus-inference treatment; use `omh-research-brief`.
- The user asks for a cited answer to a current-facts question; use `omh-web-research`, and for a reference-implementation study with a depth budget use `ulw-research`.
- The user supplies a paper/PDF/arXiv/DOI/excerpt and wants explanation; use `omh-paper-learning`.
- The user asks for recurring monitoring, source inbox, or Scout/Analyst/Briefer operations; use `omh-research-department`.
- The user asks to export, convert, render, package, or attach a file; use `omh-materials-package` or `omh-deliverable-package`.
- The user asks for an image card or visual summary; use `omh-image-cards`.

## Examples

Good example:

- Prompt: source-finder find papers, datasets, and GitHub repos for evaluating browser agent benchmarks.
- Expected behavior: Prepare source_finder_plan/v1 with typed candidates, acquisition states, missing observed evidence, and downstream choices.
- Why: The user needs source candidates before deciding whether to learn, research, package, or implement.

Bad example:

- Prompt: source-finder find current citations and summarize what the sources say.
- Expected behavior: Route to `ulw-research` because the user asks for current evidence and synthesis, not candidate acquisition status.
- Why: Source-finder prepares acquisition lifecycle metadata; research owns current evidence synthesis.

## Full Input, Output, and Artifact Expectations

Required inputs:

- source target or topic
- desired source kinds
- source boundaries or exclusion criteria
- downstream intent when known

Expected outputs:

- source_finder_plan/v1
- source_candidate/v1
- source_candidate_set/v1
- source_acquisition_status/v1
- downstream workflow recommendation
- not-evidence boundary

Artifact expectations:

- source_finder_plan/v1 under .omh/source-finder when a wrapper or CLI records it

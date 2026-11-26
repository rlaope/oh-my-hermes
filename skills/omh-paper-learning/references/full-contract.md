# Paper Learning

Load this on-demand contract after the compact `paper-learning` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The request asks to export, convert, render, or package a file; use `omh-materials-package`.
- The request asks for daily/weekly paper monitoring, digest, source inbox, or Scout/Analyst/Briefer operations; use `omh-research-department`.
- The request asks to find current papers or sources when no supplied paper exists; use `ulw-research`.
- The request asks for a visual/image card; use `omh-image-cards`.
- The request asks to implement or reproduce the paper's code; prepare a coding handoff only after a paper learning or reproduction plan is accepted.

## Examples

Good example:

- Prompt: paper-learning 이 논문 PDF를 아주 쉽게 설명해줘. 내용은 줄이지 말고 섹션별로.
- Expected behavior: Prepare paper_learning_card/v1, ask or record level=very_easy, mark PDF extraction/source_state evidence, then explain section-by-section with a coverage ledger.
- Why: The user supplied a paper/PDF explanation intent with an explicit level and coverage-preserving constraint.

Bad example:

- Prompt: paper-learning 이 PDF를 PPT로 변환해서 공유용 파일 만들어줘.
- Expected behavior: Route to `omh-materials-package` because the user wants file conversion/export, not conceptual paper explanation.
- Why: PDF file output and render QA are material packaging work, not paper learning evidence.

## Full Input, Output, and Artifact Expectations

Required inputs:

- paper identity or attachment reference
- observed text scope or extraction evidence
- explanation level: very_easy, moderate, expert, or choose
- coverage scope: full paper, selected sections, or supplied excerpt
- output language when different from the source

Expected outputs:

- paper_learning_card/v1
- explanation level metadata
- source_state boundary
- coverage ledger
- section-by-section explanation outline
- missing-section and not-observed list

Artifact expectations:

- record the card with `omh paper plan --title <title> --source <path or url> --level <level> --source-state <state>` (add `--section` once per section, in reading order, when the paper is not shaped like the ten default sections - a proof-based, systems or survey paper), which writes paper_learning_card/v1 to `$OMH_HOME/paper-learning/<paper_id>/card.json` and hashes a local source file without parsing it
- record each explained chunk with `omh paper progress <paper_id> --covered <section> --next <section> [--missing <section>] [--note <text>]`, which updates the coverage ledger and appends one line to `ledger.jsonl`; `omh paper validate` checks the store

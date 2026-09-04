---
name: "omh-paper-learning"
description: "[omh] Hermes Paper Learning workflow: explain a supplied paper or paper/PDF at a selected level while preserving full section coverage and source evidence boundaries. Use when the user says: paper-learning, paper learning, paper-explainer, paper explainer, paper explanation, explain this paper, explain this arxiv paper, paper walkthrough."
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: paper-learning
    role: researcher
    quality_tier: paper-learning-gated
---

# Paper Learning

This is a Hermes-native `paper-learning` workflow skill.

## Why This Exists

`paper-learning` exists so Hermes can act like a strong human tutor for papers: choose the right explanation level, walk through the full paper section by section, and keep PDF extraction and validation evidence honest.

## Do Not Use When

- The request asks to export, convert, render, or package a file; use `materials-package`.
- The request asks for daily/weekly paper monitoring, digest, source inbox, or Scout/Analyst/Briefer operations; use `research-department`.
- The request asks to find current papers or sources when no supplied paper exists; use `research`.
- The request asks for a visual/image card; use `img-summary`.
- The request asks to implement or reproduce the paper's code; prepare a coding handoff only after a paper learning or reproduction plan is accepted.

## Examples

Good example:

- Prompt: paper-learning 이 논문 PDF를 아주 쉽게 설명해줘. 내용은 줄이지 말고 섹션별로.
- Expected behavior: Prepare paper_learning_card/v1, ask or record level=very_easy, mark PDF extraction/source_state evidence, then explain section-by-section with a coverage ledger.
- Why: The user supplied a paper/PDF explanation intent with an explicit level and coverage-preserving constraint.

Bad example:

- Prompt: paper-learning 이 PDF를 PPT로 변환해서 공유용 파일 만들어줘.
- Expected behavior: Route to `materials-package` because the user wants file conversion/export, not conceptual paper explanation.
- Why: PDF file output and render QA are material packaging work, not paper learning evidence.

## Completion Checklist

- The selected explanation level is one of: very_easy, moderate, expert, choose.
- The source_state is recorded and scoped to observed text or extraction evidence.
- The coverage ledger lists observed, missing, or prepared sections before claiming completion.
- The explanation is section-aware and does not compress away claims, equations, figures, limitations, or reproducibility notes.
- Not-observed boundaries remain visible: full_pdf_extraction, figure_ocr, external_citation_check, math_proof_validation, code_or_benchmark_reproduction, peer_review_or_claim_correctness.

## Recovery Notes

- If no paper text is observed, prepare the learning card from metadata only and ask for an attachment, excerpt, or extraction evidence.
- If only an abstract or excerpt is supplied, label the result as excerpt explanation and list missing sections.
- If context is too long, continue section-by-section and keep covered / next / missing state in the ledger.
- If the user asks for validation, citation checking, math proof review, or reproduction, create a separate observed-evidence or coding handoff path.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `best-practice-research`, `autoresearch-goal`, `model-optimization`, `inference-serving`, `+17 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `omh-routing/references/skill-common-rail.md`.

## Use When

Use when Hermes should explain a supplied paper, arXiv entry, paper PDF, pasted excerpt, or extracted paper text at a selected level while keeping a coverage ledger instead of shrinking the paper into a lossy summary.

    Strong routing signals: `paper-learning`, `paper learning`, `paper-explainer`, `paper explainer`, `paper explanation`, `explain this paper`, `explain this arxiv paper`, `paper walkthrough`, `research paper explanation`, `arxiv paper explain`, `pdf paper explain`, `paper pdf explanation`, `explain the attached paper`, `explain this pdf paper`, `without dropping details`, `very easy paper explanation`, `moderate paper explanation`, `expert paper explanation`, `논문 설명`, `논문 해설`, `논문 쉽게 설명`, `논문 아주 쉽게`, `논문 적당한 난이도`, `논문 전문가급`, `이 논문 설명해줘`, `이 논문 PDF 설명해줘`, `논문 PDF 쉽게 설명`, `논문 내용 줄이지 말고`

## Catalog Metadata

Category: `research`
Phase: `paper-learning`
Hermes role: `researcher`
Quality tier: `paper-learning-gated`
Reasoning demand: `standard`

Quality bar:

- Ask for or state the explanation level before drafting: very easy, moderate, or expert.
- Record source_state as one of: metadata_only, excerpt_text_observed, file_text_extraction_observed, full_text_observed, unknown_or_missing.
- Preserve the coverage policy `coverage_preserving_not_lossy_summary` through a section-by-section ledger.
- Explain by chunks when the source is long; keep each chunk linked to coverage_ledger status.
- List missing sections and not-observed claims before presenting the explanation as complete.

Handoff policy:

Keep paper explanation in Hermes. Route file export to `materials-package`, current-source discovery to `research`, recurring monitoring to `research-department`, and reproduction or implementation to an accepted coding handoff only after the explanation plan is accepted.

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

- paper_learning_card/v1 under .omh/paper-learning when a wrapper or CLI records it

Safety rules:

- Do not claim full PDF extraction, figure OCR, external citation checking, math validation, code reproduction, peer review, or full-paper coverage without observed evidence.
- A pasted abstract or excerpt supports only excerpt explanation until the remaining sections are observed.
- Level changes may change scaffolding, vocabulary, analogies, and critique depth, but must not drop substantive content.
- End each chunk with covered / next / missing rather than done unless the coverage ledger is complete.

## Runtime Evidence

Preferred harness for this skill: `paper-learning`.

```sh
omh runtime record --skill paper-learning --harness paper-learning --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `omh-routing/references/skill-common-rail.md`. Load it when applicable; otherwise name an unavailable capability.

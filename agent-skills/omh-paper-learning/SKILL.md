---
name: "omh-paper-learning"
description: "[omh] Paper or paper PDF to understand: explain a supplied paper or paper/PDF at a selected level while preserving full section coverage and source evidence boundaries. Use when the user says: paper-learning, paper learning, paper-explainer, paper explainer, paper explanation, explain this paper, explain this arxiv paper, paper walkthrough."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: paper-learning
    role: researcher
    quality_tier: paper-learning-gated
---

# Paper Learning

This is an OMH `omh-paper-learning` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`omh-paper-learning` exists so Hermes can act like a strong human tutor for papers: choose the right explanation level, walk through the full paper section by section, and keep PDF extraction and validation evidence honest.

## Do Not Use When

- The request asks to export, convert, render, or package a file; use `omh-materials-package`.
- The request asks for daily/weekly paper monitoring, digest, source inbox, or Scout/Analyst/Briefer operations.
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
- If the paper is longer than one read window, plan numbered page or line ranges in a durable host-owned ledger before reading, walk them in order, and mark each covered; the native OMH plan tool is unavailable in this projection.
- If the user asks for validation, citation checking, math proof review, or reproduction, create a separate observed-evidence or coding handoff path.



## When to Use

Use when Hermes should explain a supplied paper, arXiv entry, paper PDF, pasted excerpt, or extracted paper text at a selected level while keeping a coverage ledger instead of shrinking the paper into a lossy summary.

    Strong routing signals: `paper-learning`, `paper learning`, `paper-explainer`, `paper explainer`, `paper explanation`, `explain this paper`, `explain this arxiv paper`, `paper walkthrough`, `research paper explanation`, `arxiv paper explain`, `pdf paper explain`, `paper pdf explanation`, `explain the attached paper`, `explain this pdf paper`, `without dropping details`, `very easy paper explanation`, `moderate paper explanation`, `expert paper explanation`, `논문 설명`, `논문 해설`, `논문 쉽게 설명`, `논문 아주 쉽게`, `논문 적당한 난이도`, `논문 전문가급`, `이 논문 설명해줘`, `이 논문 PDF 설명해줘`, `논문 PDF 쉽게 설명`, `논문 내용 줄이지 말고`

## Catalog Metadata

Category: `research`
Phase: `paper-learning`
Quality tier: `paper-learning-gated`
Reasoning demand: `standard`

Quality bar:

- Ask for or state the explanation level before drafting: very easy, moderate, or expert.
- Record source_state as one of: metadata_only, excerpt_text_observed, file_text_extraction_observed, full_text_observed, unknown_or_missing.
- Preserve the coverage policy `coverage_preserving_not_lossy_summary` through a section-by-section ledger.
- Explain by chunks when the source is long; keep each chunk linked to coverage_ledger status.
- Set source_state from how the paper was acquired, not from the request. An entry that Hermes' bundled `arxiv` skill returned (search or id lookup) is `metadata_only` until paper text is read. Text that the bundled `pdf` skill's `pdf_read.py <file> --text` run returned is `file_text_extraction_observed` for the pages that came back with text, and a page that came back empty is listed as missing. Without those skills, the state is whatever the supplied text supports.
- For a paper past one read budget, plan numbered page ranges before reading, and map each covered range onto the coverage ledger's sections.
- List missing sections and not-observed claims before presenting the explanation as complete.

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

- record the card with `omh paper plan --title <title> --source <path or url> --level <level> --source-state <state>`, which writes paper_learning_card/v1 to `$OMH_HOME/paper-learning/<paper_id>/card.json` and hashes a local source file without parsing it
- record each explained chunk with `omh paper progress <paper_id> --covered <section> --next <section> [--missing <section>] [--note <text>]`, which updates the coverage ledger and appends one line to `ledger.jsonl`; `omh paper validate` checks the store

Safety rules:

- Do not claim full PDF extraction, figure OCR, external citation checking, math validation, code reproduction, peer review, or full-paper coverage without observed evidence.
- A pasted abstract or excerpt supports only excerpt explanation until the remaining sections are observed.
- Level changes may change scaffolding, vocabulary, analogies, and critique depth, but must not drop substantive content.
- End each chunk with covered / next / missing rather than done unless the coverage ledger is complete.

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

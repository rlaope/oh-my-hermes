---
name: "omh-long-document-reading"
description: "[omh] Huge PDF or document to read in full: read a very large PDF, contract, manual, or report through Hermes in page-anchored ranges with a coverage ledger. Use when the user says: long-document-reading, long document reading, summarize this pdf, read this pdf, process this pdf, go through this pdf, summarize this document, read this document."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: long-document-reading
    role: researcher
    quality_tier: long-document-gated
    related_skills: [omh-paper-learning, omh-materials-package, omh-media-input, omh-source-finder]
---

# Long Document Reading

This is a Hermes-native `long-document-reading` workflow skill.

## Why This Exists

`long-document-reading` exists because a 300-page PDF is about 500,000 characters and Hermes' `read_file` returns 100,000 per call with no page numbers, re-converting the whole file each time; five unanchored reads then sit in the conversation until the ratio-based compressor summarizes them without a page number, so without a ledger the session either truncates, loses the early ranges to compaction, or claims a summary of pages it never read.

## Do Not Use When

- The document is a research paper and the user wants it explained by level; use `omh-paper-learning`.
- The request asks to convert, export, split into a new file, compare two PDFs, or extract tables into CSV; use `omh-materials-package`.
- The input is an image, screenshot, receipt, audio, or video rather than a document; use `omh-media-input`.
- The user is still looking for the document or its download link; use `omh-source-finder`.
- The document fits one read (under about 60 pages of prose); read it directly and answer.

## Examples

Good example:

- Prompt: summarize this 300-page vendor contract pdf and list every obligation with a deadline
- Expected behavior: Prepare long_document_card/v1: record the page count and scanned flags, plan five 60-page ranges, delegate them with the per-range brief, merge obligations with page anchors, and close with covered / next / missing.
- Why: The document is far past one read budget and the goal needs page-anchored claims from every range.

Bad example:

- Prompt: turn this 300-page pdf into a slide deck
- Expected behavior: Route to `materials-package`: the user wants a produced file, not a page-anchored reading of the document; the page count alone does not make it a reading request.
- Why: Reading and producing are different lanes; a deck request is file output work.

## Completion Checklist

- The page count is observed or the card says it is not.
- Every ledger range is covered, or the missing ranges are listed with a reason.
- Every claim in the merged answer carries a page anchor.
- Scanned ranges are read, declined with a reason, or listed as missing.
- Not-observed boundaries remain visible: page_count, text_extraction, scanned_page_ocr, range_delegation, hosted_ocr, cross_range_consistency.

## Recovery Notes

- If a script reports a missing dependency, install the one it names once with `pip install` (`pdfplumber`, `pypdf`, `pymupdf`, or `pypdfium2`; poppler `pdftoppm` is the system alternative for rendering), rerun, and record the install.
- If a range read truncates, halve the range, record the observed characters per page, and re-plan the remaining ranges from that measurement.
- If the context was compacted or the session resumed, reread the ledger and continue from the `next` range; do not restart from page 1.
- If the document is encrypted, ask for the password or stop; `pdf_read.py` and `pdf_split.py` accept `--password`.
- If most pages are scanned and the goal needs them all, stop and get approval for the per-page OCR job before spending one vision call per page.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `model-optimization`, `inference-serving`, `model-finetuning`, `research-brief`, `+26 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes must read a supplied document that does not fit one read: a contract, manual, annual report, specification, or any PDF past about 60 pages. The skill plans page ranges sized to the `read_file` budget, keeps a page-anchored chunk ledger with covered / next / missing state, and delegates ranges when there are more than 4, so a compacted or resumed session continues instead of restarting.

    Strong routing signals: `long-document-reading`, `long document reading`, `summarize this pdf`, `read this pdf`, `process this pdf`, `go through this pdf`, `summarize this document`, `read this document`, `process this document`, `read this whole document`, `summarize this manual`, `read this manual`, `summarize this contract`, `read this contract`, `summarize this annual report`, `read this annual report`, `read the whole pdf`, `chunk this pdf`, `pdf in chunks`, `pdf too big`, `pdf too large`, `このpdfを要約`, `この文書を要約`, `この契約書を要約`, `マニュアルを要約`, `긴 문서 읽기`, `이 pdf 요약해줘`, `이 pdf 읽어줘`, `이 문서 요약해줘`, `이 문서 읽어줘`, `계약서 요약해줘`, `매뉴얼 요약해줘`, `연간 보고서 요약해줘`, `pdf 전체 읽어`, `문서 전체 읽어`, `总结这个pdf`, `总结这份文档`, `总结这份合同`, `总结这本手册`, `baca seluruh dokumen ini`, `rangkum PDF panjang ini`, `tolong baca laporan ini sampai selesai`, `ringkas dokumen ini tanpa melewatkan bagian`, `baca manual ini dari awal sampai akhir`, `bantu rangkum seluruh isi PDF ini`, `đọc toàn bộ tài liệu này`, `hãy đọc báo cáo này đến hết`, `tóm tắt tài liệu này không bỏ sót phần nào`, `đọc tài liệu hướng dẫn này từ đầu đến cuối`

## Catalog Metadata

Category: `research`
Phase: `long-document-reading`
Hermes role: `researcher`
Quality tier: `long-document-gated`
Reasoning demand: `standard`

Quality bar:

- Get the page count and scanned flags first with `pdf_read.py --meta`; each script names its own missing dependency (`pdfplumber` for `pdf_read.py`, `pypdf` for `pdf_split.py`, `pymupdf` for `extract_pymupdf.py`, `pypdfium2` or poppler `pdftoppm` for `pdf_page_image.py`); install it once, and say so.
- Size ranges to the read budget: about 60 pages per 100,000-character call at typical density; halve the range when a probe read truncates.
- Extract each range with page selection (`extract_pymupdf.py --pages` or `read_file` on a `pdf_split.py` output) so every note carries a page anchor.
- Delegate ranges to `delegate_task` children with the fixed per-range brief when the plan has more than 4 ranges; read sequentially otherwise.
- Close every range with covered / next / missing so a resumed session starts at the ledger's `next` range.
- Record source_state as one of: metadata_only, page_count_observed, range_text_observed, full_text_observed, unknown_or_missing.

Handoff policy:

Keep document reading in Hermes: `read_file`, the built-in `pdf` skill scripts, `delegate_task` range children, and `vision_analyze` for scanned pages. Route file export to `omh-materials-package`, paper tutoring to `omh-paper-learning`, and source acquisition to `omh-source-finder`.

Required inputs:

- document path or attachment reference
- reading goal: full summary, clause or section lookup, obligations, or a question to answer
- page count and scanned-page flags when observed
- read budget when the host differs from the 100,000-character default
- output language when different from the source

Expert clarification questions:
- `reading goal: full summary, clause or section lookup, obligations, or a question to answer`
  - English: What should the reading produce: a full summary, specific clauses or sections, obligations and dates, or an answer to one question?
  - Korean: 이 문서를 읽어서 무엇을 만들어야 하나요: 전체 요약, 특정 조항이나 섹션, 의무와 기한 목록, 아니면 한 가지 질문의 답인가요?
- `page count and scanned-page flags when observed`
  - English: How many pages does the document have, and did the page scan report scanned or image-only pages?
  - Korean: 문서는 몇 페이지이고, 페이지 검사에서 스캔본이나 이미지 전용 페이지가 보고되었나요?

Expected outputs:

- long_document_card/v1
- page count and source_state boundary
- page-range plan sized to the read budget
- chunk ledger with covered / next / missing page anchors
- per-range notes merged in page order
- scanned-range decisions and not-observed list

Artifact expectations:

- long_document_card/v1 metadata-only wrapper card when recorded

Safety rules:

- Do not claim the whole document was read: only ranges the ledger marks covered are read, and a compacted context drops what the ledger did not anchor to a page.
- Do not read a document past the budget in one call and summarize the truncation; a truncated `read_file` result is one range, not the document.
- Scanned or image-only ranges are missing until a per-page `vision_analyze` pass or hosted OCR is observed; declining an unneeded scanned range is a recorded decision, not silent loss.
- Delegated range children read and note; the parent merges and answers. A child's note is not proof its range was fully readable until its own missing-page list is empty.
- Page anchors come from `pdf_read.py` or `extract_pymupdf.py --pages`, never from guessing a page off a `read_file` line offset; the ledger records the estimate as an estimate.
- Never export, convert, or package the document as a side effect of reading it; that is `materials-package` work the user asks for separately.

## Long Document Reading Protocol

Every command below runs through the `terminal` tool from Hermes' built-in `pdf` skill. On current Hermes main all four scripts sit in `skills/productivity/pdf/scripts/` (the `ocr-and-documents` skill was merged into it); on older Hermes trees `extract_pymupdf.py` and `extract_marker.py` live in `skills/productivity/ocr-and-documents/scripts/` instead. Locate the directory with `skills_list` or `search_files` before the first run. Outputs differ per script: `pdf_read.py`, `pdf_split.py`, and `pdf_page_image.py` print JSON; `extract_pymupdf.py` prints plain text with `--- Page N/M ---` separators (JSON only with `--metadata`); and `pdf_page_image.py` exits 0 with `{"rendered": false, "missing": [...]}` when no rasterizer is installed, so read `rendered` before trusting a render. Measured Hermes limits are in `references/hermes-pdf-limits.md`.

1. **Scope.** Confirm the path and the reading goal (full summary, clauses or sections, obligations and dates, or one question). If the goal is one lookup, search the extracted text for it instead of reading every range.
2. **Probe.** Run `python pdf_read.py <file> --meta` for the page count, encrypted flag, and scanned flag. Each script names its own missing dependency (`pdfplumber` here, `pypdf` for `pdf_split.py`, `pymupdf` for `extract_pymupdf.py`, `pypdfium2` or poppler `pdftoppm` for `pdf_page_image.py`); install the one named with `pip install` once, rerun, and say you installed it. For an encrypted file ask for the password (`--password`) or stop.
3. **Plan.** At about 1,600 characters per page one `read_file` call (100,000 characters) holds about 60 pages, so split the page count into ranges of 60 pages. A document under 60 pages of prose is one read; answer directly. Record the plan as the chunk ledger: one row per range with `pages`, `offset`, `chars`, and `state` (`covered`, `next`, `missing`).
4. **Extract with page anchors.** For each range run `python extract_pymupdf.py <file> --pages <start0>-<end0>` (0-indexed; plain text with a `--- Page N/M ---` line before each page, which is the page anchor to keep) or `python pdf_split.py <file> --pages <start>-<end> -o <range>.pdf` (1-based, JSON) followed by `read_file` on the split file. Never read the whole file with `read_file` and paginate by `offset`: every call re-converts the entire document, and the extraction has no page numbers. If a range read truncates, halve the range, record the observed characters per page, and re-plan the remaining rows.
5. **Delegate above 4 ranges.** Send each range to a `delegate_task` child with this brief, unchanged except for the page numbers, then merge the notes in page order keeping every page anchor: `Read pages <start>-<end> only. Return: page-anchored key points, every defined term or obligation with its page, open questions, and the exact pages you could not read. Do not summarize pages outside this range.` A child that returns no missing-page list has not proven its range was readable.
6. **Close every range.** After each range write covered / next / missing into the ledger before moving on, so a compacted or resumed session rereads the ledger and continues from `next` instead of page 1. Say done only when every row is covered and every scanned range is read or declined.
7. **Scanned ranges.** The `read_file` coverage warning names page ranges that yielded no text. For the few pages the goal needs, run `python pdf_page_image.py <file> --pages <n> --out-dir <dir>` and `vision_analyze` one page per call; the script exits 0 either way, so a result with `"rendered": false` means no rasterizer (`pypdfium2` or poppler `pdftoppm`) is installed and nothing was rendered. Hosted OCR is not a knob to turn on: `read_file` uses it by itself when `FIRECRAWL_API_KEY` is set (`file_tools.hosted_ocr: false` turns it off), and its NEEDS OCR notice says whether it was attempted. For bulk OCR of a large range the coverage warning points at marker-pdf, `extract_marker.py` from the same skill, a multi-gigabyte install that needs its own approval. Decline ranges the goal does not need and record the decision: a 300-page scan at one vision call per page is a separate approved job, not a side effect of a summary.

## Runtime Evidence

Preferred harness for this skill: `long-document-reading`.

```sh
omh runtime record --skill long-document-reading --harness long-document-reading --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.

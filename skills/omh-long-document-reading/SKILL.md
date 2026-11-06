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
- Expected behavior: Route to `omh-materials-package`: the user wants a produced file, not a page-anchored reading of the document; the page count alone does not make it a reading request.
- Why: Reading and producing are different lanes; a deck request is file output work.

## Completion Checklist

- The page count is observed or the card says it is not.
- Every ledger range is covered, or the missing ranges are listed with a reason.
- Every claim in the merged answer carries a page anchor.
- Scanned ranges are read, declined with a reason, or listed as missing.
- Not-observed boundaries remain visible: page_count, text_extraction, scanned_page_ocr, range_delegation, hosted_ocr, cross_range_consistency.

## Recovery Notes

- If a script reports a missing dependency, rerun it with the interpreter the protocol resolved (the `pdf` skill's documents or `pdf-pymupdf` environment where it gives one, else a task-local virtual environment) instead of installing anything into Hermes' interpreter; poppler `pdftoppm` is the system alternative for rendering.
- If a range read truncates, halve the range, record the observed characters per page in the range's ledger note, and read the range in two halves; do not plan again with new numbers, which creates a new plan with an empty ledger.
- If the context was compacted or the session resumed, call `omh_document_plan action=show` (or reread the ledger file) and continue from the `next` range; do not restart from page 1.
- If the document is encrypted, ask for the password or stop; `pdf_read.py` and `pdf_split.py` accept `--password`, `extract_pymupdf.py` does not, so split the ranges with `pdf_split.py --password` first.
- If most pages are scanned and the goal needs them all, stop and get approval for the per-page OCR job before spending one vision call per page.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `model-optimization`, `inference-serving`, `model-finetuning`, `research-brief`, `+28 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes must read a supplied document that does not fit one read: a contract, manual, annual report, specification, or any PDF past about 60 pages. The skill plans page ranges sized to the `read_file` budget, keeps a page-anchored chunk ledger with covered / next / missing state, and delegates ranges when there are more than 4, so a compacted or resumed session continues instead of restarting.

    Strong routing signals: `long-document-reading`, `long document reading`, `summarize this pdf`, `read this pdf`, `process this pdf`, `go through this pdf`, `summarize this document`, `read this document`, `process this document`, `read this whole document`, `summarize this manual`, `read this manual`, `summarize this contract`, `read this contract`, `summarize this annual report`, `read this annual report`, `read the whole pdf`, `chunk this pdf`, `pdf in chunks`, `pdf too big`, `pdf too large`, `このpdfを要約`, `この文書を要約`, `この契約書を要約`, `マニュアルを要約`, `긴 문서 읽기`, `이 pdf 요약해줘`, `이 pdf 읽어줘`, `이 문서 요약해줘`, `이 문서 읽어줘`, `계약서 요약해줘`, `매뉴얼 요약해줘`, `연간 보고서 요약해줘`, `pdf 전체 읽어`, `문서 전체 읽어`, `прочитай pdf`, `прочитай этот документ`, `большой документ прочитай`, `суммаризируй pdf`, `прочитай документ`, `总结这个pdf`, `总结这份文档`, `总结这份合同`, `总结这本手册`, `baca seluruh dokumen ini`, `rangkum PDF panjang ini`, `tolong baca laporan ini sampai selesai`, `ringkas dokumen ini tanpa melewatkan bagian`, `baca manual ini dari awal sampai akhir`, `bantu rangkum seluruh isi PDF ini`, `đọc toàn bộ tài liệu này`, `hãy đọc báo cáo này đến hết`, `tóm tắt tài liệu này không bỏ sót phần nào`, `đọc tài liệu hướng dẫn này từ đầu đến cuối`

## Catalog Metadata

Category: `research`
Phase: `long-document-reading`
Hermes role: `researcher`
Quality tier: `long-document-gated`
Reasoning demand: `standard`

Quality bar:

- Get the page count and scanned flags first with `pdf_read.py --meta`; each script names its own missing dependency (`pdfplumber` and, for `--meta`, `pypdf` for `pdf_read.py`; `pypdf` for `pdf_split.py`; `pymupdf` for `extract_pymupdf.py`; `pypdfium2` or poppler `pdftoppm` for `pdf_page_image.py`); run them with the interpreter the `pdf` skill's Prerequisites give (a task-local virtual environment where it gives none) and never `pip install` into Hermes' own interpreter.
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
- Never export, convert, or package the document as a side effect of reading it; that is `omh-materials-package` work the user asks for separately.

## Long Document Reading Protocol

Every command below runs through the `terminal` tool from Hermes' built-in `pdf` skill. On current Hermes main all four scripts sit in `skills/productivity/pdf/scripts/` (the `ocr-and-documents` skill was merged into it); on older Hermes trees `extract_pymupdf.py` and `extract_marker.py` live in `skills/productivity/ocr-and-documents/scripts/` instead. Locate the directory with `skills_list` or `search_files` before the first run. Outputs differ per script: `pdf_read.py`, `pdf_split.py`, and `pdf_page_image.py` print JSON; `extract_pymupdf.py` prints plain text with `--- Page N/M ---` separators (JSON only with `--metadata`); and `pdf_page_image.py` exits 0 with `{"rendered": false, "missing": [...]}` when no rasterizer is installed, so read `rendered` before trusting a render. Measured Hermes limits are in `references/hermes-pdf-limits.md`.

**Environment.** Resolve two interpreters once and call them by absolute path (`command -v <name>` for a system one, the full `<venv>/bin/python` for a virtual environment), `<PY_DOCS>` for `pdf_read.py`, `pdf_split.py` and `pdf_page_image.py` and `<PY_MUPDF>` for `extract_pymupdf.py`; a shell variable such as `$PY` does not reach a delegated child. When the `pdf` skill's Prerequisites section gives a documents-environment block (`hermes pm environment documents ...`) and the `pdf` skill's `references/ocr-extraction.md` gives a `pdf-pymupdf` block, take each interpreter from them. When the skill has no such block (Hermes before it, including the floor v2026.9.7), build a task-local virtual environment (`python3 -m venv <task dir>/pdfvenv`, then install into it only the packages the scripts name) and use its interpreter for both. Never `pip install` into the interpreter that runs Hermes or into a `hermes pm environment` one. If no environment can be built, name the missing extractor and stop.

1. **Scope.** Confirm the path and the reading goal (full summary, clauses or sections, obligations and dates, or one question). If the goal is one lookup, dump the text layer once (`<PY_MUPDF> extract_pymupdf.py <file>` into a file in the task directory), `search_files` that file, and read the pages around each hit; report an absence only as "not found in the text layer of pages X; pages Y are image-only and unsearched".
2. **Probe.** Run `<PY_DOCS> pdf_read.py <file> --meta` for the page count, encrypted flag, and scanned flag. Each script names its own missing dependency (`pdfplumber` and, for `--meta`, `pypdf` here; `pypdf` for `pdf_split.py`; `pymupdf` for `extract_pymupdf.py`; `pypdfium2` or poppler `pdftoppm` for `pdf_page_image.py`); run it with the interpreter above and say which one you used. For an encrypted file ask for the password (`--password`) or stop.
3. **Plan.** At about 1,600 characters per page one `read_file` call (100,000 characters) holds about 60 pages, so split the page count into ranges of 60 pages. A document under 60 pages of prose is one read; answer directly. Record the plan as the chunk ledger: call `omh_document_plan` with `action=plan`, the path as `source`, the `pages` count and an `outline` of `{title, page}` anchors when the front matter shows one, and write the returned `plan_id` into your notes (`action=show` needs it; planning again with the same numbers returns the same plan and keeps its ledger). Use only its chunk numbers and page spans: ignore its `read_window` and `brief`, which paginate with `read_file`. It writes the plan under the OMH home, so a compacted or resumed session calls `action=show` and resumes at the next range. If that tool is absent, keep the ledger in a file in the task directory, one row per range with `pages`, `offset`, `chars`, and `state` (`covered`, `next`, `missing`), and reread it after compaction. For Korean or other CJK text a character costs more context than English: measure one probe range and size the ranges from its observed characters per page and the model's window, passing `budget_chars` lower when the window is small, before the first plan.
4. **Extract with page anchors.** For each range run `<PY_MUPDF> extract_pymupdf.py <file> --pages <start0>-<end0>` (0-indexed; plain text with a `--- Page N/M ---` line before each page, which is the page anchor to keep; that number is the PDF page index, so when the printed page numbers differ (roman front matter) record the offset and give both) or `<PY_DOCS> pdf_split.py <file> --pages <start>-<end> -o <range>.pdf` (1-based, JSON) followed by `read_file` on the split file (for an encrypted file use `pdf_split.py --password` or `pdf_read.py --text --password`; `extract_pymupdf.py` has no `--password` and cannot open it). Never read the whole file with `read_file` and paginate by `offset`: every call re-converts the entire document, and the extraction has no page numbers. If a range read truncates, halve the range, record the observed characters per page in the range's `mark` note, and read the range in two halves; do not plan again with new numbers, which creates a new plan with an empty ledger.
5. **Delegate above 4 ranges.** Send each range to a `delegate_task` child with this brief, unchanged except for the page numbers, then merge the notes in page order keeping every page anchor: `Read pages <start>-<end> only. Return: page-anchored key points, every defined term or obligation with its page, open questions, and the exact pages you could not read. Do not summarize pages outside this range.` A child sees only its goal and context, so put the absolute `<PY_MUPDF>` path and the exact command in its `context`: `<PY_MUPDF> <scripts dir>/extract_pymupdf.py <file> --pages <start0>-<end0>` (0-indexed), with the extractor given by absolute path (find the pdf skill's `scripts` directory with `skills_list` or `search_files`) because a bare script name fails from a child's working directory. For an encrypted file the parent first splits each range with `<PY_DOCS> <scripts dir>/pdf_split.py <file> --password ... --pages <start>-<end> -o <range>.pdf` and gives the child that split file; the child runs `<PY_MUPDF> <scripts dir>/extract_pymupdf.py <range>.pdf` with no `--pages` (the range's 0-indexed numbers return nothing on a split file), and its `--- Page N/M ---` anchors count from 1, so the parent adds the range's start page minus one when merging. A child that returns no missing-page list has not proven its range was readable.
6. **Close every range.** After each range mark it (`omh_document_plan action=mark`, `plan_id`, `chunk`, `state=covered`) or write covered / next / missing into the ledger file before moving on, so a compacted or resumed session rereads the ledger and continues from `next` instead of page 1. Say done only when every row is covered and every scanned range is read or declined.
7. **Scanned ranges.** The `read_file` coverage warning names page ranges that yielded no text. For the few pages the goal needs, run `<PY_DOCS> pdf_page_image.py <file> --pages <n> --out-dir <dir>` and `vision_analyze` one page per call; the script exits 0 either way, so a result with `"rendered": false` means no rasterizer (`pypdfium2` or poppler `pdftoppm`) is installed and nothing was rendered. Hosted OCR is not a knob to turn on: `read_file` uses it by itself when `FIRECRAWL_API_KEY` is set (`file_tools.hosted_ocr: false` turns it off), and its NEEDS OCR notice says whether it was attempted. For bulk OCR of a large range the coverage warning points at marker-pdf, `extract_marker.py` from the same skill, a multi-gigabyte install that needs its own approval. Decline ranges the goal does not need and record the decision: a 300-page scan at one vision call per page is a separate approved job, not a side effect of a summary.

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

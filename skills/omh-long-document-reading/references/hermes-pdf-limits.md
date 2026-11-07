# Hermes PDF Limits (measured 2026-09)

What the installed Hermes Agent does with a large PDF, read off its source tree. Each row names the file the number comes from so a later Hermes release can be re-measured instead of trusted. None of these numbers is an OMH guarantee.

## Budgets

| Surface | Limit | Where |
| --- | --- | --- |
| `read_file` characters per call | 100,000 (`file_read_max_chars`) | `tools/file_tools.py` |
| `read_file` lines per call | 2,000 max (`limit`) | `tools/file_tools.py` |
| Document size cap for extraction | 50 MB | `tools/read_extract.py` |
| TUI `pdf.attach` rasterization | 25 pages per call | `_PDF_ATTACH_MAX_PAGES` in `tui_gateway/prompt_attachments.py` on current main; `tui_gateway/server.py` and `tui_gateway/methods_prompt.py` on older trees |
| Scanned-page coverage scan | `pdftotext`, 20 s timeout; silently returns nothing when it times out | `tools/read_extract.py` |
| Dense prose per page | about 1,600 characters, so about 60 pages per read | measured, not configured |

A 300-page document is therefore about 500,000 characters, about 125,000 tokens: five reads whose text sits in the conversation with no page numbers. Hermes compresses at a ratio of the model window (`compression.threshold: 0.50` in `hermes_cli/config_defaults.py`, floored to 0.75 for windows under 512K in `agent/context_compressor.py`), so a 200K-window model compacts near 150K tokens and a 1M-window model near 500K: the five reads alone do not cross it, the sixth range or the reply on top of the rest of the session can, and the summary that replaces the early ranges carries no page anchor. The budget per call and the missing page numbers are the problem the ledger solves; compaction is what makes an unanchored read unrecoverable.

## What `read_file` does not do

- It converts `.pdf` to Markdown through the optional `firecrawl-anydoc` package and paginates the text by line `offset` / `limit`; every paginated call re-converts the whole document, and `anydoc.to_markdown` has no page selection.
- Page numbers do not survive the conversion. The scanned-page warning speaks in page ranges, but nothing maps a page to an offset; the chunk ledger is that map.
- `search_files` is ripgrep-backed (`tools/file_tools.py`) and a PDF is a binary to it (`is_pdf_path` in `tools/binary_extensions.py`), so there is no search inside a PDF until a range is extracted to text.
- The coverage warning (`_pdf_coverage_note` in `tools/read_extract.py`) names an `ocr-and-documents` skill. On current Hermes main that skill's scripts and notes were folded into `pdf` (`skills/productivity/pdf/references/ocr-extraction.md`, `extract_pymupdf.py` and `extract_marker.py` in `pdf/scripts/`); on older trees it is a live separate skill with its own `SKILL.md` and `scripts/`, and the `pdf` skill routes scanned pages to it. The NEEDS OCR notice (`_needs_ocr_warning`, same file) names no skill and says to check `skills_list`.

## What gives page control

The built-in `pdf` skill: argparse CLIs run through `terminal`. None of their dependencies is in the shipped venv; each script names the one it is missing.

| Hermes tree | `pdf_read.py`, `pdf_split.py`, `pdf_page_image.py` | `extract_pymupdf.py`, `extract_marker.py` |
| --- | --- | --- |
| current main (`ocr-and-documents` merged into `pdf`) | `skills/productivity/pdf/scripts/` | `skills/productivity/pdf/scripts/` |
| older trees (2026-08 and before) | `skills/productivity/pdf/scripts/` | `skills/productivity/ocr-and-documents/scripts/` |

Find the directory with `skills_list` or `search_files` before the first run instead of assuming one layout.

| Script | Dependency (from its imports) | Output |
| --- | --- | --- |
| `pdf_read.py` | `pdfplumber`; `--meta` also `pypdf` | JSON |
| `pdf_split.py` | `pypdf` | JSON |
| `pdf_page_image.py` | `pypdfium2`, or poppler `pdftoppm` on PATH | JSON; exits 0 with `"rendered": false` and a `missing` list when neither is installed |
| `extract_pymupdf.py` | `pymupdf` (`pymupdf4llm` for `--markdown`) | plain text with `--- Page N/M ---` separators; JSON only for `--metadata` |
| `extract_marker.py` | marker-pdf (multi-gigabyte, PyTorch) | files under `--output_dir` |

| Script | Use |
| --- | --- |
| `pdf_read.py <file> --meta` | page count, page sizes, encrypted and scanned flags |
| `pdf_read.py <file> --text` | per-page text as JSON (whole file; pipe into a file for large documents) |
| `extract_pymupdf.py <file> --pages 0-59` | the only extractor with page selection (0-indexed) |
| `pdf_split.py <file> --pages 1-60 -o part.pdf` | 1-based range into a new file for `read_file` |
| `pdf_page_image.py <file> --pages 61-62 --out-dir imgs/` | PNG per page for `vision_analyze` |

## Delegation

`delegate_task` fans out subagents (`tools/delegate_tool.py`) but nothing splits a document into ranges; the parent plans the ranges and sends one fixed brief per child. Above 4 ranges, delegation keeps each child's context to one range; below it, sequential reads cost less. `delegation.max_concurrent_children` bounds the fan-out.

## Config knobs

- `file_read_max_chars` raises the per-call character budget; re-plan `pages_per_range` from it.
- `FIRECRAWL_API_KEY` in the environment turns hosted OCR on inside `read_file` for scanned pages (`_hosted_ocr_config` in `tools/read_extract.py`); `file_tools.hosted_ocr: false` turns it off even with the key. There is no setting that turns it on without the key.
- `web.extract_char_limit` bounds `web_extract` on a URL-hosted PDF.
- `delegation.max_concurrent_children` bounds range fan-out.

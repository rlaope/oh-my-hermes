"""Show the lines around each hit of a small ``search_files`` content search.

Measured on 2026-10-30 (the omp head-to-head, Sonnet 5.5): oh-my-pi went
from a search to its first edit in one model call, every Hermes arm in two.
omp's ``grep`` prints each hit with one line before and three after it, so the
model can write the edit from the search result. Hermes's ``search_files``
has a ``context`` argument, but it defaults to 0 and the models almost never
pass it: 3 of about 245 searches before a first edit did, all on Haiku. The
next call was usually a ``read_file`` of the files the search named.

This pass adds those lines afterwards, at the ``transform_tool_result`` seam.
It does not inject ``context`` into the call. Hermes counts context lines
against ``limit``, so an injected ``context=3`` would show about a fifth as
many hits under the same limit, and a search for every caller would lose
callers.

What it does, and what it refuses:

* **Only small, complete results.** A content search whose own call asked for
  no context, returned at most ``MAX_HITS`` hits in at most ``MAX_FILES``
  files, and was not truncated. Anything broader passes through byte for
  byte, so a broad search costs exactly what it costs today. The added lines
  are capped at ``MAX_ADDED_CHARS`` characters. A result over the cap is left
  unchanged; it is never partly enriched.
* **Hermes's own text for every hit.** Hit rows keep the host's content. The
  file is re-read only for the lines around the hits, and only after every hit
  row has been checked against the line on disk at that number (redacted the
  way Hermes redacts a hit). One mismatch leaves the whole result alone. That
  check covers an edit in between, a path that resolves elsewhere, and a
  remote or container backend whose files are not on this disk.
* **Hermes's redaction on the added lines.** The whole file goes through
  ``agent.redact.redact_sensitive_text`` with ``file_read=True``, as
  ``read_file`` does, so a multi-line private key is caught whole. Redaction
  that changes the line count leaves the result alone. Without the host's
  redactor the pass does nothing.
* **No read is recorded.** Hermes's read tracker (dedup stubs, staleness, the
  whole-file baseline ``write_file`` needs) is untouched: a later ``read_file``
  of the same file returns its full content, and ``write_file`` still refuses
  to overwrite a file it has not seen read.

The rows keep Hermes's path-grouped shape, ``<line>: <content>`` for a hit and
``<line>- <content>`` for a line around it (grep's own marks), with ``...``
where lines are left out. ``matches_format`` says so, and ``total_count``
still counts hits.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Final, NamedTuple

SEARCH_HIT_CONTEXT_TOOL: Final = "search_files"
CONTEXT_BEFORE: Final = 1
CONTEXT_AFTER: Final = 3
MAX_HITS: Final = 20
MAX_FILES: Final = 8
MAX_ADDED_CHARS: Final = 6_000
# Hermes cuts each hit's content to 500 characters (`_parse_search_output`);
# an added line is cut the same way.
LINE_CHARS: Final = 500
MAX_FILE_BYTES: Final = 512 * 1024

MATCHES_FORMAT: Final = (
    "path-grouped: each file path on its own line, followed by indented "
    "'<line>: <content>' rows for matches and '<line>- <content>' rows for "
    f"the {CONTEXT_BEFORE} line before and {CONTEXT_AFTER} after each match; "
    "'...' marks lines left out"
)

# One dense row: two spaces, the line number, ": ", the content (Hermes
# `SearchResult._densify_matches`; an empty content keeps the trailing space).
_DENSE_ROW = re.compile(r"^  (\d+): ?(.*)$")


class _Hit(NamedTuple):
    path: str
    line: int
    content: str


def enrich_search_hits(*, tool_name: object, args: object, result: object, task_id: object = "") -> str | None:
    """The result with context rows around each hit, or ``None`` to leave it alone."""
    if tool_name != SEARCH_HIT_CONTEXT_TOOL or not isinstance(result, str) or not _wants_context(args):
        return None
    try:
        payload = json.loads(result)
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("error") or payload.get("truncated"):
        return None
    hits = _hits(payload)
    if not hits or len(hits) > MAX_HITS or len({hit.path for hit in hits}) > MAX_FILES:
        return None
    redactor = _host_redactor()
    if redactor is None:
        return None
    redact, is_secret_file = redactor
    base = _base_dir(task_id)
    files: dict[str, list[str]] = {}
    for path in dict.fromkeys(hit.path for hit in hits):
        lines = _file_lines(path, base, redact, is_secret_file, [hit for hit in hits if hit.path == path])
        if lines is None:
            return None
        files[path] = lines
    text = _render(hits, files)
    if text is None:
        return None
    enriched = {key: value for key, value in payload.items() if key not in ("matches", "matches_format", "matches_text")}
    return json.dumps({"total_count": payload.get("total_count"), **enriched,
                       "matches_format": MATCHES_FORMAT, "matches_text": text}, ensure_ascii=False)


def _wants_context(args: object) -> bool:
    """A content search in content mode whose call asked for no context of its own."""
    if not isinstance(args, dict):
        return False
    if args.get("target", "content") not in ("content", "grep"):
        return False
    if args.get("output_mode", "content") != "content":
        return False
    context = args.get("context", 0)
    return context in (0, None, "0", "")


def _hits(payload: dict[str, Any]) -> list[_Hit]:
    """The hits in either shape Hermes emits: the dense text block, or the list below five hits."""
    text = payload.get("matches_text")
    if isinstance(text, str):
        hits: list[_Hit] = []
        path: str | None = None
        for row in text.split("\n"):
            if not row.startswith("  "):
                path = row
                continue
            match = _DENSE_ROW.match(row)
            if match is None or path is None:
                return []
            hits.append(_Hit(path, int(match.group(1)), match.group(2)))
        return hits
    rows = payload.get("matches")
    if not isinstance(rows, list):
        return []
    hits = []
    for row in rows:
        if not isinstance(row, dict):
            return []
        path, line, content = row.get("path"), row.get("line"), row.get("content")
        if not isinstance(path, str) or not isinstance(line, int) or isinstance(line, bool) or not isinstance(content, str):
            return []
        hits.append(_Hit(path, line, content))
    return hits


def _host_redactor() -> tuple[Any, Any] | None:
    """Hermes's redactor and its secret-file classifier, or ``None`` outside a host that has them."""
    try:
        from agent.redact import _is_secret_file_arg, redact_sensitive_text
    except ImportError:
        return None
    return redact_sensitive_text, _is_secret_file_arg


def _base_dir(task_id: object) -> str:
    """The directory a relative hit path is relative to, as Hermes's file tools resolve it."""
    try:
        from tools.file_tools_paths import _resolve_base_dir
    except ImportError:
        return os.environ.get("TERMINAL_CWD") or os.getcwd()
    try:
        return str(_resolve_base_dir(str(task_id or "default"), container_paths=False))
    except (OSError, ValueError, RuntimeError):
        return os.environ.get("TERMINAL_CWD") or os.getcwd()


def _file_lines(path: str, base: str, redact: Any, is_secret_file: Any, hits: list[_Hit]) -> list[str] | None:
    """The file's redacted lines, or ``None`` when any hit row does not match the line on disk."""
    resolved = os.path.normpath(path if os.path.isabs(path) else os.path.join(base, path))
    try:
        with open(resolved, "rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
    except OSError:
        return None
    if len(raw) > MAX_FILE_BYTES or b"\0" in raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    secret = bool(is_secret_file(resolved))
    lines = _split(text)
    for hit in hits:
        if not 1 <= hit.line <= len(lines):
            return None
        # Hermes cuts a hit to 500 characters, redacts it, and the dense block rstrips it.
        expected = redact(lines[hit.line - 1][:LINE_CHARS], file_read=True, secret_file=secret)
        if expected.rstrip() != hit.content.rstrip():
            return None
    redacted = redact(text, file_read=True, secret_file=secret)
    redacted_lines = _split(redacted)
    if len(redacted_lines) != len(lines):
        return None
    return redacted_lines


def _split(text: str) -> list[str]:
    """Lines as grep numbers them: split on "\\n" only, a final newline ends the last line.

    ``str.splitlines`` also breaks on form feeds and Unicode separators, which
    would shift every row after one.
    """
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def _render(hits: list[_Hit], files: dict[str, list[str]]) -> str | None:
    """The path-grouped block with context rows, or ``None`` when the added rows pass the cap."""
    out: list[str] = []
    added = 0
    for path, lines in files.items():
        own = {hit.line: hit.content for hit in hits if hit.path == path}
        shown: set[int] = set()
        for line in own:
            shown.update(range(max(1, line - CONTEXT_BEFORE), min(len(lines), line + CONTEXT_AFTER) + 1))
        out.append(path)
        previous = 0
        for number in sorted(shown):
            if previous and number > previous + 1:
                out.append("  ...")
            if number in own:
                out.append(f"  {number}: {own[number].rstrip()}")
            else:
                row = f"  {number}- {lines[number - 1][:LINE_CHARS].rstrip()}".rstrip()
                added += len(row) + 1
                out.append(row)
            previous = number
    if added > MAX_ADDED_CHARS:
        return None
    return "\n".join(out)

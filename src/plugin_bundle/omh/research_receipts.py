"""Fetch receipts: which URLs a session's web tools really opened.

A research answer cites sources, and a citation ledger can name a URL the
model never opened -- remembered, guessed, or copied out of a search snippet.
Hermes' own `post_tool_call` sees every web tool result, so this module turns
each successful one into a metadata-only receipt that a later check can match
a cited URL against:

* ``web_extract``: each result entry that carries a ``url`` and no ``error``
  is a ``fetched`` receipt;
* ``browser_navigate``: a successful navigation is a ``fetched`` receipt for
  the final URL the browser reported;
* ``web_search``: each listed result URL is a ``search_listed`` receipt -- the
  model saw the link and a snippet, never the page.

One JSON line per URL goes to
``$OMH_HOME/runtime/research_receipts/<session key>.jsonl``, keyed by the
session the host dispatched the call for (`host_session_id`), never by
anything in the model-supplied arguments, so a subagent's calls land in the
child's own file. The file is ``0600``, appended under the bundle's lock and
bounded to the newest ``RECEIPT_LINE_LIMIT`` lines.

What a receipt holds is identity and size, never content: the URL as a
SHA-256 of the grounded-citations normalization (``url_key``, so it matches a
ledger entry byte for byte, query included), a display form with the query
and fragment dropped, and a SHA-256 and length of the entry's text. No page
text, title, query string, or tool argument is written. A receipt proves the
URL was opened in this session; it is not evidence that the page supports
any claim made from it.

This module imports nothing from ``omh`` (`tests/test_plugin_bundle_standalone.py`).
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from .awareness_delivery import _awareness_delivery_lock
from .delegation_ledger import ledger_key

RECEIPT_SCHEMA_VERSION: Final = "research_fetch_receipt/v1"
RECEIPT_DIRNAME: Final = "research_receipts"
RECEIPT_LINE_LIMIT: Final = 2000
RECEIPT_LOCK_SECONDS: Final = 2.0
URL_DISPLAY_LIMIT: Final = 200
ID_LIMIT: Final = 160
KIND_FETCHED: Final = "fetched"
KIND_SEARCH_LISTED: Final = "search_listed"
WEB_TOOLS: Final = frozenset({"web_extract", "browser_navigate", "web_search"})
RECEIPT_FIELDS: Final = (
    "schema_version",
    "session_id",
    "tool_call_id",
    "turn_id",
    "tool",
    "kind",
    "url_key",
    "url_display",
    "content_sha256",
    "content_chars",
    "observed_at",
)
# Everything recording can raise: a home that cannot be written, a busy lock
# (`TimeoutError` is an `OSError`), and malformed host data.
_RECORD_FAILURES = (OSError, RuntimeError, ValueError, TypeError)
_APPEND_FLAGS = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)


def normalize_url(url: str) -> str:
    """The grounded-citations ledger identity for a URL (`sources.py` ``normalize_url``).

    Copied, not imported: that script is a user-installed Hermes skill. Strip,
    drop the ``#`` fragment, drop trailing slashes unless nothing is left, and
    keep the query, which usually selects different content.
    """
    u = (url or "").strip()
    if "#" in u:
        u = u.split("#", 1)[0]
    stripped = u.rstrip("/")
    return stripped or u


def url_key(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


def url_display(url: str) -> str:
    """``scheme://host/path``: no credentials, query or fragment, at most ``URL_DISPLAY_LIMIT`` chars."""
    try:
        parts = urlsplit(str(url).strip())
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return ""
    if port is not None:
        host = f"{host}:{port}"
    shown = f"{parts.scheme}://{host}{parts.path}" if parts.scheme else f"{host}{parts.path}"
    return shown[:URL_DISPLAY_LIMIT]


def receipt_path(omh_home: str | Path, session_id: str) -> Path:
    return Path(omh_home) / "runtime" / RECEIPT_DIRNAME / f"{ledger_key(session_id)}.jsonl"


def record_fetch_receipts(
    *,
    tool_name: object,
    args: object,
    result: object,
    status: object,
    session_id: str,
    tool_call_id: object,
    turn_id: object,
    omh_home: str,
) -> str:
    """Append one receipt per URL a successful web tool call opened or listed; returns what happened.

    Labels: ``not_web_tool``, ``no_session``, ``not_ok`` (the host reported
    ``error`` or ``blocked``), ``no_urls``, ``recorded``, ``refused`` (the
    store could not be written). Never raises: it runs inside
    ``post_tool_call``, and a raise there would take the other observers
    with it. ``args`` is accepted for the hook's uniform call shape and never
    read: a receipt must not carry what the model asked for.
    """
    del args
    tool = str(tool_name or "")
    if tool not in WEB_TOOLS:
        return "not_web_tool"
    session = str(session_id or "").strip()
    if not session:
        return "no_session"
    if str(status or "ok") != "ok":
        return "not_ok"
    try:
        entries = _receipt_entries(tool, _parsed(result))
        if not entries:
            return "no_urls"
        observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines = [
            json.dumps(
                {
                    "schema_version": RECEIPT_SCHEMA_VERSION,
                    "session_id": session[:ID_LIMIT],
                    "tool_call_id": str(tool_call_id or "")[:ID_LIMIT],
                    "turn_id": str(turn_id or "")[:ID_LIMIT],
                    "tool": tool,
                    "kind": kind,
                    "url_key": url_key(url),
                    "url_display": url_display(url),
                    "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
                    "content_chars": len(text),
                    "observed_at": observed_at,
                },
                sort_keys=True,
            )
            for kind, url, text in entries
        ]
        _append_bounded(receipt_path(omh_home, session), lines)
    except _RECORD_FAILURES:
        return "refused"
    return "recorded"


def _parsed(result: object) -> object:
    if isinstance(result, (str, bytes)):
        try:
            return json.loads(result)
        except ValueError:
            return None
    return result


def _receipt_entries(tool: str, data: object) -> list[tuple[str, str, str]]:
    """``(kind, url, text)`` for each URL the result shows was opened or listed."""
    if not isinstance(data, dict):
        return []
    if tool == "browser_navigate":
        url = data.get("url")
        if data.get("success") is True and isinstance(url, str) and url.strip():
            return [(KIND_FETCHED, url, "")]
        return []
    if tool == "web_extract":
        rows, kind, text_field = data.get("results"), KIND_FETCHED, "content"
    else:
        if data.get("success") is False:
            return []
        web = data.get("data")
        rows, kind, text_field = (web.get("web") if isinstance(web, dict) else None), KIND_SEARCH_LISTED, "description"
    entries: list[tuple[str, str, str]] = []
    for row in rows if isinstance(rows, list) else ():
        if not isinstance(row, dict) or row.get("error"):
            continue
        url = row.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        text = row.get(text_field)
        entries.append((kind, url, text if isinstance(text, str) else ""))
    return entries


def _append_bounded(path: Path, lines: list[str]) -> None:
    """Append under the lock; past the bound, atomically keep only the newest lines."""
    with _awareness_delivery_lock(path, timeout_seconds=RECEIPT_LOCK_SECONDS):
        if path.is_symlink():
            raise OSError("receipt file is a symlink")
        existing: list[bytes] = []
        if path.exists():
            existing = path.read_bytes().splitlines()
        new = [line.encode("utf-8") for line in lines]
        if len(existing) + len(new) <= RECEIPT_LINE_LIMIT:
            descriptor = os.open(path, _APPEND_FLAGS, 0o600)
            with os.fdopen(descriptor, "ab") as handle:
                handle.write(b"".join(line + b"\n" for line in new))
            os.chmod(path, 0o600)
            return
        kept = (existing + new)[-RECEIPT_LINE_LIMIT:]
        temporary = path.with_name(f".{path.name}.{os.getpid()}-{secrets.token_hex(6)}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(b"".join(line + b"\n" for line in kept))
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if temporary.exists() and not temporary.is_symlink():
                temporary.unlink()

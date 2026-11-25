"""Selected-node evidence for /dag: a static A2UI Basic Catalog v1 snapshot."""
from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import re
from typing import Any

from ..plugin_bundle.omh import runtime_paths
from ..system.secure_regular_file import SecureFileError, open_regular_read, read_bounded
from .escapes import strip_escapes
from .markdown import clean_text, render_markdown
from .style import Line, Span
from .theme import Theme

# A2UI commit 5ff1b05f02d39f969b52a942e78e864ef3ac01fa, catalogs/basic/v1/catalog.json.
CATALOG = "https://a2ui.org/specification/v1_0/catalogs/basic/catalog.json"
VERSION = "1.0"
HANDOFF_BYTES = 8192
_NODE = re.compile(r"d:([a-z0-9][a-z0-9-]{0,31}):([a-z0-9][a-z0-9-]{0,31})")
_ORDER = ("title", "status", "divider", "handoff")


def _inert_links(text: str) -> str:
    """Keep link labels and discard targets without recursive parsing."""
    out: list[str] = []
    opens: list[int] = []
    pos = 0
    while pos < len(text):
        char = text[pos]
        if char == "\\" and pos + 1 < len(text) and not text.startswith("](", pos + 1):
            out.append(text[pos:pos + 2])
            pos += 2
            continue
        if char == "\n":
            opens.clear()
        if char == "[":
            image = bool(out and out[-1] == "!")
            if image:
                out.pop()
            opens.append(len(out))
            out.append("![" if image else "[")
        elif char == "]":
            start = opens.pop() if opens else None
            # Redact malformed closers too; the display parser accepts escaped closers.
            if pos + 1 < len(text) and text[pos + 1] == "(":
                target = pos + 2
                depth = 1
                while target < len(text) and text[target] != "\n" and depth:
                    if text[target] == "\\" and target + 1 < len(text):
                        target += 2
                        continue
                    if text[target] == "(":
                        depth += 1
                    elif text[target] == ")":
                        depth -= 1
                    target += 1
                if depth:
                    # A malformed target may still render as a URL; discard its line tail.
                    target = text.find("\n", pos)
                    if target < 0:
                        target = len(text)
                if start is not None:
                    out[start] = ""
                else:
                    out.append(char)
                pos = target
                continue
            out.append(char)
        else:
            out.append(char)
        pos += 1
    return "".join(out)


def selected_node(payload: object, selected: str) -> Mapping[str, Any] | None:
    """Only an actual DAG node in the active session-scoped HUD is eligible."""
    graph = payload.get("delegation_graph") if isinstance(payload, Mapping) else None
    if not isinstance(graph, Mapping) or graph.get("scope") != "session" or graph.get("status") != "active":
        return None
    match = _NODE.fullmatch(selected)
    nodes = graph.get("nodes")
    if match is None or not isinstance(nodes, list):
        return None
    return next((node for node in nodes if isinstance(node, Mapping) and node.get("id") == selected
                 and node.get("dag_node") == match[2] and not node.get("outside_dag")), None)


def read_handoff(home: str | Path | None, stored: str, selected: str) -> str:
    """Read one exact local handoff, never another ledger or a remote backend."""
    match = _NODE.fullmatch(selected)
    if not stored or match is None:
        return ""
    run, node = match.groups()
    # On demand: `dag_pager` imports this module with the TUI, and the TUI keeps the plugin's runtime
    # readers out of a session until they are used (`HudReaderImportTests`).
    from ..plugin_bundle.omh import dag_run

    try:
        root = Path(home).expanduser() if home else runtime_paths.default_omh_home()
        with open_regular_read(dag_run.record_path(root, stored, run)) as fd:
            record = json.loads(read_bounded(fd, dag_run.MAX_RECORD_BYTES))
        if (not isinstance(record, dict) or record.get("schema_version") != dag_run.DAG_SCHEMA_VERSION
                or record.get("run") != run or record.get("session_id") != stored or record.get("handoff_root")):
            return ""
        nodes = record.get("nodes")
        if not isinstance(nodes, list) or sum(isinstance(row, dict) and row.get("id") == node for row in nodes) != 1:
            return ""
        with open_regular_read(dag_run.handoff_path(root, stored, run, node)) as fd:
            raw = os.read(fd, HANDOFF_BYTES + 1)
    except (OSError, ValueError, RecursionError, SecureFileError):
        return ""
    text = strip_escapes(raw[:HANDOFF_BYTES].decode("utf-8", errors="replace"))
    text = "\n".join(clean_text(line) for line in text.split("\n")).strip()
    return text + "\n\n[Handoff preview clipped]" if len(raw) > HANDOFF_BYTES else text


def evidence(node: Mapping[str, Any], handoff: str) -> tuple[dict[str, Any], str]:
    """One-shot catalog envelope and Markdown from the same selected-node data."""
    def value(key: str) -> str:
        text = node.get(key)
        return " ".join(_inert_links(clean_text(text[:160])).split()) if isinstance(text, str) else ""

    title = f"# Evidence · {value('title') or 'DAG node'}"
    status = f"Status: {value('status') or value('state') or 'unknown'}"
    if role := value("role"):
        status += f" · Role: {role}"
    body = "## Handoff\n\n" + (_inert_links(handoff) or "No readable local handoff for this session and node.")
    records = [
        {"id": "root", "component": "Card", "child": "body"},
        {"id": "body", "component": "Column", "children": list(_ORDER)},
        {"id": "title", "component": "Text", "text": title, "variant": "body"},
        {"id": "status", "component": "Text", "text": status, "variant": "caption"},
        {"id": "divider", "component": "Divider", "axis": "horizontal"},
        {"id": "handoff", "component": "Text", "text": body, "variant": "body"},
    ]
    return {"version": VERSION, "createSurface": {
        "surfaceId": "dag-evidence", "catalogId": CATALOG, "components": records,
    }}, f"{title}\n\n{status}\n\n{body}"


def _parts(message: Mapping[str, Any]) -> list[Mapping[str, Any]] | None:
    """Validate the whole static profile before dereferencing any record."""
    if set(message) != {"version", "createSurface"} or message["version"] != VERSION:
        return None
    surface = message["createSurface"]
    if (not isinstance(surface, Mapping) or set(surface) != {"surfaceId", "catalogId", "components"}
            or surface["surfaceId"] != "dag-evidence" or surface["catalogId"] != CATALOG):
        return None
    records = surface["components"]
    if not isinstance(records, list) or len(records) != 6:
        return None
    by_id = {}
    for record in records:
        if not isinstance(record, Mapping) or not isinstance(key := record.get("id"), str) or key in by_id:
            return None
        by_id[key] = record
    if (by_id.get("root") != {"id": "root", "component": "Card", "child": "body"}
            or by_id.get("body") != {"id": "body", "component": "Column", "children": list(_ORDER)}):
        return None
    children = [by_id.get(key, {}) for key in by_id["body"]["children"]]
    for key, child in zip(_ORDER, children):
        if key == "divider":
            if child != {"id": "divider", "component": "Divider", "axis": "horizontal"}:
                return None
        elif (set(child) != {"id", "component", "text", "variant"} or child["component"] != "Text"
              or child["variant"] != ("caption" if key == "status" else "body")
              or not isinstance(child["text"], str) or len(child["text"]) > HANDOFF_BYTES * 4):
            return None
    return children


def evidence_lines(message: Mapping[str, Any], fallback: str, width: int, theme: Theme) -> list[Line]:
    """Render approved Basic Catalog records or the equivalent inert Markdown."""
    children = _parts(message)
    if children is None:
        return [(Span("Basic Catalog unavailable · Markdown", theme.muted),), *render_markdown(fallback, width, theme)]
    rows: list[Line] = []
    for child in children:
        if child["component"] == "Divider":
            rows.append((Span("─" * width, theme.rule),))
        else:
            rows.extend(render_markdown(child["text"], width, theme))
    return rows

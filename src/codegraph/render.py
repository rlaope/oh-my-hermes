from __future__ import annotations

import re
from typing import Any

from .schema import (
    CLAIM_BOUNDARY,
    CODEGRAPH_CONTEXT_SCHEMA_VERSION,
    CODEGRAPH_SUMMARY_SCHEMA_VERSION,
)


MAX_SUMMARY_ENTRYPOINTS = 20
MAX_SUMMARY_WARNINGS = 10
MAX_HANDOFF_FILES = 12
MAX_HANDOFF_SYMBOLS = 20


def summarize_codegraph(graph: dict[str, Any]) -> dict[str, Any]:
    entrypoint_files = [
        {
            "path": record["path"],
            "entrypoint_tags": record["entrypoint_tags"],
        }
        for record in graph.get("files", [])
        if isinstance(record, dict) and record.get("entrypoint_tags")
    ]
    return {
        "schema_version": CODEGRAPH_SUMMARY_SCHEMA_VERSION,
        "repo_root": graph["repo_root"],
        "generated_at": graph["generated_at"],
        "stats": graph["stats"],
        "entrypoint_files": entrypoint_files[:MAX_SUMMARY_ENTRYPOINTS],
        "entrypoint_file_count": len(entrypoint_files),
        "warnings": list(graph.get("warnings", []))[:MAX_SUMMARY_WARNINGS],
        "warning_count": len(graph.get("warnings", [])),
        "claim_boundary": graph.get("claim_boundary", CLAIM_BOUNDARY),
    }


def build_handoff_context(graph: dict[str, Any], *, task: str) -> dict[str, Any]:
    terms = _task_terms(task)
    focus_files = _ranked_focus_files(graph, terms)
    focus_symbols = _ranked_focus_symbols(graph, terms)
    summary = summarize_codegraph(graph)
    return {
        "schema_version": CODEGRAPH_CONTEXT_SCHEMA_VERSION,
        "task": task,
        "repo_root": graph["repo_root"],
        "generated_at": graph["generated_at"],
        "summary": summary,
        "task_terms": terms,
        "focus_files": focus_files,
        "focus_symbols": focus_symbols,
        "entrypoint_files": summary["entrypoint_files"],
        "warnings": summary["warnings"],
        "claim_boundary": graph.get("claim_boundary", CLAIM_BOUNDARY),
    }


def render_summary_text(summary: dict[str, Any]) -> str:
    stats = summary["stats"]
    lines = [
        "OMH codegraph summary",
        f"Repo: {summary['repo_root']}",
        f"Generated: {summary['generated_at']}",
        "Stats",
        f"  Files: {stats['file_count']} Python ({stats['parsed_file_count']} parsed, {stats['parse_error_count']} parse errors)",
        f"  Symbols: {stats['symbol_count']}",
        f"  Edges: {stats['edge_count']} ({stats['internal_import_edge_count']} internal imports)",
        f"  Entrypoint files: {stats['entrypoint_file_count']}",
    ]
    entrypoints = summary.get("entrypoint_files", [])
    if entrypoints:
        lines.append("Entrypoints")
        for record in entrypoints[:MAX_SUMMARY_ENTRYPOINTS]:
            lines.append(f"  - {record['path']}: {', '.join(record['entrypoint_tags'])}")
    if summary.get("warnings"):
        lines.append("Warnings")
        for warning in summary["warnings"]:
            lines.append(f"  - {warning}")
        if summary.get("warning_count", 0) > len(summary["warnings"]):
            lines.append(f"  - ... {summary['warning_count'] - len(summary['warnings'])} more")
    lines.extend(
        [
            "Boundary",
            f"  {summary['claim_boundary']}",
            "For machine-readable output, rerun with `--json`.",
        ]
    )
    return "\n".join(lines)


def render_build_text(graph: dict[str, Any]) -> str:
    summary = summarize_codegraph(graph)
    lines = render_summary_text(summary).splitlines()
    artifact_path = graph.get("artifact_path")
    if artifact_path:
        lines.insert(1, f"Artifact: {artifact_path}")
    return "\n".join(lines)


def render_handoff_text(context: dict[str, Any]) -> str:
    lines = [
        "OMH codegraph handoff context",
        f"Task: {context['task']}",
        f"Repo: {context['repo_root']}",
        "Focus files",
    ]
    focus_files = context.get("focus_files", [])
    if focus_files:
        for record in focus_files:
            tags = ", ".join(record.get("entrypoint_tags", [])) or "no entrypoint tags"
            lines.append(f"  - {record['path']} ({tags})")
    else:
        lines.append("  - none")
    focus_symbols = context.get("focus_symbols", [])
    if focus_symbols:
        lines.append("Focus symbols")
        for record in focus_symbols[:MAX_HANDOFF_SYMBOLS]:
            lines.append(f"  - {record['qualified_name']} ({record['kind']}, {record['path']}:{record['line']})")
    if context.get("warnings"):
        lines.append("Warnings")
        for warning in context["warnings"]:
            lines.append(f"  - {warning}")
    lines.extend(
        [
            "Boundary",
            f"  {context['claim_boundary']}",
            "For machine-readable output, rerun with `--json`.",
        ]
    )
    return "\n".join(lines)


def _ranked_focus_files(graph: dict[str, Any], terms: list[str]) -> list[dict[str, Any]]:
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for record in graph.get("files", []):
        if not isinstance(record, dict):
            continue
        score = _score_text(_file_haystack(record), terms)
        if score == 0 and record.get("entrypoint_tags"):
            score = 1
        if score == 0:
            continue
        scored.append((score, str(record["path"]), record))
    if not scored:
        scored = [(1, str(record["path"]), record) for record in graph.get("files", [])[:MAX_HANDOFF_FILES]]
    selected = [record for _, _, record in sorted(scored, key=lambda item: (-item[0], item[1]))[:MAX_HANDOFF_FILES]]
    return [_compact_file_record(record) for record in selected]


def _ranked_focus_symbols(graph: dict[str, Any], terms: list[str]) -> list[dict[str, Any]]:
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for symbol in graph.get("symbols", []):
        if not isinstance(symbol, dict):
            continue
        haystack = " ".join(str(symbol.get(key, "")) for key in ("name", "qualified_name", "kind", "path")).lower()
        score = _score_text(haystack, terms)
        if score:
            scored.append((score, str(symbol["qualified_name"]), symbol))
    if not scored:
        scored = [
            (1, str(symbol["qualified_name"]), symbol)
            for symbol in graph.get("symbols", [])[:MAX_HANDOFF_SYMBOLS]
            if isinstance(symbol, dict)
        ]
    return [
        {
            "name": symbol["name"],
            "qualified_name": symbol["qualified_name"],
            "kind": symbol["kind"],
            "path": symbol["path"],
            "line": symbol["line"],
        }
        for _, _, symbol in sorted(scored, key=lambda item: (-item[0], item[1]))[:MAX_HANDOFF_SYMBOLS]
    ]


def _compact_file_record(record: dict[str, Any]) -> dict[str, Any]:
    imports = []
    for item in record.get("imports", [])[:12]:
        if not isinstance(item, dict):
            continue
        target = str(item.get("module") or "")
        if item.get("name"):
            target = f"{target}:{item['name']}"
        imports.append(target)
    compact = {
        "path": record["path"],
        "kind": record["kind"],
        "entrypoint_tags": record.get("entrypoint_tags", []),
        "defines": record.get("defines", [])[:12],
        "imports": imports,
    }
    if record.get("parse_error"):
        compact["parse_error"] = record["parse_error"]
    return compact


def _file_haystack(record: dict[str, Any]) -> str:
    parts: list[str] = [str(record.get("path", ""))]
    parts.extend(str(tag) for tag in record.get("entrypoint_tags", []))
    parts.extend(str(name) for name in record.get("defines", []))
    for item in record.get("imports", []):
        if isinstance(item, dict):
            parts.append(str(item.get("module", "")))
            parts.append(str(item.get("name", "")))
    return " ".join(parts).lower()


def _task_terms(task: str) -> list[str]:
    return sorted(dict.fromkeys(term.lower() for term in re.findall(r"[A-Za-z0-9_]+", task) if len(term) >= 3))


def _score_text(text: str, terms: list[str]) -> int:
    if not terms:
        return 0
    score = 0
    for term in terms:
        if term in text:
            score += 1
    return score

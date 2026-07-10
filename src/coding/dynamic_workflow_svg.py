from __future__ import annotations

from html import escape
from typing import Sequence

from .dynamic_workflow_contracts import DYNAMIC_WORKFLOW_CHART_SCHEMA_VERSION, DYNAMIC_WORKFLOW_LANES


_LANE_COLORS = {
    "intake": "#f4f4f5",
    "planning": "#dbeafe",
    "critique": "#fee2e2",
    "implementation": "#dcfce7",
    "review": "#fef3c7",
    "report": "#ede9fe",
}
_CARD_WIDTH = 220
_CARD_HEIGHT = 112
_LEFT_MARGIN = 40
_RIGHT_MARGIN = 40
_LANE_GAP = 44


def render_dynamic_workflow_svg(workflow: dict[str, object]) -> str:
    stages = _stage_objects(workflow)
    lanes = [lane for lane in DYNAMIC_WORKFLOW_LANES if any(_stage_text(stage, "lane") == lane for stage in stages)]
    lane_counts = {lane: sum(1 for stage in stages if _stage_text(stage, "lane") == lane) for lane in lanes}
    width = max(960, _LEFT_MARGIN + _RIGHT_MARGIN + len(lanes) * _CARD_WIDTH + max(0, len(lanes) - 1) * _LANE_GAP)
    height = max(360, 150 + (_CARD_HEIGHT + 28) * max(lane_counts.values(), default=1))
    layout = _svg_layout(stages, lanes)
    body: list[str] = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="dynamic-workflow-title dynamic-workflow-desc">'
        ),
        '<title id="dynamic-workflow-title">Dynamic coding workflow</title>',
        (
            '<desc id="dynamic-workflow-desc">'
            "Prepared typed target workflow chart across model, runtime, wrapper, tool, and agent surfaces. "
            "It shows planned agents, targets, models, and gates, but it is not execution, review, CI, or merge "
            "evidence."
            "</desc>"
        ),
        f"<metadata>{DYNAMIC_WORKFLOW_CHART_SCHEMA_VERSION}</metadata>",
        "<defs>",
        '<marker id="arrow" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">',
        '<path d="M 0 0 L 10 4 L 0 8 z" fill="#475569"/>',
        "</marker>",
        "</defs>",
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        _svg_text(32, 38, "Dynamic coding workflow", size=20, weight="700"),
        _svg_text(32, 64, "status: prepared_not_observed | chart is not execution/review/CI/merge evidence", size=13),
    ]
    body.extend(_svg_edges(_edge_objects(workflow), layout))
    for stage in stages:
        xy = layout.get(_stage_text(stage, "id"))
        if xy:
            body.extend(_svg_stage(stage, xy))
    body.append("</svg>")
    return "\n".join(body) + "\n"


def _svg_edges(edges: Sequence[dict[str, object]], layout: dict[str, tuple[int, int]]) -> list[str]:
    lines: list[str] = []
    for edge in edges:
        start = layout.get(str(edge.get("from", "")))
        end = layout.get(str(edge.get("to", "")))
        if start and end:
            lines.append(_svg_edge(start, end))
    return lines


def _stage_objects(workflow: dict[str, object]) -> list[dict[str, object]]:
    stages = workflow.get("stages")
    if not isinstance(stages, list):
        return []
    return [stage for stage in stages if isinstance(stage, dict)]


def _edge_objects(workflow: dict[str, object]) -> list[dict[str, object]]:
    edges = workflow.get("edges")
    if not isinstance(edges, list):
        return []
    return [edge for edge in edges if isinstance(edge, dict)]


def _svg_layout(stages: Sequence[dict[str, object]], lanes: Sequence[str]) -> dict[str, tuple[int, int]]:
    if not lanes:
        return {}
    x_by_lane = {lane: _LEFT_MARGIN + index * (_CARD_WIDTH + _LANE_GAP) for index, lane in enumerate(lanes)}
    layout: dict[str, tuple[int, int]] = {}
    for lane in lanes:
        lane_stages = [stage for stage in stages if _stage_text(stage, "lane") == lane]
        for index, stage in enumerate(lane_stages):
            stage_id = _stage_text(stage, "id")
            if stage_id:
                layout[stage_id] = (x_by_lane[lane], 100 + index * (_CARD_HEIGHT + 28))
    return layout


def _svg_edge(start: tuple[int, int], end: tuple[int, int]) -> str:
    x1, y1 = start[0] + _CARD_WIDTH - 2, start[1] + 48
    x2, y2 = end[0] - 8, end[1] + 38
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        'stroke="#475569" stroke-width="1.5" marker-end="url(#arrow)"/>'
    )


def _svg_stage(stage: dict[str, object], xy: tuple[int, int]) -> list[str]:
    x, y = xy
    lane = str(stage.get("lane", ""))
    color = _LANE_COLORS.get(lane, "#f8fafc")
    target = _stage_text(stage, "target") or _stage_text(stage, "runtime") or "target"
    target_type = _stage_text(stage, "target_type") or "target"
    return [
        f'<rect x="{x}" y="{y}" width="{_CARD_WIDTH}" height="{_CARD_HEIGHT}" rx="8" fill="{color}" stroke="#334155" stroke-width="1"/>',
        _svg_text(x + 12, y + 22, str(stage.get("agent", "agent")), size=13, weight="700"),
        _svg_text(x + 12, y + 42, f"target: {target} ({target_type})", size=11),
        _svg_text(x + 12, y + 58, f"model: {stage.get('model', 'model')}", size=11),
        _svg_text(x + 12, y + 74, f"role: {stage.get('role', 'role')}", size=10, fill="#475569"),
        _svg_text(x + 12, y + 90, f"cost: {stage.get('cost_tier', 'unknown')}", size=10, fill="#475569"),
        _svg_text(x + 12, y + 106, f"gate: {stage.get('gate', 'gate')}", size=9, fill="#475569"),
    ]


def _svg_text(x: int, y: int, value: str, *, size: int, weight: str = "400", fill: str = "#0f172a") -> str:
    return (
        f'<text x="{x}" y="{y}" font-family="Inter, Arial, sans-serif" '
        f'font-size="{size}" font-weight="{weight}" fill="{fill}">{_xml_text(value)}</text>'
    )


def _xml_text(value: str) -> str:
    for character in value:
        if not _is_xml_10_character(character):
            raise ValueError("SVG text contains a character that is not valid in XML 1.0")
    return escape(value)


def _is_xml_10_character(character: str) -> bool:
    codepoint = ord(character)
    return (
        codepoint in (0x09, 0x0A, 0x0D)
        or 0x20 <= codepoint <= 0xD7FF
        or 0xE000 <= codepoint <= 0xFFFD
        or 0x10000 <= codepoint <= 0x10FFFF
    )


def _stage_text(stage: dict[str, object], key: str) -> str:
    value = stage.get(key)
    return str(value) if value is not None else ""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
from functools import lru_cache
from typing import Mapping, Sequence

from ..ingress import CHAT_SOURCES
from ..wrapper.contract import build_chat_interaction_payload
from ..wrapper.localized_copy import detect_copy_locale


LOCALIZED_CHAT_COPY_SCHEMA_VERSION = "localized_chat_copy/v1"


@dataclass(frozen=True)
class LocalizedChatCopyCase:
    id: str
    title: str
    message: str
    expected_locale: str
    expected_kind: str
    expected_next_action: str
    headline_marker: str
    body_markers: tuple[str, ...]
    forbidden_body_markers: tuple[str, ...] = field(default_factory=tuple)


LOCALIZED_CHAT_COPY_CASES: tuple[LocalizedChatCopyCase, ...] = (
    LocalizedChatCopyCase(
        id="catalog-picker-ja",
        title="Japanese catalog picker",
        message="OMHで使えるスキルは？",
        expected_locale="ja",
        expected_kind="skill_picker",
        expected_next_action="choose_skill",
        headline_marker="OMH workflow 一覧",
        body_markers=("shell command の承認なし", "まずここから:", "Route for me:"),
        forbidden_body_markers=("Start here:",),
    ),
    LocalizedChatCopyCase(
        id="catalog-picker-zh",
        title="Chinese catalog picker",
        message="OMH 有哪些工作流？",
        expected_locale="zh",
        expected_kind="skill_picker",
        expected_next_action="choose_skill",
        headline_marker="OMH workflow 列表",
        body_markers=("不需要先批准 shell command", "从这里开始:", "Route for me:"),
        forbidden_body_markers=("Start here:",),
    ),
    LocalizedChatCopyCase(
        id="catalog-picker-es",
        title="Spanish catalog picker",
        message="¿Qué comandos de OMH están disponibles?",
        expected_locale="es",
        expected_kind="skill_picker",
        expected_next_action="choose_skill",
        headline_marker="workflows de OMH",
        body_markers=("No necesitas aprobar un shell command", "Empieza aquí:", "Route for me:"),
        forbidden_body_markers=("Start here:",),
    ),
    LocalizedChatCopyCase(
        id="catalog-picker-de",
        title="German catalog picker",
        message="Welche OMH Workflows gibt es?",
        expected_locale="de",
        expected_kind="skill_picker",
        expected_next_action="choose_skill",
        headline_marker="OMH workflows",
        body_markers=("Du musst keinen shell command freigeben", "Start hier:", "Route for me:"),
        forbidden_body_markers=("Start here:",),
    ),
    LocalizedChatCopyCase(
        id="source-finder-fr",
        title="French source finder",
        message="trouve le dépôt GitHub et le PDF public",
        expected_locale="fr",
        expected_kind="source_finder",
        expected_next_action="prepare_source_finder_plan",
        headline_marker="plan d'acquisition de sources",
        body_markers=("source-finder plan", "Je prépare", "avant observation"),
    ),
    LocalizedChatCopyCase(
        id="paper-learning-fr",
        title="French paper learning",
        message="explique ce PDF de recherche simplement",
        expected_locale="fr",
        expected_kind="paper_learning",
        expected_next_action="prepare_paper_learning",
        headline_marker="papier",
        body_markers=("paper-learning card", "niveau d'explication", "avant observation"),
    ),
    LocalizedChatCopyCase(
        id="img-summary-ko",
        title="Korean image summary",
        message="회의록을 세로 이미지 카드로 만들어줘",
        expected_locale="ko",
        expected_kind="img_summary",
        expected_next_action="prepare_visual_prompt_card",
        headline_marker="공유용 이미지 카드",
        body_markers=("이미지 안 문구", "연결된 이미지 생성 도구", "말하지 않고"),
    ),
    LocalizedChatCopyCase(
        id="agent-ops-status-ko",
        title="Korean agent ops status",
        message="무슨일이노",
        expected_locale="ko",
        expected_kind="agent_ops_review",
        expected_next_action="refresh_agent_ops_status",
        headline_marker="지금 상황",
        body_markers=("관리자 관점", "shell 명령", "관측된 증거"),
        forbidden_body_markers=("Progress, blockers",),
    ),
)


def build_localized_chat_copy_demo(*, source: str = "discord") -> dict[str, object]:
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported demo source: {source}")
    return deepcopy(_build_localized_chat_copy_demo_cached(source))


@lru_cache(maxsize=None)
def _build_localized_chat_copy_demo_cached(source: str) -> dict[str, object]:
    rows = [_evaluate_case(case, source=source) for case in LOCALIZED_CHAT_COPY_CASES]
    passing_count = sum(1 for row in rows if bool(row["passed"]))
    return {
        "schema_version": LOCALIZED_CHAT_COPY_SCHEMA_VERSION,
        "source": source,
        "summary": {
            "case_count": len(rows),
            "passing_count": passing_count,
            "all_passing": bool(rows) and passing_count == len(rows),
            "locale_count": len({str(row["observed"].get("locale", "")) for row in rows}),
        },
        "check_basis": [
            "Common non-English operator prompts select the expected local copy locale.",
            "Localized card frames keep wrapper-visible contract terms such as Route for me and workflow plan names.",
            "Localized card frames avoid falling back to the English catalog intro when a local frame exists.",
            "This gate checks deterministic local copy only; it does not prove translation quality or live messenger rendering.",
        ],
        "cases": rows,
        "claim_boundary": (
            "This is deterministic local localized-chat-copy coverage, not live Hermes chat rendering, "
            "platform delivery, translation service quality, source retrieval, executor execution, review, CI, merge, "
            "or delivery evidence."
        ),
    }


def format_localized_chat_copy_summary(payload: Mapping[str, object]) -> str:
    summary = _nested(payload, "summary")
    rows = _mapping_rows(payload.get("cases"))
    total = int(summary.get("case_count", len(rows)) or 0)
    passing = int(summary.get("passing_count", 0) or 0)
    lines = [
        "OMH localized chat copy",
        f"Source: {payload.get('source', 'unknown')}",
        f"Result: {passing}/{total} localized card cases passing",
        f"Locales: {summary.get('locale_count', 0)}",
        "",
        "What this proves:",
    ]
    for basis in _string_items(payload.get("check_basis")):
        lines.append(f"- {basis}")
    lines.extend(["", "Localized card rollup:"])
    for row in rows:
        observed = _nested(row, "observed")
        status = "ok" if row.get("passed") else "needs attention"
        lines.append(
            f"- {row.get('title', 'Untitled localized card')}: {status}; "
            f"locale={observed.get('locale', 'unknown')}; "
            f"kind={observed.get('kind', 'unknown')}; "
            f"next={observed.get('next_action', 'unknown')}"
        )
    failed = [row for row in rows if not row.get("passed")]
    if failed:
        lines.extend(["", "Failures:"])
        for row in failed:
            lines.append(f"- {row.get('id', 'unknown')}: {', '.join(_string_items(row.get('issues'))) or 'unknown issue'}")
    lines.extend(
        [
            "",
            f"Boundary: {payload.get('claim_boundary', '')}",
            "Use --json for the full machine-readable payload.",
        ]
    )
    return "\n".join(lines)


def localized_chat_copy_errors(payload: Mapping[str, object]) -> list[str]:
    if payload.get("schema_version") != LOCALIZED_CHAT_COPY_SCHEMA_VERSION:
        return ["unexpected_schema"]
    if bool(_nested(payload, "summary").get("all_passing")):
        return []
    return [
        f"{row.get('id', 'unknown')}: {', '.join(_string_items(row.get('issues'))) or 'failed'}"
        for row in _mapping_rows(payload.get("cases"))
        if not row.get("passed")
    ]


def _evaluate_case(case: LocalizedChatCopyCase, *, source: str) -> dict[str, object]:
    interaction = build_chat_interaction_payload(case.message, source=source)
    response = _nested(interaction, "chat_response")
    body = str(response.get("body", ""))
    headline = str(response.get("plain_headline") or response.get("headline") or "")
    locale = detect_copy_locale(case.message)
    issues: list[str] = []
    if locale != case.expected_locale:
        issues.append(f"expected locale {case.expected_locale}, observed {locale}")
    if response.get("kind") != case.expected_kind:
        issues.append(f"expected kind {case.expected_kind}, observed {response.get('kind')}")
    if interaction.get("next_action") != case.expected_next_action:
        issues.append(f"expected next action {case.expected_next_action}, observed {interaction.get('next_action')}")
    if case.headline_marker not in headline:
        issues.append(f"missing headline marker {case.headline_marker}")
    for marker in case.body_markers:
        if marker not in body:
            issues.append(f"missing body marker {marker}")
    for marker in case.forbidden_body_markers:
        if marker in body:
            issues.append(f"forbidden body marker {marker}")
    return {
        "id": case.id,
        "title": case.title,
        "message_sha256": hashlib.sha256(case.message.encode("utf-8")).hexdigest(),
        "passed": not issues,
        "expected": {
            "locale": case.expected_locale,
            "kind": case.expected_kind,
            "next_action": case.expected_next_action,
        },
        "observed": {
            "locale": locale,
            "kind": response.get("kind"),
            "next_action": interaction.get("next_action"),
            "headline_marker_present": case.headline_marker in headline,
            "body_marker_count": sum(1 for marker in case.body_markers if marker in body),
            "forbidden_body_marker_count": sum(1 for marker in case.forbidden_body_markers if marker in body),
        },
        "issues": issues,
    }


def _nested(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    return value if isinstance(value, Mapping) else {}


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _string_items(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if str(item)]

from __future__ import annotations

from dataclasses import dataclass

from ..skills.catalog import routable_definitions
from .localization import normalized_phrase, prepare_routing_text, routing_tokens


SCHEMA_VERSION = "workflow_route_plan/v1"
CLAIM_BOUNDARY = (
    "Workflow route plans are routing guidance only. They do not prove research, planning acceptance, "
    "executor dispatch, implementation, review, CI, docs sync, PR creation, or merge evidence."
)
_STOPWORDS = {
    "the",
    "and",
    "then",
    "with",
    "for",
    "this",
    "that",
    "please",
    "해줘",
    "해주세요",
    "하고",
    "그리고",
    "뒤",
}
_STAGE_ORDER = (
    "clarify",
    "triage",
    "research",
    "plan",
    "deliver",
    "review",
    "verify",
    "learn",
)
_SKILL_STAGE = {
    "deep-interview": "clarify",
    "feedback-triage": "triage",
    "source-finder": "research",
    "web-research": "research",
    "best-practice-research": "research",
    "research-brief": "research",
    "research-department": "research",
    "paper-learning": "research",
    "plan": "plan",
    "ralplan": "plan",
    "ultraprocess": "deliver",
    "ultragoal": "deliver",
    "ultrawork": "deliver",
    "ai-slop-cleaner": "deliver",
    "code-review": "review",
    "ultraqa": "verify",
    "workflow-learning": "learn",
}
_STAGE_PRIORITY = {
    "clarify": ("deep-interview",),
    "triage": ("feedback-triage",),
    "research": ("web-research", "source-finder", "best-practice-research", "research-brief", "research-department", "paper-learning"),
    "plan": ("ralplan", "plan"),
    "deliver": ("ultraprocess", "ultragoal", "ultrawork", "ai-slop-cleaner"),
    "review": ("code-review",),
    "verify": ("ultraqa",),
    "learn": ("workflow-learning",),
}
_STAGE_REASON = {
    "clarify": "Clarify ambiguous product, workflow, or implementation intent before committing to a plan.",
    "triage": "Classify supplied feedback or bug signals before turning them into implementation work.",
    "research": "Gather source-backed context before planning or handoff.",
    "plan": "Produce a reviewed plan with risks, acceptance criteria, and verification before execution.",
    "deliver": "Prepare one bounded implementation or executor handoff path after planning context exists.",
    "review": "Review observed changes or claims before reporting quality or merge readiness.",
    "verify": "Run or prepare verification scenarios and keep pass/fail evidence separate from proposed fixes.",
    "learn": "Turn routing or workflow problems into a learning trace, regression, or patch proposal.",
}
_STAGE_BOUNDARY = {
    "clarify": "A clarification brief is not plan acceptance or implementation evidence.",
    "triage": "Feedback triage is not a roadmap decision, reproduction, implementation, or fix evidence.",
    "research": "Research guidance is not proof that sources were fetched or that code changed.",
    "plan": "A reviewed plan is not execution, review, CI, PR, or merge evidence.",
    "deliver": "A prepared delivery or handoff path is not dispatch, implementation, review, CI, or PR evidence.",
    "review": "A review step needs concrete observed diff, artifact, or command evidence before it can pass.",
    "verify": "Verification is observed only from concrete command, artifact, or wrapper evidence.",
    "learn": "A learning trace or patch proposal does not silently change installed skills.",
}
_STAGE_SIGNAL_PHRASES = {
    "triage": (
        "customer feedback",
        "payment failure",
        "bug report",
        "feedback",
        "결제 실패",
        "피드백",
        "버그 제보",
    ),
    "research": (
        "research",
        "web search",
        "current source",
        "latest",
        "citation",
        "source",
        "조사",
        "검색",
        "자료",
        "출처",
        "웹서치",
        "리서치",
    ),
    "plan": (
        "plan",
        "reviewed plan",
        "acceptance criteria",
        "risk",
        "architecture",
        "reproduction plan",
        "safe",
        "unsafe",
        "dangerous",
        "계획",
        "재현",
        "위험",
        "설계",
    ),
    "deliver": (
        "implement",
        "fix",
        "coding",
        "codex",
        "claude",
        "pr",
        "pull request",
        "구현",
        "고쳐",
        "코덱스",
        "코딩",
        "pr까지",
    ),
    "review": (
        "code review",
        "review",
        "audit",
        "리뷰",
        "코드 리뷰",
        "검토",
    ),
    "verify": (
        "test",
        "qa",
        "ci",
        "verify",
        "verification",
        "테스트",
        "검증",
    ),
}


@dataclass(frozen=True)
class _RouteStep:
    stage: str
    skill: str
    score: int
    confidence: str
    matched: tuple[str, ...]
    reason: str
    evidence_boundary: str

    def to_dict(self, order: int) -> dict[str, object]:
        return {
            "order": order,
            "stage": self.stage,
            "skill": self.skill,
            "score": self.score,
            "confidence": self.confidence,
            "matched": list(self.matched),
            "reason": self.reason,
            "evidence_boundary": self.evidence_boundary,
            "status": "prepared_not_observed",
        }


def build_workflow_route_plan(
    message: str,
    recommendations: object,
    *,
    selected_skill: str,
    action: str,
) -> dict[str, object] | None:
    if action == "fallback":
        return None
    recommendation_list = _recommendation_list(recommendations)
    if not recommendation_list:
        return None

    routing_text = prepare_routing_text(message)
    normalized = normalized_phrase(routing_text.scoring_text)
    tokens = routing_tokens(normalized, stopwords=_STOPWORDS)
    signal_stages = set(_stages_from_signals(normalized, tokens))
    by_skill = {item["skill"]: item for item in recommendation_list if item.get("skill")}
    definition_names = {definition.name for definition in routable_definitions()}
    steps_by_stage: dict[str, _RouteStep] = {}

    for item in recommendation_list:
        skill = str(item.get("skill", ""))
        stage = _SKILL_STAGE.get(skill)
        if not stage:
            continue
        score = _int_value(item.get("score", 0))
        if score < 4 and stage not in signal_stages:
            continue
        if stage == "learn" and stage not in signal_stages:
            continue
        step = _step_from_recommendation(stage, item)
        steps_by_stage[stage] = _better_step(stage, step, steps_by_stage.get(stage), normalized)

    for stage in signal_stages:
        if stage in steps_by_stage:
            continue
        skill = _fallback_skill_for_stage(stage, by_skill, definition_names)
        if skill is None:
            continue
        steps_by_stage[stage] = _step_from_recommendation(
            stage,
            by_skill.get(
                skill,
                {
                    "skill": skill,
                    "score": 0,
                    "confidence": "low",
                    "matched": [f"route_plan:{stage}"],
                },
            ),
        )

    if selected_skill in _SKILL_STAGE and _SKILL_STAGE[selected_skill] not in steps_by_stage:
        stage = _SKILL_STAGE[selected_skill]
        steps_by_stage[stage] = _step_from_recommendation(
            stage,
            by_skill.get(selected_skill, {"skill": selected_skill, "score": 0, "confidence": "low", "matched": []}),
        )

    stages = _ordered_stages(steps_by_stage, selected_skill=selected_skill)
    if len(stages) < 2:
        return None
    steps = [steps_by_stage[stage].to_dict(index + 1) for index, stage in enumerate(stages)]
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "multi_workflow",
        "primary_skill": selected_skill,
        "stages": stages,
        "steps": steps,
        "next_action": f"start_with_{steps[0]['skill']}",
        "claim_boundary": CLAIM_BOUNDARY,
    }


def _ordered_stages(steps_by_stage: dict[str, _RouteStep], *, selected_skill: str) -> list[str]:
    stages = [stage for stage in _STAGE_ORDER if stage in steps_by_stage]
    if selected_skill == "workflow-learning" and "learn" in stages:
        return ["learn", *(stage for stage in stages if stage != "learn")]
    return stages


def compact_workflow_route_plan(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    steps = value.get("steps", [])
    if not isinstance(steps, list):
        return None
    compact_steps: list[dict[str, object]] = []
    for item in steps:
        if not isinstance(item, dict):
            continue
        compact_steps.append(
            {
                "order": int(item.get("order", len(compact_steps) + 1)),
                "stage": str(item.get("stage", "")),
                "skill": str(item.get("skill", "")),
                "confidence": str(item.get("confidence", "low")),
                "reason": str(item.get("reason", "")),
                "evidence_boundary": str(item.get("evidence_boundary", "")),
                "status": "prepared_not_observed",
            }
        )
    if not compact_steps:
        return None
    stages = [str(item.get("stage", "")) for item in compact_steps if str(item.get("stage", ""))]
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": str(value.get("mode", "multi_workflow")),
        "primary_skill": str(value.get("primary_skill", "")),
        "stages": stages,
        "steps": compact_steps,
        "next_action": str(value.get("next_action", "")),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def _recommendation_list(recommendations: object) -> list[dict[str, object]]:
    if not isinstance(recommendations, (list, tuple)):
        return []
    items: list[dict[str, object]] = []
    for item in recommendations:
        if isinstance(item, dict):
            items.append(dict(item))
    return items


def _step_from_recommendation(stage: str, item: dict[str, object]) -> _RouteStep:
    matched = item.get("matched", [])
    return _RouteStep(
        stage=stage,
        skill=str(item.get("skill", "")),
        score=_int_value(item.get("score", 0)),
        confidence=str(item.get("confidence", "low")),
        matched=tuple(str(value) for value in matched) if isinstance(matched, list) else (),
        reason=_STAGE_REASON[stage],
        evidence_boundary=_STAGE_BOUNDARY[stage],
    )


def _better_step(stage: str, candidate: _RouteStep, current: _RouteStep | None, normalized: str) -> _RouteStep:
    if current is None:
        return candidate
    if stage == "plan" and _risk_or_review_signal(normalized):
        candidate_priority = _priority(stage, candidate.skill)
        current_priority = _priority(stage, current.skill)
        if candidate_priority < current_priority:
            return candidate
    if candidate.score > current.score:
        return candidate
    if candidate.score == current.score and _priority(stage, candidate.skill) < _priority(stage, current.skill):
        return candidate
    return current


def _priority(stage: str, skill: str) -> int:
    try:
        return _STAGE_PRIORITY.get(stage, ()).index(skill)
    except ValueError:
        return 99


def _risk_or_review_signal(normalized: str) -> bool:
    return any(
        phrase in normalized
        for phrase in (
            "risk",
            "risky",
            "unsafe",
            "dangerous",
            "review",
            "acceptance",
            "verification",
            "위험",
            "리뷰",
            "검증",
        )
    )


def _stages_from_signals(normalized: str, tokens: set[str]) -> tuple[str, ...]:
    stages: list[str] = []
    for stage in _STAGE_ORDER:
        phrases = _STAGE_SIGNAL_PHRASES.get(stage, ())
        if any(normalized_phrase(phrase) in normalized for phrase in phrases):
            stages.append(stage)
            continue
        if any(normalized_phrase(phrase) in tokens for phrase in phrases if " " not in phrase):
            stages.append(stage)
    return tuple(stages)


def _fallback_skill_for_stage(
    stage: str,
    by_skill: dict[str, dict[str, object]],
    definition_names: set[str],
) -> str | None:
    for skill in _STAGE_PRIORITY.get(stage, ()):
        if skill in by_skill or skill in definition_names:
            return skill
    return None


def _int_value(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default

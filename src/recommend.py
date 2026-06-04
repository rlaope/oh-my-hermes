from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from .skills.catalog import SkillDefinition, builtin_definitions


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9-]*")
_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "when",
    "use",
    "task",
    "request",
    "workflow",
    "skill",
    "agent",
    "hermes",
}
_FALLBACK_SKILLS = ("oh-my-hermes", "plan", "deep-interview")
_FALLBACK_WHY = "No strong catalog metadata match; start with general routing/planning guidance."


@dataclass(frozen=True)
class Recommendation:
    skill: str
    description: str
    category: str
    phase: str
    score: int
    confidence: str
    matched: tuple[str, ...]
    why: str
    suggested_prompt: str

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["matched"] = list(self.matched)
        return data


def recommend_skills(query: str, *, limit: int = 5) -> list[dict[str, object]]:
    if limit < 1:
        raise ValueError("recommend --limit must be at least 1")

    normalized_query = query.strip().lower()
    query_tokens = _tokens(normalized_query)
    definitions = list(builtin_definitions())
    scored = [_score_definition(definition, normalized_query, query_tokens, query) for definition in definitions]
    matches = [recommendation for recommendation in scored if recommendation.score > 0]
    if not matches:
        matches = _fallback_recommendations(definitions, query)
    matches.sort(key=lambda recommendation: (-recommendation.score, recommendation.skill))
    return [recommendation.to_dict() for recommendation in matches[:limit]]


def _score_definition(
    definition: SkillDefinition,
    normalized_query: str,
    query_tokens: set[str],
    original_query: str,
) -> Recommendation:
    score = 0
    matched: set[str] = set()

    for trigger in definition.triggers:
        trigger_normalized = trigger.lower()
        if _phrase_match(normalized_query, trigger_normalized):
            score += 6
            matched.add(f"trigger:{trigger_normalized}")

    name_normalized = definition.name.lower()
    if _phrase_match(normalized_query, name_normalized):
        score += 5
        matched.add(f"name:{name_normalized}")

    description_normalized = definition.description.lower()
    if _phrase_match(normalized_query, description_normalized):
        score += 3
        matched.add("description:phrase")

    use_when_normalized = definition.use_when.lower()
    if _phrase_match(normalized_query, use_when_normalized):
        score += 3
        matched.add("use_when:phrase")

    for field_name, value in (("category", definition.category), ("phase", definition.phase)):
        normalized_value = value.lower()
        if _phrase_match(normalized_query, normalized_value):
            score += 2
            matched.add(f"{field_name}:{normalized_value}")

    trigger_tokens = _tokens(" ".join(definition.triggers))
    for token in sorted(query_tokens & trigger_tokens):
        score += 3
        matched.add(f"trigger:{token}")

    metadata_tokens = _tokens(" ".join((definition.name, definition.description, definition.use_when)))
    for token in sorted(query_tokens & metadata_tokens):
        score += 1
        matched.add(f"metadata:{token}")

    matched_tuple = tuple(sorted(matched))
    return Recommendation(
        skill=definition.name,
        description=definition.description,
        category=definition.category,
        phase=definition.phase,
        score=score,
        confidence=_confidence(score),
        matched=matched_tuple,
        why=_why(matched_tuple),
        suggested_prompt=_suggested_prompt(definition.name, original_query),
    )


def _fallback_recommendations(definitions: list[SkillDefinition], query: str) -> list[Recommendation]:
    by_name = {definition.name: definition for definition in definitions}
    recommendations = []
    for name in _FALLBACK_SKILLS:
        definition = by_name.get(name)
        if definition is None:
            continue
        recommendations.append(
            Recommendation(
                skill=definition.name,
                description=definition.description,
                category=definition.category,
                phase=definition.phase,
                score=0,
                confidence="low",
                matched=(),
                why=_FALLBACK_WHY,
                suggested_prompt=_suggested_prompt(definition.name, query),
            )
        )
    return recommendations


def _tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for raw_token in _TOKEN_RE.findall(value.lower()):
        for token in (raw_token, *raw_token.split("-")):
            if len(token) >= 3 and token not in _STOPWORDS:
                tokens.add(token)
    return tokens


def _phrase_match(query: str, value: str) -> bool:
    return bool(query and value and (query in value or value in query))


def _confidence(score: int) -> str:
    if score >= 8:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def _why(matched: tuple[str, ...]) -> str:
    if not matched:
        return _FALLBACK_WHY
    sources = sorted({item.split(":", 1)[0] for item in matched})
    return f"Matched {'/'.join(sources)} metadata for this task."


def _suggested_prompt(skill: str, query: str) -> str:
    return f"Use {skill} for: {query}"

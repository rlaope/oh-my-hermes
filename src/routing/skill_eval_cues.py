"""Phrases that name checking an agent skill against its hosts, shared by the skill's triggers and routing.

"skill" is also a person's ability: "is my skill any good at chess", "my tennis
skill evaluation", "직원 스킬 평가 기준". The English phrases below therefore keep
`skill-eval` only alone or beside a word of agent skills (`EVERYDAY_SENSE_PHRASES`
in policy.py), and the Korean ones count only alone or beside a Korean anchor
(`skill_eval_korean_match`).

A host word is not proof of the object: "evaluate my skill at using Codex for
Python" names a host and still asks about a person. `skill_eval_person_sense`
keeps every phrase off when the message says a person's ability (a skill *at*
something, a skill level, staff, an interview) and names no skill artifact
(SKILL.md, a skill folder, an agent skill, loading).
"""
from __future__ import annotations

from .localization import normalized_phrase, phrase_is_spoken, routing_tokens

# Each one is also a trigger of the skill (`EVERYDAY_SENSE_PHRASES` withdraws
# a skill only on a phrase it claims).
SKILL_EVAL_SHARED_PHRASES = (
    "skill eval",
    "evaluate my skill",
    "is my skill any good",
    "skill compatibility",
)

# Named by the job, not the skill's name; every one opens with "skill" or
# carries it, so `policy._bare_first_word_names_a_longer_skill` reads them.
SKILL_EVAL_JOB_PHRASES = (
    "skill-eval",
    "skill harness check",
    "will my skill load",
    "will this skill load",
    "skill.md compatibility",
    "agent skill loads",
    "skill loads in",
    "does this skill load",
    "does my skill load",
)

# Only words the router keeps as tokens can anchor: "agent", "hermes" and
# "skill.md" are dropped by `routing_tokens`, so listing them would read as
# coverage no message can reach. SKILL.md is read by `_ARTIFACT_PHRASES` below.
SKILL_EVAL_ANCHORS = frozenset(
    {
        "agents",
        "claude",
        "codex",
        "copilot",
        "description",
        "folder",
        "frontmatter",
        "host",
        "hosts",
        "load",
        "loads",
        "omh",
        "openclaw",
        "opencode",
        "plugin",
    }
)

_KOREAN_PHRASES = tuple(normalized_phrase(p) for p in ("스킬 평가", "스킬 점검", "스킬 호환성", "스킬 괜찮은지"))
_KOREAN_ANCHORS = tuple(
    normalized_phrase(p)
    for p in ("내 스킬", "이 스킬", "skill.md", "에이전트", "클로드", "코덱스", "헤르메스", "스킬 폴더", "호스트")
)
# A person's ability: the skill is had *at* or *in* a craft, has a level, or
# belongs to staff, a candidate or a learner.
_PERSON_PHRASES = tuple(
    normalized_phrase(p)
    for p in (
        "skill at", "skills at", "skill level", "skill levels", "skill set", "skillset", "proficiency",
        "employee", "employees", "staff", "interview", "candidate", "candidates", "hiring", "student", "students",
        "직원", "사원", "팀원", "지원자", "면접", "인재", "역량", "학생", "신입", "채용",
    )
)
# Words that make a skill artifact the object of the check.
_ARTIFACT_PHRASES = tuple(
    normalized_phrase(p)
    for p in (
        "skill.md", "skill folder", "skill folders", "agent skill", "agent skills", "skill-eval", "skill harness",
        "frontmatter", "loads", "load in", "load on", "스킬 폴더", "에이전트 스킬",
    )
)
_KOREAN_FILLER = frozenset(
    routing_tokens(normalized_phrase("좀 해줘 해주세요 부탁해 부탁해요 확인해줘 확인 봐줘 해봐 체크해줘"))
)


def skill_eval_person_sense(normalized_query: str) -> bool:
    """The message says a person's ability and names no skill artifact, whatever host it also names."""
    if not any(phrase_is_spoken(normalized_query, phrase) for phrase in _PERSON_PHRASES):
        return False
    return not any(phrase_is_spoken(normalized_query, phrase) for phrase in _ARTIFACT_PHRASES)


def skill_eval_korean_match(normalized_query: str) -> bool:
    """A Korean skill-check phrase said alone or beside a word of agent skills.

    "직원 스킬 평가 기준 만들어줘" (staff skill assessment) carries other content and
    no anchor, so it does not count; "스킬 평가해줘" and "내 스킬 괜찮은지 점검해줘" do.
    "이 스킬로 일하는 직원 스킬 평가 기준" has an anchor but is about staff, so it does not.
    """
    spoken = [phrase for phrase in _KOREAN_PHRASES if phrase_is_spoken(normalized_query, phrase)]
    if not spoken or skill_eval_person_sense(normalized_query):
        return False
    if any(phrase_is_spoken(normalized_query, anchor) for anchor in _KOREAN_ANCHORS):
        return True
    words = routing_tokens(" ".join(spoken))
    leftover = {
        token for token in routing_tokens(normalized_query)
        if token not in _KOREAN_FILLER and not any(token.startswith(word) for word in words)
    }
    return not leftover


def skill_eval_korean_unanchored(normalized_query: str) -> bool:
    """True when a Korean skill-check phrase is spoken but `skill_eval_korean_match` keeps it off."""
    spoken = any(phrase_is_spoken(normalized_query, phrase) for phrase in _KOREAN_PHRASES)
    return spoken and not skill_eval_korean_match(normalized_query)


def skill_eval_names_the_check(normalized_query: str) -> bool:
    """A skill-eval job phrase is spoken about a skill artifact, not a person's ability."""
    return (
        any(phrase_is_spoken(normalized_query, normalized_phrase(phrase)) for phrase in SKILL_EVAL_JOB_PHRASES)
        and not skill_eval_person_sense(normalized_query)
    )


def skill_eval_phrase_spoken(normalized_query: str) -> bool:
    """A skill-eval job or shared phrase is spoken (the shared ones are still checked for an anchor later)."""
    return any(
        phrase_is_spoken(normalized_query, normalized_phrase(phrase))
        for phrase in (*SKILL_EVAL_JOB_PHRASES, *SKILL_EVAL_SHARED_PHRASES)
    )

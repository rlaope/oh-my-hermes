"""Phrases that name applying an OMH bot template, shared by the skill's triggers and routing.

"bot template" is also code: "create a discord bot template in python", "slack
bot template repo", "디스코드 봇 템플릿 코드 짜줘" ask for a starter project, not
for setting up a Hermes bot. The English phrases below therefore keep
`bot-template` only alone or beside an anchor (a template id, or a word that
applies, lists or shows one) through `EVERYDAY_SENSE_PHRASES` in policy.py, and
`bot_template_code_sense` keeps them off whenever the message names code, a
language or a repository, anchor or not. The Korean phrase counts only through
`bot_template_korean_match`.
"""
from __future__ import annotations

from ..catalogs.bot_templates import bot_template_ids
from .localization import normalized_phrase, phrase_is_spoken, routing_tokens

# Each one is also a trigger of the skill (`EVERYDAY_SENSE_PHRASES` withdraws a skill only on a phrase it claims).
BOT_TEMPLATE_SHARED_PHRASES = (
    "bot template",
    "bot templates",
    "apply the bot template",
    "apply a bot template",
)

# Named by the job: a template id followed by "template" ("apply the pr-review template"). Hyphenated ids are never
# everyday words ("release notes template" is not "release-notes template"), so these count wherever they are said.
BOT_TEMPLATE_JOB_PHRASES = (
    "bot-template",
    *(f"{template_id} template" for template_id in bot_template_ids()),
    *(f"{template_id} 템플릿" for template_id in bot_template_ids()),
)

# Template ids as the router keeps them (hyphenated ids stay one token), the words of their titles that name a bot's
# job, and the words that apply, list, show or use one.
BOT_TEMPLATE_ANCHORS = frozenset(
    {
        *bot_template_ids(),
        "apply",
        "applying",
        "applied",
        "use",
        "set",
        "list",
        "show",
        "which",
        "available",
        "reviewer",
        "triage",
        "inbox",
        "omh",
        "omher",
    }
)

# A starter project's words: a language, a framework, a repository, code, or the messenger a bot is coded for
# ("a discord bot template"). Any one keeps the route off unless the message also names a template id.
_CODE_TOKENS = frozenset(
    {
        "python", "typescript", "javascript", "js", "ts", "node", "nodejs", "rust", "golang", "java", "kotlin",
        "code", "coding", "scaffold", "boilerplate", "starter", "repo", "repository", "sdk", "library", "framework",
        "npm", "pip", "aiogram", "fastapi", "flask", "django", "react", "github", "gitlab",
        "discord", "telegram", "slack", "whatsapp", "chatbot",
    }
    | routing_tokens(
        normalized_phrase("코드 레포 파이썬 타입스크립트 자바스크립트 깃허브 구현 짜줘 디스코드 텔레그램 슬랙")
    )
)

_KOREAN_PHRASES = tuple(normalized_phrase(p) for p in ("봇 템플릿",))
# Korean words are matched as stems: "적용해줘" and "적용하기" both start with "적용".
# `normalized_phrase` writes Hangul as decomposed jamo, so the stems are normalized the same way.
_KOREAN_ANCHOR_STEMS = tuple(normalized_phrase(p) for p in ("적용", "목록", "보여", "어떤", "설정", "omh", "omher"))
_KOREAN_FILLER = frozenset(routing_tokens(normalized_phrase("좀 해줘 해주세요 부탁해 부탁해요 이 봇 봇에 이 봇에")))


def bot_template_code_sense(normalized_query: str) -> bool:
    """The message names code, a language, a repository or a messenger and no template id: a starter project."""
    tokens = routing_tokens(normalized_query)
    return bool(tokens & _CODE_TOKENS) and not tokens & frozenset(bot_template_ids())


def bot_template_names_the_job(normalized_query: str) -> bool:
    """A job phrase ("bot-template", "<template id> template") is spoken."""
    return any(phrase_is_spoken(normalized_query, normalized_phrase(p)) for p in BOT_TEMPLATE_JOB_PHRASES)


def bot_template_phrase_spoken(normalized_query: str) -> bool:
    return any(phrase_is_spoken(normalized_query, normalized_phrase(p)) for p in BOT_TEMPLATE_SHARED_PHRASES)


def bot_template_korean_match(normalized_query: str) -> bool:
    """"봇 템플릿" said alone, or beside a word that applies, lists or shows one, or a template id, and no code word.

    "봇 템플릿 적용해줘" and "이 봇에 pr-review 봇 템플릿 적용해줘" count; "디스코드 봇 템플릿 코드 짜줘" and
    "봇 템플릿 만들어줘" (a starter project) do not.
    """
    if not any(phrase_is_spoken(normalized_query, phrase) for phrase in _KOREAN_PHRASES):
        return False
    if bot_template_code_sense(normalized_query):
        return False
    tokens = routing_tokens(normalized_query)
    if tokens & frozenset(bot_template_ids()):
        return True
    words = routing_tokens(" ".join(_KOREAN_PHRASES))
    leftover = {token for token in tokens if token not in words and token not in _KOREAN_FILLER}
    return not leftover or any(token.startswith(_KOREAN_ANCHOR_STEMS) for token in leftover)


def bot_template_korean_unanchored(normalized_query: str) -> bool:
    """True when "봇 템플릿" is spoken but `bot_template_korean_match` keeps it off."""
    spoken = any(phrase_is_spoken(normalized_query, phrase) for phrase in _KOREAN_PHRASES)
    return spoken and not bot_template_korean_match(normalized_query)

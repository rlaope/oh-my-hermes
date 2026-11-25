"""Phrases that name applying an OMH bot template, shared by the skill's triggers and routing.

"bot template" is also code: "create a discord bot template in python", "slack
bot template repo", "디스코드 봇 템플릿 코드 짜줘" ask for a starter project, not
for setting up a Hermes bot. The English phrases below therefore keep
`bot-template` only alone or beside an anchor (a template id, or a word that
applies, lists or shows one) through `EVERYDAY_SENSE_PHRASES` in policy.py, and
`bot_template_code_sense` keeps them off whenever the message names code, a
language, a repository or a messenger (unless it names a template id) or a file
being edited (always). The Korean phrase counts only through
`bot_template_korean_match`.

A template id is also a file name: "update the release-notes template in
.github" and "our pr-review template in the repo" edit a repository's own
markdown template, and "apply the release-notes template" alone does not say
which. So "<id> template" counts only in the bot sense, beside the word bot (봇),
and never beside a file, repository, code or document word.

One forge word is excused: "apply the pr-review template to this bot for our
github prs" names where the bot reviews. GitHub and GitLab (깃허브, 깃랩) stand
nothing down when the message applies a template whose Hermes skills read
GitHub to a bot, the apply verb governing the template, nothing deferred and no
other action asked (`_applied_template_ids`, `_sense_tokens`). The app lanes
that would take such a sentence stand down through `bot_template_id_applied`,
only for an app the applied template itself reads.
"""
from __future__ import annotations

from ..catalogs.bot_templates import bot_template, bot_template_ids
from .localization import normalized_phrase, phrase_is_spoken, routing_tokens

# Each one is also a trigger of the skill (`EVERYDAY_SENSE_PHRASES` withdraws a skill only on a phrase it claims).
BOT_TEMPLATE_SHARED_PHRASES = (
    "bot template",
    "bot templates",
    "apply the bot template",
    "apply a bot template",
)

# Named by the job: a template id followed by "template" ("apply the pr-review template to this bot"). They count only
# in the bot sense and never in a file sense (`bot_template_names_the_job`).
BOT_TEMPLATE_JOB_PHRASES = (
    "bot-template",
    *(f"{template_id} template" for template_id in bot_template_ids()),
    *(f"{template_id} 템플릿" for template_id in bot_template_ids()),
)

# Each template id as the router keeps it: one hyphenated token ("pr-review"), or its first hyphenated token when
# the tokenizer splits on a stopword ("meeting-to-issues" -> "meeting-to").
_ID_TOKENS = frozenset(
    token for template_id in bot_template_ids() for token in routing_tokens(template_id) if "-" in token
)

# Template ids as the router keeps them, the words of their titles that name a bot's job, and the words that apply,
# list or show one ("use" is a stopword the router drops, so it is no anchor).
BOT_TEMPLATE_ANCHORS = frozenset(
    {
        *_ID_TOKENS,
        "apply",
        "applying",
        "applied",
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

# A repository's own template file being edited: these keep every phrase off, a template id or not. "add" is left
# out on purpose: "add the pr-review template to this bot" applies one, and every file-sense sentence seen with it
# also says file, section, markdown, repo or changelog.
_FILE_TOKENS = frozenset(
    {"file", "files", "markdown", "md", "section", "changelog", "generator", "edit", "update", "rename", "readme",
     "repo", "repository", "github", "gitlab", "pull_request_template", "issue_template", "document", "documents",
     "doc", "docs"}
)
# Korean stems, normalized like the query (decomposed jamo): 파일, 수정, 레포, 깃허브, 마크다운, 섹션, 문서.
_KOREAN_FILE_STEMS = tuple(normalized_phrase(p) for p in ("파일", "수정", "레포", "깃허브", "마크다운", "섹션", "문서"))
# Another action on a template than applying it: removing it or exporting its data. Any one keeps every phrase off,
# a template id or not: the skill applies and removes nothing, so "delete the inbox-triage bot template" must not reach
# a skill that answers with an apply plan.
_OTHER_ACTION_TOKENS = frozenset(
    {"delete", "deleting", "remove", "removing", "uninstall", "drop", "export", "exporting", "json", "yaml", "csv"}
)
_KOREAN_OTHER_ACTION_STEMS = tuple(normalized_phrase(p) for p in ("삭제", "제거", "지워", "지우", "내보내"))
# A language or code word: it stands a job phrase down even beside a template id ("build a bot from the
# release-notes template in python"). The messengers are left out: a channel watch names Slack or Discord.
_LANGUAGE_TOKENS = _CODE_TOKENS - frozenset({"discord", "telegram", "slack", "whatsapp", "chatbot"}) - routing_tokens(
    normalized_phrase("디스코드 텔레그램 슬랙")
)
# The bot sense of "<id> template": the message names a bot ("to this bot", "이 봇에").
_JOB_ANCHORS = frozenset({"bot", "bots"})
_KOREAN_JOB_STEMS = tuple(normalized_phrase(p) for p in ("봇",))

# A template applied to a bot by id (`_applied_template_ids`): the apply verb governs the template ("apply the
# pr-review template", "set this bot up with the pr-review template", "pr-review 템플릿 적용해줘"), the word bot (봇) is
# said, and nothing defers it or asks for another action now. Then the forge or app that template reads is where the
# bot will work: "apply the pr-review template to this bot for our github prs" excuses GitHub as a code word
# (`_sense_tokens`), and the lanes that react to that app's own items stand down (`bot_template_id_applied`).
_EN_APPLY_LEADS = (
    ("apply", "the"), ("applying", "the"), ("use", "the"), ("set", "up", "the"), ("add", "the"),
    ("set", "this", "bot", "up", "with", "the"), ("set", "the", "bot", "up", "with", "the"),
)
_KOREAN_APPLY_STEMS = tuple(normalized_phrase(p) for p in ("적용", "설정"))
_KOREAN_TEMPLATE_STEM = normalized_phrase("템플릿")
_KOREAN_BOT = normalized_phrase("봇")
# Deferring or declining the apply: "don't apply ...", "... can wait", "적용하지 말고".
_APPLY_DEFERRALS = tuple(
    normalized_phrase(p) for p in ("don't", "dont", "do not", "instead of", "later", "can wait", "aside", "not now")
)
_KOREAN_DEFERRAL_STEMS = tuple(normalized_phrase(p) for p in ("말고", "나중"))
# Another action on a concrete item in the same message ("... and merge github PR 12", "... fix the sentry alert that
# fired"): the apply plan would swallow it, so the message keeps its old route. A number or version is an item too.
_ITEM_ACTION_WORDS = frozenset(
    {
        "merge", "merging", "close", "closing", "comment", "commenting", "label", "labels", "publish", "publishing",
        "post", "posting", "create", "creating", "fix", "fixing", "research", "review", "reviewing", "open", "run",
        "now", "fired", "then", "first",
        # app-work-intake's own action verbs: "..., investigate why it is noisy"
        "investigate", "investigating", "debug", "debugging", "handoff", "triage", "triaging",
    }
)
_KOREAN_ITEM_ACTION_STEMS = tuple(
    normalized_phrase(p)
    for p in (
        "고쳐", "수정", "발행", "코멘트", "리뷰", "머지", "닫아", "만들어", "조사", "올려", "게시", "지금", "디버그", "원인",
        "넘겨", "분류", "트리아지",
    )
)
# GitHub's own CI and config: "apply the pr-review bot template to the github action workflow" edits a workflow file.
_FORGE_CONFIG_WORDS = frozenset({"action", "actions", "workflow", "workflows", "ci", ".github"})
_KOREAN_FORGE_CONFIG_STEMS = tuple(normalized_phrase(p) for p in ("액션", "워크플로", "워크플로우"))
_FORGE_TOKENS = frozenset({"github", "gitlab"})
_KOREAN_FORGE_STEMS = tuple(normalized_phrase(p) for p in ("깃허브", "깃랩"))
_FORGE_TEMPLATE_IDS = frozenset(
    template_id for template_id in bot_template_ids() if "github" in bot_template(template_id).hermes_skills
)
# What each template reads, as it may be said: its apps and Hermes skills, GitLab beside GitHub, Jira and Confluence
# for Atlassian, and the Korean names.
_APP_ALIASES = {"github": ("gitlab", "깃허브", "깃랩"), "atlassian": ("jira", "confluence", "지라"),
                "sentry": ("센트리",), "datadog": ("데이터독",), "grafana": ("그라파나",), "linear": ("리니어",),
                "notion": ("노션",), "obsidian": ("옵시디언",)}
_TEMPLATE_APP_NAMES = {
    template_id: tuple(
        normalized_phrase(name)
        for app in (*(a.name for a in bot_template(template_id).apps), *bot_template(template_id).hermes_skills)
        for name in (app, *_APP_ALIASES.get(app, ()))
    )
    for template_id in bot_template_ids()
}

_KOREAN_PHRASES = tuple(normalized_phrase(p) for p in ("봇 템플릿",))
# Korean words are matched as stems: "적용해줘" and "적용하기" both start with "적용".
# `normalized_phrase` writes Hangul as decomposed jamo, so the stems are normalized the same way.
_KOREAN_ANCHOR_STEMS = tuple(
    normalized_phrase(p) for p in ("적용", "목록", "보여", "어떤", "설정", "추천", "시작", "omh", "omher")
)
_KOREAN_FILLER = frozenset(routing_tokens(normalized_phrase("좀 해줘 해주세요 부탁해 부탁해요 이 봇 봇에 이 봇에")))


def _words(normalized_query: str) -> list[str]:
    return [word.strip(",!?;:()[]{}\"'`") for word in normalized_query.split()]


def _template_follows(words: list[str], index: int) -> bool:
    """"<id> template", "<id> bot template", "<id> 템플릿" or "<id> 봇 템플릿" at *index*."""
    following = words[index + 1:index + 3]
    if following[:1] and following[0] in ("bot", _KOREAN_BOT):
        following = following[1:]
    return bool(following) and (following[0].startswith("template") or following[0].startswith(_KOREAN_TEMPLATE_STEM))


_BOT_DETERMINERS = ("this", "the", "our", "my")


def _apply_governs(words: list[str], index: int) -> bool:
    """The apply verb takes the template at *index*, and the template goes to a bot.

    English: a lead before it ("apply the", "set this bot up with the"), and the bot inside the phrase ("<id> bot
    template"), in the lead, or right after it ("... template to|on|for this bot"). Korean: an apply word after
    "<id> (봇) 템플릿", with 봇 said in the message ("이 봇에 pr-review 템플릿 적용해줘").
    """
    lead = next(
        (lead for lead in _EN_APPLY_LEADS if tuple(words[max(0, index - len(lead)):index]) == lead), None
    )
    if lead is not None:
        if "bot" in lead or words[index + 1:index + 2] == ["bot"]:
            return True
        after = words[index + 2:index + 5]
        return len(after) == 3 and after[0] in ("to", "on", "for") and after[1] in _BOT_DETERMINERS and after[2] in (
            "bot", "bots"
        )
    korean_bot = any(word.startswith(_KOREAN_BOT) for word in words)
    return korean_bot and any(word.startswith(_KOREAN_APPLY_STEMS) for word in words[index + 2:index + 5])


def _another_action_or_deferral(normalized_query: str, words: list[str]) -> bool:
    if any(phrase_is_spoken(normalized_query, phrase) for phrase in _APPLY_DEFERRALS):
        return True
    ids = set(bot_template_ids())
    for index, word in enumerate(words):
        if word in ids:
            continue
        following = words[index + 1] if index + 1 < len(words) else ""
        if word.startswith(_KOREAN_DEFERRAL_STEMS) or (word.endswith(normalized_phrase("하지")) and following.startswith(
            normalized_phrase("마")
        )):
            return True
        # "merge requests" is GitLab's name for a pull request, not a merge
        if word in ("merge", "merging") and following.startswith("request"):
            continue
        if word in _ITEM_ACTION_WORDS or word.startswith(_KOREAN_ITEM_ACTION_STEMS) or any(c.isdigit() for c in word):
            return True
        # "적용하고 ...": the apply and then something else
        if word.startswith(_KOREAN_APPLY_STEMS) and word.endswith(normalized_phrase("하고")):
            return True
    return False


def _applied_template_ids(normalized_query: str) -> frozenset[str]:
    """The templates this message applies to a bot, or none (see `_EN_APPLY_LEADS`)."""
    words = _words(normalized_query)
    if not any(word in _JOB_ANCHORS or word.startswith(_KOREAN_JOB_STEMS) for word in words):
        return frozenset()
    ids = set(bot_template_ids())
    applied = frozenset(
        word for index, word in enumerate(words)
        if word in ids and _template_follows(words, index) and _apply_governs(words, index)
    )
    if not applied or _another_action_or_deferral(normalized_query, words):
        return frozenset()
    return applied


def _sense_tokens(normalized_query: str) -> set[str]:
    """The message's tokens, less the forge word when a template that reads GitHub is applied to a bot and no GitHub
    CI or config word is said (`_FORGE_TOKENS`)."""
    tokens = set(routing_tokens(normalized_query))
    if not (tokens & _FORGE_TOKENS or any(token.startswith(_KOREAN_FORGE_STEMS) for token in tokens)):
        return tokens
    if not _applied_template_ids(normalized_query) & _FORGE_TEMPLATE_IDS:
        return tokens
    words = _words(normalized_query)
    if tokens & _FORGE_CONFIG_WORDS or _FORGE_CONFIG_WORDS & set(words):
        return tokens
    if any(word.startswith(_KOREAN_FORGE_CONFIG_STEMS) for word in words):
        return tokens
    return {token for token in tokens if token not in _FORGE_TOKENS and not token.startswith(_KOREAN_FORGE_STEMS)}


def bot_template_file_sense(normalized_query: str) -> bool:
    """The message edits a repository's own template file: a file word, in English or Korean."""
    tokens = _sense_tokens(normalized_query)
    return bool(tokens & _FILE_TOKENS) or any(token.startswith(_KOREAN_FILE_STEMS) for token in tokens)


def bot_template_other_action(normalized_query: str) -> bool:
    """The message removes or exports a template rather than applying it, in English or Korean."""
    tokens = routing_tokens(normalized_query)
    return bool(tokens & _OTHER_ACTION_TOKENS) or any(token.startswith(_KOREAN_OTHER_ACTION_STEMS) for token in tokens)


def bot_template_code_sense(normalized_query: str) -> bool:
    """Not an apply: code or a language (whatever it names), a messenger with no template id, a file being edited, or
    a template removed or exported."""
    if bot_template_file_sense(normalized_query) or bot_template_other_action(normalized_query):
        return True
    tokens = _sense_tokens(normalized_query)
    # a language or code word is a starter project even beside a template id ("write a pr-review bot template in
    # python"); only a messenger word is excused by an id ("the channel-watch bot template for slack")
    if tokens & _LANGUAGE_TOKENS:
        return True
    return bool(tokens & _CODE_TOKENS) and not tokens & _ID_TOKENS


def bot_template_names_the_job(normalized_query: str) -> bool:
    """A job phrase ("bot-template", "<template id> template") spoken in the bot sense (beside the word bot or 봇) and
    not about a file, a repository, code, a language or a document, nor removing or exporting a template."""
    if not any(phrase_is_spoken(normalized_query, normalized_phrase(p)) for p in BOT_TEMPLATE_JOB_PHRASES):
        return False
    if bot_template_file_sense(normalized_query) or bot_template_other_action(normalized_query):
        return False
    tokens = _sense_tokens(normalized_query)
    if tokens & _LANGUAGE_TOKENS:
        return False
    return bool(tokens & _JOB_ANCHORS) or any(token.startswith(_KOREAN_JOB_STEMS) for token in tokens)


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
    if tokens & _ID_TOKENS:
        return True
    words = routing_tokens(" ".join(_KOREAN_PHRASES))
    leftover = {token for token in tokens if token not in words and token not in _KOREAN_FILLER}
    return not leftover or any(token.startswith(_KOREAN_ANCHOR_STEMS) for token in leftover)


def bot_template_id_applied(normalized_query: str) -> bool:
    """A template applied to a bot by id (`_applied_template_ids`), spoken as a template phrase with no code, language,
    file, removal or export word, and naming an app that template itself reads.

    "apply the pr-review template to this bot for our github prs" and "apply the alert-triage template to this bot for
    our sentry alerts" set a bot up; the app is where it will work, so the lanes that react to that app's own events or
    items stand down for it. "apply the inbox-triage template to this bot for our github issues" names an app that
    template does not read, so it does not.
    """
    applied = _applied_template_ids(normalized_query)
    if not applied:
        return False
    tokens = routing_tokens(normalized_query)
    names = tuple(name for template_id in applied for name in _TEMPLATE_APP_NAMES[template_id])
    if not any(token in names or token.startswith(names) for token in tokens if not token.isascii()) and not (
        set(names) & tokens
    ):
        return False
    if bot_template_names_the_job(normalized_query):
        return True
    spoken = bot_template_phrase_spoken(normalized_query) or any(
        phrase_is_spoken(normalized_query, phrase) for phrase in _KOREAN_PHRASES
    )
    return spoken and not bot_template_code_sense(normalized_query)


def bot_template_korean_unanchored(normalized_query: str) -> bool:
    """True when "봇 템플릿" is spoken but `bot_template_korean_match` keeps it off."""
    spoken = any(phrase_is_spoken(normalized_query, phrase) for phrase in _KOREAN_PHRASES)
    return spoken and not bot_template_korean_match(normalized_query)

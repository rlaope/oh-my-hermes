"""When a message is a plain knowledge question: one short sentence, no work object.

"Explain TCP vs UDP briefly" or "클로저가 뭐야?" asks the model to answer from
what it knows. The skill catalog's words ("explain", "review", "merge") also
appear in such questions, so a token-only match would hang a workflow on a
message that has no work in it. This predicate is the one place that says
"plain question"; the per-turn candidate line (`skill_shortlist`) and the route
hint's token-only rules (`awareness`) both stand down when it holds.

It fails closed: a message is plain only in a few concept shapes, and every
work or status question keeps its hint. A message is plain only when all of
these hold:

- one line (no newline anywhere in the raw message), one sentence, at most 20
  words (English) or 40 characters (Hangul);
- no URL, file path (POSIX or a Windows drive), code fence, backtick, or
  `#<number>`;
- no first or second person work owner (I, my, me, we, our, us; 내, 제, 우리);
- no OMH or agent vocabulary (omh, hermes, skill, workflow, agent, codex, ci,
  pr, ...), read as Latin words in either language;
- English: it opens with a concept cue (explain, what, what's, define,
  describe, difference, meaning, "best way"), optionally after "quick
  question", a greeting, please, or "can you" / "could you" followed by
  explain, describe, define or tell; and it names no deictic work object
  (this, these, my, our, attached, ... followed within three words by paper,
  pdf, file, code, repo, pr, log, trace, error, project, ...);
- Hangul: it carries a concept cue (뭐야, 차이, 설명해줘, 알려줘, 방법, ...)
  and no status or task word (지금, 됐, 했어, 찾아, 점검, 상태, 고쳐, ...),
  no deictic, and no work noun.

Only words are read, on a message already capped in length. Stdlib only.
"""

from __future__ import annotations

import re

_MAX_WORDS = 20
_MAX_HANGUL_CHARS = 40

_HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
_WORD_RE = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_SENTENCE_BREAK_RE = re.compile(r"[.!?]\s+\S")
# A URL, a file path (a slash between word characters, a dotted file name with
# a known extension, a home or relative prefix, a Windows drive), a code fence
# or backtick, or an issue / PR number.
_WORK_SHAPE_RE = re.compile(
    r"https?://|www\.|`|#\d"
    r"|(?:^|\s)(?:~|\.{1,2})?/\S"
    r"|\w/\w"
    r"|[A-Za-z]:\\"
    r"|\b\w+\.(?:py|js|ts|tsx|jsx|json|ya?ml|toml|md|txt|csv|pdf|rs|go|java|sh|c|cpp|h|rb|sql)\b",
    re.IGNORECASE,
)

_LEAD_FILLERS = (
    "quick question:",
    "quick question",
    "hey,",
    "hey",
    "hi,",
    "hi",
    "hello,",
    "hello",
    "please",
    "pls",
)
# "can you explain ..." is a concept request; "can you do ..." is work.
_COURTESY_OPENERS = ("can you", "could you", "would you", "will you")
_COURTESY_VERBS = frozenset({"explain", "describe", "define", "tell"})
_QUESTION_OPENERS = frozenset(
    {"explain", "what", "what's", "whats", "define", "describe", "difference", "meaning"}
)
# A person who owns the work: "my CI", "should we", "for us".
_WORK_OWNERS = frozenset({"i", "i'm", "my", "me", "we", "our", "us", "ours"})
# OMH and agent vocabulary: a question about these is about the user's setup.
_AGENT_VOCABULARY = frozenset(
    {
        "omh", "hermes", "skill", "skills", "workflow", "workflows", "agent", "agents", "codex", "claude",
        "ulw", "dag", "plugin", "plugins", "gateway", "cron", "ci", "pr", "prs",
    }
)
# A task verb anywhere after the opener turns the question into work: "explain
# the outage and write a postmortem", "explain how to fix the deployment",
# "what should go in the launch announcement".
_WORK_VERBS = frozenset(
    {
        "fix", "fixes", "fixing", "repair", "patch", "draft", "write", "rewrite", "produce", "create", "make",
        "build", "generate", "implement", "flag", "reply", "respond", "recommend", "plan", "prepare", "review",
        "audit", "debug", "deploy", "migrate", "refactor", "update", "summarize", "summarise", "triage",
        "investigate", "diagnose", "resolve", "compare", "analyze", "analyse", "estimate", "propose", "should",
    }
)
_DEICTICS = frozenset({"this", "these", "that", "those", "my", "our", "attached", "your", "its", "their"})
_WORK_NOUNS = frozenset(
    {
        "paper", "papers", "pdf", "pdfs", "file", "files", "code", "codebase", "repo", "repos", "repository",
        "pr", "prs", "log", "logs", "trace", "traceback", "error", "errors", "project", "projects",
        "ci", "build", "pipeline", "server", "service", "app", "bug", "issue", "function", "script",
        "query", "config", "test", "tests", "branch", "commit", "diff", "deck", "doc", "docs",
        "document", "dataset", "data", "spreadsheet", "screenshot", "image", "email", "ticket",
        "arxiv", "stack", "crash", "output", "report", "database", "schema", "module", "class",
        "refactor",
    }
)
_DEICTIC_WINDOW = 3

_HANGUL_QUESTION_CUES = (
    "뭐야", "뭐예요", "뭐에요", "뭔가요", "뭐임", "무엇인가", "차이", "설명해줘", "설명해 줘", "알려줘", "방법",
)
# A status check or a task: "어디까지 됐어?", "지금 뭐하고 있는지 알려줘".
_HANGUL_STATUS_CUES = (
    "지금", "됐", "했어", "했나", "찾아", "점검", "상태", "이상해", "고쳐", "만들어",
    # Task verbs: "고객 불만 요약하고 답장 방법 알려줘".
    "요약", "작성", "답장", "수정", "정리", "써줘", "짜줘", "계획", "리뷰", "검토", "분석", "해결", "고치",
)
_HANGUL_WORK_NOUNS = (
    "논문", "파일", "코드", "레포", "리포", "로그", "에러", "오류", "프로젝트", "첨부", "스택",
    "서버", "빌드", "배포",
)
_HANGUL_DEICTIC_RE = re.compile(r"(?:^|\s)(?:이|저|그|우리|내|제)(?:\s|$)|(?:^|\s)(?:우리|내가|제가)")


def plain_question(message: str) -> bool:
    """True for a one-sentence knowledge question with no work object."""
    if not message or "\n" in message or "\r" in message:
        return False
    text = message.strip()
    if not text or len(text) > 200:
        return False
    if _WORK_SHAPE_RE.search(text) or _SENTENCE_BREAK_RE.search(text):
        return False
    lowered = text.lower().replace("\u2019", "'")
    words = _WORD_RE.findall(lowered)
    if any(word in _AGENT_VOCABULARY for word in words):
        return False
    if _HANGUL_RE.search(text):
        return _plain_hangul(text)
    return _plain_english(lowered, words)


def _plain_hangul(text: str) -> bool:
    if len(text) > _MAX_HANGUL_CHARS:
        return False
    if any(noun in text for noun in _HANGUL_WORK_NOUNS) or any(cue in text for cue in _HANGUL_STATUS_CUES):
        return False
    if _HANGUL_DEICTIC_RE.search(text):
        return False
    return any(cue in text for cue in _HANGUL_QUESTION_CUES)


def _plain_english(lowered: str, all_words: list[str]) -> bool:
    if not lowered.isascii() or any(word in _WORK_OWNERS for word in all_words):
        return False
    stripped = lowered
    for _ in range(2):
        for filler in _LEAD_FILLERS:
            if stripped.startswith(filler) and not stripped[len(filler) : len(filler) + 1].isalnum():
                stripped = stripped[len(filler) :].lstrip(" ,:")
                break
    words = _WORD_RE.findall(stripped)
    if not words or len(words) > _MAX_WORDS:
        return False
    if len(words) > 2 and " ".join(words[:2]) in _COURTESY_OPENERS:
        if words[2] not in _COURTESY_VERBS:
            return False
    elif words[0] == "best":
        if words[1:2] != ["way"]:
            return False
    elif words[0] not in _QUESTION_OPENERS:
        return False
    if any(word in _WORK_VERBS for word in words[1:]):
        return False
    for index, word in enumerate(words):
        if word in _DEICTICS and any(
            following in _WORK_NOUNS for following in words[index + 1 : index + 1 + _DEICTIC_WINDOW]
        ):
            return False
    return True

"""A request's command verb, and the verbs that make it a code edit: one list for every reader.

The router's direct code-edit guard (`omh.routing.policy`) and the
workflow-intent classifier (`workflow_intent`, which the router and the
bundle's route hint share) both ask whether a request commands an edit, so the
words live here, in a bundle module both can import without a cycle and that a
host without the `omh` package can load. Stdlib only.
"""

from __future__ import annotations

import re
import unicodedata

from .korean_request import korean_request
from .request_lead import after_courtesy, courtesy_opener_length

DIRECT_CODING_EDIT_VERBS = frozenset(
    {"add", "adjust", "build", "change", "delete", "edit", "fix", "implement", "make", "patch", "remove", "rename", "set", "tweak", "update"}
)
# A request also opens with a code edit on these verbs, which the direct
# code-edit guard in `policy` does not read: "OMH: migrate the loader to
# pathlib", "refactor the parser". Only `leads_with_code_edit` reads them.
_CODE_EDIT_LEAD_VERBS = DIRECT_CODING_EDIT_VERBS | frozenset({"migrate", "refactor", "rewrite"})
# A request that names the tool before the edit: "using OMH, rename ...",
# "with Hermes, add ...". The tool is one of these names, then the verb.
_TOOL_LEADS = frozenset({"using", "with"})
_TOOL_NAMES = frozenset({"omh", "oh-my-hermes", "hermes"})
# The Korean requested verbs of a code edit, as `korean_request` reads them: a
# 하다 verb's noun ("수정" from "수정해줘") or the stem before the ending ("고쳐"
# from "고쳐줘"). The same verbs the direct code-edit guard in `policy` reads,
# with 작성 (write) added: "테스트 작성해줘" asks for code.
KOREAN_CODE_EDIT_PREDICATES = frozenset(
    {"고쳐", "수정", "추가", "작성", "구현", "개선", "삭제", "제거", "변경", "바꿔", "넣어", "만들어"}
)
# The Korean side of `_CODE_EDIT_LEAD_VERBS`: "리팩터링해줘", "마이그레이션해줘".
# Only `leads_with_code_edit` reads them.
_KOREAN_CODE_EDIT_LEAD_PREDICATES = KOREAN_CODE_EDIT_PREDICATES | frozenset(
    {"리팩터링", "리팩토링", "마이그레이션", "재작성"}
)

# The verbs a clause opens with when it gives the user's own command ("now run
# it on staging", "copy them to the backup folder"), after the courtesy openers
# `command_words` strips ("now", "so", "please", "go ahead and"). The code-edit
# verbs are among them. "look", "see" and "record" are not: "let's look at
# why" asks about OMH's own routing.
REQUEST_COMMAND_VERBS = DIRECT_CODING_EDIT_VERBS | frozenset(
    {
        "run", "write", "copy", "open", "show", "list", "summarize", "summarise", "move", "paste", "tag",
        "refactor", "deploy", "release", "merge", "push", "commit", "create", "generate", "translate",
        "format", "convert", "archive", "count", "print", "start", "install", "publish", "send", "export",
        "review", "test", "upload", "download", "sort", "draft", "restart", "revert", "apply", "execute",
        "bump", "ship", "rerun", "retry", "check", "find", "explain",
    }
)
# Two-word commands whose first word alone is not one: "kick off a run".
_REQUEST_COMMAND_PHRASES = frozenset({("kick", "off")})
# A command verb followed by these asks about what happened rather than for
# work: "check why", "find out why", "explain what happened", "show me why",
# "list the reasons". The object pronoun ("me", "us") and "the" are skipped.
_INQUIRY_AFTER_VERB = (("why",), ("out",), ("what", "happened"), ("reason",), ("reasons",))
_INQUIRY_VERBS = frozenset({"check", "find", "explain", "show", "list", "tell"})
_INQUIRY_SKIPPED = frozenset({"me", "us", "the"})

# The word before a verb that still makes it the command: "use X to fix",
# "help me fix", or a second command joined by "and"/"then".
_COMMAND_INTRODUCERS = frozenset({"to", "me", "and", "then"})
# A request that hands the task to someone opens with one of these, then names
# who, then the verb: "use OMH to fix", "have Hermes add", "ask OMH to update".
_DELEGATING_LEADS = frozenset({"use", "have", "let", "ask", "get", "tell"})
_WORD = re.compile(r"[a-z0-9#][a-z0-9#+.-]*")
# Where a Korean message's clauses part: a comma, an aside in parentheses
# ("코드 고쳐줘 (OMH 세션)", "테스트 작성해줘, OMH 환경이야"), a line break, or
# the end of a sentence ("OMH가 설정 파일을 골랐어. 타임아웃 수정해줘"). A
# sentence keeps its own mark for `korean_request` to read.
_KOREAN_CLAUSE_BREAK = re.compile(r"[,，(（)）\n]|(?<=[.!?。])")


def ordered_words(text: str) -> list[str]:
    """The words of folded `text`, in order: the tokenizer `command_words` reads."""
    return _WORD.findall(text)


# The words of a message from its command verb on, after the courtesy openers
# and the address to the assistant ("please", "can you", "omh", "hermes,") that
# every reader of a request's opening strips (`request_lead.COURTESY_OPENERS`).
# Used only to NARROW guards: an edit verb that is not the command verb does
# not make a request an edit.
def command_words(normalized_query: str) -> list[str]:
    return ordered_words(after_courtesy(normalized_query.strip()))


def commanded_words(words: list[str]) -> set[str]:
    """The command verb, a verb introduced as the task, or a second command joined by "and"/"then"."""
    return set(words[:1]) | {words[i] for i in range(1, len(words)) if words[i - 1] in _COMMAND_INTRODUCERS}


def gives_command(clause: str) -> bool:
    """`clause` (folded) opens with the user's own command: a code-edit lead, or a `REQUEST_COMMAND_VERBS` verb.

    Not an inquiry verb that asks why: "show me why", "find out why",
    "explain what happened", "list the reasons".
    """
    words = command_words(clause)
    if words and tuple(words[:2]) in _REQUEST_COMMAND_PHRASES:
        return True
    if words and words[0] in _INQUIRY_VERBS:
        rest = words[1:]
        while rest[:1] and rest[0] in _INQUIRY_SKIPPED:
            rest = rest[1:]
        if any(tuple(rest[: len(inquiry)]) == inquiry for inquiry in _INQUIRY_AFTER_VERB):
            return False
    return bool(words) and words[0] in REQUEST_COMMAND_VERBS or leads_with_code_edit(clause)


# What "find out" asks when it has no clause of its own and so refers to the
# clause before it: "find out why", "find out the reason", "find out what
# happened (there)", "find out what caused it", "find out how that happened".
_FIND_OUT_BARE_QUESTIONS = frozenset(
    {
        ("why",), ("reason",), ("reasons",), ("the", "reason"), ("the", "reasons"),
        ("what", "happened"), ("what", "went", "wrong"),
        ("what", "caused", "it"), ("what", "caused", "that"), ("what", "caused", "this"),
        ("how", "it", "happened"), ("how", "that", "happened"), ("how", "this", "happened"),
    }
)
_FIND_OUT_BARE_TAILS = frozenset({"there", "here", "again", "for", "me", "us", "please", "pls", "thanks"})


# A find-out clause that asks about OMH's own choice: "find out what made it
# pick that", "find out why OMH routed it there", "find out what led it to do
# that". Its subject is OMH or a pronoun for it, then a choice verb.
_CHOICE_SUBJECTS = frozenset({"it", "omh", "they", "that"})
_CHOICE_VERB_FORMS = frozenset(
    {
        "pick", "picks", "picked", "picking", "choose", "chooses", "chose", "chosen", "choosing",
        "select", "selects", "selected", "selecting", "route", "routes", "routed", "routing",
        "decide", "decides", "decided",
    }
)
_DO_THAT = frozenset({("do", "that"), ("did", "that"), ("does", "that"), ("do", "this"), ("did", "this"), ("do", "so")})


def find_out_asks_about_choice(clause: str) -> bool:
    """`clause` is "find out" with a clause of its own about OMH's choice ("find out what made it pick that")."""
    rest = _after_find_out(clause)
    if not rest:
        return False
    pairs = list(zip(rest, rest[1:]))
    return any(subject in _CHOICE_SUBJECTS and verb in _CHOICE_VERB_FORMS for subject, verb in pairs) or any(
        pair in _DO_THAT for pair in pairs
    )


# How a Korean clause ends when it asks or tells someone to do something,
# whatever the verb: "정리해 줘", "손봐줘", "다듬어 주세요", "바꿔볼래?", "갈아엎자",
# "고쳐라", "업데이트 좀 해", "해 줄 수 있어?". Read on the clause's last words,
# composed, after the closing marks. A statement in the casual 해 form ("이상해")
# reads as a request too; where this is read, that only gives up a reading.
_KOREAN_REQUEST_ENDINGS = (
    "줘", "줘요", "주세요", "주라", "줄래", "줄래요", "주실래요", "주시겠어요", "봐", "봐요", "볼래", "볼래요",
    "해", "해요", "해라", "하자", "자", "라", "세요", "십시오", "부탁해", "부탁해요", "부탁드려요", "부탁드립니다",
)
_KOREAN_ASKING_TAILS = ("줄 수 있어", "줄 수 있어요", "줄 수 있나요", "주실 수 있나요", "주실 수 있어요")
_CLOSING_MARKS = " \t?!.~。！？"


def korean_clauses(text: str) -> list[str]:
    """The Korean clauses of folded `text`, split as the code-edit lead splits them."""
    return [clause for clause in _KOREAN_CLAUSE_BREAK.split(text) if clause.strip()]


def ends_in_korean_request(clause: str) -> bool:
    """`clause` ends in a Korean request or imperative ending (`_KOREAN_REQUEST_ENDINGS`), whatever its verb."""
    composed = unicodedata.normalize("NFC", clause).rstrip(_CLOSING_MARKS)
    words = composed.split()
    if not words or not any("\uac00" <= char <= "\ud7a3" for char in words[-1]):
        return False
    if any(composed.endswith(tail) for tail in _KOREAN_ASKING_TAILS):
        return True
    return words[-1].endswith(_KOREAN_REQUEST_ENDINGS)


def find_out_refers_back(clause: str) -> bool:
    """`clause` is "find out" with only a bare cause question, about the clause before it ("find out why").

    False for "find out" with its own content clause ("find out which keys
    are unused", "find out whether it retries"), and for a clause that is not
    "find out" at all.
    """
    rest = _after_find_out(clause)
    if rest is None:
        return False
    while rest and rest[-1] in _FIND_OUT_BARE_TAILS:
        rest = rest[:-1]
    return tuple(rest) in _FIND_OUT_BARE_QUESTIONS


def _after_find_out(clause: str) -> list[str] | None:
    words = command_words(clause)
    if words[:1] != ["find"]:
        return None
    rest = words[1:]
    while rest[:1] and rest[0] in _INQUIRY_SKIPPED:
        rest = rest[1:]
    return rest[1:] if rest[:1] == ["out"] else None


def asks_to_find_out(clause: str) -> bool:
    """`clause` (folded) opens with "find out" ("find out which keys are unused", "can you find me out why").

    `gives_command` never reads it as a command. Whether it asks about what OMH
    did or gives the user's own task depends on the clause before it, which the
    workflow-intent classifier reads.
    """
    return _after_find_out(clause) is not None


def inquiry_why_lead_length(words: list[str]) -> int:
    """How many of `words` open a why-question: "why" alone, or an inquiry verb then "why".

    "show me why OMH picked them", "can you tell me why OMH chose ...". 0 when
    they open with none. Courtesy openers before the inquiry verb are skipped,
    but not the product name, which is the question's subject.
    """
    if words[:1] == ["why"]:
        return 1
    index = 0
    while (step := courtesy_opener_length(words[index:])) and words[index] != "omh":
        index += step
    if words[index : index + 1] and words[index] in _INQUIRY_VERBS:
        index += 1
        while words[index : index + 1] and words[index] in _INQUIRY_SKIPPED:
            index += 1
        if words[index : index + 1] == ["why"]:
            return index + 1
    return 0


def leads_with_code_edit(normalized_query: str) -> bool:
    """The request OPENS with a code edit, in English or Korean.

    English: the first command word is an edit verb ("fix ...", "OMH, add
    ...", "OMH: migrate ..."), or the request hands the edit over at its start
    ("use OMH to fix", "have Hermes add", "help me fix", "using OMH, rename").
    An edit verb later in the sentence ("I asked OMH to fix a test and it
    ...") is not the request's lead.
    Korean: a clause ends on a code-edit request ("테스트 고쳐줘", "코드 수정해
    주세요"), read by `korean_request`.
    """
    words = command_words(normalized_query)
    if words:
        if words[0] in _CODE_EDIT_LEAD_VERBS:
            return True
        if words[0] == "help":
            rest = words[1:]
            rest = rest[1:] if rest[:1] == ["me"] else rest
            rest = rest[1:] if rest[:1] == ["to"] else rest
            if rest[:1] and rest[0] in _CODE_EDIT_LEAD_VERBS:
                return True
        if words[0] in _TOOL_LEADS and words[1:2] and words[1] in _TOOL_NAMES:
            rest = words[2:]
            rest = rest[1:] if rest[:1] == ["to"] else rest
            if rest[:1] and rest[0] in _CODE_EDIT_LEAD_VERBS:
                return True
        if words[0] in _DELEGATING_LEADS:
            # Who the task goes to is at most three words ("OMH", "the OMH
            # agent"); the verb follows it, after "to" or "and" or bare.
            for index in range(1, min(len(words), 5)):
                word = words[index]
                if word in {"to", "and"}:
                    return words[index + 1 : index + 2] != [] and words[index + 1] in _CODE_EDIT_LEAD_VERBS
                if word in _CODE_EDIT_LEAD_VERBS:
                    return True
    return any(
        _korean_code_edit_request(clause) for clause in _KOREAN_CLAUSE_BREAK.split(normalized_query) if clause.strip()
    )


def _korean_code_edit_request(clause: str) -> bool:
    """`clause` ends on a Korean code-edit request; "수정해줘?" counts too.

    `korean_request` reads "해줘?" as an echoed request, which matters to the
    spend and data-share gates. For a code edit it is the ordinary casual way
    to ask (#2485 review), so this reading alone retries without the "?".
    """
    request = korean_request(clause)
    if request is None and clause.rstrip().endswith("?"):
        request = korean_request(clause.rstrip().rstrip("?"))
    return request is not None and request.predicate in _KOREAN_CODE_EDIT_LEAD_PREDICATES

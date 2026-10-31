"""A request's command verb, and the verbs that make it a code edit: one list for every reader.

The direct code-edit guard in `policy` and the workflow-intent classifier in
`intent` both ask whether a request commands an edit. `policy` imports
`intent`, so the words live here, in a module both can import without a
cycle. Stdlib only.
"""

from __future__ import annotations

import re

from ..plugin_bundle.omh.korean_request import korean_request
from ..plugin_bundle.omh.request_lead import after_courtesy

DIRECT_CODING_EDIT_VERBS = frozenset(
    {"add", "adjust", "build", "change", "delete", "edit", "fix", "implement", "make", "patch", "remove", "rename", "set", "tweak", "update"}
)
# The Korean requested verbs of a code edit, as `korean_request` reads them: a
# 하다 verb's noun ("수정" from "수정해줘") or the stem before the ending ("고쳐"
# from "고쳐줘"). The same verbs the direct code-edit guard in `policy` reads,
# with 작성 (write) added: "테스트 작성해줘" asks for code.
KOREAN_CODE_EDIT_PREDICATES = frozenset(
    {"고쳐", "수정", "추가", "작성", "구현", "개선", "삭제", "제거", "변경", "바꿔", "넣어", "만들어"}
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
# work: "check why", "explain what happened", "show me why", "list the
# reasons". The object pronoun ("me", "us") and a leading "the" are skipped.
_INQUIRY_AFTER_VERB = (("why",), ("what", "happened"), ("reason",), ("reasons",))
# "find out" asks about what happened unless it opens an object question: "find
# out which keys are unused", "where it is imported", "whether it retries", "if
# it uses X", "how many endpoints", "what calls it". A cause stays a question:
# "find out why / how that happened / the reasons / the cause / what went
# wrong / what caused it / what's wrong / where that came from" (#2454 review).
_OUT_OBJECT_QUESTIONS = frozenset({"which", "whether", "if", "where"})
_OUT_HOW_OBJECTS = frozenset({"many", "much"})
# After "what", these ask for a cause or point back at what OMH did ("what the
# router did"), so the clause stays a question. "what's" folds to "what s".
_OUT_WHAT_ASKS = frozenset({
    "happened", "happens", "went", "goes", "caused", "causes", "triggered", "triggers", "made", "makes",
    "led", "leads", "broke", "breaks", "prompted", "is", "s", "was", "were", "are", "wrong", "behind",
    "the", "this", "that", "it", "its", "they", "omh", "hermes", "you", "i", "we",
})
_ORIGIN_VERBS = frozenset({"came", "comes", "come"})
_INQUIRY_VERBS = frozenset({"check", "find", "explain", "show", "list", "tell"})
_INQUIRY_SKIPPED = frozenset({"me", "us", "the"})

# The word before a verb that still makes it the command: "use X to fix",
# "help me fix", or a second command joined by "and"/"then".
_COMMAND_INTRODUCERS = frozenset({"to", "me", "and", "then"})
# A request that hands the task to someone opens with one of these, then names
# who, then the verb: "use OMH to fix", "have Hermes add", "ask OMH to update".
_DELEGATING_LEADS = frozenset({"use", "have", "let", "ask", "get", "tell"})
_WORD = re.compile(r"[a-z0-9#][a-z0-9#+.-]*")
# Where a Korean message's clauses part: a comma, or an aside in parentheses
# ("코드 고쳐줘 (OMH 세션)", "테스트 작성해줘, OMH 환경이야").
_KOREAN_CLAUSE_BREAK = re.compile(r"[,，(（)）]")


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
    "explain what happened", "list the reasons", and "find out" before
    anything but an object question (`_out_names_an_object`).
    """
    words = command_words(clause)
    if words and tuple(words[:2]) in _REQUEST_COMMAND_PHRASES:
        return True
    if words and words[0] in _INQUIRY_VERBS:
        rest = words[1:]
        while rest[:1] and rest[0] in _INQUIRY_SKIPPED:
            rest = rest[1:]
        if rest[:1] == ["out"]:
            if not _out_names_an_object(rest[1:]):
                return False
        elif any(tuple(rest[: len(inquiry)]) == inquiry for inquiry in _INQUIRY_AFTER_VERB):
            return False
    return bool(words) and words[0] in REQUEST_COMMAND_VERBS or leads_with_code_edit(clause)


def _out_names_an_object(words: list[str]) -> bool:
    """The words after "find out" open an object question, the user's own task, rather than a cause."""
    if not words:
        return False
    head, rest = words[0], words[1:]
    if head == "where":
        # "where that decision came from" asks for a cause; "where it is imported" for a place.
        return not any(word in _ORIGIN_VERBS and rest[index + 1 : index + 2] == ["from"]
                       for index, word in enumerate(rest))
    if head in _OUT_OBJECT_QUESTIONS:
        return True
    if head == "how":
        return rest[:1] != [] and rest[0] in _OUT_HOW_OBJECTS
    if head == "what":
        return rest[:1] != [] and rest[0] not in _OUT_WHAT_ASKS
    return False


def leads_with_code_edit(normalized_query: str) -> bool:
    """The request OPENS with a code edit, in English or Korean.

    English: the first command word is an edit verb ("fix ...", "OMH, add
    ..."), or the request hands the edit over at its start ("use OMH to fix",
    "have Hermes add", "help me fix"). An edit verb later in the sentence ("I
    asked OMH to fix a test and it ...") is not the request's lead.
    Korean: a clause ends on a code-edit request ("테스트 고쳐줘", "코드 수정해
    주세요"), read by `korean_request`.
    """
    words = command_words(normalized_query)
    if words:
        if words[0] in DIRECT_CODING_EDIT_VERBS:
            return True
        if words[0] == "help":
            rest = words[1:]
            rest = rest[1:] if rest[:1] == ["me"] else rest
            rest = rest[1:] if rest[:1] == ["to"] else rest
            if rest[:1] and rest[0] in DIRECT_CODING_EDIT_VERBS:
                return True
        if words[0] in _DELEGATING_LEADS:
            # Who the task goes to is at most three words ("OMH", "the OMH
            # agent"); the verb follows it, after "to" or "and" or bare.
            for index in range(1, min(len(words), 5)):
                word = words[index]
                if word in {"to", "and"}:
                    return words[index + 1 : index + 2] != [] and words[index + 1] in DIRECT_CODING_EDIT_VERBS
                if word in DIRECT_CODING_EDIT_VERBS:
                    return True
    return any(
        (request := korean_request(clause)) is not None and request.predicate in KOREAN_CODE_EDIT_PREDICATES
        for clause in _KOREAN_CLAUSE_BREAK.split(normalized_query)
        if clause.strip()
    )

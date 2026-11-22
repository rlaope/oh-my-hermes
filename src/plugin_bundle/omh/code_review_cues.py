"""Whether a request is, sentence by sentence, a request to review a code change.

One implementation for the router's `CODE_REVIEW_REQUEST_GUARD`
(`routing.policy.code_review_request_guard_applies`) and the plugin bundle's
per-turn route hint (`awareness`). Hermes loads the bundle with its own
interpreter, which often cannot import the `omh` package, so the shapes live
here and the router imports them; the two paths read one function and cannot
reach different verdicts on the same text. Stdlib only.

A request to review a code change, like the frontend guard, is read as whole
sentences, not as words anywhere: "review" alone also takes an essay, a
contract or a budget, and "PR", "change" and "commit" are objects of writing,
merging and pushing. The guard fires when one sentence of the request (split
at full stops, question marks and line breaks) is entirely one of the shapes
below. A sentence with any other word ("review PR 12 and merge it", "review my
change for the export feature", "who should review my PR?") keeps its route.
Other sentences may follow, so a review task that goes on to describe where
the diff lives and what to answer still counts. The price is reach: another
word order or a qualified object ("the auth PR") stays at its base verdict.

Callers pass text folded by `text_fold.normalized_phrase` (decomposed Hangul),
the fold the slots below are built in.
"""

from __future__ import annotations

import re

from .text_fold import normalized_phrase

_CODE_REVIEW_EN_LEADS = ("please", "can you", "could you", "would you", "pls")
_CODE_REVIEW_EN_VERBS = ("review", "code review", "do a code review of", "look over", "go over")
_CODE_REVIEW_EN_CHECK_VERBS = ("check", "scan", "inspect", "look at", "audit")
_CODE_REVIEW_EN_DETERMINERS = ("a", "the", "this", "my", "our", "these", "that")
_CODE_REVIEW_EN_OBJECTS = (
    "code change",
    "code changes",
    "change",
    "changes",
    "diff",
    "patch",
    "pull request",
    "pr",
    "commit",
    "commits",
)
# A bare "change" is also a policy, contract or schedule change: it counts only
# when the sentence asks about bugs in it, or as "code change".
_CODE_REVIEW_EN_BARE_OBJECTS = ("change", "changes")
_CODE_REVIEW_EN_PURPOSES = ("bugs", "a bug", "any bugs", "regressions", "bugs and regressions", "correctness")
_CODE_REVIEW_EN_INTRODUCE = ("introduce", "introduces", "add", "adds", "cause", "causes")
_CODE_REVIEW_EN_BUG_OBJECTS = ("a bug", "any bugs", "bugs", "a regression", "any regressions", "regressions")
_CODE_REVIEW_EN_WHETHER = ("decide whether", "check whether", "check if", "tell me whether", "tell me if", "find out whether", "see if")
_CODE_REVIEW_KO_DETERMINERS = ("이", "이번", "내", "제", "우리")
_CODE_REVIEW_KO_OBJECTS = (
    "diff",
    "pr",
    "패치",
    "변경",
    "변경사항",
    "변경 사항",
    "커밋",
    "코드",
    "코드 변경",
    "풀 리퀘스트",
    "풀리퀘스트",
)
_CODE_REVIEW_KO_BARE_OBJECTS = ("변경", "변경사항", "변경 사항")
_CODE_REVIEW_KO_VERBS = ("리뷰", "코드 리뷰", "검토", "코드 검토")
_CODE_REVIEW_KO_COMPOUND_VERBS = ("코드 리뷰", "코드리뷰", "코드 검토")
_CODE_REVIEW_KO_ENDINGS = ("해줘", "해 줘", "해주세요", "해 주세요", "부탁해")
_CODE_REVIEW_KO_LOOK_VERBS = ("봐줘", "봐 줘", "봐주세요", "확인해줘", "확인해 줘", "확인해주세요", "찾아줘", "찾아 줘", "체크해줘", "검토해줘")


def _slot(*phrases: str) -> str:
    # Cues and particles are folded like the query, so they match its decomposed text.
    return "(?:" + "|".join(re.escape(normalized_phrase(phrase)) for phrase in phrases) + ")"


def _code_review_shapes() -> tuple[re.Pattern[str], ...]:
    slot = _slot
    lead = f"(?:{slot(*_CODE_REVIEW_EN_LEADS)} )?"
    det = slot(*_CODE_REVIEW_EN_DETERMINERS)
    code_objects = tuple(o for o in _CODE_REVIEW_EN_OBJECTS if o not in _CODE_REVIEW_EN_BARE_OBJECTS)
    obj = f"{slot(*code_objects)}(?: #?\\d+)?"
    any_obj = f"{slot(*_CODE_REVIEW_EN_OBJECTS)}(?: #?\\d+)?"
    purpose = f"(?: for {slot(*_CODE_REVIEW_EN_PURPOSES)})?"
    polite = f"(?: {slot('please')})?"
    numbered = f"(?:{slot('pr', 'pull request')} #?\\d+)"
    ko_det = f"(?:{slot(*_CODE_REVIEW_KO_DETERMINERS)} )?"
    ko_code_objects = tuple(o for o in _CODE_REVIEW_KO_OBJECTS if o not in _CODE_REVIEW_KO_BARE_OBJECTS)
    ko_obj = f"{ko_det}{slot(*ko_code_objects)}"
    ko_any_obj = f"{ko_det}{slot(*_CODE_REVIEW_KO_OBJECTS)}"
    statement = (
        f"{slot('the', 'this', 'my')} {slot(*_CODE_REVIEW_EN_OBJECTS)} "
        f"{slot(*_CODE_REVIEW_EN_INTRODUCE)} {slot(*_CODE_REVIEW_EN_BUG_OBJECTS)}"
    )
    shapes = (
        # review this diff / can you review my PR / review PR 1234 for bugs
        f"{lead}{slot(*_CODE_REVIEW_EN_VERBS)} (?:{det} {obj}|{numbered}){purpose}{polite}",
        # review this change for bugs: a bare change needs the bug purpose.
        f"{lead}{slot(*_CODE_REVIEW_EN_VERBS)} {det} {any_obj} for {slot(*_CODE_REVIEW_EN_PURPOSES)}{polite}",
        # check this patch for regressions: a check verb needs the bug purpose.
        f"{lead}{slot(*_CODE_REVIEW_EN_CHECK_VERBS)} (?:{det} {any_obj}|{numbered}) for {slot(*_CODE_REVIEW_EN_PURPOSES)}{polite}",
        # find bugs in this diff
        f"{lead}{slot('find', 'look for')} {slot(*_CODE_REVIEW_EN_BUG_OBJECTS)} in (?:{det} {any_obj}|{numbered}){polite}",
        # does this change introduce a bug
        f"{slot('does', 'did', 'will', 'would')} {slot('the', 'this', 'my')} {slot(*_CODE_REVIEW_EN_OBJECTS)} "
        f"{slot('introduce', 'add', 'cause')} {slot(*_CODE_REVIEW_EN_BUG_OBJECTS)}",
        # decide whether the change introduces a bug
        f"{slot(*_CODE_REVIEW_EN_WHETHER)} {statement}",
        # 이 diff 리뷰해줘: the object is required, a bare "검토해줘" is not this lane.
        f"{ko_obj}{slot('를', '을')}?(?: {slot('좀')})? {slot(*_CODE_REVIEW_KO_VERBS)} ?{slot(*_CODE_REVIEW_KO_ENDINGS)}",
        # 코드 리뷰 해줘: the verb carries its own object.
        f"{slot(*_CODE_REVIEW_KO_COMPOUND_VERBS)} ?{slot(*_CODE_REVIEW_KO_ENDINGS)}",
        # 이 PR 버그 있는지 봐줘
        f"{ko_any_obj}{slot('에', '에서', '에는')}? {slot('버그')}{slot('가')}? {slot('있는지', '없는지')}(?: {slot('좀')})? {slot(*_CODE_REVIEW_KO_LOOK_VERBS)}",
        # 이 diff에서 버그 찾아줘
        f"{ko_any_obj}{slot('에서')}? {slot('버그')}{slot('를')}? {slot('찾아줘', '찾아 줘', '찾아주세요')}",
    )
    return tuple(re.compile(pattern) for pattern in shapes)


_CODE_REVIEW_SHAPES = _code_review_shapes()
_CODE_REVIEW_SENTENCE_SPLIT = re.compile(r"(?:[.!]\s+|[.!]$|\?|\n)")


def request_sentences(normalized_query: str) -> tuple[str, ...]:
    """The request's sentences as the guard reads them: split at full stops, question marks and line breaks."""
    sentences = (" ".join(raw.replace(",", " ").split()).rstrip(" .!~") for raw in _CODE_REVIEW_SENTENCE_SPLIT.split(normalized_query))
    return tuple(sentence for sentence in sentences if sentence)


def code_review_request_sentence(normalized_query: str) -> str:
    """The first sentence that is wholly a closed review or find-bugs shape, or "" when none is."""
    for sentence in request_sentences(normalized_query):
        if any(shape.fullmatch(sentence) for shape in _CODE_REVIEW_SHAPES):
            return sentence
    return ""


def code_review_request_guard_applies(normalized_query: str) -> bool:
    """One sentence of the request is a closed review or find-bugs shape over a code-change object."""
    return bool(code_review_request_sentence(normalized_query))

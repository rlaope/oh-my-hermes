"""Whether a message names a coding CLI as the one to do the work, not as what the work is about.

Stdlib and bundle imports only: Hermes loads this package without core ``omh``.
`omh.routing.executor_cues` re-exports `owner_named_as_doer`, so the router,
the chat wrapper and dag-ulw's in-message owner reader share one cue list.
"""

from __future__ import annotations

from functools import lru_cache
import re
import unicodedata

from .text_fold import normalized_phrase


# An owner named in a message counts as a choice of who writes the code only when the message names it as the
# doer: "with codex", "use codex", "have claude code fix ...", "codex로", "클로드 코드한테". A bare product word is
# what the work is about as often as who does it ("fix the codex adapter tests", "update the claude code docs"),
# so it never picks the owner. The cue lists are closed: a new form joins on positive evidence, with a negative
# case beside it. Text and phrase are compared after the same fold (`normalized_phrase`).
_DOER_LEAD_WORDS: tuple[str, ...] = (
    "with", "use", "using", "via", "through", "have", "let", "ask", "tell",
    "assign it to", "assign to", "hand it to", "hand it off to", "hand off to", "delegate it to", "delegate to",
    "give it to", "send it to",
    # Where the work runs, said of the work itself ("open this in codex", the cards' "Open in Codex").
    "open in", "open this in", "open it in", "run it in", "run this in", "do it in", "do this in",
)
_DOER_TRAILING_WORDS: tuple[str, ...] = ("should", "will", "can", "must")
# Korean and Japanese particles or verbs right after the name ("codex로", "codex 써서", "codexて" once
# `normalized_phrase` strips the dakuten of "で").
_DOER_SUFFIXES: tuple[str, ...] = (
    "으로", "로", "한테", "에게", "시켜", " 시켜", " 써서", "를 써", "을 써", " 사용해", " 이용해",
    "て", "に任せ", "に頼",
    # Opening a session in the CLI to work in it ("codex 세션 켜서 작업 시작", "claude code 작업 세션 열어줘").
    " 세션 켜", " 세션 열", " 세션 시작", " 작업 세션 열", " 작업 세션 켜", " 작업 세션 시작",
)
_COORDINATED_LEAD = re.compile(
    r"(?:^|\s)(?:" + "|".join(re.escape(lead) for lead in _DOER_LEAD_WORDS) + r")\s+\S+(?:\s\S+)?,?\s+(?:or|and)\s$"
)
_NEGATED_LEADS: tuple[str, ...] = ("don't ", "dont ", "do not ", "never ", "not ", "no ")
_NEGATED_TAILS: tuple[str, ...] = ("말고", " 말고", "빼고", " 빼고", "없이", " 없이", " 쓰지 마", " 하지 마")
# Phrases that already say who does the work ("have pi implement", "pi한테", "hermes coding").
_SELF_CUED_PATTERN = re.compile(r"^(?:have|ask|tell|let|delegate to|use|with)\s|\bcoding$")


def _bounded_at(text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start > 0 else " "
    after = text[end] if end < len(text) else " "
    return not (before.isascii() and before.isalnum() or before in "-_") and not (
        after.isascii() and (after.isalnum() or after in "-_.")
        and not (after == "." and (end + 1 >= len(text) or text[end + 1] == " "))
    )


@lru_cache(maxsize=1)
def _folded_cues() -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """The cue lists through `normalized_phrase`, which decomposes Hangul: text and cues must share one fold."""
    def fold(values: tuple[str, ...]) -> tuple[str, ...]:
        # A leading space marks a separate word; it is kept outside the fold.
        return tuple((" " if value.startswith(" ") else "") + normalized_phrase(value.strip()) for value in values)

    return fold(_DOER_SUFFIXES), fold(_NEGATED_TAILS), tuple(normalized_phrase(value) for value in ("한테", "에게", "코딩"))


def owner_named_as_doer(text: str, phrase: str) -> bool:
    """Whether ``text`` names ``phrase`` as the one to do the work, not as what the work is about.

    Both arguments are folded the same way (`normalized_phrase`). A phrase
    that already carries its cue counts wherever it stands at a word boundary.
    """
    if not phrase:
        return False
    # Callers fold with `normalized_phrase`; one that passes composed Hangul still meets the decomposed cues.
    text, phrase = unicodedata.normalize("NFKD", text), unicodedata.normalize("NFKD", phrase)
    suffixes, negated_tails, self_cued_endings = _folded_cues()
    self_cued = bool(_SELF_CUED_PATTERN.search(phrase)) or phrase.endswith(self_cued_endings)
    start = text.find(phrase)
    while start != -1:
        end = start + len(phrase)
        if _bounded_at(text, start, end):
            if self_cued:
                return True
            head, tail = text[:start], text[end:]
            led = any(
                head.endswith(lead + " ") and not any(head[: -len(lead) - 1].endswith(neg) for neg in _NEGATED_LEADS)
                for lead in _DOER_LEAD_WORDS
            )
            # A second owner in the same cue: "use codex or claude code", "with codex and claude code".
            led = led or bool(_COORDINATED_LEAD.search(head))
            trailed = any(tail.startswith(" " + word + " ") for word in _DOER_TRAILING_WORDS) or (
                tail.startswith(" session") and head.endswith(("open a ", "start a ", "open an ", "start an "))
            )
            suffixed = any(tail.startswith(suffix) for suffix in suffixes) and not any(
                tail[len(suffix):].startswith(neg) or tail.startswith(neg)
                for suffix in suffixes if tail.startswith(suffix) for neg in negated_tails
            )
            if led or trailed or suffixed or _addressed_as_doer(head, tail):
                return True
        start = text.find(phrase, start + 1)
    return False


# Forms that address the CLI as the one to act, each pinned beside a negative in `OwnerCueTests`.
_REQUEST_VERBS: tuple[str, ...] = (
    "fix", "implement", "build", "write", "add", "update", "refactor", "handle", "make", "do", "take", "change",
)
# A Korean request ending somewhere after "가"/"이" makes the name the subject of a request ("codex가 해줘"),
# never of a question about it ("codex가 왜 죽어").
_KO_REQUEST_ENDINGS: tuple[str, ...] = (
    "해줘", "해 줘", "해주세요", "해 주세요", "고쳐", "구현해", "만들어", "작성해", "수정해", "처리해", "맡아", "진행해", "해봐",
)


@lru_cache(maxsize=1)
def _folded_request_endings() -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (tuple(normalized_phrase(value) for value in _KO_REQUEST_ENDINGS),
            tuple(normalized_phrase(value) for value in ("가 ", "이 ")))


def _addressed_as_doer(head: str, tail: str) -> bool:
    """"codex가 고쳐줘", "codex, fix ...", "get codex to ...", "codex please ...", "can codex fix ...", "codexに…させ"."""
    endings, particles = _folded_request_endings()
    question = tail.rstrip().endswith("?")
    if tail.startswith(particles) and not question:
        clause = tail[2:].split(".")[0]
        if any(ending in clause for ending in endings):
            return True
    if not head.strip() and tail.startswith(",") and not question:
        return True
    if head.endswith("get ") and tail.startswith(" to "):
        return True
    if tail.startswith(" please") and not question:
        return True
    if head.endswith(("can ", "could ")) and any(tail.startswith(" " + verb + " ") for verb in _REQUEST_VERBS):
        return True
    if tail.startswith("に") and "させ" in tail.split("。")[0]:
        return True
    return False

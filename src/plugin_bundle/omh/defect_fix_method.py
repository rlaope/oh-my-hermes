"""The debugging and verification method, on a turn that asks to fix a code defect.

Hermes tells a model to open a skill only for domain knowledge it lacks and
never for "general process skills (testing, debugging, review methodology)"
(its skills-index preamble), so `omh-app-debugging` and
`omh-verification-gate` stay closed on exactly the turns they were written
for. Measured on the paired-run harder set (2026-11-16, both arms with
`file,skills,terminal`): the variant opened no skill in 45 cells and failed the
same tasks the same way as Hermes alone, with a patch at the place the symptom
showed (a crash coerced where it surfaced, a wrong figure reformatted) while the
bad value came from a loader or parser upstream, and a run of only the named
test.

So this module carries the method itself: a short block, condensed from those
two skills, that `pre_llm_call` adds to a turn whose request asks to fix a code
defect (`asks_to_fix_code`). It is a few hundred characters, rides once per
session (`claim_method_block`), and no other turn gets it: a question, a review,
a feature request, or a fix of something that is not code reads as before.

The predicate reads words only: a change verb (fix, debug, repair, "make ...
pass", 고쳐, 수정해, ...) together with a code object (a source file path, a
dotted name or a call, a test or test runner, a traceback or an `...Error`,
function, class, module, code, bug; 코드, 함수, 테스트, 에러, ...). Stdlib only.

The block is prepared instruction. Injecting it is not evidence that the model
followed it, and nothing here observes a reproduction, a run, or a fix.
"""

from __future__ import annotations

from collections import OrderedDict
import re
import threading
from typing import Final

METHOD_BLOCK: Final[str] = (
    "[OMH Debugging Method] This turn asks to fix a code defect (method of omh-app-debugging and "
    "omh-verification-gate, condensed; no need to load them):\n"
    "1. Reproduce first: run the failing test or the reported call and read the actual wrong value or "
    "traceback.\n"
    "2. Trace the bad value back to where it is first produced (the parser, loader or constructor), "
    "not where it surfaced, and fix it there; reuse a helper the code base already has for that job.\n"
    "3. Before calling it fixed, feed other valid variants of the same input through the public entry "
    "point (other formats the input may arrive in, edge and boundary values) with a one-off check you "
    "do not commit.\n"
    "4. Run the whole test suite, not only the named test, and compare against the failures that were "
    "there before your edit.\n"
    "A patch that only makes the named check pass where the symptom showed is a symptom mask, not a fix."
)

# A change verb: the request asks for the defect to go away, not about it.
_CHANGE_RE: Final = re.compile(
    r"\b(?:fix(?:es|ed|ing)?|debug(?:s|ged|ging)?|repair(?:s|ed|ing)?|resolve|troubleshoot)\b"
    r"|\bmake\b(?:[^.!?\n]|\.(?=\S)){0,80}?\b(?:pass|passes|green|work)\b",
    re.IGNORECASE,
)
_HANGUL_CHANGE: Final = ("고쳐", "고치", "수정해", "수정하", "디버그", "디버깅", "해결해")

# A code object: what is broken is software.
_CODE_RE: Final = re.compile(
    r"\b\w+\.(?:py|pyi|js|jsx|ts|tsx|go|rs|java|kt|rb|php|cs|c|cc|cpp|h|hpp|swift|scala|sh)\b"
    r"|\b[a-z_]\w*(?:\.[a-z_]\w*){2,}\b"
    r"|\b[a-z_]\w*\.\w*_\w*\b|\b\w*_\w*\.[a-z_]\w*\b"
    r"|\b[A-Za-z_]\w*\("
    r"|\b(?:tests?|unittest|pytest|jest|vitest|traceback|stack ?trace|exceptions?|segfault|regression)\b"
    r"|\b[A-Z]\w*(?:Error|Exception)\b"
    r"|\b(?:functions?|methods?|class|classes|modules?|code|codebase|bugs?|script|endpoint|compiler)\b",
)
_HANGUL_CODE: Final = ("코드", "함수", "테스트", "에러", "오류", "예외", "버그", "모듈", "클래스", "메서드", "스크립트")


def asks_to_fix_code(message: str) -> bool:
    """True when the request asks to fix a defect in code."""
    if not isinstance(message, str) or not message.strip():
        return False
    text = message[:4000]
    change = _CHANGE_RE.search(text) is not None or any(cue in text for cue in _HANGUL_CHANGE)
    if not change:
        return False
    return _CODE_RE.search(text) is not None or any(noun in text for noun in _HANGUL_CODE)


# Sessions already shown the block, process-local like the candidate line's
# memory (`skill_shortlist.claim_candidate_line`): a Hermes restart forgets it
# and the next fix request shows the block again.
_MAX_REMEMBERED_SESSIONS: Final = 256
_shown_lock = threading.Lock()
_shown: "OrderedDict[str, None]" = OrderedDict()


def claim_method_block(session_id: str) -> bool:
    """True the first time a session asks for it; a session with no id always gets it."""
    if not session_id:
        return True
    with _shown_lock:
        if session_id in _shown:
            return False
        _shown[session_id] = None
        while len(_shown) > _MAX_REMEMBERED_SESSIONS:
            _shown.popitem(last=False)
    return True


def reset_method_block_state() -> None:
    with _shown_lock:
        _shown.clear()


__all__ = ["METHOD_BLOCK", "asks_to_fix_code", "claim_method_block", "reset_method_block_state"]

"""Name `dag-ulw` as a way to run a plan, on the two turns where a plan's follow-on is chosen.

The planning skills name `dag-ulw` among the follow-ons of an accepted plan,
but neither turn on which the person actually chooses one carried them:

- Hermes' own `/plan` turn. It is host-written, so nothing of OMH's routes on
  it, and its template closes by offering to carry the plan out. That offer is
  the choice the person later answers ("구현하기"), and it named no engine.
- The turn that answers a plan just made. The planning skill was loaded a turn
  earlier, or never (`/plan`), and the router reads "구현해줘" as plain work.

So each gets one line here, and both lines only offer. `plan_turn_line` rides
`/plan`'s turn, read from its frame alone (`host_plan_turn`).
`acceptance_line` is conditional: it asks the model to read the person's
message itself, may name `dag-ulw` beside carrying the plan out directly, and
tells the model to ignore it when the message declined, held, edited, asked or
changed topic. A misfire therefore costs one ignored note, never a start. It
rides at most once per fresh plan, decided in two steps:

1. A plan was just made, read from structure, never from this turn's words.
   The turn before this one was `/plan`'s, invoked a planning skill by slash,
   loaded one with `skill_view`, or wrote a plan file (`write_file` or `patch`
   on a path under `.hermes/plans/` or `.omh/plans/`). A read or a mention of a
   plan file does not count, so carrying a plan out never reopens it. Or this
   is the first turn that sees a planning workflow state active for the
   session (`_first_sight_of_planning_state`, held in this process).
2. A cheap pre-filter on the person's words (`accepts_plan`): no question
   mark, and every word from a closed set of go words, acknowledgements and
   fillers, with at least one go word or acknowledgement. A word outside the
   set ("아직", "only", "codex로", "테스트") leaves the turn as it was, and so
   does a long message, which always holds one.

Without step 1 nothing is read, so a turn with no fresh plan renders exactly
what it rendered before.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping, Sequence
import json
import re
import threading
import unicodedata
from typing import Final

from .hermes_session_commands import host_plan_turn, person_request_text

DAG_ULW: Final = "dag-ulw"
# The workflow states a plan is drafted under (`ALLOWED_TRANSITIONS` sources that name dag-ulw).
PLANNING_WORKFLOWS: Final = frozenset({"plan", "ralplan", "refactor-plan"})
# Their catalog names and the labels Hermes lists and `skill_view` loads them by.
PLANNING_SKILL_NAMES: Final = frozenset(
    {"plan", "omh-plan", "ralplan", "ulw-plan", "refactor-plan", "omh-refactor-plan"}
)
PLAN_FILE_DIRS: Final = (".hermes/plans/", ".omh/plans/")
# Hermes' file tools that write (`tools/file_tools.py`); `read_file` and `search_files` only read.
_WRITE_TOOLS: Final = frozenset({"write_file", "patch"})
_V4A_FILE_HEADERS: Final = ("*** Add File:", "*** Update File:")

# The fit condition is the planning skills' own (#2558): tasks that form a
# graph with disjoint write scopes, ending in a verification task.
PLAN_TURN_LINE: Final = (
    "[OMH Plan Follow-on] When you offer to carry this plan out, and its tasks form a graph (some can run "
    "apart, with disjoint write scopes) ending in a verification task, also name `dag-ulw` as one option "
    "beside carrying it out directly, with the fit reason in one line. Start neither this turn."
)
ACCEPTANCE_LINE: Final = (
    "[OMH Plan Follow-on] A plan was just made. If the person's message accepts it without choosing how to "
    "run it, and its tasks form a graph (some can run apart, with disjoint write scopes) ending in a "
    "verification task, you may name `dag-ulw` as one option beside carrying it out directly, with the fit "
    "reason in one line, unless your last offer already named it. Start nothing they did not pick. If they "
    "declined, held, edited, asked something or changed topic, ignore this note."
)

_LATIN_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_HANGUL = re.compile(r"[\u1100-\u11ff\u3131-\u318e\uac00-\ud7a3]")
_EDGE_PUNCTUATION = ".,!~…:;—-–\"'()[]"

# English: every token from this set, and at least one cue among them.
_EN_CUES: Final = frozenset(
    {
        "implement", "implementing", "execute", "proceed", "start", "begin", "build", "ship", "approve",
        "approved", "accept", "accepted", "lgtm", "go", "yes", "yep", "yeah", "ok", "okay", "sure", "alright",
        "good", "great", "perfect",
    }
)
_EN_FILLERS: Final = frozenset(
    {
        "please", "pls", "plz", "the", "this", "that", "plan", "now", "then", "let's", "lets", "let", "us",
        "we", "you", "can", "and", "so", "as", "written", "is", "it", "do", "run", "carry", "out", "ahead",
        "for", "with", "in", "looks", "sounds", "kick", "off", "all", "right",
    }
)
_EN_PHRASE_CUES: Final = (("do", "it"), ("do", "this"), ("run", "it"), ("carry", "it", "out"))


def _fold_ko(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _ko_set(values: Sequence[str]) -> frozenset[str]:
    return frozenset(_fold_ko(value) for value in values)


# Korean: every word from these sets, and at least one cue word among them.
_KO_ACKS: Final = _ko_set(
    (
        "좋아", "좋아요", "좋습니다", "좋다", "좋네", "좋네요", "오케이", "오키", "ㅇㅋ", "ㅇㅇ", "응", "넵", "네", "넹",
        "예", "그래", "그래요", "콜", "굿", "승인", "승인합니다", "고", "고고", "ㄱ", "ㄱㄱ", "가자", "가즈아",
    )
)
_KO_GO_STEMS: Final = ("구현", "진행", "실행", "시작", "착수", "개발", "적용", "작업")
_KO_GO_ENDINGS: Final = (
    "", "해", "해줘", "해줘요", "해주세요", "해요", "해라", "하자", "하기", "합시다", "하세요", "하시죠", "해봐",
    "해보자", "하죠", "고", "고고",
)
_KO_GO_WORDS: Final = _ko_set(
    tuple(stem + ending for stem in _KO_GO_STEMS for ending in _KO_GO_ENDINGS)
    + ("만들어", "만들어줘", "만들어주세요", "만들어요", "만들자", "들어가자", "해", "해줘", "해주세요", "하자",
       "합시다", "그렇게")
)
_KO_FILLERS: Final = _ko_set(
    ("이", "그", "이대로", "그대로", "플랜대로", "계획대로", "플랜", "계획", "플랜으로", "계획으로", "플랜을", "계획을",
     "바로", "그럼", "이제", "자", "주세요", "줘")
)

_lock = threading.Lock()
# Per session, the planning workflow already seen active in this process.
_seen_planning_state: OrderedDict[str, str] = OrderedDict()
_MAX_TRACKED_SESSIONS: Final = 256


def _word_reading(word: str) -> tuple[bool, bool]:
    """(the word is in the closed set, the word is a go word or acknowledgement)."""
    if _HANGUL.search(word):
        if word in _KO_ACKS or word in _KO_GO_WORDS:
            return True, True
        return word in _KO_FILLERS, False
    tokens = _LATIN_TOKEN.findall(word)
    if not tokens:
        return False, False
    allowed = all(token in _EN_CUES or token in _EN_FILLERS for token in tokens)
    return allowed, allowed and any(token in _EN_CUES for token in tokens)


def accepts_plan(text: str) -> bool:
    """The pre-filter: a message made only of go words, acknowledgements and fillers, and no question.

    A path (a word holding `/`) is skipped, so "execute the plan in
    .hermes/plans/x.md" still reads as go. The model, not this, decides
    whether the message accepted the plan.
    """
    folded = _fold_ko(text).strip()
    if not folded or "?" in folded:
        return False
    words = [word.strip(_EDGE_PUNCTUATION) for word in folded.split() if "/" not in word]
    words = [word for word in words if word]
    if not words:
        return False
    readings = [_word_reading(word) for word in words]
    if not all(allowed for allowed, _ in readings):
        return False
    tokens = [token for word in words for token in _LATIN_TOKEN.findall(word)]
    phrase = any(
        tuple(tokens[at:at + len(cue)]) == cue for cue in _EN_PHRASE_CUES for at in range(len(tokens) - len(cue) + 1)
    )
    return phrase or any(cue for _, cue in readings)


def _previous_turn(history: object) -> list[Mapping[str, object]]:
    """The rows of the turn before this one: its user row first, then what followed it.

    The newest user row is this turn's own (`build_turn_context` appends it
    before the hook runs), so the turn before runs from the user row ahead of
    it up to it. No such row, no previous turn.
    """
    if not isinstance(history, (list, tuple)):
        return []
    rows = [row for row in history if isinstance(row, Mapping)]
    users = [index for index, row in enumerate(rows) if row.get("role") == "user"]
    if len(users) < 2:
        return []
    return rows[users[-2]:users[-1]]


def _arguments(function: Mapping[str, object]) -> Mapping[str, object]:
    arguments = function.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return {}
    return arguments if isinstance(arguments, Mapping) else {}


def _in_plan_dir(path: object) -> bool:
    return isinstance(path, str) and any(directory in path for directory in PLAN_FILE_DIRS)


def _makes_plan(call: object) -> bool:
    """A tool call that loads a planning skill or writes a plan file."""
    function = call.get("function") if isinstance(call, Mapping) else None
    if not isinstance(function, Mapping):
        return False
    name = function.get("name")
    arguments = _arguments(function)
    if name == "skill_view":
        skill = arguments.get("name")
        return isinstance(skill, str) and skill.strip().rsplit("/", 1)[-1] in PLANNING_SKILL_NAMES
    if name not in _WRITE_TOOLS:
        return False
    if _in_plan_dir(arguments.get("path")):
        return True
    patch = arguments.get("patch")
    return isinstance(patch, str) and any(
        line.startswith(_V4A_FILE_HEADERS) and _in_plan_dir(line) for line in patch.splitlines()
    )


def plan_just_made(history: object) -> bool:
    """Whether the turn before this one made a plan, read from its rows' structure."""
    turn = _previous_turn(history)
    if not turn:
        return False
    opening = turn[0].get("content")
    if host_plan_turn(opening):
        return True
    if isinstance(opening, str):
        invoked = person_request_text(opening).split(maxsplit=1)
        if invoked and invoked[0].startswith("/") and invoked[0][1:] in PLANNING_SKILL_NAMES:
            return True
    return any(
        _makes_plan(call)
        for row in turn[1:]
        for call in (row.get("tool_calls") or ())
    )


def _first_sight_of_planning_state(session_id: str, active_workflow: Mapping[str, object] | None) -> bool:
    """True on the first turn this process sees a planning workflow active for the session.

    The mark is dropped on a turn that sees none, so a later activation counts
    again. A restarted process sees an active state for the first time once
    more; the line it may add then is the conditional note above.
    """
    key = session_id.strip()
    workflow = active_workflow.get("workflow") if active_workflow and active_workflow.get("state") == "active" else None
    with _lock:
        if workflow not in PLANNING_WORKFLOWS or not key:
            if key:
                _ = _seen_planning_state.pop(key, None)
            return False
        if _seen_planning_state.get(key) == workflow:
            return False
        _seen_planning_state[key] = str(workflow)
        _seen_planning_state.move_to_end(key)
        while len(_seen_planning_state) > _MAX_TRACKED_SESSIONS:
            _ = _seen_planning_state.popitem(last=False)
        return True


def reset_plan_follow_on_state() -> None:
    with _lock:
        _seen_planning_state.clear()


def plan_turn_line(user_message: object) -> str:
    """`PLAN_TURN_LINE` on `/plan`'s own turn, else ""."""
    return PLAN_TURN_LINE if host_plan_turn(user_message) else ""


def acceptance_line(
    request: str, history: object, active_workflow: Mapping[str, object] | None, session_id: str = ""
) -> str:
    """`ACCEPTANCE_LINE` on a person's turn right after a plan was made, when the pre-filter passes; else "".

    `request` is the person's own words (empty on a turn Hermes wrote), and
    `active_workflow` this session's `active_workflow_context` projection.
    The state is observed on every turn, so its first sight is spent on the
    turn right after the activation whatever that turn says.
    """
    fresh_state = _first_sight_of_planning_state(session_id, active_workflow)
    if not request.strip() or not (fresh_state or plan_just_made(history)):
        return ""
    return ACCEPTANCE_LINE if accepts_plan(request) else ""

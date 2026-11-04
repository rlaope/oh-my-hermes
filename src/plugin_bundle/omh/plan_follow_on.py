"""Name `dag-ulw` as a way to run a plan, on the two turns where a plan's follow-on is chosen.

The planning skills name `dag-ulw` among the follow-ons of an accepted plan,
but neither turn on which the person actually chooses one carried them:

- Hermes' own `/plan` turn. It is host-written, so nothing of OMH's routes on
  it, and its template closes by offering to carry the plan out. That offer is
  the choice the person later answers ("구현하기"), and it named no engine.
- The turn that accepts the plan. The planning skill was loaded a turn
  earlier, or never (`/plan`), and the router reads "구현해줘" as plain work.

So each gets one line here. `plan_turn_line` rides `/plan`'s turn, read from
its frame alone (`host_plan_turn`). `acceptance_line` rides a person's turn
that follows a plan and reads as accepting it, and is decided in two steps:

1. A plan was just produced, read from structure, never from the words of
   this turn: the active workflow is a planning one; or the previous turn
   was `/plan`'s, invoked a planning skill, loaded one with `skill_view`, or
   wrote or named a plan file (`.hermes/plans/`, `.omh/plans/`).
2. This turn accepts it and leaves the way to run it open (`accepts_plan`): a
   short message that says go, without a question, a change, a hold, or the
   name of a way to run it (`dag-ulw`, `ultrawork`, subagents, "직접").

Without step 1 nothing is read, so a turn with no fresh plan renders exactly
what it rendered before. Both lines only offer: the person picks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import re

from .hermes_session_commands import host_plan_turn, person_request_text
from .text_fold import TOKEN_RE, fold_for_match

DAG_ULW = "dag-ulw"
# The workflow states a plan is drafted under (`ALLOWED_TRANSITIONS` sources that name dag-ulw).
PLANNING_WORKFLOWS = frozenset({"plan", "ralplan", "refactor-plan"})
# Their catalog names and the labels Hermes lists and `skill_view` loads them by.
PLANNING_SKILL_NAMES = frozenset({"plan", "omh-plan", "ralplan", "ulw-plan", "refactor-plan", "omh-refactor-plan"})
PLAN_FILE_DIRS = (".hermes/plans/", ".omh/plans/")

PLAN_TURN_LINE = (
    "[OMH Plan Follow-on] When you offer to carry this plan out: if it has several tasks with an order "
    "between them and a verification step, offer `dag-ulw` too (its tasks as a dependency graph with a "
    "closing verify node) beside carrying it out directly. Start neither this turn."
)
ACCEPTANCE_LINE = (
    "[OMH Plan Follow-on] This message accepts the plan just made without saying how to run it. If the "
    "plan has several tasks with an order between them and a verification step, and the person has not "
    "already picked from an offer naming `dag-ulw`, offer `dag-ulw` (the tasks as a dependency graph with "
    "a closing verify node) beside carrying it out directly, in one line, and start what they pick. "
    "Otherwise carry it out."
)

# A message longer than this is doing more than saying go.
_MAX_WORDS = 12
_LATIN_TOKEN = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*")
# Saying go. English is matched as whole tokens or token runs; Korean stems
# anywhere in the folded text, and Korean acknowledgements as whole words.
_GO_TOKENS = frozenset(
    {
        "implement", "implementing", "execute", "proceed", "start", "begin", "build", "ship",
        "approve", "approved", "accept", "accepted", "lgtm", "yes", "yep", "yeah", "ok", "okay", "sure",
    }
)
_GO_PHRASES = (("do", "it"), ("go", "ahead"), ("carry", "it", "out"), ("looks", "good"), ("sounds", "good"),
               ("let's", "go"), ("run", "it"))
_GO_KO_STEMS = ("구현", "진행", "실행", "시작", "승인", "만들어", "개발", "착수", "가자", "고고", "ㄱㄱ", "대로")
_GO_KO_WORDS = frozenset({"좋아", "좋아요", "좋습니다", "오케이", "ㅇㅋ", "ㅇㅇ", "응", "네", "넵", "예", "그래", "콜"})
# A change, a question, a hold or a refusal: not acceptance yet.
_NOT_YET_TOKENS = frozenset(
    {
        "change", "instead", "but", "except", "add", "remove", "drop", "rename", "replace", "update", "revise",
        "edit", "modify", "rewrite", "redo", "again", "not", "no", "don't", "dont", "wait", "hold", "stop",
        "cancel", "later", "explain", "why", "what", "how", "which", "first", "before",
    }
)
_NOT_YET_KO_STEMS = (
    "바꿔", "바꾸", "변경", "수정", "고쳐", "대신", "근데", "그런데", "하지만", "다만", "빼고", "빼줘", "추가", "넣어",
    "다시", "아니", "말고", "잠깐", "기다", "멈춰", "중지", "취소", "보류", "나중", "왜", "뭐", "무엇", "설명", "어떻게",
    "먼저", "전에",
)
# A way to run it, already named: the person chose, so nothing is offered.
_CHOSEN_TOKENS = frozenset(
    {"dag", "ulw", "ultrawork", "ultraqa", "ralph", "loop", "team", "subagent", "subagents", "directly",
     "yourself", "manually"}
)
_CHOSEN_KO_STEMS = ("서브에이전트", "서브 에이전트", "직접", "울트라")


def _folded(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(fold_for_match(value) for value in values)


_GO_KO = _folded(_GO_KO_STEMS)
_GO_KO_WORDS_FOLDED = frozenset(_folded(tuple(_GO_KO_WORDS)))
_NOT_YET_KO = _folded(_NOT_YET_KO_STEMS)
_CHOSEN_KO = _folded(_CHOSEN_KO_STEMS)


def _has_phrase(tokens: list[str], phrases: tuple[tuple[str, ...], ...]) -> bool:
    return any(
        tuple(tokens[at:at + len(phrase)]) == phrase for phrase in phrases for at in range(len(tokens) - len(phrase) + 1)
    )


def accepts_plan(text: str) -> bool:
    """Whether a person's message, read right after a plan, says go and leaves how to run it open."""
    folded = fold_for_match(text).strip()
    words = folded.split()
    if not words or len(words) > _MAX_WORDS or "?" in folded:
        return False
    kept = [word for word in words if "/" not in word]
    # Latin runs on their own, so a particle glued on ("ultrawork로") leaves the word whole.
    tokens = [token for word in kept for token in _LATIN_TOKEN.findall(word)]
    parts = set(tokens) | {part for token in tokens for part in token.split("-")}
    if parts & (_NOT_YET_TOKENS | _CHOSEN_TOKENS) or any(stem in folded for stem in _NOT_YET_KO + _CHOSEN_KO):
        return False
    return bool(
        parts & _GO_TOKENS
        or _has_phrase(tokens, _GO_PHRASES)
        or any(stem in folded for stem in _GO_KO)
        or _GO_KO_WORDS_FOLDED & {token for word in kept for token in TOKEN_RE.findall(word)}
    )


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


def _names_plan_file(value: object) -> bool:
    return isinstance(value, str) and any(directory in value for directory in PLAN_FILE_DIRS)


def _loaded_planning_skill(call: object) -> bool:
    function = call.get("function") if isinstance(call, Mapping) else None
    if not isinstance(function, Mapping) or function.get("name") != "skill_view":
        return False
    arguments = function.get("arguments")
    try:
        parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
    except ValueError:
        return False
    name = parsed.get("name") if isinstance(parsed, Mapping) else None
    return isinstance(name, str) and name.strip().rsplit("/", 1)[-1] in PLANNING_SKILL_NAMES


def plan_just_made(history: object) -> bool:
    """Whether the turn before this one produced a plan, read from its rows' structure."""
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
    for row in turn[1:]:
        if row.get("role") != "assistant":
            continue
        if _names_plan_file(row.get("content")):
            return True
        for call in row.get("tool_calls") or ():
            if _loaded_planning_skill(call):
                return True
            function = call.get("function") if isinstance(call, Mapping) else None
            if isinstance(function, Mapping) and _names_plan_file(function.get("arguments")):
                return True
    return False


def plan_turn_line(user_message: object) -> str:
    """`PLAN_TURN_LINE` on `/plan`'s own turn, else ""."""
    return PLAN_TURN_LINE if host_plan_turn(user_message) else ""


def acceptance_line(request: str, history: object, active_workflow: Mapping[str, object] | None) -> str:
    """`ACCEPTANCE_LINE` on a person's turn that accepts a plan just made, else "".

    `request` is the person's own words (empty on a turn Hermes wrote), and
    `active_workflow` this session's `active_workflow_context` projection.
    """
    if not request.strip():
        return ""
    planning = bool(
        active_workflow
        and active_workflow.get("state") == "active"
        and active_workflow.get("workflow") in PLANNING_WORKFLOWS
    )
    if not (planning or plan_just_made(history)):
        return ""
    return ACCEPTANCE_LINE if accepts_plan(request) else ""

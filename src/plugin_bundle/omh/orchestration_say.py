"""One plain sentence about an orchestration decision, for the model to relay.

Four OMH tools make a decision the person never sees unless the model says
so: which model takes a part of the work (`omh_delegate_route`), what the plan
is and when it counts as done, or which step is blocked or not yet confirmed
(`omh_todo`), what a loop is working toward or waiting on (`omh_loop`), and
which teammate a board lane adds (`omh_agent_board`). Their results carry the
facts in record fields whose names and values are OMH's own vocabulary, and a
model that relays those fields relays the vocabulary with them.

Each builder here turns the fields of one successful result into a `say`
string in plain English. The tool description and the common rail tell the
model to relay it once, in the person's language and its own words; nothing
here is quoted to the person verbatim.

Rules every builder keeps, pinned in `tests/test_orchestration_say.py`:

- Only the decision's own success status gets a sentence. A read, an error, a
  refusal or a contended write returns ``None``, so the result carries no key.
- The sentence states what the record holds and never invents a criterion,
  a reason or a model.
- Nothing from OMH's record vocabulary is added around the echoed values: no
  category id, no reason code, no schema id, no `[OMH ...]` head. Values the
  model wrote (a title, an item, a blocked reason, a goal) are echoed as
  written, so the sentence carries exactly the vocabulary they carry, and a
  value that already ends a sentence (`?`, `!`, `。`) gets no period added.

Stdlib only and no `omh.*` import: this module runs inside Hermes's own
interpreter. The model labels are vendored from
`omh.catalogs.model_chain_table.MODEL_DISPLAY_LABELS`, and a parity test fails
with the alias to add when the two differ.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

# Vendored from `omh.catalogs.model_chain_table.MODEL_DISPLAY_LABELS`; the
# parity test names the alias to add or remove. An alias with no label (a
# person's own chain entry, an explicit model id) is said as written: a model
# alias is the person's own word for a model, not OMH vocabulary.
MODEL_DISPLAY_LABELS: Final[dict[str, str]] = {
    "claude-fable-5-1": "Claude Fable 5.1",
    "claude-fable-5-2": "Claude Fable 5.2",
    "claude-haiku-4-5": "Claude Haiku 4.5",
    "claude-haiku-5-5": "Claude Haiku 5.5",
    "claude-opus-5": "Claude Opus 5",
    "claude-opus-5-5": "Claude Opus 5.5",
    "claude-sonnet-5-5": "Claude Sonnet 5.5",
    "deepseek-flash": "DeepSeek V4.1 Flash",
    "gemini-3.1-pro": "Gemini 3.1 Pro",
    "gemini-4-argon": "Gemini 4 Argon",
    "glm-5.3": "GLM 5.3",
    "glm-5.3-flash": "GLM 5.3 Flash",
    "gpt-5.6-luna": "GPT-5.6 Luna",
    "gpt-5.6-sol": "GPT-5.6 Sol",
    "gpt-5.6-terra": "GPT-5.6 Terra",
    "gpt-6-astra": "GPT-6 Astra",
    "gpt-6-luna": "GPT-6 Luna",
    "gpt-6-sol": "GPT-6 Sol",
    "gpt-6.1-sol": "GPT-6.1 Sol",
    "gpt-6.1-terra": "GPT-6.1 Terra",
    "gpt-6-cyber": "GPT-6 Cyber",
    "gpt-5.6-cyber": "GPT-5.6 Cyber",
    "gpt-6-rosalind": "GPT-6 Rosalind",
    "grok-4.7": "Grok 4.7",
    "grok-build-0.1": "Grok Build 0.1",
    "grok-code-fast": "Grok Code Fast",
    "kimi-k3": "Kimi K3",
    "kimi-k3.1-pro": "Kimi K3.1 Pro",
    "kimi-k3.1-pro-highspeed": "Kimi K3.1 Pro Highspeed",
    "qwen3-coder": "Qwen3-Coder",
}

# What a routed part is FOR, keyed on the bundle's routable categories
# (`hermes_delegation.HERMES_MIXTURE_CATEGORY_CHAINS`). Owned here rather than
# vendored from the chain table's "What it is for" cells, which are table
# labels ("Strong default tier", "Cheaper fallback") and read as record copy
# after "for". A category whose name is a strength or cost tier rather than a
# kind of work has no phrase, and says why below; the parity test requires
# every routable category to sit in exactly one of the two maps.
ROUTE_PURPOSE_PHRASES: Final[dict[str, str]] = {
    "ultrabrain": "the hardest reasoning",
    "architect": "architecture and system design",
    "quick": "short tasks",
    "writing": "prose and docs",
    "visual-engineering": "frontend and visual work",
    "artistry": "unconventional work",
    "simple-work": "small everyday tasks",
    "deep-work": "long, demanding tasks",
    "google-search": "research grounded in Google Search",
    "x-search": "live search on X",
    "review": "an independent attempt to break the change",
    "swarm": "one of many parallel slices",
    "forensics": "root-causing a live symptom or a captured trace",
    "synthesize": "merging many results into one answer",
}
ROUTE_NO_PURPOSE_REASONS: Final[dict[str, str]] = {
    "deep": "a strength tier; it names no kind of work",
    "capable": "a strength tier; it names no kind of work",
    "unspecified-high": "the default working tier; it names no kind of work",
    "unspecified-low": "a cost tier; it names no kind of work",
}

EXHAUSTED_ROUTE_SAY: Final = (
    "No other chosen model is left for this part, so it goes back to your usual model."
)

# One plain clause per `done_unverified` reason code
# (`todo_reconciliation.EVIDENCE_REASONS`); the code itself is never said.
# The test loops over the producer's codes, so a new code fails by name.
UNVERIFIED_REASON_PHRASES: Final[dict[str, str]] = {
    "no_evidence": "nothing recorded yet shows it was carried out",
    "evidence_failed": "the recorded result shows it failed",
    "evidence_unresolved": "its recorded result could not be confirmed",
    "evidence_unreadable": "this session's records could not be read to confirm it",
}
_UNKNOWN_UNVERIFIED_PHRASE: Final = "no recorded result confirms it yet"

PLAN_DONE_CRITERION: Final = (
    "It is complete when every step is finished with a recorded result or blocked "
    "with a stated reason."
)

# Per `lane_role` (`omh.workflows.agent_board.LANE_ROLES`); the parity test
# names a role to add. Only a prepared create says it: the model still has to
# invoke the native action, so this says a teammate is being set up, never
# that one is working.
LANE_ROLE_SAY: Final[dict[str, str]] = {
    "builder": "Setting up a teammate to build this part.",
    "verifier": "Setting up a teammate to check this work once the parts it depends on land.",
    "reviewer": "Setting up a reviewer to look over this work once the parts it depends on land.",
    "docs": "Setting up a teammate to write the docs for this work.",
    "qa": "Setting up a teammate to try this work the way a user would.",
}


# A value that already ends a sentence gets no period after it: "is blocked:
# can we ship?" stays a question, and a Japanese reason keeps its own `。`.
_SENTENCE_ENDS: Final = ("?", "!", "？", "！", "。")


def _clause(value: object) -> str:
    """An echoed value as a clause: trimmed, one line, no closing ASCII period."""
    text = " ".join(str(value or "").split())
    return text.rstrip(" .")


def _ended(clause: str) -> str:
    """*clause* closed as a sentence: a period unless it already ends one."""
    return clause if clause.endswith(_SENTENCE_ENDS) else f"{clause}."


def model_label(alias: object) -> str:
    name = str(alias or "").strip()
    return MODEL_DISPLAY_LABELS.get(name, name)


def route_say(result: Mapping[str, Any]) -> str | None:
    """The sentence for an `omh_delegate_route` result, or ``None``."""
    status = result.get("status")
    if status == "exhausted_to_inherit":
        return EXHAUSTED_ROUTE_SAY
    if status not in {"routed", "fell_back"}:
        return None
    applied = result.get("applied")
    alias = applied.get("alias") if isinstance(applied, Mapping) else ""
    label = model_label(alias)
    if not label:
        return None
    phrase = ROUTE_PURPOSE_PHRASES.get(str(result.get("category") or ""), "")
    purpose = f" for {phrase}" if phrase else ""
    if status == "fell_back":
        return f"This part moves to the next model in line: {label}{purpose}."
    return f"This part will run on {label}{purpose}."


def _steps(count: int) -> str:
    return f"{count} step" if count == 1 else f"{count} steps"


def _item(todo: Mapping[str, Any], index: object) -> Mapping[str, Any] | None:
    items = todo.get("items")
    if not isinstance(items, list) or not isinstance(index, int) or isinstance(index, bool):
        return None
    if 1 <= index <= len(items) and isinstance(items[index - 1], Mapping):
        return items[index - 1]
    return None


def _unverified_sentence(todo: Mapping[str, Any], unverified: object) -> str:
    if not isinstance(unverified, Sequence) or isinstance(unverified, str) or not unverified:
        return ""
    first = unverified[0]
    if not isinstance(first, Mapping):
        return ""
    index = first.get("item")
    item = _item(todo, index)
    named = f"Step {index} ({_clause(item.get('text'))})" if item else f"Step {index}"
    phrase = UNVERIFIED_REASON_PHRASES.get(str(first.get("reason") or ""), _UNKNOWN_UNVERIFIED_PHRASE)
    sentence = f"{named} is marked done, but {phrase}, so it still counts as open."
    more = len(unverified) - 1
    if more:
        sentence += f" {more} more marked-done {'step also counts' if more == 1 else 'steps also count'} as open."
    return sentence


def todo_say(
    action: object,
    status: object,
    todo: object,
    *,
    item: object = None,
    unverified: object = None,
) -> str | None:
    """The sentence for an `omh_todo` write, or ``None``.

    A set states the plan and its done criterion; an advance that leaves its
    item with a recorded reason states the item and the reason -- blocked
    while it is open, skipped once it is done. Either one adds the
    first done item no recorded result closes. Nothing else speaks.
    """
    if status != "written" or not isinstance(todo, Mapping):
        return None
    parts: list[str] = []
    if action == "set":
        items = todo.get("items")
        count = len(items) if isinstance(items, list) else 0
        if not count:
            return None
        title = _clause(todo.get("title"))
        head = f"Plan: {title} ({_steps(count)})." if title else f"Plan: {_steps(count)}."
        parts.extend((head, PLAN_DONE_CRITERION))
    elif action == "advance":
        changed = _item(todo, item)
        reason = _clause(changed.get("blocked_reason")) if changed else ""
        if reason:
            # A done item with a reason is a step the plan did not need (the
            # code-story template keeps an unneeded phase that way), and the
            # record closes it as skipped; only an open item is blocked.
            named = f"{item} ({_clause(changed.get('text'))})"
            if changed.get("state") == "done":
                parts.append(_ended(f"Skipped step {named}: {reason}"))
            else:
                parts.append(_ended(f"Step {named} is blocked: {reason}"))
    else:
        return None
    unverified_sentence = _unverified_sentence(todo, unverified)
    if unverified_sentence:
        parts.append(unverified_sentence)
    return " ".join(parts) or None


def loop_say(request: Mapping[str, Any], envelope: Mapping[str, Any]) -> str | None:
    """The sentence for an `omh_loop` start or external wait, or ``None``."""
    if envelope.get("status") != "ok":
        return None
    action = request.get("action")
    if action == "start":
        goal = _clause(request.get("goal_reframe"))
        raw = request.get("success_criteria")
        criteria = [_clause(value) for value in raw] if isinstance(raw, list) else []
        criteria = [value for value in criteria if value]
        if not goal or not criteria:
            return None
        return f"Goal: {_ended(goal)} Done when: {_ended('; '.join(criteria))}"
    if action == "feedback":
        wait = _clause(request.get("external_wait"))
        return _ended(f"Waiting on something outside this work: {wait}") if wait else None
    return None


def board_say(prepared: Mapping[str, Any]) -> str | None:
    """The sentence for a prepared `omh_agent_board` create with a role, or ``None``."""
    if prepared.get("state") != "prepared" or prepared.get("operation") != "create":
        return None
    return LANE_ROLE_SAY.get(str(prepared.get("lane_role") or ""))


def with_say(payload: dict[str, Any], say: str | None) -> dict[str, Any]:
    """*payload* with ``say`` added when there is one; no key otherwise."""
    if say:
        payload["say"] = say
    return payload

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
import json
import logging
from pathlib import PurePosixPath
from threading import Lock
import time
from typing import Final, TypeGuard

from .. import runtime_paths
from ..caller_check import round_end_note as caller_note
from ..catch_log import PLAN_CONTINUED, record_catch
from ..consistency_trigger import (discard_snapshots, note_tool_batch, round_end_trigger, shell_changed_files,
                                   shell_spent_kinds, spend_shell_round_end, turn_root)
from ..export_check import round_end_note as export_note
from ..host_observation import observe_plugin_hook_call
from ..impact_check import round_end_note
from ..test_expectation_check import round_end_note as test_note
from ..todo_reconciliation import plan_continuation_parts
from .nudge_budget import plan_nudge_allowed

_UI_SUFFIXES: Final = frozenset({".css", ".html", ".jsx", ".less", ".sass", ".scss", ".svelte", ".tsx", ".vue"})
_DEPENDENCY_FILES: Final = frozenset(
    {
        "bun.lock",
        "cargo.lock",
        "cargo.toml",
        "go.mod",
        "go.sum",
        "package-lock.json",
        "package.json",
        "pnpm-lock.yaml",
        "pyproject.toml",
        "uv.lock",
        "yarn.lock",
    }
)
_OBSERVATION_KEYS: Final = ("host", "source", "evidence_ref", "evidence_refs", "omh_home", "hermes_home")
# Source files whose edit earns the round-end checklist. Deliberately partial:
# common source languages only. Docs, data, lock files and anything unlisted get
# no checklist, which is the cheap direction to be wrong in.
_CODE_SUFFIXES: Final = frozenset(
    {
        ".bash", ".c", ".cc", ".cjs", ".clj", ".cpp", ".cs", ".cxx", ".dart", ".erl", ".ex", ".exs", ".go",
        ".groovy", ".h", ".hpp", ".hs", ".java", ".jl", ".js", ".jsx", ".kt", ".kts", ".lua", ".m", ".mjs",
        ".ml", ".mm", ".php", ".pl", ".ps1", ".py", ".pyi", ".r", ".rb", ".rs", ".scala", ".sh", ".sql",
        ".svelte", ".swift", ".tf", ".ts", ".tsx", ".vue", ".zig", ".zsh",
    }
)
# Asked at most once per turn, at the first stop after a code edit, and alone
# only when `consistency_trigger` finds a copy or a reference outside the
# edited files (or cannot rule one out). It carries one
# check only: a second copy or call site of the changed logic that had to change
# with it, the miss a model makes when it stops as soon as the target test
# passes. Scope and verification lines were measured too and showed no effect
# (bench README, 2026-10-30). "Do not re-run tests" is scoped to this check and
# dropped when the served-surface gate or the impact note beside it asks for a
# run or a re-check: that request stands.
ROUND_END_CHECKLIST: Final = (
    "OMH round-end consistency check, once per turn: look for other copies or call sites of the logic "
    "you changed this turn that have to change with it, and fix any you find. Do not re-run tests for "
    "this check. This note is guidance, not verification evidence."
)
ROUND_END_CHECKLIST_BESIDE_A_RECHECK: Final = (
    "OMH round-end consistency check, once per turn: look for other copies or call sites of the logic "
    "you changed this turn that have to change with it, and fix any you find. This note is guidance, not "
    "verification evidence."
)
# The host keeps the answer the model stopped with only as an interim message,
# and whatever the model says after this note becomes the turn's final
# response: the one `--oneshot`, API and delegating callers receive. Asking the
# model to retype that answer cost a whole extra answer and invited test
# re-runs, so it replies with this one line instead, and `transform_llm_output`
# swaps the line back to the stashed answer, byte for byte.
ROUND_END_SENTINEL: Final = "OMH: no further changes."
ROUND_END_CLOSING: Final = (
    "When you are done: if you changed nothing more this turn, reply with exactly the next line and nothing "
    f"else, and OMH returns the answer you just gave, unchanged:\n{ROUND_END_SENTINEL}\n"
    "If you changed anything, give your full updated final answer instead, in the form the task asked for."
)
# Without a stash to swap back there is no sentinel to offer, so the model is
# asked for the answer itself.
ROUND_END_CLOSING_UNSTASHED: Final = (
    "When you are done, give your final answer to the task again, in full and in the form the task asked "
    "for: it replaces the answer you just gave."
)
# Delegated children answer a parent, often against an output schema; their
# final response is the parent's tool result and must stay the task's answer.
# This only matters under `agent.coding_context: on`: Hermes gives
# non-interactive platforms such as `subagent` no coding posture otherwise, so
# `coding` is already False for them.
_NO_CHECKLIST_PLATFORMS: Final = frozenset({"subagent"})
# One stashed answer per session, for the turn that is ending. Consumed only by
# a sentinel match, cleared at the session's next turn start, bounded like the
# other per-session maps in this bundle, and aged out as a last backstop.
MAX_STASHED_ANSWERS: Final = 64
STASHED_ANSWER_SECONDS: Final = 3600.0
_STASHED_ANSWERS: "OrderedDict[str, tuple[float, str]]" = OrderedDict()
_STASH_LOCK = Lock()


def pre_verify(
    session_id: str = "",
    platform: str = "",
    model: str = "",
    coding: object = False,
    attempt: object = 0,
    final_response: str = "",
    changed_paths: object = None,
    **_kwargs: object,
) -> dict[str, str] | None:
    valid_coding = coding is True
    attempt_value = _attempt_value(attempt)
    paths = _normalized_paths(changed_paths)
    observation = {key: _kwargs[key] for key in _OBSERVATION_KEYS if key in _kwargs}
    observation.update(
        {
            "session_id": session_id,
            "coding": valid_coding,
            "attempt": attempt_value if attempt_value is not None else -1,
            "changed_path_count": len(paths),
            "changed_path_categories": _path_categories(paths),
            "session_present": bool(session_id),
            "platform_present": bool(platform),
            "model_present": bool(model),
            "final_response_present": bool(final_response),
        }
    )
    _ = observe_plugin_hook_call("pre_verify", observation)
    if attempt_value is None or not paths:
        if attempt_value == 0:
            # A stop with no edited path still ends the turn: its snapshots are not kept to the next one.
            discard_snapshots(session_id)
        return None
    # The opt-in cross-file impact check (`impact_check`) answers once per
    # turn, at the first stop, and does not depend on the coding posture: it
    # has a baseline only when this turn edited a Python file, which is the
    # posture's own evidence. Empty unless an importer gained an error.
    impact_message = round_end_note(session_id, changed_paths) if attempt_value == 0 else ""
    # The export check is always on: it parses only this turn's edited `.py` files (and the
    # workspace modules they import from) with `ast`, so it costs no language server and no
    # extra round of its own. It names an `__all__` entry or a `from x import name` that no
    # longer resolves -- a rename's leftover that no type error reports -- and is empty otherwise.
    # A line the impact note already names is not named again; its paths are relative to the same
    # workspace root, the one this turn's tools resolved against.
    export_message = (export_note(session_id, changed_paths, impact_message, turn_root(session_id))
                      if attempt_value == 0 else "")
    # The test check names an existing test whose expected values this turn changed, when the request
    # asked for behaviour to stay the same and did not ask for that test to change. Like the export
    # note it continues the turn on its own: putting the expectation back is the work.
    test_message = test_note(session_id, turn_root(session_id)) if attempt_value == 0 else ""
    # The caller check names a call this turn's signature change broke: one that bound to the
    # function's turn-start parameters and no longer binds, found with `ast` through the importer scan
    # (package re-exports included). It also continues the turn on its own, and a line the impact or
    # export note already names is not named again.
    caller_message = (caller_note(session_id, turn_root(session_id), f"{impact_message}\n{export_message}")
                      if attempt_value == 0 else "")
    surface_message = checklist_message = plan_message = ""
    open_items = 0
    if valid_coding:
        plan_message, stamp, open_items = _session_plan_reading(_kwargs, session_id)
        # The host offers `agent.max_verify_nudges` nudges per turn and enforces
        # that bound itself, so the plan line may spend more than the first -- but
        # only while the plan keeps being written. A nudge that produced no movement
        # does not repeat, which is what the idempotency guidance was protecting;
        # `nudge_budget` holds the one piece of per-turn state that tells the two
        # apart.
        if not plan_nudge_allowed(session_id=session_id, attempt=attempt_value, stamp=stamp):
            plan_message = ""
        # The served-surface gate stays one-shot. It asks for the check this turn's
        # edit just earned, and the edits are the same on a later attempt of the
        # same turn, so repeating it would restate a request the turn already has.
        surface_message = _served_surface_message(paths) if attempt_value == 0 else ""
        # The round-end check is one-shot for the same reason, and it is the
        # turn's only one: attempt 0 is the first stop after the edits, and the
        # host moves `attempt` past 0 once any nudge here continues the turn.
        # As the host spelled them: `paths` is lower-cased for matching, and the
        # trigger reads these files from the disk.
        raw_paths = changed_paths if _is_path_sequence(changed_paths) else ()
        code_paths = tuple(path for path in raw_paths
                           if isinstance(path, str) and _is_code_path(path.replace("\\", "/").lower()))
        if attempt_value == 0 and str(platform) not in _NO_CHECKLIST_PLATFORMS and code_paths:
            # The check costs a round of its own only when nothing else here
            # continues the turn. Then it fires only when the edit has a copy or
            # a reference outside the edited files, or when that cannot be ruled
            # out (`consistency_trigger`). Beside another nudge it rides along,
            # the export note included: that note continues the turn on its own
            # whatever the trigger says, because fixing the line it names is the work.
            alone = not (surface_message or impact_message or export_message or test_message or caller_message
                          or plan_message)
            if not alone or round_end_trigger(session_id, code_paths).fire:
                # Beside a request to run or re-check something, the check must
                # not say "do not re-run": that request stands.
                checklist_message = (ROUND_END_CHECKLIST_BESIDE_A_RECHECK
                                     if surface_message or impact_message or test_message else ROUND_END_CHECKLIST)
    if attempt_value == 0:
        # The turn's snapshots are spent at its first stop, read or not.
        discard_snapshots(session_id)
    # One directive, in a fixed order: the served-surface gate, the impact
    # note, the export note, the test note, the caller note, the round-end check, the plan directive. Each can
    # be true of the same turn, and dropping one because another fired would
    # lose exactly the case it was written for. One closing final-answer
    # sentence goes last, for the notes and the check together, and only
    # without a plan directive: an open plan means the turn goes on, so there
    # is no final answer to ask for yet.
    closing = ""
    if (impact_message or export_message or test_message or caller_message or checklist_message) and not plan_message:
        # A delegated child's reply is its parent's tool result: it returns
        # its full answer, never a sentinel, so nothing is stashed for it.
        # A broken call is a change the turn still has to make, so no
        # "nothing more changed" line is offered beside the caller note.
        if str(platform) in _NO_CHECKLIST_PLATFORMS or caller_message \
                or not _stash_answer(session_id, final_response):
            closing = ROUND_END_CLOSING_UNSTASHED
        else:
            closing = ROUND_END_CLOSING
    messages = [text for text in (surface_message, impact_message, export_message, test_message, caller_message,
                                  checklist_message, plan_message, closing) if text]
    if not messages:
        return None
    # Recorded for the person once per turn. `attempt` is the only turn
    # boundary this hook is given (no turn id), and attempt 0 always passes
    # `plan_nudge_allowed`, so a plan line there is the turn's first; a later
    # attempt re-issuing it is the same catch with the plan still moving.
    if attempt_value == 0 and plan_message and open_items:
        record_catch(str(_kwargs.get("omh_home") or ""), session_id, PLAN_CONTINUED, open_items=open_items)
    return {"action": "continue", "message": "\n".join(messages)}


def _stash_answer(session_id: object, answer: object) -> bool:
    """Keep the answer this turn stopped with, for `restore_round_end_answer`; False when there is none."""
    if not isinstance(session_id, str) or not session_id or not isinstance(answer, str) or not answer.strip():
        return False
    with _STASH_LOCK:
        _STASHED_ANSWERS[session_id] = (time.monotonic(), answer)
        _STASHED_ANSWERS.move_to_end(session_id)
        while len(_STASHED_ANSWERS) > MAX_STASHED_ANSWERS:
            _STASHED_ANSWERS.popitem(last=False)
    return True


def restore_round_end_answer(*, session_id: object, response_text: object) -> str | None:
    """The stashed answer when this turn's reply is the round-end sentinel; None otherwise.

    Called from `transform_llm_output`. The stash is consumed only by a
    sentinel match. Hermes's background review runs as a fork that shares the
    parent's session id and still fires `transform_llm_output`, so a fork
    finishing during the consistency round must not take the parent's stash
    with it. Anything left is cleared at the session's next turn start
    (`clear_round_end_answer`, from `pre_llm_call`), overwritten by the next
    attempt-0 stash, or aged out.
    """
    if not isinstance(session_id, str) or not session_id or not isinstance(response_text, str):
        return None
    if not _is_sentinel(response_text):
        return None
    with _STASH_LOCK:
        stashed = _STASHED_ANSWERS.pop(session_id, None)
    if stashed is None:
        return None
    taken_at, answer = stashed
    if time.monotonic() - taken_at > STASHED_ANSWER_SECONDS:
        return None
    return answer


def clear_round_end_answer(session_id: object) -> None:
    """Drop a stash a finished turn left behind; called at the session's next turn start."""
    if isinstance(session_id, str) and session_id:
        with _STASH_LOCK:
            _STASHED_ANSWERS.pop(session_id, None)


# Light wrapping a model adds to a one-line reply: code ticks, quotes, bold or
# italic markers. Longer text, or the line after a report, is not the sentinel.
_SENTINEL_WRAPPING: Final = "`\"'*_"


def _is_sentinel(text: str) -> bool:
    core = text.strip().strip(_SENTINEL_WRAPPING).strip()
    return core.removesuffix(".") == ROUND_END_SENTINEL.removesuffix(".")


def reset_stashed_answers() -> None:
    """Forget every stashed answer (tests)."""
    with _STASH_LOCK:
        _STASHED_ANSWERS.clear()


# Hermes calls `pre_verify` only after a `patch` / `write_file` landed this turn, so a turn that edits
# only through a command (`sed -i`, a heredoc script) never reaches it. The round end's structural notes
# (export, test, caller: each names a line that is broken now, and is empty otherwise) ride the result of
# the command that changed a Python file instead, each check once per turn, under their own key. The model reads a
# message's results together, so of a message's commands only its last one is looked at; and a turn whose
# round end `pre_verify` already ran gets none, since its turn-start text is gone. The consistency
# checklist does not: it needs the coding posture, which this seam is not given, and alone it names no
# line. The impact note does not either: its baseline is taken only before a `patch` / `write_file`.
SHELL_ROUND_END_TOOLS: Final = frozenset({"terminal", "execute_code"})
SHELL_ROUND_END_KEY: Final = "omh_round_end"
_LOG = logging.getLogger("omh.verify_hooks")


def annotate_shell_round_end(*, tool_name: object, result: object, session_id: object,
                             turn_id: object, tool_call_id: object = "") -> str | None:
    """`transform_tool_result`: the command's result with the round-end notes for the Python files this
    turn changed, when the command just changed one and a note names something; None otherwise."""
    if tool_name not in SHELL_ROUND_END_TOOLS or not isinstance(result, str) or not result:
        return None
    try:
        parsed: object = json.loads(result)
    except (ValueError, TypeError):
        parsed = None
    if parsed is not None and (not isinstance(parsed, dict) or SHELL_ROUND_END_KEY in parsed):
        return None
    note = shell_round_end_note(session_id, turn_id, tool_call_id)
    if not note:
        return None
    if not isinstance(parsed, dict):
        return f"{result}\n\n{note}"
    parsed[SHELL_ROUND_END_KEY] = note
    return json.dumps(parsed, ensure_ascii=False)


def post_api_request(session_id: object = "", response: object = None, **_kwargs: object) -> None:
    """Keep the model message's tool-call ids, so the shell round end looks at a message's commands only
    after its last one (`consistency_trigger.note_tool_batch`). An observer: returns nothing."""
    message = response.get("assistant_message") if isinstance(response, dict) else None
    note_tool_batch(session_id, message.get("tool_calls") if isinstance(message, dict) else None)


def shell_round_end_note(session_id: object, turn_id: object, tool_call_id: object = "") -> str:
    """The export, test and caller notes `pre_verify` would give at attempt 0, for a turn that changed
    Python files only through commands; ``""`` when the last command changed none or no note names a line."""
    paths = shell_changed_files(session_id, turn_id, tool_call_id)
    if not paths or not isinstance(session_id, str):
        return ""
    root = turn_root(session_id)
    spent = shell_spent_kinds(session_id)
    export_message = export_note(session_id, list(paths), "", root) if "export" not in spent else ""
    test_message = test_note(session_id, root) if "test" not in spent else ""
    caller_message = caller_note(session_id, root, export_message) if "caller" not in spent else ""
    _LOG.info("shell_round_end session=%s files=%d export=%d test=%d caller=%d", session_id, len(paths),
              bool(export_message), bool(test_message), bool(caller_message))
    spoke = {kind for kind, text in (("export", export_message), ("test", test_message), ("caller", caller_message))
             if text}
    spend_shell_round_end(session_id, spoke)
    return "\n".join(text for text in (export_message, test_message, caller_message) if text)


def _session_plan_reading(kwargs: dict[str, object], session_id: str) -> tuple[str, str, int]:
    """The open-plan directive for the session whose turn is ending, its stamp, and its open items.

    Homes bind the way ``pre_llm_call`` binds them. A binding failure is
    silence: a plugin that cannot read the plan has nothing to say about it
    and must not fail the turn it is decorating. It also has no stamp, so a
    turn whose homes stop binding mid-way spends no further budget.
    """
    try:
        omh_home = str(runtime_paths.plugin_home(kwargs.get("omh_home")))
        hermes_home = str(runtime_paths.plugin_home(kwargs.get("hermes_home"), hermes=True))
    except (runtime_paths.RuntimeBindingError, OSError, RuntimeError):
        return "", "", 0
    return plan_continuation_parts(
        omh_home=omh_home, hermes_home=hermes_home, session_ref=session_id
    )


def _normalized_paths(value: object) -> tuple[str, ...]:
    if not _is_path_sequence(value):
        return ()
    return _normalized_string_paths(value)


def _is_path_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, (list, tuple))


def _normalized_string_paths(paths: Sequence[object]) -> tuple[str, ...]:
    return tuple(path.replace("\\", "/").lower() for path in paths if isinstance(path, str) and path.strip())


def _attempt_value(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _path_categories(paths: tuple[str, ...]) -> list[str]:
    categories: list[str] = []
    if any(_is_plugin_path(path) for path in paths):
        categories.append("plugin")
    if any(_is_ui_path(path) for path in paths):
        categories.append("ui")
    if any(PurePosixPath(path).name in _DEPENDENCY_FILES for path in paths):
        categories.append("dependency")
    if any(_is_ci_path(path) for path in paths):
        categories.append("ci")
    return categories or (["other"] if paths else [])


def _served_surface_message(paths: tuple[str, ...]) -> str:
    if any(_is_plugin_path(path) for path in paths):
        return (
            "OMH served-surface verification gate: this change affects a Hermes plugin surface. "
            "Run the smallest real plugin load and registration smoke available, then report the observed command and result. "
            "This nudge is guidance, not plugin-load or verification evidence."
        )
    if any(_is_ui_path(path) for path in paths):
        return (
            "OMH served-surface verification gate: this change affects a rendered surface. "
            "Open or render the changed UI at representative desktop and mobile sizes, inspect interaction and text layout, "
            "and report observed evidence. This nudge is guidance, not visual QA evidence."
        )
    if any(PurePosixPath(path).name in _DEPENDENCY_FILES for path in paths):
        return (
            "OMH served-surface verification gate: this change affects dependency or build metadata. "
            "Run the smallest installation or import smoke plus the relevant project check, then report the observed command and result. "
            "This nudge is guidance, not installation or verification evidence."
        )
    if any(_is_ci_path(path) for path in paths):
        return (
            "OMH served-surface verification gate: this change affects CI workflow configuration. "
            "Validate the workflow syntax and exercise the nearest local command path before finishing. "
            "This nudge is guidance, not CI or verification evidence."
        )
    return ""


def _is_code_path(path: str) -> bool:
    return PurePosixPath(path).suffix in _CODE_SUFFIXES


def _is_ui_path(path: str) -> bool:
    return PurePosixPath(path).suffix in _UI_SUFFIXES


def _is_plugin_path(path: str) -> bool:
    return "/plugin_bundle/" in f"/{path.lstrip('/')}" or path.endswith("plugin.yaml")


def _is_ci_path(path: str) -> bool:
    return "/.github/workflows/" in f"/{path.lstrip('/')}"

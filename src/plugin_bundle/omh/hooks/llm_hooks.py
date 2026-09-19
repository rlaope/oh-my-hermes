from __future__ import annotations

from .. import runtime_paths

from collections import Counter
import errno
from datetime import datetime, timezone
import hashlib
import re
import sqlite3
import threading

from ..awareness import (
    awareness_context_match_degradation,
    awareness_context_matches_message,
    awareness_primer_context,
    awareness_route_hint,
    awareness_route_hint_context_from_payload,
)
from ..context_brief import build_context_brief
from ..degradation import (
    COMPONENT_LOCALIZED_ROUTING_TEXT,
    COMPONENT_RUNTIME_STATUS_READ,
    degradation_payload,
    safe_error_type,
    runtime_binding_degradation,
)
from ..active_workflow_context import active_workflow_context, render_active_workflow_context
from ..approval_bypass import record_approval_bypass
from ..awareness_delivery import claim_route_guidance_delivery, record_awareness_delivery
from ..context_budget_plan import context_budget_continuation, render_context_budget
from ..host_context import record_active_main_agent_model
from ..host_observation import observe_plugin_hook_call
from ..kanban_board_reader import conversation_session_ids, kanban_db_path, read_kanban_lanes
from ..omh_roles import extract_role_marker, role_context_payload
from ..dispatch_outcomes import unacknowledged_outcomes
from ..runtime_reader import read_omh_activity, read_omh_hud, read_omh_status, read_omh_todo
from .session_attendance import note_session_platform
from ..todo_reconciliation import (
    answer_first_turn,
    continuation_claim_without_resume,
    open_todo_reminder,
)
from ..turn_authorship import host_synthesized_turn
from ..status_board_reader import (
    last_running_work_board_fingerprint,
    read_running_work_board,
    record_running_work_board_emission,
    render_running_work_block_text,
    running_work_board_fingerprint,
)


# A closing claim lives at the END of a message, so the bound keeps the tail;
# the guard only needs to recognize the phrasing, not fold a whole long reply.
_MAX_ASSISTANT_CLAIM_CHARS = 4000

# The board re-entry card is one line, once per session. The memory is
# process-local, the way `code_mode_guidance` remembers its one-shot line: the
# awareness ledger keeps exactly one slot per session, and that slot is the
# route-hint claim, so parking a second fact there would either replace the
# route fingerprint or be replaced by it.
_BOARD_CARD_MAX_CHARS = 160
_board_card_lock = threading.Lock()
_board_card_sessions: set[str] = set()

# Where this hook's return value ends up, and why it needs a wrapper of its
# own. Hermes concatenates it onto the API copy of the USER message --
# `compose_user_api_content` in `agent/turn_context.py` builds
# `content + "\n\n" + injections` -- with no role separation and no marker. So
# every line below is delivered as a continuation of what the person wrote,
# and while most of them open with an `[OMH ...]` head, the dispatch lines and
# the running-work rows carry no head at all.
#
# Hermes already solved exactly this for its own memory channel, which wraps
# `<memory-context>` around a `[System note: ... NOT new user input]` line
# (`build_memory_context_block`, `agent/memory_manager.py`). This is the same
# device for the plugin channel, with the second sentence the memory block
# does not need: memory is reference data, whereas this is instruction, and
# instruction arriving inside someone's message can outrank the message
# unless it says it does not.
#
# The fence is emitted only around something. A turn with nothing to say
# injects exactly zero characters, as it did before.
OMH_CONTEXT_FENCE_OPEN = "<omh-context>"
OMH_CONTEXT_FENCE_CLOSE = "</omh-context>"
# Two properties and no third: what this text is, and that it loses to the
# person. It is repeated on every turn that injects anything, so its length is
# paid per turn -- and it cannot be sent once and referred back to, because a
# compaction that drops the earlier turn would leave a bare tag with nothing
# saying what it fences.
OMH_CONTEXT_FENCE_NOTE = (
    "[System note: automated OMH context, NOT the person's words; their "
    "message outranks it.]"
)

# The fence's second half, and it is not optional. Most of what goes inside is
# text OMH did not write: todo item text and the active-item label the model
# authored, dispatch run and unit refs, workflow names, kanban lane titles,
# role markdown, route-hint fields derived from the person's own message. A
# part carrying `</omh-context>` closes the fence early, and everything after
# it is delivered as the person's words again with no marker -- the exact
# condition the fence exists to remove, reachable by whatever writes a todo
# item. So the tag is removed from the body rather than trusted not to appear.
#
# The host's own memory fence does the same thing (`sanitize_context`,
# `agent/memory_manager.py`) and this matches its tolerance: either tag, any
# case, whitespace inside the brackets.
#
# Stripped rather than escaped, for the host's reason and one more. An escape
# needs a reader that un-escapes it and there is none -- the bytes go to a
# model, and Hermes replays this turn's `api_content` verbatim on every later
# turn, so an escaped tag would sit in the prompt forever looking like a
# boundary marker. Removing it costs the surrounding text nothing.
_OMH_CONTEXT_FENCE_TAG_RE = re.compile(r"</?\s*omh-context\s*>", re.IGNORECASE)

# That a tag had to be removed is worth knowing and is not a call failure, so
# it does not belong in `degradation` -- that lane's claim boundary says an
# OMH-local delegated call failed and a fallback answered, which would be
# false here. This is the shape `engagement_nudges` already uses for the same
# need: one in-process tally with a reader, diagnostics only and never a gate.
# No file, no schema, no new journal.
_fence_strips: "Counter[str]" = Counter()


def omh_context_fence_strips() -> dict[str, int]:
    """A copy of the fence-tag strip tally, by tag. Diagnostics, never a gate."""
    return dict(_fence_strips)


def reset_omh_context_fence_strips() -> None:
    """Test seam: forget the strip tally."""
    _fence_strips.clear()


def _strip_fence_tags(part: str) -> str:
    """Remove any `omh-context` tag a part carries, counting what was removed."""
    cleaned, removed = _OMH_CONTEXT_FENCE_TAG_RE.subn("", part)
    if removed:
        _fence_strips["omh_context_tag"] += removed
    return cleaned


def fence_omh_context(parts: list[str]) -> str:
    """Join this turn's context parts inside the OMH fence, or return ``""``.

    Everything goes inside, including the parts that carry no `[OMH ...]`
    head: the point of the fence is that the boundary is structural rather
    than a convention each producer has to remember. For the same reason the
    body is sanitized here and not by each producer -- a new part added
    upstream is covered without its author knowing this exists.

    A part that carried no tag is unchanged byte for byte, and a turn with
    nothing to say is still exactly zero characters.
    """
    body = "\n\n".join(_strip_fence_tags(part) for part in parts if part)
    if not body.strip():
        return ""
    return (
        f"{OMH_CONTEXT_FENCE_OPEN}\n{OMH_CONTEXT_FENCE_NOTE}\n\n"
        f"{body}\n{OMH_CONTEXT_FENCE_CLOSE}"
    )


def _token_metadata_from_kwargs(kwargs: dict) -> dict[str, object]:
    keys = (
        "tokens_remaining",
        "token_budget",
        "input_tokens",
        "output_tokens",
        "context_remaining_percent",
    )
    return {key: kwargs[key] for key in keys if kwargs.get(key) is not None}


def _record_delivery(
    *,
    delivered: bool,
    route_hint: bool,
    context_chars: int,
    omh_home: str | None,
    session_id: str = "",
    route_fingerprint: str = "",
) -> None:
    """Note that this hook ran. Never let bookkeeping break the hook itself."""
    try:
        record_awareness_delivery(
            delivered=delivered,
            route_hint=route_hint,
            context_chars=context_chars,
            observed_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            omh_home=omh_home or "",
            session_id=session_id,
            route_fingerprint=route_fingerprint,
        )
    except (OSError, ValueError, TypeError):
        return


def _primer_already_in_api_history(conversation_history: object, primer: str) -> bool:
    """Whether Hermes already persisted this primer in an API-content sidecar.

    Hermes replays prior ``api_content`` values byte-for-byte for prompt-cache
    stability. Re-emitting the same primer on a later turn therefore grows the
    prompt permanently. Inspect only the host-injected suffix of that sidecar,
    subtracting the clean message prefix, so a user quoting
    ``[OMH Awareness]`` cannot suppress guidance.
    """
    if not primer or not isinstance(conversation_history, (list, tuple)):
        return False
    for message in reversed(conversation_history):
        if not isinstance(message, dict):
            continue
        api_content = message.get("api_content")
        if not isinstance(api_content, str):
            continue
        clean_content = message.get("content")
        injected_content = api_content
        if isinstance(clean_content, str) and api_content.startswith(clean_content):
            injected_content = api_content[len(clean_content) :]
        if primer in injected_content:
            return True
    return False


def _last_assistant_text(conversation_history: object) -> str:
    """The previous turn's closing text, or "" when the host replays none.

    Hermes hands `pre_llm_call` the conversation so far; the newest assistant
    message in it is the closing text of the turn that just ended. `content`
    is the clean message -- `api_content` carries host-injected context that
    the model never wrote, so a plugin reminder quoting a continuation phrase
    could otherwise flag itself.
    """
    if not isinstance(conversation_history, (list, tuple)):
        return ""
    for message in reversed(conversation_history):
        if not isinstance(message, dict):
            continue
        if str(message.get("role", "")) != "assistant":
            continue
        content = message.get("content")
        return content[-_MAX_ASSISTANT_CLAIM_CHARS:] if isinstance(content, str) else ""
    return ""


def _turn_display_kind(conversation_history: object) -> str:
    """The host's own typing of the row that opened this turn, or ``""``.

    Hermes hands `pre_llm_call` no field saying who wrote the turn, but it
    does hand over `conversation_history`, and the turn's own user row is the
    newest one in it: `build_turn_context` appends `user_msg` to `messages`
    and passes that list, with nothing appended after it before this hook
    runs. `_stage_turn_user_message` stamps `display_kind` on that row at turn
    START -- that is what `persist_user_display_kind` exists for -- so the
    value is present by the time this reads it.

    Scanned from the end for the newest user row rather than taken from the
    last index, because turn-start compaction may prepend a handoff row and
    the assistant rows of earlier turns sit in between. Same shape as
    `_last_assistant_text` above, for the same reason.

    A history the host did not pass, or one with no user row in it, answers
    absence -- which `turn_opened_by_person` reads as a person, keeping the
    behaviour a caller had before this existed.
    """
    if not isinstance(conversation_history, (list, tuple)):
        return ""
    for message in reversed(conversation_history):
        if not isinstance(message, dict) or str(message.get("role", "")) != "user":
            continue
        kind = message.get("display_kind")
        return kind if isinstance(kind, str) else ""
    return ""


def _todo_stall_status(omh_home: str, hermes_home: str, session_ref: str) -> str:
    """The reader's own stall verdict for this session's plan.

    `todo.stall` is where that verdict lives, so the guard reads it instead of
    re-deriving "has this plan stopped moving" from an age and a liveness
    flag -- the duplication the projection exists to end. A read that raises
    leaves the guard resting on the unacknowledged count alone; an absent
    verdict is never inverted into a stall.
    """
    try:
        todo = read_omh_todo(omh_home or None, hermes_home or None, session_ref=session_ref)
    except (OSError, ValueError, TypeError):
        return ""
    stall = todo.get("stall")
    return str(stall.get("status", "")) if isinstance(stall, dict) else ""


def _board_lanes_card(hermes_home: str, session_id: str) -> str:
    """One line naming the open board lanes this conversation created, or "".

    A Hermes Kanban task carries the ``session_id`` that created it, and the
    board outlives the chat: a lane queued last session is still on the board
    when the conversation resumes, with nothing in the replayed history saying
    so. The card names the count and the tool that reads the lanes back. It is
    absent whenever the board has nothing this conversation owns -- no db, no
    rows, rows stamped by another session -- and on any read fault, since a
    missing card costs one line and a raised hook costs the whole turn's
    context.
    """
    if not session_id:
        return ""
    try:
        db = kanban_db_path(hermes_home)
        if db is None or not db.is_file():
            return ""
        owners = conversation_session_ids(hermes_home, session_id)
        if not owners:
            return ""
        lanes = read_kanban_lanes(hermes_home, session_ids=owners, limit=1)
    except (OSError, RuntimeError, ValueError, TypeError, sqlite3.Error):
        return ""
    if lanes.get("scope") != "session":
        return ""
    running = int(lanes.get("running", 0) or 0)
    queued = int(lanes.get("queued", 0) or 0)
    blocked = int(lanes.get("blocked", 0) or 0)
    total = running + queued + blocked
    if total <= 0:
        return ""
    noun = "lane" if total == 1 else "lanes"
    card = (
        f"[OMH board] {total} board {noun} from this chat: {running} running, "
        f"{queued} queued, {blocked} blocked; read back with kanban_list"
    )
    return card[:_BOARD_CARD_MAX_CHARS]


def _claim_board_card(session_id: str) -> bool:
    """Atomically claim the one board card this process shows a session."""
    with _board_card_lock:
        if session_id in _board_card_sessions:
            return False
        _board_card_sessions.add(session_id)
    return True


def _reset_board_card_state() -> None:
    """Test seam: forget which sessions were shown the board card."""
    with _board_card_lock:
        _board_card_sessions.clear()


def _tracker_event_is_present(kwargs: dict) -> bool:
    """Recognize a host-labelled tracker event without inspecting its text."""
    for key in ("tracker_event", "github_event"):
        event = kwargs.get(key)
        if isinstance(event, dict) and (
            "tracker_content" in event or "github_event" in event or event.get("provider") == "github"
        ):
            return True
    return False


def pre_llm_call(**kwargs) -> dict[str, object] | None:
    """Inject bounded OMH role/status context without storing prompts."""
    # Bind before any observer or awareness I/O. A failed root must not reach
    # downstream defaults as None, or fail before the status classifier runs.
    try:
        omh_home = str(runtime_paths.plugin_home(kwargs.get("omh_home")))
        hermes_home = str(runtime_paths.plugin_home(kwargs.get("hermes_home"), hermes=True))
    except (runtime_paths.RuntimeBindingError, OSError, RuntimeError) as exc:
        return runtime_binding_degradation(exc)
    record_active_main_agent_model(kwargs.get("model"))
    # The only hook OMH registers that is passed a platform and fires once
    # per turn before that turn's tool calls. `pre_tool_call` is passed the
    # five identity ids and nothing else, so this is where the repeat guard
    # learns whether its stage-two escalation would have a reader.
    note_session_platform(kwargs.get("session_id"), kwargs.get("platform"))
    observe_plugin_hook_call("pre_llm_call", kwargs)
    # Turn start is the freshest in-process view of the Shift+Tab yolo flag:
    # a toggle shows on the HUD at the user's next message, not only at the
    # next tool call.
    record_approval_bypass(omh_home=omh_home)
    context_parts: list[str] = []
    payload: dict[str, object] = {}
    user_message = "" if _tracker_event_is_present(kwargs) else str(kwargs.get("user_message", "") or "")
    is_first_turn = bool(kwargs.get("is_first_turn", False))
    include_awareness = kwargs.get("include_omh_awareness", True) is not False
    route_hint_context = ""
    route_hint_payload: dict[str, object] | None = None
    route_fingerprint = ""
    session_id = str(kwargs.get("session_id", "") or "")
    # Read once per turn and handed to every surface that branches on it, so
    # the plan line, the claim-finding suppression and the router cannot
    # disagree about who opened this turn.
    turn_display_kind = _turn_display_kind(kwargs.get("conversation_history"))
    # Hermes opens turns for rows it writes itself -- a background process
    # finishing, an async delegation batch, a model switch -- and each is a
    # `role="user"` row carrying real text. There is no request on such a
    # turn, so there is nothing to route: every surface below that reads the
    # message AS A REQUEST reads this instead, and gets absence. Measured in
    # the owner's `state.db`, 272 of the 282 host-synthesized rows match the
    # awareness vocabulary, one of them producing a `selected=` verdict and
    # 3,297 characters of routing on a background-process notice (#1741).
    #
    # One derived value rather than a condition per surface: the route hint,
    # the vocabulary match, the per-fingerprint claim and the structured
    # brief all ask "what is this turn asking for", and a gate on three of
    # the four is how the fourth keeps routing. What is NOT re-pointed is
    # everything that reads the turn as an event rather than a request -- the
    # plan drive, the dispatch outcome lines, the active-workflow line, the
    # role marker, the first-turn primer -- because a completion notice is
    # exactly the turn on which those matter.
    request_message = "" if host_synthesized_turn(turn_display_kind) else user_message
    message_matches_awareness = False
    degraded: list[tuple[str, str]] = []
    if include_awareness:
        if is_first_turn:
            route_hint_payload = awareness_route_hint(request_message)
            route_hint_context = awareness_route_hint_context_from_payload(route_hint_payload)
            message_matches_awareness = bool(route_hint_context)
            route_degradation = route_hint_payload.get("degradation")
            if isinstance(route_degradation, dict):
                for row in route_degradation.get("components", []):
                    if isinstance(row, dict):
                        degraded.append((str(row.get("component", "")), str(row.get("error_type", ""))))
        else:
            # The matcher is called exactly when it is called today; the
            # `is_first_turn` short circuit is preserved because the cache-count
            # tests depend on it. The accessor reads the same cache entry the
            # matcher just populated, so it costs a hit and never a miss.
            message_matches_awareness = awareness_context_matches_message(request_message)
            match_error = awareness_context_match_degradation(request_message)
            if match_error:
                degraded.append((COMPONENT_LOCALIZED_ROUTING_TEXT, match_error))
        if message_matches_awareness and route_hint_payload is None:
            route_hint_payload = awareness_route_hint(request_message)
            route_hint_context = awareness_route_hint_context_from_payload(route_hint_payload)
        if route_hint_context:
            route_fingerprint = hashlib.sha256(route_hint_context.encode("utf-8")).hexdigest()
            if not claim_route_guidance_delivery(
                session_id=session_id,
                route_fingerprint=route_fingerprint,
                omh_home=omh_home,
            ):
                route_hint_context = ""
                message_matches_awareness = False
    # The primer is the block that says OMH exists at all. Gating it on the
    # message already containing OMH vocabulary made it unreachable for exactly
    # the sessions that needed it: eight ordinary work requests measured on
    # `main` -- including "migrate the database schema, update all models, fix
    # the tests, and write the migration guide" -- carried no OMH word and so
    # got nothing. There was no way out from inside either, because the
    # per-turn plan line reads an `established` plan and can only continue a
    # checklist that already exists.
    #
    # So the session's first turn carries it unconditionally. Deliberately not
    # a task-size test: judging "big enough" is the same guess that is already
    # failing here, and the largest request in that set is one of the misses.
    # The cost is bounded and one-off -- one primer, once per session.
    #
    # The route hint keeps its own gate: it is message-specific, so a message
    # that matched nothing still contributes no hint text, and the
    # per-fingerprint claim above still decides whether guidance already went
    # out. This widens what the primer reaches, not what counts as a route.
    #
    # `is_first_turn` therefore stays unqualified by who opened that turn. A
    # session whose first row is a notice -- a cron, a resumed run picking up
    # a finished background process -- still gets the primer on it, and that
    # is the reachable choice rather than the tidy one: Hermes computes
    # `is_first_turn` as "no prior history" (`_collect_pre_llm_call_context`,
    # `agent/turn_context.py`), so it is true on exactly one turn per
    # session. Withholding the primer there does not defer it to the first
    # person turn, it drops it for the whole session and puts that session
    # back on the vocabulary gate the paragraph above describes. Delivering
    # it costs nothing later either: the host replays it in `api_content`, so
    # `_primer_already_in_api_history` finds it and the person's turns read
    # the primer they would have got. What the notice does NOT get is the
    # routing -- `request_message` is empty above, so the brief's route hint
    # is the no-hint shape and no `[OMH Route Hint]` block is built.
    should_include_awareness = (
        include_awareness
        and (bool(route_hint_context) or message_matches_awareness or is_first_turn)
    )
    if should_include_awareness:
        primer = awareness_primer_context()
        if not _primer_already_in_api_history(kwargs.get("conversation_history"), primer):
            context_parts.append(primer)
        payload["omh_context_brief"] = build_context_brief(
            request_message,
            source=str(kwargs.get("source") or kwargs.get("host") or "pre_llm_call"),
            max_hints=2,
            include_prompt_context=False,
            route_hint_payload=route_hint_payload,
        )
        if route_hint_context:
            context_parts.append(route_hint_context)
        brief = payload.get("omh_context_brief")
        if isinstance(brief, dict):
            for row in brief.get("degradation", {}).get("components", []):
                if isinstance(row, dict):
                    degraded.append((str(row.get("component", "")), str(row.get("error_type", ""))))

    marker = extract_role_marker(user_message)
    if marker:
        role_payload = role_context_payload(marker)
        if role_payload["status"] == "available":
            context_parts.append(
                "\n".join(
                    [
                        f"[OMH Role: {role_payload['role']}]",
                        str(role_payload["context"]),
                        str(role_payload["claim_boundary"]),
                    ]
                )
            )
        else:
            context_parts.append(
                "[OMH Role Warning] "
                f"Unknown role '{marker}'. Available roles: {', '.join(role_payload['available_roles']) or '(none)'}."
            )

    # An open plan is a state, not a phrasing: while one exists, every turn
    # carries the reconciliation line so a completion claim cannot part ways
    # with the HUD checklist unnoticed. Honors the caller's awareness opt-out.
    #
    # `user_message` rides along for one bit only -- whether a message opened
    # this turn, which decides whether the line asks for the next plan item or
    # asks for that message to be answered first. It is the variable computed
    # above rather than the raw kwarg on purpose: a host-labelled tracker
    # event is already zeroed there, and an event is not someone writing.
    if include_awareness:
        outcomes = unacknowledged_outcomes(
            omh_home,
            hermes_home,
            session_id,
        )
        todo_reminder = open_todo_reminder(
            omh_home=omh_home,
            hermes_home=hermes_home,
            session_ref=session_id,
            outcomes=outcomes,
            user_message=user_message,
            turn_display_kind=turn_display_kind,
            # This hook IS the turn. Hermes calls it exactly once per turn from
            # `build_turn_context`, which is the only reason the reconciliation
            # rule's per-plan turn budget can be counted here at all.
            count_turn=True,
        )
        if todo_reminder:
            context_parts.append(todo_reminder)
        workflow_context = active_workflow_context(
            omh_home, session_id
        )
        if workflow_context:
            payload["omh_active_workflow"] = workflow_context
            context_parts.append(render_active_workflow_context(workflow_context))
        budget_context = context_budget_continuation(
            omh_home, session_id, str(kwargs.get("model", "") or "")
        )
        if budget_context:
            payload["omh_context_budget"] = budget_context
            context_parts.append(render_context_budget(budget_context))
        # The only seam OMH has on assistant text: Hermes replays the prior
        # turn in `conversation_history`, so a continuation promised last turn
        # is checked at the start of this one -- which is exactly when it can
        # still be kept. There is no post-turn hook that sees the closing
        # message as it is written.
        #
        # Held back entirely on a turn whose plan line is the answer-first
        # variant. Three obligations each claimed "this turn" and could be
        # live together: the plan line said the message was the turn's work,
        # the dispatch block said the finished unit was, and this said the
        # next step was. The dispatch block is now ordered behind the answer
        # (`DISPATCH_AFTER_ANSWER_RULE`) and this one has nothing left to add:
        # its two record facts are the plan line and the dispatch lines
        # sitting directly above it.
        claim_finding = (
            ""
            if answer_first_turn(
                user_message=user_message,
                turn_display_kind=turn_display_kind,
                omh_home=omh_home,
                hermes_home=hermes_home,
                session_ref=session_id,
            )
            else continuation_claim_without_resume(
                _last_assistant_text(kwargs.get("conversation_history")),
                # An outstanding outcome already answers the question, so the
                # plan is only re-read when there is none.
                todo_stall_status=(
                    ""
                    if outcomes
                    else _todo_stall_status(
                        omh_home,
                        hermes_home,
                        session_id,
                    )
                ),
                unacknowledged=len(outcomes),
            )
        )
        if claim_finding:
            context_parts.append(f"[OMH continuation claim] {claim_finding}")
        # The board is read every turn (an existence check first, one bounded
        # read-only query after), but the card goes out once: the claim is
        # taken only when there is a card to show, so a session whose lanes
        # appear on a later turn still gets named exactly once.
        board_card = _board_lanes_card(hermes_home, session_id)
        if board_card and _claim_board_card(session_id):
            context_parts.append(board_card)

    try:
        try:
            activity = read_omh_activity(omh_home=omh_home, limit=3)
        except Exception as exc:
            # Keep the historical degradation component stable while moving
            # the hot path from full status to the active-only projection.
            error_type = "RuntimeError" if getattr(exc, "errno", None) == errno.ELOOP else type(exc).__name__
            degraded.append((COMPONENT_RUNTIME_STATUS_READ, safe_error_type(error_type)))
            activity = {"active_executors": []}
        if activity.get("active_executors"):
            status = read_omh_status(omh_home=omh_home, limit=3)
            hud = read_omh_hud(
                omh_home=omh_home,
                hermes_home=hermes_home,
                status=status,
                preset="focused",
                limit=3,
                token_metadata=_token_metadata_from_kwargs(kwargs),
            )
        else:
            status = activity
            hud = {}
    except Exception as exc:
        # The read raised. Without this the next branch reads the empty status
        # as `runtime_state_present` being false, so a failed status read looks
        # exactly like a host with nothing to report.
        status = {}
        hud = {}
        error_type = "RuntimeError" if getattr(exc, "errno", None) == errno.ELOOP else type(exc).__name__
        degraded.append((COMPONENT_RUNTIME_STATUS_READ, safe_error_type(error_type)))

    # A first-turn primer fallback stood here, reached only when an executor
    # was already running. `should_include_awareness` now covers every first
    # turn, so its `not should_include_awareness` condition can no longer be
    # true and the block would have been unreachable code claiming to handle a
    # case the gate above already handles.

    board = read_running_work_board(omh_home, limit=6)
    running_count = int(board.get("running_count", 0) or 0)
    # Two or more concurrently running coding units IS the "multi-session
    # orchestration is in flight" condition -- no fixed keyword phrasing can
    # cover every way a user's message might arrive while that is true, but a
    # live running-unit count cannot be phrased around. One running unit is
    # ordinary single-session work, not evidence of orchestration, so the
    # threshold is a count (>= 2), never a keyword match.
    board_fingerprint = running_work_board_fingerprint(board) if running_count >= 2 else ""
    show_running_work = running_count >= 2 and board_fingerprint != last_running_work_board_fingerprint(omh_home)

    degradation = degradation_payload(degraded)
    if (
        not context_parts
        and not degradation
        and not status.get("active_executors")
        and not show_running_work
    ):
        return None

    if status.get("active_executors"):
        lines = [
            str(hud.get("display", {}).get("line", "[omh] status unavailable")),
            "[OMH] Native bridge status context.",
            "Evidence boundary: prepared handoffs are not execution, review, CI, merge-readiness, or merge evidence.",
        ]
        latest_run_id = status.get("latest_run_id")
        if latest_run_id:
            lines.append(f"Latest runtime run: {latest_run_id}.")
        for executor in status.get("active_executors", [])[:3]:
            profile = executor.get("executor_profile") or executor.get("executor") or "unknown"
            target_type = executor.get("target_type") or "unknown"
            state = executor.get("state") or "active"
            latest_event = executor.get("latest_event", {})
            event_status = latest_event.get("status", "") if isinstance(latest_event, dict) else ""
            suffix = f", status={event_status}" if event_status else ""
            lines.append(
                f"- active executor: profile={profile}, target_type={target_type}, state={state}{suffix}."
            )
        for run in status.get("runs", [])[:3]:
            run_id = run.get("run_id", "unknown")
            workflow = run.get("workflow", "unknown")
            phase = run.get("phase", "unknown")
            observation = run.get("observation_status", "unknown")
            execution = run.get("execution_observed", False)
            review = run.get("review_observed", False)
            ci = run.get("ci_observed", False)
            merge = run.get("merge_observed", False)
            lines.append(
                f"- {run_id}: workflow={workflow}, phase={phase}, observation={observation}, "
                f"execution_observed={execution}, review_observed={review}, ci_observed={ci}, merge_observed={merge}."
            )
        lines.append("Use omh_hud for the compact status line, omh_role for role context, or omh_status for full metadata-only status.")
        context_parts.append("\n".join(lines))
    if show_running_work:
        board_text = render_running_work_block_text(board)
        context_parts.append(board_text)
        record_running_work_board_emission(omh_home, byte_count=len(board_text), fingerprint=board_fingerprint)
    if degradation:
        payload["omh_degradation"] = degradation
        # Component labels only here, which now differs from the binding
        # degradation on this same hook: that one names the exception type in
        # its own context line. The difference is what the value is worth to
        # a reader, not a disagreement about the rule. These components are
        # OMH-local fallbacks whose exception type tells a person nothing they
        # can act on, while a binding fault's type is the only thing
        # separating a session no profile owns from a store that was named
        # and could not be read, and it has no other surface (#1733).
        # One caveat for whoever reads the older half of this sentence:
        # "stays in the structured payload" is not "stays readable". No host
        # path reads that block, so a value kept only there is dropped.
        context_parts.append(
            "[OMH Degraded] components="
            + ",".join(str(row["component"]) for row in degradation["components"])
            + ". An OMH-local delegated call failed and a reduced local fallback answered. "
            "This is a local call failure, not a genuine standalone host. It is an observation of "
            "that failure only: not execution, review, CI, merge-readiness, or merge evidence."
        )
    payload["context"] = fence_omh_context(context_parts)
    _record_delivery(
        delivered=True,
        route_hint=bool(route_hint_context),
        context_chars=len(payload["context"]),
        omh_home=omh_home,
        session_id=session_id,
        route_fingerprint=route_fingerprint,
    )
    return payload

"""Model judgement for the messenger chat gate: in a Slack or Discord room where
Hermes lets a silence marker stand, the model decides "be quiet" and "not for
me" in any language or wording, not a word list.

Three seams, all in the gateway process:

1. `pre_gateway_dispatch` (`messenger_gate.gate_event`) asks `judged_room`
   whether the message's room is judged. Hermes must resolve
   `allow_silence: true` for it through its own
   ``GatewayRunner._room_allow_silence`` (Hermes 0.22.6 and later; the method
   is the capability check, never a version string), and streaming must be off.
   A message such a room lets through is noted with `note_room`.
2. `pre_llm_call` appends `instruction(...)` when the turn's room, read from
   Hermes' session ContextVars, was noted (`turn_instruction`), and keeps the
   turn by its id.
3. `transform_llm_output` (`judged_reply`) turns an exact ``[SHUTUP]`` from a
   kept turn into Hermes' ``[SILENT]``, mutes the thread, and schedules the 🫡
   reaction on the gateway's event loop through Hermes' own
   ``agent.async_utils.safe_schedule_threadsafe``. A ``[SILENT]`` the model wrote itself
   goes to Hermes untouched.

Everywhere else (no `allow_silence`, an older Hermes, streaming on, a DM)
nothing is noted and no instruction is sent, so the model is never asked for a
marker Hermes would answer with its "returned only a silence marker" notice.
The instruction asks for a marker and nothing else; it never touches the bot's
voice. Both stores live in process memory, bounded in size and age, and are
shared by every copy of this module in the process.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import types
import unicodedata
from collections import OrderedDict
from typing import Any, Callable, NamedTuple

SHUTUP_TOKEN = "[SHUTUP]"
SILENT_TOKEN = "[SILENT]"
QUIET_LINE = (
    "If the latest message asks you to be quiet or to stop replying in this thread, in any "
    f"language or wording, reply with exactly {SHUTUP_TOKEN} and nothing else."
)
ELSEWHERE_LINE = (
    f"If it is clearly meant for someone else and not for you, reply with exactly {SILENT_TOKEN} "
    "and nothing else."
)
CLOSING_LINE = "Otherwise answer as you normally would."
INSTRUCTION_HEAD = "[OMH group chat]"

ROOM_LIMIT = 256
ROOM_TTL_SECONDS = 15 * 60
TURN_LIMIT = 256
TURN_TTL_SECONDS = 60 * 60
_TOKEN_LENGTH_CAP = 64
_SHUTUP_FORMS = frozenset({"[SHUTUP]", "[SHUT UP]", "[SHUT_UP]"})


class Room(NamedTuple):
    """A message a judged room let through: what the turn it opens needs at its end."""

    noted: float
    mode: str
    mute: Callable[[float], object]
    react: Callable[[], object]
    loop: Any


_LOG = logging.getLogger(__name__)
# One gateway process holds one copy of this module per profile home
# (`hermes_plugins.omh`, `hermes_plugins.omh__home_<digest>`). At a multiplexed
# gateway's ingress no profile scope is bound, so `pre_gateway_dispatch` runs on
# the launch profile's copy, while the turn's hooks run on the serving
# profile's. Per-copy records would leave a named profile's turn reading a room
# nobody noted, so they live in one process-wide holder (as `jev_consent`).
_STATE_HOLDER = "_omh_messenger_judgement_state"


def _shared_state() -> types.SimpleNamespace:
    candidate = types.SimpleNamespace(lock=threading.Lock(), rooms=OrderedDict(), turns=OrderedDict())
    holder = sys.modules.setdefault(_STATE_HOLDER, types.ModuleType(_STATE_HOLDER))
    return holder.__dict__.setdefault("state", candidate)


_state = _shared_state()
_lock = _state.lock
_rooms: OrderedDict[str, Room] = _state.rooms
_turns: OrderedDict[str, Room] = _state.turns


# --- the room ---------------------------------------------------------------------


def streaming_possible(gateway: object) -> bool:
    """Whether Hermes may stream this gateway's replies: its ``streaming.enabled`` switch.

    A per-platform display setting can only narrow that switch, so off here is
    off everywhere. Unknown reads as on: a raw ``[SHUTUP]`` must never stream.
    """
    streaming = getattr(getattr(gateway, "config", None), "streaming", None)
    return getattr(streaming, "globally_enabled", True) is not False


def judged_room(gateway: object, source: object) -> bool:
    """Whether the model judges messages in `source`'s room: Hermes lets a silence marker stand there."""
    lookup = getattr(gateway, "_room_allow_silence", None)
    if not callable(lookup) or not callable(getattr(gateway, "_silence_allowed_for_source", None)):
        return False
    if streaming_possible(gateway):
        return False
    try:
        return lookup(source) is True
    except (AttributeError, LookupError, OSError, TypeError, ValueError):
        return False


def gateway_loop(gateway: object) -> Any:
    """The gateway's event loop as Hermes records it (``GatewayRunner._gateway_loop``), for the reaction."""
    return getattr(gateway, "_gateway_loop", None)


def _put(store: OrderedDict, key: Any, value: Room, limit: int) -> None:
    store[key] = value
    store.move_to_end(key)
    while len(store) > limit:
        store.popitem(last=False)


def note_room(key: str, room: Room) -> None:
    """Remember the newest message a judged room let through."""
    with _lock:
        _put(_rooms, key, room, ROOM_LIMIT)


# --- the turn -----------------------------------------------------------------------


def instruction(mode: str) -> str:
    lines = [INSTRUCTION_HEAD, QUIET_LINE]
    if mode == "on":
        lines.append(ELSEWHERE_LINE)
    lines.append(CLOSING_LINE)
    return " ".join(lines)


def turn_instruction(turn_id: object, room_key: str, *, now: float | None = None) -> str:
    """The instruction for a turn in a judged room, or ""; keeps the turn for `judged_reply`."""
    if not isinstance(turn_id, str) or not turn_id or not room_key:
        return ""
    tick = time.time() if now is None else now
    with _lock:
        room = _rooms.get(room_key)
        if room is None or tick - room.noted > ROOM_TTL_SECONDS:
            return ""
        _put(_turns, turn_id, room, TURN_LIMIT)
    return instruction(room.mode)


def _take_turn(turn_id: object, now: float) -> Room | None:
    if not isinstance(turn_id, str) or not turn_id:
        return None
    with _lock:
        room = _turns.pop(turn_id, None)
    if room is None or now - room.noted > TURN_TTL_SECONDS:
        return None
    return room


# --- the reply ----------------------------------------------------------------------


def _canonical(text: str) -> str:
    stripped = text.strip()
    start, end = 0, len(stripped)
    # Stray edge punctuation (`*[SHUTUP]*`, `[SHUTUP].`), never the brackets themselves.
    while start < end and stripped[start] not in "[]" and unicodedata.category(stripped[start]).startswith("P"):
        start += 1
    while end > start and stripped[end - 1] not in "[]" and unicodedata.category(stripped[end - 1]).startswith("P"):
        end -= 1
    return " ".join(stripped[start:end].upper().split())


def is_shutup(text: object) -> bool:
    """True only when `text` is the whole ``[SHUTUP]`` token; one inside other text is not."""
    if not isinstance(text, str) or not 0 < len(text.strip()) <= _TOKEN_LENGTH_CAP:
        return False
    return _canonical(text) in _SHUTUP_FORMS


def _hermes_silence(text: str) -> bool:
    """Hermes' own exact silence-marker test; False on a host without it."""
    try:
        from gateway.response_filters import is_intentional_silence_response
    except ImportError:
        return False
    return is_intentional_silence_response(text) is True


def _schedule(react: Callable[[], object], loop: Any) -> bool:
    """Hand the 🫡 reaction to the gateway's loop; False when there is none to send.

    Hermes' own helper schedules it from this worker thread and closes the
    coroutine when the loop is gone; OMH imports no event-loop module itself.
    """
    if loop is None:
        return False
    pending = react()
    if pending is None:
        return False
    try:
        from agent.async_utils import safe_schedule_threadsafe
    except ImportError:
        close = getattr(pending, "close", None)
        if callable(close):
            close()
        return False
    return safe_schedule_threadsafe(pending, loop, logger=_LOG, log_message="omh messenger judgement reaction") is not None


def judged_reply(turn_id: object, response_text: object, *, now: float | None = None) -> tuple[bool, str | None]:
    """``(handled, replacement)`` for a turn's final reply.

    `handled` is True only for a kept turn whose reply is a marker: an exact
    ``[SHUTUP]`` becomes ``[SILENT]`` (the thread muted, the 🫡 scheduled), and
    a Hermes silence marker the model wrote passes with no replacement. Either
    way the caller adds nothing to it. Every other reply is not handled.
    """
    tick = time.time() if now is None else now
    room = _take_turn(turn_id, tick)
    if room is None or not isinstance(response_text, str):
        return False, None
    if not is_shutup(response_text):
        return (True, None) if _hermes_silence(response_text) else (False, None)
    try:
        room.mute(tick)
        _schedule(room.react, room.loop)
    except Exception as exc:  # health: allow BLE001 -- the room allows silence; a failed mute or reaction must not send the raw token
        _LOG.info("omh messenger judgement mute or reaction failed: %s", type(exc).__name__)
    return True, SILENT_TOKEN

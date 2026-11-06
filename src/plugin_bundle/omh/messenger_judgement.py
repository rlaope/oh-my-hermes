"""Model judgement for the messenger chat gate: in a Slack or Discord room where
Hermes lets a silence marker stand, the model decides "be quiet" and "not for
me" in any language or wording, not a word list.

Three seams, all in the gateway process:

1. `pre_gateway_dispatch` (`messenger_gate.gate_event`) asks `judged_room`
   whether the message's room is judged. Hermes must resolve
   `allow_silence: true` for it through its own
   ``GatewayRunner._room_allow_silence`` (Hermes 0.22.6 and later; the method
   is the capability check, never a version string), streaming must be off,
   and the serving profile must not run the Codex app-server runtime, which
   posts each finished message before the output hook runs.
   A message such a room lets through is noted with `note_room`.
2. `pre_llm_call` appends `instruction(...)` when the turn's room, read from
   Hermes' session ContextVars, was noted (`turn_instruction`), and keeps the
   turn by its id.
3. `transform_llm_output` (`judged_reply`) turns a ``[SHUTUP]`` reply from a
   kept turn into Hermes' ``[SILENT]``, mutes the thread, and schedules the 🫡
   reaction on the gateway's event loop through Hermes' own
   ``agent.async_utils.safe_schedule_threadsafe``. A ``[SILENT]`` the model wrote
   itself goes to Hermes, clean. A real answer is never dropped or altered: a
   token closing it is removed, with no mute, and one inside a sentence, a code
   block or a list stays, so it can show.

Everywhere else (no `allow_silence`, an older Hermes, streaming on, a DM)
nothing is noted and no instruction is sent, so the model is never asked for a
marker Hermes would answer with its "returned only a silence marker" notice.
The instruction asks for a marker and nothing else; it never touches the bot's
voice. Both stores live in process memory, bounded in size and age, and are
shared by every copy of this module in the process.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
import time
import types
import unicodedata
from collections import OrderedDict
from pathlib import Path
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
_ACKNOWLEDGEMENT_CHARS = 60
_CODE_OR_LINK_MARKS = frozenset('=`"[]()<>{}')
# What ends a sentence, read after `_normalized`: NFKC has made ``…`` into ``...`` and fullwidth ``！？`` into ASCII.
_SENTENCE_ENDS = frozenset(".!?。؟।۔‽")
_SHUTUP_WHOLE = re.compile(r"\[\s*SHUT[\s_-]*UP\s*\]", re.IGNORECASE)
_SILENT_WHOLE = re.compile(r"\[\s*SILENT\s*\]", re.IGNORECASE)
_EXACT_TOKENS = frozenset({SHUTUP_TOKEN, SILENT_TOKEN})
_LIST_ITEM = re.compile(r"\s*(?:[-*+]|\d+[.)])\s")
_CODEX_APP_SERVER = "codex_app_server"


class Room(NamedTuple):
    """A message a judged room let through: what the turn it opens needs at its end."""

    noted: float
    mode: str
    mute: Callable[[float], object]
    react: Callable[[], object]
    loop: Any
    addressed: bool = False
    log: Callable[[str, float], object] | None = None


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


def posts_before_output_hook(hermes_home: Path | None) -> bool:
    """Whether the serving profile may run Codex's app-server, read as Hermes reads it.

    That runtime posts a finished message (`_emit_interim_assistant_message`)
    before `transform_llm_output` fires, so a token would reach the chat. The
    setting alone decides, whatever the provider or display settings: only a
    profile that names the runtime can get it. Hermes' loader answers ``{}`` for
    a config it could not read, which is unknown here and reads as yes.
    """
    if hermes_home is None:
        return True
    try:
        from gateway.run import _load_gateway_config
    except (ImportError, AttributeError):
        return True
    config = _load_gateway_config(Path(hermes_home) / "config.yaml")
    if not isinstance(config, dict) or not config:
        return True
    model = config.get("model")
    if not isinstance(model, dict):
        return False
    providers, name = config.get("providers"), model.get("provider")
    provider = providers.get(name) if isinstance(providers, dict) and isinstance(name, str) else None
    named = (model.get("openai_runtime"), model.get("api_mode"),
             provider.get("api_mode") if isinstance(provider, dict) else None)
    return any(str(value or "").strip().lower() == _CODEX_APP_SERVER for value in named)


def judged_room(gateway: object, source: object, hermes_home: Path | None) -> bool:
    """Whether the model judges messages in `source`'s room: Hermes lets a silence marker stand there."""
    lookup = getattr(gateway, "_room_allow_silence", None)
    if not callable(lookup) or not callable(getattr(gateway, "_silence_allowed_for_source", None)):
        return False
    if streaming_possible(gateway):
        return False
    try:
        if lookup(source) is not True:
            return False
    except (AttributeError, LookupError, OSError, TypeError, ValueError):
        return False
    return not posts_before_output_hook(hermes_home)


def gateway_loop(gateway: object) -> Any:
    """The gateway's event loop as Hermes records it (``GatewayRunner._gateway_loop``), for the reaction."""
    return getattr(gateway, "_gateway_loop", None)


def _put(store: OrderedDict, key: Any, value: Room, limit: int) -> None:
    store[key] = value
    store.move_to_end(key)
    while len(store) > limit:
        store.popitem(last=False)


def note_room(key: str, room: Room) -> None:
    """Remember the newest message a judged room let through.

    An addressed message stays addressed until a turn takes it: a later aside must not offer
    ``[SILENT]`` to the turn that answers the request.
    """
    with _lock:
        held = _rooms.get(key)
        _put(_rooms, key, room._replace(addressed=room.addressed or bool(held and held.addressed)), ROOM_LIMIT)


# --- the turn -----------------------------------------------------------------------


def instruction(mode: str, addressed: bool = False) -> str:
    """The turn's instruction. A message the gate knows is addressed to the bot is never offered
    ``[SILENT]``: a real request must not be dropped. "Be quiet" is still the model's to read."""
    lines = [INSTRUCTION_HEAD, QUIET_LINE]
    if mode == "on" and not addressed:
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
        # The turn's own age starts here: a long queue wait must not shorten it.
        _put(_turns, turn_id, room._replace(noted=tick), TURN_LIMIT)
        _rooms[room_key] = room._replace(addressed=False)
    return instruction(room.mode, room.addressed)


def _take_turn(turn_id: object, now: float) -> Room | None:
    if not isinstance(turn_id, str) or not turn_id:
        return None
    with _lock:
        room = _turns.pop(turn_id, None)
    if room is None or now - room.noted > TURN_TTL_SECONDS:
        return None
    return room


# --- the reply ----------------------------------------------------------------------


def _normalized(text: str) -> str:
    """NFKC (fullwidth ``［SHUTUP］``) with format characters (zero-width, BOM) dropped."""
    folded = unicodedata.normalize("NFKC", text)
    return "".join(c for c in folded if unicodedata.category(c) != "Cf")


def _unwrapped(line: str) -> str:
    """`line` without the marks a model wraps around a token: code ticks, ``~~``, emoji, punctuation.

    Never the square brackets themselves, so a malformed ``[SHUTUP`` stays malformed.
    """
    start, end = 0, len(line)
    while start < end and line[start] not in "[]" and unicodedata.category(line[start])[0] in "PSZC":
        start += 1
    while end > start and line[end - 1] not in "[]" and unicodedata.category(line[end - 1])[0] in "PSZC":
        end -= 1
    return line[start:end]


def _whole_reply(text: str) -> str:
    """The reply with light wrapping gone: code ticks, ``~~``, edge marks, a fence that is all of it."""
    stripped = _normalized(text).strip()
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
        stripped = "\n".join(lines[1:-1]).strip()
    return _unwrapped(stripped)


def _acknowledged(text: str) -> bool:
    """One short line: the exact ``[SHUTUP]``, then a brief acknowledgement with no code or link marks."""
    stripped = _normalized(text).strip()
    if len(stripped) > _ACKNOWLEDGEMENT_CHARS or "\n" in stripped or not stripped.startswith(SHUTUP_TOKEN + " "):
        return False
    return not any(mark in stripped[len(SHUTUP_TOKEN):] for mark in _CODE_OR_LINK_MARKS)


def reply_marker(text: object) -> str | None:
    """The marker this whole reply is, or None: a real answer is never read as one.

    The whole reply is the token once lightly unwrapped, in any case, or it opens with the exact
    ``[SHUTUP]`` and a brief acknowledgement on one short line, or every line of it is a token (with
    any ``[SHUTUP]`` among them, that is the marker). A bare Hermes marker (``SILENT``, ``NO REPLY``)
    counts only as the whole reply. Any other token is the answer's own text.
    """
    if not isinstance(text, str):
        return None
    core = _whole_reply(text)
    if len(core) > _TOKEN_LENGTH_CAP:
        return None
    if _SHUTUP_WHOLE.fullmatch(core) or _acknowledged(text):
        return SHUTUP_TOKEN
    if _SILENT_WHOLE.fullmatch(core) or _hermes_silence(core):
        return SILENT_TOKEN
    return _token_lines_marker(core)


def _token_lines_marker(core: str) -> str | None:
    """The marker a reply of nothing but token lines is, or None. A list of them is shown, not said."""
    lines = [line for line in core.splitlines() if line.strip()]
    if any(_LIST_ITEM.match(line) for line in lines):
        return None
    tokens = [_unwrapped(line) for line in lines]
    if not tokens or not all(_SHUTUP_WHOLE.fullmatch(token) or _SILENT_WHOLE.fullmatch(token) for token in tokens):
        return None
    return SHUTUP_TOKEN if any(_SHUTUP_WHOLE.fullmatch(token) for token in tokens) else SILENT_TOKEN


def _quoted_at(lines: list[str], index: int) -> bool:
    """Whether the line at `index` is shown, not said: in a fence, in a list, or introduced by a colon."""
    if sum(line.lstrip().startswith("```") for line in lines[:index]) % 2:
        return True
    if index and _LIST_ITEM.match(lines[index - 1]):
        return True
    before = [line for line in lines[:index] if line.strip()]
    return bool(before) and _normalized(before[-1]).rstrip().endswith(":")


def _without_closing_token(line: str) -> str:
    """`line` without an exact token that closes a finished sentence, or `line` as it is.

    The token must follow punctuation that ends a sentence (`_SENTENCE_ENDS`): ``The token is [SILENT]``,
    ``Answer: [SILENT]`` and ``The marker - [SILENT]`` show the token, and text with code or link marks may too.
    """
    stripped = line.rstrip()
    for token in _EXACT_TOKENS:
        if stripped.endswith(" " + token):
            head = stripped[:-len(token)].rstrip()
            folded = _normalized(head).rstrip()
            closes = folded[-1:] in _SENTENCE_ENDS
            shown = folded.endswith(":") or _LIST_ITEM.match(stripped) is not None
            if closes and not shown and not any(mark in head for mark in _CODE_OR_LINK_MARKS):
                return head
    return line


def without_edge_tokens(text: str) -> str:
    """`text` without the tokens at its edges, as Hermes does for a closing marker: the model
    answered, and the token is not meant for the reader. An opening line counts only for
    ``[SHUTUP]``: ``[SILENT]`` first can be the subject of an answer."""
    lines = text.split("\n")
    filled = [index for index, line in enumerate(lines) if line.strip()]
    if not filled:
        return text
    first, last = filled[0], filled[-1]
    if not _quoted_at(lines, last):
        lines[last] = _without_closing_token(lines[last])
    drop = set()
    if first != last and lines[first].strip() == SHUTUP_TOKEN:
        drop.add(first)
    if first != last and lines[last].strip() in _EXACT_TOKENS and not _quoted_at(lines, last):
        drop.add(last)
    kept = [line for index, line in enumerate(lines) if index not in drop]
    return "\n".join(kept).strip("\n") if drop else "\n".join(kept)


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

    `handled` is True only for a kept turn whose reply is a marker, and the
    caller then adds nothing to it. ``[SHUTUP]`` becomes ``[SILENT]`` (the
    thread muted, the 🫡 scheduled once the mute is written). A silence marker
    is logged and comes back clean: no replacement when Hermes already reads it
    exactly, ``[SILENT]`` when it was wrapped. An answer with a token at its edge
    is not handled and comes back without it. Every other reply is
    ``(False, None)``.
    """
    tick = time.time() if now is None else now
    room = _take_turn(turn_id, tick)
    if room is None or not isinstance(response_text, str):
        return False, None
    marker = reply_marker(response_text)
    answer = without_edge_tokens(response_text)
    if marker is None and answer.strip():
        return False, (answer if answer != response_text else None)
    shutup = marker == SHUTUP_TOKEN
    try:
        if shutup and room.mute(tick):
            _schedule(room.react, room.loop)
        if room.log is not None:
            room.log(marker or SILENT_TOKEN, tick)
    except Exception as exc:  # health: allow BLE001 -- the room allows silence; a failed log, mute or reaction must not send the raw token
        _LOG.info("omh messenger judgement side effect failed: %s", type(exc).__name__)
    if not shutup and _hermes_silence(response_text):
        return True, None
    return True, SILENT_TOKEN

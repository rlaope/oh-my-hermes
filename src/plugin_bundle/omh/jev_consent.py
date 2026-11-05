"""Whether the person asked for Jev in the current turn, recorded from their own words.

`omh_jev_ask` sends data off the machine, so it runs only when the human's
message for THIS turn names Jev. `pre_llm_call` is the one hook that receives
that message, once per turn, before the turn's tool calls; it records a
marker here and the tool reads it. A skill the model loaded on its own, a
bare "yes", or an earlier turn's request is not consent.

The rule is a fail-closed allow-gate on the person's text, not an inference
that stops work: a token equal to `jev`, a token that starts with `jev` and
continues with no Latin letter (`jev로`, `jev's`, `jev-1`), or an `omh-jev-*`
name sets the marker. Tokens split on anything that is not a letter or digit,
so `omh_jev_ask` counts as naming Jev, and a Latin letter after `jev` ends the
match, so `Jevons paradox` and `jevity` do not.

A mention is consent only when nothing in the person's text negates or
refuses anything. The scope is the whole segment the gate reads, not the
clause around the mention: a sentence split cannot see a retraction that
follows in its own sentence ("use jev? no, review this locally"), so any
negation or refusal cue anywhere records "not requested". English cues:
`no`, `not`, `never`, `nope`, `nah`, `none`, `nothing`, `neither`, `nor`,
`without`, `w/o`, `stop`, `avoid`, `skip`, `cancel`, `refuse`, `forget`,
`except`, `exclude`, `instead`, `rather than`, `hold off`, `cannot`, any
`n't` contraction, and the common ones typed without it (`dont`, `wont`),
plus a few common Latin-script ones (`nicht`, `kein`, `ohne`, `pas`, `sans`,
`sin`, `nunca`, `jamais`, `não`, `sem`). Korean cues: `말고`/`말아`/`말라`,
`지 마`/`지 말` (`쓰지마`, `쓰지 말고`, `하지마`), `없` (`없이`, `없어도`), `빼`,
`제외`, `대신`, `그만`, `금지`, `않`, `싫`, `아니`, and `안`/`못` as a negating
adverb (`안 써`, `안써`, `못 써`) but not inside a word (`보안`, `안전`). A
text holding letters of any other script records "not requested" too: the
gate cannot read negation there, and when it cannot tell whether a mention
is affirmative it denies. The cost: an affirmative ask that carries a
negation of its own ("ask jev whether nothing is missing", "claude 말고 jev로
물어봐") or is written in another script is not consent; the person rephrases.

Only an attended platform can set it. `ATTENDED_PLATFORMS` is an allowlist of
the host platform ids where a person types the turn's message; every other id
-- `webhook`, `msgraph_webhook`, `api_server`, `batch`, `cron`, `subagent`, an
empty id, a plugin platform this list has not read -- records "not requested".
A single-query run (`HERMES_SINGLE_QUERY_SESSION=1`, Hermes `oneshot`, which
reaches the hook as platform `cli`) and a process started for a kanban task
(`HERMES_KANBAN_TASK`) are unattended too, as are a host-synthesized notice, a
tracker event, and a delegated child session.

The gate reads only the person's own text. Hermes assembles the user message
from host material and the person's words (`gateway/run_inbound.py`,
`_prepare_inbound_message_text`, read at hermes-agent origin/main 8fb0fc6ae6):

* host blocks prepended before the text, each closed by `]` and a blank line:
  `[Triggering message id: ...]` (Discord), `[Replying to...: "<quoted>"]`, a
  `[The user sent ...]` note per attachment or image, and per voice clip when
  speech-to-text is disabled, fails, or hears nothing;
* a successfully transcribed voice clip, prepended as a bare quoted paragraph
  `"<transcript>"` and a blank line, with no bracketed marker
  (`_transcribe_one_clip`, read at hermes-agent origin/main 16fe260aab);
* channel-history backfill, `<earlier messages>` then a blank line and
  `[New message]` on its own line before the text
  (`_prefix_inbound_sender_context`, on by default on Discord);
* in a shared multi-user session, a `[<display name>] ` sender prefix on the
  text itself;
* adapter-inlined material with no closing boundary: `[Content of <name>]:`
  file text and QQ's `[Quoted message]:` block;
* `@`-reference expansion, appended AFTER the person's text: Hermes runs
  `preprocess_context_references` over the whole assembled message, backfill
  included, and adds `--- Context Warnings ---` (a line per reference, each
  naming the reference) and `--- Attached Context ---` (fetched file, folder,
  git, or page content) on their own lines (`agent/context_references.py`,
  read at hermes-agent origin/main 6b6c7f4a99; the CLI and TUI turns run the
  same expansion). A backfilled `@file:jev...` from an unverified sender, or a
  page the person linked that says "call omh_jev_ask", lands there.

So the person's segment is found by cutting at the first expansion header
line, then after the last backfill separator or, without one, after the last
`]` plus blank line, and it counts only if no host-block opener and no other
bracketed line survives the cut; a message with inlined material records "not
requested" outright, because it cannot be split. The sender prefix is removed
before matching.

An expansion header next to a host block or backfill also records "not
requested" outright. The reply pointer and the Discord trigger note are
prepended AFTER expansion, and a quote keeps the other person's newlines, so
text alone cannot tell a header line spelled inside a quoted or backfilled
message from the host's own; cutting at it would leave the pointer's
opener, and a `]` plus blank line planted in the quote would then pick the
third party's line as the person's. The cost: a reply, or a backfilled turn,
whose own words name Jev next to an `@`-reference is not consent. Every other
step can only remove text, so a wrong cut fails closed.

On a messaging platform only the FIRST line of that segment counts, and a
media turn counts not at all: one whose message or newest user row in
`conversation_history` carries a content part that is not text (a
native-vision turn is an OpenAI-style list with an `image_url` part per image,
`build_native_content_parts` in `agent/image_routing.py`; with observed group
context the hook gets the plain-string persist form and only the history row
is the list), or whose text carries an attachment note (`[The user sent ...`,
`[Image attached ...`). A content list is read by its text parts, never
`str()`-ed.
Hermes merges inbound messages from different senders into the first
sender's event and keeps that sender's `user_id`: the text batcher appends
each chunk after a newline (`_append_text`; its key is the session, and
SimpleX keys it by chat, so a group's per-user session receives the others'
text too), and the busy-session pending slot appends captions and text the
same way (`merge_pending_message_event`, `gateway/platforms/base.py`, read at
hermes-agent origin/main f63c388e1a). A captionless photo takes another
sender's caption whole, so a media event's caption is nobody's certain words.
A voice clip is media too: the pending slot merges another sender's clip into
the owner's event, and its transcript is prepended as the first paragraph, so
a turn whose text opens with a quoted transcript paragraph is a media turn.
The cost is that an owner's "ask jev" on a second line, as a photo caption,
or spoken in a voice clip is not consent on a messaging platform; a terminal
surface has no such merge and keeps every line.

In a shared multi-user session any participant can type "ask jev", so there
consent needs the session's owner: the `sender_id` Hermes passed on the turn
that opened the session. That turn is `is_first_turn` with a history holding
nothing but its own message. A turn-start compaction rotation also arrives as
`is_first_turn` on a new session id, but with the compacted history (the
host's `parent_session_id` there is the delegation parent, not the rotation's
parent, so ownership cannot be carried over); it records no owner, and a
recorded owner is never replaced. A turn from any other sender never sets
the marker, and a shared turn whose owner this process did not see -- a
restart mid-session, a rotated child, an evicted record -- sets none either.
A session is known to be shared when its text carries the sender prefix, or
when a sender other than the recorded owner speaks. Residuals: a shared
session on a platform that supplies no display name, first seen by this
process after a restart, cannot be told from a direct message; and a
participant who opens a fresh session with `/new` (open to every participant
unless the host's `allow_admin_from` is set), or who speaks first after a
`/stop` suspended the session (Hermes starts a fresh session for the next
message, whoever sends it, `gateway/run_turn.py`), owns that session's
consent.

A bot is read as a person. Hermes drops other bots' messages by default and
accepts them when the operator opts in (`DISCORD_ALLOW_BOTS=mentions|all`,
`slack.allow_bots` / `SLACK_ALLOW_BOTS`); the adapter then sets
`SessionSource.is_bot`, and the turn runner passes it on only as
`turn_author.is_bot` to `run_conversation`, which hands it to memory
providers' `on_turn_start` and `sync_turn` (read at hermes-agent origin/main
16fe260aab). `pre_llm_call` receives `sender_id` and no bot flag, and a bot's
id has the same shape as a person's, so this gate cannot tell them apart.
Residual: on a profile that allows bot messages, a bot that relays
third-party text naming Jev -- a CI bot posting a PR title -- consents like
the person it stands in for, and in a per-user session it opened it is the
session's owner. Leave bot messages off on a profile with a Jev route.

Words the owner relays are read as the owner's own: no adapter marks a
forwarded message, and WeCom's quote-only messages and forwarded voice
transcripts reach the hook as plain text from the forwarding sender. A person
who forwards someone else's "ask jev" into their own chat has asked for Jev;
the owner is the one who decides what to forward.

The marker is bound to the turn that recorded it. `pre_llm_call` stores the
turn's `turn_id`; OMH's `pre_tool_call` arms each `omh_jev_ask` call under its
`tool_call_id` with the call's `turn_id`, and `post_tool_call` disarms it; the
tool proceeds only when every armed call runs in the recorded turn. A
background-review fork or a `/btw` side question shares the session id but runs
under its own `turn_id`, so it cannot spend the main turn's consent, and while
its call overlaps the main turn's, neither proceeds: the handler is not told
its own call id, so it cannot tell which arm is its own. Nor does the fork
replace the main turn's marker: `pre_llm_call` records nothing for a turn whose
`parent_session_id` is its own session id. Residual: a host path that runs the
tool without `pre_tool_call` leaves no arm of its own, and would read another
in-flight call's.

Process-local and bounded, like `session_attendance`: nothing about it is
written to disk. Every copy of this module in the process shares the one
state holder, because Hermes can load the bundle twice (#1939).
"""

from __future__ import annotations

import os
import re
import sys
import threading
import types
from collections import OrderedDict
from typing import Any, Final

MAX_TRACKED_SESSIONS: Final = 256
# `jev` at the start of a token, not followed by a Latin letter.
_JEV_TOKEN: Final = re.compile(r"(?<![^\W_])jev(?![a-z])", re.IGNORECASE)
# Negation or refusal anywhere in the person's text voids a Jev mention.
_NEGATION_CUE: Final = re.compile(
    r"\b(?:no|not|never|nope|nah|none|nothing|neither|nor|without|w/o|stop\w*|avoid\w*|skip\w*"
    r"|cancel\w*|refus\w*|forget|except|exclud\w*|instead|rather\s+than|hold\s+off"
    r"|nicht|kein\w*|ohne|pas|sans|sin|nunca|jamais|não|nao|sem"
    r"|cannot|(?:do|does|did|wo|ca|should|would|could|is|are|was|were|have|has|had|must|need)nt"
    r")\b|n['\u2019]t\b"
    r"|말[고아라]|지\s*(?:마|말)|없|빼|제외|대신|그만|금지|않|싫|아니"
    r"|(?<![가-힣])[안못](?:\s|$|(?=[써쓰해하돼되물보불시가갈줘]))",
    re.IGNORECASE,
)
# Letters the negation cues are written for: Latin and Hangul.
_READABLE_LETTER: Final = re.compile(r"[A-Za-z\u00c0-\u024f\u1e00-\u1eff\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f]")

# One process can hold two copies of this module: Hermes' memory-provider
# loader execs the bundle again under `_hermes_user_memory.*`, next to the
# general loader's `hermes_plugins.omh`. The hooks that record and arm stay on
# the general loader's copy, while `omh_jev_ask` is whichever copy registered
# it last, so per-copy state left the tool reading a marker nobody wrote
# (#1939). The state lives in one process-wide holder instead.
_STATE_HOLDER: Final = "_omh_jev_consent_state"


def _shared_state() -> types.SimpleNamespace:
    candidate = types.SimpleNamespace(
        lock=threading.Lock(),
        # session -> (turn_id, requested)
        turn_markers=OrderedDict(),
        # session -> {tool_call_id: turn_id} of each `omh_jev_ask` call
        # between its pre_tool_call and its post_tool_call
        armed_turns=OrderedDict(),
        # session -> sender_id recorded on the session's first turn
        session_owners=OrderedDict(),
    )
    holder = sys.modules.setdefault(_STATE_HOLDER, types.ModuleType(_STATE_HOLDER))
    return holder.__dict__.setdefault("state", candidate)


_state = _shared_state()
_lock = _state.lock
_turn_markers: "OrderedDict[str, tuple[str, bool]]" = _state.turn_markers
_armed_turns: "OrderedDict[str, dict[str, str]]" = _state.armed_turns
# In-flight calls tracked per session; past this the session reads as contested.
MAX_ARMED_CALLS: Final = 32
_session_owners: "OrderedDict[str, str]" = _state.session_owners

# Host platform ids where a person types the turn's message. Read from
# hermes-agent origin/main 8fb0fc6ae6: `Platform` in `gateway/config.py`, the
# bundled adapters under `plugins/platforms/`, and the local surfaces (`cli`,
# `tui` and `desktop` in `run_agent.py`, `acp` in `acp_adapter/session.py`).
# Deliberately absent: `webhook`, `msgraph_webhook`, `api_server` (a program's
# request), `email` (forwarded and quoted mail), `homeassistant` (automations),
# `local`, `relay`, `wecom_callback`, `a2a`, `buzz`, `raft`, `ntfy` (agents or
# publishers, not a person), and `cron`, `subagent`, `batch`, `curator`.
LOCAL_ATTENDED_PLATFORMS: Final = frozenset({"cli", "tui", "desktop", "acp"})
MESSAGING_ATTENDED_PLATFORMS: Final = frozenset(
    {
        "bluebubbles",
        "dingtalk",
        "discord",
        "feishu",
        "google_chat",
        "irc",
        "line",
        "matrix",
        "mattermost",
        "photon",
        "qqbot",
        "signal",
        "simplex",
        "slack",
        "sms",
        "teams",
        "telegram",
        "wecom",
        "weixin",
        "whatsapp",
        "whatsapp_cloud",
        "yuanbao",
    }
)
ATTENDED_PLATFORMS: Final = LOCAL_ATTENDED_PLATFORMS | MESSAGING_ATTENDED_PLATFORMS
KANBAN_TASK_ENV: Final = "HERMES_KANBAN_TASK"
SINGLE_QUERY_ENV: Final = "HERMES_SINGLE_QUERY_SESSION"

# Host blocks closed by `]` and a blank line before the person's text. These
# blocks, the backfill separator and the sender prefix are public because
# `hermes_session_commands.person_request_text` reads the same assembly.
HOST_BLOCK_OPENERS: Final = (
    "[Replying to",
    "[The user sent",
    "[Triggering message id:",
    "[If you need a closer look",
    "[Quoted message]",
)
HOST_BLOCK_END: Final = "]\n\n"
# Notes Hermes writes for an attachment; the pending slot merges any sender's
# caption into such an event (`merge_pending_message_event`).
# `[Image attached at: <path>]` / `[Image attached: <url>]` is the hint
# `build_native_content_parts` (`agent/image_routing.py`) adds to a native-vision
# turn's text part; it is a second layer behind the structural check on the
# message's parts in `_flatten`.
_MEDIA_NOTES: Final = ("[The user sent", "[If you need a closer look", "[Image attached")
# Content-part types that carry text. Any other part -- `image_url`,
# `input_audio`, a type this module has not read -- makes the turn a media turn.
_TEXT_PART_TYPES: Final = frozenset({"text", "input_text"})
# A successful speech-to-text note: the transcript as a bare quoted paragraph,
# prepended before the text (`_transcribe_one_clip`). After a pending-slot
# merge it may be another sender's clip, so it marks a media turn. DOTALL, so
# a transcript that spans lines or quotes its own words still matches.
_TRANSCRIPT_PARAGRAPH: Final = re.compile(r'\A\s*".*"(?:\n\n|\s*\Z)', re.DOTALL)
BACKFILL_SEPARATOR: Final = "\n\n[New message]\n"
# Inlined material with no closing boundary: the generic note that says a
# file's content follows, every adapter's `[Content of <name>]:` header, and
# QQ's `[Quoted message]:` block, whose quoted text runs into the person's.
_UNSPLITTABLE_MARKERS: Final = (
    "Its content has been included below",
    "[Content of ",
    "[Quoted message]",
)
# Headers `agent/context_references.py` appends after the whole assembled
# message when it expands `@file:`/`@url:`/`@folder:`/git references.
_EXPANSION_HEADERS: Final = ("--- Context Warnings ---", "--- Attached Context ---")
# `[<display name>] ` at the start of the person's text in a shared session.
SENDER_PREFIX: Final = re.compile(r"\[[^\]\n]*\] ")


def _flatten(message: object) -> tuple[str, bool]:
    """(the message's text, whether it carries any part that is not text).

    Hermes passes a native-vision turn as an OpenAI-style content list
    (`build_native_content_parts`): a text part, then an `image_url` part per
    image. The text parts are joined by newlines, never `str()`-ed, so the
    list's own brackets cannot pass for a sender prefix. A part this module
    cannot read as text counts as media, and anything that is neither a
    string nor a list of parts has no text at all.
    """
    if message is None:
        return "", False
    if isinstance(message, str):
        return message, False
    if isinstance(message, dict):
        message = [message]
    if not isinstance(message, (list, tuple)):
        return "", True
    texts: list[str] = []
    media = False
    for part in message:
        if isinstance(part, str):
            texts.append(part)
        elif (
            isinstance(part, dict)
            and part.get("type") in _TEXT_PART_TYPES
            and isinstance(part.get("text"), str)
        ):
            texts.append(part["text"])
        else:
            media = True
    return "\n".join(texts), media


def _newest_user_row_has_media(history: object) -> bool:
    """Whether the newest user row of `conversation_history` carries a non-text part.

    With observed group context Hermes hands `pre_llm_call` the plain-string
    persist form of the turn while the API row it appended is the content
    list, so the image is visible only here.
    """
    if not isinstance(history, (list, tuple)):
        return False
    for row in reversed(history):
        if isinstance(row, dict) and row.get("role") == "user":
            return _flatten(row.get("content"))[1]
    return False


def _person_segment(message: object, *, messaging: bool) -> tuple[str, bool]:
    """(the person's own text or "", whether a sender prefix was removed)."""
    text = _flatten(message)[0]
    if any(marker in text for marker in _UNSPLITTABLE_MARKERS):
        return "", False
    # Everything from the first `@`-reference expansion header on is host
    # material: warnings and fetched file or page content. Cut before any
    # other search, so a separator or block end inside fetched text is never
    # taken for the host's.
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if line.strip() in _EXPANSION_HEADERS:
            # The reply pointer and trigger note are prepended AFTER
            # expansion, and backfill precedes the person's text, so a header
            # next to any of them may be a line inside quoted or backfilled
            # material rather than the host's own: fail closed.
            if "[New message]" in text or any(opener in text for opener in HOST_BLOCK_OPENERS):
                return "", False
            text = "\n".join(lines[:index])
            break
    if BACKFILL_SEPARATOR in text:
        text = text.rsplit(BACKFILL_SEPARATOR, 1)[1]
        # A separator spelled inside a quoted block is not the host's: cut
        # after any block end that follows it.
        cut = text.rfind(HOST_BLOCK_END)
        if cut != -1:
            text = text[cut + len(HOST_BLOCK_END):]
    elif any(opener in text for opener in HOST_BLOCK_OPENERS):
        cut = text.rfind(HOST_BLOCK_END)
        if cut == -1:
            return "", False
        text = text[cut + len(HOST_BLOCK_END):]
    if any(opener in text for opener in (*HOST_BLOCK_OPENERS, "[New message]")):
        return "", False
    prefixed = False
    if messaging:
        match = SENDER_PREFIX.match(text)
        if match:
            text = text[match.end():]
            prefixed = True
    if any(line.lstrip().startswith("[") for line in text.splitlines()):
        # A bracketed host block this module does not recognize.
        return "", prefixed
    return text, prefixed


def person_text(message: object, *, messaging: bool = True) -> str:
    """The part of a host-assembled user message the person typed, or ""."""
    return _person_segment(message, messaging=messaging)[0]


def _names_jev_affirmatively(text: str) -> bool:
    """The one consent rule: `text` names Jev, negates nothing, and is in a script the cues read."""
    if not _JEV_TOKEN.search(text):
        return False
    if _NEGATION_CUE.search(text):
        return False
    return all(_READABLE_LETTER.match(char) for char in text if char.isalpha())


def message_requests_jev(message: object, *, messaging: bool = True) -> bool:
    """Whether a person's message names Jev in the sense the gate accepts."""
    return _names_jev_affirmatively(person_text(message, messaging=messaging))


def clear_turn(session_id: object) -> None:
    """Record "not requested" for the session; the hook calls this first on every turn."""
    note_turn(session_id, "")


def _unattended(platform: str, delegated: bool) -> bool:
    return (
        delegated
        or platform not in ATTENDED_PLATFORMS
        or bool(os.environ.get(KANBAN_TASK_ENV))
        or os.environ.get(SINGLE_QUERY_ENV) == "1"
    )


def attended_turn(platform: object, *, delegated: bool = False) -> bool:
    """Whether a person types this turn's messages and is there to answer: the platform rule above
    (`ATTENDED_PLATFORMS`, a single-query run, a kanban task process, a delegated child), for other gates."""
    return not _unattended(str(platform or "").strip().casefold(), delegated)


def _remember(table: "OrderedDict[str, Any]", key: str, value: Any) -> None:
    _ = table.pop(key, None)
    table[key] = value
    while len(table) > MAX_TRACKED_SESSIONS:
        # Oldest first; an evicted session reads as "not requested".
        _ = table.popitem(last=False)


def note_turn(
    session_id: object,
    request_message: object,
    *,
    delegated: bool = False,
    platform: object = "",
    turn_id: object = "",
    sender_id: object = "",
    is_first_turn: bool = False,
    history: object = None,
) -> None:
    """Record this turn's marker for the session, replacing the previous turn's.

    `history` is the hook's `conversation_history`; only a first turn whose
    history is at most its own message opens the session and names its owner.
    """
    key = str(session_id or "").strip()
    if not key:
        return
    platform_id = str(platform or "").strip().casefold()
    turn = str(turn_id or "").strip()
    sender = str(sender_id or "").strip()
    messaging = platform_id in MESSAGING_ATTENDED_PLATFORMS
    opens_session = is_first_turn and isinstance(history, (list, tuple)) and len(history) <= 1
    with _lock:
        if opens_session and sender and key not in _session_owners:
            _remember(_session_owners, key, sender)
        owner = _session_owners.get(key, "")
    requested = False
    if turn and not _unattended(platform_id, delegated):
        text, shared = _person_segment(request_message, messaging=messaging)
        if messaging and (owner or shared):
            # A shared session, or one whose owner is known: only the owner.
            owner_speaks = bool(owner) and sender == owner
        else:
            owner_speaks = True
        if messaging:
            flat, media = _flatten(request_message)
            if (
                media
                or _newest_user_row_has_media(history)
                or any(note in flat for note in _MEDIA_NOTES)
                or _TRANSCRIPT_PARAGRAPH.match(flat)
                or _TRANSCRIPT_PARAGRAPH.match(text)
            ):
                # A media event's caption or transcript may be another
                # sender's, merged whole.
                text = ""
            # Merged chunks from other senders follow a newline; only the
            # first line is certainly the event sender's own.
            text = text.split("\n", 1)[0]
        requested = owner_speaks and _names_jev_affirmatively(text)
    with _lock:
        _remember(_turn_markers, key, (turn, requested))
        _ = _armed_turns.pop(key, None)


def arm_tool_call(session_id: object, turn_id: object, tool_call_id: object = "") -> None:
    """Record the turn an `omh_jev_ask` call is running in; `pre_tool_call` calls this."""
    key = str(session_id or "").strip()
    if not key:
        return
    with _lock:
        arms = dict(_armed_turns.get(key, {}))
        arms[str(tool_call_id or "").strip()] = str(turn_id or "").strip()
        if len(arms) > MAX_ARMED_CALLS:
            # Too many calls in flight to tell apart: no turn matches "".
            arms = {"": ""}
        _remember(_armed_turns, key, arms)


def disarm_tool_call(session_id: object, tool_call_id: object) -> None:
    """Forget a finished `omh_jev_ask` call; `post_tool_call` calls this."""
    key = str(session_id or "").strip()
    call = str(tool_call_id or "").strip()
    if not key or not call:
        return
    with _lock:
        arms = _armed_turns.get(key)
        if arms is not None:
            _ = arms.pop(call, None)


def consent_observed(session_id: object) -> bool:
    """True only when this session's current turn asked for Jev and every call in flight runs in that turn.

    The tool handler receives the session id but not the call's turn id or
    tool call id (Hermes `model_tools._execute_tool` passes `task_id`,
    `session_id`, and `user_task`), so it cannot name its own arm. Each call
    is armed under its `tool_call_id` and disarmed at its `post_tool_call`;
    while calls from two different turns overlap -- a `/btw` fork's call next
    to the main turn's -- neither can tell which arm is its own, so neither
    proceeds.
    """
    key = str(session_id or "").strip()
    if not key:
        return False
    with _lock:
        turn, requested = _turn_markers.get(key, ("", False))
        armed = set(_armed_turns.get(key, {}).values())
    return requested and bool(turn) and armed == {turn}


def reset_turn_markers() -> None:
    """Test seam: forget every recorded turn, arm, and owner."""
    with _lock:
        _turn_markers.clear()
        _armed_turns.clear()
        _session_owners.clear()


__all__ = [
    "ATTENDED_PLATFORMS",
    "LOCAL_ATTENDED_PLATFORMS",
    "MESSAGING_ATTENDED_PLATFORMS",
    "arm_tool_call",
    "clear_turn",
    "consent_observed",
    "disarm_tool_call",
    "message_requests_jev",
    "note_turn",
    "person_text",
    "reset_turn_markers",
]

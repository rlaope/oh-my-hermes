"""Whether a Slack or Discord group message opens a turn at all.

Runs from the `pre_gateway_dispatch` hook, once per inbound message, before
Hermes' auth and before a busy session is steered or interrupted. It never
writes a reply and never changes the bot's voice; it only answers "skip" or
nothing (Hermes then dispatches as usual). Anything unexpected fails open.

Order, per message in a Slack or Discord group, channel or thread chat:

1. Quiet: the whole message, once the bot's own mention or call by name is
   removed, is a quiet word (`messenger_gate_words`), and it is aimed at the
   bot: the bot is mentioned, called by name, or replied to, or the message is
   in a thread. The thread is muted, the message gets a 🫡 reaction (no text),
   and it is skipped.
2. Addressed to the bot: a real mention of the bot, a reply to the bot's own
   message, Hermes' `reply_expected is True`, or a call by one of the bot's
   names at the start or end. Unmutes the thread and passes.
3. Muted thread: skipped.
4. Not for the bot (`on` only): R1, the message opens with a real mention of
   someone else; R2, it calls someone else by name at its start or end (a
   trailing real mention counts), and nothing in it names the bot or says
   "you". Skipped; never mutes.

Every skip is written to a bounded log so a wrong skip can be found. Mutes have
no expiry. Records live in ``<omh_home>/runtime/messenger_gate.json``.

Profile settings, under ``plugins.entries.omh.settings`` in config.yaml:
``messenger_gate`` (``on`` default, ``mute_only``, ``off``),
``messenger_self_names`` and ``messenger_other_names`` (comma-separated).
"""

from __future__ import annotations

import inspect
import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, NamedTuple

from . import runtime_paths
from .awareness_delivery import _awareness_delivery_lock, _write_delivery_record
from .messenger_gate_words import LANGUAGES

GATE_SETTING = "messenger_gate"
SELF_NAMES_SETTING = "messenger_self_names"
OTHER_NAMES_SETTING = "messenger_other_names"
GATE_MODES = ("on", "mute_only", "off")
DEFAULT_GATE_MODE = "on"
GATED_PLATFORMS = frozenset({"slack", "discord"})
STATE_FILE = "messenger_gate.json"
STATE_SCHEMA_VERSION = 1
SKIP_LOG_LIMIT = 200
SKIP_TEXT_CHARS = 120
SLACK_ACK_EMOJI = "saluting_face"
DISCORD_ACK_EMOJI = "\U0001fae1"

REASON_QUIET = "omh_messenger_quiet"
REASON_MUTED = "omh_messenger_muted_thread"
REASON_OTHER_MENTION = "omh_messenger_addressed_to_other_mention"
REASON_OTHER_NAME = "omh_messenger_addressed_to_other_name"

_MENTION = re.compile(r"<@!?([A-Za-z0-9]+)(?:\|[^>]*)?>")
_QUOTE_OPENERS = frozenset("\"'“”‘’「『«„>")
_OFF_SPELLINGS = frozenset({"off", "false", "no"})


class Message(NamedTuple):
    """What the decision reads from one inbound event; built by `message_from_event`."""

    text: str
    raw_text: str = ""
    self_ids: frozenset[str] = frozenset()
    self_names: tuple[str, ...] = ()
    other_names: tuple[str, ...] = ()
    reply_to_own: bool = False
    reply_expected: bool | None = None
    in_thread: bool = False


# --- text folding -------------------------------------------------------------


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _dropped(character: str) -> bool:
    """Punctuation, symbols (emoji included) and control/format characters."""
    return unicodedata.category(character)[0] in "PSC"


def _boundary(character: str) -> bool:
    return character.isspace() or _dropped(character)


def compact(text: str) -> str:
    """`text` folded, with punctuation, symbols, emoji and every space removed."""
    return "".join(c for c in _fold(text) if not (c.isspace() or _dropped(c)))


def _words(folded: str) -> list[str]:
    return "".join(" " if _boundary(c) else c for c in folded).split()


def _trim(folded: str) -> str:
    start, end = 0, len(folded)
    while start < end and folded[start].isspace():
        start += 1
    while end > start and _boundary(folded[end - 1]):
        end -= 1
    return folded[start:end]


_QUIET = frozenset(compact(word) for language in LANGUAGES for word in language.quiet)
_SUFFIXES = tuple(sorted({_fold(s) for lang in LANGUAGES for s in lang.vocative_suffixes}, key=len, reverse=True))
_PREFIXES = tuple(sorted({_fold(p) for lang in LANGUAGES for p in lang.vocative_prefixes}, key=len, reverse=True))
_YOU_TOKENS = frozenset(_fold(t) for lang in LANGUAGES for t in lang.second_person_tokens)
_YOU_SUBSTRINGS = tuple(_fold(s) for lang in LANGUAGES for s in lang.second_person_substrings)


# --- calls by name --------------------------------------------------------------


def _ends_call(rest: str, *, bare_needs_mark: bool) -> int | None:
    """Length of a call's tail in `rest` (what follows a name), or None.

    A suffix (`야`, `さん`, ` ơi`) must itself be followed by a boundary or the
    end. With no suffix, the name must end the message or be followed by
    punctuation; a bare space is not enough when `bare_needs_mark` (``alex
    said`` is about alex, ``alex, look`` calls alex).
    """
    for suffix in _SUFFIXES:
        if rest.startswith(suffix):
            after = rest[len(suffix):]
            if not after or _boundary(after[0]):
                return len(suffix)
    if not rest:
        return 0
    if _dropped(rest[0]) and rest[0] != "@":
        return 0
    if rest[0].isspace() and not bare_needs_mark:
        return 0
    return None


def leading_call(folded: str, names: tuple[str, ...]) -> int:
    """End index of a call by one of `names` that opens `folded`; 0 when none."""
    text = folded.lstrip()
    offset = len(folded) - len(text)
    for name in names:
        if text.startswith("@" + name):
            rest = text[len(name) + 1:]
            if not rest or _boundary(rest[0]):
                return offset + len(name) + 1
            tail = _ends_call(rest, bare_needs_mark=False)
            if tail is not None:
                return offset + len(name) + 1 + tail
        for prefix in _PREFIXES:
            if text.startswith(prefix + " ") and text[len(prefix) + 1:].lstrip().startswith(name):
                start = len(text) - len(text[len(prefix) + 1:].lstrip())
                rest = text[start + len(name):]
                if not rest or _boundary(rest[0]):
                    return offset + start + len(name)
        if text.startswith(name):
            tail = _ends_call(text[len(name):], bare_needs_mark=True)
            if tail is not None:
                return offset + len(name) + tail
    return 0


def trailing_call(folded: str, names: tuple[str, ...]) -> int:
    """Start index of a call by one of `names` that closes `folded`; -1 when none."""
    text = _trim(folded)
    for name in names:
        if text.endswith("@" + name):
            start = len(text) - len(name) - 1
            if start == 0 or _boundary(text[start - 1]):
                return start
        for suffix in ("", *_SUFFIXES):
            if not text.endswith(name + suffix):
                continue
            start = len(text) - len(name) - len(suffix)
            before = text[:start]
            if before and not _boundary(before[-1]):
                continue
            if suffix or not before.strip() or _dropped(before.rstrip()[-1]):
                return start
    return -1


def _says_you(folded: str) -> bool:
    if any(word in _YOU_TOKENS for word in _words(folded)):
        return True
    return any(fragment in folded for fragment in _YOU_SUBSTRINGS)


# --- the decision ---------------------------------------------------------------


class Decision(NamedTuple):
    action: str  # "allow", "unmute", "mute", "skip"
    reason: str = ""


def decide(message: Message, *, muted: bool, mode: str = DEFAULT_GATE_MODE) -> Decision:
    """The gate's answer for one group message. Pure: no I/O."""
    folded = _fold(message.text)
    mention_ids = _MENTION.findall(message.raw_text)
    self_names = tuple(n for n in (_fold(n).strip() for n in message.self_names) if n)
    other_names = tuple(
        n for n in (_fold(n).strip() for n in message.other_names) if n and n not in self_names
    )
    self_mentioned = any(i in message.self_ids for i in mention_ids)
    for self_id in message.self_ids:
        folded = folded.replace(f"<@{self_id.casefold()}>", " ").replace(f"<@!{self_id.casefold()}>", " ")
    lead = leading_call(folded, self_names)
    tail = trailing_call(folded[lead:], self_names)
    called = bool(lead) or tail >= 0
    body = _trim(folded[lead:]) if tail < 0 else _trim(_trim(folded[lead:])[:tail])
    addressed = (
        self_mentioned or called or message.reply_to_own or message.reply_expected is True
    )
    if (
        body
        and body[0] not in _QUOTE_OPENERS
        and not body.startswith("&gt;")
        and compact(body) in _QUIET
        and (addressed or message.in_thread)
    ):
        return Decision("mute", REASON_QUIET)
    if addressed:
        return Decision("unmute")
    if muted:
        return Decision("skip", REASON_MUTED)
    if mode != "on":
        return Decision("allow")
    raw = message.raw_text.lstrip()
    lead_mention = _MENTION.match(raw)
    if message.self_ids and lead_mention and lead_mention.group(1) not in message.self_ids:
        return Decision("skip", REASON_OTHER_MENTION)
    if any(name in folded for name in self_names) or _says_you(folded):
        return Decision("allow")
    trail_mention = re.search(r"<@!?([A-Za-z0-9]+)(?:\|[^>]*)?>\W*$", message.raw_text)
    if message.self_ids and trail_mention and trail_mention.group(1) not in message.self_ids:
        return Decision("skip", REASON_OTHER_NAME)
    if other_names and (leading_call(folded, other_names) or trailing_call(folded, other_names) >= 0):
        return Decision("skip", REASON_OTHER_NAME)
    return Decision("allow")


# --- settings ---------------------------------------------------------------------


def read_settings(hermes_home: Path | None) -> dict[str, Any]:
    """The gate mode and configured names; defaults when the config is absent or unreadable."""
    settings: dict[str, Any] = {"mode": DEFAULT_GATE_MODE, "self_names": (), "other_names": ()}
    if hermes_home is None:
        return settings
    try:
        text = (Path(hermes_home).expanduser() / "config.yaml").read_text(encoding="utf-8")
        mode = runtime_paths.plugin_setting_text(text, GATE_SETTING)
        self_names = runtime_paths.plugin_setting_text(text, SELF_NAMES_SETTING)
        other_names = runtime_paths.plugin_setting_text(text, OTHER_NAMES_SETTING)
    except (OSError, ValueError, runtime_paths.RuntimeBindingError):
        return settings
    if mode is not None:
        spelled = mode.strip().lower()
        settings["mode"] = "off" if spelled in _OFF_SPELLINGS else spelled if spelled in GATE_MODES else DEFAULT_GATE_MODE
    settings["self_names"] = _name_list(self_names)
    settings["other_names"] = _name_list(other_names)
    return settings


def _name_list(value: str | None) -> tuple[str, ...]:
    return tuple(part.strip() for part in (value or "").split(",") if part.strip())


# --- state ------------------------------------------------------------------------


def state_path(omh_home: Path) -> Path:
    return Path(omh_home) / "runtime" / STATE_FILE


def read_state(omh_home: Path) -> dict[str, Any]:
    """Mutes and the skip log; an empty state for an absent or unreadable file."""
    try:
        data = json.loads(state_path(omh_home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or data.get("schema_version") != STATE_SCHEMA_VERSION:
        data = {}
    mutes = data.get("mutes")
    skips = data.get("skips")
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "mutes": mutes if isinstance(mutes, dict) else {},
        "skips": skips if isinstance(skips, list) else [],
    }


def update_state(omh_home: Path, *, mute: tuple[str, dict[str, Any]] | None = None,
                 unmute: str | None = None, skip: dict[str, Any] | None = None) -> bool:
    """Apply one change under the sidecar lock with an atomic replace; False when it could not be written."""
    path = state_path(omh_home)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _awareness_delivery_lock(path):
            state = read_state(omh_home)
            if mute is not None:
                state["mutes"][mute[0]] = mute[1]
            if unmute is not None:
                if unmute not in state["mutes"]:
                    return True
                del state["mutes"][unmute]
            if skip is not None:
                state["skips"] = [*state["skips"], skip][-SKIP_LOG_LIMIT:]
            _write_delivery_record(path, state)
    except (OSError, ValueError, TypeError):
        return False
    return True


def thread_key(profile: str, platform: str, chat_id: str, thread_id: str) -> str:
    return "/".join((profile or "default", platform, chat_id, thread_id))


# --- event reading ------------------------------------------------------------------


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _adapter(gateway: object, source: object) -> object:
    finder = getattr(gateway, "_adapter_for_source", None)
    if callable(finder):
        try:
            found = finder(source)
        except (AttributeError, LookupError, TypeError, ValueError):
            found = None
        if found is not None:
            return found
    adapters = getattr(gateway, "adapters", None)
    if isinstance(adapters, dict):
        return adapters.get(getattr(source, "platform", None))
    return None


def _identity(platform: str, adapter: object, raw: object) -> tuple[set[str], list[str]]:
    """The bot's own user ids and display names, from the adapter and the raw message."""
    ids: set[str] = set()
    names: list[str] = []
    if platform == "slack":
        team = raw.get("team") if isinstance(raw, dict) else None
        team_ids = getattr(adapter, "_team_bot_user_ids", None)
        team_names = getattr(adapter, "_team_bot_names", None)
        # Every workspace's bot id: an event without its team still knows the bot's own mention.
        ids.update(_text(value) for value in (team_ids.values() if isinstance(team_ids, dict) else ()))
        ids.add(_text(getattr(adapter, "_bot_user_id", None)))
        names.append(_text(team_names.get(team)) if isinstance(team_names, dict) else "")
        names.append(_text(getattr(adapter, "_bot_display_name", None)))
    else:
        members = [getattr(getattr(adapter, "_client", None), "user", None),
                   getattr(getattr(raw, "guild", None), "me", None)]
        for member in members:
            if member is None:
                continue
            if getattr(member, "id", None) is not None:
                ids.add(str(member.id))
            for attribute in ("name", "display_name", "global_name", "nick"):
                if isinstance(getattr(member, attribute, None), str):
                    names.append(getattr(member, attribute))
    return {i for i in ids if i}, [n for n in names if n and n != "unknown"]


def _raw_text(platform: str, raw: object) -> str:
    if platform == "slack":
        return _text(raw.get("text")) if isinstance(raw, dict) else ""
    return _text(getattr(raw, "content", None))


def _discord_reply_to_own(raw: object, self_ids: set[str]) -> bool:
    resolved = getattr(getattr(raw, "reference", None), "resolved", None)
    author_id = getattr(getattr(resolved, "author", None), "id", None)
    return author_id is not None and str(author_id) in self_ids


def message_from_event(event: object, adapter: object, settings: dict[str, Any]) -> Message:
    source = getattr(event, "source", None)
    platform = _platform(source)
    raw = getattr(event, "raw_message", None)
    self_ids, adapter_names = _identity(platform, adapter, raw)
    reply_to_own = getattr(event, "reply_to_is_own_message", False) is True
    if platform == "discord" and not reply_to_own:
        reply_to_own = _discord_reply_to_own(raw, self_ids)
    reply_expected = getattr(event, "reply_expected", None)
    return Message(
        text=_text(getattr(event, "text", None)),
        raw_text=_raw_text(platform, raw),
        self_ids=frozenset(self_ids),
        self_names=tuple(dict.fromkeys([*adapter_names, *settings["self_names"]])),
        other_names=tuple(settings["other_names"]),
        reply_to_own=reply_to_own,
        reply_expected=reply_expected if isinstance(reply_expected, bool) else None,
        in_thread=bool(getattr(source, "thread_id", None)) or getattr(source, "chat_type", "") == "thread",
    )


def _platform(source: object) -> str:
    platform = getattr(source, "platform", None)
    return str(getattr(platform, "value", platform) or "").lower()


def gated(event: object) -> bool:
    """Whether the gate looks at this event at all."""
    source = getattr(event, "source", None)
    if source is None or getattr(event, "internal", False) is True:
        return False
    if _platform(source) not in GATED_PLATFORMS:
        return False
    if getattr(source, "chat_type", "dm") not in {"group", "channel", "thread"}:
        return False
    return not _text(getattr(event, "text", None)).lstrip().startswith("/")


# --- the 🫡 acknowledgement ------------------------------------------------------------


def ack_call(adapter: object, event: object, platform: str) -> object | None:
    """The pending 🫡 reaction on the quiet message, for the hook to await; None when there is none.

    Uses the adapter's private ``_add_reaction`` (Hermes has no public
    reaction API for plugins). A missing or failing method loses only the
    reaction; the skip stands either way.
    """
    react = getattr(adapter, "_add_reaction", None)
    if not callable(react):
        return None
    raw = getattr(event, "raw_message", None)
    try:
        if platform == "slack":
            team = raw.get("team", "") if isinstance(raw, dict) else ""
            chat_id = getattr(getattr(event, "source", None), "chat_id", "")
            pending = react(chat_id, getattr(event, "message_id", None), SLACK_ACK_EMOJI, team or "")
        else:
            pending = react(raw, DISCORD_ACK_EMOJI)
    except (AttributeError, LookupError, OSError, RuntimeError, TypeError, ValueError):
        return None
    return pending if inspect.isawaitable(pending) else None


# --- the hook body -------------------------------------------------------------------


def gate_event(event: object, gateway: object, *, hermes_home: Path | None, omh_home: Path,
               now: float | None = None) -> tuple[dict[str, str] | None, object | None]:
    """The `pre_gateway_dispatch` answer for `event` and the 🫡 reaction to await, if any.

    The answer is a skip dict, or None to let Hermes dispatch.
    """
    if not gated(event):
        return None, None
    settings = read_settings(hermes_home)
    if settings["mode"] == "off":
        return None, None
    source = getattr(event, "source", None)
    platform = _platform(source)
    adapter = _adapter(gateway, source)
    message = message_from_event(event, adapter, settings)
    key = thread_key(
        _text(getattr(source, "profile", None)), platform,
        str(getattr(source, "chat_id", "") or ""), str(getattr(source, "thread_id", "") or ""),
    )
    state = read_state(omh_home)
    decision = decide(message, muted=key in state["mutes"], mode=settings["mode"])
    tick = float(now if now is not None else time.time())
    if decision.action == "allow":
        return None, None
    if decision.action == "unmute":
        if key in state["mutes"]:
            update_state(omh_home, unmute=key)
        return None, None
    entry = {
        "ts": tick, "reason": decision.reason, "key": key,
        "text": message.text[:SKIP_TEXT_CHARS], "user_id": str(getattr(source, "user_id", "") or ""),
    }
    skip = {"action": "skip", "reason": decision.reason}
    if decision.action == "mute":
        update_state(omh_home, mute=(key, {"muted_ts": tick, "by": entry["user_id"]}), skip=entry)
        return skip, ack_call(adapter, event, platform)
    update_state(omh_home, skip=entry)
    return skip, None

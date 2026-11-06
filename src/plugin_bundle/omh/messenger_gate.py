"""Whether a Slack or Discord group message opens a turn at all.

Runs from the `pre_gateway_dispatch` hook, once per inbound message, before
Hermes' auth and before a busy session is steered or interrupted. It never
writes a reply and never changes the bot's voice; it only answers "skip" or
nothing (Hermes then dispatches as usual). Anything unexpected fails open.

Order, per message in a Slack or Discord group, channel or thread chat:

1. Quiet: the whole message, once the bot's own mention or call by name is
   removed, is a quiet word (`messenger_gate_words`), not a question or
   formatted text, and it is aimed at the bot: the bot is mentioned, called by
   name, or replied to, or the message is a reply inside a thread (an ordinary
   single word such as `silence` needs the mention, name or reply). The
   thread is muted, the message gets a 🫡 reaction (no text), and it is
   skipped. A Slack top-level message is not inside a thread; a mute it sets
   covers only the thread that message opens.
2. Addressed to the bot: a real mention of the bot, a reply to the bot's own
   message, Hermes' `reply_expected is True`, or a call by one of the bot's
   names at the start or end. Unmutes the thread and passes.
3. Muted thread: skipped.
4. Not for the bot (`on` only): R1, the message opens with a real mention of
   someone else; R2, it calls a configured other name at its start, or at its
   end after punctuation, and nothing in it names the bot or says "you".
   Skipped; never mutes.

In a judged room (`messenger_judgement`: Hermes lets a silence marker stand
there and streaming is off) the model is the judge instead: steps 1 and R2
are off, the message opens a turn, and the turn is told to answer
``[SHUTUP]`` to be quiet or ``[SILENT]`` when it is not for the bot. Steps 2,
3 and R1 stand.

Only senders Hermes authorizes are gated. Every skip is appended to a bounded
log so a wrong skip can be found. Mutes have no expiry. Records live in the
owning profile's OMH home: ``runtime/messenger_gate.json`` (mutes) and
``runtime/messenger_gate_skips.jsonl`` (skips).

Profile settings, under ``plugins.entries.omh.settings`` in config.yaml:
``messenger_gate`` (``on`` default, ``mute_only``, ``off``),
``messenger_self_names`` and ``messenger_other_names`` (comma-separated or a
YAML flow list; a block list is not read).
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
from .messenger_judgement import Room, gateway_loop, judged_room, note_room

GATE_SETTING = "messenger_gate"
SELF_NAMES_SETTING = "messenger_self_names"
OTHER_NAMES_SETTING = "messenger_other_names"
GATE_MODES = ("on", "mute_only", "off")
DEFAULT_GATE_MODE = "on"
GATED_PLATFORMS = frozenset({"slack", "discord"})
STATE_FILE = "messenger_gate.json"
SKIP_LOG_FILE = "messenger_gate_skips.jsonl"
STATE_SCHEMA_VERSION = 1
MUTE_LIMIT = 1000
SKIP_LOG_LIMIT = 200
SKIP_LOG_TRIM_BYTES = 256 * 1024
# A mute must not be dropped because another writer held the lock for a moment;
# the shared 0.1 s default lost mutes under contention. The skip log keeps it.
MUTE_LOCK_SECONDS = 2.0
SKIP_TEXT_CHARS = 120
SLACK_ACK_EMOJI = "saluting_face"
DISCORD_ACK_EMOJI = "\U0001fae1"

REASON_QUIET = "omh_messenger_quiet"
REASON_MUTED = "omh_messenger_muted_thread"
REASON_OTHER_MENTION = "omh_messenger_addressed_to_other_mention"
REASON_OTHER_NAME = "omh_messenger_addressed_to_other_name"

_MENTION = re.compile(r"<@!?([A-Za-z0-9]+)(?:\|[^>]*)?>")
_QUOTE_OPENERS = frozenset("\"'“”‘’「『«„>")
# After NFKC folding (`？` is `?`): the marks that make a closing run a question.
_QUESTION_MARKS = frozenset("?‽¿")
_OFF_SPELLINGS = frozenset({"off", "false", "no"})
_GROUP_CHAT_TYPES = frozenset({"group", "channel", "thread"})


class Message(NamedTuple):
    """What the decision reads from one inbound event; built by `message_from_event`."""

    text: str
    raw_text: str = ""
    self_ids: frozenset[str] = frozenset()
    self_mentioned: bool = False
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
_QUIET_NEEDS_ADDRESS = frozenset(compact(w) for language in LANGUAGES for w in language.quiet_needs_address)
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
            # `민수야` closing a sentence is often the copula ("it's Minsu"), not a call:
            # a trailing call needs the whole message or punctuation before the name.
            if not before.strip() or _dropped(before.rstrip()[-1]):
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


def decide(message: Message, *, muted: bool, mode: str = DEFAULT_GATE_MODE, judged: bool = False) -> Decision:
    """The gate's answer for one group message. Pure: no I/O.

    `judged`: the model judges this room, so the quiet words and calls by
    other names (R2) are left to it.
    """
    folded = _fold(message.text)
    mention_ids = _MENTION.findall(message.raw_text)
    self_names = tuple(n for n in (_fold(n).strip() for n in message.self_names) if n)
    other_names = tuple(
        n for n in (_fold(n).strip() for n in message.other_names) if n and n not in self_names
    )
    self_mentioned = message.self_mentioned or any(i in message.self_ids for i in mention_ids)
    for self_id in message.self_ids:
        folded = folded.replace(f"<@{self_id.casefold()}>", " ").replace(f"<@!{self_id.casefold()}>", " ")
    lead = leading_call(folded, self_names)
    tail = trailing_call(folded[lead:], self_names)
    called = bool(lead) or tail >= 0
    region = folded[lead:].strip() if tail < 0 else _trim(folded[lead:])[:tail].strip()
    body = _trim(region)
    addressed = (
        self_mentioned or called or message.reply_to_own or message.reply_expected is True
    )
    word = compact(body)
    if (
        not judged
        and word in _QUIET
        and body[0] not in _QUOTE_OPENERS
        and not body.startswith("&gt;")
        # a question mark anywhere in the closing punctuation run (`?!`, `!?`, folded `？`, `‽`, `¿`) asks, not orders.
        and not any(mark in _QUESTION_MARKS for mark in region[len(body):])
        and not region.startswith(("~", "`"))
        and (addressed or (message.in_thread and word not in _QUIET_NEEDS_ADDRESS))
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
    if not judged and other_names and (leading_call(folded, other_names) or trailing_call(folded, other_names) >= 0):
        return Decision("skip", REASON_OTHER_NAME)
    return Decision("allow")


# --- settings ---------------------------------------------------------------------

_SETTINGS_CACHE: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}


def read_settings(hermes_home: Path | None) -> dict[str, Any]:
    """The gate mode, configured names and the profile's `omh_home` setting.

    Defaults when the config is absent or unreadable. Cached by the config's
    mtime and size, so the hot path stats one file per message.
    """
    settings: dict[str, Any] = {"mode": DEFAULT_GATE_MODE, "self_names": (), "other_names": (), "omh_home": None}
    if hermes_home is None:
        return settings
    path = Path(hermes_home).expanduser() / "config.yaml"
    try:
        stat = path.stat()
    except OSError:
        return settings
    stamp = (stat.st_mtime_ns, stat.st_size)
    cached = _SETTINGS_CACHE.get(str(path))
    if cached is not None and cached[0] == stamp:
        return dict(cached[1])
    try:
        text = path.read_text(encoding="utf-8")
        mode = runtime_paths.plugin_setting_text(text, GATE_SETTING)
        self_names = runtime_paths.plugin_setting_text(text, SELF_NAMES_SETTING)
        other_names = runtime_paths.plugin_setting_text(text, OTHER_NAMES_SETTING)
        omh_home = runtime_paths.plugin_setting_text(text, "omh_home")
    except (OSError, ValueError, runtime_paths.RuntimeBindingError):
        return settings
    if mode is not None:
        spelled = mode.strip().lower()
        settings["mode"] = "off" if spelled in _OFF_SPELLINGS else spelled if spelled in GATE_MODES else DEFAULT_GATE_MODE
    settings["self_names"] = _name_list(self_names)
    settings["other_names"] = _name_list(other_names)
    settings["omh_home"] = omh_home
    _SETTINGS_CACHE[str(path)] = (stamp, dict(settings))
    return settings


def _name_list(value: str | None) -> tuple[str, ...]:
    """Names from `a, b` or a YAML flow list `[a, "b"]`."""
    text = (value or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return tuple(part.strip().strip("\"'").strip() for part in text.split(",") if part.strip().strip("\"'").strip())


# --- state ------------------------------------------------------------------------


def state_path(omh_home: Path) -> Path:
    return Path(omh_home) / "runtime" / STATE_FILE


def skip_log_path(omh_home: Path) -> Path:
    return Path(omh_home) / "runtime" / SKIP_LOG_FILE


def read_mutes(omh_home: Path) -> dict[str, Any]:
    """Muted threads by key; empty for an absent or unreadable file."""
    try:
        data = json.loads(state_path(omh_home).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("schema_version") != STATE_SCHEMA_VERSION:
        return {}
    mutes = data.get("mutes")
    return mutes if isinstance(mutes, dict) else {}


def write_mute(omh_home: Path, key: str, record: dict[str, Any] | None) -> bool:
    """Set (`record`) or clear (None) one mute under the sidecar lock; False when it could not be written.

    The map keeps the `MUTE_LIMIT` newest mutes.
    """
    path = state_path(omh_home)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _awareness_delivery_lock(path, timeout_seconds=MUTE_LOCK_SECONDS):
            mutes = read_mutes(omh_home)
            if record is None:
                if key not in mutes:
                    return True
                del mutes[key]
            else:
                mutes[key] = record
                if len(mutes) > MUTE_LIMIT:
                    newest = sorted(mutes.items(), key=lambda item: _stamp(item[1]), reverse=True)[:MUTE_LIMIT]
                    mutes = dict(newest)
            _write_delivery_record(path, {"schema_version": STATE_SCHEMA_VERSION, "mutes": mutes})
    except (OSError, ValueError, TypeError):
        return False
    return True


def _stamp(record: object) -> float:
    value = record.get("muted_ts") if isinstance(record, dict) else None
    return float(value) if isinstance(value, (int, float)) else 0.0


def append_skip(omh_home: Path, entry: dict[str, Any]) -> bool:
    """Append one skip as a JSON line; trim to the last `SKIP_LOG_LIMIT` once the file passes `SKIP_LOG_TRIM_BYTES`."""
    path = skip_log_path(omh_home)
    line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _awareness_delivery_lock(path):
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
            if path.stat().st_size > SKIP_LOG_TRIM_BYTES:
                kept = path.read_text(encoding="utf-8").splitlines()[-SKIP_LOG_LIMIT:]
                tmp = path.with_name(f".{path.name}.tmp")
                tmp.write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")
                tmp.replace(path)
    except (OSError, ValueError, TypeError):
        return False
    return True


def read_skips(omh_home: Path) -> list[dict[str, Any]]:
    try:
        lines = skip_log_path(omh_home).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries = []
    for line in lines[-SKIP_LOG_LIMIT:]:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def thread_key(profile: str, platform: str, chat_id: str, thread_id: str) -> str:
    return "/".join((profile or "default", platform, chat_id, thread_id))


_SESSION_ROOM_VARS = ("_SESSION_PROFILE", "_SESSION_PLATFORM", "_SESSION_CHAT_ID", "_SESSION_THREAD_ID",
                      "_SESSION_CHAT_TYPE")


def session_room_key() -> str:
    """`thread_key` of the gated room the current turn serves, from Hermes' session ContextVars; "" for none.

    The gateway binds these from the turn's source before the agent runs, so
    they name the same profile, chat and thread `gate_event` keyed at ingress.
    Never `get_session_env`: its environment fallback can alias another turn.
    """
    try:
        from gateway import session_context

        values = [getattr(session_context, name).get() for name in _SESSION_ROOM_VARS]
    except (ImportError, AttributeError, LookupError):
        return ""
    profile, platform, chat_id, thread_id, chat_type = (v if isinstance(v, str) else "" for v in values)
    platform = platform.lower()
    if platform not in GATED_PLATFORMS or chat_type not in _GROUP_CHAT_TYPES or not chat_id:
        return ""
    return thread_key(profile, platform, chat_id, thread_id)


# --- homes ----------------------------------------------------------------------------


def hermes_home_for(source: object) -> Path | None:
    """The Hermes home of the profile that owns `source`.

    A named profile resolves through Hermes' own profile table. Otherwise the
    active home; at a multiplexed gateway's ingress no profile scope is bound
    yet, so the launch home (what `get_hermes_home()` returns without an
    override) stands in for it.
    """
    profile = getattr(source, "profile", None)
    if isinstance(profile, str) and profile and profile != "default":
        try:
            from hermes_cli.profiles import get_profile_dir, profile_exists
        except ImportError:
            pass
        else:
            if profile_exists(profile):
                return Path(get_profile_dir(profile))
    try:
        return runtime_paths.default_hermes_home()
    except runtime_paths.UnattributableSessionError:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home())


def omh_home_for(hermes_home: Path, settings: dict[str, Any]) -> Path:
    """The OMH home for that profile: its `omh_home` setting, the bound home, or `~/.omh`."""
    configured = settings.get("omh_home")
    if isinstance(configured, str) and configured.strip():
        return runtime_paths.expand_path(configured, hermes_home=hermes_home, relative_to=hermes_home)
    try:
        omh_home, bound_hermes = runtime_paths.resolve_homes()
    except runtime_paths.RuntimeBindingError:
        return runtime_paths.unset_launch_omh_home(hermes_home)
    if bound_hermes == hermes_home:
        return omh_home
    return runtime_paths.unset_launch_omh_home(hermes_home)


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


def _authorized(gateway: object, source: object) -> bool:
    """Hermes' own sender check, when the gateway offers one; the gate acts only for authorized senders."""
    check = getattr(gateway, "_is_user_authorized_for_source", None)
    if not callable(check):
        return True
    try:
        return check(source) is not False
    except (AttributeError, LookupError, OSError, TypeError, ValueError):
        return False


def _slack_team(source: object, raw: object) -> str:
    return _text(getattr(source, "scope_id", None)) or (_text(raw.get("team")) if isinstance(raw, dict) else "")


def _identity(platform: str, adapter: object, source: object, raw: object) -> tuple[set[str], list[str]]:
    """The bot's own user ids and display names, from the adapter and the raw message."""
    ids: set[str] = set()
    names: list[str] = []
    if platform == "slack":
        team = _slack_team(source, raw)
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


def _discord_self_mentioned(raw: object, self_ids: set[str]) -> bool:
    """Hermes strips the bot's own `<@id>` from Discord content; `message.mentions` still holds it."""
    mentions = getattr(raw, "mentions", None)
    if not isinstance(mentions, (list, tuple)):
        return False
    return any(str(getattr(member, "id", "")) in self_ids for member in mentions)


def _in_thread(platform: str, event: object, source: object) -> bool:
    thread_id = _text(str(getattr(source, "thread_id", "") or ""))
    if getattr(source, "chat_type", "") == "thread":
        return True
    # A Slack top-level message carries its own ts as thread_id (replies go into its thread).
    return bool(thread_id) and not (platform == "slack" and thread_id == str(getattr(event, "message_id", "") or ""))


def message_from_event(event: object, adapter: object, settings: dict[str, Any]) -> Message:
    source = getattr(event, "source", None)
    platform = _platform(source)
    raw = getattr(event, "raw_message", None)
    self_ids, adapter_names = _identity(platform, adapter, source, raw)
    reply_to_own = getattr(event, "reply_to_is_own_message", False) is True
    self_mentioned = False
    if platform == "discord":
        reply_to_own = reply_to_own or _discord_reply_to_own(raw, self_ids)
        self_mentioned = _discord_self_mentioned(raw, self_ids)
    reply_expected = getattr(event, "reply_expected", None)
    return Message(
        text=_text(getattr(event, "text", None)),
        raw_text=_raw_text(platform, raw),
        self_ids=frozenset(self_ids),
        self_mentioned=self_mentioned,
        self_names=tuple(dict.fromkeys([*adapter_names, *settings["self_names"]])),
        other_names=tuple(settings["other_names"]),
        reply_to_own=reply_to_own,
        reply_expected=reply_expected if isinstance(reply_expected, bool) else None,
        in_thread=_in_thread(platform, event, source),
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
    if getattr(source, "chat_type", "dm") not in _GROUP_CHAT_TYPES:
        return False
    return not _text(getattr(event, "text", None)).lstrip().startswith("/")


# --- the 🫡 acknowledgement ------------------------------------------------------------


def ack_call(adapter: object, event: object, platform: str) -> object | None:
    """The pending 🫡 reaction on the quiet message, for the hook to await; None when there is none.

    Uses the adapter's private ``_add_reaction`` (Hermes has no public
    reaction API for plugins) and honours its ``_reactions_enabled()``. A
    missing or failing method loses only the reaction; the skip stands either
    way. The call is not given a timeout of its own: it is the adapter's own
    HTTP call, bounded by the adapter's client.
    """
    react = getattr(adapter, "_add_reaction", None)
    if not callable(react):
        return None
    raw = getattr(event, "raw_message", None)
    try:
        enabled = getattr(adapter, "_reactions_enabled", None)
        if callable(enabled) and enabled() is False:
            return None
        if platform == "slack":
            source = getattr(event, "source", None)
            pending = react(getattr(source, "chat_id", ""), getattr(event, "message_id", None),
                            SLACK_ACK_EMOJI, _slack_team(source, raw))
        else:
            pending = react(raw, DISCORD_ACK_EMOJI)
    except (AttributeError, LookupError, OSError, RuntimeError, TypeError, ValueError):
        return None
    return pending if inspect.isawaitable(pending) else None


# --- the hook body -------------------------------------------------------------------


def _judged_room_record(omh_home: Path, key: str, adapter: object, event: object, platform: str, mode: str,
                        tick: float, loop: object) -> Room:
    """What a turn in a judged room needs if it answers ``[SHUTUP]``: the same mute and 🫡 a quiet word gets."""
    by = str(getattr(getattr(event, "source", None), "user_id", "") or "")
    return Room(
        noted=tick,
        mode=mode,
        mute=lambda muted_ts: write_mute(omh_home, key, {"muted_ts": muted_ts, "by": by, "judged": True}),
        react=lambda: ack_call(adapter, event, platform),
        loop=loop,
    )


def gate_event(event: object, gateway: object, *, hermes_home: Path | None = None, omh_home: Path | None = None,
               now: float | None = None) -> tuple[dict[str, str] | None, object | None]:
    """The `pre_gateway_dispatch` answer for `event` and the 🫡 reaction to await, if any.

    The answer is a skip dict, or None to let Hermes dispatch. Homes default
    to the profile that owns the event's source.
    """
    if not gated(event):
        return None, None
    source = getattr(event, "source", None)
    if not _authorized(gateway, source):
        return None, None
    if hermes_home is None:
        hermes_home = hermes_home_for(source)
    settings = read_settings(hermes_home)
    if settings["mode"] == "off":
        return None, None
    if omh_home is None:
        omh_home = omh_home_for(Path(hermes_home), settings) if hermes_home is not None else runtime_paths.default_omh_home()
    platform = _platform(source)
    adapter = _adapter(gateway, source)
    message = message_from_event(event, adapter, settings)
    key = thread_key(
        _text(getattr(source, "profile", None)), platform,
        str(getattr(source, "chat_id", "") or ""), str(getattr(source, "thread_id", "") or ""),
    )
    mutes = read_mutes(omh_home)
    judged = judged_room(gateway, source)
    decision = decide(message, muted=key in mutes, mode=settings["mode"], judged=judged)
    tick = float(now if now is not None else time.time())
    if decision.action in ("allow", "unmute"):
        if decision.action == "unmute" and key in mutes:
            write_mute(omh_home, key, None)
        if judged:
            note_room(key, _judged_room_record(omh_home, key, adapter, event, platform, settings["mode"], tick,
                                               gateway_loop(gateway)))
        return None, None
    entry = {
        "ts": tick, "reason": decision.reason, "key": key,
        "text": message.text[:SKIP_TEXT_CHARS], "user_id": str(getattr(source, "user_id", "") or ""),
    }
    append_skip(omh_home, entry)
    skip = {"action": "skip", "reason": decision.reason}
    if decision.action == "mute":
        if write_mute(omh_home, key, {"muted_ts": tick, "by": entry["user_id"]}):
            return skip, ack_call(adapter, event, platform)
    return skip, None

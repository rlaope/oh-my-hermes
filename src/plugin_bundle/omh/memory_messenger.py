"""Which messenger conversations OMH memory may treat as one person's, or one channel's.

Owner decision of 2026-10-13. A Hermes gateway session is shared by default
(`memory_session_lens`), because nobody authenticates who wrote each turn of a
multi-party chat. Three conversations can be told apart from what Hermes
already passes the provider (`platform`, `chat_type`, `chat_id`, `chat_name`,
`user_id`, `thread_id` at `initialize`, each only when set; `author_id` and
`author_is_bot` at each turn):

- a 1:1 direct message whose shape proves it has two parties, the bot and one
  person. When that person is the only user Hermes authorizes on the platform,
  it is the owner's DM and reads like an operator console; otherwise the
  person gets memory bound to their own principal;
- a group conversation, whose memory is the channel's own;
- anything else, which stays shared.

`chat_type` alone proves nothing. `SessionSource.chat_type` defaults to "dm"
(`gateway/session.py`), a relay connector's missing value becomes "dm"
(`gateway/relay/ws_transport.py`), and a handoff into a home channel that
could not open a thread is labelled "dm" with `user_id="system:handoff"`
(`gateway/run_startup.py`). Slack labels a group DM (mpim) "dm" too. So each
covered platform has its own structural check on the ids, drawn from its
adapter, and a platform without one is not covered and stays shared:

- telegram: a private chat's id is the user's own positive id
  (`chat_id == user_id`); groups and channels are negative, and a channel
  post's author is the channel itself;
- slack: a 1:1 IM's channel id starts with "D" (an mpim's does not), the
  author is a "U"/"W" user, and the chat is named. The message path always
  names it, falling back to its id (`_resolve_channel_name`); a slash command
  never does (`_handle_slash_command`), and one can run in a DM between two
  people, which carries a "D" id too;
- whatsapp: a person's JID ends in "@s.whatsapp.net" or "@lid", a group's in
  "@g.us"; the chat and the author must be the same person;
- whatsapp_cloud: DMs only, `chat_id == user_id`, digits;
- signal: a DM's chat id is the sender (`chat_id == user_id`), a group's is
  "group:<id>".

Discord has no DM check. The relay transport turns a missing `chat_type` into
"dm" while keeping the platform `discord`, and its adapter labels every
guild-less interaction "dm", user-installed app commands in group DMs
included (`gateway/relay/adapter.py`); relayed events are authorized upstream
and nothing in the provider's kwargs says an event was relayed. So every
Discord conversation is a channel, with memory per `chat_id`. A thread Hermes
auto-created from a channel message shares the parent channel's memory (see
`memory_thread_parent`); other threads keep their own scope.

The authorized set is what Hermes would admit on the platform, read the way
Hermes reads it and never written: `<PLATFORM>_ALLOWED_USERS` and
`GATEWAY_ALLOWED_USERS` (the process environment and the profile's `.env`)
together with the pairing store's approved users. A `GATEWAY_ALLOWED_USERS`
entry counts for a platform only when it has that platform's id shape
(`_GLOBAL_ENTRY_SHAPES`), so one global list may name the owner on two
platforms. Every reading that could admit someone OMH cannot list makes the
set unknown, and an unknown or open set has no owner: an allow-all flag, a
`*` entry, an unreadable pairing file, or an authorization key in
`config.yaml` (an adapter allowlist or DM policy there is consulted only when
no env allowlist exists, and its members cannot be listed without a YAML
parser). Every file -- `.env`, `config.yaml`, the pairing files and WhatsApp's
lid-mapping files -- is re-read only when its stat changes, so the set can be
re-evaluated at every turn start: pairing a second person mid-session turns
the owner's DM into that person's own DM at the next turn.

Stdlib only; no import of the `omh` control plane or of Hermes.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Callable, Mapping

DIRECT = "direct"
CHANNEL = "channel"

# Hermes' platform -> allowlist env map (`gateway/pairing.py`,
# `_PLATFORM_ALLOWLIST_ENV`), for the platforms with a DM check only.
ALLOWLIST_ENV = {
    "telegram": "TELEGRAM_ALLOWED_USERS",
    "slack": "SLACK_ALLOWED_USERS",
    "whatsapp": "WHATSAPP_ALLOWED_USERS",
    "whatsapp_cloud": "WHATSAPP_CLOUD_ALLOWED_USERS",
    "signal": "SIGNAL_ALLOWED_USERS",
}
GLOBAL_ALLOWLIST_ENV = "GATEWAY_ALLOWED_USERS"
GLOBAL_ALLOW_ALL_ENV = "GATEWAY_ALLOW_ALL_USERS"
# Platforms whose groups are channels but whose DMs nothing proves.
CHANNEL_ONLY_PLATFORMS = frozenset({"discord"})
COVERED_PLATFORMS = frozenset(ALLOWLIST_ENV) | CHANNEL_ONLY_PLATFORMS

AUTH_CLOSED = "closed"
AUTH_OPEN = "open"
AUTH_UNKNOWN = "unknown"

_TRUTHY = frozenset({"true", "1", "yes"})
_TELEGRAM_PRIVATE = re.compile(r"^[1-9][0-9]{0,19}$")
_TELEGRAM_GROUP = re.compile(r"^-[1-9][0-9]{0,19}$")
_SLACK_IM = re.compile(r"^D[A-Z0-9]{2,30}$")
_SLACK_CONVERSATION = re.compile(r"^[CG][A-Z0-9]{2,30}$")
_SLACK_USER = re.compile(r"^[UW][A-Z0-9]{2,30}$")
_SNOWFLAKE = re.compile(r"^[1-9][0-9]{5,24}$")
_WHATSAPP_PERSON = re.compile(r"^\+?[0-9]{3,24}(?::[0-9]{1,4})?@(?:s\.whatsapp\.net|lid)$")
_WHATSAPP_GROUP = re.compile(r"^[0-9][0-9-]{2,60}@g\.us$")
_DIGITS = re.compile(r"^[1-9][0-9]{3,24}$")
_SIGNAL_PERSON = re.compile(r"^(?:\+[1-9][0-9]{5,15}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")
_SIGNAL_GROUP = re.compile(r"^group:[A-Za-z0-9+/=_-]{8,128}$")
_SAFE_ALIAS = re.compile(r"^[A-Za-z0-9@.+\-]+$")
# A config.yaml line that can admit someone OMH cannot list. Only the key is
# matched; a value that disables it is the only thing that does not count.
_CONFIG_GRANT_LINE = re.compile(r"^\s*(allow_from|allowed_users|allow_all_users|allowed_roles|dm_policy)\s*:(.*)$")
_CONFIG_ABSENT_VALUES = frozenset({"[]", "null", "~", '""', "''", "false", "no", "off"})
_CONFIG_SAFE_DM_POLICIES = frozenset({"pairing", "disabled"})


def _whatsapp_shaped(entry: str) -> bool:
    return normalize_whatsapp_identifier(entry).isdigit()


# The shape a `GATEWAY_ALLOWED_USERS` entry must have to count for a platform.
# No platform's user can carry another's shape -- a Slack id is never digits,
# a Telegram id never has letters -- so dropping the rest drops nobody Hermes
# would admit there. Digits fit Telegram and both WhatsApp APIs alike and count
# for each of them.
_GLOBAL_ENTRY_SHAPES: dict[str, Callable[[str], bool]] = {
    "telegram": lambda entry: bool(_TELEGRAM_PRIVATE.fullmatch(entry)),
    "slack": lambda entry: bool(_SLACK_USER.fullmatch(entry)),
    "whatsapp": _whatsapp_shaped,
    "whatsapp_cloud": _whatsapp_shaped,
    "signal": lambda entry: bool(_SIGNAL_PERSON.fullmatch(entry)),
}


@dataclass(frozen=True)
class MessengerConversation:
    """A structurally verified conversation: a DM with ``partner``, or the channel ``chat_id``."""

    platform: str
    kind: str
    partner: str
    chat_id: str


@dataclass(frozen=True)
class AuthorizedSet:
    """Who Hermes admits on one platform: closed (listed people), open, or unknown."""

    state: str
    people: tuple[frozenset[str], ...] = ()


class _StatCache:
    """Parsed file contents, re-read only when the file's stat changes."""

    def __init__(self) -> None:
        self._entries: dict[Path, tuple[tuple[int, ...], object]] = {}

    def read(self, path: Path, parse: Callable[[str | None], object]) -> object:
        """``parse(text)`` for the file, ``parse(None)`` when it is absent; None when it cannot be read."""
        try:
            stat = path.stat()
        except FileNotFoundError:
            return parse(None)
        except OSError:
            return None
        key = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
        cached = self._entries.get(path)
        if cached is not None and cached[0] == key:
            return cached[1]
        try:
            text = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            return None
        value = parse(text)
        self._entries[path] = (key, value)
        return value


# WhatsApp's lid-mapping files, read by every classification and author check.
_LID_MAPPINGS = _StatCache()


def classify_conversation(
    platform: object,
    *,
    chat_type: object,
    chat_id: object,
    user_id: object,
    thread_id: object = "",
    chat_name: object = "",
    hermes_home: Path | None = None,
) -> MessengerConversation | None:
    """The verified conversation for Hermes' gateway kwargs, or None (shared) when nothing proves one."""
    name = str(platform or "")
    kind, chat, user = str(chat_type or ""), str(chat_id or "").strip(), str(user_id or "").strip()
    if name not in COVERED_PLATFORMS or not chat:
        return None
    direct = _DIRECT_CHECKS.get(name)
    if kind == "dm" and user and direct is not None and direct(chat, user, str(thread_id or "").strip(), bool(str(chat_name or "").strip()), hermes_home):
        return MessengerConversation(name, DIRECT, user, chat)
    if _CHANNEL_CHECKS[name](kind, chat):
        return MessengerConversation(name, CHANNEL, "", chat)
    return None


def same_person(platform: str, first: object, second: object, hermes_home: Path | None = None) -> bool:
    """Whether two of the platform's user ids name one person (WhatsApp: phone, LID and device aliases)."""
    left, right = str(first or "").strip(), str(second or "").strip()
    if not left or not right:
        return False
    if platform in ("whatsapp", "whatsapp_cloud"):
        return bool(_whatsapp_aliases(left, hermes_home) & _whatsapp_aliases(right, hermes_home))
    return left == right


def principal_identity(conversation: MessengerConversation, hermes_home: Path | None = None) -> str:
    """The host identity a DM partner's principal is derived from.

    WhatsApp shows one person as a phone JID or a LID; Hermes keys a DM by the
    shortest alias (`canonical_whatsapp_identifier`), and so does this, so an
    alias flip keeps the person's memory.
    """
    if conversation.platform in ("whatsapp", "whatsapp_cloud"):
        aliases = _whatsapp_aliases(conversation.partner, hermes_home)
        return min(aliases, key=lambda alias: (len(alias), alias)) if aliases else normalize_whatsapp_identifier(conversation.partner)
    return conversation.partner


def normalize_whatsapp_identifier(value: object) -> str:
    """Hermes' own rule (`gateway/whatsapp_identity.py`): no "+", no device, no domain."""
    return str(value or "").strip().replace("+", "", 1).split(":", 1)[0].split("@", 1)[0]


def _telegram_direct(chat: str, user: str, _thread: str, _named: bool, _home: Path | None) -> bool:
    return bool(_TELEGRAM_PRIVATE.fullmatch(chat)) and chat == user


def _slack_direct(chat: str, user: str, _thread: str, named: bool, _home: Path | None) -> bool:
    # A DM thread is normal: Slack keys each top-level DM thread as its own session.
    return bool(_SLACK_IM.fullmatch(chat) and _SLACK_USER.fullmatch(user)) and named


def _whatsapp_direct(chat: str, user: str, _thread: str, _named: bool, home: Path | None) -> bool:
    return bool(_WHATSAPP_PERSON.fullmatch(chat) and _WHATSAPP_PERSON.fullmatch(user)) and same_person("whatsapp", chat, user, home)


def _whatsapp_cloud_direct(chat: str, user: str, _thread: str, _named: bool, _home: Path | None) -> bool:
    return bool(_DIGITS.fullmatch(chat)) and chat == user


def _signal_direct(chat: str, user: str, _thread: str, _named: bool, _home: Path | None) -> bool:
    return bool(_SIGNAL_PERSON.fullmatch(chat)) and chat == user


_DIRECT_CHECKS: dict[str, Callable[[str, str, str, bool, Path | None], bool]] = {
    "telegram": _telegram_direct,
    "slack": _slack_direct,
    "whatsapp": _whatsapp_direct,
    "whatsapp_cloud": _whatsapp_cloud_direct,
    "signal": _signal_direct,
}

_CHANNEL_CHECKS: dict[str, Callable[[str, str], bool]] = {
    "telegram": lambda kind, chat: kind in ("group", "channel") and bool(_TELEGRAM_GROUP.fullmatch(chat)),
    "slack": lambda kind, chat: kind == "group" and bool(_SLACK_CONVERSATION.fullmatch(chat)),
    # Whatever its label: a DM, a guild channel and a thread each have their own id.
    "discord": lambda kind, chat: bool(_SNOWFLAKE.fullmatch(chat)),
    "whatsapp": lambda kind, chat: kind == "group" and bool(_WHATSAPP_GROUP.fullmatch(chat)),
    # The Cloud API delivers no group conversation (`gateway/platforms/whatsapp_cloud.py`).
    "whatsapp_cloud": lambda kind, chat: False,
    "signal": lambda kind, chat: kind == "group" and bool(_SIGNAL_GROUP.fullmatch(chat)),
}


class HermesAuthorization:
    """The authorized set per platform, each file re-read only when its stat changes."""

    def __init__(self, hermes_home: Path | None, *, environ: Mapping[str, str] | None = None) -> None:
        self._home = Path(hermes_home) if hermes_home is not None else None
        self._environ = environ
        self._files = _StatCache()

    def authorized(self, platform: str) -> AuthorizedSet:
        env_var = ALLOWLIST_ENV.get(platform)
        if env_var is None or self._home is None:
            return AuthorizedSet(AUTH_UNKNOWN)
        environ = os.environ if self._environ is None else self._environ
        dotenv = self._files.read(self._home / ".env", _parse_dotenv)
        if dotenv is None:
            return AuthorizedSet(AUTH_UNKNOWN)

        def values(name: str) -> list[str]:
            return [str(environ.get(name, "") or ""), str(dotenv.get(name, "") or "")]

        allow_all = (env_var.replace("_ALLOWED_USERS", "_ALLOW_ALL_USERS"), GLOBAL_ALLOW_ALL_ENV)
        if any(value.strip().lower() in _TRUTHY for name in allow_all for value in values(name)):
            return AuthorizedSet(AUTH_OPEN)
        if self._files.read(self._home / "config.yaml", _config_grants_unlisted) is not False:
            return AuthorizedSet(AUTH_UNKNOWN)
        ids = {entry for value in values(env_var) for entry in _split(value)}
        shaped = _GLOBAL_ENTRY_SHAPES[platform]
        ids.update(entry for value in values(GLOBAL_ALLOWLIST_ENV) for entry in _split(value) if entry == "*" or shaped(entry))
        for path in (self._home / "platforms" / "pairing" / f"{platform}-approved.json", self._home / "pairing" / f"{platform}-approved.json"):
            approved = self._files.read(path, _parse_approved)
            if approved is None:
                return AuthorizedSet(AUTH_UNKNOWN)
            ids.update(approved)
        if "*" in ids:
            return AuthorizedSet(AUTH_OPEN)
        return AuthorizedSet(AUTH_CLOSED, self._people(platform, ids))

    def owner(self, conversation: MessengerConversation) -> bool:
        """True when the DM partner is the one person Hermes authorizes on the platform."""
        if conversation.kind != DIRECT:
            return False
        authorized = self.authorized(conversation.platform)
        if authorized.state != AUTH_CLOSED or len(authorized.people) != 1:
            return False
        return any(same_person(conversation.platform, conversation.partner, alias, self._home) for alias in authorized.people[0])

    def _people(self, platform: str, ids: set[str]) -> tuple[frozenset[str], ...]:
        """One alias set per person: WhatsApp's phone, LID and "+"/device spellings of one person merge."""
        people: list[frozenset[str]] = []
        for entry in sorted(ids):
            aliases = frozenset(_whatsapp_aliases(entry, self._home)) if platform in ("whatsapp", "whatsapp_cloud") else frozenset({entry})
            merged = [person for person in people if person & aliases]
            people = [person for person in people if not person & aliases]
            people.append(frozenset().union(aliases, *merged))
        return tuple(people)


def _split(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _parse_dotenv(text: str | None) -> dict[str, str]:
    """``KEY=value`` lines, as Hermes' `.env` holds them; quotes and a trailing comment dropped."""
    values: dict[str, str] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        values[key] = value
    return values


def _parse_approved(text: str | None) -> set[str] | None:
    """The approved user ids of one pairing file (`gateway/pairing.py`); None when it is not an object."""
    if text is None:
        return set()
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    return {str(key).strip() for key in data if str(key).strip()}


def _config_grants_unlisted(text: str | None) -> bool:
    """True when config.yaml holds an authorization key whose members OMH cannot list."""
    for raw in (text or "").splitlines():
        match = _CONFIG_GRANT_LINE.match(raw)
        if match is None:
            continue
        key, value = match.group(1), match.group(2).split("#", 1)[0].strip()
        if key == "dm_policy" and value.strip("'\"").lower() in _CONFIG_SAFE_DM_POLICIES:
            continue
        if value.lower() in _CONFIG_ABSENT_VALUES:
            continue
        # A bare key with a block list below it counts like any other value.
        return True
    return False


def _parse_lid_mapping(text: str | None) -> str:
    """The alias one lid-mapping file names; "" when absent or unreadable as JSON."""
    if text is None:
        return ""
    try:
        return normalize_whatsapp_identifier(json.loads(text))
    except ValueError:
        return ""


def _whatsapp_aliases(identifier: str, hermes_home: Path | None) -> set[str]:
    """Hermes' alias closure (`expand_whatsapp_aliases`) over the bridge's lid-mapping files; read only."""
    start = normalize_whatsapp_identifier(identifier)
    if not start:
        return set()
    directories = (
        [hermes_home / "platforms" / "whatsapp" / "session", hermes_home / "whatsapp" / "session"] if hermes_home is not None else []
    )
    resolved: set[str] = set()
    queue = [start]
    while queue:
        current = queue.pop(0)
        if not current or current in resolved or not _SAFE_ALIAS.fullmatch(current):
            continue
        resolved.add(current)
        for directory in directories:
            for suffix in ("", "_reverse"):
                mapped = _LID_MAPPINGS.read(directory / f"lid-mapping-{current}{suffix}.json", _parse_lid_mapping)
                if isinstance(mapped, str) and mapped and mapped not in resolved:
                    queue.append(mapped)
    return resolved


__all__ = [
    "ALLOWLIST_ENV",
    "AUTH_CLOSED",
    "AUTH_OPEN",
    "AUTH_UNKNOWN",
    "AuthorizedSet",
    "CHANNEL",
    "CHANNEL_ONLY_PLATFORMS",
    "COVERED_PLATFORMS",
    "DIRECT",
    "HermesAuthorization",
    "MessengerConversation",
    "classify_conversation",
    "normalize_whatsapp_identifier",
    "principal_identity",
    "same_person",
]

"""OMH memory on messenger apps: the owner's DM, other people's DMs, and group channels.

Issue #2088: an outside user's Slack 1:1 DM received 0 of 33 approved
records, because every gateway session was a shared surface and a shared
surface denies every identity-unbound record. The owner decision of
2026-10-13 splits a gateway session three ways, from the kwargs Hermes
already passes (`agent/agent_init.py::_memory_provider_init_kwargs` at
`initialize`, `agent/turn_context.py::_memory_turn_start_and_prefetch` at each
turn):

- the owner's DM -- a 1:1 DM whose shape proves it, with the only user Hermes
  authorizes on the platform -- reads and writes like an operator console;
- anyone else's DM reads and writes only memory bound to that person;
- a group conversation reads and writes only its own channel's memory.

Everything unverified stays shared. Every test drives the provider's real
`initialize` / `on_turn_start` / `prefetch` with Hermes-shaped kwargs per
platform and the tool's real handler; nothing patches the classifier.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.coding_delegation import build_coding_delegation_payload  # noqa: E402
from omh.paths import resolve_paths  # noqa: E402
from omh.plugin_bundle.omh.memory_admission import capture_project_memory_candidate  # noqa: E402
from omh.plugin_bundle.omh.memory_blocks import approve_memory_block, build_memory_block, write_memory_block  # noqa: E402
from omh.plugin_bundle.omh.memory_messenger import ALLOWLIST_ENV, HermesAuthorization, classify_conversation  # noqa: E402
from omh.plugin_bundle.omh.memory_principals import derive_channel_ref, principal_operation_decision, principal_recall_decision  # noqa: E402
from omh.plugin_bundle.omh.memory_provider import OmhMemoryProvider  # noqa: E402
from omh.plugin_bundle.omh.memory_session_digest import write_session_close  # noqa: E402
from omh.plugin_bundle.omh.memory_session_lens import (  # noqa: E402
    SESSION_LENS_SCHEMA_VERSION,
    SURFACE_BACKGROUND,
    SURFACE_CHANNEL,
    SURFACE_DIRECT,
    SURFACE_OPERATOR_CONSOLE,
    SURFACE_OWNER_DIRECT,
    SURFACE_SHARED,
    read_session_lens,
    session_lens_path,
    tighter_surface_class,
)
from omh.plugin_bundle.omh.tools.chat_tool import omh_interact_handler  # noqa: E402
from omh.plugin_bundle.omh.tools.memory_tool import omh_memory_handler  # noqa: E402
from omh.workflows.memory import memory_recall_pack_for_handoff, scope_allowlist_errors, validate_project_memory_recall_pack  # noqa: E402
from omh.wrapper_sessions import (  # noqa: E402
    create_or_resume_wrapper_session,
    prepare_wrapper_session_handoff,
    record_plan_decision,
    select_wrapper_session_executor,
)
from project_identity_fixture import seed_project_identity  # noqa: E402
from test_memory_demote_tool import FACT, entry, sha, write_memory  # noqa: E402
from test_memory_prefetch_canonical import rendered_ids  # noqa: E402
from test_memory_session_digest import digest_attributes, stamp, write_record  # noqa: E402

# Ids shaped as each adapter delivers them (see `memory_messenger`).
SLACK_OWNER, SLACK_DM, SLACK_TEAM, SLACK_OTHER_TEAM = "U01OWNER", "D0OWNERDM", "C0TEAM", "C0OTHER"
TELEGRAM_OWNER = "123456789"
DISCORD_OWNER, DISCORD_DM = "987654321098765432", "1234567890123456789"
WHATSAPP_PHONE = "15551234567"
SIGNAL_OWNER = "+15551234567"
# (platform, init kwargs of a real 1:1 DM with the owner, allowlist value).
# The `gateway` helper adds the `chat_name` every message path sets.
OWNER_DMS = (
    ("slack", {"chat_type": "dm", "chat_id": SLACK_DM, "user_id": SLACK_OWNER, "thread_id": "1760000000.000100"}, SLACK_OWNER),
    ("telegram", {"chat_type": "dm", "chat_id": TELEGRAM_OWNER, "user_id": TELEGRAM_OWNER}, TELEGRAM_OWNER),
    (
        "whatsapp",
        {"chat_type": "dm", "chat_id": f"{WHATSAPP_PHONE}@s.whatsapp.net", "user_id": f"{WHATSAPP_PHONE}@s.whatsapp.net"},
        f"+{WHATSAPP_PHONE}",
    ),
    ("whatsapp_cloud", {"chat_type": "dm", "chat_id": WHATSAPP_PHONE, "user_id": WHATSAPP_PHONE}, WHATSAPP_PHONE),
    ("signal", {"chat_type": "dm", "chat_id": SIGNAL_OWNER, "user_id": SIGNAL_OWNER}, SIGNAL_OWNER),
)
# Conversations labelled "dm" that nothing proves are 1:1. Each stays shared.
UNPROVEN_DMS = (
    # Slack labels a group DM (mpim) "dm" on the message path; its id is not a "D" IM.
    ("slack", {"chat_type": "dm", "chat_id": "G0MPIM123", "user_id": SLACK_OWNER}),
    ("slack", {"chat_type": "dm", "chat_id": SLACK_TEAM, "user_id": SLACK_OWNER}),
    # The handoff into a home channel that opened no thread (`gateway/run_startup.py`).
    ("slack", {"chat_type": "dm", "chat_id": SLACK_DM, "user_id": "system:handoff"}),
    # A slash command run in a DM between two people: a "D" id, but the
    # slash path never names the chat (`_handle_slash_command`).
    ("slack", {"chat_type": "dm", "chat_id": "D0TWOHUMANS", "user_id": SLACK_OWNER, "chat_name": ""}),
    ("telegram", {"chat_type": "dm", "chat_id": "-1001234567890", "user_id": TELEGRAM_OWNER}),
    ("telegram", {"chat_type": "dm", "chat_id": "555000111", "user_id": TELEGRAM_OWNER}),
    # A channel post's author is the channel itself (`_build_message_event`); a
    # relay that drops its type delivers it as "dm" with chat_id == user_id.
    ("telegram", {"chat_type": "dm", "chat_id": "-1009876543210", "user_id": "-1009876543210"}),
    ("whatsapp", {"chat_type": "dm", "chat_id": "120363012345678901@g.us", "user_id": f"{WHATSAPP_PHONE}@s.whatsapp.net"}),
    # A LID chat and a phone author with no lid-mapping file: not provably one person.
    ("whatsapp", {"chat_type": "dm", "chat_id": "99887766554433@lid", "user_id": f"{WHATSAPP_PHONE}@s.whatsapp.net"}),
    ("signal", {"chat_type": "dm", "chat_id": "group:QUJDREVGR0hJSktMTU5PUA==", "user_id": SIGNAL_OWNER}),
    # The SessionSource default: chat_type "dm" with no chat id at all.
    ("slack", {"chat_type": "dm", "user_id": SLACK_OWNER}),
    # Platforms with no structural check are not covered.
    ("matrix", {"chat_type": "dm", "chat_id": "!room:example.org", "user_id": "@owner:example.org"}),
    ("mattermost", {"chat_type": "dm", "chat_id": "abcdefghijklmnopqrstuvwxyz", "user_id": "owner"}),
    ("email", {"chat_type": "dm", "chat_id": "owner@example.org", "user_id": "owner@example.org"}),
    ("relay", {"chat_type": "dm", "chat_id": SLACK_DM, "user_id": SLACK_OWNER}),
    ("api_server", {}),
)
CLEARED_ENV = (
    *ALLOWLIST_ENV.values(),
    *(name.replace("_ALLOWED_USERS", "_ALLOW_ALL_USERS") for name in ALLOWLIST_ENV.values()),
    "GATEWAY_ALLOWED_USERS",
    "GATEWAY_ALLOW_ALL_USERS",
    "DISCORD_ALLOWED_USERS",
    "DISCORD_ALLOWED_ROLES",
    "HERMES_SESSION_ID",
)
# Discord shapes: the message path's DM, a relayed event whose type was lost,
# a guild-less interaction the relay labels "dm" (a group DM included), and
# the handoff fallback. Each is a channel keyed by its own id.
DISCORD_CONVERSATIONS = (
    {"chat_type": "dm", "chat_id": DISCORD_DM, "user_id": DISCORD_OWNER},
    {"chat_id": DISCORD_DM, "user_id": DISCORD_OWNER},
    {"chat_type": "dm", "chat_id": "3333333333333333333", "user_id": DISCORD_OWNER},
    {"chat_type": "dm", "chat_id": "1122334455667788990", "user_id": "system:handoff"},
    {"chat_type": "group", "chat_id": "1111111111111111111", "user_id": DISCORD_OWNER},
)


class _Messenger(unittest.TestCase):
    """An OMH home, a Hermes home, and gateway sessions started the way Hermes starts them."""

    def setUp(self) -> None:
        base = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.home = base / "omh-home"
        self.hermes = base / "hermes-home"
        (self.hermes / "memories").mkdir(parents=True)
        # The gateway's working directory, outside any repository.
        self.workspace = base / "workspace"
        self.workspace.mkdir()
        self.enterContext(patch.dict(os.environ, {"OMH_HOME": str(self.home), "HERMES_HOME": str(self.hermes)}))
        for name in CLEARED_ENV:
            os.environ.pop(name, None)
        self.providers: list[OmhMemoryProvider] = []

    def gateway(self, session_id: str, platform: str, **identity: object) -> OmhMemoryProvider:
        """`initialize` with what `_memory_provider_init_kwargs` builds for a gateway agent (truthy keys only)."""
        live = OmhMemoryProvider(self.home)
        kwargs: dict[str, object] = {
            "platform": platform,
            "hermes_home": str(self.hermes),
            "agent_context": "primary",
            "user_name": "someone",
            "chat_name": "a chat",
            "gateway_session_key": f"agent:main:{platform}:{identity.get('chat_type', 'dm')}:{identity.get('chat_id', '')}",
            "cwd": str(self.workspace),
            "agent_identity": "default",
            "agent_workspace": "hermes",
        }
        for key, value in identity.items():
            # Hermes passes an identity key only when it is set.
            if value:
                kwargs[key] = value
            else:
                kwargs.pop(key, None)
        live.initialize(session_id, **kwargs)
        self.providers.append(live)
        return live

    def console(self, session_id: str = "cli-session") -> OmhMemoryProvider:
        live = OmhMemoryProvider(self.home)
        live.initialize(session_id, platform="cli", hermes_home=str(self.hermes), agent_context="primary", cwd=str(self.workspace))
        self.providers.append(live)
        return live

    @staticmethod
    def turn(live: OmhMemoryProvider, number: int, message: str, *, author_id: object = None, author_is_bot: bool = False) -> str:
        """One Hermes turn: `on_turn_start` with the author kwargs, then `prefetch` with the live id."""
        live.on_turn_start(number, message, author_id=author_id, author_name="someone" if author_id else None, author_is_bot=author_is_bot)
        return live.prefetch(message, session_id=live._session_id)

    def tool(self, action: str, session_id: str, **args: object) -> dict:
        return json.loads(omh_memory_handler({"action": action, **args}, cwd=str(self.workspace), session_id=session_id))

    def capture(self, session_id: str, summary: str, **args: object) -> dict:
        result = self.tool("capture", session_id, summary=summary, **args)
        self.assertEqual(result["status"], "remembered", result)
        return result

    def owner_capture(self, summary: str) -> str:
        """A capture made at the CLI: identity-unbound, user-global outside a repository."""
        self.console()
        return str(self.capture("cli-session", summary)["record_id"])

    def store_bytes(self) -> dict[str, bytes]:
        memory = self.home / "memory"
        return {str(path.relative_to(memory)): path.read_bytes() for path in sorted(memory.rglob("*")) if path.is_file()} if memory.exists() else {}

    def record(self, record_id: str) -> dict:
        return json.loads((self.home / "memory" / "records" / f"{record_id}.json").read_text(encoding="utf-8"))

    def write_env(self, **values: str) -> None:
        (self.hermes / ".env").write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")

    def write_pairing(self, platform: str, *user_ids: str, legacy: bool = False) -> Path:
        directory = self.hermes / "pairing" if legacy else self.hermes / "platforms" / "pairing"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{platform}-approved.json"
        path.write_text(json.dumps({user_id: {"user_name": user_id, "approved_at": 1760000000.0} for user_id in user_ids}), encoding="utf-8")
        return path


class ClassificationTests(_Messenger):
    def test_a_real_owner_dm_on_each_covered_platform_is_the_owners(self) -> None:
        for index, (platform, identity, allowed) in enumerate(OWNER_DMS):
            with self.subTest(platform=platform), patch.dict(os.environ, {ALLOWLIST_ENV[platform]: allowed}):
                live = self.gateway(f"owner-{index}", platform, **identity)
                self.assertEqual(live._surface_class, SURFACE_OWNER_DIRECT)
                lens = read_session_lens(self.home, f"owner-{index}")
                assert lens is not None
                self.assertEqual((lens["surface_class"], lens["shared_surface"], lens["writes_enabled"]), (SURFACE_OWNER_DIRECT, False, True))
                self.assertIsNone(lens["principal_context"])

    def test_the_same_dm_with_another_authorized_user_is_that_persons_own(self) -> None:
        for index, (platform, identity, allowed) in enumerate(OWNER_DMS):
            other = "+15559990000" if platform == "signal" else ("U02OTHER" if platform == "slack" else "15559990000")
            with self.subTest(platform=platform), patch.dict(os.environ, {ALLOWLIST_ENV[platform]: f"{allowed},{other}"}):
                live = self.gateway(f"two-{index}", platform, **identity)
                self.assertEqual(live._surface_class, SURFACE_DIRECT)
                lens = read_session_lens(self.home, f"two-{index}")
                assert lens is not None
                self.assertRegex(lens["principal_context"]["principal"], r"^principal:v1:[0-9a-f]{64}$")
                self.assertEqual(lens["principal_context"]["actor_kind"], "human")

    def test_every_discord_conversation_is_a_channel_of_its_own_id(self) -> None:
        # The relay turns a missing type into "dm" and labels guild-less
        # interactions "dm", group DMs included; nothing in the kwargs says an
        # event was relayed, so no Discord conversation is a DM.
        os.environ["DISCORD_ALLOWED_USERS"] = DISCORD_OWNER
        scopes = []
        for index, identity in enumerate(DISCORD_CONVERSATIONS):
            with self.subTest(identity=identity):
                live = self.gateway(f"discord-{index}", "discord", **identity)
                self.assertEqual(live._surface_class, SURFACE_CHANNEL)
                self.assertIsNone(live._principal_context)
                scopes.append((identity["chat_id"], live._channel_scope["ref"]))
        self.assertEqual(len({ref for _chat, ref in scopes}), len({chat for chat, _ref in scopes}), "one scope per chat id")

    def test_a_dm_nothing_proves_is_shared_even_with_a_single_authorized_user(self) -> None:
        self.write_env(**{name: SLACK_OWNER if name == "SLACK_ALLOWED_USERS" else TELEGRAM_OWNER for name in ("SLACK_ALLOWED_USERS", "TELEGRAM_ALLOWED_USERS")})
        for index, (platform, identity) in enumerate(UNPROVEN_DMS):
            with self.subTest(platform=platform, identity=identity):
                live = self.gateway(f"unproven-{index}", platform, **identity)
                self.assertEqual(live._surface_class, SURFACE_SHARED)
                self.assertIsNone(live._conversation)

    def test_a_lid_chat_whose_mapping_names_the_author_is_one_person(self) -> None:
        session = self.hermes / "platforms" / "whatsapp" / "session"
        session.mkdir(parents=True)
        (session / "lid-mapping-99887766554433.json").write_text(json.dumps(WHATSAPP_PHONE), encoding="utf-8")
        conversation = classify_conversation(
            "whatsapp", chat_type="dm", chat_id="99887766554433@lid", user_id=f"{WHATSAPP_PHONE}:12@s.whatsapp.net", hermes_home=self.hermes
        )
        assert conversation is not None
        self.assertEqual(conversation.kind, "direct")

    def test_a_whatsapp_alias_flip_keeps_the_persons_principal(self) -> None:
        # Hermes keys a WhatsApp DM by the shortest alias; the principal follows
        # it, so the same person seen as a LID and then as a phone keeps one memory.
        session = self.hermes / "platforms" / "whatsapp" / "session"
        session.mkdir(parents=True)
        (session / "lid-mapping-99887766554433.json").write_text(json.dumps(WHATSAPP_PHONE), encoding="utf-8")
        (session / f"lid-mapping-{WHATSAPP_PHONE}_reverse.json").write_text(json.dumps("99887766554433"), encoding="utf-8")
        os.environ["WHATSAPP_ALLOWED_USERS"] = f"{WHATSAPP_PHONE},15559990000"
        as_lid = self.gateway("wa-lid", "whatsapp", chat_type="dm", chat_id="99887766554433@lid", user_id="99887766554433@lid")
        as_phone = self.gateway("wa-phone", "whatsapp", chat_type="dm", chat_id=f"{WHATSAPP_PHONE}@s.whatsapp.net", user_id=f"{WHATSAPP_PHONE}:7@s.whatsapp.net")
        self.assertEqual((as_lid._surface_class, as_phone._surface_class), (SURFACE_DIRECT, SURFACE_DIRECT))
        self.assertEqual(as_lid._principal_context["principal"], as_phone._principal_context["principal"])

    def test_a_reverse_only_mapping_still_reaches_the_shortest_alias(self) -> None:
        # The bridge may have written only the LID's reverse file; Hermes
        # follows `_reverse` files too, so the LID still reaches the phone.
        session = self.hermes / "platforms" / "whatsapp" / "session"
        session.mkdir(parents=True)
        (session / "lid-mapping-99887766554433_reverse.json").write_text(json.dumps(WHATSAPP_PHONE), encoding="utf-8")
        os.environ["WHATSAPP_ALLOWED_USERS"] = f"{WHATSAPP_PHONE},15559990000"
        as_lid = self.gateway("wa-lid", "whatsapp", chat_type="dm", chat_id="99887766554433@lid", user_id="99887766554433@lid")
        as_phone = self.gateway("wa-phone", "whatsapp", chat_type="dm", chat_id=f"{WHATSAPP_PHONE}@s.whatsapp.net", user_id=f"{WHATSAPP_PHONE}@s.whatsapp.net")
        self.assertEqual((as_lid._surface_class, as_phone._surface_class), (SURFACE_DIRECT, SURFACE_DIRECT))
        self.assertEqual(as_lid._principal_context["principal"], as_phone._principal_context["principal"])

    def test_groups_on_each_covered_platform_are_channels(self) -> None:
        groups = (
            ("slack", {"chat_type": "group", "chat_id": SLACK_TEAM, "user_id": SLACK_OWNER, "thread_id": "1760000000.000200"}),
            ("telegram", {"chat_type": "group", "chat_id": "-1001234567890", "user_id": TELEGRAM_OWNER, "thread_id": "7"}),
            ("telegram", {"chat_type": "channel", "chat_id": "-1009876543210", "user_id": "-1009876543210"}),
            ("discord", {"chat_type": "group", "chat_id": "1111111111111111111", "user_id": DISCORD_OWNER}),
            ("discord", {"chat_type": "thread", "chat_id": "2222222222222222222", "user_id": DISCORD_OWNER, "thread_id": "2222222222222222222"}),
            ("whatsapp", {"chat_type": "group", "chat_id": "120363012345678901@g.us", "user_id": f"{WHATSAPP_PHONE}@s.whatsapp.net"}),
            ("signal", {"chat_type": "group", "chat_id": "group:QUJDREVGR0hJSktMTU5PUA==", "user_id": SIGNAL_OWNER}),
        )
        for index, (platform, identity) in enumerate(groups):
            with self.subTest(platform=platform, identity=identity):
                live = self.gateway(f"group-{index}", platform, **identity)
                self.assertEqual(live._surface_class, SURFACE_CHANNEL)
                lens = read_session_lens(self.home, f"group-{index}")
                assert lens is not None
                self.assertRegex(lens["channel_scope"]["ref"], r"^channel:v1:[0-9a-f]{64}$")
                self.assertIsNone(lens["principal_context"])
        # A group shape on the wrong platform proves nothing.
        self.assertEqual(self.gateway("odd", "slack", chat_type="group", chat_id="D0NOTAGROUP", user_id=SLACK_OWNER)._surface_class, SURFACE_SHARED)
        self.assertEqual(self.gateway("cloud", "whatsapp_cloud", chat_type="group", chat_id="15551234567", user_id="15551234567")._surface_class, SURFACE_SHARED)

    def test_a_console_a_background_run_and_a_tightening_request_ignore_the_chat(self) -> None:
        identity = {"chat_type": "dm", "chat_id": SLACK_DM, "user_id": SLACK_OWNER}
        with patch.dict(os.environ, {"SLACK_ALLOWED_USERS": SLACK_OWNER}):
            self.assertEqual(self.gateway("as-cli", "cli", **identity)._surface_class, SURFACE_OPERATOR_CONSOLE)
            cron = OmhMemoryProvider(self.home)
            cron.initialize("as-cron", platform="slack", hermes_home=str(self.hermes), agent_context="cron", **identity)
            self.assertEqual(cron._surface_class, SURFACE_BACKGROUND)
            self.assertEqual(self.gateway("tight", "slack", shared_surface=True, **identity)._surface_class, SURFACE_SHARED)

    def test_tightness_lattice(self) -> None:
        for first, second, expected in (
            (SURFACE_OPERATOR_CONSOLE, SURFACE_OWNER_DIRECT, SURFACE_OWNER_DIRECT),
            (SURFACE_OWNER_DIRECT, SURFACE_DIRECT, SURFACE_DIRECT),
            (SURFACE_DIRECT, SURFACE_CHANNEL, SURFACE_SHARED),
            (SURFACE_CHANNEL, SURFACE_DIRECT, SURFACE_SHARED),
            (SURFACE_CHANNEL, SURFACE_SHARED, SURFACE_SHARED),
            (SURFACE_DIRECT, SURFACE_BACKGROUND, SURFACE_BACKGROUND),
            (SURFACE_DIRECT, SURFACE_DIRECT, SURFACE_DIRECT),
            ("bogus", SURFACE_OWNER_DIRECT, "bogus"),
        ):
            with self.subTest(first=first, second=second):
                self.assertEqual(tighter_surface_class(first, second), expected)


class AuthorizedSetTests(_Messenger):
    """Who Hermes admits, read from its files and never written; an unlistable grant means no owner."""

    def owner(self, platform: str = "slack", chat_id: str = SLACK_DM, user_id: str = SLACK_OWNER) -> bool:
        conversation = classify_conversation(platform, chat_type="dm", chat_id=chat_id, user_id=user_id, chat_name="a DM", hermes_home=self.hermes)
        assert conversation is not None
        return HermesAuthorization(self.hermes).owner(conversation)

    def test_each_listing_source_names_the_owner(self) -> None:
        cases = {
            "process env": lambda: os.environ.__setitem__("SLACK_ALLOWED_USERS", SLACK_OWNER),
            "profile .env": lambda: self.write_env(SLACK_ALLOWED_USERS=f'"{SLACK_OWNER}"'),
            "global allowlist": lambda: os.environ.__setitem__("GATEWAY_ALLOWED_USERS", SLACK_OWNER),
            "pairing store": lambda: self.write_pairing("slack", SLACK_OWNER),
            "legacy pairing dir": lambda: self.write_pairing("slack", SLACK_OWNER, legacy=True),
        }
        for label, arrange in cases.items():
            with self.subTest(source=label), patch.dict(os.environ):
                for path in (self.hermes / ".env", self.hermes / "platforms" / "pairing" / "slack-approved.json", self.hermes / "pairing" / "slack-approved.json"):
                    path.unlink(missing_ok=True)
                arrange()
                self.assertTrue(self.owner())

    def test_no_owner_when_the_set_is_empty_open_or_unlistable(self) -> None:
        cases = {
            "empty": lambda: None,
            "two people": lambda: (os.environ.__setitem__("SLACK_ALLOWED_USERS", SLACK_OWNER), self.write_pairing("slack", "U02GUEST")),
            "wildcard": lambda: os.environ.__setitem__("SLACK_ALLOWED_USERS", f"{SLACK_OWNER},*"),
            "platform allow-all": lambda: (os.environ.__setitem__("SLACK_ALLOWED_USERS", SLACK_OWNER), os.environ.__setitem__("SLACK_ALLOW_ALL_USERS", "true")),
            "gateway allow-all": lambda: (os.environ.__setitem__("SLACK_ALLOWED_USERS", SLACK_OWNER), self.write_env(GATEWAY_ALLOW_ALL_USERS="yes")),
            "config allowlist": lambda: (
                os.environ.__setitem__("SLACK_ALLOWED_USERS", SLACK_OWNER),
                (self.hermes / "config.yaml").write_text("slack:\n  allow_from:\n    - U09ELSE\n", encoding="utf-8"),
            ),
            "config dm policy open": lambda: (
                self.write_pairing("slack", SLACK_OWNER),
                (self.hermes / "config.yaml").write_text("platforms:\n  slack:\n    dm_policy: open\n", encoding="utf-8"),
            ),
            "unreadable pairing": lambda: (
                os.environ.__setitem__("SLACK_ALLOWED_USERS", SLACK_OWNER),
                (self.hermes / "platforms" / "pairing").mkdir(parents=True, exist_ok=True),
                (self.hermes / "platforms" / "pairing" / "slack-approved.json").write_text("{not json", encoding="utf-8"),
            ),
            "a username entry": lambda: os.environ.__setitem__("SLACK_ALLOWED_USERS", "owner@example.org"),
        }
        for label, arrange in cases.items():
            with self.subTest(case=label), patch.dict(os.environ):
                for path in (self.hermes / ".env", self.hermes / "config.yaml", self.hermes / "platforms" / "pairing" / "slack-approved.json"):
                    path.unlink(missing_ok=True)
                arrange()
                self.assertFalse(self.owner())

    def test_a_harmless_config_names_the_owner(self) -> None:
        os.environ["SLACK_ALLOWED_USERS"] = SLACK_OWNER
        (self.hermes / "config.yaml").write_text("slack:\n  dm_policy: pairing\n  allow_from: []\n  require_mention: true\n", encoding="utf-8")
        self.assertTrue(self.owner())

    def test_the_global_allowlist_adds_people_and_counts_only_its_platforms_shapes(self) -> None:
        # Another person in either list: two people, so no owner.
        os.environ["SLACK_ALLOWED_USERS"] = SLACK_OWNER
        os.environ["GATEWAY_ALLOWED_USERS"] = "U02OTHER"
        self.assertFalse(self.owner())
        os.environ["SLACK_ALLOWED_USERS"] = "U02OTHER"
        os.environ["GATEWAY_ALLOWED_USERS"] = SLACK_OWNER
        self.assertFalse(self.owner())
        # One global list naming the owner on two platforms names each once.
        del os.environ["SLACK_ALLOWED_USERS"]
        os.environ["GATEWAY_ALLOWED_USERS"] = f"{SLACK_OWNER},{TELEGRAM_OWNER},+15559990000"
        self.assertTrue(self.owner())
        self.assertTrue(self.owner("telegram", TELEGRAM_OWNER, TELEGRAM_OWNER), "a +phone is no Telegram id")
        # Bare digits fit Telegram and WhatsApp alike, so they count for both.
        os.environ["GATEWAY_ALLOWED_USERS"] = f"{SLACK_OWNER},{TELEGRAM_OWNER},15559990000"
        self.assertTrue(self.owner())
        self.assertFalse(self.owner("telegram", TELEGRAM_OWNER, TELEGRAM_OWNER))
        os.environ["GATEWAY_ALLOWED_USERS"] = f"{SLACK_OWNER},*"
        self.assertFalse(self.owner(), "a wildcard opens every platform")

    def test_hermes_files_are_read_never_written(self) -> None:
        self.write_env(SLACK_ALLOWED_USERS=SLACK_OWNER)
        pairing = self.write_pairing("slack", SLACK_OWNER)
        (self.hermes / "config.yaml").write_text("model: x\n", encoding="utf-8")
        before = {path: path.read_bytes() for path in self.hermes.rglob("*") if path.is_file()}
        live = self.gateway("owner", "slack", chat_type="dm", chat_id=SLACK_DM, user_id=SLACK_OWNER)
        self.turn(live, 1, "hello", author_id=SLACK_OWNER)
        self.capture("owner", "The owner keeps the on-call rota in the team calendar.")
        live.shutdown()
        self.assertEqual({path: path.read_bytes() for path in self.hermes.rglob("*") if path.is_file()}, before)
        self.assertTrue(pairing.is_file())


class OwnerDmTests(_Messenger):
    """#2088: the owner's own Slack DM reads and writes the memory the CLI has."""

    def owner_dm(self, session_id: str = "slack-dm") -> OmhMemoryProvider:
        return self.gateway(session_id, "slack", chat_type="dm", chat_id=SLACK_DM, user_id=SLACK_OWNER, thread_id="1760000000.000100")

    def assert_recalls_cli_memory(self) -> None:
        record_id = self.owner_capture("The owner deploys the billing service only on Tuesday mornings.")
        live = self.owner_dm()
        pack = self.turn(live, 1, "when does the billing service deploy", author_id=SLACK_OWNER)
        self.assertEqual(rendered_ids(pack), [record_id])
        status = live.recall_status()
        assert status is not None
        self.assertEqual((status.provider_label, status.count), ("OMH", 1), "the recall line shows")

    def test_issue_2088_single_user_through_slack_allowed_users(self) -> None:
        os.environ["SLACK_ALLOWED_USERS"] = SLACK_OWNER
        self.assert_recalls_cli_memory()

    def test_issue_2088_single_user_through_the_pairing_store(self) -> None:
        self.write_pairing("slack", SLACK_OWNER)
        self.assert_recalls_cli_memory()

    def test_without_an_owner_the_same_dm_recalls_none_of_it(self) -> None:
        record_id = self.owner_capture("The owner deploys the billing service only on Tuesday mornings.")
        pack = self.turn(self.owner_dm(), 1, "when does the billing service deploy", author_id=SLACK_OWNER)
        self.assertNotIn(record_id, pack)

    def test_the_owner_dm_writes_what_the_cli_reads_and_gets_the_console_extras(self) -> None:
        os.environ["SLACK_ALLOWED_USERS"] = SLACK_OWNER
        write_memory_block(self.home, approve_memory_block(build_memory_block("operator", "The operator's always-on note.")))
        live = self.owner_dm()
        pack = self.turn(live, 1, "hello", author_id=SLACK_OWNER)
        self.assertIn("always-on note", pack)
        self.assertEqual(self.tool("blocks", "slack-dm")["block_count"], 1)
        captured = self.capture("slack-dm", "The owner prefers short status updates in the morning.")
        self.assertEqual(self.record(captured["record_id"])["scope"], {"kind": "user-global", "ref": "default"})
        self.assertEqual(self.record(captured["record_id"])["schema_version"], "project_memory_record/v2")
        cli = self.console("cli-later")
        self.assertIn(captured["record_id"], rendered_ids(self.turn(cli, 1, "status updates in the morning")))
        write_memory(self.hermes, "MEMORY.md", FACT, entry(1))
        self.assertEqual(self.tool("demote", "slack-dm", entry_sha256=sha(FACT)[:12])["status"], "demoted")

    def test_the_owner_dm_serves_the_digest(self) -> None:
        os.environ["SLACK_ALLOWED_USERS"] = SLACK_OWNER
        write_session_close(self.home, at=datetime.now(timezone.utc) - timedelta(hours=3))
        inside = stamp(datetime.now(timezone.utc) - timedelta(hours=2))
        write_record(self.home, "rec-a", created_at=inside, source="hermes_model", scope={"kind": "user-global", "ref": "default"})
        self.assertIsNotNone(digest_attributes(self.turn(self.owner_dm(), 1, "hello", author_id=SLACK_OWNER)))

    def test_pairing_a_second_person_mid_session_ends_the_owners_dm_at_the_next_turn(self) -> None:
        pairing = self.write_pairing("slack", SLACK_OWNER)
        record_id = self.owner_capture("The owner deploys the billing service only on Tuesday mornings.")
        live = self.owner_dm()
        self.assertIn(record_id, self.turn(live, 1, "billing service deploy", author_id=SLACK_OWNER))
        pairing.write_text(json.dumps({SLACK_OWNER: {}, "U02GUEST": {}}), encoding="utf-8")
        os.utime(pairing, ns=(pairing.stat().st_atime_ns, pairing.stat().st_mtime_ns + 1_000_000_000))
        pack = self.turn(live, 2, "billing service deploy", author_id=SLACK_OWNER)
        self.assertNotIn(record_id, pack)
        self.assertEqual(live._surface_class, SURFACE_DIRECT)
        self.assertEqual(read_session_lens(self.home, "slack-dm")["surface_class"], SURFACE_DIRECT)


class PerTurnBindingTests(_Messenger):
    """A turn written by anyone but the DM partner, or by a bot, is shared for that turn."""

    def setUp(self) -> None:
        super().setUp()
        os.environ["SLACK_ALLOWED_USERS"] = SLACK_OWNER
        self.record_id = self.owner_capture("The owner deploys the billing service only on Tuesday mornings.")
        self.live = self.gateway("slack-dm", "slack", chat_type="dm", chat_id=SLACK_DM, user_id=SLACK_OWNER)

    def assert_turn_is_shared(self, number: int, **author: object) -> None:
        pack = self.turn(self.live, number, "billing service deploy", **author)
        self.assertNotIn(self.record_id, pack)
        self.assertEqual(read_session_lens(self.home, "slack-dm")["surface_class"], SURFACE_SHARED)
        before = self.store_bytes()
        refused = self.tool("capture", "slack-dm", summary="Someone else says the billing deploy moved to Fridays.")
        self.assertEqual((refused["status"], refused["reason"]), ("refused", "shared_surface_writes_refused"))
        self.assertEqual(self.tool("blocks", "slack-dm")["reason"], "shared_surface_reads_refused")
        self.assertEqual(self.store_bytes(), before)

    def test_an_author_mismatch_is_shared_for_that_turn_only(self) -> None:
        self.assertIn(self.record_id, self.turn(self.live, 1, "billing service deploy", author_id=SLACK_OWNER))
        self.assert_turn_is_shared(2, author_id="U03INTRUDER")
        self.assertIn(self.record_id, self.turn(self.live, 3, "billing service deploy", author_id=SLACK_OWNER))

    def test_a_bot_author_is_shared(self) -> None:
        self.assert_turn_is_shared(1, author_id=SLACK_OWNER, author_is_bot=True)

    def test_a_session_rotated_mid_turn_keeps_the_turns_binding(self) -> None:
        # A compression rotates the id inside the intruder's turn; the new id
        # is bound by that same turn's author, never by a default partner.
        self.assert_turn_is_shared(1, author_id="U03INTRUDER")
        self.live.on_session_switch("slack-dm-compressed", parent_session_id="slack-dm", reset=False)
        self.assertEqual(self.live._surface_class, SURFACE_SHARED)
        self.assertEqual(read_session_lens(self.home, "slack-dm-compressed")["surface_class"], SURFACE_SHARED)
        self.assertNotIn(self.record_id, self.live.prefetch("billing service deploy", session_id="slack-dm-compressed"))
        before = self.store_bytes()
        refused = self.tool("capture", "slack-dm-compressed", summary="Someone else says the billing deploy moved to Fridays.")
        self.assertEqual(refused["reason"], "shared_surface_writes_refused")
        self.assertEqual(self.store_bytes(), before)
        # The next turn by the partner is the owner's again.
        self.assertIn(self.record_id, self.turn(self.live, 2, "billing service deploy", author_id=SLACK_OWNER))

    def test_a_turn_with_no_author_is_the_partners(self) -> None:
        self.assertIn(self.record_id, self.turn(self.live, 1, "billing service deploy"))

    def test_a_shared_turn_does_not_spend_the_owners_digest(self) -> None:
        write_session_close(self.home, at=datetime.now(timezone.utc) - timedelta(hours=3))
        inside = stamp(datetime.now(timezone.utc) - timedelta(hours=2))
        write_record(self.home, "rec-a", created_at=inside, source="hermes_model", scope={"kind": "user-global", "ref": "default"})
        live = self.gateway("slack-dm-2", "slack", chat_type="dm", chat_id=SLACK_DM, user_id=SLACK_OWNER)
        self.assertIsNone(digest_attributes(self.turn(live, 1, "hello", author_id=SLACK_OWNER, author_is_bot=True)))
        self.assertIsNotNone(digest_attributes(self.turn(live, 2, "hello", author_id=SLACK_OWNER)))


class OtherPeoplesDmTests(_Messenger):
    """With two authorized users, each DM reads and writes only its own person's memory."""

    ALICE, BOB = "U01ALICE", "U02BOB"

    def setUp(self) -> None:
        super().setUp()
        os.environ["SLACK_ALLOWED_USERS"] = f"{self.ALICE},{self.BOB}"
        self.owner_record = self.owner_capture("The release passwords live on the operator's hardware key.")

    def dm(self, user_id: str, session_id: str) -> OmhMemoryProvider:
        return self.gateway(session_id, "slack", chat_type="dm", chat_id=f"D0{user_id}", user_id=user_id)

    def test_each_dm_sees_only_its_own_captures_and_never_the_owners(self) -> None:
        alice, bob = self.dm(self.ALICE, "alice-1"), self.dm(self.BOB, "bob-1")
        self.turn(alice, 1, "hi", author_id=self.ALICE)
        self.turn(bob, 1, "hi", author_id=self.BOB)
        alice_record = self.capture("alice-1", "Alice prefers release notes as a bulleted list.")["record_id"]
        bob_record = self.capture("bob-1", "Bob prefers release notes as a single paragraph.")["record_id"]
        stored = self.record(alice_record)
        self.assertEqual(stored["schema_version"], "project_memory_record/v3")
        self.assertEqual(stored["scope"]["kind"], "user")
        self.assertEqual(stored["identity"]["subject_principal"], stored["scope"]["ref"])
        for live, author, session_id, own, other in ((alice, self.ALICE, "alice-1", alice_record, bob_record), (bob, self.BOB, "bob-1", bob_record, alice_record)):
            with self.subTest(author=author):
                pack = self.turn(live, 2, "release notes passwords", author_id=author)
                self.assertEqual(rendered_ids(pack), [own])
                recalled = self.tool("recall", session_id, query="release notes passwords")
                self.assertEqual([row["record_id"] for row in recalled["records"]], [own])
                self.assertNotIn(other, json.dumps(recalled))
                self.assertNotIn(self.owner_record, json.dumps(recalled))
        # A later session in Alice's DM is still Alice.
        again = self.dm(self.ALICE, "alice-2")
        self.assertEqual(rendered_ids(self.turn(again, 1, "release notes", author_id=self.ALICE)), [alice_record])
        # The console never sees a person's DM memory.
        self.assertNotIn(alice_record, self.turn(self.console("cli-2"), 1, "release notes"))

    def test_a_person_may_correct_and_retire_only_their_own(self) -> None:
        alice, bob = self.dm(self.ALICE, "alice-1"), self.dm(self.BOB, "bob-1")
        self.turn(alice, 1, "hi", author_id=self.ALICE)
        self.turn(bob, 1, "hi", author_id=self.BOB)
        alice_record = self.capture("alice-1", "Alice prefers release notes as a bulleted list.")["record_id"]
        before = self.store_bytes()
        for action, args in (("retire", {"reason": "no_longer_true"}), ("correct", {"summary": "Bob rewrote it."}), ("confirm", {})):
            with self.subTest(action=action):
                refused = self.tool(action, "bob-1", record_id=alice_record, **args)
                self.assertEqual((refused["status"], refused["reason"]), ("refused", "record_not_in_scope"), refused)
                owner_refused = self.tool(action, "bob-1", record_id=self.owner_record, **args)
                self.assertEqual(owner_refused["reason"], "record_not_in_scope")
        self.assertEqual(self.store_bytes(), before)
        corrected = self.tool("correct", "alice-1", record_id=alice_record, summary="Alice prefers release notes as a numbered list.")
        self.assertEqual(corrected["status"], "corrected", corrected)
        self.assertEqual(self.record(corrected["record_id"])["schema_version"], "project_memory_record/v3")

    def test_a_record_shared_with_an_audience_is_read_but_never_rewritten(self) -> None:
        alice = self.dm(self.ALICE, "alice-1")
        self.turn(alice, 1, "hi", author_id=self.ALICE)
        context = read_session_lens(self.home, "alice-1")["principal_context"]
        shared = capture_project_memory_candidate(
            self.home, "The shared runbook lives in the team wiki.", scope_kind="thread", scope_ref="alice-1",
            principal_context=context, audience_principals=[context["principal"]], source="hermes_model", on_duplicate="skip",
        )["record"]["record_id"]
        self.assertEqual(self.record(shared)["identity"]["audience"]["kind"], "explicit_principals")
        recalled = self.tool("recall", "alice-1", query="shared runbook team wiki")
        self.assertEqual([row["record_id"] for row in recalled["records"]], [shared])
        before = self.store_bytes()
        for action, args in (("retire", {"reason": "no_longer_true"}), ("correct", {"summary": "The runbook moved."}), ("confirm", {})):
            with self.subTest(action=action):
                refused = self.tool(action, "alice-1", record_id=shared, **args)
                self.assertEqual((refused["status"], refused["reason"]), ("refused", "unsupported_record_schema"), refused)
        self.assertEqual(self.store_bytes(), before)

    def test_only_a_persons_own_user_record_is_theirs_to_rewrite(self) -> None:
        # Both halves of the rule, each on a record whose other half holds:
        # a user-scope record shared with an audience, and a subject-only
        # record outside user scope. The lens reaches both.
        alice = self.dm(self.ALICE, "alice-1")
        self.turn(alice, 1, "hi", author_id=self.ALICE)
        context = read_session_lens(self.home, "alice-1")["principal_context"]
        audience = capture_project_memory_candidate(
            self.home, "The shared runbook lives in the team wiki.", scope_kind="thread", scope_ref="alice-1",
            principal_context=context, audience_principals=[context["principal"]], source="hermes_model", on_duplicate="skip",
        )["record"]["record_id"]
        own = self.capture("alice-1", "Alice prefers release notes as a bulleted list.")["record_id"]
        for record_id, scope in ((audience, {"kind": "user", "ref": context["principal"]}), (own, {"kind": "thread", "ref": "alice-1"})):
            path = self.home / "memory" / "records" / f"{record_id}.json"
            path.write_text(json.dumps({**self.record(record_id), "scope": scope}), encoding="utf-8")
        before = self.store_bytes()
        for record_id in (audience, own):
            for action, args in (("confirm", {}), ("retire", {"reason": "no_longer_true"})):
                with self.subTest(record_id=record_id, action=action):
                    refused = self.tool(action, "alice-1", record_id=record_id, **args)
                    self.assertEqual((refused["status"], refused["reason"]), ("refused", "unsupported_record_schema"), refused)
        self.assertEqual(self.store_bytes(), before)

    def test_refusals_in_a_persons_dm_write_nothing(self) -> None:
        write_memory(self.hermes, "MEMORY.md", FACT, entry(1))
        write_memory_block(self.home, approve_memory_block(build_memory_block("operator", "The operator's always-on note.")))
        alice = self.dm(self.ALICE, "alice-1")
        pack = self.turn(alice, 1, "hello", author_id=self.ALICE)
        for marker in ("<memory_blocks", "<memory_block_index", "omh reminder:", "<memory_consolidation", "<memory_digest", "always-on note"):
            self.assertNotIn(marker, pack)
        before, hermes_before = self.store_bytes(), (self.hermes / "memories" / "MEMORY.md").read_bytes()
        project = self.tool("capture", "alice-1", summary="The project deploys from main.", scope="project")
        self.assertEqual((project["status"], project["reason"]), ("refused", "scope_unavailable_here"))
        demoted = self.tool("demote", "alice-1", entry_sha256=sha(FACT)[:12])
        self.assertEqual((demoted["status"], demoted["reason"]), ("refused", "demote_owner_only"))
        self.assertNotIn("remove_from_hermes", demoted)
        self.assertEqual(self.tool("blocks", "alice-1")["reason"], "shared_surface_reads_refused")
        self.assertEqual(self.tool("read", "alice-1", label="operator")["reason"], "shared_surface_reads_refused")
        self.assertEqual(self.store_bytes(), before)
        self.assertEqual((self.hermes / "memories" / "MEMORY.md").read_bytes(), hermes_before)


class GroupChannelTests(_Messenger):
    """A group conversation reads and writes only its own channel's memory."""

    def setUp(self) -> None:
        super().setUp()
        os.environ["SLACK_ALLOWED_USERS"] = SLACK_OWNER
        self.owner_record = self.owner_capture("The release passwords live on the operator's hardware key.")

    def channel(self, session_id: str, chat_id: str = SLACK_TEAM, user_id: str = SLACK_OWNER, **extra: object) -> OmhMemoryProvider:
        return self.gateway(session_id, "slack", chat_type="group", chat_id=chat_id, user_id=user_id, **extra)

    def test_a_channel_capture_is_recalled_in_that_channel_only(self) -> None:
        team = self.channel("team-owner")
        self.turn(team, 1, "hi", author_id=SLACK_OWNER)
        captured = self.capture("team-owner", "The team standup moved to 10:30 on weekdays.")
        stored = self.record(captured["record_id"])
        self.assertEqual(stored["scope"]["kind"], "channel")
        self.assertEqual(stored["scope"], read_session_lens(self.home, "team-owner")["channel_scope"])
        self.assertEqual(stored["schema_version"], "project_memory_record/v2")
        # Another member's session in the same channel, and a thread there.
        teammate = self.channel("team-teammate", user_id="U05MATE")
        self.assertEqual(rendered_ids(self.turn(teammate, 1, "when is the standup", author_id="U05MATE")), [captured["record_id"]])
        thread = self.channel("team-thread", thread_id="1760000000.000300")
        self.assertEqual(rendered_ids(self.turn(thread, 1, "when is the standup", author_id=SLACK_OWNER)), [captured["record_id"]])
        # Not in another channel, the owner's DM, or the console.
        other = self.channel("other-team", chat_id=SLACK_OTHER_TEAM)
        dm = self.gateway("owner-dm", "slack", chat_type="dm", chat_id=SLACK_DM, user_id=SLACK_OWNER)
        for live, author in ((other, SLACK_OWNER), (dm, SLACK_OWNER), (self.console("cli-2"), None)):
            with self.subTest(session=live._session_id):
                pack = self.turn(live, 1, "when is the standup", author_id=author)
                self.assertNotIn(captured["record_id"], pack)
        self.assertNotIn(captured["record_id"], json.dumps(self.tool("recall", "other-team", query="standup weekdays")))
        self.assertNotIn(captured["record_id"], json.dumps(self.tool("recall", "owner-dm", query="standup weekdays")))

    def test_the_owners_memory_never_appears_and_the_extras_stay_out(self) -> None:
        write_memory_block(self.home, approve_memory_block(build_memory_block("operator", "The operator's always-on note.")))
        write_memory(self.hermes, "MEMORY.md", *[entry(index) for index in range(10)])
        write_session_close(self.home, at=datetime.now(timezone.utc) - timedelta(hours=3))
        team = self.channel("team-owner")
        pack = self.turn(team, 1, "release passwords hardware key", author_id=SLACK_OWNER)
        self.assertNotIn(self.owner_record, pack)
        for marker in ("<memory_blocks", "<memory_block_index", "omh reminder:", "<memory_consolidation", "<demote ", "<memory_digest", "always-on note"):
            self.assertNotIn(marker, pack)
        recalled = self.tool("recall", "team-owner", query="release passwords hardware key")
        self.assertEqual(recalled["status"], "nothing_found")

    def test_channel_refusals_write_nothing(self) -> None:
        write_memory(self.hermes, "MEMORY.md", FACT, entry(1))
        self.channel("team-owner")
        before = self.store_bytes()
        for scope in ("user", "project"):
            with self.subTest(scope=scope):
                refused = self.tool("capture", "team-owner", summary="The owner's own fact said in a group.", scope=scope)
                self.assertEqual((refused["status"], refused["reason"]), ("refused", "scope_unavailable_here"))
        self.assertEqual(self.tool("demote", "team-owner", entry_sha256=sha(FACT)[:12])["reason"], "demote_owner_only")
        self.assertEqual(self.tool("blocks", "team-owner")["reason"], "shared_surface_reads_refused")
        self.assertEqual(self.tool("retire", "team-owner", record_id=self.owner_record, reason="no_longer_true")["reason"], "record_not_in_scope")
        self.assertEqual(self.store_bytes(), before)

    def test_telegram_topics_share_channel_but_unverified_discord_threads_do_not(self) -> None:
        # Telegram: a forum topic is the group's; Slack: covered above.
        group = self.gateway("tg-group", "telegram", chat_type="group", chat_id="-1001234567890", user_id=TELEGRAM_OWNER)
        topic = self.gateway("tg-topic", "telegram", chat_type="group", chat_id="-1001234567890", user_id="5550001", thread_id="7")
        self.assertEqual(group._channel_scope, topic._channel_scope)
        # Discord delivers a thread under its own channel id: its own scope.
        parent = self.gateway("dc-parent", "discord", chat_type="group", chat_id="1111111111111111111", user_id=DISCORD_OWNER)
        thread = self.gateway("dc-thread", "discord", chat_type="thread", chat_id="2222222222222222222", user_id=DISCORD_OWNER, thread_id="2222222222222222222")
        self.assertNotEqual(parent._channel_scope, thread._channel_scope)
        # The same chat id on another platform is another channel.
        self.assertNotEqual(group._channel_scope, self.gateway("x", "discord", chat_type="group", chat_id="1234567890123", user_id=DISCORD_OWNER)._channel_scope)

    def test_a_channel_gets_no_digest_even_of_its_own_records(self) -> None:
        scope = self.channel("probe")._channel_scope
        write_session_close(self.home, at=datetime.now(timezone.utc) - timedelta(hours=3))
        inside = stamp(datetime.now(timezone.utc) - timedelta(hours=2))
        write_record(self.home, "rec-channel", created_at=inside, source="hermes_model", scope=scope)
        self.assertIsNone(digest_attributes(self.turn(self.channel("team-later"), 1, "hello", author_id=SLACK_OWNER)))

    def test_a_declared_allowlist_names_a_channel_only_as_the_packs_own_scope(self) -> None:
        channel = {"kind": "channel", "ref": "channel:v1:" + "c" * 64}
        other = {"kind": "channel", "ref": "channel:v1:" + "d" * 64}
        project = {"kind": "project", "ref": "prj:" + "a" * 64}
        thread = {"kind": "thread", "ref": "session-1"}
        self.assertEqual(scope_allowlist_errors([channel], channel, "pack"), [])
        self.assertEqual(scope_allowlist_errors([channel, thread], channel, "pack"), [])
        self.assertTrue(scope_allowlist_errors([channel, other], channel, "pack"), "one channel at most")
        self.assertTrue(scope_allowlist_errors([other], channel, "pack"), "another channel")
        self.assertTrue(scope_allowlist_errors([{"kind": "user-global", "ref": "default"}, project, channel], project, "pack"), "a channel beside a project")
        # A channel's pack is the channel's: no person's memory beside it.
        for personal in ({"kind": "user-global", "ref": "default"}, {"kind": "user", "ref": "principal:v1:" + "e" * 64}):
            with self.subTest(personal=personal["kind"]):
                errors = scope_allowlist_errors([personal, channel], channel, "pack")
                self.assertTrue(any("beside a channel" in error for error in errors), errors)

    def test_the_principal_gate_admits_only_the_named_channel(self) -> None:
        channel = {"kind": "channel", "ref": "channel:v1:" + "c" * 64}
        other = {"kind": "channel", "ref": "channel:v1:" + "d" * 64}
        record = {"schema_version": "project_memory_record/v2", "record_id": "r", "scope": channel}
        self.assertTrue(principal_recall_decision(record, None, shared_surface=True, channel_scopes=[channel])["allowed"])
        self.assertFalse(principal_recall_decision(record, None, shared_surface=True, channel_scopes=[other])["allowed"])
        self.assertFalse(principal_recall_decision(record, None, shared_surface=True)["allowed"])
        # A channel label names a channel only: a project record under it stays out.
        project = {**record, "scope": {"kind": "project", "ref": channel["ref"]}}
        self.assertFalse(principal_recall_decision(project, None, shared_surface=True, channel_scopes=[channel, project["scope"]])["allowed"])
        # A principal's export or lifecycle operation never reaches a channel's records.
        self.assertFalse(principal_operation_decision(record, None)["allowed"])

    def test_a_bot_turn_in_a_channel_is_shared(self) -> None:
        team = self.channel("team-owner")
        self.turn(team, 1, "hi", author_id="B0BOT", author_is_bot=True)
        before = self.store_bytes()
        refused = self.tool("capture", "team-owner", summary="A bot says the standup moved.")
        self.assertEqual(refused["reason"], "shared_surface_writes_refused")
        self.assertEqual(self.store_bytes(), before)


class DiscordThreadScopeTests(_Messenger):
    """Only threads Hermes auto-created share the parent channel's memory."""

    PARENT = "1111111111111111111"
    OTHER_PARENT = "4444444444444444444"
    THREAD_A = "2222222222222222222"
    THREAD_B = "3333333333333333333"
    OTHER_THREAD = "5555555555555555555"

    def write_thread_origin(self, session_id: str, chat_id: str, parent_chat_id: str, **provenance: object) -> None:
        origin = {"platform": "discord", "chat_type": "thread", "chat_id": chat_id, "parent_chat_id": parent_chat_id, **provenance}
        # Default rollback journaling leaves no WAL sidecars for the reader.
        with closing(sqlite3.connect(self.hermes / "state.db")) as connection:
            with connection:
                connection.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, origin_json TEXT)")
                connection.execute("INSERT INTO sessions (id, origin_json) VALUES (?, ?)", (session_id, json.dumps(origin)))

    def thread(self, session_id: str, chat_id: str) -> OmhMemoryProvider:
        return self.gateway(session_id, "discord", chat_type="thread", chat_id=chat_id, thread_id=chat_id, user_id=DISCORD_OWNER)

    def test_auto_threads_share_only_their_parent_channel_scope(self) -> None:
        for session_id, chat_id, parent_id in (
            ("dc-thread-a", self.THREAD_A, self.PARENT),
            ("dc-thread-b", self.THREAD_B, self.PARENT),
            ("dc-other-thread", self.OTHER_THREAD, self.OTHER_PARENT),
        ):
            self.write_thread_origin(session_id, chat_id, parent_id, auto_thread_created=True)
        parent = self.gateway("dc-parent", "discord", chat_type="group", chat_id=self.PARENT, user_id=DISCORD_OWNER)
        first = self.thread("dc-thread-a", self.THREAD_A)
        second = self.thread("dc-thread-b", self.THREAD_B)
        other = self.thread("dc-other-thread", self.OTHER_THREAD)
        for live, chat_id in ((first, self.THREAD_A), (second, self.THREAD_B)):
            with self.subTest(session=live._session_id):
                self.assertEqual(live._channel_scope, parent._channel_scope)
                self.assertEqual(live._conversation.chat_id, chat_id, "only the scope changes, not the conversation")
                self.assertEqual(live._surface_class, SURFACE_CHANNEL)
                self.assertIsNone(live._principal_context)
                self.assertEqual(read_session_lens(self.home, live._session_id)["channel_scope"], parent._channel_scope)
        self.assertNotEqual(other._channel_scope, parent._channel_scope)

    def test_remember_in_one_auto_thread_prefetches_in_the_next_but_not_another_channel(self) -> None:
        self.write_thread_origin("dc-thread-a", self.THREAD_A, self.PARENT, auto_thread_created=True)
        self.write_thread_origin("dc-thread-b", self.THREAD_B, self.PARENT, auto_thread_created=True)
        self.write_thread_origin("dc-other-thread", self.OTHER_THREAD, self.OTHER_PARENT, auto_thread_created=True)
        first = self.thread("dc-thread-a", self.THREAD_A)
        self.turn(first, 1, "Channel reviews use the release checklist.", author_id=DISCORD_OWNER)
        saved = json.loads(first.handle_tool_call("omh_remember", {"action": "save", "summary": "Channel reviews use the release checklist."}))
        self.assertEqual((saved["status"], saved["action"], saved["plugin_tool"]), ("remembered", "save", "omh_remember"), saved)
        record_id = saved["record_id"]
        record = self.record(record_id)
        self.assertEqual(record["scope"], first._channel_scope)
        self.assertEqual(record["source_ref"], "hermes-session:dc-thread-a")
        second = self.thread("dc-thread-b", self.THREAD_B)
        self.assertEqual(rendered_ids(self.turn(second, 1, "release checklist", author_id=DISCORD_OWNER)), [record_id])
        parent = self.gateway("dc-parent", "discord", chat_type="group", chat_id=self.PARENT, user_id=DISCORD_OWNER)
        self.assertEqual(rendered_ids(self.turn(parent, 1, "release checklist", author_id=DISCORD_OWNER)), [record_id])
        unrelated = self.gateway("dc-other-parent", "discord", chat_type="group", chat_id=self.OTHER_PARENT, user_id=DISCORD_OWNER)
        for live in (unrelated, self.thread("dc-other-thread", self.OTHER_THREAD), self.thread("dc-plain-thread", self.THREAD_A)):
            with self.subTest(session=live._session_id):
                self.assertNotIn(record_id, self.turn(live, 1, "release checklist", author_id=DISCORD_OWNER))

    def test_threads_without_auto_creation_provenance_keep_their_own_scope(self) -> None:
        parent = self.gateway("dc-parent", "discord", chat_type="group", chat_id=self.PARENT, user_id=DISCORD_OWNER)
        plain = self.thread("dc-no-row", self.THREAD_A)
        self.assertNotEqual(plain._channel_scope, parent._channel_scope)
        for session_id, provenance in (("dc-no-marker", {}), ("dc-manual-thread", {"auto_thread_created": False})):
            with self.subTest(session=session_id):
                self.write_thread_origin(session_id, self.THREAD_A, self.PARENT, **provenance)
                live = self.thread(session_id, self.THREAD_A)
                self.assertEqual(live._channel_scope, plain._channel_scope)
                self.assertNotEqual(live._channel_scope, parent._channel_scope)

    def test_a_failed_store_keeps_the_thread_on_its_own_scope(self) -> None:
        (self.hermes / "state.db").mkdir()
        live = self.thread("dc-thread-a", self.THREAD_A)
        expected = derive_channel_ref(self.home, profile_ref="default", surface_ref="discord", channel_identity=self.THREAD_A)
        self.assertEqual(live._channel_scope, {"kind": "channel", "ref": expected})
        self.assertTrue((self.hermes / "state.db").is_dir())

    def test_slack_and_telegram_keep_their_scope_without_a_parent_lookup(self) -> None:
        (self.hermes / "state.db").mkdir()
        with patch("omh.plugin_bundle.omh.memory_provider.auto_thread_parent_channel", side_effect=AssertionError("non-Discord store read")) as lookup:
            for platform, chat_id, author in (("slack", SLACK_TEAM, SLACK_OWNER), ("telegram", "-1001234567890", TELEGRAM_OWNER)):
                with self.subTest(platform=platform):
                    group = self.gateway(f"{platform}-group", platform, chat_type="group", chat_id=chat_id, user_id=author)
                    topic = self.gateway(f"{platform}-topic", platform, chat_type="group", chat_id=chat_id, user_id=author, thread_id="7")
                    expected = derive_channel_ref(self.home, profile_ref="default", surface_ref=platform, channel_identity=chat_id)
                    self.assertEqual(group._channel_scope, {"kind": "channel", "ref": expected})
                    self.assertEqual(topic._channel_scope, group._channel_scope)
            lookup.assert_not_called()

    def test_compression_keeps_the_parent_scope_without_another_store_read(self) -> None:
        self.write_thread_origin("dc-thread-a", self.THREAD_A, self.PARENT, auto_thread_created=True)
        live = self.thread("dc-thread-a", self.THREAD_A)
        expected = dict(live._channel_scope)
        with patch("omh.plugin_bundle.omh.memory_provider.auto_thread_parent_channel", side_effect=AssertionError("scope re-derived during compression")) as lookup:
            live.on_session_switch("dc-compressed", parent_session_id="dc-thread-a", reset=False)
            self.turn(live, 1, "release checklist", author_id=DISCORD_OWNER)
            lookup.assert_not_called()
        self.assertEqual(live._channel_scope, expected)
        self.assertEqual(live._conversation.chat_id, self.THREAD_A)
        self.assertEqual(read_session_lens(self.home, "dc-compressed")["channel_scope"], expected)

    def test_a_late_origin_does_not_widen_the_scope_mid_conversation(self) -> None:
        live = self.thread("dc-thread-a", self.THREAD_A)
        expected = dict(live._channel_scope)
        self.write_thread_origin("dc-thread-a", self.THREAD_A, self.PARENT, auto_thread_created=True)
        with patch("omh.plugin_bundle.omh.memory_provider.auto_thread_parent_channel", side_effect=AssertionError("late origin lookup")) as lookup:
            self.turn(live, 1, "release checklist", author_id=DISCORD_OWNER)
            live.on_session_switch("dc-compressed", parent_session_id="dc-thread-a", reset=False)
            lookup.assert_not_called()
        self.assertEqual(live._channel_scope, expected)
        self.assertEqual(read_session_lens(self.home, "dc-compressed")["channel_scope"], expected)


class HandoffTests(_Messenger):
    """A chat-built coding handoff carries only what its chat may see, read from that chat's lens."""

    def setUp(self) -> None:
        super().setUp()
        self.paths = resolve_paths(self.home, self.hermes)
        os.environ["SLACK_ALLOWED_USERS"] = f"{SLACK_OWNER},U01ALICE"
        self.owner_record = self.owner_capture("The release checklist lives on the operator's hardware key.")
        self.team = self.gateway("team", "slack", chat_type="group", chat_id=SLACK_TEAM, user_id="U01ALICE")
        self.team_record = self.capture("team", "The release checklist for the team is pinned in the channel.")["record_id"]
        self.alice = self.gateway("alice", "slack", chat_type="dm", chat_id="D0ALICE", user_id="U01ALICE")
        self.turn(self.alice, 1, "hi", author_id="U01ALICE")
        self.alice_record = self.capture("alice", "Alice keeps her release checklist in a notebook.")["record_id"]

    def carried(self, hermes_session_id: str = "") -> set[str]:
        pack = memory_recall_pack_for_handoff(self.paths, "release checklist", hermes_session_id=hermes_session_id)
        return {str(row["record_id"]) for row in (pack or {}).get("included_records", [])}

    def owner_dm(self) -> None:
        os.environ["SLACK_ALLOWED_USERS"] = SLACK_OWNER
        self.gateway("owner-dm", "slack", chat_type="dm", chat_id=SLACK_DM, user_id=SLACK_OWNER)

    def test_each_chat_carries_its_own_set(self) -> None:
        self.assertEqual(self.carried("team"), {self.team_record})
        self.assertEqual(self.carried("alice"), {self.alice_record})
        self.assertEqual(self.carried(""), set(), "no Hermes session: shared, nothing identity-unbound")
        self.assertEqual(self.carried("never-published"), set())
        self.owner_dm()
        self.assertEqual(self.carried("owner-dm"), {self.owner_record})

    def test_the_process_environment_never_names_the_chat(self) -> None:
        # In a gateway `HERMES_SESSION_ID` is process-wide and belongs to the
        # agent built or compressed last; here it names the owner's DM.
        self.owner_dm()
        self.gateway("quiet-group", "slack", chat_type="group", chat_id="C0QUIET", user_id="U01ALICE")
        with patch.dict(os.environ, {"HERMES_SESSION_ID": "owner-dm"}):
            self.assertIsNone(memory_recall_pack_for_handoff(self.paths, "release checklist", hermes_session_id="quiet-group"))
            self.assertEqual(self.carried(), set(), "in process, an unnamed session is shared")
            self.assertEqual(self.carried("team"), {self.team_record})

    def test_the_chat_tool_hands_each_chat_its_own_lens(self) -> None:
        # `omh_interact` runs inside the gateway: the tool's own `session_id`
        # names the chat, whatever the process environment says.
        self.owner_dm()
        message = "risky refactor of the release checklist in src/release.py"
        with patch.dict(os.environ, {"HERMES_SESSION_ID": "owner-dm"}):
            for session_id, expected, absent in (
                ("team", self.team_record, (self.owner_record, self.alice_record)),
                ("alice", self.alice_record, (self.owner_record, self.team_record)),
            ):
                for record_session in (False, True):
                    with self.subTest(session_id=session_id, record_session=record_session):
                        out = omh_interact_handler(
                            {"message": f"{message} for {session_id}", "source": "slack", "mode": "delegate", "record_session": record_session, "executor_target": "claude-code"},
                            session_id=session_id,
                        )
                        self.assertIn(expected, out)
                        for record_id in absent:
                            self.assertNotIn(record_id, out)

    def test_coding_delegate_reads_the_session_hermes_started_it_for(self) -> None:
        # A command Hermes starts gets its own session's `HERMES_SESSION_ID`
        # (`tools/environments/local.py`); that is the one place it is read.
        prefix = ["--omh-home", str(self.home), "--hermes-home", str(self.hermes)]
        message = "risky refactor of the release checklist in src/release.py"
        for hermes_session, expected, absent in (
            ("team", self.team_record, (self.owner_record, self.alice_record)),
            ("alice", self.alice_record, (self.owner_record, self.team_record)),
        ):
            with self.subTest(hermes_session=hermes_session), patch.dict(os.environ, {"HERMES_SESSION_ID": hermes_session, "HERMES_SESSION_PLATFORM": "slack"}):
                status, stdout, stderr = run_cli(prefix + ["coding", "delegate", "--executor", "claude-code", message])
                self.assertEqual(status, 0, stderr)
                self.assertIn(expected, stdout)
                for record_id in absent:
                    self.assertNotIn(record_id, stdout)

    def test_the_chat_commands_read_the_session_hermes_started_them_for(self) -> None:
        # `omh chat interact`, `chat session start` and `prepare-handoff` are
        # commands too: run from a messenger chat's terminal, they serve it.
        prefix = ["--omh-home", str(self.home), "--hermes-home", str(self.hermes)]
        message = "risky refactor of the release checklist in src/release.py"
        for hermes_session, expected, absent in (
            ("team", self.team_record, (self.owner_record, self.alice_record)),
            ("alice", self.alice_record, (self.owner_record, self.team_record)),
        ):
            with self.subTest(hermes_session=hermes_session), patch.dict(os.environ, {"HERMES_SESSION_ID": hermes_session}):
                outputs = []
                status, stdout, stderr = run_cli(
                    prefix + ["chat", "interact", "--source", "slack", "--mode", "delegate", "--executor", "claude-code", f"{message} via interact for {hermes_session}"]
                )
                self.assertEqual(status, 0, stderr)
                outputs.append(stdout)
                # A start that names a coding owner builds its handoff at once.
                status, stdout, stderr = run_cli(
                    prefix + ["chat", "session", "start", "--source", "slack", f"use codex to implement the release checklist fix in src/release.py for {hermes_session}"]
                )
                self.assertEqual(status, 0, stderr)
                outputs.append(stdout)
                status, stdout, stderr = run_cli(prefix + ["chat", "session", "start", "--source", "slack", f"{message} via session for {hermes_session}"])
                self.assertEqual(status, 0, stderr)
                session_id = json.loads(stdout)["session"]["session_id"]
                self.assertEqual(run_cli(prefix + ["chat", "session", "accept-plan", session_id])[0], 0)
                self.assertEqual(run_cli(prefix + ["chat", "session", "select-executor", session_id, "claude-code"])[0], 0)
                status, stdout, stderr = run_cli(prefix + ["chat", "session", "prepare-handoff", session_id, f"{message} via session for {hermes_session}"])
                self.assertEqual(status, 0, stderr)
                outputs.append(stdout)
                for output in outputs:
                    self.assertIn(expected, output)
                    for record_id in absent:
                        self.assertNotIn(record_id, output)

    def test_each_chats_pack_builds_a_coding_payload(self) -> None:
        # The owner's DM reads like a console: user-global records outside a
        # repository and a project's records inside one, the shapes the role
        # context pack's declared allowlist must hold. Each chat's pack must
        # survive the real payload and validate.
        self.owner_dm()
        for hermes_session, expected in (("owner-dm", {self.owner_record}), ("team", {self.team_record}), ("alice", {self.alice_record})):
            with self.subTest(hermes_session=hermes_session, store="outside a repository"):
                self.assert_payload_carries(self.paths, hermes_session, expected)
        # The same owner's DM with its OMH home inside a repository: a project
        # record and a user-global one, under one declared allowlist.
        repository = self.workspace.parent / "repo"
        seed_project_identity(repository)
        home = repository / ".omh"
        with patch.dict(os.environ, {"OMH_HOME": str(home)}):
            console = OmhMemoryProvider(home)
            console.initialize("cli-repo", platform="cli", hermes_home=str(self.hermes), agent_context="primary", cwd=str(repository))
            project = self.tool_in("capture", "cli-repo", repository, summary="The release checklist for this repository lives in docs/release.md.")
            personal = self.tool_in("capture", "cli-repo", repository, summary="The operator signs the release checklist with a hardware key.", scope="user")
            dm = OmhMemoryProvider(home)
            dm.initialize(
                "owner-dm-repo", platform="slack", hermes_home=str(self.hermes), agent_context="primary",
                chat_type="dm", chat_id=SLACK_DM, user_id=SLACK_OWNER, chat_name="a DM", cwd=str(repository),
            )
            with self.subTest(store="inside a repository"):
                pack = self.assert_payload_carries(resolve_paths(home, self.hermes), "owner-dm-repo", {project["record_id"], personal["record_id"]})
                self.assertEqual({row["scope"]["kind"] for row in pack["included_records"]}, {"project", "user-global"})

    def tool_in(self, action: str, session_id: str, cwd: Path, **args: object) -> dict:
        result = json.loads(omh_memory_handler({"action": action, **args}, cwd=str(cwd), session_id=session_id))
        self.assertEqual(result["status"], "remembered", result)
        return result

    def assert_payload_carries(self, paths, hermes_session: str, expected: set[str]) -> dict:
        pack = memory_recall_pack_for_handoff(paths, "release checklist", hermes_session_id=hermes_session)
        assert pack is not None
        self.assertEqual({str(row["record_id"]) for row in pack["included_records"]}, expected)
        self.assertEqual(validate_project_memory_recall_pack(pack), [])
        payload = build_coding_delegation_payload(
            "risky refactor of the release checklist", source="slack", executor_target="claude-code", memory_recall_pack=pack
        )
        for record_id in expected:
            self.assertIn(record_id, json.dumps(payload))
        return pack

    def test_the_wrapper_path_reads_the_session_it_is_given(self) -> None:
        message = "risky refactor of the release checklist"
        with patch.dict(os.environ, {"HERMES_SESSION_ID": "alice"}):
            for hermes_session, expected, absent in (
                ("alice", self.alice_record, (self.owner_record, self.team_record)),
                ("team", self.team_record, (self.owner_record, self.alice_record)),
            ):
                with self.subTest(hermes_session=hermes_session):
                    started = create_or_resume_wrapper_session(
                        self.paths, f"{message} {hermes_session}", source="slack", hermes_session_id=hermes_session
                    )
                    session_id = str(started["session"]["session_id"])
                    record_plan_decision(self.paths, session_id, "accept")
                    select_wrapper_session_executor(self.paths, session_id, "claude-code")
                    prepared = json.dumps(
                        prepare_wrapper_session_handoff(self.paths, session_id, f"{message} {hermes_session}", hermes_session_id=hermes_session)
                    )
                    self.assertIn(expected, prepared)
                    for record_id in absent:
                        self.assertNotIn(record_id, prepared)


class LensTests(_Messenger):
    def test_a_console_guest_under_a_dm_holds_no_binding(self) -> None:
        os.environ["SLACK_ALLOWED_USERS"] = f"{SLACK_OWNER},U01ALICE"
        owner = self.gateway("alice-dm", "slack", chat_type="dm", chat_id="D0ALICE", user_id="U01ALICE")
        self.turn(owner, 1, "hi", author_id="U01ALICE")
        published = read_session_lens(self.home, "alice-dm")
        # Hermes' hygiene and /compress agents load the provider as `cli` under the gateway id.
        guest = OmhMemoryProvider(self.home)
        guest.initialize("alice-dm", platform="cli", hermes_home=str(self.hermes), agent_context="primary", cwd=str(self.workspace))
        self.assertTrue(guest._guest)
        self.assertEqual(guest._surface_class, SURFACE_SHARED)
        self.assertIsNone(guest._principal_context)
        self.assertEqual(read_session_lens(self.home, "alice-dm")["instance"], published["instance"])
        guest.shutdown()
        self.assertIsNotNone(read_session_lens(self.home, "alice-dm"), "a guest never withdraws the owner's lens")

    def test_a_console_guest_under_the_owners_dm_reads_like_it_and_asks_nothing(self) -> None:
        os.environ["SLACK_ALLOWED_USERS"] = SLACK_OWNER
        self.gateway("owner-dm", "slack", chat_type="dm", chat_id=SLACK_DM, user_id=SLACK_OWNER)
        guest = OmhMemoryProvider(self.home)
        guest.initialize("owner-dm", platform="cli", hermes_home=str(self.hermes), agent_context="primary", cwd=str(self.workspace))
        self.assertEqual(guest._surface_class, SURFACE_OWNER_DIRECT)
        self.assertFalse(guest._attended)

    def test_a_bound_class_without_its_binding_is_not_a_lens(self) -> None:
        base = {
            "schema_version": SESSION_LENS_SCHEMA_VERSION,
            "shared_surface": True,
            "writes_enabled": True,
            "homes": [str(self.home)],
            "seen": [],
            "confirmed": [],
            "instance": "planted",
        }
        for session_id, fields in (
            ("no-principal", {"surface_class": SURFACE_DIRECT, "principal_context": None}),
            ("bot-principal", {"surface_class": SURFACE_DIRECT, "principal_context": {"actor_kind": "bot"}}),
            ("no-channel", {"surface_class": SURFACE_CHANNEL, "principal_context": None}),
            ("bad-channel", {"surface_class": SURFACE_CHANNEL, "principal_context": None, "channel_scope": {"kind": "channel", "ref": "not-a-ref"}}),
            ("thread-channel", {"surface_class": SURFACE_CHANNEL, "principal_context": None, "channel_scope": {"kind": "thread", "ref": "channel:v1:" + "a" * 64}}),
        ):
            with self.subTest(session_id=session_id):
                path = session_lens_path(self.home, session_id)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({**base, **fields, "session_id": session_id}), encoding="utf-8")
                self.assertIsNone(read_session_lens(self.home, session_id))
                refused = self.tool("capture", session_id, summary="A planted lens tries to write.")
                self.assertEqual(refused["reason"], "session_lens_unavailable")


if __name__ == "__main__":
    unittest.main()

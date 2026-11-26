"""Platform profile registry and the omh_platform_envelope/v1 builder.

The envelope is the one shape every channel adapter hands the core: who the
platform is, what it can render, what it can carry, and where session
ownership stops. These tests pin the registry contents (exactly 23 platforms,
three with verified limits), the transport-source mapping and the source
check that enforces it, ref safety (phone/email/secret/body-shaped values
never leave the process), renderer limit keys shared with
``src/wrapper/contract.py``, the render_profile/format_family split, and the
rule that no vendor capability is verified in-repo: every capability is
unknown, resolves false, and may only be resolved by an adapter declaration.
"""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.system.metadata_safety import is_raw_pii_shaped
from omh.system.platform_envelope import (
    PlatformContextError,
    build_platform_envelope,
    compact_session_platform,
    platform_thread_key_scope,
)
from omh.system.platform_profiles import PLATFORM_IDS, PLATFORM_PROFILES, PlatformProfile


_EXPECTED_PLATFORM_IDS = (
    "telegram",
    "discord",
    "whatsapp",
    "slack",
    "signal",
    "mattermost",
    "matrix",
    "home_assistant",
    "email",
    "twilio_sms",
    "dingtalk",
    "wecom_websocket",
    "wecom_callback",
    "wechat_ilink",
    "feishu_lark",
    "imessage_bluebubbles",
    "qqbot",
    "tencent_yuanbao",
    "microsoft_teams",
    "line",
    "simplex",
    "api_server",
    "buzz",
)

_VERIFIED_LIMIT_SOURCES = ("telegram", "discord", "slack")

#: transport_source each platform requires as the envelope ``source``.
_SOURCE_FOR = {
    platform_id: (
        platform_id
        if platform_id in _VERIFIED_LIMIT_SOURCES
        else "hermes"
        if platform_id == "buzz"
        else "generic"
    )
    for platform_id in _EXPECTED_PLATFORM_IDS
}


def _source(platform_id: str) -> str:
    return _SOURCE_FOR[platform_id]


def _envelope(platform: str = "discord", **context: object) -> dict:
    return build_platform_envelope(
        {"platform": platform, **context}, source=_source(platform)
    )


class PlatformProfileRegistryTests(unittest.TestCase):
    def test_exactly_23_platform_ids_in_order(self) -> None:
        self.assertEqual(len(PLATFORM_IDS), 23)
        self.assertEqual(tuple(PLATFORM_IDS), _EXPECTED_PLATFORM_IDS)
        self.assertEqual(len(set(PLATFORM_IDS)), 23)

    def test_every_id_has_a_frozen_profile(self) -> None:
        self.assertEqual(tuple(PLATFORM_PROFILES), _EXPECTED_PLATFORM_IDS)
        for platform_id in _EXPECTED_PLATFORM_IDS:
            profile = PLATFORM_PROFILES[platform_id]
            self.assertIsInstance(profile, PlatformProfile)
            self.assertEqual(profile.platform_id, platform_id)
            with self.assertRaises(Exception):
                profile.platform_id = "mutated"  # type: ignore[misc]

    def test_transport_source_mapping(self) -> None:
        self.assertEqual(PLATFORM_PROFILES["telegram"].transport_source, "telegram")
        self.assertEqual(PLATFORM_PROFILES["discord"].transport_source, "discord")
        self.assertEqual(PLATFORM_PROFILES["slack"].transport_source, "slack")
        self.assertEqual(PLATFORM_PROFILES["buzz"].transport_source, "hermes")
        for platform_id in _EXPECTED_PLATFORM_IDS:
            if platform_id in (*_VERIFIED_LIMIT_SOURCES, "buzz"):
                continue
            self.assertEqual(
                PLATFORM_PROFILES[platform_id].transport_source,
                "generic",
                platform_id,
            )

    def test_buzz_reuses_the_hermes_transport(self) -> None:
        profile = PLATFORM_PROFILES["buzz"]
        self.assertEqual(profile.format_family, "buzz/markdown")
        envelope = build_platform_envelope(
            {"platform": "buzz", "conversation_ref": "conv-buzz-1234"},
            source="hermes",
        )
        self.assertEqual(envelope["platform_id"], "buzz")
        self.assertEqual(envelope["transport_source"], "hermes")
        for wrong_source in ("generic", "buzz"):
            with self.subTest(source=wrong_source):
                with self.assertRaises(PlatformContextError):
                    build_platform_envelope(
                        {"platform": "buzz", "conversation_ref": "conv-buzz-1234"},
                        source=wrong_source,
                    )

    def test_verified_core_limits_use_renderer_keys(self) -> None:
        self.assertEqual(PLATFORM_PROFILES["discord"].limits.max_recommended_chars, 1700)
        self.assertEqual(PLATFORM_PROFILES["discord"].limits.hard_limit_chars, 1900)
        self.assertEqual(PLATFORM_PROFILES["slack"].limits.max_recommended_chars, 2700)
        self.assertEqual(PLATFORM_PROFILES["slack"].limits.hard_limit_chars, 2900)
        self.assertEqual(PLATFORM_PROFILES["telegram"].limits.max_recommended_chars, 3700)
        self.assertEqual(PLATFORM_PROFILES["telegram"].limits.hard_limit_chars, 3900)

    def test_conservative_default_limits_for_unverified_platforms(self) -> None:
        for platform_id in _EXPECTED_PLATFORM_IDS:
            if platform_id in _VERIFIED_LIMIT_SOURCES:
                continue
            profile = PLATFORM_PROFILES[platform_id]
            self.assertEqual(profile.limits.max_recommended_chars, 1600, platform_id)
            self.assertEqual(profile.limits.hard_limit_chars, 1800, platform_id)

    def test_no_vendor_capability_is_verified(self) -> None:
        # The repo holds no transport evidence for any vendor media/reply/
        # reaction/action fact, so all 22 registries stay unknown.
        for platform_id in _EXPECTED_PLATFORM_IDS:
            profile = PLATFORM_PROFILES[platform_id]
            for group in ("media", "reply", "reactions", "actions"):
                self.assertIn(group, profile.capabilities, platform_id)
                for name, value in profile.capabilities[group].items():
                    self.assertIsNone(value, f"{platform_id}.{group}.{name}")

    def test_render_profile_is_limited_or_rich_markdown(self) -> None:
        for platform_id in _EXPECTED_PLATFORM_IDS:
            self.assertIn(
                PLATFORM_PROFILES[platform_id].render_profile,
                ("limited_markdown", "rich_markdown"),
                platform_id,
            )

    def test_approved_render_profiles_and_format_families(self) -> None:
        expected_formats = {
            "telegram": "telegram_plain_text", "discord": "discord_markdown",
            "whatsapp": "whatsapp/plain_text", "slack": "slack_mrkdwn",
            "signal": "signal/body_ranges", "mattermost": "mattermost/commonmark",
            "matrix": "matrix/matrix_html", "home_assistant": "home_assistant/structured_json",
            "email": "email/mime", "twilio_sms": "twilio_sms/plain_text",
            "dingtalk": "dingtalk/card_json", "wecom_websocket": "wecom/card_json",
            "wecom_callback": "wecom/card_json", "wechat_ilink": "wechat_ilink/plain_text",
            "feishu_lark": "feishu_lark/post_card_json",
            "imessage_bluebubbles": "imessage_bluebubbles/attributed_text",
            "qqbot": "qqbot/markdown", "tencent_yuanbao": "tencent_yuanbao/plain_text",
            "microsoft_teams": "microsoft_teams/adaptive_card", "line": "line/flex_message",
            "simplex": "simplex/plain_text", "api_server": "api_server/structured_json",
        }
        rich = {"mattermost", "matrix", "email", "microsoft_teams", "api_server"}
        for platform_id, format_family in expected_formats.items():
            profile = PLATFORM_PROFILES[platform_id]
            self.assertEqual(profile.format_family, format_family, platform_id)
            self.assertEqual(
                profile.render_profile,
                "rich_markdown" if platform_id in rich else "limited_markdown",
                platform_id,
            )


class RawPiiDetectionTests(unittest.TestCase):
    def test_phone_shaped_detected(self) -> None:
        self.assertTrue(is_raw_pii_shaped("+821012345678"))
        self.assertTrue(is_raw_pii_shaped("+1 (555) 123-4567"))
        self.assertTrue(is_raw_pii_shaped("555-123-4567"))

    def test_dotted_phone_shaped_detected(self) -> None:
        self.assertTrue(is_raw_pii_shaped("415.555.0132"))
        self.assertTrue(is_raw_pii_shaped("+1.415.555.0132"))
        self.assertTrue(is_raw_pii_shaped("82.10.1234.5678"))

    def test_email_shaped_detected(self) -> None:
        self.assertTrue(is_raw_pii_shaped("agent@example.com"))
        self.assertTrue(is_raw_pii_shaped("a.b+tag@sub.example.org"))

    def test_opaque_refs_not_flagged(self) -> None:
        self.assertFalse(is_raw_pii_shaped("conv_123"))
        self.assertFalse(is_raw_pii_shaped("thread:abc.def"))
        self.assertFalse(is_raw_pii_shaped("u12345"))
        self.assertFalse(is_raw_pii_shaped("room:general.v2"))
        self.assertFalse(is_raw_pii_shaped("v1.2.3"))


class SourceValidationTests(unittest.TestCase):
    def test_source_must_match_transport_source(self) -> None:
        for platform_id in _EXPECTED_PLATFORM_IDS:
            envelope = _envelope(platform_id)
            self.assertEqual(envelope["transport_source"], _source(platform_id))

    def test_generic_platform_rejects_mismatched_source(self) -> None:
        with self.assertRaises(PlatformContextError):
            build_platform_envelope({"platform": "whatsapp"}, source="whatsapp")
        with self.assertRaises(PlatformContextError):
            build_platform_envelope({"platform": "api_server"}, source="api_server")

    def test_verified_platform_rejects_generic_source(self) -> None:
        for platform_id in _VERIFIED_LIMIT_SOURCES:
            with self.assertRaises(PlatformContextError, msg=platform_id):
                build_platform_envelope({"platform": platform_id}, source="generic")

    def test_verified_platform_rejects_foreign_source(self) -> None:
        with self.assertRaises(PlatformContextError):
            build_platform_envelope({"platform": "telegram"}, source="discord")

    def test_non_string_source_rejected(self) -> None:
        with self.assertRaises(PlatformContextError):
            build_platform_envelope({"platform": "discord"}, source=None)  # type: ignore[arg-type]
        with self.assertRaises(PlatformContextError):
            build_platform_envelope({"platform": "discord"}, source="")


class BuildPlatformEnvelopeTests(unittest.TestCase):
    def test_schema_and_core_fields(self) -> None:
        envelope = _envelope(conversation_ref="conv_1")
        self.assertEqual(envelope["schema_version"], "omh_platform_envelope/v1")
        self.assertEqual(envelope["platform_id"], "discord")
        self.assertEqual(envelope["transport_source"], "discord")
        self.assertIn("render_profile", envelope)
        self.assertIn("render_profile_provenance", envelope)
        self.assertIn("format_family", envelope)
        self.assertIn("capabilities", envelope)
        for group in ("media", "reply", "reactions", "actions"):
            self.assertIn(group, envelope["capabilities"])
        self.assertIn("capability_provenance", envelope)
        self.assertIn("limits", envelope)
        self.assertIn("limit_provenance", envelope)
        self.assertIn("identity", envelope)
        self.assertIn("session_scope", envelope)
        self.assertIn("claim_boundary", envelope)

    def test_claim_boundary_is_fixed_adapter_ownership(self) -> None:
        for platform_id in ("discord", "whatsapp", "api_server"):
            envelope = _envelope(platform_id)
            self.assertEqual(
                envelope["claim_boundary"],
                "adapter_owns_transport_core_owns_response",
                platform_id,
            )

    def test_unknown_capabilities_resolve_false_with_provenance(self) -> None:
        for platform_id in ("whatsapp", "telegram", "api_server"):
            envelope = _envelope(platform_id)
            for group in ("media", "reply", "reactions", "actions"):
                for capability, value in envelope["capabilities"][group].items():
                    self.assertFalse(value, f"{platform_id}.{group}.{capability}")
                    provenance = envelope["capability_provenance"][group][capability]
                    self.assertEqual(provenance, "unverified_default_false")

    def test_verified_limits_carry_verified_provenance(self) -> None:
        envelope = _envelope("slack")
        self.assertEqual(envelope["limits"]["max_recommended_chars"], 2700)
        self.assertEqual(envelope["limits"]["hard_limit_chars"], 2900)
        self.assertEqual(envelope["limit_provenance"], "verified")

    def test_conservative_limits_carry_conservative_provenance(self) -> None:
        envelope = _envelope("matrix")
        self.assertEqual(envelope["limits"]["max_recommended_chars"], 1600)
        self.assertEqual(envelope["limits"]["hard_limit_chars"], 1800)
        self.assertEqual(envelope["limit_provenance"], "conservative_default")

    def test_missing_platform_rejected(self) -> None:
        with self.assertRaises(PlatformContextError):
            build_platform_envelope({}, source="generic")
        with self.assertRaises(PlatformContextError):
            build_platform_envelope({"platform": ""}, source="generic")
        with self.assertRaises(PlatformContextError):
            build_platform_envelope({"platform": None}, source="generic")

    def test_unknown_23rd_platform_rejected(self) -> None:
        self.assertNotIn("myspace", PLATFORM_IDS)
        with self.assertRaises(PlatformContextError):
            build_platform_envelope({"platform": "myspace"}, source="generic")

    def test_unknown_top_level_context_key_rejected(self) -> None:
        with self.assertRaises(PlatformContextError):
            _envelope(verbosity="loud")
        with self.assertRaises(PlatformContextError):
            _envelope(source="discord")
        with self.assertRaises(PlatformContextError):
            _envelope(session_scope="conversation")

    def test_render_profile_defaults_to_profile_value(self) -> None:
        envelope = _envelope("discord")
        self.assertEqual(envelope["render_profile"], "limited_markdown")
        self.assertEqual(envelope["render_profile_provenance"], "profile_default")
        self.assertEqual(envelope["format_family"], "discord_markdown")

    def test_render_profile_accepts_known_value(self) -> None:
        envelope = _envelope(render_profile="rich_markdown")
        self.assertEqual(envelope["render_profile"], "rich_markdown")
        self.assertEqual(envelope["render_profile_provenance"], "adapter_declared")

    def test_unknown_render_profile_normalizes_down_to_limited(self) -> None:
        envelope = _envelope(render_profile="sparkle_markdown")
        self.assertEqual(envelope["render_profile"], "limited_markdown")
        self.assertEqual(
            envelope["render_profile_provenance"], "normalized_unknown_to_limited"
        )

    def test_non_string_render_profile_rejected(self) -> None:
        with self.assertRaises(PlatformContextError):
            _envelope(render_profile=42)

    def test_optional_refs_pass_through_to_identity_when_safe(self) -> None:
        envelope = _envelope(
            conversation_ref="conv_123",
            thread_ref="thread:abc",
            user_ref="u_456",
        )
        self.assertEqual(envelope["identity"]["conversation_ref"], "conv_123")
        self.assertEqual(envelope["identity"]["thread_ref"], "thread:abc")
        self.assertEqual(envelope["identity"]["user_ref"], "u_456")

    def test_identity_omits_refs_not_provided(self) -> None:
        envelope = _envelope()
        self.assertNotIn("conversation_ref", envelope["identity"])
        self.assertNotIn("thread_ref", envelope["identity"])
        self.assertNotIn("user_ref", envelope["identity"])

    def test_session_scope_is_conversation_with_conversation_ref(self) -> None:
        envelope = _envelope(conversation_ref="conv_1")
        self.assertEqual(envelope["session_scope"], "conversation")

    def test_session_scope_is_event_fallback_without_conversation_ref(self) -> None:
        self.assertEqual(_envelope()["session_scope"], "event_fallback")
        self.assertEqual(
            _envelope(thread_ref="th_1")["session_scope"], "event_fallback"
        )
        self.assertEqual(
            _envelope(user_ref="u_1")["session_scope"], "event_fallback"
        )

    def test_phone_shaped_ref_rejected(self) -> None:
        for field in ("conversation_ref", "thread_ref", "user_ref"):
            with self.assertRaises(PlatformContextError, msg=field):
                _envelope(**{field: "+821012345678"})
            with self.assertRaises(PlatformContextError, msg=field):
                _envelope(**{field: "415.555.0132"})

    def test_dotted_opaque_ref_accepted(self) -> None:
        envelope = _envelope(thread_ref="thread:abc.def")
        self.assertEqual(envelope["identity"]["thread_ref"], "thread:abc.def")

    def test_email_shaped_ref_rejected(self) -> None:
        for field in ("conversation_ref", "thread_ref", "user_ref"):
            with self.assertRaises(PlatformContextError, msg=field):
                _envelope(**{field: "agent@example.com"})

    def test_secret_shaped_ref_rejected(self) -> None:
        for field in ("conversation_ref", "thread_ref", "user_ref"):
            with self.assertRaises(PlatformContextError, msg=field):
                _envelope(**{field: "xoxb-1234567890-secret"})

    def test_body_shaped_ref_rejected(self) -> None:
        for field in ("conversation_ref", "thread_ref", "user_ref"):
            with self.assertRaises(PlatformContextError, msg=field):
                _envelope(**{field: "line1\nline2"})
            with self.assertRaises(PlatformContextError, msg=field):
                _envelope(**{field: "has\ttab"})

    def test_non_string_and_malformed_ref_rejected(self) -> None:
        with self.assertRaises(PlatformContextError):
            _envelope(conversation_ref=123)
        with self.assertRaises(PlatformContextError):
            _envelope(conversation_ref="has space")
        with self.assertRaises(PlatformContextError):
            _envelope(conversation_ref="-leading-dash")


class LimitValidationTests(unittest.TestCase):
    def _build_with_limits(self, recommended: object, hard: object, platform: str = "discord") -> dict:
        return _envelope(
            platform,
            limits={"max_recommended_chars": recommended, "hard_limit_chars": hard},
        )

    def test_valid_override_pair(self) -> None:
        envelope = self._build_with_limits(1500, 1800)
        self.assertEqual(envelope["limits"]["max_recommended_chars"], 1500)
        self.assertEqual(envelope["limits"]["hard_limit_chars"], 1800)
        self.assertEqual(envelope["limit_provenance"], "adapter_declared")

    def test_valid_whatsapp_declaration_above_conservative_default(self) -> None:
        # Unverified platforms may declare up to the 40000 core cap; the
        # conservative 1800 default is not a ceiling on declarations.
        envelope = self._build_with_limits(3800, 4000, platform="whatsapp")
        self.assertEqual(envelope["limits"]["max_recommended_chars"], 3800)
        self.assertEqual(envelope["limits"]["hard_limit_chars"], 4000)
        self.assertEqual(envelope["limit_provenance"], "adapter_declared")

    def test_unverified_platform_allows_hard_up_to_core_cap(self) -> None:
        envelope = self._build_with_limits(39000, 40000, platform="whatsapp")
        self.assertEqual(envelope["limits"]["hard_limit_chars"], 40000)
        with self.assertRaises(PlatformContextError):
            self._build_with_limits(39000, 40001, platform="whatsapp")

    def test_verified_platform_declaration_capped_at_profile_hard(self) -> None:
        with self.assertRaises(PlatformContextError):
            self._build_with_limits(1700, 1901, platform="discord")
        with self.assertRaises(PlatformContextError):
            self._build_with_limits(3700, 4000, platform="telegram")
        envelope = self._build_with_limits(1700, 1900, platform="discord")
        self.assertEqual(envelope["limits"]["hard_limit_chars"], 1900)

    def test_effective_recommended_clamped_to_hard_minus_200(self) -> None:
        envelope = self._build_with_limits(1750, 1800)
        self.assertEqual(envelope["limits"]["max_recommended_chars"], 1600)
        self.assertEqual(envelope["limits"]["hard_limit_chars"], 1800)

    def test_inverted_pair_fails(self) -> None:
        with self.assertRaises(PlatformContextError):
            self._build_with_limits(1900, 1700)

    def test_equal_pair_fails(self) -> None:
        with self.assertRaises(PlatformContextError):
            self._build_with_limits(1700, 1700)

    def test_recommended_below_200_fails(self) -> None:
        with self.assertRaises(PlatformContextError):
            self._build_with_limits(199, 1900)

    def test_hard_below_400_fails(self) -> None:
        # hard - 200 must leave a recommended of at least 200.
        with self.assertRaises(PlatformContextError):
            self._build_with_limits(200, 399)
        with self.assertRaises(PlatformContextError):
            self._build_with_limits(200, 400 - 1)
        envelope = self._build_with_limits(200, 400)
        self.assertEqual(envelope["limits"]["max_recommended_chars"], 200)
        self.assertEqual(envelope["limits"]["hard_limit_chars"], 400)

    def test_non_integer_limits_fail(self) -> None:
        with self.assertRaises(PlatformContextError):
            self._build_with_limits("1700", 1900)
        with self.assertRaises(PlatformContextError):
            self._build_with_limits(1700.5, 1900)
        with self.assertRaises(PlatformContextError):
            self._build_with_limits(True, 1900)


class CapabilityOverrideTests(unittest.TestCase):
    def test_override_may_resolve_unknown_capability(self) -> None:
        envelope = _envelope(
            "whatsapp",
            capabilities={"media": {"images": True}},
        )
        self.assertTrue(envelope["capabilities"]["media"]["images"])
        self.assertEqual(
            envelope["capability_provenance"]["media"]["images"],
            "adapter_declared",
        )

    def test_override_may_resolve_unknown_to_false_explicitly(self) -> None:
        envelope = _envelope(
            "whatsapp",
            capabilities={"reply": {"threads": False}},
        )
        self.assertFalse(envelope["capabilities"]["reply"]["threads"])
        self.assertEqual(
            envelope["capability_provenance"]["reply"]["threads"],
            "adapter_declared",
        )

    def test_override_allowed_on_verified_limit_platforms_too(self) -> None:
        # Verified limits do not imply verified capabilities: telegram's
        # capabilities are unknown like everyone else's.
        envelope = _envelope(
            "telegram",
            capabilities={"reactions": {"native": True}},
        )
        self.assertTrue(envelope["capabilities"]["reactions"]["native"])
        self.assertEqual(
            envelope["capability_provenance"]["reactions"]["native"],
            "adapter_declared",
        )

    def test_override_unknown_capability_name_fails(self) -> None:
        with self.assertRaises(PlatformContextError):
            _envelope("whatsapp", capabilities={"media": {"holograms": True}})

    def test_override_unknown_group_fails(self) -> None:
        with self.assertRaises(PlatformContextError):
            _envelope("whatsapp", capabilities={"telepathy": {"native": True}})

    def test_non_boolean_override_fails(self) -> None:
        with self.assertRaises(PlatformContextError):
            _envelope("whatsapp", capabilities={"media": {"images": "yes"}})


class SessionShapeTests(unittest.TestCase):
    def test_compact_session_platform_shape(self) -> None:
        envelope = _envelope(
            "slack",
            conversation_ref="conv_1",
            thread_ref="th_2",
            user_ref="u_3",
        )
        compact = compact_session_platform(envelope)
        self.assertEqual(
            compact,
            {
                "platform_id": "slack",
                "transport_source": "slack",
                "session_scope": "conversation",
            },
        )

    def test_compact_session_persists_no_refs_capabilities_or_limits(self) -> None:
        envelope = _envelope(
            "slack",
            conversation_ref="conv_1",
            thread_ref="th_2",
            user_ref="u_3",
            capabilities={"media": {"images": True}},
        )
        compact = compact_session_platform(envelope)
        self.assertNotIn("conversation_ref", compact)
        self.assertNotIn("thread_ref", compact)
        self.assertNotIn("user_ref", compact)
        self.assertNotIn("identity", compact)
        self.assertNotIn("capabilities", compact)
        self.assertNotIn("limits", compact)
        self.assertNotIn("render_profile", compact)

    def test_compact_session_event_fallback(self) -> None:
        envelope = _envelope("signal")
        compact = compact_session_platform(envelope)
        self.assertEqual(
            compact,
            {
                "platform_id": "signal",
                "transport_source": "generic",
                "session_scope": "event_fallback",
            },
        )

    def test_compact_session_rejects_foreign_envelope(self) -> None:
        with self.assertRaises(PlatformContextError):
            compact_session_platform({"schema_version": "other/v9"})

    def test_thread_key_scope_stable_for_same_refs(self) -> None:
        context = {
            "conversation_ref": "conv_1",
            "thread_ref": "th_9",
        }
        first = platform_thread_key_scope(_envelope("discord", **context))
        second = platform_thread_key_scope(_envelope("discord", **context))
        self.assertEqual(first, second)
        self.assertEqual(first, "discord:conv_1:th_9")

    def test_thread_key_scope_differs_by_platform_and_refs(self) -> None:
        base = {"conversation_ref": "conv_1", "thread_ref": "th_9"}
        discord = platform_thread_key_scope(_envelope("discord", **base))
        slack = platform_thread_key_scope(_envelope("slack", **base))
        other_thread = platform_thread_key_scope(
            _envelope("discord", conversation_ref="conv_1", thread_ref="th_10")
        )
        self.assertNotEqual(discord, slack)
        self.assertNotEqual(discord, other_thread)

    def test_thread_key_scope_without_thread_ref(self) -> None:
        envelope = _envelope("telegram", conversation_ref="conv_7")
        self.assertEqual(platform_thread_key_scope(envelope), "telegram:conv_7")

    def test_thread_key_scope_without_any_ref(self) -> None:
        envelope = _envelope("telegram")
        self.assertEqual(platform_thread_key_scope(envelope), "telegram")

    def test_thread_key_scope_ignores_user_ref(self) -> None:
        with_user = platform_thread_key_scope(
            _envelope("discord", conversation_ref="conv_1", user_ref="u_1")
        )
        without_user = platform_thread_key_scope(
            _envelope("discord", conversation_ref="conv_1")
        )
        self.assertEqual(with_user, without_user)

    def test_thread_key_scope_rejects_foreign_envelope(self) -> None:
        with self.assertRaises(PlatformContextError):
            platform_thread_key_scope({"platform_id": "discord"})


if __name__ == "__main__":
    unittest.main()

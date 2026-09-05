"""P1 cross-channel rendering over validated platform envelopes."""

from __future__ import annotations

import hashlib
import json
import unittest

from omh.system.platform_envelope import build_platform_envelope
from omh.wrapper.contract import build_chat_interaction_payload, messenger_rendering_contract
from omh.wrapper.message_gate import build_message_gate


_BASELINE_SHA256 = {
    "discord": "0d4e80fa21a5019db5ef7ac91da43587035bccc95453e447b6785592cb3d7512",
    "slack": "052337a0fe32b6adfb1352497ae93af91cfa80c58f2a4d7e6bc717559f5e8607",
    "telegram": "695a154f10a68697a64ac3f7e00cbf52d284547e857cc6b192c74ded9a96570d",
    "hermes": "a6a686bf7dee7ab5a23281e39d6ed9a1aae19a871f7abb4e7b5ea39e42351176",
    "generic": "a6a686bf7dee7ab5a23281e39d6ed9a1aae19a871f7abb4e7b5ea39e42351176",
}


def _envelope(**overrides: object) -> dict:
    context: dict[str, object] = {
        "platform": "whatsapp",
        "conversation_ref": "conv-opaque",
        "thread_ref": "thread-opaque",
        "user_ref": "user-opaque",
        "render_profile": "rich_markdown",
        "limits": {"max_recommended_chars": 3800, "hard_limit_chars": 4000},
        "capabilities": {
            "media": {"images": True, "files": True, "voice": False, "video": True},
            "reply": {"threads": True, "quotes": True},
            "reactions": {"native": True, "custom_emoji": False},
            "actions": {"buttons": True, "forms": False},
        },
    }
    context.update(overrides)
    return build_platform_envelope(context, source="generic")


def _render(**overrides: object) -> dict:
    kwargs: dict[str, object] = {
        "visible_prefix": "[omh] cross-channel",
        "first_line": "Cross-channel result",
        "body": "body text",
        "claim_boundary": "Metadata only.",
        "source": "generic",
        "platform_envelope": _envelope(),
    }
    kwargs.update(overrides)
    return messenger_rendering_contract(**kwargs)


class EnvelopeRenderingTests(unittest.TestCase):
    def test_declared_whatsapp_limits_drive_chunking_and_keep_provenance(self) -> None:
        rendering = _render(body="x" * 8000)
        self.assertEqual(
            rendering["chunking"],
            {
                "max_recommended_chars": 3800,
                "hard_limit_chars": 4000,
                "limit_provenance": "adapter_declared",
                "split_on": ["headings", "bullets", "paragraphs"],
            },
        )
        self.assertGreater(len(rendering["chunked_body_texts"]), 1)
        self.assertTrue(all(len(chunk) <= 3800 for chunk in rendering["chunked_body_texts"]))

    def test_envelope_profile_overrides_the_legacy_argument(self) -> None:
        rendering = _render(render_profile="limited_markdown", body="| A | B |\n|---|---|\n| x | y |")
        self.assertEqual(rendering["render_profile"], "rich_markdown")
        self.assertEqual(rendering["body_format"], "rich_markdown")
        self.assertIn("|---|---|", rendering["body_text"])

    def test_platform_identity_format_and_capabilities_are_exposed(self) -> None:
        envelope = _envelope()
        rendering = _render(platform_envelope=envelope)
        self.assertEqual(rendering["platform_id"], "whatsapp")
        self.assertEqual(rendering["format_family"], "whatsapp/plain_text")
        self.assertEqual(rendering["capabilities"], envelope["capabilities"])
        self.assertIsNot(rendering["capabilities"], envelope["capabilities"])


class StructuredGateTests(unittest.TestCase):
    def test_delegated_gate_is_exposed_without_changing_text_fallbacks(self) -> None:
        gate = build_message_gate(
            skill="ulw-work",
            executor="codex",
            model="gpt-5.6-sol",
            status="prepared_not_observed",
            prompt_sha256="abc123",
            composed_prompt="Refactor the parser.",
        )
        legacy = messenger_rendering_contract(
            visible_prefix="[omh] handoff",
            first_line="Handoff",
            body="Prepared only.",
            claim_boundary="Not execution evidence.",
            source="generic",
            render_profile="rich_markdown",
            message_gate=gate,
            follow_up_texts=(gate["prompt_block"],),
        )
        rendering = _render(
            visible_prefix="[omh] handoff",
            first_line="Handoff",
            body="Prepared only.",
            claim_boundary="Not execution evidence.",
            message_gate=gate,
            follow_up_texts=(gate["prompt_block"],),
        )
        self.assertEqual(rendering["omh_message_gate"], gate)
        self.assertIsNot(rendering["omh_message_gate"], gate)
        self.assertEqual(rendering["body_text"], legacy["body_text"])
        self.assertEqual(rendering["fallback_body_text"], legacy["fallback_body_text"])
        self.assertEqual(rendering["follow_up_texts"], legacy["follow_up_texts"])

    def test_empty_or_absent_gate_adds_no_structured_key(self) -> None:
        self.assertNotIn("omh_message_gate", _render())
        self.assertNotIn("omh_message_gate", _render(message_gate={}))

    def test_common_wiring_exposes_the_same_gate_and_preserves_fallback(self) -> None:
        payload = build_chat_interaction_payload(
            "auth 모듈 리팩터링을 코덱스한테 맡겨줘",
            source="generic",
            mode="delegate",
            executor_target="codex",
            platform_context={
                "platform": "whatsapp",
                "conversation_ref": "conv-opaque",
                "render_profile": "limited_markdown",
                "limits": {"max_recommended_chars": 3800, "hard_limit_chars": 4000},
            },
        )
        response = payload["chat_response"]
        rendering = response["messenger_rendering"]
        self.assertEqual(rendering["omh_message_gate"], response["message_gate"])
        self.assertEqual(rendering["platform_id"], "whatsapp")
        self.assertEqual(
            rendering["adapter_payload"]["schema_version"],
            "omh_messenger_adapter_payload/v1",
        )
        self.assertEqual(rendering["chunking"]["max_recommended_chars"], 3800)
        self.assertEqual(rendering["chunking"]["hard_limit_chars"], 4000)
        self.assertEqual(rendering["chunking"]["limit_provenance"], "adapter_declared")
        self.assertIn("- model — ", rendering["body_text"])
        self.assertEqual(len(rendering["follow_up_texts"]), 1)


class AdapterPayloadTests(unittest.TestCase):
    def test_canonical_shape_and_execution_boundary(self) -> None:
        actions = [{"id": "approve", "payload": {"decision": "yes"}}]
        attachments = [{"kind": "image", "ref": "attachment:opaque", "meta": {"alt": "chart"}}]
        payload = _render(response_actions=actions, attachments=attachments)["adapter_payload"]
        self.assertEqual(payload["schema_version"], "omh_messenger_adapter_payload/v1")
        self.assertEqual(payload["platform_id"], "whatsapp")
        self.assertEqual(payload["transport_source"], "generic")
        self.assertEqual(
            payload["media"],
            {
                "attachments": attachments,
                "image_support": True,
                "audio_support": False,
                "video_support": True,
                "document_support": True,
                "caption_support": False,
            },
        )
        self.assertEqual(
            payload["reply"],
            {"thread_ref": "thread-opaque", "reply_support": True, "threads_support": True},
        )
        self.assertEqual(
            payload["reactions"],
            {"items": [], "native_support": True, "custom_support": False},
        )
        self.assertEqual(
            payload["actions"],
            {"response_actions": actions, "button_support": True, "form_support": False},
        )
        self.assertEqual(payload["delivery"]["state"], "prepared_not_delivered")
        self.assertFalse(payload["delivery"]["observed"])
        self.assertEqual(
            payload["delivery"]["adapter_owned_responsibilities"],
            ["auth", "network", "encryption", "media_transfer", "posting", "delivery"],
        )
        self.assertEqual(
            payload["claim_boundary"],
            "Rendering and capabilities are not execution or delivery evidence.",
        )

    def test_adapter_declared_caption_capability_is_rendered_with_provenance(self) -> None:
        envelope = _envelope(capabilities={"media": {"captions": True}})
        rendering = _render(platform_envelope=envelope)
        self.assertTrue(rendering["adapter_payload"]["media"]["caption_support"])
        self.assertTrue(rendering["capabilities"]["media"]["captions"])
        self.assertEqual(
            envelope["capability_provenance"]["media"]["captions"],
            "adapter_declared",
        )

    def test_absent_media_actions_and_unknown_support_stay_conservative(self) -> None:
        envelope = _envelope(capabilities={})
        self.assertFalse(envelope["capabilities"]["media"]["captions"])
        self.assertEqual(
            envelope["capability_provenance"]["media"]["captions"],
            "unverified_default_false",
        )
        payload = _render(platform_envelope=envelope)["adapter_payload"]
        self.assertEqual(payload["media"]["attachments"], [])
        self.assertEqual(payload["actions"]["response_actions"], [])
        for contract, keys in (
            (payload["media"], ("image_support", "audio_support", "video_support", "document_support", "caption_support")),
            (payload["reply"], ("reply_support", "threads_support")),
            (payload["reactions"], ("native_support", "custom_support")),
            (payload["actions"], ("button_support", "form_support")),
        ):
            self.assertTrue(all(contract[key] is False for key in keys))

    def test_no_raw_identity_refs_escape_except_validated_thread_ref(self) -> None:
        serialized = json.dumps(_render()["adapter_payload"], sort_keys=True)
        self.assertIn("thread-opaque", serialized)
        self.assertNotIn("conv-opaque", serialized)
        self.assertNotIn("user-opaque", serialized)
        self.assertNotIn("identity", serialized)

    def test_json_safe_and_mutation_isolated_without_mutating_inputs(self) -> None:
        envelope = _envelope()
        actions = [{"id": "approve", "payload": {"decision": "yes"}}]
        attachments = [{"kind": "image", "meta": {"alt": "chart"}}]
        first = _render(platform_envelope=envelope, response_actions=actions, attachments=attachments)
        self.assertEqual(json.loads(json.dumps(first)), first)
        first["capabilities"]["media"]["images"] = False
        first["adapter_payload"]["actions"]["response_actions"][0]["payload"]["decision"] = "mutated"
        first["adapter_payload"]["media"]["attachments"][0]["meta"]["alt"] = "mutated"
        second = _render(platform_envelope=envelope, response_actions=actions, attachments=attachments)
        self.assertTrue(second["capabilities"]["media"]["images"])
        self.assertEqual(second["adapter_payload"]["actions"]["response_actions"], actions)
        self.assertEqual(second["adapter_payload"]["media"]["attachments"], attachments)
        self.assertEqual(actions[0]["payload"]["decision"], "yes")
        self.assertEqual(attachments[0]["meta"]["alt"], "chart")

    def test_common_wiring_passes_response_actions_without_mutating_them(self) -> None:
        payload = build_chat_interaction_payload(
            "summarize the current OMH status",
            source="generic",
            platform_context={"platform": "whatsapp", "conversation_ref": "conv-opaque"},
        )
        response = payload["chat_response"]
        self.assertEqual(
            response["messenger_rendering"]["adapter_payload"]["actions"]["response_actions"],
            response["actions"],
        )
        self.assertIsNot(
            response["messenger_rendering"]["adapter_payload"]["actions"]["response_actions"],
            response["actions"],
        )


class LegacyByteEqualityTests(unittest.TestCase):
    def test_no_envelope_payloads_equal_the_p0_baseline(self) -> None:
        for source, expected in _BASELINE_SHA256.items():
            with self.subTest(source=source):
                rendering = messenger_rendering_contract(
                    visible_prefix="[omh] baseline",
                    first_line="Baseline",
                    body="## Result\n\n| A | B |\n|---|---|\n| x | **y** |",
                    claim_boundary="Metadata only.",
                    render_profile=(
                        "limited_markdown"
                        if source in {"discord", "slack", "telegram"}
                        else "rich_markdown"
                    ),
                    source=source,
                    follow_up_texts=("Follow up.",),
                )
                encoded = json.dumps(
                    rendering, ensure_ascii=False, separators=(",", ":")
                ).encode()
                self.assertEqual(hashlib.sha256(encoded).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()

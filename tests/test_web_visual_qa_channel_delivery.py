from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from omh.web_visual_qa import build_web_visual_qa_channel_delivery_card, build_web_visual_qa_package
from tests.test_cli import run_cli


class WebVisualQaChannelDeliveryTests(unittest.TestCase):
    def test_channel_card_prepares_redacted_attachment_candidates(self) -> None:
        package = build_web_visual_qa_package(
            package_id="checkout-qa",
            target="Checkout",
            source="hermes",
            criteria=({"criterion_id": "layout", "label": "Layout", "pass_rule": "fits", "severity": "blocking"},),
            captures=(
                {"capture_id": "desktop", "path_or_uri": "/tmp/desktop.png", "mime_type": "image/png", "viewport": "desktop", "evidence_summary": "Desktop capture", "redaction_status": "not_needed"},
                {"capture_id": "secret", "path_or_uri": "/tmp/secret.png", "mime_type": "image/png", "viewport": "mobile", "evidence_summary": "Sensitive capture", "redaction_status": "contains_sensitive_content"},
            ),
        )

        card = build_web_visual_qa_channel_delivery_card(package, renderer_target="slack")

        self.assertEqual(card["schema_version"], "web_visual_qa_channel_delivery/v1")
        self.assertEqual(card["renderer_target"], "slack")
        self.assertEqual(card["source"], "hermes")
        self.assertEqual(card["status"], "prepared_not_observed")
        self.assertFalse(card["delivery_observed"])
        self.assertEqual(card["attachments"][0]["capture_id"], "desktop")
        self.assertNotIn("path_or_uri", card["blocked_captures"][0])
        self.assertNotIn("evidence_summary", card["blocked_captures"][0])
        self.assertIn("platform_delivery", card["does_not_prove"])

    def test_channel_card_rejects_unknown_renderer(self) -> None:
        package = build_web_visual_qa_package(
            package_id="checkout-qa",
            target="Checkout",
            criteria=({"criterion_id": "layout", "label": "Layout", "pass_rule": "fits", "severity": "blocking"},),
        )

        with self.assertRaises(ValueError):
            build_web_visual_qa_channel_delivery_card(package, renderer_target="unknown")

    def test_channel_card_blocks_unknown_redaction(self) -> None:
        package = build_web_visual_qa_package(
            package_id="checkout-qa",
            target="Checkout",
            criteria=({"criterion_id": "layout", "label": "Layout", "pass_rule": "fits", "severity": "blocking"},),
            captures=({"capture_id": "unknown", "path_or_uri": "/tmp/unknown.png", "mime_type": "image/png", "viewport": "desktop", "evidence_summary": "Unreviewed capture"},),
        )

        card = build_web_visual_qa_channel_delivery_card(package, renderer_target="discord")

        self.assertEqual(card["attachments"], [])
        self.assertEqual(card["blocked_captures"][0]["capture_id"], "unknown")

    def test_channel_card_does_not_forward_redacted_capture_summary(self) -> None:
        package = build_web_visual_qa_package(
            package_id="checkout-qa",
            target="Checkout",
            criteria=({"criterion_id": "layout", "label": "Layout", "pass_rule": "fits", "severity": "blocking"},),
            captures=({"capture_id": "redacted", "path_or_uri": "/tmp/redacted.png", "mime_type": "image/png", "viewport": "desktop", "evidence_summary": "token=sk-live-example", "redaction_status": "redacted"},),
        )

        card = build_web_visual_qa_channel_delivery_card(package, renderer_target="telegram")

        self.assertNotIn("sk-live-example", str(card))
        self.assertEqual(card["attachments"][0]["alt_text"], "Web QA screenshot")
        self.assertNotIn("caption", card["attachments"][0])
        self.assertNotIn("role", card["attachments"][0])

    def test_show_renders_prepared_channel_card_without_delivery_claim(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = ["--omh-home", str(root / ".omh"), "web-qa"]
            self.assertEqual(run_cli(base + ["package", "--package-id", "checkout-qa", "--target", "Checkout", "--criterion", "layout:Layout:fits:blocking"])[0], 0)
            self.assertEqual(run_cli(base + ["observe-capture", "--package-id", "checkout-qa", "--capture-id", "desktop", "--path", str(root / "desktop.png"), "--mime-type", "image/png", "--viewport", "desktop", "--summary", "Desktop capture", "--redaction-status", "not_needed"])[0], 0)

            status, stdout, stderr = run_cli(base + ["show", "--package-id", "checkout-qa", "--renderer-target", "slack", "--json"], output_json=False)

            self.assertEqual(status, 0, stderr)
            self.assertIn('"schema_version": "web_visual_qa_channel_delivery/v1"', stdout)
        self.assertIn('"delivery_observed": false', stdout)
        self.assertNotIn("attachment_uploaded", stdout.split('"does_not_prove"')[0])

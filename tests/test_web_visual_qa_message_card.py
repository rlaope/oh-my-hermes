from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

import omh.web_visual_qa as web_visual_qa_facade
from omh.workflows.web_visual_qa_contracts import JsonObject
from omh.web_visual_qa import (
    build_web_visual_qa_message_card,
    build_web_visual_qa_package,
    validate_web_visual_qa_message_card,
)


class WebVisualQaMessageCardTests(unittest.TestCase):
    def test_message_card_projects_discord_package_without_delivery_claim(self) -> None:
        package = _reviewed_package("/tmp/desktop.png")

        card = build_web_visual_qa_message_card(package)

        self.assertEqual(card["schema_version"], "web_visual_qa_message_card/v1")
        self.assertEqual(card["source"], "discord")
        self.assertEqual(card["headline"], "Web visual QA hold: Checkout page")
        self.assertEqual(card["route"]["route"], "request_operator_review")
        self.assertEqual(card["route"]["label"], "Operator review required")
        self.assertEqual(card["route"]["next_action"], "record_operator_review")
        self.assertEqual(card["attachment_summary"]["eligible_count"], 1)
        self.assertEqual(card["attachment_summary"]["blocked_count"], 0)
        self.assertFalse(card["attachment_summary"]["delivery_observed"])
        self.assertEqual(card["criteria"][0]["status"], "hold")
        self.assertEqual(card["captures"][0]["path_or_uri"], "/tmp/desktop.png")
        self.assertIn("platform_delivery", card["does_not_prove"])
        self.assertTrue(any("Layout fits: hold" in block["text"] for block in card["message_blocks"]))
        self.assertEqual(validate_web_visual_qa_message_card(card), [])

    def test_message_card_validation_requires_delivery_boundary(self) -> None:
        card = build_web_visual_qa_message_card(_reviewed_package("/tmp/desktop.png"))
        card["attachment_summary"] = {"eligible_count": 1, "blocked_count": 0, "delivery_observed": True}
        card["does_not_prove"] = ["message_sent", "attachment_uploaded"]

        errors = validate_web_visual_qa_message_card(card)

        self.assertIn("attachment_summary.delivery_observed must remain false until wrapper evidence exists", errors)
        self.assertIn("attachment_summary.schema_version must be message_attachment_projection/v1", errors)
        self.assertIn("does_not_prove must include platform_delivery", errors)

    def test_message_card_validation_rejects_overclaiming_route_fields(self) -> None:
        card = build_web_visual_qa_message_card(_reviewed_package("/tmp/desktop.png"))
        card["route"]["message_delivery"] = "sent_to_discord"
        card["route"]["multimodal_strategy"] = "called_omh_model"
        card["route"]["safety_flags"] = ["uploaded_attachment"]
        card["route"]["suggested_actions"] = ["platform_delivery_observed"]
        card["route"]["routing_basis"] = [
            {
                "id": "external-plugin-runtime",
                "source_repos": ["unknown"],
                "native_rule": "Loaded an external plugin.",
            }
        ]

        errors = validate_web_visual_qa_message_card(card)

        self.assertIn("route.message_delivery is unsupported", errors)
        self.assertIn("route.multimodal_strategy is unsupported", errors)
        self.assertIn("route.safety_flags[0] is unsupported", errors)
        self.assertIn("route.suggested_actions[0] is unsupported", errors)
        self.assertIn("route.routing_basis[0].id is unsupported", errors)

    def test_low_cost_unresolved_capture_keeps_operator_route_with_multimodal_suggestion(self) -> None:
        package = build_web_visual_qa_package(
            package_id="checkout-qa",
            target="Checkout page",
            source="discord",
            risk_level="medium",
            estimated_cost_tier="low",
            criteria=[
                {
                    "criterion_id": "layout",
                    "label": "Layout fits",
                    "pass_rule": "No overlap",
                    "severity": "blocking",
                }
            ],
            captures=[
                {
                    "capture_id": "desktop",
                    "role": "desktop",
                    "path_or_uri": "/tmp/desktop.png",
                    "mime_type": "image/png",
                    "viewport": "desktop-1440",
                    "evidence_summary": "Desktop checkout viewport captured.",
                    "redaction_status": "not_needed",
                }
            ],
        )

        card = build_web_visual_qa_message_card(package)

        self.assertEqual(package["routing"]["route"], "request_operator_review")
        self.assertEqual(package["routing"]["multimodal_strategy"], "operator_review_before_low_cost_multimodal")
        self.assertIn("record_host_multimodal_review", package["routing"]["suggested_actions"])
        self.assertIn("model_call", package["routing"]["does_not_authorize"])
        self.assertEqual(card["route"]["label"], "Operator review required")
        self.assertEqual(card["route"]["message_delivery"], "prepare_message_card_with_attachments")
        self.assertIn("record_host_multimodal_review", card["route"]["suggested_actions"])
        self.assertTrue(any("Native rewrite basis" in block["text"] for block in card["message_blocks"]))
        self.assertEqual(validate_web_visual_qa_message_card(card), [])

    def test_sensitive_capture_is_blocked_from_message_attachments(self) -> None:
        package = build_web_visual_qa_package(
            package_id="checkout-qa",
            target="Checkout page",
            source="discord",
            risk_level="low",
            estimated_cost_tier="low",
            criteria=[
                {
                    "criterion_id": "layout",
                    "label": "Layout fits",
                    "pass_rule": "No overlap",
                    "severity": "blocking",
                }
            ],
            captures=[
                {
                    "capture_id": "desktop",
                    "role": "desktop",
                    "path_or_uri": "/tmp/desktop.png",
                    "mime_type": "image/png",
                    "viewport": "desktop-1440",
                    "evidence_summary": "Desktop checkout viewport captured with account details visible.",
                    "redaction_status": "contains_sensitive_content",
                }
            ],
        )

        card = build_web_visual_qa_message_card(package)

        self.assertEqual(package["routing"]["route"], "redact_before_message")
        self.assertEqual(package["routing"]["message_delivery"], "prepare_message_card_without_attachments")
        self.assertEqual(card["route"]["label"], "Redaction required")
        self.assertEqual(card["attachment_summary"]["eligible_count"], 0)
        self.assertEqual(card["attachment_summary"]["blocked_count"], 1)
        self.assertIn("sensitive_capture_requires_redaction", card["route"]["safety_flags"])
        self.assertEqual(validate_web_visual_qa_message_card(card), [])

    def test_facade_exports_only_stable_web_qa_contract_symbols(self) -> None:
        self.assertIn("build_web_visual_qa_message_card", web_visual_qa_facade.__all__)
        self.assertIn("validate_web_visual_qa_message_card", web_visual_qa_facade.__all__)
        self.assertNotIn("auto_routing", web_visual_qa_facade.__all__)
        self.assertNotIn("attachment_projection", web_visual_qa_facade.__all__)

    def test_show_command_outputs_message_card_json_and_summary(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_path = root / "desktop.png"
            base = ["--omh-home", str(root / ".omh"), "web-qa"]

            status, stdout, stderr = run_cli(
                base
                + [
                    "package",
                    "--package-id",
                    "checkout-qa",
                    "--target",
                    "Checkout page",
                    "--source",
                    "discord",
                    "--risk-level",
                    "high",
                    "--estimated-cost-tier",
                    "low",
                    "--criterion",
                    "layout:Layout fits:No overlap:blocking",
                    "--capture",
                    f"desktop:desktop:{capture_path}:image/png:desktop-1440:Desktop checkout viewport captured.",
                    "--criteria-result",
                    "layout:hold:desktop:operator:Desktop captured; mobile still needs review:blocking",
                    "--multimodal-review",
                    "vision:observed:host_vision:low:medium:desktop:Host vision checked desktop overlap",
                    "--verdict",
                    "hold",
                    "--json",
                ]
            )

            self.assertEqual(status, 0, stderr)
            self.assertEqual(json.loads(stdout)["package_id"], "checkout-qa")

            status, stdout, stderr = run_cli(base + ["show", "--package-id", "checkout-qa", "--json"])

            self.assertEqual(status, 0, stderr)
            card = json.loads(stdout)
            self.assertEqual(card["schema_version"], "web_visual_qa_message_card/v1")
            self.assertEqual(card["route"]["label"], "Operator review required")
            self.assertEqual(card["attachment_summary"]["eligible_count"], 1)

            status, stdout, stderr = run_cli(base + ["show", "--package-id", "checkout-qa"], output_json=False)

            self.assertEqual(status, 0, stderr)
            self.assertIn("Web visual QA message card", stdout)
            self.assertIn("Route: Operator review required", stdout)
            self.assertIn("Attachments: 1 eligible, 0 blocked; delivery not observed", stdout)
            self.assertIn("Layout fits: hold - Desktop captured; mobile still needs review", stdout)
            self.assertIn("Boundary:", stdout)

    def test_package_command_accepts_redaction_and_attachment_capture_fields(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_path = root / "desktop.png"
            base = ["--omh-home", str(root / ".omh"), "web-qa"]

            status, stdout, stderr = run_cli(
                base
                + [
                    "package",
                    "--package-id",
                    "checkout-qa",
                    "--target",
                    "Checkout page",
                    "--source",
                    "discord",
                    "--risk-level",
                    "low",
                    "--estimated-cost-tier",
                    "low",
                    "--criterion",
                    "layout:Layout fits:No overlap:blocking",
                    "--capture",
                    f"desktop:desktop:{capture_path}:image/png:desktop-1440:Desktop checkout viewport captured.",
                    "--capture-redaction-status",
                    "contains_sensitive_content",
                    "--capture-attachment",
                    "eligible",
                    "--json",
                ]
            )

            self.assertEqual(status, 0, stderr)
            package = json.loads(stdout)
            self.assertEqual(package["captures"][0]["redaction_status"], "contains_sensitive_content")
            self.assertEqual(package["captures"][0]["attachment"], "eligible")
            self.assertEqual(package["routing"]["route"], "redact_before_message")

    def test_package_command_preserves_colons_and_enum_words_in_capture_summary(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_path = root / "desktop.png"
            base = ["--omh-home", str(root / ".omh"), "web-qa"]

            status, stdout, stderr = run_cli(
                base
                + [
                    "package",
                    "--package-id",
                    "checkout-qa",
                    "--target",
                    "Checkout page",
                    "--criterion",
                    "layout:Layout fits:No overlap:blocking",
                    "--capture",
                    (
                        f"desktop:desktop:{capture_path}:image/png:desktop-1440:"
                        "Status: checkout still overlaps:redacted:eligible"
                    ),
                    "--json",
                ]
            )

            self.assertEqual(status, 0, stderr)
            package = json.loads(stdout)
            self.assertEqual(package["captures"][0]["evidence_summary"], "Status: checkout still overlaps:redacted:eligible")
            self.assertEqual(package["captures"][0]["redaction_status"], "unknown")
            self.assertEqual(package["captures"][0]["attachment"], "eligible")

    def test_package_command_rejects_malformed_capture_metadata_flags(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_path = root / "desktop.png"
            base = ["--omh-home", str(root / ".omh"), "web-qa"]

            status, stdout, stderr = run_cli(
                base
                + [
                    "package",
                    "--package-id",
                    "checkout-qa",
                    "--target",
                    "Checkout page",
                    "--criterion",
                    "layout:Layout fits:No overlap:blocking",
                    "--capture",
                    f"desktop:desktop:{capture_path}:image/png:desktop-1440:Desktop checkout viewport captured.",
                    "--capture-redaction-status",
                    "contains_sensitive_content",
                    "--capture-attachment",
                    "eligble",
                    "--json",
                ]
            )

            self.assertEqual(status, 2)
            self.assertEqual(stdout, "")
            self.assertIn("--capture-attachment must be one of eligible, blocked, not_requested", stderr)

    def test_capture_file_command_imports_local_screenshot_as_managed_attachment(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "desktop.png"
            screenshot_bytes = b"\x89PNG\r\n\x1a\nweb-qa-screenshot"
            source_path.write_bytes(screenshot_bytes)
            base = ["--omh-home", str(root / ".omh"), "web-qa"]

            status, stdout, stderr = run_cli(
                base
                + [
                    "package",
                    "--package-id",
                    "checkout-qa",
                    "--target",
                    "Checkout page",
                    "--source",
                    "discord",
                    "--criterion",
                    "layout:Layout fits:No overlap:blocking",
                    "--json",
                ]
            )
            self.assertEqual(status, 0, stderr)
            self.assertEqual(json.loads(stdout)["status"], "prepared")

            status, stdout, stderr = run_cli(
                base
                + [
                    "capture-file",
                    "--package-id",
                    "checkout-qa",
                    "--capture-id",
                    "desktop",
                    "--source-path",
                    str(source_path),
                    "--role",
                    "desktop",
                    "--viewport",
                    "desktop-1440",
                    "--summary",
                    "Desktop checkout screenshot imported from browser QA.",
                    "--redaction-status",
                    "not_needed",
                    "--attachment",
                    "eligible",
                    "--json",
                ]
            )

            self.assertEqual(status, 0, stderr)
            package = json.loads(stdout)
            capture = package["captures"][0]
            managed_path = Path(capture["path_or_uri"])
            self.assertTrue(managed_path.is_file())
            self.assertEqual(managed_path.read_bytes(), screenshot_bytes)
            self.assertEqual(capture["capture_origin"], "imported_local_file")
            self.assertEqual(capture["byte_size"], len(screenshot_bytes))
            self.assertEqual(capture["sha256"], hashlib.sha256(screenshot_bytes).hexdigest())
            self.assertEqual(capture["mime_type"], "image/png")

            status, stdout, stderr = run_cli(base + ["show", "--package-id", "checkout-qa", "--json"])

            self.assertEqual(status, 0, stderr)
            card = json.loads(stdout)
            attachment = card["attachment_projection"]["items"][0]
            self.assertEqual(attachment["path_or_uri"], str(managed_path))
            self.assertEqual(attachment["capture_origin"], "imported_local_file")
            self.assertEqual(card["attachment_summary"]["eligible_count"], 1)

    def test_capture_file_command_rejects_non_image_bytes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "desktop.png"
            source_path.write_text("not an image", encoding="utf-8")
            base = ["--omh-home", str(root / ".omh"), "web-qa"]

            status, _stdout, stderr = run_cli(
                base
                + [
                    "package",
                    "--package-id",
                    "checkout-qa",
                    "--target",
                    "Checkout page",
                    "--criterion",
                    "layout:Layout fits:No overlap:blocking",
                    "--json",
                ]
            )
            self.assertEqual(status, 0, stderr)

            status, stdout, stderr = run_cli(
                base
                + [
                    "capture-file",
                    "--package-id",
                    "checkout-qa",
                    "--capture-id",
                    "desktop",
                    "--source-path",
                    str(source_path),
                    "--summary",
                    "Desktop checkout screenshot.",
                    "--json",
                ]
            )

            self.assertEqual(status, 2)
            self.assertEqual(stdout, "")
            self.assertIn("--source-path must contain PNG, JPEG, or WebP image bytes", stderr)

    def test_show_command_rejects_stale_package_with_sensitive_attachment_projection(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            capture_path = root / "desktop.png"
            base = ["--omh-home", str(root / ".omh"), "web-qa"]

            status, _stdout, stderr = run_cli(
                base
                + [
                    "package",
                    "--package-id",
                    "checkout-qa",
                    "--target",
                    "Checkout page",
                    "--criterion",
                    "layout:Layout fits:No overlap:blocking",
                    "--capture",
                    f"desktop:desktop:{capture_path}:image/png:desktop-1440:Desktop checkout viewport captured.",
                    "--json",
                ]
            )

            self.assertEqual(status, 0, stderr)
            package_path = root / ".omh" / "web-visual-qa" / "packages" / "checkout-qa.json"
            package = json.loads(package_path.read_text(encoding="utf-8"))
            package["captures"][0]["redaction_status"] = "contains_sensitive_content"
            package_path.write_text(json.dumps(package), encoding="utf-8")

            status, stdout, stderr = run_cli(base + ["show", "--package-id", "checkout-qa", "--json"])

            self.assertEqual(status, 2)
            self.assertEqual(stdout, "")
            self.assertIn("attachment_projection.items[0].capture_id must reference an attachment-eligible capture", stderr)


def _reviewed_package(path: str) -> JsonObject:
    return build_web_visual_qa_package(
        package_id="checkout-qa",
        target="Checkout page",
        source="discord",
        risk_level="high",
        estimated_cost_tier="low",
        criteria=[
            {
                "criterion_id": "layout",
                "label": "Layout fits",
                "pass_rule": "No overlap",
                "severity": "blocking",
            }
        ],
        captures=[
            {
                "capture_id": "desktop",
                "role": "desktop",
                "path_or_uri": path,
                "mime_type": "image/png",
                "viewport": "desktop-1440",
                "evidence_summary": "Desktop checkout viewport captured.",
            }
        ],
        criteria_results=[
            {
                "criterion_id": "layout",
                "status": "hold",
                "evidence_refs": ["desktop"],
                "checked_by": "operator",
                "summary": "Desktop captured; mobile still needs review",
                "blocking": True,
            }
        ],
        multimodal_reviews=[
            {
                "review_id": "vision",
                "status": "observed",
                "reviewer": "host_vision",
                "cost_tier": "low",
                "confidence": "medium",
                "evidence_refs": ["desktop"],
                "summary": "Host vision checked desktop overlap",
            }
        ],
        verdict="hold",
    )


if __name__ == "__main__":
    unittest.main()

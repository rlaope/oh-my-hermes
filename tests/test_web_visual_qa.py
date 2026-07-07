from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()

from omh.paths import OmhPaths
from omh.web_visual_qa import (
    build_web_visual_qa_package,
    list_web_visual_qa_packages,
    validate_web_visual_qa_package,
    write_web_visual_qa_package,
)


class WebVisualQaTests(unittest.TestCase):
    def test_package_records_captures_criteria_results_and_multimodal_route(self) -> None:
        package = build_web_visual_qa_package(
            package_id="checkout-qa",
            target="Checkout page",
            source="discord",
            risk_level="high",
            estimated_cost_tier="low",
            criteria=[
                {
                    "criterion_id": "layout",
                    "label": "Text fits at desktop and mobile widths",
                    "pass_rule": "No text overlaps or clipped controls",
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
                    "evidence_summary": "Desktop checkout viewport captured after login boundary.",
                },
                {
                    "capture_id": "mobile",
                    "role": "mobile",
                    "path_or_uri": "/tmp/mobile.webp",
                    "mime_type": "image/webp",
                    "viewport": "mobile-390",
                    "evidence_summary": "Mobile checkout viewport captured after login boundary.",
                },
            ],
            criteria_results=[
                {
                    "criterion_id": "layout",
                    "status": "hold",
                    "evidence_refs": ["desktop"],
                    "checked_by": "wrapper",
                    "summary": "Desktop is captured; mobile still needs human review before PASS.",
                    "blocking": True,
                }
            ],
            multimodal_reviews=[
                {
                    "review_id": "vision-review",
                    "status": "observed",
                    "reviewer": "host_supplied_vision",
                    "cost_tier": "low",
                    "confidence": "medium",
                    "evidence_refs": ["desktop"],
                    "summary": "Observed host vision review found no desktop overlap.",
                }
            ],
            verdict="hold",
        )

        self.assertEqual(package["schema_version"], "web_visual_qa_package/v1")
        self.assertEqual(package["status"], "verdict_recorded")
        self.assertEqual(package["verdict"], "hold")
        self.assertEqual(package["routing"]["route"], "request_operator_review")
        self.assertEqual(package["routing"]["cost_policy"], "risk_first_cost_aware_host_observed_only")
        self.assertEqual(package["attachment_projection"]["schema_version"], "message_attachment_projection/v1")
        self.assertEqual(len(package["attachment_projection"]["items"]), 2)
        self.assertIn("platform_delivery_observed", package["does_not_prove"])
        self.assertEqual(validate_web_visual_qa_package(package), [])

    def test_pass_requires_observed_capture_and_passing_blocking_results(self) -> None:
        package = build_web_visual_qa_package(
            package_id="checkout-pass",
            target="Checkout page",
            criteria=[
                {
                    "criterion_id": "layout",
                    "label": "Text fits",
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
                    "evidence_summary": "Desktop captured.",
                }
            ],
            criteria_results=[
                {
                    "criterion_id": "layout",
                    "status": "pass",
                    "evidence_refs": ["desktop"],
                    "checked_by": "operator",
                    "summary": "Desktop criterion passed.",
                    "blocking": True,
                }
            ],
            verdict="pass",
        )

        self.assertEqual(validate_web_visual_qa_package(package), [])

        blocked = dict(package)
        blocked["criteria_results"] = [
            {
                "criterion_id": "layout",
                "status": "hold",
                "evidence_refs": ["desktop"],
                "checked_by": "operator",
                "summary": "Needs mobile review.",
                "blocking": True,
            }
        ]
        errors = validate_web_visual_qa_package(blocked)
        self.assertIn("PASS requires every blocking criterion result to pass", errors)

        missing_result = dict(package)
        missing_result["criteria"] = [
            *package["criteria"],
            {
                "criterion_id": "mobile-layout",
                "label": "Mobile text fits",
                "pass_rule": "No mobile overlap",
                "severity": "blocking",
            },
        ]
        errors = validate_web_visual_qa_package(missing_result)
        self.assertIn("PASS requires every blocking criterion result to pass", errors)

    def test_auto_routing_prepares_capture_before_operator_review_without_captures(self) -> None:
        package = build_web_visual_qa_package(
            package_id="checkout-prepared",
            target="Checkout page",
            risk_level="medium",
            estimated_cost_tier="none",
            criteria=[
                {
                    "criterion_id": "layout",
                    "label": "Text fits",
                    "pass_rule": "No overlap",
                    "severity": "blocking",
                }
            ],
        )

        self.assertEqual(package["status"], "prepared")
        self.assertEqual(package["routing"]["route"], "prepare_capture")
        self.assertEqual(package["routing"]["decision_inputs"]["capture_count"], 0)
        self.assertEqual(package["routing"]["decision_inputs"]["blocking_unresolved_count"], 1)

    def test_auto_routing_counts_missing_declared_blocking_results(self) -> None:
        package = build_web_visual_qa_package(
            package_id="checkout-partial-routing",
            target="Checkout page",
            risk_level="low",
            criteria=[
                {
                    "criterion_id": "desktop-layout",
                    "label": "Desktop text fits",
                    "pass_rule": "No desktop overlap",
                    "severity": "blocking",
                },
                {
                    "criterion_id": "mobile-layout",
                    "label": "Mobile text fits",
                    "pass_rule": "No mobile overlap",
                    "severity": "blocking",
                },
            ],
            captures=[
                {
                    "capture_id": "desktop",
                    "role": "desktop",
                    "path_or_uri": "/tmp/desktop.png",
                    "mime_type": "image/png",
                    "viewport": "desktop-1440",
                    "evidence_summary": "Desktop captured.",
                }
            ],
            criteria_results=[
                {
                    "criterion_id": "desktop-layout",
                    "status": "pass",
                    "evidence_refs": ["desktop"],
                    "checked_by": "operator",
                    "summary": "Desktop passed.",
                    "blocking": True,
                }
            ],
        )

        self.assertEqual(package["routing"]["route"], "request_operator_review")
        self.assertEqual(package["routing"]["decision_inputs"]["blocking_unresolved_count"], 1)

    def test_auto_routing_uses_cost_after_required_evidence_is_resolved(self) -> None:
        base_kwargs = {
            "target": "Checkout page",
            "risk_level": "medium",
            "criteria": [
                {
                    "criterion_id": "layout",
                    "label": "Text fits",
                    "pass_rule": "No overlap",
                    "severity": "blocking",
                }
            ],
            "captures": [
                {
                    "capture_id": "desktop",
                    "role": "desktop",
                    "path_or_uri": "/tmp/desktop.png",
                    "mime_type": "image/png",
                    "viewport": "desktop-1440",
                    "evidence_summary": "Desktop captured.",
                }
            ],
            "criteria_results": [
                {
                    "criterion_id": "layout",
                    "status": "pass",
                    "evidence_refs": ["desktop"],
                    "checked_by": "operator",
                    "summary": "Desktop passed.",
                    "blocking": True,
                }
            ],
        }

        low_cost = build_web_visual_qa_package(
            package_id="checkout-low-cost-routing",
            estimated_cost_tier="low",
            **base_kwargs,
        )
        high_cost = build_web_visual_qa_package(
            package_id="checkout-high-cost-routing",
            estimated_cost_tier="high",
            **base_kwargs,
        )

        self.assertEqual(low_cost["routing"]["route"], "request_operator_review")
        self.assertEqual(high_cost["routing"]["route"], "lightweight_capture_review")
        self.assertEqual(low_cost["routing"]["cost_policy"], "risk_first_cost_aware_host_observed_only")

    def test_auto_routing_uses_observed_multimodal_only_after_risk_and_blocking_gates(self) -> None:
        base_kwargs = {
            "target": "Checkout page",
            "estimated_cost_tier": "low",
            "criteria": [
                {
                    "criterion_id": "layout",
                    "label": "Text fits",
                    "pass_rule": "No overlap",
                    "severity": "blocking",
                }
            ],
            "captures": [
                {
                    "capture_id": "desktop",
                    "role": "desktop",
                    "path_or_uri": "/tmp/desktop.png",
                    "mime_type": "image/png",
                    "viewport": "desktop-1440",
                    "evidence_summary": "Desktop captured.",
                }
            ],
            "multimodal_reviews": [
                {
                    "review_id": "vision-review",
                    "status": "observed",
                    "reviewer": "host_supplied_vision",
                    "cost_tier": "low",
                    "confidence": "medium",
                    "evidence_refs": ["desktop"],
                    "summary": "Observed host vision review found no desktop overlap.",
                }
            ],
        }

        critical = build_web_visual_qa_package(
            package_id="checkout-critical-multimodal-routing",
            risk_level="critical",
            **base_kwargs,
        )
        unresolved = build_web_visual_qa_package(
            package_id="checkout-unresolved-multimodal-routing",
            risk_level="low",
            **base_kwargs,
        )
        resolved = build_web_visual_qa_package(
            package_id="checkout-resolved-multimodal-routing",
            risk_level="low",
            criteria_results=[
                {
                    "criterion_id": "layout",
                    "status": "pass",
                    "evidence_refs": ["desktop"],
                    "checked_by": "operator",
                    "summary": "Desktop passed.",
                    "blocking": True,
                }
            ],
            **base_kwargs,
        )

        self.assertEqual(critical["routing"]["route"], "request_operator_review")
        self.assertEqual(unresolved["routing"]["route"], "request_operator_review")
        self.assertEqual(resolved["routing"]["route"], "use_observed_multimodal_review")

    def test_attachment_projection_excludes_blocked_and_sensitive_captures(self) -> None:
        package = build_web_visual_qa_package(
            package_id="checkout-attachment-safety",
            target="Checkout page",
            criteria=[
                {
                    "criterion_id": "layout",
                    "label": "Text fits",
                    "pass_rule": "No overlap",
                    "severity": "blocking",
                }
            ],
            captures=[
                {
                    "capture_id": "eligible",
                    "role": "desktop",
                    "path_or_uri": "/tmp/eligible.png",
                    "mime_type": "image/png",
                    "viewport": "desktop-1440",
                    "evidence_summary": "Desktop captured.",
                    "redaction_status": "redacted",
                },
                {
                    "capture_id": "blocked",
                    "role": "desktop",
                    "path_or_uri": "/tmp/blocked.png",
                    "mime_type": "image/png",
                    "viewport": "desktop-1440",
                    "evidence_summary": "Blocked attachment capture.",
                    "attachment": "blocked",
                },
                {
                    "capture_id": "not-requested",
                    "role": "mobile",
                    "path_or_uri": "/tmp/not-requested.png",
                    "mime_type": "image/png",
                    "viewport": "mobile-390",
                    "evidence_summary": "Attachment was not requested.",
                    "attachment": "not_requested",
                },
                {
                    "capture_id": "sensitive",
                    "role": "mobile",
                    "path_or_uri": "/tmp/sensitive.png",
                    "mime_type": "image/png",
                    "viewport": "mobile-390",
                    "evidence_summary": "Sensitive capture.",
                    "redaction_status": "contains_sensitive_content",
                },
            ],
        )

        projection = package["attachment_projection"]
        self.assertEqual([item["capture_id"] for item in projection["items"]], ["eligible"])
        self.assertEqual(
            [item["capture_id"] for item in projection["blocked_items"]],
            ["blocked", "not-requested", "sensitive"],
        )
        self.assertEqual(validate_web_visual_qa_package(package), [])

        tampered = dict(package)
        tampered["attachment_projection"] = {
            **projection,
            "items": [
                *projection["items"],
                {
                    "id": "attachment-sensitive",
                    "capture_id": "sensitive",
                    "path_or_uri": "/tmp/sensitive.png",
                    "mime_type": "image/png",
                    "caption": "sensitive web QA capture",
                    "alt_text": "Sensitive capture.",
                    "role": "mobile",
                    "display_order": 2,
                    "platform_upload_observed": False,
                },
            ],
        }

        self.assertIn(
            "attachment_projection.items[1].capture_id must reference an attachment-eligible capture",
            validate_web_visual_qa_package(tampered),
        )

        attachment_ref = dict(package)
        attachment_ref["criteria_results"] = [
            {
                "criterion_id": "layout",
                "status": "pass",
                "evidence_refs": ["attachment-eligible"],
                "checked_by": "operator",
                "summary": "Attachment projection is not observed visual QA evidence.",
                "blocking": True,
            }
        ]

        self.assertIn(
            "criteria_results[0].evidence_refs contains unknown package evidence ref: attachment-eligible",
            validate_web_visual_qa_package(attachment_ref),
        )

    def test_validation_rejects_relative_paths_bad_mime_and_unknown_refs(self) -> None:
        package = build_web_visual_qa_package(
            package_id="checkout-bad",
            target="Checkout page",
            criteria=[
                {
                    "criterion_id": "layout",
                    "label": "Text fits",
                    "pass_rule": "No overlap",
                    "severity": "blocking",
                }
            ],
            captures=[
                {
                    "capture_id": "desktop",
                    "role": "desktop",
                    "path_or_uri": "relative.png",
                    "mime_type": "image/gif",
                    "viewport": "desktop",
                    "evidence_summary": "",
                }
            ],
            criteria_results=[
                {
                    "criterion_id": "missing",
                    "status": "pass",
                    "evidence_refs": ["unknown-capture"],
                    "checked_by": "operator",
                    "summary": "Wrong ref.",
                    "blocking": True,
                }
            ],
            verdict="hold",
        )

        errors = validate_web_visual_qa_package(package)

        self.assertIn("captures[0].path_or_uri must be an absolute local path or URI", errors)
        self.assertIn("captures[0].mime_type must be one of image/png, image/jpeg, image/webp", errors)
        self.assertIn("captures[0].evidence_summary is required", errors)
        self.assertIn("criteria_results[0].criterion_id must reference criteria[].criterion_id", errors)
        self.assertIn("criteria_results[0].evidence_refs contains unknown package evidence ref: unknown-capture", errors)

    def test_write_package_persists_private_index(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = OmhPaths(omh_home=root / "omh", hermes_home=root / "hermes")
            package = build_web_visual_qa_package(
                package_id="checkout-qa",
                target="Checkout page",
                criteria=[
                    {
                        "criterion_id": "layout",
                        "label": "Text fits",
                        "pass_rule": "No overlap",
                        "severity": "blocking",
                    }
                ],
            )

            written = write_web_visual_qa_package(paths, package)
            records = list_web_visual_qa_packages(paths)

            self.assertEqual(written["package_id"], "checkout-qa")
            self.assertEqual([record["package_id"] for record in records], ["checkout-qa"])
            self.assertTrue(paths.web_visual_qa_packages_index_path.is_file())


if __name__ == "__main__":
    unittest.main()

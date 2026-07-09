from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.workflows.web_visual_qa_captures import MAX_CAPTURE_FILE_BYTES
from omh.web_visual_qa import build_web_visual_qa_package, validate_web_visual_qa_package


PNG_BYTES = b"\x89PNG\r\n\x1a\nweb-qa-screenshot"


class WebVisualQaCaptureFileSafetyTests(unittest.TestCase):
    def test_capture_file_rejects_symlinked_managed_package_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "desktop.png"
            source_path.write_bytes(PNG_BYTES)
            base = _base(root)
            _create_package(base)
            captures_root = root / ".omh" / "web-visual-qa" / "captures"
            outside = root / "outside-captures"
            captures_root.mkdir(parents=True)
            outside.mkdir()
            try:
                (captures_root / "checkout-qa").symlink_to(outside, target_is_directory=True)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

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
            self.assertIn("package capture storage must not be a symlink", stderr)
            self.assertFalse((outside / "desktop.png").exists())

    def test_capture_file_failed_validation_does_not_leave_managed_bytes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "desktop.png"
            source_path.write_bytes(PNG_BYTES)
            base = _base(root)
            _create_package(base)

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
                    "   ",
                    "--json",
                ]
            )

            managed_path = root / ".omh" / "web-visual-qa" / "captures" / "checkout-qa" / "desktop.png"
            self.assertEqual(status, 2)
            self.assertEqual(stdout, "")
            self.assertIn("captures[0].evidence_summary is required", stderr)
            self.assertFalse(managed_path.exists())

    def test_capture_file_rejects_large_sources_before_importing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "desktop.png"
            source_path.write_bytes(PNG_BYTES)
            with source_path.open("ab") as handle:
                handle.truncate(MAX_CAPTURE_FILE_BYTES + 1)
            base = _base(root)
            _create_package(base)

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

            managed_path = root / ".omh" / "web-visual-qa" / "captures" / "checkout-qa" / "desktop.png"
            self.assertEqual(status, 2)
            self.assertEqual(stdout, "")
            self.assertIn("--source-path must be 25 MiB or smaller", stderr)
            self.assertFalse(managed_path.exists())

    def test_imported_local_file_requires_managed_provenance_metadata(self) -> None:
        package = build_web_visual_qa_package(
            package_id="checkout-qa",
            target="Checkout page",
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
                    "evidence_summary": "Desktop checkout screenshot.",
                    "capture_origin": "imported_local_file",
                }
            ],
        )

        errors = validate_web_visual_qa_package(package)

        self.assertIn("captures[0].byte_size is required for imported_local_file captures", errors)
        self.assertIn("captures[0].sha256 is required for imported_local_file captures", errors)


def _base(root: Path) -> list[str]:
    return ["--omh-home", str(root / ".omh"), "web-qa"]


def _create_package(base: list[str]) -> None:
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
            "--json",
        ]
    )
    if status != 0:
        raise AssertionError(stderr)
    package = json.loads(stdout)
    if package["status"] != "prepared":
        raise AssertionError(f"unexpected package status: {package['status']}")


if __name__ == "__main__":
    unittest.main()

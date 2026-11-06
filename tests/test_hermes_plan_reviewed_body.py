from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli

REVIEWED = "## Options\n- A: Redis\n- B: sticky sessions (rejected)\n\n## Success criteria\n| Criterion | Task | Verification |\n| p95 under 200ms | T1 | make bench |\n"


class HermesPlanReviewedBodyTests(unittest.TestCase):
    def _run(self, root: Path, *args: str) -> tuple[int, dict, str]:
        status, stdout, stderr = run_cli(
            ["--omh-home", str(root / "omh"), "--hermes-home", str(root / "hermes"), *args]
        )
        return status, (json.loads(stdout) if stdout.strip().startswith("{") else {}), stderr

    def test_plan_file_replaces_the_canned_sections_with_the_reviewed_plan(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "reviewed.md"
            body.write_text(REVIEWED, encoding="utf-8")
            status, payload, _ = self._run(
                root, "hermes", "plan", "--record", "--plan-file", str(body), "Move sessions to Redis"
            )
            self.assertEqual(status, 0)
            text = Path(payload["artifact"]["path"]).read_text(encoding="utf-8")
            self.assertIn("plan_body: reviewed", text)
            self.assertIn("## Reviewed Plan", text)
            self.assertIn("sticky sessions (rejected)", text)
            self.assertNotIn("Create a durable Hermes-facing planning artifact.", text)
            self.assertNotIn("say", payload)
            self.assertEqual(payload["artifact"]["plan_body"], "reviewed")

    def test_accepting_a_reviewed_plan_says_nothing_extra(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "reviewed.md"
            body.write_text(REVIEWED, encoding="utf-8")
            _, payload, _ = self._run(root, "hermes", "plan", "--record", "--plan-file", str(body), "Move sessions")
            _, accepted, _ = self._run(root, "hermes", "plan-accept", payload["artifact"]["path"])
            self.assertEqual(accepted["artifact"]["status"], "accepted")
            self.assertNotIn("say", accepted)
            self.assertIn("p95 under 200ms", Path(payload["artifact"]["path"]).read_text(encoding="utf-8"))

    def test_recording_without_a_body_says_so_and_accept_says_scaffold(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, payload, _ = self._run(root, "hermes", "plan", "--record", "Move sessions")
            self.assertIn("scaffold only", payload["say"])
            self.assertEqual(payload["artifact"]["plan_body"], "scaffold")
            _, accepted, _ = self._run(root, "hermes", "plan-accept", payload["artifact"]["path"])
            self.assertFalse(accepted["reviewed_body"])
            self.assertIn("only the generated scaffold", accepted["say"])
            self.assertIn("scaffold", accepted["journal_event"]["summary"])

    def test_bundle_is_recorded_as_input_and_cannot_be_accepted(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "bundle.md"
            body.write_text("### Hard Constraints\n- keep p95\n### Open Questions\n- cost?\n", encoding="utf-8")
            status, payload, _ = self._run(
                root, "hermes", "plan", "--record", "--plan-file", str(body), "--input-bundle", "Redis proposal"
            )
            self.assertEqual(status, 0)
            self.assertEqual(payload["artifact"]["schema_version"], "hermes_plan_input/v1")
            path = payload["artifact"]["path"]
            text = Path(path).read_text(encoding="utf-8")
            self.assertIn("INPUT TO PLANNING, NOT A PLAN", text)
            self.assertNotIn("Review-gated Hermes plan", text)
            status, _, stderr = run_cli(
                ["--omh-home", str(root / "omh"), "--hermes-home", str(root / "hermes"), "hermes", "plan-accept", path]
            )
            self.assertNotEqual(status, 0)
            self.assertIn("hermes_plan/v1", stderr)

    def test_flags_need_record_and_a_non_empty_file(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "reviewed.md"
            body.write_text(REVIEWED, encoding="utf-8")
            empty = root / "empty.md"
            empty.write_text("  \n", encoding="utf-8")
            args = ["--omh-home", str(root / "omh"), "--hermes-home", str(root / "hermes"), "hermes", "plan"]
            self.assertNotEqual(run_cli([*args, "--plan-file", str(body), "x y"])[0], 0)
            self.assertNotEqual(run_cli([*args, "--record", "--input-bundle", "x y"])[0], 0)
            status, _, stderr = run_cli([*args, "--record", "--plan-file", str(empty), "x y"])
            self.assertNotEqual(status, 0)
            self.assertIn("empty", stderr)


if __name__ == "__main__":
    unittest.main()

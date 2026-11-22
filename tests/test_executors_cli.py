"""`omh coding executors` and registry-id admission through the real parser.

Every test runs against a disposable OMH home. Nothing reads the developer's
home, the repository or the cwd, and no vendor CLI is installed or spawned:
the check test uses a program name that is absent on purpose.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli  # noqa: E402
from _test_temp_root import make_test_tempdir  # noqa: E402

ABSENT_PROGRAM = "omh-absent-harness-xyz"


def _unit(owner: str) -> dict[str, object]:
    return {
        "unit_id": "alpha",
        "title": "Alpha",
        "owner": owner,
        "file_scope": ["src/alpha.py"],
        "depends_on": [],
    }


class ExecutorsCliTests(unittest.TestCase):
    def setUp(self) -> None:
        holder = make_test_tempdir(prefix="omh-executors-cli-")
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name)
        self.home = self.root / "omh"
        self.home.mkdir()
        self.work = self.root / "work"
        self.work.mkdir()

    def cli(self, *args: str) -> tuple[int, dict[str, Any]]:
        status, stdout, _stderr = run_cli(["--omh-home", str(self.home), "coding", *args])
        try:
            payload = json.loads(stdout) if stdout.strip().startswith("{") else {}
        except json.JSONDecodeError:
            payload = {}
        return status, payload

    def write_config(self, text: str) -> None:
        (self.home / "routing").mkdir(parents=True, exist_ok=True)
        (self.home / "routing" / "executors.toml").write_text(text, encoding="utf-8")

    def write_units(self, owner: str) -> Path:
        path = self.work / "units.json"
        path.write_text(json.dumps([_unit(owner)]), encoding="utf-8")
        return path

    def test_add_devin_then_list_shows_it_unvalidated(self) -> None:
        status, added = self.cli("executors", "add", "devin")
        self.assertEqual(status, 0)
        self.assertEqual(added["id"], "devin")
        self.assertFalse(added["validated"])

        status, listing = self.cli("executors", "list", "--json")
        self.assertEqual(status, 0)
        enabled = {entry["id"]: entry for entry in listing["enabled"]}
        self.assertIn("devin", enabled)
        self.assertFalse(enabled["devin"]["validated"])
        self.assertEqual(enabled["devin"]["preset"], "devin")
        self.assertFalse(enabled["devin"]["remote_pr"])
        self.assertIn("claude-code", listing["builtin"])
        self.assertFalse(listing["probed"])
        self.assertNotIn("devin", {entry["id"] for entry in listing["available_presets"]})

    def test_add_unknown_preset_fails_and_writes_nothing(self) -> None:
        status, _payload = self.cli("executors", "add", "not-a-harness")
        self.assertNotEqual(status, 0)
        self.assertFalse((self.home / "routing" / "executors.toml").exists())

    def test_add_existing_id_is_refused_unless_forced(self) -> None:
        self.assertEqual(self.cli("executors", "add", "devin")[0], 0)
        self.assertNotEqual(self.cli("executors", "add", "devin")[0], 0)
        self.assertEqual(self.cli("executors", "add", "devin", "--force")[0], 0)

    def test_remove_drops_the_entry(self) -> None:
        self.assertEqual(self.cli("executors", "add", "gemini")[0], 0)
        status, removed = self.cli("executors", "remove", "gemini")
        self.assertEqual(status, 0)
        self.assertTrue(removed["removed"])
        _status, listing = self.cli("executors", "list", "--json")
        self.assertNotIn("gemini", {entry["id"] for entry in listing["enabled"]})
        self.assertNotEqual(self.cli("executors", "remove", "gemini")[0], 0)

    def test_list_reports_rejected_entries_with_reasons(self) -> None:
        self.write_config(
            'schema_version = 1\n'
            '[executors.broken]\nargv = "devin -p {prompt}"\n'
            '[executors.good-one]\nargv = ["good-one", "run", "{prompt}"]\n'
        )
        status, listing = self.cli("executors", "list", "--json")
        self.assertEqual(status, 0)
        self.assertIn("good-one", {entry["id"] for entry in listing["enabled"]})
        rejected = {(entry["id"], entry["field"]): entry["reason"] for entry in listing["rejected"]}
        self.assertTrue(any(key[0] == "broken" for key in rejected), rejected)

    def test_check_reports_not_installed_when_binary_absent(self) -> None:
        self.write_config(
            'schema_version = 1\n'
            f'[executors.absent]\nargv = ["{ABSENT_PROGRAM}", "run", "{{prompt}}"]\n'
        )
        status, checked = self.cli("executors", "check", "absent")
        self.assertNotEqual(status, 0)
        self.assertFalse(checked["ok"])
        self.assertEqual(checked["checked"][0]["id"], "absent")
        self.assertEqual(checked["checked"][0]["reason"], "not_installed")
        self.assertEqual(checked["checked"][0]["status"], "missing")

    def test_check_unknown_id_is_refused(self) -> None:
        status, _payload = self.cli("executors", "check", "nobody")
        self.assertNotEqual(status, 0)

    def test_owner_accepts_a_loaded_id_and_refuses_an_unloaded_one(self) -> None:
        self.write_config(
            'schema_version = 1\n'
            f'[executors.my-agent]\nargv = ["{ABSENT_PROGRAM}", "run", "{{prompt}}"]\n'
        )
        status, validated = self.cli(
            "fanout", "validate", "--units", str(self.write_units("my-agent"))
        )
        self.assertEqual(status, 0, validated)
        self.assertTrue(validated["ok"])

        status, refused = self.cli(
            "fanout", "validate", "--units", str(self.write_units("someone-else"))
        )
        self.assertNotEqual(status, 0)
        self.assertFalse(refused["ok"])

    def test_executor_readiness_accepts_a_loaded_id(self) -> None:
        self.write_config(
            'schema_version = 1\n'
            f'[executors.my-agent]\nargv = ["{ABSENT_PROGRAM}", "run", "{{prompt}}"]\n'
        )
        status, contract = self.cli("executor-readiness", "--executor", "my-agent", "--dry-run")
        self.assertEqual(status, 0)
        self.assertEqual(contract["profile"], "my-agent")
        self.assertTrue(contract["user_executor"])

    def test_allow_remote_pr_is_refused_until_the_lane_exists(self) -> None:
        status, _stdout, stderr = run_cli(
            ["--omh-home", str(self.home), "coding", "run", "--owner", "codex", "--goal", "noop", "--allow-remote-pr"]
        )
        self.assertNotEqual(status, 0)
        self.assertIn("remote_pr lane not available", stderr)


if __name__ == "__main__":
    unittest.main()

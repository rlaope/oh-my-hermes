from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from _local_package import load_local_package

load_local_package()
from omh.paths import resolve_paths
from omh.targets import (
    build_target_change_notice,
    inspect_target_observation,
    record_target_observation,
    summarize_target_registry,
)


class TargetRegistryTests(unittest.TestCase):
    def test_records_single_to_multi_and_multi_to_single_without_forgetting_history(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes-a")

            first = record_target_observation(paths, source="setup")
            self.assertTrue(first["persisted"])
            self.assertEqual(first["topology"]["mode"], "single_agent_target")
            self.assertFalse(first["topology"]["changed"])

            second = record_target_observation(
                paths,
                source="chat:discord",
                source_metadata={
                    "agent_ref": "agent-b",
                    "hermes_home": str(root / ".hermes-b"),
                },
            )
            self.assertEqual(second["topology"]["transition"], "single_to_multi")
            self.assertEqual(second["topology"]["mode"], "multi_agent_targets")
            self.assertTrue(second["topology"]["requires_skill_scope_awareness"])

            back_to_one = inspect_target_observation(
                paths,
                source="chat:discord",
                source_metadata={
                    "agent_ref": "agent-a",
                    "hermes_home": str(root / ".hermes-a"),
                    "agent_count": "1",
                },
            )
            self.assertFalse(back_to_one["persisted"])
            self.assertEqual(back_to_one["topology"]["transition"], "multi_to_single")
            self.assertEqual(back_to_one["topology"]["mode"], "single_agent_target")
            self.assertGreaterEqual(back_to_one["topology"]["known_target_count"], 2)
            self.assertEqual(back_to_one["topology"]["active_agent_count"], 1)

    def test_change_notice_distinguishes_pending_and_applied_persistence(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes-a")

            record_target_observation(paths, source="setup")
            pending = inspect_target_observation(
                paths,
                source="chat:slack",
                source_metadata={
                    "agent_ref": "agent-b",
                    "hermes_home": str(root / ".hermes-b"),
                    "agent_count": "2",
                },
            )
            pending_notice = build_target_change_notice(pending)

            self.assertIsNotNone(pending_notice)
            assert pending_notice is not None
            self.assertEqual(pending_notice["action"], "ask_to_apply_target_change")
            self.assertEqual(pending_notice["persistence"], "pending_user_confirmation")
            self.assertIn("multiple Hermes agent targets", pending_notice["body"])
            self.assertEqual(pending_notice["apply_payload"]["source"], "chat:slack")
            self.assertEqual(pending_notice["apply_payload"]["source_metadata"]["agent_ref"], "agent-b")
            self.assertEqual(pending_notice["apply_payload"]["source_metadata"]["agent_count"], "2")

            applied = record_target_observation(
                paths,
                source="chat:slack",
                source_metadata={
                    "agent_ref": "agent-b",
                    "hermes_home": str(root / ".hermes-b"),
                    "agent_count": "2",
                },
            )
            applied_notice = build_target_change_notice(applied, auto_applied=True)

            self.assertIsNotNone(applied_notice)
            assert applied_notice is not None
            self.assertEqual(applied_notice["action"], "target_change_applied")
            self.assertEqual(applied_notice["persistence"], "persisted")
            self.assertEqual(summarize_target_registry(paths)["mode"], "multi_agent_targets")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()
from omh.coding_delegation import build_coding_delegation_payload
from omh.memory import (
    apply_memory_update_batch,
    build_handoff_context_pack,
    build_memory_inspection,
    build_memory_review_card,
    read_handoff_context_pack_file,
)
from omh.paths import resolve_paths
from omh.profiles.setup import write_setup_profile
from omh.targets import record_target_observation


class MemoryContractTests(unittest.TestCase):
    def test_inspection_separates_sources_and_detects_stale_conflicts(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            write_setup_profile(paths, ["prompt-only-coding"])
            record_target_observation(
                paths,
                source="discord",
                source_metadata={"target_ref": "team-thread", "agent_count": "3"},
            )
            wrapper_snapshot = _wrapper_snapshot(
                [
                    {
                        "item_id": "executor-pref",
                        "key": "default_executor",
                        "value": "codex",
                        "summary": "Use Codex by default",
                        "scope": {"kind": "project", "ref": "default"},
                    },
                    {
                        "item_id": "target-mode",
                        "key": "target_mode",
                        "value": "single_agent_target",
                        "summary": "Assume one Hermes agent",
                        "scope": {"kind": "project", "ref": "default"},
                    },
                    {
                        "item_id": "release-verified",
                        "key": "verification_status",
                        "value": "verified",
                        "summary": "Release is verified",
                        "scope": {"kind": "project", "ref": "default"},
                    },
                    {
                        "item_id": "private-note",
                        "key": "note",
                        "value": "raw-secret-token-123",
                        "summary": "Private note",
                        "scope": {"kind": "project", "ref": "default"},
                    },
                ]
            )

            inspection = build_memory_inspection(paths, wrapper_snapshot=wrapper_snapshot)

            self.assertEqual(inspection["schema_version"], "memory_inspection/v1")
            source_levels = {snapshot["source"]: snapshot["truth_level"] for snapshot in inspection["snapshots"]}
            self.assertEqual(source_levels["setup_profile"], "preference_default")
            self.assertEqual(source_levels["target_topology"], "setup_evidence")
            self.assertEqual(source_levels["wrapper_snapshot"], "supplied_hint")
            conflict_keys = {conflict["key"] for conflict in inspection["conflicts"]}
            self.assertIn("default_executor", conflict_keys)
            self.assertIn("target_mode", conflict_keys)
            self.assertIn("verification_status", conflict_keys)
            self.assertNotIn("raw-secret-token-123", json.dumps(inspection))

    def test_wrapper_snapshot_cannot_claim_runtime_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            wrapper_snapshot = _wrapper_snapshot(
                [
                    {
                        "item_id": "release-verified",
                        "key": "verification_status",
                        "value": "verified",
                        "summary": "Release is verified",
                        "scope": {"kind": "project", "ref": "default"},
                    }
                ]
            )
            wrapper_snapshot["source"] = "runtime_evidence"

            inspection = build_memory_inspection(paths, wrapper_snapshot=wrapper_snapshot)

            wrapper_sources = [snapshot for snapshot in inspection["snapshots"] if snapshot["source"] == "wrapper_snapshot"]
            self.assertEqual(len(wrapper_sources), 1)
            self.assertEqual(wrapper_sources[0]["truth_level"], "supplied_hint")
            self.assertIn("verification_status", {conflict["key"] for conflict in inspection["conflicts"]})
            review_items = {item["item_id"]: item for item in inspection["review_items"]}
            self.assertTrue(review_items["release-verified"]["blocked"])

    def test_review_card_is_distinct_from_runtime_status_card(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            inspection = build_memory_inspection(paths, wrapper_snapshot=_wrapper_snapshot([]))

            card = build_memory_review_card(inspection)

            self.assertEqual(card["schema_version"], "memory_review_card/v1")
            self.assertNotEqual(card["schema_version"], "status_card/v1")
            action_ids = {action["id"] for action in card["actions"]}
            self.assertIn("keep_memory", action_ids)
            self.assertIn("forget_memory", action_ids)
            self.assertIn("update_memory", action_ids)
            self.assertIn("change_memory_scope", action_ids)
            self.assertIn("apply_memory_updates", action_ids)
            self.assertIn("Memory review is not runtime execution evidence", card["claim_boundary"])

    def test_apply_batch_is_dry_run_idempotent_and_path_safe(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            batch = {
                "schema_version": "memory_update_batch/v1",
                "approved_by": "user",
                "source_surface": "discord",
                "updates": [
                    {
                        "op": "update",
                        "item_id": "executor-pref",
                        "scope": {"kind": "project", "ref": "default"},
                        "value": "claude-code",
                        "summary": "Prefer Claude Code prompt-only handoffs",
                        "reason": "User changed default coding preference",
                    }
                ],
            }

            dry_run = apply_memory_update_batch(paths, batch, dry_run=True)

            self.assertFalse(dry_run["applied"])
            self.assertFalse((paths.omh_home / "memory").exists())

            applied = apply_memory_update_batch(paths, batch)
            second = apply_memory_update_batch(paths, batch)

            self.assertTrue(applied["applied"])
            self.assertEqual(second["updates"][0]["status"], "noop")
            memory_file = paths.omh_home / "memory" / "scopes" / "project.json"
            self.assertTrue(memory_file.exists())
            stored = json.loads(memory_file.read_text(encoding="utf-8"))
            self.assertEqual(stored["items"]["executor-pref"]["value"], "claude-code")

            secret_batch = {
                "schema_version": "memory_update_batch/v1",
                "updates": [
                    {
                        "op": "update",
                        "item_id": "private-note",
                        "scope": {"kind": "project", "ref": "default"},
                        "key": "note",
                        "value": "raw-secret-token-123",
                        "summary": "Private note",
                    }
                ],
            }
            apply_memory_update_batch(paths, secret_batch)
            stored_after_secret = memory_file.read_text(encoding="utf-8")
            self.assertNotIn("raw-secret-token-123", stored_after_secret)
            private_note = json.loads(stored_after_secret)["items"]["private-note"]
            self.assertNotIn("value", private_note)

            unsafe = {
                "schema_version": "memory_update_batch/v1",
                "updates": [
                    {
                        "op": "update",
                        "item_id": "bad",
                        "scope": {"kind": "thread", "ref": "../../escape"},
                        "value": "bad",
                    }
                ],
            }
            with self.assertRaises(ValueError):
                apply_memory_update_batch(paths, unsafe)

    def test_memory_inspection_ignores_symlink_scope_escapes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            outside = root / "outside.json"
            outside.write_text(
                json.dumps(
                    {
                        "schema_version": "omh_memory_scope/v1",
                        "scope": {"kind": "project", "ref": "default"},
                        "items": {"outside": {"item_id": "outside", "key": "note", "value": "outside-secret-token"}},
                    }
                ),
                encoding="utf-8",
            )
            scopes = paths.memory_dir / "scopes"
            scopes.mkdir(parents=True)
            (scopes / "escape.json").symlink_to(outside)

            inspection = build_memory_inspection(paths)

            self.assertNotIn("outside-secret-token", json.dumps(inspection))
            self.assertNotIn("outside", {item["item_id"] for item in inspection["review_items"]})

    def test_handoff_context_pack_attaches_only_when_conflict_free(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            apply_memory_update_batch(
                paths,
                {
                    "schema_version": "memory_update_batch/v1",
                    "updates": [
                        {
                            "op": "update",
                            "item_id": "repo-verification",
                            "scope": {"kind": "project", "ref": "default"},
                            "key": "verification_command",
                            "value": "uv run python -m unittest discover -s tests -v",
                            "summary": "Run the unittest suite",
                            "reason": "Project verification default",
                        }
                    ],
                },
            )

            pack = build_handoff_context_pack(paths, executor_target="codex")
            payload = build_coding_delegation_payload(
                "risky refactor with token-secret-123",
                source="discord",
                executor_target="codex",
                include_message=True,
                context_pack=pack,
            )

            self.assertEqual(pack["schema_version"], "handoff_context_pack/v1")
            self.assertEqual(pack["blocked_by_conflicts"], [])
            self.assertIn("context_pack", payload["executor_handoff"])
            self.assertEqual(payload["executor_handoff"]["context_pack"]["schema_version"], "handoff_context_pack/v1")
            self.assertNotIn("token-secret-123", json.dumps(payload["executor_handoff"]["context_pack"]))

    def test_conflicting_context_pack_is_blocked_instead_of_attached(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            write_setup_profile(paths, ["prompt-only-coding"])
            inspection = build_memory_inspection(
                paths,
                wrapper_snapshot=_wrapper_snapshot(
                    [
                        {
                            "item_id": "executor-pref",
                            "key": "default_executor",
                            "value": "codex",
                            "summary": "Use Codex by default",
                            "scope": {"kind": "project", "ref": "default"},
                        }
                    ]
                ),
            )
            pack = build_handoff_context_pack(paths, inspection=inspection, executor_target="codex")

            payload = build_coding_delegation_payload("risky refactor", source="discord", executor_target="codex", context_pack=pack)

            self.assertTrue(pack["blocked_by_conflicts"])
            self.assertNotIn("context_pack", payload["executor_handoff"])
            self.assertIn("context_pack_blocked", payload["executor_handoff"])

    def test_malformed_context_pack_is_rejected_before_attachment(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            malformed = build_handoff_context_pack(paths, executor_target="codex")
            malformed["blocked_by_conflicts"] = "none"
            malformed["redaction_policy"] = "raw"
            malformed["included_context"] = [{"item_id": "bad", "key": "note", "value": "raw-secret-token"}]
            pack_path = root / "pack.json"
            pack_path.write_text(json.dumps(malformed), encoding="utf-8")

            with self.assertRaises(ValueError):
                read_handoff_context_pack_file(pack_path)
            with self.assertRaises(ValueError):
                build_coding_delegation_payload("risky refactor", source="discord", executor_target="codex", context_pack=malformed)


def _wrapper_snapshot(items: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "memory_snapshot/v1",
        "source": "wrapper_snapshot",
        "scope": {"kind": "project", "ref": "default"},
        "items": items,
        "redaction_policy": "metadata_only",
        "claim_boundary": "Wrapper supplied memory candidates are not trusted until reviewed.",
    }


if __name__ == "__main__":
    unittest.main()

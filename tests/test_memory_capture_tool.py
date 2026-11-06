"""The model's own write path into OMH memory: `omh_memory(action="capture")`.

The tool calls memory admission in-process -- the same bundle path the
`omh memory capture` CLI reaches through its adapters -- the default policy is
auto-safe so no operator step sits in the loop, and a duplicate names the
record already held instead of leaving a candidate nobody will approve.
"""

from __future__ import annotations

from contextlib import chdir
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _cli_harness import run_cli
from _credential_fixtures import AWS_ACCESS_KEY_ID
from _local_package import load_local_package

load_local_package()
from omh.paths import resolve_paths
from omh.plugin_bundle.omh.tools import memory_tool
from omh.plugin_bundle.omh.tools.memory_tool import MEMORY_ACTIONS, OMH_MEMORY_SCHEMA, omh_memory_handler
from omh.profiles.setup import write_setup_profile
from omh.workflows.memory import read_project_memory_policy, scan_project_memory_records
from project_identity_fixture import seed_project_identity
from test_memory_prefetch_canonical import SESSION, provider, rendered_ids
from test_memory_provider_hermes_order import hermes_turn


class InProcessCaptureTests(unittest.TestCase):
    """The tool against a real temp home: no runner, no shim, no stub."""

    def setUp(self) -> None:
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        seed_project_identity(self.root)
        (self.root / ".hermes").mkdir()
        # A sibling directory, not a child: identity resolution walks up.
        self.outside = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.store = self.root / ".omh"
        self.paths = resolve_paths(self.store, self.root / ".hermes")
        self.enterContext(patch.dict(os.environ, {"OMH_HOME": str(self.store), "HERMES_HOME": str(self.root / ".hermes")}))
        # Capture writes only in a session the provider described as an
        # operator console; this is the CLI one Hermes starts.
        provider(self.root)

    def call(self, cwd: Path | None = None, **args) -> dict:
        return json.loads(omh_memory_handler({"action": "capture", **args}, cwd=str(cwd or self.root), session_id=SESSION))

    def test_schema_advertises_capture_beside_the_four_reads(self) -> None:
        self.assertEqual(
            MEMORY_ACTIONS,
            ("status", "blocks", "read", "consolidation", "capture", "demote", "recall", "confirm", "correct", "retire"),
        )
        properties = OMH_MEMORY_SCHEMA["parameters"]["properties"]
        self.assertEqual(tuple(properties["action"]["enum"]), MEMORY_ACTIONS)
        self.assertEqual(properties["record_type"]["enum"], ["fact", "decision", "lesson", "procedure", "episode"])
        self.assertEqual(properties["scope"]["enum"], ["project", "user"])
        self.assertEqual(properties["retention_class"]["enum"], ["durable", "standard", "volatile"])
        description = OMH_MEMORY_SCHEMA["description"]
        for guidance in ("capture", "preference", "decision", "secrets", "raw logs", "transcripts", "task progress"):
            self.assertIn(guidance, description)

    def test_capture_reaches_replay_ready_on_disk_and_the_next_hermes_turn(self) -> None:
        summary = "The operator ships releases only from the release branch."
        result = self.call(summary=summary, tags=["release"])
        self.assertEqual(result["status"], "remembered", result)
        self.assertEqual(result["receipt_state"], "replay_ready")
        self.assertEqual(result["admission_state"], "approved_auto_safe")
        self.assertEqual((result["action"], result["source_backend"]), ("capture", "bundle_memory"))
        record_id = result["record_id"]
        memory_dir = self.store / "memory"
        stored = json.loads((memory_dir / "records" / f"{record_id}.json").read_text(encoding="utf-8"))
        self.assertEqual((stored["source"], stored["retention"]["class"], stored["tags"]), ("hermes_model", "durable", ["release"]))
        self.assertEqual(stored["scope"]["kind"], "project")
        self.assertEqual(len(list((memory_dir / "reviews").iterdir())), 1)
        index = json.loads((memory_dir / "index.json").read_text(encoding="utf-8"))
        self.assertIn(f"records/{record_id}.json", index["record_files"])
        candidates = sorted((memory_dir / "candidates").iterdir())

        again = self.call(summary=summary)
        self.assertEqual((again["status"], again["duplicate_of"], again["record_id"]), ("already_remembered", record_id, record_id))
        self.assertIsNone(again["receipt_state"])
        self.assertEqual(sorted((memory_dir / "candidates").iterdir()), candidates)

        pack = hermes_turn(provider(self.root), 1, "which branch do releases ship from")
        self.assertEqual(rendered_ids(pack), [record_id])

    def test_a_held_candidate_is_pending_review_with_its_reason(self) -> None:
        result = self.call(summary="The deploy freeze ends tomorrow.")
        self.assertEqual(result["status"], "pending_review", result)
        self.assertEqual(result["review_reason"], "relative_time_phrase")
        self.assertEqual(result["receipt_state"], "candidate_persisted")
        self.assertEqual(result["admission_state"], "pending_review")
        self.assertIsNone(result["record_id"])
        self.assertTrue((self.store / "memory" / "candidates" / f"{result['candidate_id']}.json").is_file())
        # The model restates a relative date itself; no review step is named to it.
        self.assertIn("absolute date", result["next_action"])
        self.assertIn("tell the user it was not kept", result["next_action"])
        self.assertNotIn("omh memory review", result["next_action"])

        write_setup_profile(self.paths, [], memory_mode="review-first")
        held = self.call(summary="Reviews happen on Thursdays.")
        self.assertEqual((held["status"], held["review_reason"]), ("pending_review", "policy_review_first"))
        # Only this reason has a person behind it, and the verbs are the real ones.
        self.assertIn("`omh memory review` shows it and `omh memory approve` releases it", held["next_action"])
        self.assertEqual(scan_project_memory_records(self.paths), ([], []))

    def test_unsafe_content_is_held_for_review_through_the_tool(self) -> None:
        # The safety classifier's verdict reaches the tool's status set as
        # pending_review with its own reason; the fake-runner suite pinned this
        # and the in-process suite must too.
        result = self.call(summary=f"Deploy key is {AWS_ACCESS_KEY_ID} for the staging bucket.")
        self.assertEqual(result["status"], "pending_review", result)
        self.assertEqual(result["review_reason"], "unsafe_content")
        # Protected content cannot be approved, so no approval is offered (it would exit 2).
        self.assertIn("there is nothing to approve", result["next_action"])
        self.assertNotIn("omh memory", result["next_action"])
        self.assertEqual(result["receipt_state"], "candidate_persisted")
        self.assertIsNone(result["record_id"])
        self.assertEqual(scan_project_memory_records(self.paths), ([], []))

    def test_the_mapper_never_upgrades_a_receipt_state(self) -> None:
        # An admission result that stopped at indexes_refreshed is reported at
        # that state; the tool relays what the write observed and claims no
        # later state.
        payload = {
            "captured": True,
            "auto_approved": True,
            "receipt_state": "indexes_refreshed",
            "candidate": {"candidate_id": "cand_x"},
            "record": {"record_id": "mem_x", "admission": {"state": "approved_auto_safe"}},
        }
        mapped = memory_tool._map_capture_payload(payload)
        self.assertEqual((mapped["status"], mapped["receipt_state"]), ("remembered", "indexes_refreshed"))
        self.assertEqual(memory_tool._map_capture_payload({**payload, "receipt_state": None})["receipt_state"], None)

    def test_memory_turned_off_is_refused_and_nothing_is_written(self) -> None:
        write_setup_profile(self.paths, [], memory_mode="off")
        result = self.call(summary="Anything.")
        self.assertEqual((result["status"], result["reason"]), ("refused", "project_memory_disabled"))
        self.assertFalse((self.store / "memory" / "candidates").exists())

    def test_scope_defaults_to_user_outside_a_repository_and_project_there_is_refused(self) -> None:
        result = self.call(cwd=self.outside, summary="Prefers terse replies.")
        self.assertEqual(result["status"], "remembered", result)
        stored = json.loads((self.store / "memory" / "records" / f"{result['record_id']}.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["scope"], {"kind": "user-global", "ref": "default"})
        refused = self.call(cwd=self.outside, summary="Repo fact.", scope="project")
        self.assertEqual((refused["status"], refused["reason"]), ("refused", "project_scope_unresolved"))

    def test_a_store_fault_is_an_error_result_not_a_raise(self) -> None:
        for fault in (OSError("disk"), TimeoutError("lock"), RuntimeError("bug")):
            with self.subTest(fault=type(fault).__name__), patch.object(memory_tool, "capture_project_memory_candidate", side_effect=fault):
                result = self.call(summary="A fact the store could not take.")
                self.assertEqual((result["status"], result["reason"]), ("error", type(fault).__name__))
                self.assertIsNone(result["receipt_state"])
                self.assertIn("next_action", result)

    def test_invalid_input_is_refused_before_admission_runs(self) -> None:
        with patch.object(memory_tool, "capture_project_memory_candidate", side_effect=AssertionError("must not run")):
            for args, reason in (
                ({}, "summary_required"),
                ({"summary": "x" * 501}, "summary_too_long"),
                ({"summary": "ok", "record_type": "rumor"}, "unsupported_record_type"),
                ({"summary": "ok", "retention_class": "forever"}, "unsupported_retention_class"),
                ({"summary": "ok", "tags": "deploy"}, "invalid_tags"),
                ({"summary": "ok", "scope": "thread"}, "unsupported_scope"),
            ):
                with self.subTest(reason=reason):
                    result = self.call(**args)
                    self.assertEqual((result["status"], result["reason"]), ("refused", reason))

    def test_the_four_read_actions_still_answer(self) -> None:
        for action in ("status", "blocks", "read", "consolidation"):
            with self.subTest(action=action):
                payload = json.loads(omh_memory_handler({"action": action}))
                self.assertEqual(payload["action"], action)


class CaptureInputRefusalTests(unittest.TestCase):
    def test_a_nul_byte_is_refused_before_admission_runs(self) -> None:
        # The CLI can never carry a NUL (it cannot travel in an argv), so the
        # tool refuses one rather than storing what the CLI path cannot.
        with patch.object(memory_tool, "capture_project_memory_candidate", side_effect=AssertionError("must not run")):
            for args in (
                {"action": "capture", "summary": "Use pnpm\x00 for installs."},
                {"action": "capture", "summary": "Use pnpm for installs.", "tags": ["tool\x00ing"]},
            ):
                result = json.loads(omh_memory_handler(args))
                self.assertEqual((result["status"], result["reason"]), ("refused", "control_character"), result)

    def test_an_unbound_home_is_an_error_result_not_a_raise(self) -> None:
        with patch.object(
            memory_tool, "_home", side_effect=memory_tool.runtime_paths.RuntimeBindingError("no profile")
        ), patch.object(memory_tool, "_session_cwd", return_value=None):
            result = json.loads(omh_memory_handler({"action": "capture", "summary": "Use pnpm for installs.", "scope": "user"}))
            self.assertEqual((result["status"], result["reason"]), ("error", "RuntimeBindingError"), result)


class DefaultPolicyTests(unittest.TestCase):
    def _paths(self, root: Path):
        return resolve_paths(root / ".omh", root / ".hermes")

    def test_no_profile_is_auto_safe_by_default(self) -> None:
        with TemporaryDirectory() as tmp:
            policy = read_project_memory_policy(self._paths(Path(tmp)))
            self.assertEqual((policy["mode"], policy["mode_source"]), ("auto-safe", "default"))
            self.assertTrue(policy["auto_approve_safe"])

    def test_setup_without_a_mode_is_defaulted_and_with_one_is_explicit(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            profile = write_setup_profile(paths, [])
            self.assertEqual(profile["memory_policy"]["mode_source"], "default")
            self.assertEqual(read_project_memory_policy(paths)["mode"], "auto-safe")
            write_setup_profile(paths, [], memory_mode="review-first")
            policy = read_project_memory_policy(paths)
            self.assertEqual((policy["mode"], policy["mode_source"]), ("review-first", "explicit"))
            write_setup_profile(paths, [], memory_mode="off")
            policy = read_project_memory_policy(paths)
            self.assertEqual((policy["mode"], policy["capture_enabled"]), ("off", False))

    def test_a_rerun_without_a_mode_keeps_the_mode_the_operator_chose(self) -> None:
        # Setup rewrites the whole profile. A rerun that does not mention
        # memory must not turn an explicit review-first into the default and
        # relabel it `default`, which the legacy rule would then flip.
        with TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            write_setup_profile(paths, [], memory_mode="review-first")
            profile = write_setup_profile(paths, [])
            self.assertEqual((profile["memory_policy"]["mode"], profile["memory_policy"]["mode_source"]), ("review-first", "explicit"))
            self.assertEqual(read_project_memory_policy(paths)["mode"], "review-first")
            # A new explicit choice still replaces it; a defaulted profile stays defaulted.
            write_setup_profile(paths, [], memory_mode="auto-safe")
            self.assertEqual(read_project_memory_policy(paths)["mode_source"], "explicit")
            paths.setup_profile_path.unlink()
            write_setup_profile(paths, [])
            self.assertEqual(write_setup_profile(paths, [])["memory_policy"]["mode_source"], "default")

    def test_a_profile_written_by_the_old_default_follows_the_new_one(self) -> None:
        # The owner machine's profile: review-first stored by the old default,
        # with no mode_source, because nobody passed --memory-mode.
        with TemporaryDirectory() as tmp:
            paths = self._paths(Path(tmp))
            profile = write_setup_profile(paths, [])
            for legacy_mode, expected in (("review-first", ("auto-safe", "default")), ("off", ("off", "legacy_explicit"))):
                with self.subTest(legacy_mode=legacy_mode):
                    policy = {key: value for key, value in profile["memory_policy"].items() if key != "mode_source"}
                    stored = {**profile, "memory_mode": legacy_mode, "memory_policy": {**policy, "mode": legacy_mode}}
                    paths.setup_profile_path.write_text(json.dumps(stored), encoding="utf-8")
                    policy = read_project_memory_policy(paths)
                    self.assertEqual((policy["mode"], policy["mode_source"]), expected)

    def test_memory_status_discloses_where_the_mode_came_from(self) -> None:
        with TemporaryDirectory() as tmp:
            status, stdout, stderr = run_cli(["--omh-home", str(Path(tmp) / ".omh"), "--hermes-home", str(Path(tmp) / ".hermes"), "memory", "status"])
            self.assertEqual(status, 0, stderr)
            policy = json.loads(stdout)["policy"]
            self.assertEqual((policy["mode"], policy["mode_source"]), ("auto-safe", "default"))


class OnDuplicateSkipTests(unittest.TestCase):
    def test_skip_persists_nothing_and_names_the_existing_record(self) -> None:
        with TemporaryDirectory() as tmp, chdir(tmp):
            root = Path(tmp)
            seed_project_identity(root)
            homes = ["--omh-home", str(root / "store"), "--hermes-home", str(root / "hermes")]
            status, stdout, stderr = run_cli([*homes, "memory", "capture", "Staging deploys run before production."])
            self.assertEqual(status, 0, stderr)
            first = json.loads(stdout)
            self.assertTrue(first["auto_approved"])
            record_id = first["record"]["record_id"]
            candidates = root / "store" / "memory" / "candidates"
            before = sorted(path.name for path in candidates.iterdir())

            status, stdout, stderr = run_cli([*homes, "memory", "capture", "--on-duplicate", "skip", "Staging  deploys run before PRODUCTION."])
            self.assertEqual(status, 0, stderr)
            skipped = json.loads(stdout)
            self.assertFalse(skipped["captured"])
            self.assertEqual((skipped["reason"], skipped["duplicate_of"]), ("duplicate", record_id))
            self.assertEqual(sorted(path.name for path in candidates.iterdir()), before)

            # The default keeps the reviewer-facing behaviour: a stamped candidate.
            status, stdout, stderr = run_cli([*homes, "memory", "capture", "Staging deploys run before production."])
            kept = json.loads(stdout)
            self.assertEqual(kept["candidate"]["duplicate_of"], record_id)
            self.assertEqual(kept["review_reason"], "duplicate")
            self.assertEqual(kept["receipt_state"], "candidate_persisted")
            self.assertEqual(len(list(candidates.iterdir())), len(before) + 1)

    def test_parallel_captures_of_one_fact_persist_one_record(self) -> None:
        # Two captures of the same fact arriving together both passed the
        # duplicate check and both persisted; the capture lock serializes the
        # check, the write and the approval.
        from concurrent.futures import ThreadPoolExecutor

        from omh.workflows.memory import capture_project_memory_candidate, scan_project_memory_records

        with TemporaryDirectory() as tmp, chdir(tmp):
            root = Path(tmp)
            seed_project_identity(root)
            paths = resolve_paths(root / "store", root / "hermes")

            def capture(_: int) -> dict:
                return capture_project_memory_candidate(paths, "Staging deploys run before production.", on_duplicate="skip")

            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(capture, range(8)))
            captured = [result for result in results if result["captured"]]
            self.assertEqual(len(captured), 1, [result.get("reason") for result in results])
            self.assertTrue(captured[0]["auto_approved"])
            skipped = [result for result in results if not result["captured"]]
            self.assertEqual({result["reason"] for result in skipped}, {"duplicate"})
            self.assertEqual({result["duplicate_of"] for result in skipped}, {captured[0]["record"]["record_id"]})
            records, unreadable = scan_project_memory_records(paths)
            self.assertEqual((len(records), unreadable), (1, []))

    def test_skip_only_counts_a_record_held_under_the_same_scope(self) -> None:
        # The same fact stated in another project is a different memory: a
        # record confined to project A is never recalled in project B, so
        # "already remembered" would drop it there for good. The reviewer
        # stamp (default mode) may still point across scopes.
        with TemporaryDirectory() as tmp, chdir(tmp):
            root = Path(tmp)
            seed_project_identity(root)
            homes = ["--omh-home", str(root / "store"), "--hermes-home", str(root / "hermes")]
            scope_a = ["--scope-kind", "project", "--scope-ref", "acme-project-a"]
            scope_b = ["--scope-kind", "project", "--scope-ref", "acme-project-b"]
            status, stdout, stderr = run_cli([*homes, "memory", "capture", *scope_a, "Use pnpm, not npm, for installs."])
            self.assertEqual(status, 0, stderr)
            held_in_a = json.loads(stdout)["record"]["record_id"]

            status, stdout, stderr = run_cli([*homes, "memory", "capture", "--on-duplicate", "skip", *scope_b, "Use pnpm, not npm, for installs."])
            self.assertEqual(status, 0, stderr)
            in_b = json.loads(stdout)
            self.assertTrue(in_b["captured"], in_b)
            self.assertTrue(in_b["auto_approved"], "a cross-scope match is not a duplicate here and must not block auto-safe")
            self.assertNotEqual(in_b["record"]["record_id"], held_in_a)
            self.assertNotIn("duplicate_of", in_b["candidate"])

            status, stdout, stderr = run_cli([*homes, "memory", "capture", "--on-duplicate", "skip", *scope_a, "Use pnpm, not npm, for installs."])
            self.assertEqual(status, 0, stderr)
            again_in_a = json.loads(stdout)
            self.assertFalse(again_in_a["captured"])
            self.assertEqual(again_in_a["duplicate_of"], held_in_a)

            # Default mode keeps the reviewer-facing cross-scope hint.
            status, stdout, stderr = run_cli([*homes, "memory", "capture", "--scope-kind", "project", "--scope-ref", "acme-project-c", "Use pnpm, not npm, for installs."])
            self.assertEqual(status, 0, stderr)
            self.assertIn(json.loads(stdout)["candidate"]["duplicate_of"], {held_in_a, in_b["record"]["record_id"]})


if __name__ == "__main__":
    unittest.main()

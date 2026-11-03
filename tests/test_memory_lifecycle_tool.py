"""The model's own memory lifecycle: `omh_memory` recall / confirm / correct / retire, and served counts.

Correct, confirm, retire and recall existed only as operator verbs in a package
the Hermes process cannot import, and the usage weight in the recall ranking
was always zero in chat because only a handoff attachment counted. These pin:

- the tool acts under the lens the memory provider published for its session
  (`memory_session_lens`), driven here through the provider's real
  `initialize` for each platform Hermes passes; no lens means a shared surface
  with no writes;
- recall is the prefetch selector, so its order is the order prefetch serves;
- confirm renews the review deadline like `omh memory confirm` and counts one
  `used` per record per session; correct links the new fact to the old record
  and the approval that admits it supersedes the old one into history; retire
  archives a live record only after this session saw it, and never deletes;
- a prefetch that returns a pack counts `served` in the record's own store, a
  queued re-render does not, and the ranking never reads `served`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from omh.paths import resolve_paths
from omh.plugin_bundle.omh import memory_admission
from omh.plugin_bundle.omh.memory_admission import approve_project_memory_candidate, capture_project_memory_candidate
from omh.plugin_bundle.omh.memory_provider import OmhMemoryProvider
from omh.plugin_bundle.omh.memory_records import read_record_store_snapshot, read_served_counts, select_prefetch_records
from omh.plugin_bundle.omh.memory_session_lens import read_session_lens
from omh.plugin_bundle.omh.tools import memory_tool
from omh.plugin_bundle.omh.tools.memory_tool import MEMORY_ACTIONS, OMH_MEMORY_SCHEMA, RETIRE_REASONS, omh_memory_handler
from omh.workflows.memory import build_project_memory_status
from omh.workflows.memory_lifecycle import build_memory_restore
from project_identity_fixture import seed_project_identity
from test_memory_prefetch_canonical import SESSION, rendered_ids
from test_memory_provider_hermes_order import hermes_turn

OTHER_PROJECT = "prj:" + "b" * 64


def start(home: Path, root: Path, session_id: str = SESSION, *, platform: str = "cli") -> OmhMemoryProvider:
    """Initialize a provider the way Hermes does (`agent/agent_init.py::_memory_provider_init_kwargs`)."""
    live = OmhMemoryProvider(home)
    live.initialize(
        session_id,
        hermes_home=str(root / ".hermes"),
        platform=platform,
        agent_context=platform if platform in ("cron", "subagent") else "primary",
        cwd=str(root),
    )
    return live


class _Home(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.identity = seed_project_identity(self.root)
        (self.root / ".hermes").mkdir()
        self.store = self.root / ".omh"
        self.memory = self.store / "memory"
        self.paths = resolve_paths(self.store, self.root / ".hermes")
        self.enterContext(patch.dict(os.environ, {"OMH_HOME": str(self.store), "HERMES_HOME": str(self.root / ".hermes")}))
        self.live = start(self.store, self.root)

    def call(self, action: str, session_id: str = SESSION, **args) -> dict:
        return json.loads(omh_memory_handler({"action": action, **args}, cwd=str(self.root), session_id=session_id))

    def capture(self, summary: str, **args) -> str:
        result = self.call("capture", summary=summary, **args)
        self.assertEqual(result["status"], "remembered", result)
        return str(result["record_id"])

    def seed(self, summary: str, **capture) -> str:
        defaults = {"scope_kind": "project", "scope_ref": self.identity, "source": "hermes_model", "retention_class": "durable"}
        payload = capture_project_memory_candidate(self.store, summary, **{**defaults, **capture})
        self.assertTrue(payload["auto_approved"], payload)
        return str(payload["record"]["record_id"])

    def record_path(self, record_id: str, store: Path | None = None) -> Path:
        return (store or self.store) / "memory" / "records" / f"{record_id}.json"

    def read_record(self, record_id: str) -> dict:
        return json.loads(self.record_path(record_id).read_text(encoding="utf-8"))

    def edit_record(self, record_id: str, **changes) -> None:
        record = self.read_record(record_id)
        for key, value in changes.items():
            record[key] = {**record.get(key, {}), **value} if isinstance(value, dict) else value
        self.record_path(record_id).write_text(json.dumps(record), encoding="utf-8")

    def store_bytes(self) -> dict[str, bytes]:
        # The session lens is the provider's bookkeeping, not the record store.
        return {
            str(path.relative_to(self.memory)): path.read_bytes()
            for path in sorted(self.memory.rglob("*"))
            if path.is_file() and "sessions" not in path.relative_to(self.memory).parts
        }

    def recalled(self, query: str, session_id: str = SESSION) -> list[str]:
        result = self.call("recall", session_id=session_id, query=query)
        self.assertIn(result["status"], ("found", "nothing_found"), result)
        return [row["record_id"] for row in result["records"]]

    def candidates_for(self, record_id: str) -> list[dict]:
        return [
            candidate
            for candidate in (json.loads(path.read_text(encoding="utf-8")) for path in (self.memory / "candidates").glob("*.json"))
            if candidate.get("record_id") == record_id
        ]


class SchemaTests(unittest.TestCase):
    def test_schema_advertises_the_four_lifecycle_actions_and_a_closed_reason_set(self) -> None:
        self.assertEqual(MEMORY_ACTIONS[-4:], ("recall", "confirm", "correct", "retire"))
        properties = OMH_MEMORY_SCHEMA["parameters"]["properties"]
        self.assertEqual(tuple(properties["action"]["enum"]), MEMORY_ACTIONS)
        self.assertEqual(tuple(properties["reason"]["enum"]), RETIRE_REASONS)
        self.assertEqual(RETIRE_REASONS, ("no_longer_true", "superseded", "user_asked"))
        for name in ("query", "limit", "record_id"):
            self.assertIn(name, properties)
        description = OMH_MEMORY_SCHEMA["description"]
        for word in ("recall", "confirm", "correct", "retire", "display_line"):
            self.assertIn(word, description)
        # The bot's persona owns its reply language; the schema names none.
        for language in ("English", "Korean", "language"):
            self.assertNotIn(language, description)

    def test_the_tool_reads_no_hermes_session_context_of_its_own(self) -> None:
        source = Path(memory_tool.__file__).read_text(encoding="utf-8")
        self.assertNotIn("session_context", source)
        self.assertNotIn("_SESSION_PLATFORM", source)


class ProviderLensTests(_Home):
    """The real seam: provider `initialize` per platform, then a tool call in that session."""

    def test_each_platform_reaches_exactly_what_its_provider_decided(self) -> None:
        project = self.capture("The project deploy summary goes to the release channel.")
        user_global = self.capture("The operator prefers concise deploy summaries.", scope="user")
        # (platform, shared surface, writes enabled) as the provider decides them.
        for platform, shared, writes in (
            ("cli", False, True),
            ("tui", False, True),
            ("desktop", False, True),
            ("telegram", True, True),
            ("cron", True, False),
            ("subagent", True, False),
        ):
            with self.subTest(platform=platform):
                session_id = f"session-{platform}"
                live = start(self.store, self.root, session_id, platform=platform)
                lens = read_session_lens(self.store, session_id)
                self.assertEqual((lens["shared_surface"], lens["writes_enabled"]), (shared, writes))
                served = rendered_ids(hermes_turn(live, 1, "deploy summary"))
                self.assertEqual(sorted(self.recalled("deploy summary", session_id)), sorted(served))
                self.assertEqual(sorted(served), [] if shared else sorted([project, user_global]))
                before = self.store_bytes()
                result = self.call("confirm", session_id=session_id, record_id=project)
                if not writes:
                    self.assertEqual((result["status"], result["reason"]), ("refused", "writes_disabled"))
                elif shared:
                    self.assertEqual((result["status"], result["reason"]), ("refused", "record_not_in_scope"))
                else:
                    self.assertEqual(result["status"], "confirmed", result)
                if result["status"] == "refused":
                    self.assertEqual(self.store_bytes(), before)
                for action, extra in (("correct", {"summary": "The deploy summary goes to the ops channel."}), ("retire", {"reason": "user_asked"})):
                    if not writes:
                        refused = self.call(action, session_id=session_id, record_id=project, **extra)
                        self.assertEqual((refused["status"], refused["reason"]), ("refused", "writes_disabled"), action)
                live.shutdown()

    def test_without_a_published_lens_the_tool_fails_closed(self) -> None:
        record_id = self.capture("The project deploy summary goes to the release channel.")
        before = self.store_bytes()
        for session_id in ("never-initialized", ""):
            with self.subTest(session_id=session_id):
                lens = memory_tool._session_lens({"session_id": session_id})
                self.assertEqual((lens.bound, lens.shared_surface, lens.writes_enabled, lens.principal_context), (False, True, False, None))
                result = self.call("recall", session_id=session_id, query="deploy summary")
                self.assertEqual(
                    (result["status"], result["reason"], result["lens_state"]), ("refused", "session_lens_unavailable", "unbound"),
                    "an unbound session is not reported as nothing matching",
                )
                for action, extra in (("confirm", {}), ("correct", {"summary": "The summary goes elsewhere."}), ("retire", {"reason": "user_asked"})):
                    refused = self.call(action, session_id=session_id, record_id=record_id, **extra)
                    self.assertEqual((refused["status"], refused["reason"]), ("refused", "session_lens_unavailable"), action)
        self.assertEqual(self.store_bytes(), before)

    def test_a_compression_switch_moves_the_lens_and_carries_what_the_session_saw(self) -> None:
        record_id = self.capture("The build cache lives on the shared NFS volume.")
        self.assertEqual(self.recalled("build cache shared volume"), [record_id])
        self.call("confirm", record_id=record_id)

        self.live.on_session_switch("session-compressed", parent_session_id=SESSION)  # as compression calls it

        self.assertIsNone(read_session_lens(self.store, SESSION))
        moved = read_session_lens(self.store, "session-compressed")
        self.assertEqual((moved["seen"], moved["confirmed"]), ([record_id], [record_id]))
        old = self.call("confirm", record_id=record_id)
        self.assertEqual((old["status"], old["reason"]), ("refused", "session_lens_unavailable"))
        again = self.call("confirm", session_id="session-compressed", record_id=record_id)
        self.assertEqual((again["status"], again["used_recorded"]), ("confirmed", False), "the carried confirmation still counts once")
        self.assertEqual(self.call("retire", session_id="session-compressed", record_id=record_id, reason="user_asked")["status"], "retired")

    def test_a_reset_switch_starts_an_empty_lens(self) -> None:
        record_id = self.capture("The build cache lives on the shared NFS volume.")
        self.recalled("build cache shared volume")
        self.live.on_session_switch("session-new", reset=True)  # /new, /reset
        lens = read_session_lens(self.store, "session-new")
        self.assertEqual((lens["seen"], lens["confirmed"]), ([], []))
        refused = self.call("retire", session_id="session-new", record_id=record_id, reason="user_asked")
        self.assertEqual((refused["status"], refused["reason"]), ("refused", "record_not_seen_this_session"))

    def test_a_rewound_switch_keeps_the_lens(self) -> None:
        # `rewound` means the id did not change, whatever id the call carries.
        self.live.on_session_switch("session-elsewhere", rewound=True)
        self.assertIsNotNone(read_session_lens(self.store, SESSION))
        self.assertIsNone(read_session_lens(self.store, "session-elsewhere"))

    def test_prefetch_under_a_new_session_id_rebinds_as_a_new_conversation(self) -> None:
        record_id = self.capture("OMH recall serves deterministic memory packs.")
        self.assertEqual(self.recalled("omh recall memory packs"), [record_id])
        self.call("confirm", record_id=record_id)
        self.live.on_turn_start(1, "omh recall memory packs")
        self.live.prefetch("omh recall memory packs", session_id="session-leased")  # turn-lease reload, or a racing /new
        self.assertIsNone(read_session_lens(self.store, SESSION))
        lens = read_session_lens(self.store, "session-leased")
        # Only what this prefetch served is seen; nothing from the old conversation carries.
        self.assertEqual((lens["seen"], lens["confirmed"]), ([record_id], []))
        again = self.call("confirm", session_id="session-leased", record_id=record_id)
        self.assertEqual((again["status"], again["used_recorded"]), ("confirmed", True))

    def test_a_switch_drops_the_principal_bound_to_the_old_session(self) -> None:
        principal = "principal:v1:" + "a" * 64
        context = {
            "schema_version": "memory_principal_context/v1",
            "principal": principal,
            "profile_ref": "profile_fixture",
            "surface_ref": "fixture",
            "session_ref": SESSION,
            "turn_ref": "turn_1",
            "actor_kind": "human",
            "identity_evidence_refs": ["evidence:fixture"],
            "binding_state": "validated_local",
        }
        live = OmhMemoryProvider(self.store)
        live.initialize(SESSION, hermes_home=str(self.root / ".hermes"), platform="cli", agent_context="primary", cwd=str(self.root), principal_context=context)
        live.on_turn_start(1, "deploy preference", principal_context=context)
        payload = capture_project_memory_candidate(
            self.store, "The operator prefers deploy summaries as bullet lists.", scope_kind="user",
            principal_context=context, source="hermes_model", retention_class="durable",
        )
        record_id = payload["record"]["record_id"]
        self.assertEqual(read_session_lens(self.store, SESSION)["principal_context"]["principal"], principal)
        self.assertEqual(self.recalled("deploy summaries bullet lists"), [record_id])

        live.on_session_switch("session-b", parent_session_id=SESSION)

        self.assertIsNone(read_session_lens(self.store, "session-b")["principal_context"])
        self.assertEqual(self.recalled("deploy summaries bullet lists", "session-b"), [])
        refused = self.call("confirm", session_id="session-b", record_id=record_id)
        self.assertEqual((refused["status"], refused["reason"]), ("refused", "record_not_in_scope"))

    def test_shutdown_withdraws_the_lens(self) -> None:
        record_id = self.capture("The project deploy summary goes to the release channel.")
        self.live.shutdown()
        result = self.call("confirm", record_id=record_id)
        self.assertEqual((result["status"], result["reason"]), ("refused", "session_lens_unavailable"))


class RecallTests(_Home):
    def test_recall_is_the_prefetch_order_over_in_scope_eligible_records_only(self) -> None:
        ids = [
            self.capture("The release train deploys from the release branch on Fridays.", tags=["release"]),
            self.capture("Release notes for the deploy are drafted in the docs folder.", tags=["release", "docs"]),
            self.capture("The staging deploy uses the blue cluster before every release.", scope="user"),
        ]
        foreign = self.seed("The release deploy of the other project runs on Mondays.", scope_ref=OTHER_PROJECT)
        before = self.store_bytes()

        result = self.call("recall", query="release deploy")

        self.assertEqual((result["status"], result["schema_version"], result["lens_state"]), ("found", "omh_memory_recall/v1", "provider"))
        recalled = [row["record_id"] for row in result["records"]]
        self.assertEqual(sorted(recalled), sorted(ids))
        self.assertNotIn(foreign, recalled)
        self.assertNotIn("display_line", result)
        self.assertEqual(self.store_bytes(), before, "recall writes nothing to the store, usage included")
        self.assertEqual(rendered_ids(hermes_turn(start(self.store, self.root), 1, "release deploy")), recalled)

    def test_limit_cuts_the_same_order(self) -> None:
        for index in range(4):
            self.capture(f"Deploy checklist step {index} for the release runbook is documented.")
        full = self.recalled("deploy release runbook")
        result = self.call("recall", query="deploy release runbook", limit=2)
        self.assertEqual([row["record_id"] for row in result["records"]], full[:2])

    def test_bad_query_or_limit_is_refused(self) -> None:
        for args, reason in (
            ({}, "query_invalid"),
            ({"query": "x" * 501}, "query_invalid"),
            ({"query": "deploy", "limit": 7}, "limit_invalid"),
            ({"query": "deploy", "limit": 0}, "limit_invalid"),
            ({"query": "deploy", "limit": True}, "limit_invalid"),
            ({"query": "deploy", "limit": "3"}, "limit_invalid"),
        ):
            result = self.call("recall", **args)
            self.assertEqual((result["status"], result["reason"]), ("refused", reason), args)


class ConfirmTests(_Home):
    def test_confirm_renews_a_passed_deadline_and_counts_one_use_only(self) -> None:
        record_id = self.capture("The on-call rotation hands over on Mondays at noon.", retention_class="standard")
        past = "2026-01-01T00:00:00Z"
        self.edit_record(
            record_id,
            staleness={"review_due_at": past, "stale_after": past, "stale_after_days": 30},
            revalidation={"deadline": past},
        )
        self.assertEqual(self.recalled("on-call rotation"), [], "a stale record is not recallable")

        result = self.call("confirm", record_id=record_id)

        self.assertEqual(result["status"], "confirmed", result)
        self.assertTrue(result["was_stale"])
        self.assertTrue(result["deadline_renewed"])
        self.assertEqual(result["previous_review_due_at"], past)
        renewed = datetime.fromisoformat(result["review_due_at"].replace("Z", "+00:00"))
        expected = datetime.now(timezone.utc) + timedelta(days=30)
        self.assertLess(abs((renewed - expected).total_seconds()), 120, "the record's own 30-day cadence")
        stored = self.read_record(record_id)
        self.assertEqual(stored["staleness"]["review_due_at"], result["review_due_at"])
        self.assertEqual(stored["revalidation"]["confirmed_by"], "hermes_model")
        self.assertTrue(result["used_recorded"])
        usage = json.loads((self.memory / "usage.json").read_text(encoding="utf-8"))
        self.assertEqual(usage["schema_version"], "omh_memory_recall_usage/v1")
        self.assertEqual(usage["records"][record_id]["times_recalled"], 1)
        self.assertFalse((self.memory / "served.json").exists(), "confirm feeds used, never served")
        self.assertEqual(self.recalled("on-call rotation"), [record_id])
        self.assertEqual(read_record_store_snapshot((self.store,)).usage[record_id]["times_recalled"], 1)

    def test_one_use_per_record_per_session(self) -> None:
        record_id = self.capture("The project license is Apache-2.0.")
        first = self.call("confirm", record_id=record_id)
        again = self.call("confirm", record_id=record_id)
        self.assertEqual((first["used_recorded"], again["used_recorded"], again["used_already_counted_this_session"]), (True, False, True))
        start(self.store, self.root, "session-b")
        self.assertTrue(self.call("confirm", session_id="session-b", record_id=record_id)["used_recorded"])
        usage = json.loads((self.memory / "usage.json").read_text(encoding="utf-8"))
        self.assertEqual(usage["records"][record_id]["times_recalled"], 2)

    def test_confirm_on_a_durable_record_counts_the_use_and_rewrites_nothing(self) -> None:
        record_id = self.capture("The project license is Apache-2.0.")
        record_bytes = self.record_path(record_id).read_bytes()
        result = self.call("confirm", record_id=record_id)
        self.assertEqual((result["status"], result["deadline_renewed"], result["review_due_at"]), ("confirmed", False, None))
        self.assertEqual(self.record_path(record_id).read_bytes(), record_bytes)

    def test_a_usage_entry_keeps_keys_another_writer_added(self) -> None:
        record_id = self.capture("The project license is Apache-2.0.")
        (self.memory / "usage.json").write_text(
            json.dumps({"schema_version": "omh_memory_recall_usage/v1", "records": {record_id: {"times_recalled": 4, "last_recalled_at": "", "note": "kept"}}}),
            encoding="utf-8",
        )
        self.call("confirm", record_id=record_id)
        entry = json.loads((self.memory / "usage.json").read_text(encoding="utf-8"))["records"][record_id]
        self.assertEqual((entry["times_recalled"], entry["note"]), (5, "kept"))

    def test_confirm_refuses_expired_superseded_and_source_changed_records(self) -> None:
        expired = self.capture("The freeze window holds through the launch.", retention_class="volatile")
        self.edit_record(expired, ttl={"expires_at": "2026-01-02T00:00:00Z"}, retention={"expires_at": "2026-01-02T00:00:00Z"})
        superseded = self.capture("The build runs on the old runners.")
        self.edit_record(superseded, superseded_by={"id": "mem_successor", "id_key": "record_id"})
        cited = self.root / "runbook.md"
        cited.write_text("restart the indexer first\n", encoding="utf-8")
        sourced = self.seed("The runbook restarts the indexer before reindexing.", source_ref=str(cited))
        cited.write_text("restart the indexer last\n", encoding="utf-8")
        before = self.store_bytes()
        for record_id, reason in ((expired, "retention_expired"), (superseded, "superseded"), (sourced, "source_requires_correction")):
            result = self.call("confirm", record_id=record_id)
            self.assertEqual((result["status"], result["reason"]), ("refused", reason), record_id)
        self.assertEqual(self.store_bytes(), before)


class CorrectTests(_Home):
    def test_an_approved_correction_supersedes_the_old_record_into_history(self) -> None:
        old = self.capture("The deploy window is Friday afternoon.", tags=["deploy"])
        result = self.call("correct", record_id=old, summary="The deploy window is Thursday afternoon.")

        self.assertEqual(result["status"], "corrected", result)
        self.assertEqual(result["superseded_record_id"], old)
        new = result["record_id"]
        self.assertNotEqual(new, old)
        self.assertTrue(result["display_line"].startswith("✏️ OMH corrected: The deploy window is Thursday"))
        self.assertFalse(self.record_path(old).exists())
        history = json.loads((self.memory / "history" / f"{old}.r1.json").read_text(encoding="utf-8"))
        self.assertEqual(history["summary"], "The deploy window is Friday afternoon.")
        self.assertEqual((history["superseded_by"]["id"], history["superseded_by"]["id_key"]), (new, "record_id"))
        stored = self.read_record(new)
        self.assertEqual((stored["source"], stored["tags"], stored["scope"], stored["derived_from"]), ("hermes_model", ["deploy"], history["scope"], [old]))
        self.assertEqual(self.recalled("deploy window afternoon"), [new])
        index = json.loads((self.memory / "index.json").read_text(encoding="utf-8"))
        self.assertNotIn(f"records/{old}.json", index["record_files"])
        [old_candidate] = self.candidates_for(old)
        self.assertEqual(old_candidate["status"], "superseded")
        with self.assertRaises(ValueError):
            approve_project_memory_candidate(self.store, old_candidate["candidate_id"], approved_by="operator")
        self.assertFalse(self.record_path(old).exists(), "re-approval cannot resurrect the corrected record")

    def test_a_held_correction_keeps_the_old_record_until_its_approval_supersedes_it(self) -> None:
        old = self.capture("The deploy freeze ends on 2026-11-30.")
        result = self.call("correct", record_id=old, summary="The deploy freeze ends in 3 weeks.")
        self.assertEqual((result["status"], result["review_reason"]), ("pending_review", "relative_time_phrase"))
        self.assertTrue(self.record_path(old).exists())
        self.assertFalse((self.memory / "history").exists())
        self.assertEqual(self.recalled("deploy freeze ends"), [old])

        approved = approve_project_memory_candidate(self.store, result["candidate_id"], approved_by="operator")

        self.assertEqual(approved["supersession"]["state"], "superseded")
        self.assertFalse(self.record_path(old).exists())
        self.assertTrue((self.memory / "history" / f"{old}.r1.json").is_file())
        self.assertEqual(self.recalled("deploy freeze ends"), [approved["record"]["record_id"]])

    def test_a_held_correction_supersedes_only_the_revision_it_read(self) -> None:
        old = self.capture("The deploy freeze ends on 2026-11-30.")
        result = self.call("correct", record_id=old, summary="The deploy freeze ends in 3 weeks.")
        self.edit_record(old, revision=2)  # rewritten after the correction was filed
        approved = approve_project_memory_candidate(self.store, result["candidate_id"], approved_by="operator")
        self.assertEqual(approved["supersession"], {"record_id": old, "state": "skipped", "reason": "revision_moved"})
        self.assertTrue(self.record_path(old).exists())
        self.assertFalse((self.memory / "history").exists())

    def test_derived_from_alone_never_supersedes(self) -> None:
        source = self.capture("The deploy window is Friday afternoon.")
        payload = capture_project_memory_candidate(
            self.store, "Weekly summary: deploys happen on Friday afternoons.", scope_kind="project", scope_ref=self.identity,
            source="rollup", record_type="episode", derived_from=[source], force_review=True,
        )
        approve_project_memory_candidate(self.store, payload["candidate"]["candidate_id"], approved_by="operator")
        self.assertTrue(self.record_path(source).exists())

    def test_a_correction_keeps_perspective_source_and_cadence(self) -> None:
        cited = self.root / "deploy.md"
        cited.write_text("friday\n", encoding="utf-8")
        old = self.seed(
            "Hermes deploys on Friday afternoons.", retention_class="standard", stale_after_days=30,
            source_ref=str(cited), observer="hermes", observed="hermes",
        )
        result = self.call("correct", record_id=old, summary="Hermes deploys on Thursday afternoons.")
        self.assertEqual(result["status"], "corrected", result)
        stored = self.read_record(result["record_id"])
        self.assertEqual(stored["perspective"], {"observer": "hermes", "observed": "hermes"})
        self.assertEqual(stored["source_ref"], str(cited))
        self.assertEqual((stored["staleness"]["stale_after_days"], stored["retention"]["class"]), (30, "standard"))

    def test_an_instruction_shaped_correction_is_refused_and_nothing_moves(self) -> None:
        old = self.capture("The deploy window is Friday afternoon.")
        before = self.store_bytes()
        result = self.call("correct", record_id=old, summary="You must deploy on Thursday afternoon.")
        self.assertEqual((result["status"], result["reason"], result["instruction_cue"]), ("refused", "instruction_shaped_summary", "you must"))
        self.assertNotIn("display_line", result)
        self.assertEqual(self.store_bytes(), before)

    def test_the_same_text_is_unchanged_and_a_missing_summary_is_refused(self) -> None:
        old = self.capture("The deploy window is Friday afternoon.")
        before = self.store_bytes()
        same = self.call("correct", record_id=old, summary="The deploy window is Friday afternoon.")
        self.assertEqual((same["status"], same["reason"]), ("refused", "unchanged"))
        missing = self.call("correct", record_id=old)
        self.assertEqual((missing["status"], missing["reason"]), ("refused", "summary_required"))
        self.assertEqual(self.store_bytes(), before)

    def test_an_old_record_retired_mid_correction_is_reported_not_superseded(self) -> None:
        old = self.capture("The deploy window is Friday afternoon.")
        original = memory_admission.write_project_memory_candidate_unlocked
        state = {"done": False}

        def write_then_retire(home, candidate):
            original(home, candidate)
            if not state["done"]:
                state["done"] = True
                self.record_path(old).unlink()  # a concurrent call archived it

        with patch.object(memory_admission, "write_project_memory_candidate_unlocked", write_then_retire):
            result = self.call("correct", record_id=old, summary="The deploy window is Thursday afternoon.")
        self.assertEqual((result["status"], result["superseded_record_id"], result["supersede_skipped"]), ("corrected", None, "record_absent"))
        self.assertIn("already retired or replaced", result["next_action"])
        self.assertFalse((self.memory / "history").exists())


class RetireTests(_Home):
    def test_retire_needs_this_session_to_have_seen_a_live_record(self) -> None:
        record_id = self.capture("The build cache lives on the shared NFS volume.")
        before = self.store_bytes()
        unseen = self.call("retire", record_id=record_id, reason="no_longer_true")
        self.assertEqual((unseen["status"], unseen["reason"]), ("refused", "record_not_seen_this_session"))
        self.assertEqual(self.store_bytes(), before)
        self.assertEqual(self.recalled("build cache shared volume"), [record_id])

        result = self.call("retire", record_id=record_id, reason="no_longer_true")

        self.assertEqual(result["status"], "retired", result)
        self.assertTrue(result["display_line"].startswith("🗄️ OMH retired: The build cache"))
        self.assertFalse(self.record_path(record_id).exists())
        archived = self.memory / "archive" / result["archived_as"]
        self.assertEqual(json.loads(archived.read_text(encoding="utf-8"))["record_id"], record_id, "moved, never deleted")
        journal = [json.loads(line) for line in (self.memory / "archive" / "retirements.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(
            [(line["record_id"], line["reason"], line["retired_by"], line["session_id"]) for line in journal],
            [(record_id, "no_longer_true", "hermes_model", SESSION)],
        )
        self.assertEqual([candidate["status"] for candidate in self.candidates_for(record_id)], ["retired"])
        self.assertEqual(self.recalled("build cache shared volume"), [])
        restore = build_memory_restore(self.paths, record_id, 1, now=datetime.now(timezone.utc))
        self.assertTrue(restore.report["eligible"], restore.report)

    def test_a_served_record_counts_as_seen(self) -> None:
        record_id = self.capture("OMH recall serves deterministic memory packs.")
        hermes_turn(self.live, 1, "omh recall memory packs")
        self.assertEqual(self.call("retire", record_id=record_id, reason="user_asked")["status"], "retired")

    def test_an_expired_record_needs_no_sighting(self) -> None:
        record_id = self.capture("The freeze window holds through the launch.", retention_class="volatile")
        self.edit_record(record_id, ttl={"expires_at": "2026-01-02T00:00:00Z"}, retention={"expires_at": "2026-01-02T00:00:00Z"})
        self.assertEqual(self.call("retire", record_id=record_id, reason="no_longer_true")["status"], "retired")

    def test_retire_without_a_closed_reason_is_refused(self) -> None:
        record_id = self.capture("The build cache lives on the shared NFS volume.")
        before = self.store_bytes()
        for reason in ("", "because", "deleted"):
            result = self.call("retire", record_id=record_id, reason=reason)
            self.assertEqual((result["status"], result["reason"]), ("refused", "unsupported_reason"), reason)
        self.assertEqual(self.store_bytes(), before)

    def test_a_failure_after_the_move_says_the_record_was_archived(self) -> None:
        record_id = self.capture("The build cache lives on the shared NFS volume.")
        self.recalled("build cache shared volume")
        with patch.object(memory_tool, "write_memory_index_unlocked", side_effect=OSError("disk")):
            result = self.call("retire", record_id=record_id, reason="user_asked")
        self.assertEqual((result["status"], result["reason"]), ("error", "OSError"))
        self.assertTrue((self.memory / "archive" / result["archived_as"]).is_file())
        self.assertIn("archived", result["next_action"])
        self.assertNotIn("display_line", result)


class ConfinementTests(_Home):
    def test_out_of_scope_and_unknown_records_are_refused_and_nothing_is_written(self) -> None:
        self.capture("The local deploy uses the release branch.")
        foreign = self.seed("The other project deploys from main.", scope_ref=OTHER_PROJECT)
        other_thread = self.seed("This thread decided to deploy from main.", scope_kind="thread", scope_ref="session-other")
        codex_lens = self.seed("Codex deploys from main.", observer="hermes", observed="codex")
        before = self.store_bytes()
        cases = {
            "confirm": {},
            "correct": {"summary": "The other project deploys from trunk."},
            "retire": {"reason": "user_asked"},
        }
        for action, extra in cases.items():
            for record_id, reason in (
                (foreign, "record_not_in_scope"),
                (other_thread, "record_not_in_scope"),
                (codex_lens, "record_not_in_scope"),
                ("mem_doesnotexist", "record_not_found"),
                ("../escape", "record_not_found"),
            ):
                result = self.call(action, record_id=record_id, **extra)
                self.assertEqual((result["status"], result["reason"]), ("refused", reason), (action, record_id))
                self.assertNotIn("display_line", result)
                self.assertNotIn("from main", json.dumps(result), "no foreign content")
            missing = self.call(action, **extra)
            self.assertEqual((missing["status"], missing["reason"]), ("refused", "record_id_required"))
        self.assertEqual(self.store_bytes(), before)

    def test_this_sessions_thread_record_is_in_scope(self) -> None:
        own = self.seed("This thread decided to deploy from the release branch.", scope_kind="thread", scope_ref=SESSION)
        self.assertEqual(self.recalled("thread decided deploy release branch"), [own])
        self.assertEqual(self.call("confirm", record_id=own)["status"], "confirmed")

    def test_a_store_fault_is_an_error_result_not_a_raise(self) -> None:
        with patch.object(memory_tool, "read_record_store_snapshot", side_effect=PermissionError("denied")):
            result = self.call("recall", query="deploy")
        self.assertEqual((result["status"], result["reason"]), ("error", "PermissionError"))


class TwoHomeTests(unittest.TestCase):
    """A repository `.omh` and a separate OMH home: the prefetch's home order, for reads and writes."""

    def setUp(self) -> None:
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.identity = seed_project_identity(self.root)
        (self.root / ".hermes").mkdir()
        self.user = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.enterContext(patch.dict(os.environ, {"OMH_HOME": str(self.user), "HERMES_HOME": str(self.root / ".hermes")}))
        self.live = start(self.user, self.root)

    def test_the_project_copy_of_a_shared_id_wins_and_takes_the_writes(self) -> None:
        payload = capture_project_memory_candidate(
            self.root / ".omh", "The project deploys from the release branch.", scope_kind="project", scope_ref=self.identity,
            source="hermes_model", retention_class="durable",
        )
        record_id = payload["record"]["record_id"]
        project_memory = self.root / ".omh" / "memory"
        for directory in ("records", "reviews"):
            shutil.copytree(project_memory / directory, self.user / "memory" / directory, dirs_exist_ok=True)
        user_copy = self.user / "memory" / "records" / f"{record_id}.json"
        user_copy.write_text(json.dumps({**json.loads(user_copy.read_text(encoding="utf-8")), "summary": "The user copy deploys from main."}), encoding="utf-8")

        result = json.loads(omh_memory_handler({"action": "recall", "query": "deploys release branch main"}, cwd=str(self.root), session_id=SESSION))
        self.assertEqual([(row["record_id"], row["summary"]) for row in result["records"]], [(record_id, "The project deploys from the release branch.")])
        json.loads(omh_memory_handler({"action": "confirm", "record_id": record_id}, cwd=str(self.root), session_id=SESSION))
        self.assertTrue((project_memory / "usage.json").is_file())
        self.assertFalse((self.user / "memory" / "usage.json").exists())

        hermes_turn(self.live, 1, "deploys release branch")
        self.assertEqual(read_served_counts(self.root / ".omh")[record_id]["times_served"], 1, "served lands in the record's own store")
        self.assertEqual(read_served_counts(self.user), {})


class ServedCounterTests(_Home):
    def test_a_returned_pack_counts_served_once_and_a_queued_render_never(self) -> None:
        record_id = self.capture("OMH recall serves deterministic memory packs.")
        live = start(self.store, self.root)
        live.queue_prefetch("omh recall memory packs")
        self.assertEqual(read_served_counts(self.store), {}, "a queued re-render is not a serve")

        pack = hermes_turn(live, 1, "omh recall memory packs")
        self.assertEqual(rendered_ids(pack), [record_id])
        live.prefetch("omh recall memory packs")  # a second API call in the same turn
        self.assertEqual(read_served_counts(self.store)[record_id]["times_served"], 1)
        # The record is still in this conversation: a later turn does not serve it again.
        self.assertEqual(rendered_ids(hermes_turn(live, 2, "omh recall memory packs")), [])
        self.assertEqual(read_served_counts(self.store)[record_id]["times_served"], 1)
        # After a compaction drops it from context, the next turn serves it once more.
        live.on_session_switch(SESSION, reset=False)
        hermes_turn(live, 3, "omh recall memory packs")
        self.assertEqual(read_served_counts(self.store)[record_id]["times_served"], 2)
        self.assertFalse((self.memory / "usage.json").exists(), "serving never feeds the ranking's usage counter")
        status = build_project_memory_status(self.paths)["recall_usage"]
        self.assertEqual(status["store"], str(self.paths.memory_dir))
        self.assertEqual(status["served"], {"records": 1, "total": 2, "top": [{"record_id": record_id, "count": 2}]})
        self.assertEqual((status["used"]["total"], status["ranking_reads"]), (0, "used"))

    def test_ranking_never_reads_served(self) -> None:
        first = self.capture("Deploy notes alpha cover the release checklist.")
        second = self.capture("Deploy notes bravo cover the release checklist.")

        def order() -> tuple[list[str], list[dict]]:
            selection = select_prefetch_records(
                read_record_store_snapshot((self.store,)),
                "deploy notes release checklist",
                allowed_scopes=[{"kind": "project", "ref": self.identity}],
            )
            items = selection.pack["included_records"]
            return [item["record_id"] for item in items], [item["ranking"] for item in items]

        baseline = order()
        last = baseline[0][-1]
        (self.memory / "served.json").write_text(
            json.dumps({"schema_version": "omh_memory_served/v1", "records": {last: {"times_served": 999, "last_served_at": "2026-10-01T00:00:00Z"}}}),
            encoding="utf-8",
        )
        self.assertEqual(order(), baseline)
        self.assertEqual(sorted(baseline[0]), sorted([first, second]))
        self.call("confirm", record_id=last)
        ids, rankings = order()
        self.assertEqual(rankings[ids.index(last)]["times_recalled"], 1, "a confirmed use is what the ranking reads")


if __name__ == "__main__":
    unittest.main()

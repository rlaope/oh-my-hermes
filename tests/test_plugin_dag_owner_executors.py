"""A dag-ulw node may name a configured executor id as its owner, as the built-in owners are named.

The operator file is the only source: ``<omh_home>/routing/executors.toml``. Built-in owners behave as before.
"""

from __future__ import annotations

import json
import unittest

from test_dag_tool import PARENT, call, child_started, choose, handoff, homes, node, slots_table
from omh.plugin_bundle.omh.named_owner_choice import note_turn_owners
from omh.plugin_bundle.omh import dag_run
from omh.plugin_bundle.omh.tools import dag_tool
from omh.plugin_bundle.omh.user_owner_ids import configured_owner_ids


def owned(node_id: str, owner: object, **kwargs) -> dict:
    return {**node(node_id, **kwargs), "owner": owner}


def write_executors(home, text: str) -> None:
    path = home.omh / "routing" / "executors.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


DEVIN = '[executors.devin]\npreset = "devin"\n'


def choose_configured(home, *owners: str) -> tuple[str, ...]:
    """The request names ``owners``; configured ids count as the production hook counts them: with this home's ids."""
    return note_turn_owners(PARENT, "/dag-ulw build it with " + " and ".join(owners), configured_owner_ids(home.omh))


class ConfiguredOwnerTests(unittest.TestCase):
    def test_define_accepts_a_configured_owner_and_export_lists_its_nodes(self) -> None:
        with homes() as home:
            slots_table(home)
            write_executors(home, "schema_version = 1\n" + DEVIN)
            choose_configured(home, "devin")
            defined = call(action="define", run="feat", nodes=[owned("api", "devin", scope=("api.py",))])
            self.assertEqual(defined.get("status"), "ok", defined)
            stored = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))
            self.assertEqual(stored["owners"], ["devin"])
            self.assertEqual(stored["registered_owners"], ["devin"])
            exported = call(action="export", run="feat", owner="devin")
            self.assertEqual(exported["status"], "ok", exported)
            self.assertIn("api", json.dumps(exported), exported)

    def test_an_unknown_owner_is_refused(self) -> None:
        with homes() as home:
            slots_table(home)
            write_executors(home, "schema_version = 1\n" + DEVIN)
            choose_configured(home, "devin")
            refused = call(action="define", run="feat", nodes=[owned("api", "nobody", scope=("api.py",))])
            self.assertEqual(refused.get("status"), "refused", refused)
            self.assertEqual(refused.get("reason"), "invalid_owner", refused)

    def test_an_owner_removed_from_the_file_after_define_is_refused_at_export(self) -> None:
        with homes() as home:
            slots_table(home)
            write_executors(home, "schema_version = 1\n" + DEVIN)
            choose_configured(home, "devin")
            call(action="define", run="feat", nodes=[owned("api", "devin", scope=("api.py",))])
            write_executors(home, "schema_version = 1\n")
            # The run's snapshot still names devin, but the operator no longer declares it: export must not run it.
            stored = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))
            self.assertEqual(stored["registered_owners"], ["devin"])
            self.assertEqual(configured_owner_ids(home.omh), frozenset())

    def test_codex_and_claude_code_behave_as_before(self) -> None:
        with homes() as home:
            slots_table(home)
            choose(home, "codex", "claude-code")
            defined = call(action="define", run="feat", nodes=[
                owned("api", "codex", scope=("api.py",)), owned("ui", "claude-code", scope=("ui.py",))])
            self.assertEqual(defined.get("status"), "ok", defined)
            stored = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))
            self.assertEqual(stored["owners"], ["claude-code", "codex"])
            self.assertNotIn("registered_owners", stored)

    def test_the_schema_admits_any_well_formed_id_and_never_lists_the_user_file(self) -> None:
        schema = dag_tool.OMH_DAG_SCHEMA["parameters"]["properties"]["nodes"]["items"]["properties"]["owner"]
        self.assertEqual(schema["pattern"], "^[a-z][a-z0-9-]{1,31}$")
        self.assertNotIn("enum", schema)
        self.assertNotIn("devin", json.dumps(dag_tool.OMH_DAG_SCHEMA))

    def test_repair_and_extend_keep_an_owner_admitted_at_define(self) -> None:
        with homes() as home:
            slots_table(home)
            write_executors(home, "schema_version = 1\n" + DEVIN)
            choose_configured(home, "devin")
            call(action="define", run="feat", nodes=[node("api", scope=("api.py",)),
                                                      node("verify", role="verify", depends_on=("api",))])
            child_started(home, "feat", "api")
            handoff(home, "feat", "api")
            call(action="settle", run="feat", node="api", outcome="accepted")
            child_started(home, "feat", "verify")
            call(action="settle", run="feat", node="verify", outcome="failed", reason="2 tests red")
            repaired = call(action="repair", run="feat", node="verify",
                            nodes=[owned("fix", "devin", scope=("a.py",), depends_on=("api",))])
            self.assertEqual(repaired.get("status"), "ok", repaired)
            extended = call(action="extend", run="feat", node="api",
                            nodes=[owned("more", "devin", scope=("b.py",), depends_on=("api",))])
            self.assertNotEqual(extended.get("reason"), "invalid_owner", extended)

    def test_status_does_not_offer_export_for_an_owner_removed_from_the_file(self) -> None:
        with homes() as home:
            slots_table(home)
            write_executors(home, "schema_version = 1\n" + DEVIN)
            choose_configured(home, "devin")
            call(action="define", run="feat", nodes=[owned("api", "devin", scope=("api.py",))])
            write_executors(home, "schema_version = 1\n")
            status = call(action="status", run="feat")
            self.assertNotIn("devin", json.dumps(status.get("exports", [])), status)
            exported = call(action="export", run="feat", owner="devin")
            self.assertEqual(exported.get("status"), "refused", exported)

    def test_a_boolean_schema_version_admits_no_owner(self) -> None:
        with homes() as home:
            write_executors(home, "schema_version = true\n" + DEVIN)
            self.assertEqual(configured_owner_ids(home.omh), frozenset())

    def test_hud_accepts_an_external_progress_profile(self) -> None:
        from omh.plugin_bundle.omh import runtime_reader
        from omh.plugin_bundle.omh.run_records import (
            EXECUTOR_PROGRESS_BINDING_SCHEMA_VERSION, EXECUTOR_PROGRESS_EVENT_SCHEMA_VERSION,
            EXECUTOR_PROGRESS_EVENT_TYPES, EXECUTOR_PROGRESS_REPORT_SCHEMA_VERSION)
        binding_id = "run:feat:external.my-agent"
        binding = {"schema_version": EXECUTOR_PROGRESS_BINDING_SCHEMA_VERSION, "binding_id": binding_id,
                   "target_type": "run", "target_id": "feat", "target": {"type": "run", "id": "feat"},
                   "executor_profile": "external.my-agent", "instance_id": "i1", "correlation_root": "c1",
                   "state": "active", "updated_at": "2026-11-22T00:00:00Z",
                   "claim_boundary": "progress only, not result"}
        event = {"schema_version": EXECUTOR_PROGRESS_EVENT_SCHEMA_VERSION, "binding_id": binding_id,
                 "instance_id": "i1", "event_type": EXECUTOR_PROGRESS_EVENT_TYPES[0],
                 "executor_profile": "external.my-agent", "summary": "started", "transition_fingerprint": "t1",
                 "claim_boundary": "progress only, not result"}
        report = {"schema_version": EXECUTOR_PROGRESS_REPORT_SCHEMA_VERSION, "binding_id": binding_id,
                  "instance_id": "i1", "executor_profile": "external.my-agent", "summary": "working",
                  "claim_boundary": "progress only, not result"}
        self.assertTrue(runtime_reader._valid_progress_binding(binding, "run"))
        self.assertTrue(runtime_reader._valid_progress_event(event, binding_id, "i1"))
        self.assertTrue(runtime_reader._valid_progress_report(report, binding_id, "i1"))


if __name__ == "__main__":
    unittest.main()

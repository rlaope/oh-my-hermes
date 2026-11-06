"""One dag-ulw run can prepare separate, explicitly chosen external owner batches."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shlex
import time
import unittest

from test_dag_tool import FEATURE, PARENT, call, choose, handoff, homes, node, put_record, slots_table
from omh.plugin_bundle.omh import dag_run
from omh.plugin_bundle.omh.tools import dag_tool
from omh.routing import owner_preference


def choose_lane(home, owner: str, *, state: dict | None = None, age: float = 0.0,
                selected_owner: str = "") -> dict:
    """Use the router's writer, not the chat hook, to record one per-owner choice."""
    state = owner_preference.record_in_message_explicit_naming(
        state, route_family=f"ulw-coding-delivery.{owner}", selected_owner=selected_owner or owner,
        naming_cue=f"named_executor:{selected_owner or owner}",
        occurred_at=(datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat())
    put_record(home, state)
    return state


class OwnerChoicesTests(unittest.TestCase):
    def test_main_and_per_owner_choices_are_sorted_unique_without_changing_main_choice(self) -> None:
        with homes() as home:
            state = choose(home, "codex")
            state = choose_lane(home, "codex", state=state)
            choose_lane(home, "claude-code", state=state)
            self.assertEqual(dag_tool.owner_choices(home.omh, now=time.time()), ("claude-code", "codex"))
            self.assertEqual(dag_tool.owner_choice(home.omh, now=time.time()), "codex")

    def test_per_owner_choice_obeys_age_future_and_matching_owner_boundaries(self) -> None:
        for age, selected_owner, expected in (
            (23 * 3600, "codex", ("codex",)), (25 * 3600, "codex", ()),
            (-60, "codex", ()), (0, "claude-code", ()),
        ):
            with self.subTest(age=age, selected_owner=selected_owner), homes() as home:
                choose_lane(home, "codex", age=age, selected_owner=selected_owner)
                self.assertEqual(dag_tool.owner_choices(home.omh, now=time.time()), expected)
                self.assertEqual(dag_tool.owner_choice(home.omh, now=time.time()), "")

    def test_missing_or_invalid_record_grants_no_owner(self) -> None:
        with homes() as home:
            self.assertEqual(dag_tool.owner_choices(home.omh, now=time.time()), ())
            state = choose_lane(home, "codex")
            state["privacy"]["mode"] = "full"
            put_record(home, state)
            self.assertEqual(dag_tool.owner_choices(home.omh, now=time.time()), ())


def owned(node_id: str, owner: object, **kwargs) -> dict:
    return {**node(node_id, **kwargs), "owner": owner}


class NodeOwnerTests(unittest.TestCase):
    def test_define_stores_only_explicit_owner_and_owner_changes_digest(self) -> None:
        with homes() as home:
            slots_table(home)
            plain = call(action="define", run="plain", nodes=FEATURE)
            stored = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "plain"))
            # Captured from the origin/main implementation before changing NODE_FIELDS.
            self.assertEqual(stored["digest"], "3ae548ab36450591")
            self.assertTrue(all("owner" not in item for item in stored["nodes"]))
            self.assertEqual(plain["status"], "ok")
            result = call(action="define", run="named", nodes=[owned("api", "codex", scope=("api.py",))])
            self.assertEqual(result["status"], "ok", result)
            named = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "named"))
            self.assertEqual(named["nodes"][0]["owner"], "codex")
            other = dag_run.new_record(PARENT, "other", "", "", [owned("api", "claude-code", scope=("api.py",))], 0)
            self.assertNotEqual(named["digest"], other["digest"])

    def test_invalid_or_non_coding_owner_is_refused_with_node_id(self) -> None:
        cases = [owned("api", value, scope=("api.py",)) for value in ("hermes", "", None, [], {})]
        cases += [owned("check", "codex", scope=("check.py",), role=role)
                  for role in ("verify", "review", "baseline")]
        cases += [owned("read", "claude-code"),
                  owned("check", "codex", label="Independent verification", scope=("check.py",))]
        for raw in cases:
            with self.subTest(raw=raw), homes():
                result = call(action="define", run="feat", nodes=[raw])
                self.assertEqual((result["status"], result["reason"]), ("refused", "invalid_owner"), result)
                self.assertIn(raw["id"], result["say"])

    def test_repair_and_extend_validate_and_keep_owner(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("api", scope=("api.py",))])
            call(action="settle", run="feat", node="api", outcome="failed")
            bad = call(action="repair", run="feat", node="api",
                       nodes=[owned("bad", "codex", role="verify")])
            self.assertEqual(bad["reason"], "invalid_owner")
            repaired = call(action="repair", run="feat", node="api",
                            nodes=[owned("fix", "claude-code", scope=("api.py",))])
            self.assertEqual(repaired["status"], "ok", repaired)
            handoff(home, "feat", "fix")
            call(action="settle", run="feat", node="fix", outcome="accepted")
            bad = call(action="extend", run="feat", nodes=[owned("bad", "codex", role="review")])
            self.assertEqual(bad["reason"], "invalid_owner")
            extended = call(action="extend", run="feat", nodes=[owned("extra", "codex", scope=("extra.py",))])
            self.assertEqual(extended["status"], "ok", extended)
            stored = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))
            self.assertEqual({item["id"]: item.get("owner") for item in stored["nodes"]},
                             {"api": None, "fix": "claude-code", "extra": "codex"})

    def test_schema_exposes_closed_optional_node_owner(self) -> None:
        schema = dag_tool.OMH_DAG_SCHEMA["parameters"]["properties"]["nodes"]["items"]
        self.assertEqual(schema["properties"]["owner"]["enum"], list(dag_tool.EXTERNAL_OWNERS))
        self.assertNotIn("owner", schema["required"])


class OwnerLaneRoutingTests(unittest.TestCase):
    def test_both_owner_exports_and_status_leave_checks_native_and_keep_both_batches_files(self) -> None:
        nodes = [owned("api", "codex", scope=("api.py",)),
                 owned("ui", "claude-code", scope=("ui.py",)), node("docs", scope=("docs.md",)),
                 node("review", role="review", scope=("review.md",)),
                 node("verify", role="verify", scope=("verify.log",)), node("baseline", role="baseline")]
        with homes() as home:
            slots_table(home)
            choose_lane(home, "claude-code", state=choose(home, "codex"))
            defined = call(action="define", run="feat", nodes=nodes)
            expected = [
                {"owner": "claude-code", "nodes": ["ui"],
                 "next": {"tool": "omh_dag", "action": "export", "owner": "claude-code"}},
                {"owner": "codex", "nodes": ["api", "docs"],
                 "next": {"tool": "omh_dag", "action": "export", "owner": "codex"}},
            ]
            self.assertEqual(defined.get("exports"), expected, defined)
            self.assertNotIn("export", defined)
            self.assertEqual({i for row in defined["calls"] for i in row["nodes"]}, {"baseline", "review", "verify"})
            status = call(action="status", run="feat")
            self.assertEqual(status["exports"], expected)
            self.assertNotIn("export", status)
            for result in (defined, status):
                for owner in dag_tool.EXTERNAL_OWNERS:
                    self.assertEqual(result["say"].count(f"omh_dag action=export owner={owner}"), 1)
            first = call(action="export", run="feat", owner="codex")
            self.assertEqual(first["status"], "ok", first)
            saved = {key: Path(first["fanout"][key]).read_bytes() for key in ("units_file", "goal_file")}
            second = call(action="export", run="feat", owner="claude-code")
            self.assertEqual(second["status"], "ok", second)
            self.assertNotEqual(first["fanout"]["fanout_id"], second["fanout"]["fanout_id"])
            for result, expected_ids in ((first, ["api", "docs"]), (second, ["ui"])):
                units = json.loads(Path(result["fanout"]["units_file"]).read_text(encoding="utf-8"))["units"]
                self.assertEqual([unit["unit_id"] for unit in units], expected_ids)
                self.assertEqual({unit["owner"] for unit in units}, {result["fanout"]["owner"]})
            for key, content in saved.items():
                self.assertEqual(Path(first["fanout"][key]).read_bytes(), content)
            self.assertEqual(call(action="ready", run="feat")["exports"], [])
            self.assertEqual(call(action="status", run="feat")["exports"], [])

    def test_a_one_node_batch_returns_a_coding_run_command_and_a_larger_one_the_fanout_pair(self) -> None:
        # `fanout prepare` freezes no contract for a single unit (it answers redirect_to_run), so the
        # usual per-owner batch of one node gets the one-unit `omh coding run` with the same goal file.
        nodes = [owned("api", "codex", scope=("src/api.py", "src/api test.py")),
                 owned("ui", "claude-code", scope=("ui.py",)), owned("css", "claude-code", scope=("css.py",))]
        with homes() as home:
            slots_table(home)
            choose_lane(home, "claude-code", state=choose_lane(home, "codex"))
            call(action="define", run="feat", nodes=nodes)
            single = call(action="export", run="feat", owner="codex")
            pair = call(action="export", run="feat", owner="claude-code")
        goal_file = single["fanout"]["goal_file"]
        self.assertEqual(single["fanout"]["commands"], [
            # write_scope is stored sorted, so the scopes come out in that order.
            f"omh coding run --owner codex --unit-id api --file-scope 'src/api test.py' --file-scope src/api.py "
            f"--goal-file {shlex.quote(goal_file)} --repo-root ."])  # quoted: a Windows temp path has backslashes
        self.assertEqual([command.split()[:4] for command in pair["fanout"]["commands"]],
                         [["omh", "coding", "fanout", "prepare"], ["omh", "coding", "fanout", "dispatch"]])
        self.assertIn(pair["fanout"]["fanout_id"], pair["fanout"]["commands"][1])

    def test_cross_owner_dependency_waits_but_same_owner_dependencies_share_batch(self) -> None:
        nodes = [owned("api", "codex", scope=("api.py",)),
                 owned("lib", "codex", scope=("lib.py",), depends_on=("api",)),
                 owned("ui", "claude-code", scope=("ui.py",), depends_on=("api",)),
                 owned("css", "claude-code", scope=("css.py",), depends_on=("ui",))]
        with homes() as home:
            slots_table(home)
            choose_lane(home, "claude-code", state=choose_lane(home, "codex"))
            result = call(action="define", run="feat", nodes=nodes)
            self.assertEqual(result.get("exports", [])[0]["nodes"], ["api"], result)
            self.assertEqual(call(action="export", run="feat", owner="claude-code")["reason"], "nothing_to_export")
            first = call(action="export", run="feat", owner="codex")
            units = json.loads(Path(first["fanout"]["units_file"]).read_text(encoding="utf-8"))["units"]
            self.assertEqual([(unit["unit_id"], unit["depends_on"]) for unit in units], [("api", []), ("lib", ["api"])])
            handoff(home, "feat", "api")
            settled = call(action="settle", run="feat", node="api", outcome="accepted")
            self.assertEqual(settled["exports"][0]["owner"], "claude-code")
            self.assertEqual(settled["exports"][0]["nodes"], ["ui"])
            second = call(action="export", run="feat", owner="claude-code")
            units = json.loads(Path(second["fanout"]["units_file"]).read_text(encoding="utf-8"))["units"]
            self.assertEqual([(unit["unit_id"], unit["depends_on"]) for unit in units], [("ui", []), ("css", ["ui"])])

    def test_unchosen_or_expired_named_owner_stays_native_even_with_another_main_owner(self) -> None:
        for expired in (False, True):
            with self.subTest(expired=expired), homes() as home:
                slots_table(home)
                state = choose(home, "claude-code")
                if expired:
                    choose_lane(home, "codex", state=state, age=25 * 3600)
                result = call(action="define", run="feat", nodes=[owned("api", "codex", scope=("api.py",))])
                self.assertEqual([row["nodes"] for row in result["calls"]], [["api"]], result)
                self.assertEqual(result.get("exports"), [])
                self.assertNotIn("export", result)
                warning = "Node api names codex, which the person has not chosen in the last day; it runs on delegate_task."
                self.assertEqual(result["say"].count(warning), 1)
                self.assertEqual(call(action="export", run="feat", owner="codex")["reason"], "owner_not_chosen")
                self.assertEqual(call(action="export", run="feat", owner="claude-code")["reason"], "nothing_to_export")

    def test_per_owner_choice_does_not_choose_an_unnamed_nodes_owner(self) -> None:
        with homes() as home:
            slots_table(home)
            choose_lane(home, "codex")
            result = call(action="define", run="feat", nodes=[node("api", scope=("api.py",))])
            self.assertEqual([row["nodes"] for row in result["calls"]], [["api"]])
            self.assertEqual(result.get("exports"), [])
            self.assertEqual(call(action="export", run="feat", owner="codex")["reason"], "nothing_to_export")

    def test_every_result_has_exports_and_empty_batches_have_no_legacy_export(self) -> None:
        with homes() as home:
            slots_table(home)
            results = [call(action="define", run="feat", nodes=[node("read")]),
                       call(action="ready", run="feat"), call(action="status", run="feat"),
                       call(action="export", run="feat", owner="codex"), call(action="cancel", run="feat")]
            for result in results:
                with self.subTest(action=result["action"]):
                    self.assertEqual(result.get("exports"), [])
                    self.assertNotIn("export", result)

    def test_legacy_single_main_choice_retains_byte_identical_export_payload(self) -> None:
        expected = {"owner": "codex", "nodes": ["api", "ui"],
                    "next": {"tool": "omh_dag", "action": "export", "owner": "codex"}}
        with homes() as home:
            slots_table(home)
            choose(home, "codex")
            result = call(action="define", run="feat", nodes=[node("api", scope=("api.py",)),
                                                               node("ui", scope=("ui.py",))])
            self.assertEqual(json.dumps(result["export"], sort_keys=True).encode(),
                             json.dumps(expected, sort_keys=True).encode())
            self.assertEqual(result.get("exports"), [expected])
            status = call(action="status", run="feat")
            self.assertEqual(status["exports"], [expected])
            self.assertEqual(status["export"], result["export"])


if __name__ == "__main__":
    unittest.main()

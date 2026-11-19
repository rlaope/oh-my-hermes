"""Carry-forward on a dag-ulw re-run: nodes an earlier run of the same goal and base accepted are not run again.

Off unless `define` passes ``carry_forward`` (the base revision). A carried
node is recorded ``carried``, never handed out, and its dependents read the
earlier run's handoff. A verify node is never carried, so it runs over the
carried work, and the goal verdict still waits on it. Every view lists what
was carried and from which run.
"""

from __future__ import annotations

import json
import os
import unittest

from _local_package import load_local_package

load_local_package()

from _delegation_state import PARENT, homes  # noqa: E402
from omh.plugin_bundle.omh import dag_run  # noqa: E402
from test_dag_tool import FEATURE, call, handoff, node, slots_table  # noqa: E402

GOAL = "Ship the export feature"
BASE = "a5649293b"


def finish(home, run: str, nodes: list, *, base: str | None = BASE, goal: str = GOAL,
           outcomes: dict | None = None) -> dict:
    """Define ``run`` (with ``carry_forward`` when ``base`` is given) and settle every node in order."""
    arguments = {"carry_forward": base} if base is not None else {}
    result = call(action="define", run=run, goal=goal, nodes=nodes, **arguments)
    for item in nodes:
        outcome = (outcomes or {}).get(item["id"], "accepted")
        handoff(home, run, item["id"], f"{run}/{item['id']} done")
        result = call(action="settle", run=run, node=item["id"], outcome=outcome)
    return result


def rows(result: dict) -> dict:
    return {row["id"]: row for row in result["nodes"]}


def not_carried(result: dict) -> dict:
    return {item["id"]: item["reason"] for item in result["carry_forward"]["not_carried"]}


def offered(result: dict) -> list:
    return sorted(node_id for call_row in result.get("calls", []) for node_id in call_row["nodes"])


class CarryForwardTests(unittest.TestCase):
    def test_exact_match_carries_every_non_verify_node_and_hands_out_only_verify(self) -> None:
        with homes() as home:
            slots_table(home)
            first = finish(home, "feat1", FEATURE)
            self.assertEqual(first["state"], "done", first)
            again = call(action="define", run="feat2", goal=GOAL, nodes=FEATURE, carry_forward=BASE)
            status = call(action="status", run="feat2")
        self.assertEqual(again["status"], "ok", again)
        self.assertEqual([item["id"] for item in again["carry_forward"]["carried"]], ["api", "ui", "docs"])
        self.assertEqual({item["from_run"] for item in again["carry_forward"]["carried"]}, {"feat1"})
        self.assertEqual(not_carried(again), {"verify": "verify_runs_again"})
        self.assertEqual(offered(again), ["verify"])
        self.assertIn("Carried 3 of 4 nodes from run feat1", again["say"])
        self.assertIn("verify node still runs", again["say"])
        for view in (again, status):
            self.assertEqual([row["id"] for row in view["carried"]], ["api", "ui", "docs"])
            self.assertTrue(all(row["from_run"] == "feat1" and "base " + BASE in row["reason"]
                                for row in view["carried"]))
            self.assertEqual({key: rows(view)[key]["state"] for key in ("api", "ui", "docs")},
                             dict.fromkeys(("api", "ui", "docs"), "carried"))
            self.assertIn("carried 3 of 4 nodes from feat1", view["status_line"])
            self.assertEqual(view["counts"]["carried"], 3)

    def test_dependents_read_the_prior_handoff_and_verify_is_told_what_was_carried(self) -> None:
        with homes() as home:
            slots_table(home)
            finish(home, "feat1", FEATURE)
            again = call(action="define", run="feat2", goal=GOAL, nodes=FEATURE, carry_forward=BASE)
            earlier = {key: str(dag_run.handoff_path(home.omh, PARENT, "feat1", key)) for key in ("api", "ui", "docs")}
            own = str(dag_run.handoff_path(home.omh, PARENT, "feat2", "verify"))
        task = again["calls"][0]["tasks"][0]["context"]
        read_first = next(line for line in task.splitlines() if line.startswith("Read first:"))
        for path in earlier.values():
            self.assertIn(path, read_first)
        self.assertNotIn("/feat2/api.md", read_first)
        self.assertIn(own, task)  # the verify node writes its own handoff in the new run
        self.assertIn("Carried from run feat1 without running again: api, ui, docs.", task)
        self.assertEqual({item["id"]: os.path.realpath(item["handoff"]) for item in again["carry_forward"]["carried"]},
                         {key: os.path.realpath(path) for key, path in earlier.items()})

    def test_changed_prompt_is_not_carried_and_its_dependents_run_again(self) -> None:
        changed = [dict(item) for item in FEATURE]
        changed[0]["prompt"] = changed[0]["prompt"] + "\nAlso export JSON."
        with homes() as home:
            slots_table(home)
            finish(home, "feat1", FEATURE)
            again = call(action="define", run="feat2", goal=GOAL, nodes=changed, carry_forward=BASE)
        self.assertEqual([item["id"] for item in again["carry_forward"]["carried"]], ["ui"])
        self.assertEqual(not_carried(again), {"api": "prompt_changed", "docs": "parent_runs_again",
                                              "verify": "verify_runs_again"})
        self.assertEqual(offered(again), ["api"])

    def test_changed_write_scope_is_not_carried(self) -> None:
        changed = [dict(item) for item in FEATURE]
        changed[1]["write_scope"] = ["src/ui.py", "src/ui_theme.py"]
        with homes() as home:
            slots_table(home)
            finish(home, "feat1", FEATURE)
            again = call(action="define", run="feat2", goal=GOAL, nodes=changed, carry_forward=BASE)
        self.assertEqual(not_carried(again)["ui"], "write_scope_changed")
        self.assertEqual([item["id"] for item in again["carry_forward"]["carried"]], ["api", "docs"])
        self.assertEqual(offered(again), ["ui"])

    def test_changed_base_carries_nothing(self) -> None:
        with homes() as home:
            slots_table(home)
            finish(home, "feat1", FEATURE)
            again = call(action="define", run="feat2", goal=GOAL, nodes=FEATURE, carry_forward="b7c8d9e0f")
            record = json.loads(dag_run.record_path(home.omh, PARENT, "feat2").read_text(encoding="utf-8"))
        self.assertEqual(again["carry_forward"]["carried"], [])
        self.assertEqual(set(not_carried(again).values()), {"no_prior_run"})
        self.assertIn("carried nothing", again["say"])
        self.assertNotIn("carried", again)
        self.assertEqual(offered(again), ["api", "ui"])
        self.assertEqual(record["carry_base"], "b7c8d9e0f")  # a later run at this base can carry from it

    def test_a_prior_run_defined_without_a_base_is_never_carried_from(self) -> None:
        with homes() as home:
            slots_table(home)
            finish(home, "feat1", FEATURE, base=None)
            again = call(action="define", run="feat2", goal=GOAL, nodes=FEATURE, carry_forward=BASE)
        self.assertEqual(again["carry_forward"]["carried"], [])
        self.assertEqual(offered(again), ["api", "ui"])

    def test_another_goal_carries_nothing(self) -> None:
        with homes() as home:
            slots_table(home)
            finish(home, "feat1", FEATURE)
            again = call(action="define", run="feat2", goal="Ship the import feature", nodes=FEATURE,
                         carry_forward=BASE)
        self.assertEqual(again["carry_forward"]["carried"], [])

    def test_a_prior_failed_or_blocked_node_is_not_carried(self) -> None:
        for outcome in ("failed", "blocked"):
            with self.subTest(outcome=outcome), homes() as home:
                slots_table(home)
                finish(home, "feat1", FEATURE[:2] + [node("verify", depends_on=("api", "ui"), role="verify")],
                       outcomes={"ui": outcome})
                again = call(action="define", run="feat2", goal=GOAL,
                             nodes=FEATURE[:2] + [node("verify", depends_on=("api", "ui"), role="verify")],
                             carry_forward=BASE)
            self.assertEqual(not_carried(again)["ui"], f"prior_{outcome}")
            self.assertEqual([item["id"] for item in again["carry_forward"]["carried"]], ["api"])
            self.assertEqual(offered(again), ["ui"])

    def test_a_prior_handoff_that_is_gone_is_not_carried(self) -> None:
        with homes() as home:
            slots_table(home)
            finish(home, "feat1", FEATURE)
            dag_run.handoff_path(home.omh, PARENT, "feat1", "ui").unlink()
            again = call(action="define", run="feat2", goal=GOAL, nodes=FEATURE, carry_forward=BASE)
        self.assertEqual(not_carried(again)["ui"], "prior_handoff_missing")
        self.assertEqual([item["id"] for item in again["carry_forward"]["carried"]], ["api", "docs"])

    def test_a_verify_node_is_never_carried_even_when_it_passed_unchanged(self) -> None:
        with homes() as home:
            slots_table(home)
            finish(home, "feat1", FEATURE)
            again = call(action="define", run="feat2", goal=GOAL, nodes=FEATURE, carry_forward=BASE)
        self.assertEqual(rows(again)["verify"]["state"], "handed_out")
        self.assertEqual(not_carried(again)["verify"], "verify_runs_again")

    def test_flag_off_runs_every_node_and_keeps_the_record_as_before(self) -> None:
        with homes() as home:
            slots_table(home)
            finish(home, "feat1", FEATURE)
            again = call(action="define", run="feat2", goal=GOAL, nodes=FEATURE)
            record = json.loads(dag_run.record_path(home.omh, PARENT, "feat2").read_text(encoding="utf-8"))
        self.assertEqual(offered(again), ["api", "ui"])
        for key in ("carry_forward", "carried"):
            self.assertNotIn(key, again)
        self.assertNotIn("carried", again["status_line"])
        self.assertNotIn("carry_base", record)
        self.assertNotIn("carried_from", record)

    def test_a_bad_base_is_refused_and_nothing_is_written(self) -> None:
        for bad in ("", "has space", "x" * 65, 7):
            with self.subTest(bad=bad), homes() as home:
                slots_table(home)
                refused = call(action="define", run="feat2", goal=GOAL, nodes=FEATURE, carry_forward=bad)
                self.assertEqual(refused["reason"], "invalid_carry_forward")
                self.assertFalse(dag_run.record_path(home.omh, PARENT, "feat2").exists())

    def test_carried_nodes_count_for_the_verdict_only_once_the_verify_node_passes(self) -> None:
        with homes() as home:
            slots_table(home)
            finish(home, "feat1", FEATURE)
            again = call(action="define", run="feat2", goal=GOAL, nodes=FEATURE, carry_forward=BASE)
            record = json.loads(dag_run.record_path(home.omh, PARENT, "feat2").read_text(encoding="utf-8"))
            derived = dag_run.derive(record, [], 0.0)
            open_verdict = dag_run.goal_verdict(record, derived)
            handoff(home, "feat2", "verify", "checked")
            failed = call(action="settle", run="feat2", node="verify", outcome="failed", reason="docs wrong")
        self.assertEqual(again["state"], "running")
        self.assertNotIn("verdict", again)
        self.assertEqual(open_verdict[0], "unverified")
        self.assertIn("verification_open:verify", open_verdict[1])
        self.assertEqual(failed["state"], "needs_repair")
        with homes() as home:
            slots_table(home)
            finish(home, "feat1", FEATURE)
            call(action="define", run="feat2", goal=GOAL, nodes=FEATURE, carry_forward=BASE)
            handoff(home, "feat2", "verify", "checked")
            passed = call(action="settle", run="feat2", node="verify", outcome="accepted")
        self.assertEqual((passed["state"], passed["verdict"]), ("done", "verified"))
        self.assertIn("carried 3 of 4 nodes from feat1", passed["status_line"])

    def test_a_carried_node_cannot_be_settled(self) -> None:
        with homes() as home:
            slots_table(home)
            finish(home, "feat1", FEATURE)
            call(action="define", run="feat2", goal=GOAL, nodes=FEATURE, carry_forward=BASE)
            refused = call(action="settle", run="feat2", node="api", outcome="accepted")
        self.assertEqual(refused["reason"], "node_not_out")

    def test_schema_adds_one_optional_string(self) -> None:
        from omh.plugin_bundle.omh.tools import dag_tool
        parameters = dag_tool.OMH_DAG_SCHEMA["parameters"]
        self.assertEqual(parameters["properties"]["carry_forward"]["type"], "string")
        self.assertNotIn("carry_forward", parameters["required"])


if __name__ == "__main__":
    unittest.main()

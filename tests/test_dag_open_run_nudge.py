"""The turn-start line for a dag-ulw run nothing will wake (`dag_open_run_nudge`).

A parent re-enters a run only when a child completes. Each test builds the
run the way the parent does (`omh_dag` through `test_dag_tool.call`, or a
record `omh_dag` would have written) and reads what the next turn's
`pre_llm_call` adds: one line naming the run and the call, once per
situation, and nothing for a child, a finished run, a conversation with no
run, or a record it cannot read.
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from _delegation_state import PARENT, homes, stop  # noqa: E402
from omh.plugin_bundle.omh import dag_open_run_nudge, dag_run  # noqa: E402
from omh.plugin_bundle.omh.dag_open_run_nudge import open_run_line, reset_open_run_nudge  # noqa: E402
from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call  # noqa: E402
from omh.plugin_bundle.omh.hooks.nudge_budget import note_delegated_session, reset_nudge_budget  # noqa: E402
from omh.plugin_bundle.omh.tools import dag_tool  # noqa: E402
from test_dag_tool import call, child_started, handoff, node, slots_table  # noqa: E402

HOUR = 3600.0


def at(moment: float, **arguments: object) -> dict:
    with patch.object(dag_tool.time, "time", return_value=moment):
        return call(**arguments)


def line(home, moment: float, *, session: str = PARENT, delegated: bool = False) -> str:
    return open_run_line(session_id=session, omh_home=str(home.omh), hermes_home=str(home.hermes),
                         delegated=delegated, now=moment)


def stored(home, nodes: list[dict], moment: float, run: str = "feat") -> dict:
    """A run as `omh_dag define` keeps it before anything is handed out: every root node ready."""
    record = dag_run.new_record(PARENT, run, "Feature", "", nodes, moment)
    path = dag_run.record_path(home.omh, PARENT, run)
    path.parent.mkdir(parents=True, exist_ok=True)
    dag_run.write_run(path, record)
    return record


def parked(home, moment: float, *, wake_in: float = 60.0, nodes: list[dict] | None = None) -> None:
    slots_table(home)
    at(moment, action="define", run="feat", nodes=nodes or [node("a")])
    at(moment, action="settle", run="feat", node="a", outcome="parked", handle="proc:ci", wake_at=moment + wake_in)


class NudgeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        reset_open_run_nudge()
        reset_nudge_budget()
        self.addCleanup(reset_open_run_nudge)
        self.addCleanup(reset_nudge_budget)


class NamedSituationTests(NudgeTestCase):
    """Mutation: drop a reason from `wake_needed`, or name the wrong call for it."""

    def test_a_parked_node_past_its_wake_with_nothing_live_names_ready(self) -> None:
        moment = time.time()
        with homes() as home:
            parked(home, moment)
            text = line(home, moment + 61)
        self.assertEqual(text, (
            "[OMH dag] Run feat: parked node a passed wake_at and no child is running, so nothing will wake the run. "
            "Call omh_dag action=ready run=feat; the parked node gets its fresh attempt."))

    def test_ready_nodes_nobody_dispatched_with_nothing_out_names_ready(self) -> None:
        moment = time.time()
        with homes() as home:
            stored(home, [node("api"), node("ui"), node("verify", depends_on=("api", "ui"))], moment)
            text = line(home, moment + 5)
        self.assertEqual(text, (
            "[OMH dag] Run feat: nodes api, ui ready and nothing is out, so nothing will wake the run. Call omh_dag "
            "action=ready run=feat and dispatch the calls it returns."))

    def test_a_node_past_the_stuck_mark_names_status(self) -> None:
        moment = time.time()
        with homes() as home:
            slots_table(home)
            at(moment, action="define", run="feat", nodes=[node("api")])
            child_started(home, "feat", "api", now=moment + 5)
            below = line(home, moment + HOUR - 1)
            past = line(home, moment + 2 * HOUR)
        self.assertEqual(below, "")
        self.assertEqual(past, (
            "[OMH dag] Run feat: node api open past the 1h stuck mark. Call omh_dag action=status run=feat for what "
            "to check."))

    def test_more_than_three_nodes_are_counted_not_listed(self) -> None:
        moment = time.time()
        with homes() as home:
            stored(home, [node(name) for name in ("a", "b", "c", "d", "e")], moment)
            text = line(home, moment)
        self.assertIn("nodes a, b, c +2 ready", text)

    def test_it_reaches_the_turn_through_pre_llm_call(self) -> None:
        moment = time.time()
        with homes() as home:
            stored(home, [node("api")], moment)
            payload = pre_llm_call(**home.hooks(), session_id=PARENT, turn_id="t2", user_message="continue",
                                   is_first_turn=False, platform="cli")
        self.assertIn("[OMH dag] Run feat: node api ready", str((payload or {}).get("context", "")))


class SilentTests(NudgeTestCase):
    """Mutation: drop the live-child, out, finished, child-session or claim check; let a read fault raise."""

    def test_a_parked_node_whose_wake_is_still_ahead_gets_nothing(self) -> None:
        moment = time.time()
        with homes() as home:
            parked(home, moment)
            self.assertEqual(line(home, moment + 30), "")

    def test_a_node_out_with_a_live_child_gets_nothing(self) -> None:
        moment = time.time()
        with homes() as home:
            # `a` is parked past its wake, but `b`'s child runs, and its completion re-opens the run.
            parked(home, moment, nodes=[node("a"), node("b")])
            child_started(home, "feat", "b", now=moment + 1)
            self.assertEqual(line(home, moment + 61), "")

    def test_ready_nodes_while_a_node_is_out_get_nothing(self) -> None:
        moment = time.time()
        with homes() as home:
            record = stored(home, [node("a"), node("b")], moment)
            record["nodes"][0]["attempts"] = [{"n": 1, "handed_out_at": moment, "opened_at": moment}]
            dag_run.write_run(dag_run.record_path(home.omh, PARENT, "feat"), record)
            self.assertEqual(line(home, moment + 5), "")

    def test_a_finished_run_gets_nothing(self) -> None:
        moment = time.time()
        with self.subTest(state="done"), homes() as home:
            slots_table(home)
            at(moment, action="define", run="feat", nodes=[node("a")])
            child_started(home, "feat", "a", now=moment + 1)
            stop(home, "child-a", now=moment + 2)
            handoff(home, "feat", "a")
            self.assertEqual(at(moment + 3, action="settle", run="feat", node="a", outcome="accepted")["state"], "done")
            self.assertEqual(line(home, moment + 2 * HOUR), "")
        with self.subTest(state="cancelled"), homes() as home:
            parked(home, moment)
            at(moment, action="cancel", run="feat")
            self.assertEqual(line(home, moment + 61), "")
        with self.subTest(state="stopped"), homes() as home:
            record = stored(home, [node("a"), node("b", depends_on=("a",))], moment)
            failed = [{"n": 1, "handed_out_at": moment, "outcome": "failed", "settled_at": moment}]
            record["nodes"][0]["attempts"] = failed
            for repair in ("r1", "r2"):
                record["nodes"].append({**node(repair), "repairs": "a", "attempts": list(failed)})
            record["repairs"] = {"a": [["r1"], ["r2"]]}
            dag_run.write_run(dag_run.record_path(home.omh, PARENT, "feat"), record)
            derived = dag_run.derive(record, [], moment)
            self.assertEqual(dag_run.run_state(record, derived), "stopped")
            self.assertEqual(line(home, moment + 2 * HOUR), "")

    def test_a_finished_run_is_skipped_even_when_it_would_match(self) -> None:
        moment = time.time()
        with homes() as home:
            stored(home, [node("a")], moment)
            with patch.object(dag_run, "run_state", return_value="stopped"):
                self.assertEqual(line(home, moment), "")

    def test_a_delegated_child_gets_nothing(self) -> None:
        moment = time.time()
        with homes() as home:
            stored(home, [node("api")], moment)
            self.assertEqual(line(home, moment, delegated=True), "")
            # Through the hook: the child Hermes told this process about.
            note_delegated_session(PARENT, omh_home=str(home.omh))
            payload = pre_llm_call(**home.hooks(), session_id=PARENT, turn_id="t2", user_message="continue",
                                   is_first_turn=False, platform="cli")
        self.assertNotIn("[OMH dag]", str((payload or {}).get("context", "")))

    def test_a_child_session_of_its_own_finds_no_run(self) -> None:
        moment = time.time()
        with homes() as home:
            stored(home, [node("api")], moment)
            self.assertEqual(line(home, moment, session="child-api"), "")

    def test_a_conversation_without_a_run_gets_nothing(self) -> None:
        moment = time.time()
        with homes() as home:
            self.assertEqual(line(home, moment), "")
            stored(home, [node("api")], moment)
            self.assertEqual(line(home, moment, session="20261020_150000_other"), "")

    def test_an_unreadable_record_says_nothing_and_never_raises(self) -> None:
        moment = time.time()
        with homes() as home:
            path = dag_run.record_path(home.omh, PARENT, "feat")
            path.parent.mkdir(parents=True)
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(line(home, moment), "")
            stored(home, [node("api")], moment, run="other")
            for target, error in ((dag_run, "derive"), (dag_open_run_nudge, "reading_session_id"),
                                  (dag_run, "session_runs")):
                for raised in (OSError("disk"), KeyError("nodes"), ValueError("bad")):
                    with self.subTest(target=error, raised=type(raised).__name__), patch.object(
                            target, error, side_effect=raised):
                        self.assertEqual(line(home, moment), "")

    def test_the_same_situation_on_the_next_turn_gets_nothing(self) -> None:
        moment = time.time()
        with homes() as home:
            stored(home, [node("api")], moment)
            self.assertTrue(line(home, moment))
            self.assertEqual(line(home, moment + 60), "")

    def test_a_new_wake_at_is_a_new_situation(self) -> None:
        moment = time.time()
        with homes() as home:
            parked(home, moment)
            self.assertTrue(line(home, moment + 61))
            self.assertEqual(line(home, moment + 62), "")
            # `ready` hands the node its fresh attempt, the child parks it again with a new deadline.
            at(moment + 62, action="ready", run="feat")
            at(moment + 63, action="settle", run="feat", node="a", outcome="parked", handle="proc:ci",
               wake_at=moment + 200)
            self.assertEqual(line(home, moment + 150), "")
            self.assertIn("parked node a passed wake_at", line(home, moment + 201))

    def test_a_stuck_mark_of_zero_turns_the_stuck_line_off(self) -> None:
        moment = time.time()
        with homes() as home:
            (home.hermes / "config.yaml").write_text(
                "plugins:\n  entries:\n    omh:\n      settings:\n        dag_stuck_after_s: 0\n", encoding="utf-8")
            slots_table(home)
            at(moment, action="define", run="feat", nodes=[node("api")])
            child_started(home, "feat", "api", now=moment + 5)
            self.assertEqual(line(home, moment + 9 * HOUR), "")


if __name__ == "__main__":
    unittest.main()

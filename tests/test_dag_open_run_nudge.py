"""The turn-start line for a dag-ulw run with no node running (`dag_open_run_nudge`).

A parent re-enters a run only when a child completes. Each test builds the
run the way the parent does (`omh_dag` through `test_dag_tool.call`, or a
record `omh_dag` would have written) and reads what the next turn's
`pre_llm_call` adds: one line naming the run and the call, once per
situation, and nothing for a child, a finished run, a conversation with no
run, or a record it cannot read.
"""

from __future__ import annotations

import os
import sqlite3
import time
import unittest
from unittest.mock import patch

from _local_package import load_local_package
from _module_patch import patch_modules

load_local_package()

from _delegation_state import PARENT, homes, start, stop  # noqa: E402
from omh.plugin_bundle.omh import dag_open_run_nudge, dag_run  # noqa: E402
from omh.plugin_bundle.omh.dag_open_run_nudge import open_run_line, reset_open_run_nudge  # noqa: E402
from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call  # noqa: E402
from omh.plugin_bundle.omh.hooks.nudge_budget import note_delegated_session, reset_nudge_budget  # noqa: E402
from omh.plugin_bundle.omh.tools import dag_tool  # noqa: E402
from test_dag_tool import call, child_started, handoff, hermes_process, node, slots_table  # noqa: E402

HOUR = 3600.0


def at(moment: float, **arguments: object) -> dict:
    with patch.object(dag_tool.time, "time", return_value=moment):
        return call(**arguments)


def line(home, moment: float, *, session: str = PARENT, delegated: bool = False) -> str:
    return open_run_line(session_id=session, omh_home=str(home.omh), hermes_home=str(home.hermes),
                         delegated=delegated, now=moment)


def stored(home, nodes: list[dict], moment: float, run: str = "feat", *, out: dict | None = None) -> dict:
    """A run as `omh_dag define` keeps it before anything is handed out: every root node ready.

    ``out`` maps a node id to its open attempt's extra fields: that node is handed out at ``moment``.
    """
    record = dag_run.new_record(PARENT, run, "Feature", "", nodes, moment)
    for item in record["nodes"]:
        if item["id"] in (out or {}):
            item["attempts"] = [{"n": 1, "handed_out_at": moment, "opened_at": moment, **out[item["id"]]}]
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

    def test_a_parked_node_past_its_wake_with_nothing_running_names_ready(self) -> None:
        moment = time.time()
        with homes() as home:
            parked(home, moment)
            text = line(home, moment + 61)
        self.assertEqual(text, (
            "[OMH dag] Run feat: parked node a passed wake_at and no node of this run is running. Call omh_dag "
            "action=ready run=feat; the parked node gets its fresh attempt."))

    def test_several_parked_nodes_due_are_named_in_the_plural(self) -> None:
        moment = time.time()
        with homes() as home:
            parked(home, moment, nodes=[node("a"), node("b")])
            at(moment, action="settle", run="feat", node="b", outcome="parked", handle="proc:ci", wake_at=moment + 60)
            text = line(home, moment + 61)
        self.assertEqual(text, (
            "[OMH dag] Run feat: parked nodes a, b passed wake_at and no node of this run is running. Call omh_dag "
            "action=ready run=feat; each parked node gets its fresh attempt."))

    def test_ready_nodes_nobody_dispatched_with_nothing_running_names_ready(self) -> None:
        moment = time.time()
        with homes() as home:
            stored(home, [node("api"), node("ui"), node("verify", depends_on=("api", "ui"))], moment)
            text = line(home, moment + 5)
        self.assertEqual(text, (
            "[OMH dag] Run feat: nodes api, ui ready and no node of this run is running. Call omh_dag action=ready "
            "run=feat and dispatch the calls it returns."))

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

    def test_every_reason_says_what_is_true_of_the_run_only(self) -> None:
        """Mutation: say the parent will not wake (another run's child may), or drop a reason's own text."""
        texts = {reason: dag_open_run_nudge.open_run_text(reason, "feat", ["a"], "1h")
                 for reason in dag_open_run_nudge.REASONS}
        self.assertEqual(len(set(texts.values())), len(texts))
        for reason, text in texts.items():
            with self.subTest(reason=reason):
                self.assertTrue(text.startswith("[OMH dag] Run feat: "), text)
                self.assertIn("run=feat", text)
                self.assertNotIn("nothing will wake", text)


class OutWithNoChildTests(NudgeTestCase):
    """A node handed out that no child runs: a restart ended it, or none ever took it.

    Mutation: keep only parked and ready offerable nodes, drop the `lost_for_good` reason, or count a node out with
    no child as a wake source.
    """

    def out(self, home, moment: float) -> None:
        """A one-node run whose child started in a Hermes process that started at 1000."""
        slots_table(home)
        with patch.object(dag_tool.time, "time", return_value=moment), patch_modules(hermes_process(1000)):
            call(action="define", run="feat", nodes=[node("api")])
            child_started(home, "feat", "api", now=moment + 1)

    def test_a_node_whose_child_a_restart_ended_names_ready(self) -> None:
        moment = time.time()
        with homes() as home:
            self.out(home, moment)
            with patch_modules(hermes_process(1000)):
                alive = line(home, moment + 60)
            with patch_modules(hermes_process(5000)):
                after_restart = line(home, moment + 60)
        self.assertEqual(alive, "")
        self.assertEqual(after_restart, (
            "[OMH dag] Run feat: node api is out with no child (a restart ended it or none took it) and no node of "
            "this run is running. Call omh_dag action=ready run=feat and dispatch the calls it returns."))

    def test_a_second_restart_after_a_fresh_attempt_is_named_again(self) -> None:
        """Mutation: key a situation on its reason and nodes only (the second restart then says nothing)."""
        moment = time.time()
        with homes() as home:
            self.out(home, moment)
            with patch_modules(hermes_process(5000)):
                first = line(home, moment + 60)
                at(moment + 61, action="ready", run="feat")
                start(home, "child-api-2", "sa-api-2", "Node api [dag:feat/api]", now=moment + 62)
                running = line(home, moment + 90)
            with patch_modules(hermes_process(9000)):
                second = line(home, moment + 120)
        self.assertIn("node api is out with no child", first)
        self.assertEqual(running, "")
        self.assertEqual(second, first)

    def test_a_node_past_the_re_offer_bound_names_status_then_settle(self) -> None:
        moment = time.time()
        with homes() as home:
            self.out(home, moment)
            path = dag_run.record_path(home.omh, PARENT, "feat")
            for lost, expected in ((dag_run.MAX_LOST_REOFFERS - 1, "is out with no child"),
                                   (dag_run.MAX_LOST_REOFFERS, "past the re-offer bound")):
                record = dag_run.read_run(path)
                record["nodes"][0]["attempts"][-1]["lost"] = lost
                dag_run.write_run(path, record)
                reset_open_run_nudge()
                with self.subTest(lost=lost), patch_modules(hermes_process(5000)):
                    self.assertIn(expected, line(home, moment + 60))
            with patch_modules(hermes_process(5000)):
                reset_open_run_nudge()
                text = line(home, moment + 60)
        self.assertEqual(text, (
            "[OMH dag] Run feat: a Hermes restart ended the child of node api past the re-offer bound, so ready will "
            "not offer it again, and no node of this run is running. Call omh_dag action=status run=feat, then "
            "settle it failed or blocked."))

    def test_a_node_no_child_took_is_named_once_it_is_offered_again(self) -> None:
        moment = time.time()
        with homes() as home:
            stored(home, [node("api")], moment, out={"api": {}})
            within = line(home, moment + dag_run.HANDOUT_STALE_SECONDS - 1)
            stale = line(home, moment + dag_run.HANDOUT_STALE_SECONDS + 1)
        self.assertEqual(within, "")
        self.assertIn("node api is out with no child", stale)

    def test_a_stuck_mark_of_zero_leaves_a_node_no_child_took_named(self) -> None:
        moment = time.time()
        with homes() as home:
            (home.hermes / "config.yaml").write_text(
                "plugins:\n  entries:\n    omh:\n      settings:\n        dag_stuck_after_s: 0\n", encoding="utf-8")
            stored(home, [node("api")], moment, out={"api": {}})
            self.assertIn("node api is out with no child", line(home, moment + 9 * HOUR))

    def test_a_node_out_with_no_child_is_no_wake_source_for_ready_nodes(self) -> None:
        moment = time.time()
        for lane in ("", "fanout", "parent"):
            with self.subTest(lane=lane or "delegate_task, just out"), homes() as home:
                reset_open_run_nudge()
                stored(home, [node("a"), node("b")], moment, out={"a": {"lane": lane} if lane else {}})
                self.assertIn("node b ready and no node of this run is running", line(home, moment + 5))


class ReturnedTests(NudgeTestCase):
    """A node whose child came back and is not settled is no wake source: its completion already happened.

    Mutation: count a returned node as a wake source, name it on the completion's own turn, or name it every turn.
    """

    def test_a_returned_node_is_named_from_the_turn_after_its_completion(self) -> None:
        moment = time.time()
        with homes() as home:
            stored(home, [node("a"), node("b")], moment, out={"a": {}})
            child_started(home, "feat", "a", now=moment + 1)
            stop(home, "child-a", now=moment + 2)
            completion_turn = line(home, moment + 3)
            next_turn = line(home, moment + 60)
            after = line(home, moment + 120)
        self.assertEqual(completion_turn, "")
        self.assertEqual(next_turn, (
            "[OMH dag] Run feat: node a came back and is not settled, and no node of this run is running. Read its "
            "handoff and call omh_dag action=settle run=feat for it; settle hands out what comes next."))
        self.assertEqual(after, "")

    def test_a_returned_node_while_another_runs_gets_nothing(self) -> None:
        moment = time.time()
        with homes() as home:
            stored(home, [node("a"), node("b")], moment, out={"a": {}, "b": {}})
            child_started(home, "feat", "a", now=moment + 1)
            child_started(home, "feat", "b", now=moment + 1)
            stop(home, "child-a", now=moment + 2)
            self.assertEqual([line(home, moment + 3), line(home, moment + 60)], ["", ""])


class SlotTests(NudgeTestCase):
    """Ready nodes while other work holds every delegate_task slot of this process.

    Mutation: say "call ready" while ready would hand out nothing, or keep that situation claimed so the line never
    comes back once a slot frees.
    """

    def test_slots_held_by_other_work_say_so_and_ready_comes_back_once_free(self) -> None:
        moment = time.time()
        with homes() as home:
            (home.hermes / "config.yaml").write_text("delegation:\n  max_concurrent_children: 1\n", encoding="utf-8")
            slots_table(home, running=[("deleg_other_session", os.getpid())])
            stored(home, [node("a")], moment)
            held = line(home, moment + 5)
            again = line(home, moment + 10)
            slots_table(home)
            freed = line(home, moment + 20)
        self.assertEqual(held, (
            "[OMH dag] Run feat: node a ready and no node of this run is running, but other work holds every "
            "delegate_task slot of this process, so ready would hand out nothing now. Call omh_dag action=ready "
            "run=feat at a later turn, once a slot is free."))
        self.assertEqual(again, "")
        self.assertIn("node a ready and no node of this run is running. Call omh_dag action=ready", freed)


class RepairTests(NudgeTestCase):
    """A failed node with a repair cycle left: the run is needs_repair and only the parent moves it.

    Mutation: drop the needs_repair reason, name it while a child runs, or name a stopped run.
    """

    def failed(self, home, moment: float, nodes: list[dict]) -> None:
        """Define ``nodes`` and settle ``a`` failed after its child came back."""
        slots_table(home)
        at(moment, action="define", run="feat", nodes=nodes)
        child_started(home, "feat", "a", now=moment + 1)
        stop(home, "child-a", "failed", now=moment + 2)
        at(moment + 3, action="settle", run="feat", node="a", outcome="failed", reason="tests fail")

    def test_a_failed_node_with_a_cycle_left_names_repair(self) -> None:
        moment = time.time()
        with homes() as home:
            self.failed(home, moment, [node("a"), node("b", depends_on=("a",))])
            record = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))
            self.assertEqual(dag_run.run_state(record, dag_run.derive(record, [], moment)), "needs_repair")
            texts = [line(home, moment + 60), line(home, moment + 2 * HOUR), line(home, moment + 24 * HOUR)]
        self.assertEqual(texts, [
            "[OMH dag] Run feat: node a failed or blocked with a repair cycle left, and no node of this run is "
            "running. Call omh_dag action=repair run=feat node=a, or report what is open and cancel the run.", "", ""])

    def test_only_failures_with_a_cycle_left_are_named(self) -> None:
        """Mutation: name every open failure, including one whose repair cycles are spent."""
        moment = time.time()
        with homes() as home:
            record = stored(home, [node("a"), node("c")], moment)
            failed = [{"n": 1, "handed_out_at": moment, "outcome": "failed", "settled_at": moment}]
            record["nodes"][0]["attempts"] = failed
            record["nodes"][1]["attempts"] = list(failed)
            for repair in ("r1", "r2"):
                record["nodes"].append({**node(repair), "repairs": "a", "attempts": list(failed)})
            record["repairs"] = {"a": [["r1"], ["r2"]]}
            dag_run.write_run(dag_run.record_path(home.omh, PARENT, "feat"), record)
            self.assertEqual(dag_run.run_state(record, dag_run.derive(record, [], moment)), "needs_repair")
            text = line(home, moment + 60)
        self.assertIn("Run feat: node c failed or blocked with a repair cycle left", text)
        self.assertIn("action=repair run=feat node=c,", text)

    def test_a_failed_node_beside_a_running_child_gets_only_the_stuck_line(self) -> None:
        moment = time.time()
        with homes() as home:
            self.failed(home, moment, [node("a"), node("c")])
            child_started(home, "feat", "c", now=moment + 1)
            below = line(home, moment + 60)
            past = line(home, moment + 2 * HOUR)
        self.assertEqual(below, "")
        self.assertIn("node c open past the 1h stuck mark", past)

    def test_a_stopped_run_with_no_cycle_left_gets_nothing(self) -> None:
        moment = time.time()
        with homes() as home:
            record = stored(home, [node("a"), node("b", depends_on=("a",))], moment)
            failed = [{"n": 1, "handed_out_at": moment, "outcome": "failed", "settled_at": moment}]
            record["nodes"][0]["attempts"] = failed
            for repair in ("r1", "r2"):
                record["nodes"].append({**node(repair), "repairs": "a", "attempts": list(failed)})
            record["repairs"] = {"a": [["r1"], ["r2"]]}
            dag_run.write_run(dag_run.record_path(home.omh, PARENT, "feat"), record)
            self.assertEqual(dag_run.run_state(record, dag_run.derive(record, [], moment)), "stopped")
            self.assertEqual([line(home, moment + 60), line(home, moment + 24 * HOUR)], ["", ""])


class ManyRunsTests(NudgeTestCase):
    """Mutation: judge a run by another run's child, stop at the first claimed run, or re-read finished runs."""

    def test_a_run_with_no_node_running_is_named_beside_a_run_with_one(self) -> None:
        moment = time.time()
        with homes() as home:
            stored(home, [node("a")], moment, run="busy", out={"a": {}})
            child_started(home, "busy", "a", now=moment + 1)
            stored(home, [node("b")], moment, run="idle")
            text = line(home, moment + 5)
        self.assertEqual(text, (
            "[OMH dag] Run idle: node b ready and no node of this run is running. Call omh_dag action=ready run=idle "
            "and dispatch the calls it returns."))

    def test_a_claimed_run_falls_through_to_the_next_one(self) -> None:
        moment = time.time()
        with homes() as home:
            stored(home, [node("a")], moment, run="older")
            stored(home, [node("b")], moment + 1, run="newer")
            texts = [line(home, moment + 5), line(home, moment + 6), line(home, moment + 7)]
        self.assertEqual([text.split(":")[0] for text in texts], ["[OMH dag] Run newer", "[OMH dag] Run older", ""])

    def test_a_finished_run_is_read_once_until_its_file_changes(self) -> None:
        moment = time.time()
        with homes() as home:
            record = stored(home, [node("a")], moment)
            record["nodes"][0]["attempts"] = [{"n": 1, "handed_out_at": moment, "outcome": "accepted",
                                               "settled_at": moment}]
            path = dag_run.record_path(home.omh, PARENT, "feat")
            dag_run.write_run(path, record)
            reads = []
            real = dag_run.read_run

            def counted(target):
                reads.append(target)
                return real(target)

            with patch.object(dag_run, "read_run", side_effect=counted):
                self.assertEqual([line(home, moment + 5), line(home, moment + 6)], ["", ""])
                self.assertEqual(len(reads), 1, "a finished run is not read again while its file is unchanged")
                # An extend round reopens the run: a changed file is read again.
                record["nodes"].append({**node("b"), "attempts": []})
                dag_run.write_run(path, record)
                text = line(home, moment + 7)
        self.assertEqual(len(reads), 2)
        self.assertIn("node b ready", text)


class SilentTests(NudgeTestCase):
    """Mutation: drop the running-child, finished, child-session or claim check; let a read fault raise."""

    def test_a_parked_node_whose_wake_is_still_ahead_gets_nothing(self) -> None:
        moment = time.time()
        with homes() as home:
            parked(home, moment)
            self.assertEqual(line(home, moment + 30), "")

    def test_a_node_with_a_running_child_silences_the_run(self) -> None:
        moment = time.time()
        with self.subTest(other="parked past its wake"), homes() as home:
            # `a` is parked past its wake, but `b`'s child runs, and its completion re-opens the run.
            parked(home, moment, nodes=[node("a"), node("b")])
            child_started(home, "feat", "b", now=moment + 1)
            self.assertEqual(line(home, moment + 61), "")
        with self.subTest(other="ready"), homes() as home:
            stored(home, [node("a"), node("b")], moment, out={"a": {}})
            child_started(home, "feat", "a", now=moment + 1)
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
        reads = ((dag_run, "derive"), (dag_run, "read_run"), (dag_open_run_nudge, "reading_session_id"),
                 (dag_open_run_nudge, "conversation_session_ids"), (dag_tool, "_children"), (dag_tool, "dag_limits"),
                 (dag_tool, "free_slots"))
        faults = (OSError("disk"), KeyError("nodes"), ValueError("bad"), sqlite3.OperationalError("locked"),
                  TypeError("shape"), RuntimeError("cycle"))
        with homes() as home:
            path = dag_run.record_path(home.omh, PARENT, "feat")
            path.parent.mkdir(parents=True)
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(line(home, moment), "")
            stored(home, [node("api")], moment, run="other")
            for target, name in reads:
                for raised in faults:
                    with self.subTest(target=name, raised=type(raised).__name__), patch.object(
                            target, name, side_effect=raised):
                        self.assertEqual(line(home, moment), "")
            # Every patched read was on the path: unpatched, the same turn names the run.
            self.assertIn("Run other: node api ready", line(home, moment))

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

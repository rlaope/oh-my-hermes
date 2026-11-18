"""A dag node whose child stops on a judgement it cannot settle is settled escalated and offered one category up.

`dag_run.settle(outcome="escalated")` closes the attempt like a provider-error retry, moves the node one rung up
`dag_run.ESCALATION_LADDER` (at most `dag_run.MAX_ESCALATIONS` times), and the next task carries the question.
"""

from __future__ import annotations

import json
import os
import time
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

import test_dag_tool as dag_tests  # noqa: E402  (helpers only; a module import keeps its tests out of this file)
from _delegation_state import PARENT, homes  # noqa: E402

from omh.plugin_bundle.omh import dag_run  # noqa: E402
from omh.plugin_bundle.omh.hooks import nudge_budget, session_attendance  # noqa: E402
from omh.plugin_bundle.omh.hooks.tool_hooks import pre_tool_call  # noqa: E402

ESCALATE_LINE = (
    "If the task turns on a judgement you cannot settle with confidence (a design choice, a root cause you cannot pin "
    "down), do not guess: before editing, write ESCALATE: <the question> and what you found into the handoff, and stop."
)
QUESTION = "Should the cache key include the tenant id?"


def _record(category: str = "quick", **extra: object) -> dict:
    raw = [{**dag_tests.node("api", category=category, scope=("src/api.py",)), **extra}]
    return dag_run.new_record(PARENT, "feat", "Feature", "Ship it", raw, 1_000_000.0)


def _out(record: dict, now: float, home) -> list[dict]:
    """Hand out every offerable node; the calls ``ready`` would return."""
    calls, _ = dag_run.calls_for(record, dag_run.derive(record, [], now), free_slots=10, per_call=10,
                                 omh_home=home, now=now)
    return calls


def _settle(record: dict, outcome: str, reason: object, now: float, **kwargs: object) -> str:
    def unread() -> tuple[bool, str]:
        raise AssertionError("an escalated settle reads no handoff")

    kwargs.setdefault("provider_error", False)
    return dag_run.settle(record, dag_run.derive(record, [], now), "api", outcome, reason,
                          kwargs.pop("provider_error"), read_handoff=unread, now=now, **kwargs)


class EscalationClimbsTheLadderTest(unittest.TestCase):
    def test_a_quick_node_escalates_twice_and_each_call_carries_the_question(self) -> None:
        with homes() as home:
            record, now = _record(), 1_000_000.0
            node = record["nodes"][0]
            self.assertEqual(_out(record, now, home.omh)[0]["category"], "quick")
            self.assertEqual(_settle(record, "escalated", QUESTION, now + 1), "escalated")
            attempt = node["attempts"][-1]
            self.assertEqual((attempt["outcome"], attempt["reason"], attempt["settled_at"]),
                             ("escalated", QUESTION, now + 1))
            self.assertEqual((attempt["escalated_from"], attempt["escalated_to"]), ("quick", "unspecified-low"))
            self.assertEqual(node["category"], "unspecified-low")
            self.assertEqual(node["defined_category"], "quick")
            self.assertEqual(node["escalations"], [{"from": "quick", "to": "unspecified-low", "at": now + 1}])
            self.assertEqual(dag_run.derive(record, [], now + 2)["api"]["state"], "ready")

            calls = _out(record, now + 2, home.omh)
            self.assertEqual(calls[0]["category"], "unspecified-low")
            context = calls[0]["tasks"][0]["context"]
            handoff = dag_run.node_handoff(record, home.omh, "api")
            paragraph = (f"Escalated from quick to unspecified-low. The previous attempt stopped on this question: "
                         f"{QUESTION} Read its handoff at {handoff} for what it found, decide the question, then do "
                         "the task.")
            self.assertIn(paragraph, context)
            # After the resume line's place, before the run goal.
            self.assertLess(context.index(paragraph), context.index("Run goal (saved):"))
            fresh = node["attempts"][-1]
            self.assertFalse(fresh["fallback"])
            self.assertNotIn("resume_handle", fresh)
            # unspecified-low still has a rung above and one escalation left.
            self.assertIn(ESCALATE_LINE, context)
            self.assertEqual(context.index(ESCALATE_LINE) + len(ESCALATE_LINE) + 1,
                             context.index("Stay inside your SCOPE"))

            self.assertEqual(_settle(record, "escalated", "Which index wins?", now + 3), "escalated")
            self.assertEqual(node["category"], "unspecified-high")
            self.assertEqual(node["defined_category"], "quick")
            self.assertEqual([step["to"] for step in node["escalations"]], ["unspecified-low", "unspecified-high"])
            calls = _out(record, now + 4, home.omh)
            self.assertEqual(calls[0]["category"], "unspecified-high")
            context = calls[0]["tasks"][0]["context"]
            self.assertIn("Escalated from unspecified-low to unspecified-high. The previous attempt stopped on this "
                          "question: Which index wins? Read", context)
            # At the limit the line is gone, though unspecified-high has a rung above it.
            self.assertNotIn(ESCALATE_LINE, context)

    def test_an_unspecified_high_node_escalates_to_ultrabrain(self) -> None:
        with homes() as home:
            record = _record("unspecified-high")
            _out(record, 1_000_000.0, home.omh)
            _settle(record, "escalated", QUESTION, 1_000_001.0)
            self.assertEqual(record["nodes"][0]["category"], "ultrabrain")
            self.assertEqual(_out(record, 1_000_002.0, home.omh)[0]["category"], "ultrabrain")

    def test_a_provider_retry_after_an_escalation_keeps_the_question(self) -> None:
        with homes() as home:
            record, now = _record(), 1_000_000.0
            _out(record, now, home.omh)
            _settle(record, "escalated", QUESTION, now + 1)
            _out(record, now + 2, home.omh)
            self.assertEqual(_settle(record, "failed", "HTTP 400", now + 3, provider_error=True), "retry")
            context = _out(record, now + 4, home.omh)[0]["tasks"][0]["context"]
        self.assertIn(f"stopped on this question: {QUESTION} Read", context)

    def test_a_question_without_an_end_mark_gets_one_full_stop(self) -> None:
        with homes() as home:
            record, now = _record(), 1_000_000.0
            _out(record, now, home.omh)
            _settle(record, "escalated", "Which schema owns the tenant column", now + 1)
            context = _out(record, now + 2, home.omh)[0]["tasks"][0]["context"]
        self.assertIn("stopped on this question: Which schema owns the tenant column. Read", context)
        self.assertNotIn("?.", context)

    def test_an_accepted_attempt_after_an_escalation_ends_the_paragraph(self) -> None:
        with homes() as home:
            record, now = _record(), 1_000_000.0
            _out(record, now, home.omh)
            _settle(record, "escalated", QUESTION, now + 1)
            _out(record, now + 2, home.omh)
            dag_run.settle(record, dag_run.derive(record, [], now + 3), "api", "accepted", "", False,
                           read_handoff=lambda: (True, ""), now=now + 3)
            node = record["nodes"][0]
            self.assertEqual(dag_run.derive(record, [], now + 4)["api"]["state"], "accepted")
            context = dag_run.task_for(record, node, home.omh, dag_run.derive(record, [], now + 4))["context"]
        self.assertNotIn("Escalated from", context)


class RetryCountTest(unittest.TestCase):
    def test_retries_restart_after_an_escalation(self) -> None:
        node = {"attempts": [{"outcome": "retry"}, {"outcome": "escalated"}]}
        self.assertEqual(dag_run.retry_count(node), 0)
        node["attempts"].append({"outcome": "retry"})
        self.assertEqual(dag_run.retry_count(node), 1)
        self.assertEqual(dag_run.retry_count({"attempts": [{"outcome": "retry"}, {"outcome": "failed"}]}), 1)
        self.assertEqual(dag_run.retry_count({}), 0)

    def test_the_new_category_starts_from_its_first_model_map_option(self) -> None:
        with homes() as home:
            record, now = _record(), 1_000_000.0
            backend = {"backend": "model_map", "status": "read",
                       "options": {"quick": ["q1", "q2"], "unspecified-low": ["l1", "l2"]}}

            def out(at: float) -> dict:
                calls, _ = dag_run.calls_for(record, dag_run.derive(record, [], at), free_slots=10, per_call=10,
                                             omh_home=home.omh, now=at, backend=backend)
                return calls[0]

            self.assertEqual(out(now)["route"]["option"], "q1")
            _settle(record, "failed", "HTTP 400", now + 1, provider_error=True)
            self.assertEqual(out(now + 2)["route"]["option"], "q2")
            _settle(record, "escalated", QUESTION, now + 3)
            self.assertEqual(out(now + 4)["route"]["option"], "l1")


class EscalationRefusedTest(unittest.TestCase):
    def _refusal(self, record: dict, reason: object, now: float = 1_000_001.0) -> str:
        with self.assertRaises(dag_run.DagRefusal) as caught:
            _settle(record, "escalated", reason, now)
        return caught.exception.reason

    def test_an_empty_reason_is_refused(self) -> None:
        with homes() as home:
            record = _record()
            _out(record, 1_000_000.0, home.omh)
            for reason in ("", "   ", None):
                self.assertEqual(self._refusal(record, reason), "escalation_needs_reason")
            self.assertEqual(record["nodes"][0]["category"], "quick")
            self.assertNotIn("escalations", record["nodes"][0])

    def test_a_category_off_the_ladder_cannot_escalate(self) -> None:
        for category in ("ultrabrain", "review", "deep", "writing"):
            with self.subTest(category=category), homes() as home:
                record = _record(category)
                _out(record, 1_000_000.0, home.omh)
                self.assertEqual(self._refusal(record, QUESTION), "no_higher_category")
                self.assertEqual(record["nodes"][0]["category"], category)
                self.assertEqual(record["nodes"][0]["attempts"][-1]["outcome"], "")

    def test_a_third_escalation_is_refused(self) -> None:
        with homes() as home:
            record, now = _record(), 1_000_000.0
            for step in range(dag_run.MAX_ESCALATIONS):
                _out(record, now + 2 * step, home.omh)
                _settle(record, "escalated", QUESTION, now + 2 * step + 1)
            _out(record, now + 10, home.omh)
            self.assertEqual(record["nodes"][0]["category"], "unspecified-high")
            self.assertEqual(self._refusal(record, QUESTION, now + 11), "escalation_limit_reached")
            self.assertEqual(len(record["nodes"][0]["escalations"]), dag_run.MAX_ESCALATIONS)

    def test_a_node_not_out_is_refused(self) -> None:
        record = _record()
        self.assertEqual(self._refusal(record, QUESTION), "node_not_out")

    def test_a_cancelled_run_is_refused(self) -> None:
        with homes() as home:
            record = _record()
            _out(record, 1_000_000.0, home.omh)
            record["cancelled_at"] = 1_000_000.5
            self.assertEqual(self._refusal(record, QUESTION), "run_cancelled")

    def test_an_escalated_settle_reads_no_handoff(self) -> None:
        with homes() as home:
            record = _record()
            _out(record, 1_000_000.0, home.omh)
            reads: list[str] = []
            happened = dag_run.settle(
                record, dag_run.derive(record, [], 1_000_001.0), "api", "escalated", QUESTION, False,
                read_handoff=lambda: reads.append("handoff") or (False, ""),
                read_criteria=lambda: reads.append("criteria") or (False, "", []), now=1_000_001.0)
        self.assertEqual((happened, reads), ("escalated", []))


class EscalateLineTest(unittest.TestCase):
    def test_only_a_node_that_can_escalate_is_told_how(self) -> None:
        with homes() as home:
            for category, expected in (("quick", True), ("unspecified-low", True), ("unspecified-high", True),
                                       ("ultrabrain", False), ("review", False), ("deep", False)):
                with self.subTest(category=category):
                    record = _record(category)
                    context = dag_run.task_for(record, record["nodes"][0], home.omh,
                                               dag_run.derive(record, [], 1_000_000.0))["context"]
                    self.assertEqual(ESCALATE_LINE in context, expected)
                    self.assertNotIn("Escalated from", context)

    def test_a_node_at_the_limit_is_not_told(self) -> None:
        with homes() as home:
            record = _record()
            record["nodes"][0]["escalations"] = [{"from": "a", "to": "b", "at": 0}] * dag_run.MAX_ESCALATIONS
            context = dag_run.task_for(record, record["nodes"][0], home.omh,
                                       dag_run.derive(record, [], 1_000_000.0))["context"]
        self.assertNotIn(ESCALATE_LINE, context)


class StatusAndStoredRecordTest(unittest.TestCase):
    def test_status_rows_count_escalations(self) -> None:
        with homes() as home:
            record, now = _record(), 1_000_000.0
            row = dag_run.node_rows(record, dag_run.derive(record, [], now))[0]
            self.assertNotIn("escalations", row)
            self.assertNotIn("defined_category", row)
            _out(record, now, home.omh)
            _settle(record, "escalated", QUESTION, now + 1)
            row = dag_run.node_rows(record, dag_run.derive(record, [], now + 2))[0]
        self.assertEqual((row["escalations"], row["defined_category"]), (1, "quick"))
        self.assertEqual((row["category"], row["state"], row["reason"]), ("unspecified-low", "ready", QUESTION))

    def test_a_record_with_and_without_escalations_reads(self) -> None:
        with homes() as home:
            record, now = _record(), 1_000_000.0
            path = dag_run.record_path(home.omh, PARENT, "feat")
            path.parent.mkdir(parents=True, exist_ok=True)
            dag_run.write_run(path, record)
            stored = dag_run.read_run(path)
            assert stored is not None
            self.assertNotIn("escalations", stored["nodes"][0])
            _out(record, now, home.omh)
            _settle(record, "escalated", QUESTION, now + 1)
            dag_run.write_run(path, record)
            self.assertEqual(dag_run.read_run(path), json.loads(json.dumps(record)))


class ToolSaysWhereTheNodeGoesTest(unittest.TestCase):
    def test_the_tool_settles_escalated_and_offers_the_node_again(self) -> None:
        with homes() as home:
            dag_tests.slots_table(home)
            nodes = [dag_tests.node("api", scope=("src/api.py",))]
            self.assertEqual(dag_tests.call(action="define", run="feat", goal="ship", nodes=nodes)["status"], "ok")
            refused = dag_tests.call(action="settle", run="feat", node="api", outcome="escalated", reason="")
            self.assertEqual(refused.get("reason"), "escalation_needs_reason", refused)
            settled = dag_tests.call(action="settle", run="feat", node="api", outcome="escalated", reason=QUESTION)
        self.assertEqual(settled["status"], "ok", settled)
        self.assertEqual(settled["settled"], {"node": "api", "outcome": "escalated"})
        self.assertIn("Node api goes up to unspecified-low; it is offered again with the question it stopped on.",
                      settled["say"])
        self.assertIn("escalated", dag_tests.dag_tool.OMH_DAG_SCHEMA["parameters"]["properties"]["outcome"]["enum"])


class ScopeGuardTest(unittest.TestCase):
    def test_an_escalated_last_attempt_binds_no_child(self) -> None:
        with homes() as home:
            workspace = (home.omh.parent / "repo").resolve()
            (workspace / "src").mkdir(parents=True)
            cwd = mock.patch.dict(os.environ, {"TERMINAL_CWD": str(workspace)})
            cwd.start()
            self.addCleanup(cwd.stop)
            session_attendance.reset_session_attendance()
            nudge_budget.reset_nudge_budget()
            self.addCleanup(session_attendance.reset_session_attendance)
            self.addCleanup(nudge_budget.reset_nudge_budget)
            dag_tests.slots_table(home)
            nodes = [dag_tests.node("api", scope=("src/api.py",))]
            self.assertEqual(dag_tests.call(action="define", run="feat", goal="ship", nodes=nodes)["status"], "ok")
            dag_tests.call(action="ready", run="feat")
            dag_tests.child_started(home, "feat", "api", now=time.time())

            def write() -> dict | None:
                return pre_tool_call(tool_name="write_file", args={"path": "src/other.py", "content": "x\n"},
                                     session_id="child-api", task_id="child-api", turn_id="turn-1", **home.hooks())

            blocked = write()
            assert blocked is not None
            self.assertEqual(blocked["action"], "block")
            settled = dag_tests.call(action="settle", run="feat", node="api", outcome="escalated", reason=QUESTION)
            self.assertEqual(settled["settled"]["outcome"], "escalated", settled)
            # The settle's own ready handed the node out again: write the record back to the closed attempt.
            path = dag_run.record_path(home.omh, PARENT, "feat")
            record = json.loads(path.read_text(encoding="utf-8"))
            attempts = record["nodes"][0]["attempts"]
            if attempts[-1]["outcome"] == "":
                attempts.pop()
            self.assertEqual(attempts[-1]["outcome"], "escalated")
            dag_run.write_run(path, record)
            self.assertIsNone(write())


if __name__ == "__main__":
    unittest.main()

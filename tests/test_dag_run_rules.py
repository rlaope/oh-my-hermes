"""The run rules of `omh_dag` that a goal loop leans on: repairs, re-verification, blocked nodes, the stored record.

Each test drives the tool the way Hermes calls it (`test_dag_tool.call`) and
reads what the parent would read: the task context of the next call, the run
state, the rows, and the stored record.
"""

from __future__ import annotations

import json
import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from _delegation_state import PARENT, homes  # noqa: E402
from omh.plugin_bundle.omh import dag_run  # noqa: E402
from omh.plugin_bundle.omh.tools import dag_tool  # noqa: E402
from test_dag_tool import PROMPT, call, child_started, handoff, node, slots_table  # noqa: E402


def calls_by_node(result: dict) -> dict[str, dict]:
    return {node_id: task for call_row in result.get("calls", [])
            for node_id, task in zip(call_row["nodes"], call_row["tasks"])}


def states(result: dict) -> dict[str, str]:
    return {row["id"]: row["state"] for row in result["nodes"]}


def record_of(home, run: str = "feat") -> dict:
    return json.loads(dag_run.record_path(home.omh, PARENT, run).read_text(encoding="utf-8"))


class SavedGoalLifecycleTests(unittest.TestCase):
    """Delivery checks only: no live worker compliance is inferred."""

    def test_retry_repair_reverification_and_extend_keep_the_saved_goal(self) -> None:
        goal = "Retain executable engine and output quality; compare the same task before accepting."
        with homes() as home:
            slots_table(home)
            definitions = [node("api", scope=("a.py",)), node("verify", role="verify", depends_on=("api",))]
            call(action="define", run="feat", goal=goal, nodes=definitions)
            # A repeated definition does not replace the immutable saved goal.
            call(action="define", run="feat", goal="Only package tests now", nodes=definitions)
            retried = call(action="settle", run="feat", node="api", outcome="failed", provider_error=True)
            self.assertEqual(retried["calls"][0]["route"]["action"], "fallback")
            call(action="settle", run="feat", node="api", outcome="failed")
            repaired = call(action="repair", run="feat", node="api", nodes=[node("api-fix", scope=("a.py",))])
            handoff(home, "feat", "api-fix")
            verified = call(action="settle", run="feat", node="api-fix", outcome="accepted")
            self.assertIn("api-fix.md", calls_by_node(verified)["verify"]["context"])
            call(action="settle", run="feat", node="verify", outcome="failed")
            verify_repair = call(action="repair", run="feat", node="verify", nodes=[node("fix", scope=("a.py",))])
            handoff(home, "feat", "fix")
            reverified = call(action="settle", run="feat", node="fix", outcome="accepted")
            handoff(home, "feat", "verify")
            done = call(action="settle", run="feat", node="verify", outcome="accepted")
            self.assertEqual(done["state"], "done")
            extended = call(action="extend", run="feat", nodes=[node("craft", depends_on=("verify",), scope=("craft.py",)),
                            node("verify-output", role="verify", depends_on=("craft",))])
            handoff(home, "feat", "craft")
            extend_verified = call(action="settle", run="feat", node="craft", outcome="accepted")
            for result, node_id in ((retried, "api"), (repaired, "api-fix"), (verified, "verify"),
                                    (verify_repair, "fix"), (reverified, "verify"), (extended, "craft"),
                                    (extend_verified, "verify-output")):
                with self.subTest(node=node_id, result=result):
                    self.assertEqual(result["status"], "ok", result)
                    context = calls_by_node(result)[node_id]["context"]
                    self.assertIn(f"Run goal (saved):\n{goal}\n", context)
                    self.assertIn("not permission to widen your SCOPE", context)
                    if "verify" in node_id:
                        self.assertIn("Check the complete run goal", context)
            self.assertEqual(record_of(home)["goal"], goal)

    def test_ready_reoffers_reloaded_legacy_records_without_inventing_a_goal(self) -> None:
        for legacy in (None, "", "   "):
            with self.subTest(goal=legacy), homes() as home:
                slots_table(home)
                call(action="define", run="feat", nodes=[node("api")])
                path = dag_run.record_path(home.omh, PARENT, "feat")
                record = record_of(home)
                if legacy is None:
                    record.pop("goal")
                else:
                    record["goal"] = legacy
                path.write_text(json.dumps(record), encoding="utf-8")
                with patch.object(dag_tool.time, "time", return_value=time.time() + dag_run.HANDOUT_STALE_SECONDS + 1):
                    ready = call(action="ready", run="feat")
                task = calls_by_node(ready)["api"]
                self.assertNotIn("Run goal (saved):", task["context"])
                self.assertNotIn("None", task["context"])
                self.assertEqual(task["goal"], "Node api [dag:feat/api]")

    def test_ready_reoffers_saved_goal_at_its_existing_limit(self) -> None:
        goal = "Q" * dag_run.MAX_GOAL_CHARS
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", goal=goal, nodes=[node("api")])
            with patch.object(dag_tool.time, "time", return_value=time.time() + dag_run.HANDOUT_STALE_SECONDS + 1):
                ready = call(action="ready", run="feat")
            self.assertIn(f"Run goal (saved):\n{goal}\n", calls_by_node(ready)["api"]["context"])


class BaselineNodeTests(unittest.TestCase):
    def test_baseline_is_not_verification_or_coding(self) -> None:
        for node_id, label in (("baseline", "Verify existing tests"),
                               ("verify-baseline", "Capture failures"),
                               ("capture", "Audit BASELINE failures")):
            with self.subTest(node_id=node_id, label=label):
                baseline = node(node_id, label=label, scope=("baseline.txt",))
                self.assertTrue(dag_run.is_baseline(baseline))
                self.assertFalse(dag_run.is_verification(baseline))
                self.assertFalse(dag_run.is_coding(baseline))
        for label in ("Prebaseline check", "Baselineish change"):
            with self.subTest(label=label):
                self.assertFalse(dag_run.is_baseline(node("api", label=label)))
        record = dag_run.new_record(PARENT, "feat", "Feature", "", [
            node("baseline", role="baseline", scope=("baseline.txt",)), node("api", scope=("api.py",)),
        ], time.time())
        derived = dag_run.derive(record, [], time.time())
        self.assertEqual([unit["unit_id"] for unit in dag_tool.export_units(record, derived, "codex")], ["api"])
        with homes() as home, patch.object(dag_tool, "owner_choice", return_value="codex"):
            slots_table(home)
            result = call(action="define", run="feat", nodes=[
                node("baseline", role="baseline", scope=("baseline.txt",)), node("api", scope=("api.py",)),
            ])
            self.assertIn("baseline", calls_by_node(result))
            self.assertEqual(result["export"]["nodes"], ["api"])

    def test_lint_verify_without_baseline(self) -> None:
        for prompt in ("Run the FULL SUITE", "python -m unittest discover -s tests", "pytest", "Run `pytest -q`",
                       "VERIFY: pytest, exit 0", "python -m pytest --maxfail=1 -k 'not slow'",
                       "pytest --tb short", "pytest tests/test_api.py && pytest -q"):
            with self.subTest(prompt=prompt):
                definitions = [node("api"), node("verify", role="verify", depends_on=("api",), prompt=prompt)]
                self.assertIn("verify_without_baseline:verify", dag_run.lint(definitions))
                definitions.insert(0, node("baseline", role="baseline"))
                self.assertIn("verify_without_baseline:verify", dag_run.lint(definitions))
                definitions[1]["depends_on"] = ["baseline"]
                self.assertNotIn("verify_without_baseline:verify", dag_run.lint(definitions))
        for prompt in ("pytest tests/test_api.py", "pytest -q tests/", "pytest -k 'not slow' tests",
                       "python -m unittest tests.test_api", "Run the focused suite", "pytest.ini"):
            with self.subTest(prompt=prompt):
                self.assertNotIn("verify_without_baseline:verify", dag_run.lint([node("verify", prompt=prompt)]))
        self.assertNotIn("verify_without_baseline:baseline", dag_run.lint([
            node("baseline", role="baseline", label="Verify baseline", prompt="Run full suite"),
        ]))

    def test_verify_held_when_baseline_failed(self) -> None:
        for outcome in ("failed", "blocked"):
            for indirect in (False, True):
                with self.subTest(outcome=outcome, indirect=indirect), homes() as home:
                    slots_table(home)
                    definitions = [node("baseline", role="baseline"), node("side")]
                    if indirect:
                        definitions.append(node("api", depends_on=("baseline",)))
                    definitions.append(node("verify", role="verify", depends_on=("api" if indirect else "baseline",)))
                    started = call(action="define", run="feat", nodes=definitions)
                    self.assertIn("side", calls_by_node(started))
                    failed = call(action="settle", run="feat", node="baseline", outcome=outcome)
                    ready = call(action="ready", run="feat")
                    for result in (failed, ready):
                        row = next(item for item in result["nodes"] if item["id"] == "verify")
                        self.assertEqual((row["state"], row["held_by"], row["attempts"]), ("held", ["baseline"], 0))
                        self.assertNotIn("verify", calls_by_node(result))
                    record = record_of(home)
                    self.assertNotIn("verify", dag_run.offerable(record, dag_run.derive(record, [], time.time()),
                                                                time.time()))

    def _baseline_context(self, home) -> tuple[dict, str]:
        record = dag_run.new_record(PARENT, "feat", "Feature", "", [
            node("baseline", role="baseline"),
            node("old-tests", role="baseline", label="Capture BASELINE failures"),
            node("unrelated-baseline", role="baseline"),
            node("api", depends_on=("baseline", "old-tests")),
            node("verify", role="verify", depends_on=("api",)),
        ], time.time())
        record["handoff_root"] = "/sandbox-home/dev/.omh/dag"
        derived = dag_run.derive(record, [], time.time())
        context = dag_run.task_for(record, record["nodes"][-1], home.omh, derived)["context"]
        return record, context

    def _baseline_line(self, home) -> str:
        return next(line for line in self._baseline_context(home)[1].splitlines() if line.startswith("Baseline:"))

    def test_verify_task_names_baseline_handoff(self) -> None:
        with homes() as home:
            record, context = self._baseline_context(home)
            baseline_lines = [line for line in context.splitlines() if line.startswith("Baseline:")]
            self.assertEqual(len(baseline_lines), 2)
            for baseline_id, line in zip(("baseline", "old-tests"), baseline_lines):
                self.assertIn(dag_run.node_handoff(record, home.omh, baseline_id), line)
                self.assertIn("Read", line)
                self.assertIn("same test id and assertion/error signature", line)
            self.assertNotIn("unrelated-baseline.md", "\n".join(baseline_lines))
            producer = dag_run.task_for(record, record["nodes"][-2], home.omh,
                                        dag_run.derive(record, [], time.time()))["context"]
            self.assertNotIn("Baseline:", producer)

    def test_matching_baseline_failure_may_be_exempted_but_is_disclosed(self) -> None:
        # Worker guidance only: this pins the generated instruction, not live compliance.
        with homes() as home:
            line = self._baseline_line(home)
        self.assertIn("Exempt only a failure it lists that you re-ran here with the same test id and "
                      "assertion/error signature", line)
        self.assertIn("under a comparable command and environment at the pinned base and candidate revisions", line)
        self.assertIn("report it as pre-existing", line)
        self.assertIn("does not make an unmet full-suite-green goal done", line)
        self.assertNotIn("fail only on test failures absent from the baseline list", line)

    def test_baseline_exemption_never_waives_changed_or_unevidenced_failures(self) -> None:
        # Worker guidance only: this pins the generated instruction, not live compliance.
        with homes() as home:
            line = self._baseline_line(home)
        for guard in ("same-id failure that changed", "missing evidence", "skipped or reduced coverage",
                      "collection/execution/exit errors", "security or mandatory gates"):
            with self.subTest(guard=guard):
                self.assertIn(guard, line)
        self.assertIn("never exempt: fail them", line)

    def test_baseline_failures_do_not_close_an_unmet_full_suite_goal(self) -> None:
        with homes() as home:
            context = self._baseline_context(home)[1]
        self.assertIn("does not make an unmet full-suite-green goal done", context)
        self.assertIn("Check the complete run goal, not only this node's local VERIFY", context)
        self.assertIn("Name each unmet or unobserved goal criterion", context)

    def test_baseline_quality_bar_carries_the_same_comparison_guards(self) -> None:
        from omh.skills.dag_ulw_skill import DEFINITION

        bullets = [bullet for bullet in DEFINITION.quality_bar if "`baseline` node" in bullet]
        self.assertEqual(len(bullets), 1)
        bullet = bullets[0]
        for term in ("test id, assertion/error signature", "comparable command", "pinned base and candidate revisions",
                     "changed same-id failure", "missing evidence", "skipped or reduced coverage",
                     "collection/exit errors", "security/mandatory gates", "pre-existing",
                     "full-suite-green goal met"):
            with self.subTest(term=term):
                self.assertIn(term, bullet)


class ParkedNodeTests(unittest.TestCase):
    def test_parked_wait_contract_is_documented(self) -> None:
        from omh.skills.dag_ulw_skill import run_loop_reference

        reference = run_loop_reference()
        for phrase in ("outcome=parked", "handle", "wake_at", "24 hours", "three parks", "park_limit_reached"):
            self.assertIn(phrase, reference)

    def test_short_park_does_not_rebind_the_previous_child(self) -> None:
        with homes() as home:
            slots_table(home)
            moment = time.time()
            with patch.object(dag_tool.time, "time", return_value=moment):
                call(action="define", run="feat", nodes=[node("a")])
                child_started(home, "feat", "a", now=moment)
                call(action="settle", run="feat", node="a", outcome="parked",
                     handle="proc:short", wake_at=moment + 1)
            with patch.object(dag_tool.time, "time", return_value=moment + 1):
                ready = call(action="ready", run="feat")
            self.assertEqual(states(ready)["a"], "handed_out", ready)

    def test_cancel_turns_parked_cancelled(self) -> None:
        for elapsed in (0, 61):
            with self.subTest(elapsed=elapsed), homes() as home:
                slots_table(home)
                moment = time.time()
                with patch.object(dag_tool.time, "time", return_value=moment):
                    call(action="define", run="feat", nodes=[node("a")])
                    call(action="settle", run="feat", node="a", outcome="parked",
                         handle="proc:123", wake_at=moment + 60)
                with patch.object(dag_tool.time, "time", return_value=moment + elapsed):
                    cancelled = call(action="cancel", run="feat")
                    ready = call(action="ready", run="feat")
                self.assertEqual(cancelled["state"], "cancelled")
                self.assertEqual(states(cancelled)["a"], "cancelled")
                self.assertFalse(ready["calls"])
                self.assertEqual(record_of(home)["nodes"][0]["attempts"][-1]["outcome"], "parked")

    def test_legacy_record_without_parked_derives(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "Feature", "", [node("a"), node("b", depends_on=("a",))], 100)
        for outcome, expected in (("", "handed_out"), ("accepted", "accepted"), ("failed", "failed"),
                                  ("blocked", "blocked"), ("retry", "ready")):
            with self.subTest(outcome=outcome):
                # Pre-park attempts have neither wait metadata nor resume metadata.
                record["nodes"][0]["attempts"] = [{"n": 1, "handed_out_at": 100, "outcome": outcome,
                                                  "settled_at": 101 if outcome else None}]
                derived = dag_run.derive(record, [], 200)
                self.assertEqual(derived["a"], {"child": None, "attempts": 1, "waits_on": [],
                                                "held_by": [], "state": expected})
                dependent = {"accepted": "ready", "failed": "held", "blocked": "held"}.get(outcome, "waiting")
                self.assertEqual(derived["b"]["state"], dependent)
                self.assertEqual(dag_run.cycles_left(record, "a"), dag_run.MAX_REPAIR_CYCLES)

    def test_parked_needs_handle_and_deadline(self) -> None:
        moment = 1_800_000_000.0
        invalid = [
            ({"wake_at": moment + 60}, "invalid_handle"),
            ({"handle": "", "wake_at": moment + 60}, "invalid_handle"),
            ({"handle": "x" * 121, "wake_at": moment + 60}, "invalid_handle"),
            ({"handle": "proc:\n123", "wake_at": moment + 60}, "invalid_handle"),
            ({"handle": 123, "wake_at": moment + 60}, "invalid_handle"),
            ({"handle": "proc:123"}, "invalid_wake_at"),
        ]
        invalid.extend(({"handle": "proc:123", "wake_at": deadline}, "invalid_wake_at")
                       for deadline in (None, True, float("nan"), float("inf"), moment, moment - 1,
                                        moment + 86401, "nonsense", "2027-01-15T08:01:00",
                                        "2027-01-15T09:01:00+01:00"))
        with homes() as home, patch.object(dag_tool.time, "time", return_value=moment):
            slots_table(home)
            call(action="define", run="feat", nodes=[node("a")])
            original = record_of(home)
            for args, reason in invalid:
                with self.subTest(args=args):
                    refused = call(action="settle", run="feat", node="a", outcome="parked", **args)
                    self.assertEqual(refused.get("reason"), reason, refused)
                    self.assertEqual(record_of(home), original)
            for index, deadline in enumerate((moment + 86400, "2027-01-15T08:01:00Z",
                                              "2027-01-15T08:01:00+00:00")):
                run = f"valid-{index}"
                call(action="define", run=run, nodes=[node("a")])
                result = call(action="settle", run=run, node="a", outcome="parked",
                              handle="x" * 120, wake_at=deadline)
                self.assertEqual(result["status"], "ok", result)
                self.assertIsInstance(result["nodes"][0]["wake_at"], (int, float))
        properties = dag_tool.OMH_DAG_SCHEMA["parameters"]["properties"]
        self.assertIn("parked", properties["outcome"]["enum"])
        self.assertEqual(properties["handle"]["maxLength"], 120)
        self.assertEqual(set(properties["wake_at"]["type"]), {"string", "number"})

    def test_park_limit_requires_settle(self) -> None:
        for outcome in ("accepted", "failed", "blocked"):
            with self.subTest(outcome=outcome), homes() as home:
                slots_table(home)
                moment = time.time()
                with patch.object(dag_tool.time, "time", return_value=moment):
                    call(action="define", run="feat", nodes=[node("a")])
                for count in range(3):
                    now = moment + count * 60
                    with patch.object(dag_tool.time, "time", return_value=now):
                        result = call(action="settle", run="feat", node="a", outcome="parked",
                                      handle=f"proc:{count}", wake_at=now + 60)
                    self.assertEqual(result["status"], "ok", result)
                    with patch.object(dag_tool.time, "time", return_value=now + 60):
                        self.assertIn("a", calls_by_node(call(action="ready", run="feat")))
                stored = record_of(home)
                with patch.object(dag_tool.time, "time", return_value=moment + 180):
                    refused = call(action="settle", run="feat", node="a", outcome="parked",
                                   handle="proc:fourth", wake_at=moment + 240)
                    self.assertEqual(refused.get("reason"), "park_limit_reached", refused)
                    self.assertEqual(record_of(home), stored)
                    handoff(home, "feat", "a")
                    settled = call(action="settle", run="feat", node="a", outcome=outcome)
                self.assertEqual(settled["status"], "ok", settled)
                self.assertEqual(states(settled)["a"], outcome)
                self.assertEqual(dag_run.cycles_left(record_of(home), "a"), dag_run.MAX_REPAIR_CYCLES)

    def test_parked_reoffered_after_wake_at(self) -> None:
        with homes() as home:
            slots_table(home)
            moment = time.time()
            with patch.object(dag_tool.time, "time", return_value=moment):
                call(action="define", run="feat", nodes=[node("a"), node("b", depends_on=("a",))])
                child_started(home, "feat", "a", now=moment)
                parked = call(action="settle", run="feat", node="a", outcome="parked",
                              handle="ci:run-987", wake_at=moment + 60)
            self.assertEqual(parked["status"], "ok", parked)
            for offset in (0, 59):
                with patch.object(dag_tool.time, "time", return_value=moment + offset):
                    self.assertFalse(call(action="ready", run="feat")["calls"])
            with patch.object(dag_tool.time, "time", return_value=moment + 60):
                ready = call(action="ready", run="feat")
                repeat = call(action="ready", run="feat")
            self.assertIn("a", calls_by_node(ready), ready)
            self.assertIn("ci:run-987", calls_by_node(ready)["a"]["context"])
            self.assertEqual(states(ready), {"a": "handed_out", "b": "waiting"})
            self.assertFalse(repeat["calls"])
            attempts = record_of(home)["nodes"][0]["attempts"]
            self.assertEqual(len(attempts), 2)
            self.assertEqual(attempts[0]["outcome"], "parked")
            self.assertEqual(attempts[1]["n"], 2)
            self.assertEqual(attempts[1]["outcome"], "")

    def test_parked_does_not_spend_repair_cycle(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("a"), node("b", depends_on=("a",))])
            deadline = time.time() + 60
            parked = call(action="settle", run="feat", node="a", outcome="parked",
                          handle="proc:123", wake_at=deadline)
            self.assertEqual(parked["status"], "ok", parked)
            stored = record_of(home)
            self.assertEqual(dag_run.cycles_left(stored, "a"), dag_run.MAX_REPAIR_CYCLES)
            self.assertEqual(parked["state"], "running")
            self.assertEqual(states(parked), {"a": "parked", "b": "waiting"})
            self.assertEqual(parked["counts"]["failed"], 0)
            self.assertEqual(parked["counts"]["parked"], 1)
            self.assertIn("1 parked", parked["status_line"])
            row = next(row for row in parked["nodes"] if row["id"] == "a")
            self.assertEqual((row["handle"], row["wake_at"]), ("proc:123", deadline))
            self.assertEqual(stored["nodes"][0]["attempts"][-1]["handle"], "proc:123")
            self.assertFalse(parked["calls"])
            refused = call(action="repair", run="feat", node="a", nodes=[node("fix")])
            self.assertEqual(refused["reason"], "not_failed")
            self.assertEqual(record_of(home), stored)

    def test_provider_retry_after_wake_keeps_the_resume_handle(self) -> None:
        with homes() as home:
            slots_table(home)
            moment = time.time()
            with patch.object(dag_tool.time, "time", return_value=moment):
                call(action="define", run="feat", nodes=[node("a")])
                call(action="settle", run="feat", node="a", outcome="parked",
                     handle="ci:123", wake_at=moment + 60)
            with patch.object(dag_tool.time, "time", return_value=moment + 60):
                wake = call(action="ready", run="feat")
                retry = call(action="settle", run="feat", node="a", outcome="failed", provider_error=True)
            wake_context = calls_by_node(wake)["a"]["context"]
            retry_context = calls_by_node(retry)["a"]["context"]
            self.assertIn("ci:123", wake_context)
            self.assertEqual(retry["settled"], {"node": "a", "outcome": "retry"})
            self.assertEqual([row["route"]["action"] for row in retry["calls"]], ["fallback"])
            self.assertIn("ci:123", retry_context)
            # One resume instruction carrying the one handle; the goal is not restated as a second work order.
            self.assertEqual(retry_context.count("Resume the still-running wait"), 1)
            self.assertEqual(retry_context.count("ci:123"), 1)
            self.assertEqual(retry_context.count(PROMPT), 1)
            attempts = record_of(home)["nodes"][0]["attempts"]
            self.assertEqual([attempt.get("resume_handle") for attempt in attempts], [None, "ci:123", "ci:123"])
            self.assertEqual(attempts[-1]["fallback"], True)

    def test_a_resume_handle_dies_with_the_attempt_that_held_it(self) -> None:
        # Two parks in a row keep the latest identity, not the first one.
        chained = {"attempts": [
            {"n": 1, "outcome": "parked", "handle": "ci:one"},
            {"n": 2, "outcome": "retry", "resume_handle": "ci:one"},
            {"n": 3, "outcome": "parked", "handle": "ci:two"},
            {"n": 4, "outcome": "retry", "resume_handle": "ci:two"},
        ]}
        self.assertEqual(dag_run.hand_out(chained, "ready", 100).get("resume_handle"), "ci:two")
        # Once the resumed attempt settles, later work on the node starts fresh.
        settled = {"attempts": [
            {"n": 1, "outcome": "parked", "handle": "ci:one"},
            {"n": 2, "outcome": "retry", "resume_handle": "ci:one"},
            {"n": 3, "outcome": "failed", "provider_error": False},
        ]}
        self.assertNotIn("resume_handle", dag_run.hand_out(settled, "ready", 200))
        # A provider retry that never resumed a wait carries no identity either.
        plain = {"attempts": [{"n": 1, "outcome": "retry", "provider_error": True}]}
        self.assertNotIn("resume_handle", dag_run.hand_out(plain, "ready", 300))


class ComposedDagLifecycleTests(unittest.TestCase):
    """Composition boundary: prepared worker guidance, not evidence comparison or live compliance."""

    def test_oneshot_refusal_preserves_the_parked_baseline_graph(self) -> None:
        with homes() as home, patch.object(dag_tool, "_single_query_session", return_value=False):
            slots_table(home)
            moment = time.time()
            definitions = [node("baseline", role="baseline"), node("api", depends_on=("baseline",)),
                           node("verify", role="verify", depends_on=("api",))]
            with patch.object(dag_tool.time, "time", return_value=moment):
                defined = call(action="define", run="feat", nodes=definitions)
                self.assertEqual(defined["status"], "ok", defined)
                parked = call(action="settle", run="feat", node="baseline", outcome="parked",
                              handle="ci:baseline-oneshot", wake_at=moment + 60)
                self.assertEqual(states(parked)["baseline"], "parked")
                path = dag_run.record_path(home.omh, PARENT, "feat")
                before = path.read_bytes()
                (home.hermes / "config.yaml").write_text("delegation:\n  oneshot_max_children: 1\n", encoding="utf-8")
                with patch.object(dag_tool, "_single_query_session", return_value=True):
                    refused = call(action="define", run="feat", nodes=definitions)
                self.assertEqual((refused["status"], refused["reason"]), ("refused", "oneshot_budget_exceeded"))
                self.assertEqual(path.read_bytes(), before)
                cancelled = call(action="cancel", run="feat")
                self.assertEqual(states(cancelled), {"baseline": "cancelled", "api": "cancelled", "verify": "cancelled"})
                self.assertFalse(call(action="ready", run="feat")["calls"])

    def test_marked_baseline_park_wake_producer_verifier_and_cancel(self) -> None:
        with homes() as home:
            slots_table(home)
            moment = time.time()
            definitions = [node("baseline", role="baseline", label="Capture baseline", scope=("baseline.txt",)),
                           node("api", depends_on=("baseline",), scope=("api.py",)),
                           node("verify", role="verify", label="Verify full suite", depends_on=("api",),
                                prompt=PROMPT + "\nRun the full suite.")]
            with patch.object(dag_tool.time, "time", return_value=moment):
                defined = call(action="define", run="feat", nodes=definitions,
                               goal="Deliver the change with comparable baseline evidence and full-suite green.")
                self.assertEqual(defined["status"], "ok", defined)
                self.assertEqual(set(calls_by_node(defined)), {"baseline"})
                self.assertNotIn("verify_without_baseline:verify", defined["lint"])
                child_started(home, "feat", "baseline", now=moment)
                parked = call(action="settle", run="feat", node="baseline", outcome="parked",
                              handle="ci:baseline-123", wake_at=moment + 60)
                self.assertEqual(states(parked), {"baseline": "parked", "api": "waiting", "verify": "waiting"})
                self.assertFalse(parked["calls"])
            with patch.object(dag_tool.time, "time", return_value=moment + 59):
                self.assertFalse(call(action="ready", run="feat")["calls"])
            with patch.object(dag_tool.time, "time", return_value=moment + 60):
                wake = call(action="ready", run="feat")
                self.assertEqual(set(calls_by_node(wake)), {"baseline"})
                context = calls_by_node(wake)["baseline"]["context"]
                self.assertEqual(context.count("Resume the still-running wait: ci:baseline-123"), 1)
                self.assertEqual(context.count(PROMPT), 1)
                self.assertFalse(call(action="ready", run="feat")["calls"])
                record = record_of(home)
                self.assertEqual(dag_run.cycles_left(record, "baseline"), dag_run.MAX_REPAIR_CYCLES)
                baseline_path = handoff(home, "feat", "baseline", "Pinned base; comparable command/env; test id/signature.").resolve()
                accepted = call(action="settle", run="feat", node="baseline", outcome="accepted")
                self.assertEqual(set(calls_by_node(accepted)), {"api"})
                self.assertIn(str(baseline_path), calls_by_node(accepted)["api"]["context"])
                self.assertNotIn("Baseline:", calls_by_node(accepted)["api"]["context"])
                handoff(home, "feat", "api")
                produced = call(action="settle", run="feat", node="api", outcome="accepted")
                self.assertEqual(set(calls_by_node(produced)), {"verify"})
                verify_context = calls_by_node(produced)["verify"]["context"]
                lines = [line for line in verify_context.splitlines() if line.startswith("Baseline:")]
                self.assertEqual(len(lines), 1)
                line = lines[0]
                self.assertIn(str(baseline_path), line)
                for guard in ("same test id and assertion/error signature", "comparable command and environment",
                              "pinned base and candidate revisions", "same-id failure that changed", "missing evidence",
                              "skipped or reduced coverage", "collection/execution/exit errors",
                              "security or mandatory gates", "never exempt: fail them",
                              "does not make an unmet full-suite-green goal done"):
                    self.assertIn(guard, line)
                cancelled = call(action="cancel", run="feat")
                self.assertEqual(states(cancelled)["verify"], "cancelled")
                self.assertFalse(call(action="ready", run="feat")["calls"])
                refused = call(action="settle", run="feat", node="verify", outcome="accepted")
                self.assertEqual(refused["reason"], "run_cancelled")
                self.assertEqual(states(cancelled)["baseline"], "accepted")


class RepairDataFlowTests(unittest.TestCase):
    def test_a_dependent_reads_the_repair_groups_handoff_not_the_failed_nodes(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("a", scope=("a.py",)), node("b", depends_on=("a",)),
                                                     node("verify", role="verify", depends_on=("b",), label="Verify")])
            call(action="settle", run="feat", node="a", outcome="blocked", reason="no key")
            call(action="repair", run="feat", node="a", nodes=[node("a-fix", scope=("a.py",))])
            handoff(home, "feat", "a-fix")
            result = call(action="settle", run="feat", node="a-fix", outcome="accepted")
            context = calls_by_node(result)["b"]["context"]
        read_first = next(line for line in context.splitlines() if line.startswith("Read first:"))
        paths = read_first.removeprefix("Read first: ").split(". A missing file")[0].split(", ")
        self.assertEqual([Path(path).name for path in paths], ["a-fix.md"])

    def test_a_repair_may_write_what_the_failed_nodes_dependents_write(self) -> None:
        # b waits for a, and a waits for its repair group: the order is already there, so the scope is not refused.
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("a", scope=("x.py",)),
                                                     node("b", depends_on=("a",), scope=("x.py",))])
            call(action="settle", run="feat", node="a", outcome="failed")
            repaired = call(action="repair", run="feat", node="a", nodes=[node("a-fix", scope=("x.py",))])
        self.assertEqual(repaired["status"], "ok", repaired)
        self.assertEqual([c["nodes"] for c in repaired["calls"]], [["a-fix"]])


class ReVerificationTests(unittest.TestCase):
    """A failed verification is verified again: its repair never stands in for it."""

    def test_verifier_receives_whole_goal_acceptance_instructions_after_reload(self) -> None:
        goal = "Keep the source engine and craft quality, not only a working package."
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", goal=goal, nodes=[node("api", scope=("a.py",)),
                 node("verify", role="verify", depends_on=("api",), label="Verify the feature")])
            handoff(home, "feat", "api", "Package tests pass; output comparison not run.")
            result = call(action="settle", run="feat", node="api", outcome="accepted")
            context = calls_by_node(result)["verify"]["context"]
        self.assertIn(f"Run goal (saved):\n{goal}\n", context)
        self.assertIn("Check the complete run goal, not only this node's local VERIFY.", context)
        self.assertIn("Name each unmet or unobserved goal criterion; producer claims are not verification evidence.",
                      context)

    def _failed_verify(self, home) -> None:
        slots_table(home)
        call(action="define", run="feat", nodes=[node("api", scope=("a.py",)),
                                                 node("verify", role="verify", depends_on=("api",), label="Verify the feature")])
        handoff(home, "feat", "api")
        call(action="settle", run="feat", node="api", outcome="accepted")
        call(action="settle", run="feat", node="verify", outcome="failed", reason="2 tests red")

    def test_a_repaired_verification_runs_again_before_the_run_is_done(self) -> None:
        with homes() as home:
            self._failed_verify(home)
            repaired = call(action="repair", run="feat", node="verify", nodes=[node("fix", scope=("a.py",))])
            handoff(home, "feat", "fix")
            fixed = call(action="settle", run="feat", node="fix", outcome="accepted")
            rerun = calls_by_node(fixed).get("verify")
            handoff(home, "feat", "verify")
            done = call(action="settle", run="feat", node="verify", outcome="accepted")
            stored = record_of(home)
        self.assertNotIn("verification_misses:fix", repaired["lint"])
        self.assertEqual(fixed["state"], "running")
        self.assertIsNotNone(rerun, fixed)
        self.assertTrue(rerun["goal"].endswith(" [dag:feat/verify]"))
        self.assertEqual(states(fixed)["verify"], "handed_out")
        self.assertEqual(done["state"], "done")
        self.assertEqual(states(done)["verify"], "accepted")
        verify = next(item for item in stored["nodes"] if item["id"] == "verify")
        self.assertEqual([attempt["outcome"] for attempt in verify["attempts"]], ["failed", "accepted"])

    def test_a_failed_reverification_takes_the_second_cycle_then_the_run_stops(self) -> None:
        with homes() as home:
            self._failed_verify(home)
            call(action="repair", run="feat", node="verify", nodes=[node("fix", scope=("a.py",))])
            handoff(home, "feat", "fix")
            call(action="settle", run="feat", node="fix", outcome="accepted")
            again = call(action="settle", run="feat", node="verify", outcome="failed", reason="1 test red")
            call(action="repair", run="feat", node="verify", nodes=[node("fix2", scope=("a.py",))])
            handoff(home, "feat", "fix2")
            call(action="settle", run="feat", node="fix2", outcome="accepted")
            last = call(action="settle", run="feat", node="verify", outcome="failed", reason="still red")
            refused = call(action="repair", run="feat", node="verify", nodes=[node("fix3")])
        self.assertEqual(again["state"], "needs_repair")
        self.assertEqual(last["state"], "stopped")
        self.assertEqual(last["open"], ["verify"])
        self.assertEqual(refused["reason"], "repair_limit_reached")

    def test_a_repaired_producer_still_stands_in_for_its_node(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("api", scope=("a.py",)),
                                                     node("verify", role="verify", depends_on=("api",), label="Verify")])
            call(action="settle", run="feat", node="api", outcome="failed")
            call(action="repair", run="feat", node="api", nodes=[node("api-fix", scope=("a.py",))])
            handoff(home, "feat", "api-fix")
            result = call(action="settle", run="feat", node="api-fix", outcome="accepted")
        self.assertEqual(states(result)["api"], "repaired")
        self.assertEqual(list(calls_by_node(result)), ["verify"])

    def test_repair_and_extend_return_the_lint(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("api", scope=("a.py",)),
                                                     node("verify", role="verify", depends_on=("api",), label="Verify")])
            call(action="settle", run="feat", node="api", outcome="failed")
            markerless = call(action="repair", run="feat", node="api", nodes=[node("api-fix", prompt="just fix it")])
            repaired = call(action="repair", run="feat", node="api", nodes=[node("api-fix", scope=("a.py",),
                                                                               prompt="TASK: just fix it")])
        self.assertEqual((markerless["status"], markerless["reason"]), ("refused", "prompt_markers_missing"))
        self.assertIn("missing_markers:api-fix:DELIVERABLE,SCOPE,VERIFY,STOP_WHEN", repaired["lint"])
        self.assertIn("topology", repaired)


class BlockedNodeTests(unittest.TestCase):
    def test_a_blocked_node_is_never_counted_done_and_holds_everything_below_it(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("a", scope=("a.py",)), node("b", depends_on=("a",)),
                                                     node("c", depends_on=("b",)), node("side")])
            handoff(home, "feat", "side")
            call(action="settle", run="feat", node="side", outcome="accepted")
            blocked = call(action="settle", run="feat", node="a", outcome="blocked", reason="no key")
        rows = {row["id"]: row for row in blocked["nodes"]}
        self.assertEqual(blocked["counts"]["done"], 1)
        self.assertEqual(blocked["counts"]["failed"], 1)
        self.assertEqual(blocked["state"], "needs_repair")
        self.assertEqual((rows["b"]["state"], rows["b"]["held_by"]), ("held", ["a"]))
        # Held through b: the failed node is an ancestor, not a parent.
        self.assertEqual((rows["c"]["state"], rows["c"]["held_by"]), ("held", ["a"]))
        self.assertFalse(blocked["calls"])


class AttemptBindingTests(unittest.TestCase):
    def test_a_retry_does_not_take_the_child_of_the_attempt_before_it(self) -> None:
        with homes() as home:
            slots_table(home)
            moment = time.time()
            with patch.object(dag_tool.time, "time", return_value=moment):
                call(action="define", run="feat", nodes=[node("a", scope=("a.py",))])
            child_started(home, "feat", "a", now=moment + 1)
            with patch.object(dag_tool.time, "time", return_value=moment + 60):
                retried = call(action="settle", run="feat", node="a", outcome="failed", provider_error=True)
        # The first attempt's child started before the retry was handed out: the retry has no child yet.
        self.assertEqual(states(retried)["a"], "handed_out")
        self.assertEqual(retried["calls"][0]["route"]["action"], "fallback")


class ProviderErrorTests(unittest.TestCase):
    def test_provider_error_is_a_bool_or_its_two_words(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("a"), node("b"), node("c")])
            word_false = call(action="settle", run="feat", node="a", outcome="failed", provider_error="false")
            word_true = call(action="settle", run="feat", node="b", outcome="failed", provider_error="true")
            other = call(action="settle", run="feat", node="c", outcome="failed", provider_error="yes")
        self.assertEqual(word_false["settled"]["outcome"], "failed")
        self.assertEqual(word_true["settled"]["outcome"], "retry")
        self.assertEqual(other["reason"], "invalid_provider_error")


class TaskBudgetTests(unittest.TestCase):
    def test_calls_carry_no_more_tasks_than_the_budget_and_hold_the_rest(self) -> None:
        with homes() as home:
            raw = [node("a"), node("b"), node("c", category="writing"), node("d", category="writing")]
            record = dag_run.new_record(PARENT, "feat", None, None, raw, 100.0)
            derived = dag_run.derive(record, [], 100.0)
            calls, held = dag_run.calls_for(record, derived, free_slots=10, per_call=10, omh_home=home.omh,
                                            now=100.0, task_budget=3)
        self.assertEqual(sum(len(item["tasks"]) for item in calls), 3)
        self.assertEqual([item["nodes"] for item in calls], [["a", "b"], ["c"]])
        self.assertEqual(held, ["d"])
        attempts = {str(item["id"]): len(item.get("attempts") or []) for item in record["nodes"]}
        self.assertEqual(attempts, {"a": 1, "b": 1, "c": 1, "d": 0})

    def test_no_budget_is_the_slot_rule_alone(self) -> None:
        with homes() as home:
            record = dag_run.new_record(PARENT, "feat", None, None, [node("a"), node("b"), node("c")], 100.0)
            derived = dag_run.derive(record, [], 100.0)
            calls, held = dag_run.calls_for(record, derived, free_slots=1, per_call=2, omh_home=home.omh, now=100.0)
            empty, all_held = dag_run.calls_for(record, dag_run.derive(record, [], 100.0), free_slots=10,
                                                per_call=10, omh_home=home.omh, now=100.0, task_budget=0)
        self.assertEqual(([item["nodes"] for item in calls], held), ([["a", "b"]], ["c"]))
        self.assertEqual((empty, all_held), ([], ["c"]))


class RecordStorageTests(unittest.TestCase):
    def test_the_record_is_private_from_its_first_byte(self) -> None:
        with homes() as home:
            slots_table(home)
            # chmod never runs: the file must still be created 0600, not widened by the umask and narrowed later.
            with patch.object(dag_run.os, "chmod"):
                call(action="define", run="feat", nodes=[node("a")])
            mode = dag_run.record_path(home.omh, PARENT, "feat").stat().st_mode & 0o777
        if os.name != "nt":  # Windows has no POSIX mode bits to check
            self.assertEqual(mode, 0o600)

    def test_a_record_too_large_or_holding_a_cycle_is_not_read(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("a"), node("b", depends_on=("a",))])
            path = dag_run.record_path(home.omh, PARENT, "feat")
            good = json.loads(path.read_text(encoding="utf-8"))
            self.assertIsNotNone(dag_run.read_run(path))
            cyclic = json.loads(json.dumps(good))
            cyclic["nodes"][0]["depends_on"] = ["b"]
            path.write_text(json.dumps(cyclic), encoding="utf-8")
            self.assertIsNone(dag_run.read_run(path))
            padded = json.loads(json.dumps(good))
            padded["pad"] = "x" * dag_run.MAX_RECORD_BYTES
            path.write_text(json.dumps(padded), encoding="utf-8")
            self.assertIsNone(dag_run.read_run(path))

    def test_a_full_session_drops_its_oldest_finished_run_for_a_new_one(self) -> None:
        with homes() as home:
            slots_table(home)
            for index in range(dag_run.MAX_RUNS_PER_SESSION):
                call(action="define", run=f"r{index}", nodes=[node("a")])
                if index == 0:
                    call(action="cancel", run="r0")
            newest = call(action="define", run="newest", nodes=[node("a")])
            runs = sorted(record["run"] for record, _path in dag_run.session_runs(home.omh, PARENT))
        self.assertEqual(newest["status"], "ok", newest)
        self.assertEqual(len(runs), dag_run.MAX_RUNS_PER_SESSION)
        self.assertNotIn("r0", runs)
        self.assertIn("newest", runs)

    def test_a_full_session_with_no_finished_run_refuses(self) -> None:
        with homes() as home:
            slots_table(home)
            for index in range(dag_run.MAX_RUNS_PER_SESSION):
                call(action="define", run=f"r{index}", nodes=[node("a")])
            refused = call(action="define", run="newest", nodes=[node("a")])
        self.assertEqual(refused["reason"], "too_many_runs")


class LimitTests(unittest.TestCase):
    def test_forty_eight_nodes_fit_and_forty_nine_do_not(self) -> None:
        with homes() as home:
            slots_table(home)
            fits = call(action="define", run="big", nodes=[node(f"n{index}") for index in range(dag_run.MAX_NODES)])
            over = call(action="define", run="bigger",
                        nodes=[node(f"n{index}") for index in range(dag_run.MAX_NODES + 1)])
        self.assertEqual(fits["status"], "ok", fits)
        self.assertEqual(over["reason"], "too_many_nodes")

    def test_one_node_needs_no_verification_node(self) -> None:
        self.assertNotIn("no_verification_node", dag_run.lint([dag_run._validated_node(node("a"))]))

    def test_the_configured_cap_wins_over_the_environment(self) -> None:
        with homes() as home:
            home.hermes.joinpath("config.yaml").write_text("delegation:\n  max_concurrent_children: 3\n")
            with patch.dict(os.environ, {dag_tool.MAX_CONCURRENT_ENV: "7"}):
                self.assertEqual(dag_tool.free_slots(home.hermes)["cap"], 3)
            home.hermes.joinpath("config.yaml").write_text("delegation:\n  other: 1\n")
            with patch.dict(os.environ, {dag_tool.MAX_CONCURRENT_ENV: "7"}):
                self.assertEqual(dag_tool.free_slots(home.hermes)["cap"], 7)


# Node labels from live dag-ulw records (2026-11-02) that the label guess read wrong: (id, label, the role the parent
# meant, the role the label guess gives, which is how a record stored before nodes carried a role still reads).
MEASURED_LABELS = (
    ("indep-verify", "independent verification vs baseline", "verify", "baseline"),
    ("full-check", "Full suite + review vs baseline", "verify", "baseline"),
    ("typecheck", "typecheck + pnpm test on the fix branch", "verify", "build"),
    ("frontend", "frontend observe-each-change + visual-qa", "build", "verify"),
    ("motion", "visual-qa motion continuity reference", "build", "verify"),
)


def stored(definition: dict) -> dict:
    """A node as a record written before nodes carried a role holds it: the validated shape without ``role``."""
    validated = dag_run.new_record(PARENT, "old", "", "", [{**definition, "role": "build"}], time.time())["nodes"][0]
    validated.pop("role")
    validated.pop("role_guess", None)
    return validated


def settled(record: dict, node_id: str, outcome: str, *, unread: str = "") -> None:
    """Hand ``node_id`` out and settle it, as `ready` and `settle` do; ``unread``: its handoff could not be read."""
    now = time.time()
    target = next(item for item in record["nodes"] if item["id"] == node_id)
    dag_run.hand_out(target, dag_run.derive(record, [], now)[node_id]["state"], now)
    dag_run.settle(record, dag_run.derive(record, [], now), node_id, outcome, "", False,
                   read_handoff=lambda: (not unread, unread), now=now)


def finished(record: dict) -> tuple[str, str, list[str]]:
    derived = dag_run.derive(record, [], time.time())
    return (dag_run.run_state(record, derived), *dag_run.goal_verdict(record, derived))


class NodeRoleTests(unittest.TestCase):
    def test_a_declared_role_classifies_each_measured_label(self) -> None:
        for node_id, label, meant, _guess in MEASURED_LABELS:
            with self.subTest(label=label):
                declared = dag_run.new_record(PARENT, "feat", "", "", [
                    node(node_id, label=label, scope=() if meant == "verify" else ("a.py",), role=meant),
                ], time.time())["nodes"][0]
                self.assertEqual(dag_run.node_role(declared), meant)
                self.assertEqual(dag_run.is_verification(declared), meant == "verify")
                self.assertEqual(dag_run.is_coding(declared), meant == "build")
                self.assertNotIn("role_guess", declared)

    def test_a_stored_node_without_a_role_reads_as_its_label_did(self) -> None:
        for node_id, label, _meant, guess in MEASURED_LABELS:
            with self.subTest(label=label):
                old = stored(node(node_id, label=label, scope=("a.py",)))
                self.assertEqual(dag_run.node_role(old), guess)
                self.assertEqual(dag_run.is_verification(old), guess == "verify")
                self.assertEqual(dag_run.is_baseline(old), guess == "baseline")
                self.assertEqual(dag_run.is_coding(old), guess == "build")
        self.assertEqual(dag_run.node_role(stored(node("rev", label="Review the diff"))), "review")

    def test_a_new_node_without_a_role_is_build_and_its_guess_is_only_advice(self) -> None:
        # A node that reads like a check and writes files is refused (`role_required`); these write nothing.
        definitions = [node(node_id, label=label, scope=() if guess == "verify" else (f"{node_id}.py",))
                       for node_id, label, _m, guess in MEASURED_LABELS]
        record = dag_run.new_record(PARENT, "feat", "", "", definitions, time.time())
        self.assertEqual({dag_run.node_role(item) for item in record["nodes"]}, {"build"})
        self.assertEqual([item for item in record["lint"] if item.startswith("role_guess:")],
                         [f"role_guess:{node_id}={guess}" for node_id, _l, _m, guess in MEASURED_LABELS
                          if guess != "build"])
        self.assertIn("no_verification_node", record["lint"])
        # The parent named the role: no hint, whatever the label reads like.
        named = dag_run.new_record(PARENT, "feat", "", "", [
            node("frontend", label="frontend observe-each-change + visual-qa", scope=("ui.py",), role="build"),
            node("check", label="typecheck + pnpm test on the fix branch", depends_on=("frontend",), role="verify"),
        ], time.time())
        self.assertEqual(named["lint"], ["no_review_node"])

    def test_a_file_writing_node_that_reads_like_a_check_must_name_its_role(self) -> None:
        for label, guess in (("Verify: typecheck + tests", "verify"), ("QA the build", "verify"),
                             ("Review the diff", "review")):
            with self.subTest(label=label):
                with self.assertRaises(dag_run.DagRefusal) as refused:
                    dag_run.new_record(PARENT, "feat", "", "", [node("ui", label=label, scope=("ui.tsx",))], time.time())
                self.assertEqual(refused.exception.reason, "role_required")
                self.assertIn(f"Node ui writes files and its label opens like a {guess} node", refused.exception.say)
                built = dag_run.new_record(PARENT, "feat", "", "", [
                    node("ui", label=label, scope=("ui.tsx",), role="build")], time.time())
                checked = dag_run.new_record(PARENT, "feat", "", "", [
                    node("ui", label=label, scope=("ui.tsx",), role=guess)], time.time())
                self.assertEqual([unit["unit_id"] for unit in dag_tool.export_units(
                    built, dag_run.derive(built, [], time.time()), "codex")], ["ui"])
                with self.assertRaises(dag_run.DagRefusal) as native:
                    dag_tool.export_units(checked, dag_run.derive(checked, [], time.time()), "codex")
                self.assertEqual(native.exception.reason, "nothing_to_export")
        # Without a write scope it runs as a build node, and the lint names what the label reads like.
        quiet = dag_run.new_record(PARENT, "feat", "", "", [node("ui", label="Review the diff")], time.time())
        self.assertIn("role_guess:ui=review", quiet["lint"])
        with homes() as home:
            slots_table(home)
            first = call(action="define", run="feat", nodes=[node("check", label="Verify the build", scope=("r.md",))])
            self.assertEqual((first["status"], first["reason"]), ("refused", "role_required"))
            self.assertFalse(dag_run.record_path(home.omh, PARENT, "feat").exists())
            call(action="define", run="feat", nodes=[node("api", scope=("a.py",))])
            call(action="settle", run="feat", node="api", outcome="failed")
            call(action="define", run="done", nodes=[node("api", scope=("a.py",))])
            handoff(home, "done", "api")
            self.assertEqual(call(action="settle", run="done", node="api", outcome="accepted")["state"], "done")
            for run, action, extra in (("feat", "repair", {"node": "api"}), ("done", "extend", {})):
                before = dag_run.record_path(home.omh, PARENT, run).read_bytes()
                result = call(action=action, run=run, **extra,
                              nodes=[node("audit", label="Audit the fix", scope=("a.py",))])
                self.assertEqual((result["status"], result["reason"]), ("refused", "role_required"), action)
                self.assertEqual(dag_run.record_path(home.omh, PARENT, run).read_bytes(), before)

    def test_build_work_that_mentions_a_check_word_later_in_its_label_is_not_refused(self) -> None:
        for label, guess in (("Add input validation to the API", "verify"), ("Fix review comments", "review"),
                             ("Implement audit log table", "verify"), ("Add QA fixtures", "verify"),
                             ("frontend observe-each-change + visual-qa", "verify")):
            with self.subTest(label=label):
                record = dag_run.new_record(PARENT, "feat", "", "", [node("ui", label=label, scope=("ui.py",))],
                                            time.time())
                self.assertEqual(dag_run.node_role(record["nodes"][0]), "build")
                self.assertIn(f"role_guess:ui={guess}", record["lint"])

    def test_an_unknown_role_is_refused_and_the_record_is_untouched(self) -> None:
        with self.assertRaises(dag_run.DagRefusal) as refused:
            dag_run.new_record(PARENT, "feat", "", "", [node("api", role="tester")], time.time())
        self.assertEqual(refused.exception.reason, "invalid_role")
        with homes() as home:
            slots_table(home)
            first = call(action="define", run="feat", nodes=[node("api", role="verifier")])
            self.assertEqual((first["status"], first["reason"]), ("refused", "invalid_role"))
            self.assertFalse(dag_run.record_path(home.omh, PARENT, "feat").exists())
            call(action="define", run="feat", nodes=[node("api", scope=("a.py",)), node("check", depends_on=("api",))])
            call(action="settle", run="feat", node="api", outcome="failed")
            before = dag_run.record_path(home.omh, PARENT, "feat").read_bytes()
            for role in ("QA", "", 1, None):
                with self.subTest(role=role):
                    raw = node("api-fix", scope=("a.py",))
                    raw["role"] = role
                    refused_repair = call(action="repair", run="feat", node="api", nodes=[raw])
                    self.assertEqual((refused_repair["status"], refused_repair["reason"]), ("refused", "invalid_role"))
                    self.assertEqual(dag_run.record_path(home.omh, PARENT, "feat").read_bytes(), before)

    def test_a_stored_record_with_an_unknown_role_is_not_read(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("api")])
            path = dag_run.record_path(home.omh, PARENT, "feat")
            record = json.loads(path.read_text(encoding="utf-8"))
            record["nodes"][0]["role"] = "judge"
            path.write_text(json.dumps(record), encoding="utf-8")
            self.assertIsNone(dag_run.read_run(path))

    def test_a_run_stored_without_roles_defined_again_unchanged_is_the_same_run(self) -> None:
        definitions = [node("api", scope=("a.py",)), node("docs", depends_on=("api",), scope=("d.md",))]
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=definitions)
            path = dag_run.record_path(home.omh, PARENT, "feat")
            record = json.loads(path.read_text(encoding="utf-8"))
            for item in record["nodes"]:
                item.pop("role")
            path.write_text(json.dumps(record), encoding="utf-8")
            again = call(action="define", run="feat", nodes=definitions)
        self.assertEqual((again["status"], again.get("reused")), ("ok", True))

    def test_a_stored_run_with_a_check_labelled_writer_defined_again_unchanged_is_reused(self) -> None:
        definitions = [node("api", scope=("a.py",)),
                       node("verify", label="Verify the feature", depends_on=("api",), scope=("report.md",))]
        with homes() as home:
            slots_table(home)
            # Stored before nodes carried a role: written here as build (left out of the digest), then stripped.
            stored_as = [{**item, "role": "build"} for item in definitions]
            self.assertEqual(call(action="define", run="feat", nodes=stored_as)["status"], "ok")
            path = dag_run.record_path(home.omh, PARENT, "feat")
            record = json.loads(path.read_text(encoding="utf-8"))
            for item in record["nodes"]:
                item.pop("role")
            path.write_text(json.dumps(record), encoding="utf-8")
            again = call(action="define", run="feat", nodes=definitions)
            fresh = call(action="define", run="fresh", nodes=definitions)
        self.assertEqual((again["status"], again.get("reused")), ("ok", True))
        self.assertEqual((fresh["status"], fresh["reason"]), ("refused", "role_required"))

    def test_the_external_owner_takes_build_nodes_by_role_never_a_verify_node(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", [
            node("motion", label="visual-qa motion continuity reference", scope=("motion.ts",), role="build"),
            node("frontend", label="frontend observe-each-change + visual-qa", scope=("ui.tsx",), role="build"),
            node("check", label="Typecheck the branch", scope=("report.md",), role="verify"),
            node("diff", label="Look over the diff", scope=("notes.md",), role="review"),
        ], time.time())
        derived = dag_run.derive(record, [], time.time())
        self.assertEqual([unit["unit_id"] for unit in dag_tool.export_units(record, derived, "codex")],
                         ["motion", "frontend"])


# Role-less writers whose label reads like a check past its first word (2026-11-02 review round): not refused, kept
# native. (label, the guess the node carries.)
CHECK_LABELLED_WRITERS = (
    ("Re-verify the fix", "verify"),
    ("Final verification pass", "verify"),
    ("Re-review the diff", "review"),
    ("independent verification vs baseline", "baseline"),
    ("Double-check the migration", "verify"),
    # Build work that reads the same way: native too, until the parent names role=build.
    ("Add input validation to the API", "verify"),
)


def exported(record: dict) -> list[str]:
    return [unit["unit_id"] for unit in dag_tool.export_units(record, dag_run.derive(record, [], time.time()), "codex")]


class CheckLabelledWriterTests(unittest.TestCase):
    """A role-less writer that reads like a check runs as a native build node; a node named build is exported.

    Mutation: export a node carrying ``role_guess``, drop the double-check guess, put the guess in the digest, or read
    a stored node without the guess differently.
    """

    def test_a_role_less_writer_that_reads_like_a_check_stays_native_and_is_still_a_producer(self) -> None:
        for label, guess in CHECK_LABELLED_WRITERS:
            with self.subTest(label=label):
                record = dag_run.new_record(PARENT, "feat", "", "", [
                    node("api", scope=("a.py",)), node("check", label=label, depends_on=("api",), scope=("c.py",)),
                ], time.time())
                check = record["nodes"][1]
                self.assertEqual((dag_run.node_role(check), check.get("role_guess")), ("build", guess))
                self.assertFalse(dag_run.is_coding(check))
                self.assertTrue(dag_run.is_producer(check))
                self.assertIn(f"role_guess:check={guess}", record["lint"])
                self.assertEqual(exported(record), ["api"])
                named = dag_run.new_record(PARENT, "feat", "", "", [
                    node("api", scope=("a.py",)),
                    node("check", label=label, depends_on=("api",), scope=("c.py",), role="build"),
                ], time.time())
                self.assertNotIn("role_guess", named["nodes"][1])
                self.assertEqual(exported(named), ["api", "check"])

    def test_a_failed_writer_guessed_as_verify_runs_again_after_its_repair(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", [
            node("api", scope=("a.py",)), node("check", label="Re-verify the fix", depends_on=("api",), scope=("c.py",)),
            node("gate", depends_on=("check",), role="verify"),
        ], time.time())
        settled(record, "api", "accepted")
        settled(record, "check", "failed")
        dag_run.repair(record, dag_run.derive(record, [], time.time()), "check",
                       [node("fix", depends_on=("api",), scope=("a.py",))], time.time())
        settled(record, "fix", "accepted")
        self.assertEqual(dag_run.derive(record, [], time.time())["check"]["state"], "ready")
        settled(record, "check", "accepted")
        self.assertEqual(finished(record)[:2], ("running", "unverified"))
        settled(record, "gate", "accepted")
        self.assertEqual(finished(record), ("done", "verified", []))
        # A failed build or a role-less writer guessed as review is repaired, not run again.
        for label in ("Node check", "Re-review the diff"):
            with self.subTest(label=label):
                other = dag_run.new_record(PARENT, "feat", "", "", [
                    node("api", scope=("a.py",)), node("check", label=label, depends_on=("api",), scope=("c.py",)),
                ], time.time())
                settled(other, "api", "accepted")
                settled(other, "check", "failed")
                dag_run.repair(other, dag_run.derive(other, [], time.time()), "check",
                               [node("fix", depends_on=("api",), scope=("a.py",))], time.time())
                settled(other, "fix", "accepted")
                self.assertEqual(dag_run.derive(other, [], time.time())["check"]["state"], "repaired")

    def test_a_writer_guessed_as_verify_alone_leaves_the_goal_unverified(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", [
            node("api", scope=("a.py",)), node("check", label="Re-verify the fix", depends_on=("api",), scope=("c.py",)),
        ], time.time())
        settled(record, "api", "accepted")
        settled(record, "check", "accepted")
        self.assertEqual(finished(record), ("done", "unverified", ["no_verification_node"]))

    def test_double_check_is_guessed_only_for_a_new_node(self) -> None:
        old = stored(node("mig", label="Double-check the migration", scope=("m.py",)))
        self.assertEqual(dag_run.node_role(old), "build")
        self.assertTrue(dag_run.is_coding(old))

    def test_a_stored_build_node_without_the_guess_reads_exactly_as_before(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", [
            node("api", scope=("a.py",)), node("check", label="Re-verify the fix", depends_on=("api",), scope=("c.py",)),
        ], time.time())
        record["nodes"][1].pop("role_guess")
        self.assertTrue(dag_run.is_coding(record["nodes"][1]))
        self.assertEqual(exported(record), ["api", "check"])

    def test_the_guess_leaves_the_digest_alone_and_a_redefine_is_reused(self) -> None:
        definitions = [node("api", scope=("a.py",)),
                       node("check", label="Re-verify the fix", depends_on=("api",), scope=("c.py",))]
        record = dag_run.new_record(PARENT, "feat", "", "", definitions, time.time())
        bare = [{key: value for key, value in item.items() if key != "role_guess"} for item in record["nodes"]]
        self.assertEqual(record["digest"], dag_run.definition_digest(bare))
        named = dag_run.new_record(PARENT, "feat", "", "", [{**item, "role": "build"} for item in definitions],
                                   time.time())
        self.assertEqual(record["digest"], named["digest"])
        with homes() as home:
            slots_table(home)
            self.assertEqual(call(action="define", run="feat", nodes=definitions)["status"], "ok")
            # A record stored before the guess kept the node native: the same node, without the field.
            path = dag_run.record_path(home.omh, PARENT, "feat")
            stored_record = json.loads(path.read_text(encoding="utf-8"))
            stored_record["nodes"][1].pop("role_guess")
            path.write_text(json.dumps(stored_record), encoding="utf-8")
            again = call(action="define", run="feat", nodes=definitions)
        self.assertEqual((again["status"], again.get("reused")), ("ok", True))


class ReviewLintTests(unittest.TestCase):
    """`no_review_node`: a build node writes code and no node reviews it. Advice only.

    Mutation: name it for a one-node run, a docs-only scope or a run with a review node, or let it move the run's
    state or goal verdict.
    """

    def test_a_code_writing_run_with_no_review_node_is_linted_and_still_verified(self) -> None:
        for scope in (("src/api.py",), ("src/",), ("docs/api.md", "src/api.py"), ("src/docs/gen.py",),
                      ("changelog.py",)):
            with self.subTest(scope=scope):
                record = dag_run.new_record(PARENT, "feat", "", "", [
                    node("api", scope=scope), node("check", depends_on=("api",), role="verify"),
                ], time.time())
                self.assertIn("no_review_node", record["lint"])
                settled(record, "api", "accepted")
                settled(record, "check", "accepted")
                self.assertEqual(finished(record), ("done", "verified", []))

    def test_no_finding_with_a_review_node_a_docs_only_scope_or_one_node(self) -> None:
        cases = {
            "review node": [node("api", scope=("src/api.py",)),
                            node("diff", label="Look over the diff", depends_on=("api",), role="review"),
                            node("check", depends_on=("api", "diff"), role="verify")],
            "docs only": [node("docs", scope=("docs/api.md", "README.rst", "NOTES.TXT")),
                          node("check", depends_on=("docs",), role="verify")],
            "docs directory": [node("docs", scope=("docs/", "./docs/guide/setup.png")),
                               node("check", depends_on=("docs",), role="verify")],
            "extensionless docs": [node("docs", scope=("CHANGELOG", "README", "pkg/LICENSE")),
                                   node("check", depends_on=("docs",), role="verify")],
            "review guessed from a label": [node("api", scope=("src/api.py",)),
                                            node("diff", label="Review the diff", depends_on=("api",))],
            "one node": [node("api", scope=("src/api.py",))],
            "only checks write code": [node("base", scope=("base.py",), role="baseline"),
                                       node("check", depends_on=("base",), scope=("report.py",), role="verify")],
        }
        for name, definitions in cases.items():
            with self.subTest(case=name):
                record = dag_run.new_record(PARENT, "feat", "", "", definitions, time.time())
                self.assertNotIn("no_review_node", record["lint"])


class GoalVerdictTests(unittest.TestCase):
    def test_a_run_with_no_verify_node_is_done_and_unverified(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", [
            node("api", scope=("a.py",)), node("ui", scope=("u.py",)),
        ], time.time())
        for node_id in ("api", "ui"):
            settled(record, node_id, "accepted")
        self.assertEqual(finished(record), ("done", "unverified", ["no_verification_node"]))
        lone = dag_run.new_record(PARENT, "lone", "", "", [node("api", scope=("a.py",))], time.time())
        settled(lone, "api", "accepted")
        self.assertEqual(finished(lone), ("done", "unverified", ["no_verification_node"]))

    def test_a_producer_no_verify_node_follows_leaves_the_goal_unverified(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", [
            node("api", scope=("a.py",)), node("ui", scope=("u.py",)),
            node("check", depends_on=("api",), role="verify"),
        ], time.time())
        for node_id in ("api", "ui", "check"):
            settled(record, node_id, "accepted")
        self.assertEqual(finished(record), ("done", "unverified", ["verification_misses:ui"]))

    def test_a_verify_node_whose_handoff_was_not_checked_does_not_verify(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", [
            node("api", scope=("a.py",)), node("check", depends_on=("api",), role="verify"),
        ], time.time())
        settled(record, "api", "accepted")
        settled(record, "check", "accepted", unread="docker terminal not up")
        self.assertEqual(finished(record), ("done", "unverified", ["handoff_not_checked:check"]))

    def test_every_producer_under_a_passing_verify_node_is_verified(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", [
            node("base", role="baseline", scope=("base.txt",)), node("api", depends_on=("base",), scope=("a.py",)),
            node("ui", scope=("u.py",)), node("diff", depends_on=("api", "ui"), role="review"),
            node("check", depends_on=("diff",), role="verify"),
        ], time.time())
        for node_id in ("base", "api", "ui", "diff"):
            settled(record, node_id, "accepted")
        self.assertEqual(finished(record), ("running", "unverified",
                                           ["verification_open:check", "verification_misses:api,base,ui"]))
        settled(record, "check", "accepted")
        self.assertEqual(finished(record), ("done", "verified", []))

    def test_a_failed_verify_repaired_and_run_again_to_acceptance_is_verified(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", [
            node("api", scope=("a.py",)), node("check", depends_on=("api",), role="verify"),
        ], time.time())
        settled(record, "api", "accepted")
        settled(record, "check", "failed")
        self.assertEqual(finished(record), ("needs_repair", "verify_failed", ["verify_failed:check"]))
        dag_run.repair(record, dag_run.derive(record, [], time.time()), "check",
                       [node("fix", depends_on=("api",), scope=("a.py",))], time.time())
        settled(record, "fix", "accepted")
        self.assertEqual(finished(record)[:2], ("running", "unverified"))
        settled(record, "check", "accepted")
        self.assertEqual(finished(record), ("done", "verified", []))

    def test_a_verify_node_failing_past_its_repair_cycles_is_verify_failed(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", [
            node("api", scope=("a.py",)), node("check", depends_on=("api",), role="verify"),
        ], time.time())
        settled(record, "api", "accepted")
        for cycle in range(1, dag_run.MAX_REPAIR_CYCLES + 1):
            settled(record, "check", "failed")
            dag_run.repair(record, dag_run.derive(record, [], time.time()), "check",
                           [node(f"fix{cycle}", depends_on=("api",), scope=("a.py",))], time.time())
            settled(record, f"fix{cycle}", "accepted")
        settled(record, "check", "blocked")
        self.assertEqual(finished(record), ("stopped", "verify_failed", ["verify_failed:check"]))

    def test_a_stored_run_without_roles_keeps_its_verification_node(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", [
            node("api", scope=("a.py",)), node("verify", depends_on=("api",), label="Verify the feature"),
        ], time.time())
        for item in record["nodes"]:
            item.pop("role")
            item.pop("role_guess", None)
        settled(record, "api", "accepted")
        settled(record, "verify", "failed")
        dag_run.repair(record, dag_run.derive(record, [], time.time()), "verify",
                       [node("fix", depends_on=("api",), scope=("a.py",))], time.time())
        settled(record, "fix", "accepted")
        # A verification root runs again after its repair, as it did before nodes carried a role.
        self.assertEqual(dag_run.derive(record, [], time.time())["verify"]["state"], "ready")
        settled(record, "verify", "accepted")
        self.assertEqual(finished(record), ("done", "verified", []))

    def test_the_tool_says_the_verdict_and_asks_for_a_verify_node_while_rounds_are_left(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("api", scope=("a.py",)), node("ui", scope=("u.py",))])
            handoff(home, "feat", "api")
            call(action="settle", run="feat", node="api", outcome="accepted")
            running = call(action="status", run="feat")
            handoff(home, "feat", "ui")
            done = call(action="settle", run="feat", node="ui", outcome="accepted")
            status = call(action="status", run="feat")
            self.assertNotIn("verdict", running)
            for result in (done, status):
                self.assertEqual((result["state"], result["verdict"], result["verdict_reasons"]),
                                 ("done", "unverified", ["no_verification_node"]))
                self.assertIn("role=verify", result["say"])
                self.assertIn("omh_dag action=extend", result["say"])
                self.assertIn("every producer (api, ui)", result["say"])
                self.assertNotIn("otherwise report the goal met", result["say"])
            extended = call(action="extend", run="feat", nodes=[
                node("check", depends_on=("api", "ui"), role="verify")])
            self.assertEqual(extended["status"], "ok", extended)
            handoff(home, "feat", "check")
            verified = call(action="settle", run="feat", node="check", outcome="accepted")
        self.assertEqual((verified["state"], verified["verdict"], verified["verdict_reasons"]), ("done", "verified", []))
        self.assertIn("report the goal met", verified["say"])

    def test_with_no_round_left_the_tool_says_to_report_the_goal_unverified(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("api", scope=("a.py",))])
            handoff(home, "feat", "api")
            call(action="settle", run="feat", node="api", outcome="accepted")
            for round_number in range(dag_run.MAX_EXTEND_ROUNDS):
                extra = f"more{round_number}"
                call(action="extend", run="feat", nodes=[node(extra, depends_on=("api",))])
                handoff(home, "feat", extra)
                done = call(action="settle", run="feat", node=extra, outcome="accepted")
        self.assertEqual((done["state"], done["verdict"], done["extend_rounds_left"]), ("done", "unverified", 0))
        self.assertIn("Report the goal as unverified", done["say"])
        self.assertNotIn("action=extend", done["say"])

    def test_a_stopped_run_carries_its_verdict(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("api", scope=("a.py",)),
                                                     node("check", depends_on=("api",), role="verify")])
            handoff(home, "feat", "api")
            call(action="settle", run="feat", node="api", outcome="accepted")
            for cycle in range(1, dag_run.MAX_REPAIR_CYCLES + 1):
                call(action="settle", run="feat", node="check", outcome="failed")
                call(action="repair", run="feat", node="check", nodes=[node(f"fix{cycle}", scope=("a.py",))])
                handoff(home, "feat", f"fix{cycle}")
                call(action="settle", run="feat", node=f"fix{cycle}", outcome="accepted")
            stopped = call(action="settle", run="feat", node="check", outcome="failed")
        self.assertEqual((stopped["state"], stopped["verdict"]), ("stopped", "verify_failed"))

    def test_a_checked_verify_node_added_by_extend_clears_an_unread_one(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", [
            node("api", scope=("a.py",)), node("check", depends_on=("api",), role="verify"),
        ], time.time())
        settled(record, "api", "accepted")
        settled(record, "check", "accepted", unread="docker terminal not up")
        self.assertEqual(finished(record), ("done", "unverified", ["handoff_not_checked:check"]))
        dag_run.extend(record, dag_run.derive(record, [], time.time()),
                       [node("check2", depends_on=("api",), role="verify")], "", time.time())
        settled(record, "check2", "accepted")
        self.assertEqual(finished(record), ("done", "verified", []))
        # An unread verify node is named only where it alone follows a producer.
        other = dag_run.new_record(PARENT, "other", "", "", [
            node("api", scope=("a.py",)), node("ui", scope=("u.py",)),
            node("check", depends_on=("api",), role="verify"), node("check-ui", depends_on=("ui",), role="verify"),
        ], time.time())
        for node_id in ("api", "ui", "check"):
            settled(other, node_id, "accepted")
        settled(other, "check-ui", "accepted", unread="docker terminal not up")
        self.assertEqual(finished(other), ("done", "unverified", ["handoff_not_checked:check-ui"]))

    def test_a_superseded_verify_node_of_an_older_repair_group_does_not_fail_the_goal(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", [
            node("api", scope=("a.py",)), node("check", depends_on=("api",), role="verify"),
        ], time.time())
        settled(record, "api", "failed")
        dag_run.repair(record, dag_run.derive(record, [], time.time()), "api", [
            node("fix1", scope=("a.py",)), node("vfix1", depends_on=("fix1",), role="verify")], time.time())
        settled(record, "fix1", "accepted")
        settled(record, "vfix1", "failed")
        dag_run.repair(record, dag_run.derive(record, [], time.time()), "vfix1",
                       [node("fix2", scope=("a.py",))], time.time())
        settled(record, "fix2", "accepted")
        derived = dag_run.derive(record, [], time.time())
        self.assertEqual((derived["vfix1"]["state"], derived["api"]["state"]), ("superseded", "repaired"))
        settled(record, "check", "accepted")
        self.assertEqual(finished(record), ("done", "verified", []))

    def test_a_repaired_producer_counts_through_its_repair_and_a_superseded_one_not_at_all(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", [
            node("api", scope=("a.py",)), node("check", depends_on=("api",), role="verify"),
        ], time.time())
        settled(record, "api", "failed")
        dag_run.repair(record, dag_run.derive(record, [], time.time()), "api",
                       [node("api-fix", scope=("a.py",))], time.time())
        settled(record, "api-fix", "accepted")
        settled(record, "check", "accepted")
        self.assertEqual(finished(record), ("done", "verified", []))
        # A producer no verify node follows: its superseded first repair is not listed, its live one is.
        loose = dag_run.new_record(PARENT, "loose", "", "", [
            node("api", scope=("a.py",)), node("ui", scope=("u.py",)), node("check", depends_on=("ui",), role="verify"),
        ], time.time())
        settled(loose, "ui", "accepted")
        settled(loose, "check", "accepted")
        settled(loose, "api", "failed")
        dag_run.repair(loose, dag_run.derive(loose, [], time.time()), "api", [node("fix1", scope=("a.py",))],
                       time.time())
        settled(loose, "fix1", "failed")
        dag_run.repair(loose, dag_run.derive(loose, [], time.time()), "fix1", [node("fix2", scope=("a.py",))],
                       time.time())
        settled(loose, "fix2", "accepted")
        self.assertEqual(dag_run.derive(loose, [], time.time())["fix1"]["state"], "superseded")
        self.assertEqual(finished(loose), ("done", "unverified", ["verification_misses:api,fix2"]))

    def test_baseline_and_review_writers_are_work_a_verify_node_follows(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", [
            node("base", role="baseline", scope=("base.txt",)), node("notes", role="review", scope=("notes.md",)),
            node("api", scope=("a.py",)), node("check", depends_on=("api",), role="verify"),
        ], time.time())
        for node_id in ("base", "notes", "api", "check"):
            settled(record, node_id, "accepted")
        self.assertEqual(finished(record), ("done", "unverified", ["verification_misses:base,notes"]))
        self.assertIn("verification_misses:base,notes", record["lint"])
        # The external owner still takes build nodes only.
        exportable = dag_run.new_record(PARENT, "x", "", "", [
            node("base", role="baseline", scope=("b.txt",)), node("api", scope=("a.py",))], time.time())
        self.assertEqual([unit["unit_id"] for unit in dag_tool.export_units(
            exportable, dag_run.derive(exportable, [], time.time()), "codex")], ["api"])

    def test_a_run_of_checks_alone_is_judged_by_its_checks(self) -> None:
        passed = dag_run.new_record(PARENT, "feat", "", "", [node("suite", role="verify")], time.time())
        settled(passed, "suite", "accepted")
        self.assertEqual(finished(passed), ("done", "verified", []))
        unread = dag_run.new_record(PARENT, "feat", "", "", [node("suite", role="verify")], time.time())
        settled(unread, "suite", "accepted", unread="docker terminal not up")
        self.assertEqual(finished(unread), ("done", "unverified", ["handoff_not_checked:suite"]))
        failed = dag_run.new_record(PARENT, "feat", "", "", [node("suite", role="verify")], time.time())
        settled(failed, "suite", "failed")
        self.assertEqual(finished(failed), ("needs_repair", "verify_failed", ["verify_failed:suite"]))

    def test_an_unread_check_in_a_run_of_checks_is_cleared_by_a_read_one(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", [node("suite", role="verify")], time.time())
        settled(record, "suite", "accepted", unread="docker terminal not up")
        unread = json.loads(dag_tool._result("status", record, dag_run.derive(record, [], time.time()), None))
        self.assertEqual((unread["verdict"], unread["verdict_reasons"]), ("unverified", ["handoff_not_checked:suite"]))
        self.assertIn("that repeats the check and has its handoff read", unread["say"])
        self.assertNotIn("()", unread["say"])
        dag_run.extend(record, dag_run.derive(record, [], time.time()), [node("suite2", role="verify")], "",
                       time.time())
        settled(record, "suite2", "accepted")
        self.assertEqual(finished(record), ("done", "verified", []))
        # A run that built something names its producers, never an empty list.
        built = dag_run.new_record(PARENT, "built", "", "", [node("api", scope=("a.py",))], time.time())
        settled(built, "api", "accepted")
        said = json.loads(dag_tool._result("status", built, dag_run.derive(built, [], time.time()), None))["say"]
        self.assertIn("every producer (api)", said)
        self.assertNotIn("()", said)

    def test_a_run_that_built_nothing_is_unverified_and_not_sent_to_extend(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", [
            node("survey", label="Survey the options"), node("summary", depends_on=("survey",)),
        ], time.time())
        for node_id in ("survey", "summary"):
            settled(record, node_id, "accepted")
        self.assertEqual(finished(record), ("done", "unverified", ["no_producers"]))
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("survey", label="Survey the options")])
            handoff(home, "feat", "survey")
            done = call(action="settle", run="feat", node="survey", outcome="accepted")
        self.assertEqual((done["state"], done["verdict"], done["verdict_reasons"]), ("done", "unverified", ["no_producers"]))
        self.assertIn("nothing was built for a verify node to check", done["say"])
        self.assertNotIn("extend", done["say"])

    def test_the_graph_names_a_verdict_only_for_a_finished_run(self) -> None:
        from omh.plugin_bundle.omh.delegation_graph import build_delegation_graph

        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("api", scope=("a.py",)),
                                                     node("check", depends_on=("api",), role="verify")])
            handoff(home, "feat", "api")
            call(action="settle", run="feat", node="api", outcome="accepted")
            failed = call(action="settle", run="feat", node="check", outcome="failed")
            open_graph = build_delegation_graph(home.omh, home.hermes, PARENT)
            call(action="repair", run="feat", node="check", nodes=[node("fix", scope=("a.py",))])
            handoff(home, "feat", "fix")
            call(action="settle", run="feat", node="fix", outcome="accepted")
            handoff(home, "feat", "check")
            call(action="settle", run="feat", node="check", outcome="accepted")
            done_graph = build_delegation_graph(home.omh, home.hermes, PARENT)
        self.assertEqual(failed["state"], "needs_repair")
        self.assertNotIn("verdict", failed)
        self.assertFalse(open_graph["dag_open"])
        self.assertNotIn("dag_verdict", open_graph)
        self.assertEqual(done_graph["dag_verdict"], "verified")


if __name__ == "__main__":
    unittest.main()

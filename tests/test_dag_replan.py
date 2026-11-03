"""The last repair briefs a new approach; earlier cycles and verify re-runs stay unchanged."""

from __future__ import annotations

import os
import unittest

from _local_package import load_local_package

load_local_package()

from _delegation_state import homes  # noqa: E402
from omh.plugin_bundle.omh import dag_run  # noqa: E402
from test_dag_run_rules import calls_by_node, record_of  # noqa: E402
from test_dag_tool import PROMPT, call, choose, handoff, node, slots_table  # noqa: E402


class DagReplanTests(unittest.TestCase):
    def test_only_last_repair_carries_failure_evidence_and_new_approach_instruction(self) -> None:
        with homes() as home:
            slots_table(home)
            original = call(action="define", run="feat", nodes=[node("api")])
            self.assertNotIn("Re-plan:", calls_by_node(original)["api"]["context"])
            call(action="settle", run="feat", node="api", outcome="failed", reason="test_api: schema mismatch")
            first = call(action="repair", run="feat", node="api", nodes=[node("fix")])
            self.assertNotIn("Re-plan:", calls_by_node(first)["fix"]["context"])
            call(action="settle", run="feat", node="fix", outcome="blocked", reason="test_api: same mismatch")
            last = call(action="repair", run="feat", node="fix", nodes=[node("new-api"), node("new-ui")])
            self.assertEqual(getattr(dag_run, "REPLAN_CYCLE", None), dag_run.MAX_REPAIR_CYCLES)
            for node_id in ("new-api", "new-ui"):
                context = calls_by_node(last)[node_id]["context"]
                self.assertIn("Re-plan:", context)
                self.assertLess(context.index(PROMPT), context.index("Re-plan:"))
                self.assertLess(context.index("Re-plan:"), context.index("Handoff:"))
                block = context.split("Re-plan:", 1)[1].split("Handoff:", 1)[0]
                self.assertIn("last repair cycle for api", block)
                self.assertIn("failed api attempt 1: test_api: schema mismatch", block)
                self.assertIn("blocked fix attempt 1: test_api: same mismatch", block)
                self.assertLess(block.index("failed api"), block.index("blocked fix"))
                for instruction in ("Do not retry the same approach", "before editing", "two or three approaches",
                                    "differ in kind", "handoff", "rule out what the failures refute",
                                    "take the one that remains", "test ids, errors, measurements", "not for their plan",
                                    "every listed failure", "infrastructure", "provider error", "interrupted child",
                                    "retrying the same approach is right", "say so in the handoff"):
                    self.assertIn(instruction, block)
                self.assertLessEqual(len("Re-plan:" + block), 1200)

    def test_last_repair_say_names_root_and_replan(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("api")])
            call(action="settle", run="feat", node="api", outcome="failed")
            first = call(action="repair", run="feat", node="api", nodes=[node("fix")])
            self.assertNotIn("re-plan", first.get("say", ""))
            call(action="settle", run="feat", node="fix", outcome="failed")
            last = call(action="repair", run="feat", node="fix", nodes=[node("replacement")])
            self.assertIn("api", last.get("say", ""))
            self.assertIn("last repair cycle", last.get("say", ""))
            self.assertIn("briefed to re-plan", last.get("say", ""))

    def test_provider_flags_and_interrupted_child_remain_evidence_not_plan_failures(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("api"), node("unrelated")])
            call(action="settle", run="feat", node="unrelated", outcome="failed", reason="unrelated failure")
            retry = call(action="settle", run="feat", node="api", outcome="failed", provider_error=True,
                         reason="transient error retried")
            self.assertNotIn("Re-plan:", calls_by_node(retry)["api"]["context"])
            call(action="settle", run="feat", node="api", outcome="failed", provider_error=True,
                 reason="HTTP 400: provider down")
            call(action="repair", run="feat", node="api", nodes=[node("fix"), node("passed")])
            handoff(home, "feat", "passed")
            call(action="settle", run="feat", node="passed", outcome="accepted", reason="accepted evidence")
            call(action="settle", run="feat", node="fix", outcome="blocked", reason="interrupted child")
            last = call(action="repair", run="feat", node="fix", nodes=[node("replacement")])
            context = calls_by_node(last)["replacement"]["context"]
            block = context.split("Re-plan:", 1)[1].split("Handoff:", 1)[0]
            evidence = [line for line in block.splitlines() if line.startswith(("failed ", "blocked "))]
            self.assertEqual(evidence, ["failed api attempt 2: HTTP 400: provider down (provider error)",
                                        "blocked fix attempt 1: interrupted child"])
            for excluded in ("transient error retried", "unrelated failure", "accepted evidence"):
                self.assertNotIn(excluded, block)
            self.assertIn("If every listed failure is an infrastructure cut", block)
            self.assertIn("retrying the same approach is right; say so in the handoff", block)

    def test_failure_lines_are_latest_six_in_settle_order_and_block_is_bounded(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("api")])
            call(action="settle", run="feat", node="api", outcome="failed", reason="old root reason")
            ids = [f"repair-{index}-" + "x" * 23 for index in range(7)]
            call(action="repair", run="feat", node="api", nodes=[node(node_id) for node_id in ids])
            # Settle opposite to record order so chronology cannot accidentally follow the node list.
            for index, node_id in enumerate(reversed(ids)):
                call(action="settle", run="feat", node=node_id, outcome="blocked",
                     reason=f"failure-{index}: " + "r" * 189)
            last = call(action="repair", run="feat", node=ids[0], nodes=[node("replacement")])
            context = calls_by_node(last)["replacement"]["context"]
            block = "Re-plan:" + context.split("Re-plan:", 1)[1].split("Handoff:", 1)[0]
            evidence = [line for line in block.splitlines() if line.startswith(("failed ", "blocked "))]
            expected = list(reversed(ids))[1:]
            self.assertEqual(len(evidence), 6)
            for index, (line, node_id) in enumerate(zip(evidence, expected), start=1):
                self.assertTrue(line.startswith(f"blocked {node_id} attempt 1: failure-{index}: "), line)
                self.assertTrue(line.endswith("…"), line)
            self.assertNotIn("old root reason", block)
            self.assertNotIn("failure-0:", block)
            self.assertLessEqual(len(block), 1200)

    def test_verification_root_still_reruns_after_last_repair_without_replan(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("verify", role="verify"),
                                                     node("after", depends_on=("verify",))])
            call(action="settle", run="feat", node="verify", outcome="failed", reason="test_output: first failure")
            call(action="repair", run="feat", node="verify", nodes=[node("fix")])
            handoff(home, "feat", "fix")
            first_rerun = call(action="settle", run="feat", node="fix", outcome="accepted")
            self.assertNotIn("Re-plan:", calls_by_node(first_rerun)["verify"]["context"])
            call(action="settle", run="feat", node="verify", outcome="failed", reason="test_output: second failure")
            last = call(action="repair", run="feat", node="verify", nodes=[node("replacement")])
            context = calls_by_node(last)["replacement"]["context"]
            self.assertIn("failed verify attempt 1: test_output: first failure", context)
            self.assertIn("failed verify attempt 2: test_output: second failure", context)
            handoff(home, "feat", "replacement")
            rerun = call(action="settle", run="feat", node="replacement", outcome="accepted")
            self.assertNotIn("Re-plan:", calls_by_node(rerun)["verify"]["context"])
            self.assertNotIn("after", calls_by_node(rerun))
            self.assertEqual(record_of(home)["nodes"][0]["attempts"][-1]["n"], 3)
            handoff(home, "feat", "verify")
            accepted = call(action="settle", run="feat", node="verify", outcome="accepted")
            self.assertIn("after", calls_by_node(accepted))


    def test_last_repair_note_keeps_the_export_instruction_for_a_chosen_coding_owner(self) -> None:
        # Mutation: hand the re-plan sentence to _ready as `say` again; it then replaces the export instruction.
        with homes() as home:
            slots_table(home)
            choose(home, "codex")
            call(action="define", run="feat", goal="g", nodes=[node("api", scope=("src/api.py",))])
            call(action="export", run="feat", owner="codex")
            call(action="settle", run="feat", node="api", outcome="failed", reason="r1")
            call(action="repair", run="feat", node="api", nodes=[node("fix", scope=("src/api.py",))])
            call(action="export", run="feat", owner="codex")
            call(action="settle", run="feat", node="fix", outcome="failed", reason="r2")
            last = call(action="repair", run="feat", node="fix", nodes=[node("fix2", scope=("src/api.py",))])
            self.assertIn("export", last)
            self.assertIn("omh_dag action=export owner=codex", last["say"])
            self.assertIn("last repair cycle", last["say"])
            self.assertLess(last["say"].index("action=export"), last["say"].index("last repair cycle"))

    def test_last_repair_note_keeps_the_no_free_slot_instruction(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("api")])
            call(action="settle", run="feat", node="api", outcome="failed", reason="r1")
            call(action="repair", run="feat", node="api", nodes=[node("fix")])
            call(action="settle", run="feat", node="fix", outcome="failed", reason="r2")
            slots_table(home, running=[(f"busy{index}", os.getpid()) for index in range(50)])
            last = call(action="repair", run="feat", node="fix", nodes=[node("fix2")])
            self.assertEqual(last["calls"], [])
            self.assertIn("No delegate_task slot is free", last["say"])
            self.assertIn("last repair cycle", last["say"])

if __name__ == "__main__":
    unittest.main()

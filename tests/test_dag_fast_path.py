"""The dag-ulw fast path (`fast`, opt-in at define) and the batch settle (`settles`).

A small graph can keep its verify node: the parent runs that node's VERIFY
commands itself, writes its handoff and settles it, so the run costs one child
fewer and its verify node never rides in a `delegate_task` call. Eligibility is
decided once, at define, and stored (`dag_run.fast_ineligible`); a graph that
does not qualify is defined as it always was, with the reason in its lint. A
run defined without `fast` keeps every byte of its reply but the advisory
`fast_eligible`. `settle` also takes `settles`, a batch that applies every item
or none.
"""

from __future__ import annotations

import json
import os
import time
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from _delegation_state import PARENT, homes, start  # noqa: E402
from omh.plugin_bundle.omh import dag_run  # noqa: E402
from omh.plugin_bundle.omh.hooks.tool_hooks import pre_tool_call  # noqa: E402
from omh.plugin_bundle.omh.tools import dag_tool  # noqa: E402
from test_dag_criteria import record_bytes, record_of, token_of  # noqa: E402
from test_dag_criteria import handoff as criteria_handoff  # noqa: E402
from test_dag_tool import call, child_started, handoff, node, oneshot_config, slots_table  # noqa: E402

# Three build nodes, one verify node: the widest graph the fast path takes.
FEATURE = [
    node("api", scope=("src/api.py",)),
    node("ui", category="unspecified-low", scope=("src/ui.py",)),
    node("docs", category="writing", depends_on=("api",), scope=("docs/api.md",)),
    node("check", category="unspecified-high", depends_on=("api", "ui", "docs"), label="Verify the feature",
         role="verify"),
]
# The smallest graph it takes: one producer and one check.
PAIR = [node("build", scope=("src/api.py",)), node("check", depends_on=("build",), role="verify")]
CRITERIA = [{"id": "api", "text": "The export API returns CSV"}]
MET = "CRITERION api #T: met - curl /export returned text/csv\n"


def call_nodes(result: dict) -> list[str]:
    """Every node a reply hands to `delegate_task`, in call order."""
    return [node_id for entry in result.get("calls", []) for node_id in entry["nodes"]]


def fast_reasons(record: dict) -> list[str]:
    """The reasons a define asked for `fast` and did not get it, from the record's lint."""
    finding = next((item for item in record["lint"] if item.startswith("fast_ineligible:")), "")
    return finding.split(":", 1)[1].split(",") if finding else []


def write(home, target: str, *, session: str = PARENT) -> dict | None:
    """The real `pre_tool_call` verdict on a `write_file` to ``target``; nothing is written."""
    return pre_tool_call(tool_name="write_file", args={"path": target, "content": "x = 1\n"},
                         session_id=session, task_id=session, turn_id="turn-scope", **home.hooks())


def state_of(result: dict, node_id: str) -> str:
    return next(row for row in result["nodes"] if row["id"] == node_id)["state"]


def put_out_on_parent(home, run: str, node_id: str) -> None:
    """Write ``node_id`` as out on the parent lane, as a record an engine without the one-at-a-time rule left it."""
    path = dag_run.record_path(home.omh, PARENT, run)
    record = dag_run.read_run(path)
    target = next(item for item in record["nodes"] if item["id"] == node_id)
    dag_run.hand_out(target, "ready", time.time())["lane"] = "parent"
    dag_run.write_run(path, record)


class DefineTests(unittest.TestCase):
    def test_an_eligible_define_is_stored_fast_and_drops_three_findings(self) -> None:
        """Mutation: recompute eligibility per call, or keep the review/judgement advice on a fast run."""
        with homes() as home:
            slots_table(home)
            result = call(action="define", run="feat", goal="Ship the feature", nodes=FEATURE, fast=True)
            record = record_of(home)
        self.assertEqual(result["status"], "ok", result)
        self.assertIs(record["fast"], True)
        self.assertIs(result["fast"], True)
        # The verify node is the parent's: the define reply hands out the three producers only.
        # api and ui start at once, docs waits on api, and the verify node waits on every producer.
        self.assertEqual(call_nodes(result), ["api", "ui"])
        self.assertNotIn("for_parent", result)
        for dropped in ("no_review_node", "no_judgement_node", "no_goal_criteria", "fast_eligible"):
            self.assertNotIn(dropped, result["lint"], result["lint"])
            self.assertNotIn(dropped, record["lint"], record["lint"])
        # Same graph without `fast`: all three findings are there, and only the reply adds `fast_eligible`.
        with homes() as plain_home:
            slots_table(plain_home)
            plain = call(action="define", run="feat", goal="Ship the feature", nodes=FEATURE)
            plain_record = record_of(plain_home)
        for kept in ("no_review_node", "no_judgement_node", "no_goal_criteria"):
            self.assertIn(kept, plain["lint"], plain["lint"])
        self.assertEqual(plain["lint"], [*plain_record["lint"], "no_goal_criteria", "fast_eligible"])
        self.assertNotIn("fast", plain_record)
        self.assertNotEqual(record["digest"], plain_record["digest"])

    def test_fast_is_part_of_the_digest_only_when_true(self) -> None:
        """Mutation: hash the fast mark into every run, so a non-fast run stops matching itself."""
        now = 1_000_000.0
        plain = dag_run.new_record(PARENT, "plain", "", "", PAIR, now)
        fasted = dag_run.new_record(PARENT, "fast", "", "", PAIR, now, fast=True)
        asked_elsewhere = dag_run.new_record(PARENT, "wide", "", "", [node(f"n{index}") for index in range(7)], now,
                                            fast=True)
        self.assertNotIn("fast", plain)
        self.assertEqual(plain["digest"], dag_run.definition_digest(plain["nodes"]))
        self.assertEqual(plain["digest"], dag_run.definition_digest(plain["nodes"], (), fast=False))
        self.assertIs(fasted["fast"], True)
        self.assertNotEqual(fasted["digest"], plain["digest"])
        # A graph that does not qualify is no fast run at all: no key, the usual digest, and the reason kept.
        self.assertNotIn("fast", asked_elsewhere)
        self.assertEqual(set(fast_reasons(asked_elsewhere)),
                         {"too_many_build_nodes", "too_many_nodes", "verify_nodes"})
        self.assertEqual(asked_elsewhere["digest"],
                         dag_run.definition_digest(asked_elsewhere["nodes"]))

    def test_each_ineligible_condition_defines_a_normal_run_with_its_reason(self) -> None:
        """Mutation: adopt `fast` without checking the graph, or drop the reason from the lint."""
        cases = {
            "too_many_build_nodes": [node("a", scope=("a.py",)), node("b", scope=("b.py",)),
                                     node("c", scope=("c.py",)), node("d", scope=("d.py",)),
                                     node("check", depends_on=("a", "b", "c", "d"), role="verify")],
            "too_many_nodes": [node("a", scope=("a.py",)), node("b", scope=("b.py",)), node("c", scope=("c.py",)),
                               *[node(f"read{index}", category="review", role="review") for index in range(3)],
                               node("check", depends_on=("a", "b", "c"), role="verify")],
            "verify_nodes": [node("a", scope=("a.py",)), node("check", depends_on=("a",), role="verify"),
                             node("check2", depends_on=("a",), role="verify")],
            "verify_full_suite": [node("a", scope=("a.py",)),
                                  node("check", depends_on=("a",), role="verify",
                                       prompt="TASK: check\nDELIVERABLE: a verdict\nSCOPE: none\n"
                                              "VERIFY: run the full test suite, exit 0\nSTOP WHEN: green")],
            "baseline_node": [node("base", label="Baseline the test suite", role="baseline"),
                              node("a", scope=("a.py",)), node("check", depends_on=("base", "a"), role="verify")],
            "owner_node": [node("a", scope=("a.py",), owner="codex"), node("check", depends_on=("a",), role="verify")],
            "verify_identity": [node("a", scope=("a.py",)),
                                {**node("check", depends_on=("a",), role="verify"), "identity": "builtin:builder"}],
            "verify_local": [node("a", scope=("a.py",)),
                             {**node("check", depends_on=("a",), role="verify"), "local": True}],
        }
        for reason, definitions in cases.items():
            with self.subTest(reason=reason):
                record = dag_run.new_record(PARENT, "feat", "", "", definitions, 1_000_000.0, fast=True,
                                            owners=(*dag_run.EXTERNAL_OWNERS, "codex"))
                self.assertNotIn("fast", record, reason)
                self.assertIn(reason, fast_reasons(record), record["lint"])

    def test_an_ineligible_define_says_which_condition_failed(self) -> None:
        with homes() as home:
            slots_table(home)
            result = call(action="define", run="feat", nodes=[
                node("a", scope=("a.py",)), node("b", scope=("b.py",)), node("c", scope=("c.py",)),
                node("d", scope=("d.py",)), node("check", depends_on=("a", "b", "c", "d"), role="verify")], fast=True)
            record = record_of(home)
        self.assertEqual(result["status"], "ok", result)
        self.assertNotIn("fast", result)
        self.assertEqual(fast_reasons(record), ["too_many_build_nodes"])
        self.assertIn("The run is defined without the fast path: the graph has more than 3 build nodes",
                      result["say"])
        self.assertIn("Every node runs on delegate_task as usual.", result["say"])

    def test_a_graph_that_could_run_fast_is_told_so_once(self) -> None:
        """Mutation: drop the advice, or repeat it on every later reply."""
        with homes() as home:
            slots_table(home)
            defined = call(action="define", run="feat", nodes=PAIR)
            later = call(action="ready", run="feat")
        self.assertIn("fast_eligible", defined["lint"])
        self.assertNotIn("fast_eligible", later.get("lint", []))
        self.assertNotIn("fast", defined)


class ParentVerifyTests(unittest.TestCase):
    def test_the_verify_node_of_a_fast_run_is_the_parents_and_no_call_carries_it(self) -> None:
        """Mutation: let `calls_for` hand the verify node out, or forget `for_parent`."""
        with homes() as home:
            slots_table(home)
            defined = call(action="define", run="feat", nodes=PAIR, fast=True)
            handoff(home, "feat", "build")
            after_build = call(action="settle", run="feat", node="build", outcome="accepted")
            handed = record_of(home)
            again = call(action="ready", run="feat")
            handoff(home, "feat", "check")
            done = call(action="settle", run="feat", node="check", outcome="accepted")
        self.assertEqual(call_nodes(defined), ["build"])
        self.assertEqual(after_build["calls"], [])
        self.assertEqual(after_build["for_parent"], ["check"])
        self.assertEqual(again["for_parent"], ["check"])  # still the parent's while it waits
        # The parent lane's attempt carries the run's criteria token like a verify child's would, and a later `ready`
        # names it again without offering it a second time.
        attempts = next(item for item in handed["nodes"] if item["id"] == "check")["attempts"]
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[-1]["lane"], "parent")
        self.assertIn("This run is fast: no child runs check.", after_build["say"])
        self.assertIn("Run its VERIFY commands yourself in this session", after_build["say"])
        self.assertEqual(done["state"], "done", done)
        self.assertEqual(done["verdict"], "verified", done)
        for result in (defined, after_build, again, done):
            self.assertNotIn("check", call_nodes(result))

    def test_a_repaired_verify_node_stays_with_the_parent(self) -> None:
        """Mutation: repair hands the re-run of a fast run's verify node to delegate_task."""
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=PAIR, fast=True)
            handoff(home, "feat", "build")
            first = call(action="settle", run="feat", node="build", outcome="accepted")
            call(action="settle", run="feat", node="check", outcome="failed", reason="the check failed")
            repaired = call(action="repair", run="feat", node="check", nodes=[node("fix", scope=("src/api.py",))])
            handoff(home, "feat", "fix")
            after_fix = call(action="settle", run="feat", node="fix", outcome="accepted")
        self.assertEqual(first["for_parent"], ["check"])
        self.assertEqual(call_nodes(repaired), ["fix"])
        self.assertNotIn("check", call_nodes(repaired))
        self.assertEqual(after_fix["for_parent"], ["check"])
        self.assertNotIn("check", call_nodes(after_fix))
        self.assertIn("This run is fast: no child runs check.", after_fix["say"])
        # A fast run leaves out the advice a parent-run verify node makes moot, repair replies included.
        self.assertNotIn("no_review_node", repaired["lint"], repaired["lint"])

    def test_an_extend_round_keeps_a_new_verify_node_with_the_parent(self) -> None:
        """Mutation: read the fast mark from the calls instead of the record, so an added check goes to a child."""
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=PAIR, fast=True)
            handoff(home, "feat", "build")
            call(action="settle", run="feat", node="build", outcome="accepted")
            handoff(home, "feat", "check")
            done = call(action="settle", run="feat", node="check", outcome="accepted")
            extended = call(action="extend", run="feat", nodes=[
                node("more", category="writing", scope=("docs/x.md",)),
                node("check2", depends_on=("more",), role="verify")])
            handoff(home, "feat", "more")
            after_more = call(action="settle", run="feat", node="more", outcome="accepted")
        self.assertEqual(done["state"], "done", done)
        self.assertEqual(call_nodes(extended), ["more"])
        self.assertEqual(after_more["for_parent"], ["check2"])
        self.assertNotIn("check2", call_nodes(after_more))

    def test_the_parent_writes_the_criterion_lines_and_the_verdict_is_verified(self) -> None:
        """Mutation: hand a fast run's verify node no token, so its handoff lines count for nothing."""
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=PAIR, criteria=CRITERIA, fast=True)
            handoff(home, "feat", "build")
            out = call(action="settle", run="feat", node="build", outcome="accepted")
            token = token_of(record_of(home), "check")
            criteria_handoff(home, "feat", "check", MET)
            done = call(action="settle", run="feat", node="check", outcome="accepted")
        self.assertEqual(out["for_parent"], ["check"])
        self.assertIn(f"In check's handoff write one line per criterion (api): `CRITERION <id> #{token}: met",
                      out["say"])
        self.assertTrue(token)
        self.assertEqual(done["verdict"], "verified", done)
        self.assertEqual(done["criteria"]["met"], 1)

    def test_a_batch_settle_of_the_parents_check_still_reads_its_criteria(self) -> None:
        """Mutation: let the batch path skip the criteria read a single settle does first."""
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=PAIR, criteria=CRITERIA, fast=True)
            handoff(home, "feat", "build")
            call(action="settle", run="feat", node="build", outcome="accepted")
            token = token_of(record_of(home), "check")
            criteria_handoff(home, "feat", "check", f"CRITERION api #{token}: unmet - the export returned 500\n")
            refused = call(action="settle", run="feat", settles=[{"node": "check", "outcome": "accepted"}])
        self.assertEqual((refused["status"], refused["reason"]), ("refused", "criteria_unmet"), refused)
        self.assertIn("settle item 1 (check)", refused["say"])

    def test_an_accepted_verify_without_a_handoff_is_still_refused(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=PAIR, fast=True)
            handoff(home, "feat", "build")
            call(action="settle", run="feat", node="build", outcome="accepted")
            before = record_bytes(home)
            refused = call(action="settle", run="feat", node="check", outcome="accepted")
            after = record_bytes(home)
        self.assertEqual((refused["status"], refused["reason"]), ("refused", "handoff_missing"), refused)
        self.assertEqual(before, after)

    def test_two_runnable_nodes_sharing_a_write_scope_are_still_refused_at_define(self) -> None:
        with homes() as home:
            slots_table(home)
            refused = call(action="define", run="feat", nodes=[node("api", scope=("src/x.py",)),
                                                              node("ui", scope=("src/x.py",)),
                                                              node("check", role="verify")], fast=True)
            stored = dag_run.record_path(home.omh, PARENT, "feat").exists()
        self.assertEqual((refused["status"], refused["reason"]), ("refused", "write_scope_overlap"), refused)
        self.assertFalse(stored)

    def test_a_fast_run_says_so_in_the_status_line_and_the_payload(self) -> None:
        with homes() as home:
            slots_table(home)
            result = call(action="define", run="feat", name="Feature", nodes=PAIR, fast=True)
        self.assertTrue(result["status_line"].startswith("DAG Feature · fast · "), result["status_line"])
        self.assertIs(result["fast"], True)


class BatchSettleTests(unittest.TestCase):
    def test_a_batch_settle_closes_every_item_in_one_call(self) -> None:
        """Mutation: settle the first item and stop, or report one `settled` object for a batch."""
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("api", scope=("src/api.py",)),
                                                     node("ui", category="unspecified-low", scope=("src/ui.py",))])
            handoff(home, "feat", "api")
            handoff(home, "feat", "ui")
            result = call(action="settle", run="feat", settles=[
                {"node": "api", "outcome": "accepted"}, {"node": "ui", "outcome": "accepted", "reason": "ok"}])
            record = record_of(home)
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(result["settled"], [{"node": "api", "outcome": "accepted"},
                                             {"node": "ui", "outcome": "accepted"}])
        states = {row["id"]: row["state"] for row in result["nodes"]}
        self.assertEqual(states, {"api": "accepted", "ui": "accepted"})
        self.assertEqual([item["attempts"][-1]["outcome"] for item in record["nodes"]], ["accepted", "accepted"])

    def test_a_batch_with_one_refused_item_records_nothing(self) -> None:
        """Mutation: apply the items one by one to the record, so a later refusal keeps the earlier ones."""
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("api", scope=("src/api.py",)),
                                                     node("ui", category="unspecified-low", scope=("src/ui.py",))])
            handoff(home, "feat", "api")
            before = record_bytes(home)
            refused = call(action="settle", run="feat", settles=[{"node": "api", "outcome": "accepted"},
                                                                {"node": "ghost", "outcome": "accepted"}])
            after = record_bytes(home)
            unhanded = call(action="settle", run="feat", settles=[{"node": "api", "outcome": "accepted"},
                                                                 {"node": "ui", "outcome": "accepted"}])
        self.assertEqual((refused["status"], refused["reason"]), ("refused", "unknown_node"), refused)
        self.assertIn("settle item 2 (ghost)", refused["say"])
        self.assertIn("apply together or not at all", refused["say"])
        self.assertEqual(before, after)
        # The same batch, refused for a missing handoff of its second item, records nothing either.
        self.assertEqual((unhanded["status"], unhanded["reason"]), ("refused", "handoff_missing"), unhanded)
        self.assertIn("settle item 2 (ui)", unhanded["say"])

    def test_a_batch_takes_accepted_failed_and_blocked_only(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("api", scope=("src/api.py",)),
                                                     node("ui", category="unspecified-low", scope=("src/ui.py",))])
            before = record_bytes(home)
            for items, reason in (([{"node": "api", "outcome": "parked"}], "invalid_settles"),
                                  ([{"node": "api", "outcome": "escalated"}], "invalid_settles"),
                                  ([{"node": "api"}], "invalid_settles"),
                                  ([{"node": "api", "outcome": "accepted", "extra": 1}], "invalid_settles"),
                                  ([], "invalid_settles")):
                with self.subTest(items=items):
                    refused = call(action="settle", run="feat", settles=items)
                    self.assertEqual((refused["status"], refused["reason"]), ("refused", reason), refused)
                    self.assertEqual(record_bytes(home), before)
            handoff(home, "feat", "api")
            together = call(action="settle", run="feat", node="api", outcome="accepted",
                            settles=[{"node": "api", "outcome": "accepted"}])
            both = call(action="settle", run="feat", node="api", outcome="accepted")
        self.assertEqual((together["status"], together["reason"]), ("refused", "invalid_settles"), together)
        self.assertEqual(both["status"], "ok", both)
        self.assertEqual(both["settled"]["node"], "api")  # one node still answers with one object

    def test_a_malformed_item_names_where_it_is(self) -> None:
        """Mutation: refuse provider_error before its item's index and id are known, so the say names no item."""
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("a", scope=("src/a.py",)), node("b", scope=("src/b.py",))])
            handoff(home, "feat", "a")
            before = record_bytes(home)
            refused = call(action="settle", run="feat", settles=[
                {"node": "a", "outcome": "accepted"}, {"node": "b", "outcome": "accepted", "provider_error": 7}])
            after = record_bytes(home)
        self.assertEqual((refused["status"], refused["reason"]), ("refused", "invalid_provider_error"), refused)
        self.assertIn("settle item 2 (b)", refused["say"])
        self.assertEqual(before, after)

    def test_a_batch_fails_and_blocks_nodes_too(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("api", scope=("src/api.py",)),
                                                     node("ui", category="unspecified-low", scope=("src/ui.py",))])
            result = call(action="settle", run="feat", settles=[
                {"node": "api", "outcome": "failed", "reason": "the build broke"},
                {"node": "ui", "outcome": "blocked", "reason": "waiting for the API"}])
            record = json.loads(record_bytes(home))
        self.assertEqual(result["state"], "needs_repair", result)
        self.assertEqual(result["open"], ["api", "ui"])
        self.assertEqual([item["attempts"][-1]["outcome"] for item in record["nodes"]], ["failed", "blocked"])


class BatchRefusalTruthTests(unittest.TestCase):
    """A settle whose settlements are on disk is never reported `refused`: the next-wave refusal is beside it."""

    def test_a_batch_that_committed_reports_settled_and_the_next_refusal(self) -> None:
        """Mutation: let `_ready`'s refusal answer the whole call, so a written batch reads as refused."""
        late = {**node("next", depends_on=("a", "b")), "identity": "custom:absent-review-probe"}
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("a", scope=("src/a.py",)), node("b", scope=("src/b.py",)),
                                                    late])
            handoff(home, "feat", "a")
            handoff(home, "feat", "b")
            result = call(action="settle", run="feat", settles=[{"node": "a", "outcome": "accepted"},
                                                               {"node": "b", "outcome": "accepted"}])
            states = {row["id"]: row["state"] for row in result["nodes"]}
            retry = call(action="settle", run="feat", settles=[{"node": "a", "outcome": "accepted"},
                                                              {"node": "b", "outcome": "accepted"}])
        self.assertEqual(result["status"], "ok", result)
        self.assertNotIn("reason", result)
        self.assertEqual(result["settled"], [{"node": "a", "outcome": "accepted"},
                                             {"node": "b", "outcome": "accepted"}])
        self.assertEqual(result["calls"], [])
        self.assertEqual(result["next_refused"]["reason"], "identity_unavailable")
        self.assertEqual(states, {"a": "accepted", "b": "accepted", "next": "ready"})
        self.assertIn("Recorded a as accepted, b as accepted", result["say"])
        self.assertIn("are on disk", result["say"])
        # The truth costs no retry: settling the batch again is refused, because it did close.
        self.assertEqual((retry["status"], retry["reason"]), ("refused", "node_not_out"), retry)

    def test_a_single_settle_that_committed_reports_settled_and_the_next_refusal(self) -> None:
        """Mutation: the single-node settle path answers the next-wave refusal as a refused settle."""
        late = {**node("next", depends_on=("a",)), "identity": "custom:absent-review-probe"}
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("a", scope=("src/a.py",)), late])
            handoff(home, "feat", "a")
            result = call(action="settle", run="feat", node="a", outcome="accepted")
            states = {row["id"]: row["state"] for row in result["nodes"]}
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(result["settled"], {"node": "a", "outcome": "accepted"})
        self.assertEqual(result["next_refused"]["reason"], "identity_unavailable")
        self.assertEqual(states, {"a": "accepted", "next": "ready"})
        self.assertIn("Recorded a as accepted", result["say"])


class ParentScopeGuardTests(unittest.TestCase):
    """A fast run's verify node is the parent's turn: the write guard its child would have carried still applies."""

    def write(self, home, target: str, *, session: str = PARENT) -> dict | None:
        return pre_tool_call(tool_name="write_file", args={"path": target, "content": "x = 1\n"},
                             session_id=session, task_id=session, turn_id="turn-scope", **home.hooks())

    def test_a_fast_verify_nodes_read_only_and_write_scope_hold_the_parent(self) -> None:
        """Mutation: return unbound for the root session, so the fast verifier's parent can write anything."""
        for restriction in ({"read_only": True}, {"write_scope": ["src/check-output.txt"]}):
            with self.subTest(restriction=restriction), homes() as home, patch.dict(
                    os.environ, {"TERMINAL_CWD": str(home.omh.parent)}):
                slots_table(home)
                call(action="define", run="feat", nodes=[PAIR[0], {**PAIR[-1], **restriction}], fast=True)
                handoff(home, "feat", "build")
                out = call(action="settle", run="feat", node="build", outcome="accepted")
                self.assertEqual(out["for_parent"], ["check"], out)
                blocked = self.write(home, "src/api.py")
                self.assertIsNotNone(blocked, "a fast verifier's parent wrote outside its node's guard")
                self.assertEqual(blocked["action"], "block")
                self.assertIn("dag-ulw node check in run feat", blocked["message"])
                # Its own handoff, inside the run's runtime dir, is the one write it may make.
                self.assertIsNone(self.write(home, str(dag_run.handoff_path(home.omh, PARENT, "feat", "check"))))
                if "write_scope" in restriction:
                    self.assertIsNone(self.write(home, "src/check-output.txt"))
                handoff(home, "feat", "check")
                self.assertEqual(call(action="settle", run="feat", node="check", outcome="accepted")["status"], "ok")
                # Settled, the node is no one's: the session is its own again.
                self.assertIsNone(self.write(home, "src/api.py"))

    def test_a_plain_runs_parent_is_never_bound(self) -> None:
        """A run without `fast` keeps its parent unbound: its verify node is a child's."""
        with homes() as home, patch.dict(os.environ, {"TERMINAL_CWD": str(home.omh.parent)}):
            slots_table(home)
            call(action="define", run="feat", nodes=[PAIR[0], {**PAIR[-1], "read_only": True}])
            handoff(home, "feat", "build")
            out = call(action="settle", run="feat", node="build", outcome="accepted")
            self.assertEqual(call_nodes(out), ["check"])
            self.assertNotIn("for_parent", out)
            self.assertIsNone(self.write(home, "src/api.py"))

    def test_the_one_shot_parent_lane_stays_unbound(self) -> None:
        """A spent one-shot budget hands a node to the parent as it always did: not a fast run's guard."""
        with homes() as home, patch.object(dag_tool, "_single_query_session", return_value=True), patch.dict(
                os.environ, {"TERMINAL_CWD": str(home.omh.parent)}):
            oneshot_config(home, 1)
            call(action="define", run="feat", nodes=[node("api", scope=("src/api.py",))])
            child_started(home, "feat", "api")  # the one child the budget had
            out = call(action="settle", run="feat", node="api", outcome="failed", provider_error=True)
            self.assertEqual(out["for_parent"], ["api"], out)
            self.assertIsNone(self.write(home, "src/elsewhere.py"))


class FastVerifyAdmissionTests(unittest.TestCase):
    """A fast run's verify node runs in the parent's session: it cannot carry an identity or a local flag."""

    def finished(self, home) -> None:
        call(action="define", run="feat", nodes=PAIR, fast=True)
        handoff(home, "feat", "build")
        call(action="settle", run="feat", node="build", outcome="accepted")
        handoff(home, "feat", "check")
        call(action="settle", run="feat", node="check", outcome="accepted")

    def test_extend_refuses_a_local_or_identity_verifier_before_it_is_written(self) -> None:
        """Mutation: admit any verify node into a fast run, then hand it to the parent's cloud model."""
        for extra, reason in (({"local": True}, "fast_verify_local"),
                              ({"identity": "builtin:builder"}, "fast_verify_identity")):
            with self.subTest(extra=extra), homes() as home:
                slots_table(home)
                self.finished(home)
                before = record_bytes(home)
                refused = call(action="extend", run="feat", nodes=[{**node("private", role="verify"), **extra}])
                after = record_bytes(home)
                self.assertEqual((refused["status"], refused["reason"]), ("refused", reason), refused)
                self.assertEqual(before, after)
                self.assertIn("without `fast`", refused["say"])

    def test_repair_refuses_a_local_or_identity_verifier_before_it_is_written(self) -> None:
        """Mutation: repair admission checks the group's size and graph, not what a fast run can run."""
        for extra, reason in (({"local": True}, "fast_verify_local"),
                              ({"identity": "builtin:builder"}, "fast_verify_identity")):
            with self.subTest(extra=extra), homes() as home:
                slots_table(home)
                call(action="define", run="feat", nodes=PAIR, fast=True)
                handoff(home, "feat", "build")
                call(action="settle", run="feat", node="build", outcome="accepted")
                call(action="settle", run="feat", node="check", outcome="failed", reason="the check failed")
                before = record_bytes(home)
                refused = call(action="repair", run="feat", node="check",
                               nodes=[{**node("private", role="verify"), **extra}])
                after = record_bytes(home)
                self.assertEqual((refused["status"], refused["reason"]), ("refused", reason), refused)
                self.assertEqual(before, after)

    def test_ready_never_hands_an_identity_or_local_verify_node_to_the_parent(self) -> None:
        """Mutation: hand every verify node of a fast record to the parent lane, whatever it carries."""
        for field, value, said in (("identity", "builtin:builder", "names identity builtin:builder"),
                                   ("local", True, "is local")):
            with self.subTest(field=field), homes() as home:
                slots_table(home)
                call(action="define", run="feat", nodes=PAIR, fast=True)
                record = record_of(home)
                next(item for item in record["nodes"] if item["id"] == "check")[field] = value
                dag_run.write_run(dag_run.record_path(home.omh, PARENT, "feat"), record)
                handoff(home, "feat", "build")
                out = call(action="settle", run="feat", node="build", outcome="accepted")
                self.assertNotIn("for_parent", out)
                self.assertEqual(out["calls"], [])
                self.assertEqual(next(row for row in out["nodes"] if row["id"] == "check")["state"], "ready")
                self.assertIn("cannot run here", out["say"])
                self.assertIn(said, out["say"])


class OneShotFastBudgetTests(unittest.TestCase):
    """A one-shot budget counts children: a fast run's verify node is the parent's, so it costs none."""

    def test_define_admits_a_fast_graph_whose_verify_node_costs_no_child(self) -> None:
        """Mutation: compare the whole graph with the children left before `fast` is decided."""
        with homes() as home, patch.object(dag_tool, "_single_query_session", return_value=True):
            oneshot_config(home, 2)
            three = [node("api", scope=("src/api.py",)), node("ui", category="unspecified-low", scope=("src/ui.py",)),
                     node("check", role="verify", depends_on=("api", "ui"))]
            fast = call(action="define", run="over", nodes=three, fast=True)
            plain = call(action="define", run="plain", nodes=three)
        self.assertEqual(fast["status"], "ok", fast)
        self.assertEqual(call_nodes(fast), ["api", "ui"])
        self.assertEqual((plain["status"], plain["reason"]), ("refused", "oneshot_budget_exceeded"), plain)
        self.assertIn("at most 2 nodes", plain["say"])

    def test_extend_counts_one_child_for_a_producer_and_its_check(self) -> None:
        """Mutation: refuse an extend round that fits once the verify node is not counted."""
        with homes() as home, patch.object(dag_tool, "_single_query_session", return_value=True):
            oneshot_config(home, 2)
            call(action="define", run="feat", nodes=PAIR, fast=True)
            start(home, "child-other", "sa-other", "Look something up", now=time.time())  # one child left
            handoff(home, "feat", "build")
            call(action="settle", run="feat", node="build", outcome="accepted")
            handoff(home, "feat", "check")
            call(action="settle", run="feat", node="check", outcome="accepted")
            extended = call(action="extend", run="feat", nodes=[
                node("more", category="writing", scope=("docs/x.md",)),
                node("check2", role="verify", depends_on=("more",))])
            plain = call(action="define", run="plain", nodes=[
                node("more2", category="writing", scope=("docs/y.md",)),
                node("check3", role="verify", depends_on=("more2",))])
        self.assertEqual(extended["status"], "ok", extended)
        self.assertEqual(call_nodes(extended), ["more"])
        self.assertNotIn("check2", call_nodes(extended))
        self.assertEqual((plain["status"], plain["reason"]), ("refused", "oneshot_budget_exceeded"), plain)

    def test_repair_counts_one_child_for_its_fix_and_its_check(self) -> None:
        """Mutation: count a repair group's verify node against a budget only its fix can use."""
        with homes() as home, patch.object(dag_tool, "_single_query_session", return_value=True):
            oneshot_config(home, 2)
            call(action="define", run="feat", nodes=PAIR, fast=True)
            start(home, "child-other", "sa-other", "Look something up", now=time.time())  # one child left
            handoff(home, "feat", "build")
            call(action="settle", run="feat", node="build", outcome="accepted")
            call(action="settle", run="feat", node="check", outcome="failed", reason="the check failed")
            repaired = call(action="repair", run="feat", node="check", nodes=[
                node("fix", scope=("src/api.py",)),
                node("check2", role="verify", depends_on=("fix",))])
        self.assertEqual(repaired["status"], "ok", repaired)
        self.assertEqual(call_nodes(repaired), ["fix"])


class IsolationAfterDefineTests(unittest.TestCase):
    """Turning worktree isolation on after define holds no node this session runs itself."""

    def test_a_parent_only_verify_node_is_not_held_by_isolation(self) -> None:
        """Mutation: count every offered node, so a parent-only check waits for a worktree no child would get."""
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=PAIR, fast=True)
            (home.hermes / "config.yaml").write_text("delegation:\n  worktree_isolation: true\n", encoding="utf-8")
            handoff(home, "feat", "build")
            out = call(action="settle", run="feat", node="build", outcome="accepted")
            status = call(action="status", run="feat")
        self.assertEqual(out["for_parent"], ["check"], out)
        self.assertEqual(out["calls"], [])
        self.assertNotIn("worktree_isolation", out["say"])
        self.assertNotIn("worktree_isolation", status.get("say", ""))

    def test_isolation_still_holds_a_child_task(self) -> None:
        """The parent-only exemption is not a lift of isolation on children."""
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", fast=True, nodes=[
                node("api", scope=("src/api.py",)),
                node("ui", category="unspecified-low", depends_on=("api",), scope=("src/ui.py",)),
                node("check", role="verify", depends_on=("ui",))])
            (home.hermes / "config.yaml").write_text("delegation:\n  worktree_isolation: true\n", encoding="utf-8")
            handoff(home, "feat", "api")
            out = call(action="settle", run="feat", node="api", outcome="accepted")
        self.assertEqual(out["calls"], [])
        self.assertNotIn("for_parent", out)
        self.assertIn("worktree_isolation", out["say"])


class RetryUnbindsParentTests(unittest.TestCase):
    """R1: a parent-lane attempt binds only while it is open; a provider error's retry closes it."""

    def test_attempt_open_reads_what_closing_writes(self) -> None:
        """Mutation: decide openness by membership in the public `OUTCOMES`, which omits `retry`."""
        self.assertTrue(dag_run.attempt_open({"settled_at": None, "outcome": ""}))
        for outcome in (*dag_run.OUTCOMES, "retry", dag_run.CARRIED, "some_future_internal"):
            self.assertFalse(dag_run.attempt_open({"settled_at": 5.0, "outcome": outcome}), outcome)
        self.assertFalse(dag_run.attempt_open({"settled_at": None, "outcome": "retry"}))
        self.assertFalse(dag_run.attempt_open(None))

    def test_a_retried_check_with_a_refused_next_wave_frees_the_parent(self) -> None:
        """Mutation: keep the root bound to the closed `retry` attempt until the run is cancelled."""
        from test_dag_tool import IdentityNodeTests

        graph = [PAIR[0], {**PAIR[-1], "read_only": True},
                 {**node("review", role="review", category="review", depends_on=("build",)), "identity": "custom:qa"}]
        for many in (False, True):
            with self.subTest(batch=many), homes() as home, patch.dict(
                    os.environ, {"TERMINAL_CWD": str(home.omh.parent)}):
                IdentityNodeTests._identities(home, IdentityNodeTests.DOCUMENT)
                slots_table(home)
                call(action="define", run="feat", nodes=graph, fast=True)
                handoff(home, "feat", "build")
                out = call(action="settle", run="feat", node="build", outcome="accepted")
                self.assertEqual(out["for_parent"], ["check"], out)
                self.assertIsNotNone(write(home, "src/unrelated.py"))
                # The unstarted review child goes stale and its identity goes away: the next wave is refused.
                later = record_of(home)["nodes"][-1]["attempts"][-1]["handed_out_at"] + dag_run.HANDOUT_STALE_SECONDS + 2
                IdentityNodeTests._identities(home, {**IdentityNodeTests.DOCUMENT, "identities": {}})
                failed = {"node": "check", "outcome": "failed", "provider_error": True}
                with patch.object(dag_tool.time, "time", return_value=later):
                    result = (call(action="settle", run="feat", settles=[failed]) if many
                              else call(action="settle", run="feat", **failed))
                self.assertEqual(result["status"], "ok", result)
                self.assertEqual(result["next_refused"]["reason"], "identity_unavailable")
                self.assertNotIn("for_parent", result)
                attempt = record_of(home)["nodes"][1]["attempts"][-1]
                self.assertEqual((attempt["outcome"], attempt["lane"]), ("retry", "parent"))
                self.assertIsNone(write(home, "src/unrelated.py"), "a closed retry attempt still bound the parent")

    def test_a_superseded_check_no_longer_holds_the_parent(self) -> None:
        """Mutation: bind on the attempt alone, so a check `settle` refuses as not out holds the parent for good."""
        with homes() as home, patch.dict(os.environ, {"TERMINAL_CWD": str(home.omh.parent)}):
            slots_table(home)
            call(action="define", run="feat", nodes=PAIR, fast=True)
            handoff(home, "feat", "build")
            call(action="settle", run="feat", node="build", outcome="accepted")
            call(action="settle", run="feat", node="check", outcome="failed", reason="the check failed")
            out = call(action="repair", run="feat", node="check", nodes=[
                node("fix", scope=("src/api.py",)), {**node("check2", role="verify"), "read_only": True}])
            self.assertEqual(out["for_parent"], ["check2"], out)
            self.assertIsNotNone(write(home, "src/unrelated.py"))
            call(action="settle", run="feat", node="fix", outcome="failed", reason="the fix failed")
            again = call(action="repair", run="feat", node="fix", nodes=[node("fix2", scope=("src/api.py",))])
            self.assertEqual(state_of(again, "check2"), "superseded")
            refused = call(action="settle", run="feat", node="check2", outcome="failed")
            self.assertEqual(refused["reason"], "node_not_out")
            self.assertEqual(dag_run.parent_lane_open(record_of(home)), [])
            self.assertIsNone(write(home, "src/unrelated.py"))
            # And it holds no later check: the root check runs again once the new group is accepted.
            handoff(home, "feat", "fix2")
            rerun = call(action="settle", run="feat", node="fix2", outcome="accepted")
            self.assertEqual(rerun["for_parent"], ["check"], rerun)
            self.assertNotIn("held_for_parent", rerun)

    def test_a_plain_runs_child_stays_guarded_across_a_retry(self) -> None:
        """Runs without `fast` are unchanged: a child is bound to its node, and only a public settle releases it."""
        with homes() as home, patch.dict(os.environ, {"TERMINAL_CWD": str(home.omh.parent)}):
            slots_table(home)
            call(action="define", run="feat", nodes=[PAIR[0], {**PAIR[-1], "read_only": True}])
            handoff(home, "feat", "build")
            call(action="settle", run="feat", node="build", outcome="accepted")
            child_started(home, "feat", "check")
            self.assertIsNotNone(write(home, "src/api.py", session="child-check"))
            record = record_of(home)
            record["nodes"][1]["attempts"][-1].update(settled_at=time.time(), outcome="retry", provider_error=True)
            dag_run.write_run(dag_run.record_path(home.omh, PARENT, "feat"), record)
            self.assertIsNotNone(write(home, "src/api.py", session="child-check"))
            self.assertIsNone(write(home, "src/api.py"))  # and its parent is never bound

    def test_the_retrys_next_attempt_binds_again(self) -> None:
        """The release is of the closed attempt only: once the check is handed out again, the guard is back."""
        with homes() as home, patch.dict(os.environ, {"TERMINAL_CWD": str(home.omh.parent)}):
            slots_table(home)
            call(action="define", run="feat", nodes=[PAIR[0], {**PAIR[-1], "read_only": True}], fast=True)
            handoff(home, "feat", "build")
            call(action="settle", run="feat", node="build", outcome="accepted")
            out = call(action="settle", run="feat", node="check", outcome="failed", provider_error=True)
            self.assertEqual(out["for_parent"], ["check"], out)
            self.assertEqual(len(record_of(home)["nodes"][1]["attempts"]), 2)
            self.assertIsNotNone(write(home, "src/unrelated.py"))


class OneParentCheckAtATimeTests(unittest.TestCase):
    """R2: the parent holds one fast check at a time, and the guard enforces every one that is out anyway."""

    TARGET = "src/check-output.txt"

    def test_a_second_fast_runs_check_waits_for_the_first(self) -> None:
        """Mutation: hand each fast run's check to the parent regardless of the conversation's other runs."""
        with homes() as home, patch.dict(os.environ, {"TERMINAL_CWD": str(home.omh.parent)}):
            slots_table(home)
            for run, restrict in (("a-scoped", {"write_scope": [self.TARGET]}), ("z-read-only", {"read_only": True})):
                call(action="define", run=run, nodes=[PAIR[0], {**PAIR[-1], **restrict}], fast=True)
                handoff(home, run, "build")
            first = call(action="settle", run="a-scoped", node="build", outcome="accepted")
            second = call(action="settle", run="z-read-only", node="build", outcome="accepted")
            again = call(action="ready", run="z-read-only")
            self.assertEqual(first["for_parent"], ["check"], first)
            for reply in (second, again):
                self.assertNotIn("for_parent", reply)
                self.assertEqual(reply["held_for_parent"], ["check"], reply)
                self.assertEqual(state_of(reply, "check"), "ready")
                self.assertIn("check in run a-scoped", reply["say"])
            # Only a-scoped's check is out: its scope decides, and it covers the target.
            self.assertIsNone(write(home, self.TARGET))
            self.assertIn("run a-scoped", write(home, "src/api.py")["message"])
            handoff(home, "a-scoped", "check")
            self.assertEqual(call(action="settle", run="a-scoped", node="check", outcome="accepted")["state"], "done")
            self.assertIsNone(write(home, self.TARGET))  # nothing is out between the two
            after = call(action="ready", run="z-read-only")
            self.assertEqual(after["for_parent"], ["check"], after)
            self.assertNotIn("held_for_parent", after)
            self.assertIn("run z-read-only", write(home, self.TARGET)["message"])

    def test_overlapping_settles_on_two_fast_runs_hand_out_one_check(self) -> None:
        """Mutation: scan the conversation's other runs outside the parent-lane lock, or write the record after it.

        Two settle calls on two fast runs, each under its own run lock, pause after their scan of the other runs. With
        the scan and the hand-out under one conversation lock, the second waits for the first's write and sees its
        check open, so exactly one check goes to the parent.
        """
        import threading
        from concurrent.futures import ThreadPoolExecutor

        with homes() as home, patch.dict(os.environ, {"TERMINAL_CWD": str(home.omh.parent)}):
            slots_table(home)
            for run, restrict in (("a-scoped", {"write_scope": [self.TARGET]}), ("z-read-only", {"read_only": True})):
                call(action="define", run=run, nodes=[PAIR[0], {**PAIR[-1], **restrict}], fast=True)
                handoff(home, run, "build")
            real = dag_tool._parent_lane_elsewhere
            entered = threading.Event()

            def scan_then_pause(record, *args):
                busy = real(record, *args)
                if not entered.is_set():
                    entered.set()
                    time.sleep(0.5)  # the other call starts while this one holds what it scanned
                return busy

            with patch.object(dag_tool, "_parent_lane_elsewhere", new=scan_then_pause), \
                    ThreadPoolExecutor(max_workers=2) as pool:
                jobs = [pool.submit(call, action="settle", run=run, node="build", outcome="accepted")
                        for run in ("a-scoped", "z-read-only")]
                replies = [job.result(timeout=30) for job in jobs]
            handed = [reply.get("for_parent", []) for reply in replies]
            self.assertEqual(sorted(len(item) for item in handed), [0, 1], replies)
            held = [reply.get("held_for_parent", []) for reply in replies]
            self.assertEqual(sorted(len(item) for item in held), [0, 1], replies)
            open_checks = [dag_run.parent_lane_open(record_of(home, run)) for run in ("a-scoped", "z-read-only")]
            self.assertEqual(sorted(len(item) for item in open_checks), [0, 1], open_checks)

    def test_two_verify_nodes_in_one_extend_go_out_one_at_a_time(self) -> None:
        """Mutation: hand every ready verify node of an extend round to the parent in one reply."""
        with homes() as home, patch.dict(os.environ, {"TERMINAL_CWD": str(home.omh.parent)}):
            slots_table(home)
            call(action="define", run="feat", nodes=PAIR, fast=True)
            for name in ("build", "check"):
                handoff(home, "feat", name)
                call(action="settle", run="feat", node=name, outcome="accepted")
            out = call(action="extend", run="feat", nodes=[
                node("a-scoped", role="verify", scope=(self.TARGET,)),
                {**node("z-read-only", role="verify"), "read_only": True}])
            self.assertEqual(out["for_parent"], ["a-scoped"], out)
            self.assertEqual(out["held_for_parent"], ["z-read-only"], out)
            self.assertEqual(state_of(out, "z-read-only"), "ready")
            self.assertIn("z-read-only stays ready until a-scoped is settled", out["say"])
            self.assertNotIn("z-read-only:", out["say"])  # no handoff path, no instruction to run it yet
            self.assertIsNone(write(home, self.TARGET))
            handoff(home, "feat", "a-scoped")
            nxt = call(action="settle", run="feat", node="a-scoped", outcome="accepted")
            self.assertEqual(nxt["for_parent"], ["z-read-only"], nxt)
            self.assertNotIn("held_for_parent", nxt)
            self.assertIn("node z-read-only in run feat", write(home, self.TARGET)["message"])

    def test_the_guard_enforces_every_open_parent_check(self) -> None:
        """Mutation: bind the root to the first open parent-lane node it finds and stop looking.

        `ready` no longer puts two out, so the record is written as an older engine left it: both attempts open on
        the parent lane, in both orders across runs and inside one run.
        """
        scoped, read_only = {"write_scope": [self.TARGET]}, {"read_only": True}
        for first, second in ((scoped, read_only), (read_only, scoped)):
            with self.subTest(first=first, where="two runs"), homes() as home, patch.dict(
                    os.environ, {"TERMINAL_CWD": str(home.omh.parent)}):
                slots_table(home)
                for run, restrict in (("a-run", first), ("z-run", second)):
                    call(action="define", run=run, nodes=[PAIR[0], {**PAIR[-1], **restrict}], fast=True)
                    put_out_on_parent(home, run, "check")
                blocked = write(home, self.TARGET)
                self.assertIsNotNone(blocked, "the scoped check's allow covered a read-only check that is also out")
                self.assertIn("is read-only", blocked["message"])
                self.assertIsNotNone(write(home, "src/api.py"))
                for run in ("a-run", "z-run"):  # each run's own handoff stays writable
                    self.assertIsNone(write(home, str(dag_run.handoff_path(home.omh, PARENT, run, "check"))))
        with self.subTest(where="one run"), homes() as home, patch.dict(
                os.environ, {"TERMINAL_CWD": str(home.omh.parent)}):
            slots_table(home)
            call(action="define", run="feat", nodes=PAIR, fast=True)
            path = dag_run.record_path(home.omh, PARENT, "feat")
            record = record_of(home)
            record["nodes"].append({**record["nodes"][-1], "id": "other", "write_scope": ["src/other.txt"],
                                    "depends_on": []})
            record["nodes"][1]["write_scope"] = [self.TARGET]
            dag_run.write_run(path, record)
            for name in ("check", "other"):
                put_out_on_parent(home, "feat", name)
            # Covered by one scope and not the other: every bound node's scope has to cover a write.
            self.assertIn("node other in run feat", write(home, self.TARGET)["message"])
            self.assertIn("node check in run feat", write(home, "src/other.txt")["message"])

    def test_a_cancelled_run_holds_no_one(self) -> None:
        """An open check in a cancelled run neither binds the parent nor keeps another run's check waiting."""
        with homes() as home, patch.dict(os.environ, {"TERMINAL_CWD": str(home.omh.parent)}):
            slots_table(home)
            for run in ("a-run", "z-run"):
                call(action="define", run=run, nodes=[PAIR[0], {**PAIR[-1], "read_only": True}], fast=True)
                handoff(home, run, "build")
            call(action="settle", run="a-run", node="build", outcome="accepted")
            held = call(action="settle", run="z-run", node="build", outcome="accepted")
            self.assertEqual(held["held_for_parent"], ["check"], held)
            call(action="cancel", run="a-run")
            self.assertIsNone(write(home, "src/api.py"))
            self.assertEqual(call(action="ready", run="z-run")["for_parent"], ["check"])

    def test_a_plain_run_never_lists_held_for_parent(self) -> None:
        """Runs without `fast` are untouched: an open fast check elsewhere holds none of their nodes."""
        with homes() as home:
            slots_table(home)
            call(action="define", run="a-fast", nodes=PAIR, fast=True)
            handoff(home, "a-fast", "build")
            call(action="settle", run="a-fast", node="build", outcome="accepted")
            call(action="define", run="plain", nodes=PAIR)
            handoff(home, "plain", "build")
            out = call(action="settle", run="plain", node="build", outcome="accepted")
        self.assertEqual(call_nodes(out), ["check"])
        self.assertNotIn("held_for_parent", out)
        self.assertNotIn("for_parent", out)


class MixedWaveIsolationTests(unittest.TestCase):
    """R3: isolation turned on after define holds child dispatch, not the parent's own check."""

    GRAPH = [*PAIR, node("review", role="review", category="review", depends_on=("build",))]

    def test_a_mixed_wave_hands_the_parent_its_check_and_holds_the_child(self) -> None:
        """Mutation: let the child's isolation hold gate the parent-lane handout too."""
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=self.GRAPH, fast=True)
            (home.hermes / "config.yaml").write_text("delegation:\n  worktree_isolation: true\n", encoding="utf-8")
            handoff(home, "feat", "build")
            out = call(action="settle", run="feat", node="build", outcome="accepted")
            again = call(action="ready", run="feat")
            status = call(action="status", run="feat")
            handoff(home, "feat", "check")
            closed = call(action="settle", run="feat", node="check", outcome="accepted")
        self.assertEqual(status["say"], dag_tool.WORKTREE_ISOLATION_CHILDREN_HELD)
        for reply in (out, again):
            self.assertEqual(reply["for_parent"], ["check"], reply)
            self.assertEqual(reply["calls"], [])
            self.assertEqual(state_of(reply, "check"), "handed_out")
            self.assertEqual(state_of(reply, "review"), "ready")
            self.assertIn(dag_tool.WORKTREE_ISOLATION_CHILDREN_HELD, reply["say"])
            self.assertNotIn("No node was handed out", reply["say"])
        # With the check settled only the child is left, and the hold reads as it always did.
        self.assertEqual(closed["calls"], [])
        self.assertNotIn("for_parent", closed)
        self.assertTrue(closed["say"].endswith(dag_tool.WORKTREE_ISOLATION_HELD), closed["say"])

    def test_without_isolation_the_same_wave_dispatches_the_child(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=self.GRAPH, fast=True)
            handoff(home, "feat", "build")
            out = call(action="settle", run="feat", node="build", outcome="accepted")
        self.assertEqual(out["for_parent"], ["check"], out)
        self.assertEqual(call_nodes(out), ["review"])

    def test_a_plain_run_under_isolation_hands_out_nothing(self) -> None:
        """Runs without `fast` are unchanged: the verify node is a child's and is held with the rest."""
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=self.GRAPH)
            (home.hermes / "config.yaml").write_text("delegation:\n  worktree_isolation: true\n", encoding="utf-8")
            handoff(home, "feat", "build")
            out = call(action="settle", run="feat", node="build", outcome="accepted")
        self.assertEqual(out["calls"], [])
        self.assertNotIn("for_parent", out)
        self.assertTrue(out["say"].endswith(dag_tool.WORKTREE_ISOLATION_HELD), out["say"])


class SchemaTests(unittest.TestCase):
    def test_the_schema_names_fast_and_settles(self) -> None:
        properties = dag_tool.OMH_DAG_SCHEMA["parameters"]["properties"]
        self.assertEqual(properties["fast"]["type"], "boolean")
        self.assertEqual(properties["settles"]["items"]["properties"]["outcome"]["enum"],
                         list(dag_run.BATCH_OUTCOMES))
        self.assertIn("fast", dag_tool.OMH_DAG_SCHEMA["description"])


if __name__ == "__main__":
    unittest.main()

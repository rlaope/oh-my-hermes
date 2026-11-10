"""Goal criteria of a dag-ulw run: the goal split into separately checkable outcomes its verify node marks.

The model passes ``criteria`` at define (and extend); a verify node's task
asks for one ``CRITERION <id>: <status> - <evidence>`` line per criterion in
its handoff; `settle` reads those lines, keeps the status words, and refuses
an ``accepted`` that leaves one unmet or unobserved; the verdict needs every
one met. A run without criteria behaves exactly as it did before they
existed, pinned below against what origin/main produced.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from _delegation_state import PARENT, homes  # noqa: E402
from omh.plugin_bundle.omh import dag_run  # noqa: E402
from omh.plugin_bundle.omh.tools import dag_tool  # noqa: E402
from test_dag_tool import (  # noqa: E402
    PROMPT, SANDBOX_SHELL, SANDBOX_SKIP, Answers, Sandbox, Terminal, call, handoff, node, slots_table, terminal_env,
)

CRITERIA = [{"id": "api", "text": "The export API returns CSV"}, {"id": "docs", "text": "The docs page names the API"}]
NODES = [node("build", scope=("src/api.py",)), node("check", depends_on=("build",), role="verify")]
ALL_MET = "CRITERION api: met - curl /export returned text/csv\nCRITERION docs: met - grep found it in docs/api.md\n"


def record_of(home, run: str = "feat") -> dict:
    return json.loads(dag_run.record_path(home.omh, PARENT, run).read_text(encoding="utf-8"))


def record_bytes(home, run: str = "feat") -> bytes:
    return dag_run.record_path(home.omh, PARENT, run).read_bytes()


def last_attempt(record: dict, node_id: str) -> dict:
    return next(item for item in record["nodes"] if item["id"] == node_id)["attempts"][-1]


def to_check(home, criteria: list | None = CRITERIA) -> dict:
    """The run defined (with ``criteria`` when given) and its producer accepted: the verify node is out."""
    slots_table(home)
    arguments = {"criteria": criteria} if criteria is not None else {}
    call(action="define", run="feat", goal="Ship the export API with docs", nodes=NODES, **arguments)
    handoff(home, "feat", "build")
    return call(action="settle", run="feat", node="build", outcome="accepted")


# What origin/main produced for the run below (`_main_run`), captured before criteria existed: a run without criteria
# must produce exactly this. The handoff root is a POSIX path, so the task text is the same on every platform.
MAIN_DIGEST = "344a76cb7bfeb253"
MAIN_STATUS_RUNNING = "DAG Feature · 0/3 done · 0 running"
MAIN_STATUS_DONE = "DAG Feature · 3/3 done · 0 running"
MAIN_VERIFY_CONTEXT = (
    "TASK: do it\nDELIVERABLE: a change\nSCOPE: only its files\nVERIFY: run `make test`, exit 0\nSTOP WHEN: green\n\n"
    "Run goal (saved):\nShip the export API with docs\n\n"
    "The run goal is acceptance context, not permission to widen your SCOPE.\n\n"
    "Handoff: before you stop, write your report to /backend-home/.omh/dag/parent-session-a1bdc27ac7582a74/feat/"
    "verify.md: what you did, the files you changed, what VERIFY showed, and anything still open. The parent reads "
    "that file and your final message.\n"
    "Read first: /backend-home/.omh/dag/parent-session-a1bdc27ac7582a74/feat/api.md, /backend-home/.omh/dag/"
    "parent-session-a1bdc27ac7582a74/feat/docs.md. A missing file means that part did not finish: stop and say so.\n"
    "Check the complete run goal, not only this node's local VERIFY. Name each unmet or unobserved goal criterion; "
    "producer claims are not verification evidence.\n"
    "In the handoff, name for each failing check the producer whose declared write_scope holds its failing path, or "
    "`unattributed`: by declared scope, not proven cause. Scopes: api: src/api.py; docs: docs/api.md\n"
    "Stay inside your SCOPE: other parts of this run work at the same time. If you cannot finish, say plainly that "
    "you are blocked and why; do not report blocked work as done."
)
MAIN_API_CONTEXT_SHA = "fd8a3794061b97010042cb5340cbcf4991630164ce58ed990667ccfbb5bc146c"
MAIN_RESULT_RUNNING_SHA = "98a177d5682046408b2dce33d187db1dc5e255f38d5b2061d442b5b0f7fedf68"
MAIN_RESULT_DONE_SHA = "6929d9578504513ff2e758766b2f293eda910749987d095aa51bba903a297c24"
MAIN_RECORD_DONE_SHA = "73428d56e7eef59d8ab280603de5610873ab3e4018287c6f03d8bfb7da544deb"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _main_run() -> dict:
    """A run without criteria driven to done through the engine, every view it gives on the way."""
    raw = [
        {"id": "api", "label": "Build the API", "category": "quick", "prompt": PROMPT, "depends_on": [],
         "write_scope": ["src/api.py"], "role": "build"},
        {"id": "docs", "label": "Write the docs", "category": "writing", "prompt": PROMPT, "depends_on": ["api"],
         "write_scope": ["docs/api.md"]},
        {"id": "verify", "label": "Verify the feature", "category": "unspecified-high", "prompt": PROMPT,
         "depends_on": ["api", "docs"], "write_scope": [], "role": "verify"},
    ]
    home, now = Path("/omh-home"), 1_000_000.0
    record = dag_run.new_record("parent-session", "feat", "Feature", "Ship the export API with docs", raw, now)
    record["handoff_root"] = "/backend-home/.omh/dag"

    def stage(at: float) -> dict:
        return dag_run.derive(record, [], at)

    seen: dict = {"digest": record["digest"]}
    dag_run.calls_for(record, stage(now), free_slots=10, per_call=10, omh_home=home, now=now)
    seen["result_running"] = dag_tool._result("ready", record, stage(now + 1), None, now=now + 1)
    seen["status_running"] = dag_run.status_line(record, stage(now + 1), now=now + 1)
    for node_id in ("api", "docs"):
        if stage(now + 2)[node_id]["state"] == "ready":
            dag_run.calls_for(record, stage(now + 2), free_slots=10, per_call=10, omh_home=home, now=now + 2)
        dag_run.settle(record, stage(now + 2), node_id, "accepted", "ok", False, read_handoff=lambda: (True, ""),
                       now=now + 3)
    dag_run.calls_for(record, stage(now + 4), free_slots=10, per_call=10, omh_home=home, now=now + 4)
    nodes = {item["id"]: item for item in record["nodes"]}
    seen["verify_task"] = dag_run.task_for(record, nodes["verify"], home, stage(now + 4))
    seen["api_task"] = dag_run.task_for(record, nodes["api"], home, stage(now + 4))
    dag_run.settle(record, stage(now + 5), "verify", "accepted", "", False, read_handoff=lambda: (True, ""),
                   now=now + 5)
    seen["verdict"] = dag_run.goal_verdict(record, stage(now + 6))
    seen["status_done"] = dag_run.status_line(record, stage(now + 6), now=now + 6)
    seen["result_done"] = dag_tool._result("status", record, stage(now + 6), None, now=now + 6)
    seen["record"] = json.dumps(record, sort_keys=True)
    return seen


class WithoutCriteriaTests(unittest.TestCase):
    def test_a_run_without_criteria_gives_what_main_gave(self) -> None:
        """Mutation: store an empty criteria key, hash criteria always, or add a criteria part to any view."""
        seen = _main_run()
        self.assertEqual(seen["digest"], MAIN_DIGEST)
        self.assertEqual(seen["status_running"], MAIN_STATUS_RUNNING)
        self.assertEqual(seen["status_done"], MAIN_STATUS_DONE)
        self.assertEqual(seen["verdict"], ("verified", []))
        self.assertEqual(seen["verify_task"]["goal"], "Verify the feature [dag:feat/verify]")
        self.assertEqual(seen["verify_task"]["context"], MAIN_VERIFY_CONTEXT)
        self.assertEqual(_sha(seen["api_task"]["context"]), MAIN_API_CONTEXT_SHA, seen["api_task"]["context"])
        self.assertEqual(_sha(seen["result_running"]), MAIN_RESULT_RUNNING_SHA, seen["result_running"])
        self.assertEqual(_sha(seen["result_done"]), MAIN_RESULT_DONE_SHA, seen["result_done"])
        self.assertEqual(_sha(seen["record"]), MAIN_RECORD_DONE_SHA, seen["record"])
        self.assertNotIn("criteria", json.loads(seen["result_done"]))
        self.assertNotIn("criteria", json.loads(seen["record"]))

    def test_define_without_criteria_lints_on_the_reply_only(self) -> None:
        with homes() as home:
            slots_table(home)
            bare = call(action="define", run="feat", nodes=NODES)
            stored = record_of(home)
            given = call(action="define", run="other", nodes=NODES, criteria=CRITERIA)
        self.assertIn("no_goal_criteria", bare["lint"])
        self.assertNotIn("no_goal_criteria", stored["lint"])
        self.assertNotIn("criteria", stored)
        self.assertNotIn("no_goal_criteria", given["lint"])


class DefineTests(unittest.TestCase):
    def test_define_stores_the_criteria_and_counts_them_in_every_view(self) -> None:
        with homes() as home:
            slots_table(home)
            defined = call(action="define", run="feat", nodes=NODES, criteria=[
                {"id": "api", "text": "  The export API   returns CSV "}, CRITERIA[1]])
            stored = record_of(home)
        self.assertEqual(defined["status"], "ok", defined)
        self.assertEqual(stored["criteria"], CRITERIA)
        self.assertEqual(defined["criteria"], {
            "total": 2, "met": 0, "unmet": [], "unobserved": [],
            "items": [{**item, "status": "unchecked"} for item in CRITERIA]})
        self.assertTrue(defined["status_line"].endswith("0/2 criteria met"), defined["status_line"])

    def test_malformed_criteria_are_refused_and_nothing_is_recorded(self) -> None:
        many = [{"id": f"c{index}", "text": "x"} for index in range(dag_run.MAX_CRITERIA + 1)]
        cases = {
            "not a list": "api works",
            "empty": [],
            "too many": many,
            "duplicate id": [CRITERIA[0], {"id": "api", "text": "again"}],
            "unknown field": [{**CRITERIA[0], "weight": 2}],
            "missing text": [{"id": "api"}],
            "bad id": [{"id": "API", "text": "x"}],
            "two lines": [{"id": "api", "text": "one\ntwo"}],
            "too long": [{"id": "api", "text": "x" * (dag_run.MAX_CRITERION_CHARS + 1)}],
            "not an object": ["api"],
        }
        for label, criteria in cases.items():
            with self.subTest(label), homes() as home:
                slots_table(home)
                refused = call(action="define", run="feat", nodes=NODES, criteria=criteria)
                self.assertEqual((refused["status"], refused["reason"]), ("refused", "invalid_criteria"), refused)
                self.assertFalse(dag_run.record_path(home.omh, PARENT, "feat").exists())

    def test_criteria_are_part_of_the_definition(self) -> None:
        """Mutation: leave criteria out of the digest, so other criteria reuse the run."""
        self.assertEqual(dag_run.definition_digest(NODES), dag_run.definition_digest(NODES, ()))
        self.assertNotEqual(dag_run.definition_digest(NODES), dag_run.definition_digest(NODES, CRITERIA))
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=NODES, criteria=CRITERIA)
            again = call(action="define", run="feat", nodes=NODES, criteria=CRITERIA)
            other = call(action="define", run="feat", nodes=NODES, criteria=CRITERIA[:1])
            bare = call(action="define", run="feat", nodes=NODES)
        self.assertTrue(again["reused"], again)
        for refused in (other, bare):
            self.assertEqual(refused["reason"], "run_exists", refused)
            self.assertIn("other nodes or criteria", refused["say"])


class TaskTests(unittest.TestCase):
    def test_only_the_verify_node_is_told_the_criteria_and_the_line_format(self) -> None:
        with homes() as home:
            slots_table(home)
            first = call(action="define", run="feat", nodes=NODES, criteria=CRITERIA)
            handoff(home, "feat", "build")
            second = call(action="settle", run="feat", node="build", outcome="accepted")
        build = first["calls"][0]["tasks"][0]["context"]
        check = second["calls"][0]["tasks"][0]["context"]
        self.assertNotIn("CRITERION", build)
        self.assertIn("Goal criteria:\n- api: The export API returns CSV\n- docs: The docs page names the API\n", check)
        self.assertIn("CRITERION <id>: met | unmet | unobserved - <the command you ran and what it showed>", check)
        self.assertIn("producer claims are not verification evidence", check)


class LineParsingTests(unittest.TestCase):
    def statuses(self, text: str) -> dict:
        return dag_run.criterion_statuses(dag_run.criterion_lines(text), ["api", "docs"])

    def test_only_marked_lines_for_declared_ids_count_and_the_last_wins(self) -> None:
        cases = [
            ("CRITERION api: met - ran it\nCRITERION docs: unmet - 404", {"api": "met", "docs": "unmet"}),
            # An id the run does not declare is ignored.
            ("CRITERION extra: met - ran it\nCRITERION api: met - ok", {"api": "met", "docs": "unobserved"}),
            # `met` with nothing after it is not evidence.
            ("CRITERION api: met\nCRITERION docs: met -  ", {"api": "unobserved", "docs": "unobserved"}),
            # Prose that mentions a criterion has no line-start marker.
            ("The criterion api was met.\nCRITERION api was met - ok\nWe saw CRITERION api: met - x",
             {"api": "unobserved", "docs": "unobserved"}),
            # A later line overrides an earlier one, either way.
            ("CRITERION api: met - ok\nCRITERION api: unmet - broke again\nCRITERION docs: unmet - no\n"
             "CRITERION docs: met - fixed", {"api": "unmet", "docs": "met"}),
            # Bullets, spaces and backticks before the marker are fine; the status word ignores case.
            ("  - `CRITERION api: MET - ran x`\n* CRITERION docs: unobserved - no access",
             {"api": "met", "docs": "unobserved"}),
            # A status word must stand alone: `metric` is no `met`.
            ("CRITERION api: metric - x\ncriterion docs: met - lower-case marker", {"api": "unobserved",
                                                                                     "docs": "unobserved"}),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.statuses(text), expected)


class SettleTests(unittest.TestCase):
    def test_accepted_needs_every_criterion_met_and_a_refusal_changes_nothing(self) -> None:
        """Mutation: accept with one unmet or unobserved, or write the attempt before refusing."""
        for text, reason, named in (
            ("CRITERION api: met - ok\nCRITERION docs: unmet - page missing", "criteria_unmet", "docs"),
            ("CRITERION api: met - ok\nCRITERION docs: met", "criteria_unobserved", "docs"),
            ("CRITERION api: unobserved - no network", "criteria_unobserved", "api, docs"),
        ):
            with self.subTest(reason=reason, text=text), homes() as home:
                to_check(home)
                handoff(home, "feat", "check", text)
                before = record_bytes(home)
                refused = call(action="settle", run="feat", node="check", outcome="accepted")
                self.assertEqual((refused["status"], refused["reason"]), ("refused", reason), refused)
                self.assertIn(f"criteria {named}", refused["say"])
                self.assertEqual(record_bytes(home), before)

    def test_every_criterion_met_is_accepted_and_verified_with_status_words_only(self) -> None:
        with homes() as home:
            to_check(home)
            handoff(home, "feat", "check", "Ran the checks.\n" + ALL_MET)
            done = call(action="settle", run="feat", node="check", outcome="accepted")
            stored = record_of(home)
            status = call(action="status", run="feat")
        self.assertEqual((done["state"], done["verdict"], done["verdict_reasons"]), ("done", "verified", []))
        self.assertEqual(last_attempt(stored, "check")["criteria"], {"api": "met", "docs": "met"})
        self.assertNotIn("curl", json.dumps(stored))  # no evidence text, no handoff content
        self.assertEqual(done["criteria"]["met"], 2)
        self.assertIn("2/2 criteria met", done["status_line"])
        self.assertIn("Goal criteria: 2/2 criteria met.", done["say"])
        self.assertEqual(status["criteria"], done["criteria"])  # status after compaction shows the same

    def test_failed_and_blocked_record_what_the_handoff_marks_and_never_need_one(self) -> None:
        for outcome in ("failed", "blocked"):
            with self.subTest(outcome=outcome), homes() as home:
                to_check(home)
                handoff(home, "feat", "check", "CRITERION api: met - ok\nCRITERION docs: unmet - 404")
                settled = call(action="settle", run="feat", node="check", outcome=outcome)
                self.assertEqual(last_attempt(record_of(home), "check")["criteria"], {"api": "met", "docs": "unmet"})
                self.assertEqual(settled["criteria"]["unmet"], ["docs"])
                self.assertIn("1/2 criteria met", settled["status_line"])
            with self.subTest(outcome=outcome, handoff="missing"), homes() as home:
                to_check(home)
                settled = call(action="settle", run="feat", node="check", outcome=outcome)
                self.assertEqual(settled["status"], "ok", settled)
                self.assertNotIn("criteria", last_attempt(record_of(home), "check"))

    def test_a_linked_handoff_is_never_followed(self) -> None:
        with homes() as home:
            to_check(home)
            target = handoff(home, "feat", "elsewhere", ALL_MET)
            link = dag_run.handoff_path(home.omh, PARENT, "feat", "check")
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("this platform cannot make a symlink here")
            refused = call(action="settle", run="feat", node="check", outcome="accepted")
        self.assertEqual(refused["reason"], "handoff_missing", refused)

    def test_lines_past_the_read_cap_are_ignored(self) -> None:
        with homes() as home:
            to_check(home)
            handoff(home, "feat", "check", "x" * dag_run.MAX_HANDOFF_READ_BYTES + "\n" + ALL_MET)
            refused = call(action="settle", run="feat", node="check", outcome="accepted")
            handoff(home, "feat", "check", ALL_MET + "x" * dag_run.MAX_HANDOFF_READ_BYTES)
            accepted = call(action="settle", run="feat", node="check", outcome="accepted")
        self.assertEqual(refused["reason"], "criteria_unobserved", refused)
        self.assertEqual(accepted["verdict"], "verified", accepted)

    def test_a_run_without_criteria_settles_its_verify_node_as_before(self) -> None:
        with homes() as home:
            to_check(home, criteria=None)
            handoff(home, "feat", "check", "CRITERION api: unmet - not a run with criteria")
            done = call(action="settle", run="feat", node="check", outcome="accepted")
            stored = record_of(home)
        self.assertEqual(done["verdict"], "verified")
        self.assertNotIn("criteria", last_attempt(stored, "check"))
        self.assertNotIn("criteria", done)


class VerdictAndExtendTests(unittest.TestCase):
    def test_extend_adds_new_criteria_only_and_they_need_their_own_check(self) -> None:
        """Mutation: let extend rewrite an id, or count a criterion no accepted check marked."""
        with homes() as home:
            to_check(home)
            handoff(home, "feat", "check", ALL_MET)
            call(action="settle", run="feat", node="check", outcome="accepted")
            before = record_bytes(home)
            duplicate = call(action="extend", run="feat", criteria=[{"id": "api", "text": "rewritten"}],
                             nodes=[node("more", depends_on=("check",), scope=("src/more.py",))])
            unchanged = record_bytes(home)
            extended = call(action="extend", run="feat", criteria=[{"id": "csv", "text": "CSV has a header"}],
                            nodes=[node("more", depends_on=("check",), scope=("src/more.py",))])
            handoff(home, "feat", "more")
            unverified = call(action="settle", run="feat", node="more", outcome="accepted")
        self.assertEqual(duplicate["reason"], "invalid_criteria", duplicate)
        self.assertEqual(unchanged, before)
        self.assertEqual(extended["status"], "ok", extended)
        self.assertEqual([item["id"] for item in extended["criteria"]["items"]], ["api", "docs", "csv"])
        self.assertEqual(unverified["verdict"], "unverified")
        self.assertIn("criteria_unobserved:csv", unverified["verdict_reasons"])
        self.assertIn("not checked yet: csv", unverified["say"])
        self.assertIn("2/3 criteria met", unverified["status_line"])

    def test_an_unread_check_records_no_criteria_and_does_not_verify_them(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", NODES, 1.0, criteria=CRITERIA)
        dag_run.calls_for(record, dag_run.derive(record, [], 1.0), free_slots=4, per_call=4, omh_home=Path("/h"),
                          now=1.0)
        dag_run.settle(record, dag_run.derive(record, [], 2.0), "build", "accepted", "", False,
                       read_handoff=lambda: (True, ""), now=2.0)
        dag_run.calls_for(record, dag_run.derive(record, [], 3.0), free_slots=4, per_call=4, omh_home=Path("/h"),
                          now=3.0)
        dag_run.settle(record, dag_run.derive(record, [], 4.0), "check", "accepted", "", False,
                       read_handoff=lambda: (True, ""), now=4.0,
                       read_criteria=lambda: (False, "backend_unanswered", []))
        derived = dag_run.derive(record, [], 5.0)
        check = next(item for item in record["nodes"] if item["id"] == "check")
        self.assertNotIn("criteria", check["attempts"][-1])
        self.assertEqual(dag_run.goal_verdict(record, derived),
                         ("unverified", ["handoff_not_checked:check", "criteria_unobserved:api,docs"]))

    def test_a_criterion_left_unmet_by_the_newest_accepted_check_is_named(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", NODES, 1.0, criteria=CRITERIA)
        for node_id, at in (("build", 2.0), ("check", 4.0)):
            dag_run.calls_for(record, dag_run.derive(record, [], at - 1), free_slots=4, per_call=4,
                              omh_home=Path("/h"), now=at - 1)
            dag_run.settle(record, dag_run.derive(record, [], at), node_id, "accepted", "", False,
                           read_handoff=lambda: (True, ""), now=at, read_criteria=lambda: (True, "", ALL_MET.split("\n")))
        # A record edited by hand past the settle rule: the verdict reads the statuses, not the outcome alone.
        next(item for item in record["nodes"] if item["id"] == "check")["attempts"][-1]["criteria"]["docs"] = "unmet"
        self.assertEqual(dag_run.goal_verdict(record, dag_run.derive(record, [], 5.0)),
                         ("unverified", ["criteria_unmet:docs"]))


class BackendTests(unittest.TestCase):
    def test_criterion_lines_come_back_with_the_file_test_in_one_command(self) -> None:
        answer = {"output": "OMH_HANDOFF_FILE\nCRITERION api: met - ran it\nCRITERION docs: met - grep\n",
                  "returncode": 0}
        with homes() as home, terminal_env():
            environment = Answers(answer)
            with Terminal("docker", environment).modules():
                to_check(home)
                accepted = call(action="settle", run="feat", node="check", outcome="accepted")
        self.assertEqual(accepted["verdict"], "verified", accepted)
        command = environment.calls[-1][0]
        self.assertIn(f"head -c {dag_run.MAX_HANDOFF_READ_BYTES} ", command)
        self.assertIn("grep -E", command)
        self.assertIn(f"tail -n {dag_tool.CRITERION_LINES_KEPT}", command)

    def test_an_interrupted_read_settles_nothing(self) -> None:
        interrupted = {"output": "[Command interrupted]", "returncode": 130, "hermes_interrupted": True}
        with homes() as home, terminal_env():
            environment = Answers({"output": "OMH_HANDOFF_FILE\n", "returncode": 0})
            with Terminal("docker", environment).modules():
                to_check(home)
                environment.answer = interrupted
                before = record_bytes(home)
                refused = call(action="settle", run="feat", node="check", outcome="failed")
                after = record_bytes(home)
        self.assertEqual(refused["reason"], "settle_interrupted", refused)
        self.assertEqual(after, before)

    @unittest.skipUnless(SANDBOX_SHELL, SANDBOX_SKIP)
    def test_a_real_shell_greps_the_lines_and_never_follows_a_link(self) -> None:
        with homes() as home, terminal_env(), TemporaryDirectory() as root:
            sandbox = Sandbox(Path(root))
            with Terminal("ssh", sandbox).modules():
                slots_table(home)
                call(action="define", run="feat", nodes=NODES, criteria=CRITERIA)
                record = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))
                built = sandbox.path(Path(dag_run.node_handoff(record, home.omh, "build")))
                built.parent.mkdir(parents=True, exist_ok=True)
                built.write_text("done", encoding="utf-8")
                call(action="settle", run="feat", node="build", outcome="accepted")
                inside = built.with_name("check.md")
                elsewhere = inside.with_name("elsewhere.md")
                elsewhere.write_text(ALL_MET, encoding="utf-8")
                os.symlink(elsewhere, inside)
                link = call(action="settle", run="feat", node="check", outcome="accepted")
                inside.unlink()
                inside.write_text("Notes.\n  - CRITERION api: met - ran it\nCRITERION docs: unmet - 404\n",
                                  encoding="utf-8")
                unmet = call(action="settle", run="feat", node="check", outcome="accepted")
                inside.write_text("Notes.\n" + ALL_MET, encoding="utf-8")
                accepted = call(action="settle", run="feat", node="check", outcome="accepted")
        self.assertEqual(link["reason"], "handoff_missing", link)
        self.assertEqual(unmet["reason"], "criteria_unmet", unmet)
        self.assertEqual(accepted["verdict"], "verified", accepted)


class ViewTests(unittest.TestCase):
    def test_the_count_stands_beside_the_verdict_wherever_it_is_drawn(self) -> None:
        from omh.plugin_bundle.omh.delegation_graph import build_delegation_graph
        from omh.plugin_bundle.omh.delegation_snapshot import end_block, lanes_of
        from omh.tui import dag_block
        from omh.tui.panels import dag_run_summary

        with homes() as home:
            to_check(home)
            handoff(home, "feat", "check", ALL_MET)
            done = call(action="settle", run="feat", node="check", outcome="accepted")
            graph = build_delegation_graph(home.omh, home.hermes, PARENT)
        self.assertEqual(dag_block.moment({"name": "omh_dag", "result": json.dumps(done)}, set()),
                         ("end · done · verified · 2/2 criteria met", "feat", []))
        self.assertEqual(graph["dag_criteria"], "2/2 criteria met")
        self.assertTrue(dag_run_summary(graph).endswith("· verified · 2/2 criteria met"), dag_run_summary(graph))
        self.assertTrue(end_block(graph, lanes_of(graph)).splitlines()[1].endswith("verified · 2/2 criteria met"))


if __name__ == "__main__":
    unittest.main()

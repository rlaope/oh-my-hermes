"""Goal criteria of a dag-ulw run: the goal split into separately checkable outcomes its verify node marks.

The model passes ``criteria`` at define (and extend); a verify node's task
asks for one ``CRITERION <id> #<attempt>: <status> - <evidence>`` line per criterion in
its handoff; `settle` reads those lines, keeps the status words, and refuses
an ``accepted`` that leaves one unmet or unobserved; the verdict needs every
one met. A run without criteria behaves exactly as it did before they
existed, pinned below against what origin/main produced.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from _delegation_state import PARENT, homes, start  # noqa: E402
from omh.plugin_bundle.omh import dag_run  # noqa: E402
from omh.plugin_bundle.omh.tools import dag_tool  # noqa: E402
from test_dag_tool import (  # noqa: E402
    PROMPT, SANDBOX_SHELL, SANDBOX_SKIP, Answers, Sandbox, Terminal, call, node, slots_table, terminal_env,
)
from test_dag_tool import handoff as _write_handoff  # noqa: E402

CRITERIA = [{"id": "api", "text": "The export API returns CSV"}, {"id": "docs", "text": "The docs page names the API"}]
NODES = [node("build", scope=("src/api.py",)), node("check", depends_on=("build",), role="verify")]
ALL_MET = "CRITERION api #T: met - curl /export returned text/csv\nCRITERION docs #T: met - grep found it in docs/api.md\n"
# Lines below say `#T` for "this attempt's token", which only the record knows (`dag_run.hand_out`); a parse test uses
# TOKEN in its place.
TOKEN = "ab12cd"


def token_of(record: dict, node_id: str) -> str:
    return dag_run.attempt_token(next(item for item in record["nodes"] if item["id"] == node_id))


def marked(text: str, token: str) -> str:
    return text.replace("#T", f"#{token}")


def record_of(home, run: str = "feat") -> dict:
    return json.loads(dag_run.record_path(home.omh, PARENT, run).read_text(encoding="utf-8"))


def record_bytes(home, run: str = "feat") -> bytes:
    return dag_run.record_path(home.omh, PARENT, run).read_bytes()


def last_attempt(record: dict, node_id: str) -> dict:
    return next(item for item in record["nodes"] if item["id"] == node_id)["attempts"][-1]


def handoff(home, run: str, node_id: str, text: str = "done") -> Path:
    """`test_dag_tool.handoff`, with `#T` in ``text`` made the token of the node's latest attempt."""
    path = dag_run.record_path(home.omh, PARENT, run)
    if "#T" in text and path.exists():
        record = json.loads(path.read_text(encoding="utf-8"))
        if any(item["id"] == node_id for item in record["nodes"]):
            text = marked(text, token_of(record, node_id))
    return _write_handoff(home, run, node_id, text)


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
            "too many": many,
            "duplicate id": [CRITERIA[0], {"id": "api", "text": "again"}],
            "unknown field": [{**CRITERIA[0], "weight": 2}],
            "missing text": [{"id": "api"}],
            "bad id": [{"id": "c_1", "text": "x"}],
            "bad id after folding": [{"id": "-C1", "text": "x"}],
            "duplicate by case": [{"id": "C1", "text": "x"}, {"id": "c1", "text": "y"}],
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

    def test_an_upper_case_id_is_read_in_lower_case(self) -> None:
        """Measured live: 6/6 first defines sent `C1`..`C8` and were refused."""
        upper = [{"id": "C1", "text": "The export API returns CSV"}, {"id": "C2", "text": "The docs page names it"}]
        with homes() as home:
            to_check(home, criteria=upper)
            stored = record_of(home)
            handoff(home, "feat", "check", "CRITERION C1 #T: met - curl returned csv\nCRITERION c2 #T: met - grep")
            done = call(action="settle", run="feat", node="check", outcome="accepted")
            again = call(action="extend", run="feat", criteria=[{"id": "c1", "text": "again"}],
                         nodes=[node("more", depends_on=("check",), scope=("src/more.py",))])
        self.assertEqual([item["id"] for item in stored["criteria"]], ["c1", "c2"])
        self.assertEqual((done["verdict"], done["criteria"]["met"]), ("verified", 2), done)
        self.assertEqual(again["reason"], "invalid_criteria", again)

    def test_a_criterion_takes_as_much_text_as_the_goal_and_the_record_keeps_room(self) -> None:
        """Measured live: the model merged conditions under the cap of 12 into a 190-character criterion."""
        self.assertEqual(dag_run.MAX_CRITERION_CHARS, dag_run.MAX_GOAL_CHARS)
        widest = [{"id": f"c{index}", "text": "t" * dag_run.MAX_CRITERION_CHARS} for index in range(dag_run.MAX_CRITERIA)]
        prompt = PROMPT + "x" * (dag_run.MAX_PROMPT_CHARS - len(PROMPT))
        nodes = [node(f"n{index}", prompt=prompt, label="L" * dag_run.MAX_LABEL_CHARS, scope=(f"src/f{index}.py",),
                      depends_on=(f"n{index - 1}",) if index else ()) for index in range(dag_run.MAX_NODES)]
        record = dag_run.new_record(PARENT, "feat", "n", "g" * dag_run.MAX_GOAL_CHARS, nodes, 1.0, criteria=widest)
        size = len(json.dumps(record, sort_keys=True).encode("utf-8"))
        self.assertLess(size, dag_run.MAX_RECORD_BYTES * 0.7, size)

    def test_an_empty_list_is_no_criteria(self) -> None:
        """A model that sends `criteria: []` gets the run it would get without them, not a refusal."""
        with homes() as home:
            to_check(home, criteria=[])
            stored = record_of(home)
            handoff(home, "feat", "check")
            done = call(action="settle", run="feat", node="check", outcome="accepted")
            extended = call(action="extend", run="feat", criteria=[],
                            nodes=[node("more", depends_on=("check",), scope=("src/more.py",))])
        self.assertNotIn("criteria", stored)
        self.assertEqual(stored["digest"], dag_run.definition_digest(NODES))
        self.assertEqual(done["verdict"], "verified")
        self.assertEqual(extended["status"], "ok", extended)
        self.assertNotIn("criteria", extended)

    def test_a_goal_over_the_limit_is_told_to_move_its_conditions_into_criteria(self) -> None:
        """Measured on main: the model packed the request's conditions into `goal`, was refused, and shortened them
        into a weaker one ("confirm it works on staging" became "staging check reported")."""
        with homes() as home:
            slots_table(home)
            refused = call(action="define", run="feat", nodes=NODES, goal="x" * (dag_run.MAX_GOAL_CHARS + 1))
            self.assertFalse(dag_run.record_path(home.omh, PARENT, "feat").exists())
        self.assertEqual((refused["status"], refused["reason"]), ("refused", "invalid_goal"), refused)
        self.assertEqual(refused["say"], dag_run.GOAL_REFUSED)
        for words in ("one short line", "put each checkable outcome in `criteria`", "the state the person asked for",
                      "not that a check was run or its result reported"):
            self.assertIn(words, refused["say"])
        schema = dag_tool.OMH_DAG_SCHEMA["parameters"]["properties"]["criteria"]["description"]
        self.assertIn("the state the person asked for, not that a check ran or was reported", schema)

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
            self.assertIn("extend adds nodes and new criteria", refused["say"])
            self.assertNotIn("use repair or extend to add nodes", refused["say"])


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
        token = re.search(r"CRITERION <id> #([0-9a-f]{6}): met \| unmet \| unobserved - <the command you ran and what "
                          r"it showed>", check)
        self.assertIsNotNone(token, check)
        self.assertIn(f"`#{token[1]}` is this attempt's mark", check)
        self.assertIn("`unmet` means you ran the check and the outcome is not there; `unobserved` means the check "
                      "could not run here, and the reason says why.", check)
        self.assertIn("producer claims are not verification evidence", check)


class SkillTextTests(unittest.TestCase):
    def test_the_reply_states_the_result_in_plain_words_and_criteria_keep_the_condition(self) -> None:
        from omh.skills.dag_ulw_skill import DEFINITION, run_loop_reference

        completion = next(line for line in DEFINITION.quality_bar if line.startswith("Completion is a claim"))
        self.assertIn("The reply states the result in plain words", completion)
        self.assertIn("verified, unverified, needs_repair, blocked, settle and node ids are record words", completion)
        self.assertIn("a criterion names the state the person asked for (it works on staging), not that a check was "
                      "run or its result reported", DEFINITION.opening_steps[0])
        self.assertIn("name a criterion by what it says, not its id", completion)
        self.assertIn('"it works on staging", not that a check was run or its result reported',
                      " ".join(run_loop_reference().split()))
        settle = next(step for step in DEFINITION.opening_steps if step.startswith("On each completion"))
        self.assertIn("a verify node with criteria is accepted only when every `CRITERION` line says met, failed when "
                      "one is unmet, blocked when one could not be checked here", settle)


class LineParsingTests(unittest.TestCase):
    def statuses(self, text: str, token: str = TOKEN) -> dict:
        return dag_run.criterion_statuses(marked(text, TOKEN).split("\n"), ["api", "docs"], token)

    def test_only_marked_lines_of_this_attempt_for_declared_ids_count_and_the_last_wins(self) -> None:
        cases = [
            ("CRITERION api #T: met - ran it\nCRITERION docs #T: unmet - 404", {"api": "met", "docs": "unmet"}),
            # An id the run does not declare is ignored.
            ("CRITERION extra #T: met - ran it\nCRITERION api #T: met - ok", {"api": "met", "docs": "unobserved"}),
            # `met` with nothing after it is not evidence.
            ("CRITERION api #T: met\nCRITERION docs #T: met -  ", {"api": "unobserved", "docs": "unobserved"}),
            # Prose that mentions a criterion has no line-start marker.
            ("The criterion api was met.\nCRITERION api #T was met - ok\nWe saw CRITERION api #T: met - x",
             {"api": "unobserved", "docs": "unobserved"}),
            # A later line overrides an earlier one, either way.
            ("CRITERION api #T: met - ok\nCRITERION api #T: unmet - broke again\nCRITERION docs #T: unmet - no\n"
             "CRITERION docs #T: met - fixed", {"api": "unmet", "docs": "met"}),
            # Bullets, spaces and backticks before the marker are fine; the status word ignores case.
            ("  - `CRITERION api #T: MET - ran x`\n* CRITERION docs #T: unobserved - no access",
             {"api": "met", "docs": "unobserved"}),
            # A status word must stand alone: `metric` is no `met`; the marker is upper case.
            ("CRITERION api #T: metric - x\ncriterion docs #T: met - lower-case marker",
             {"api": "unobserved", "docs": "unobserved"}),
            # The id reads in lower case.
            ("CRITERION API #T: met - ran it\nCRITERION Docs #T: unmet - 404", {"api": "met", "docs": "unmet"}),
            # A bare `unmet` or `unobserved` stands: it can only hold the run back.
            ("CRITERION api #T: unmet\nCRITERION docs #T: unobserved", {"api": "unmet", "docs": "unobserved"}),
            # A CRLF file and a BOM on its first line read as plain lines.
            ("\ufeffCRITERION api #T: met - ran it\r\nCRITERION docs #T: met - grep\r\n", {"api": "met", "docs": "met"}),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.statuses(text), expected)

    def test_a_line_of_another_attempt_or_with_no_token_never_counts(self) -> None:
        """Mutation: drop the token check, so a re-run is accepted on the lines another attempt left."""
        none = {"api": "unobserved", "docs": "unobserved"}
        self.assertEqual(self.statuses(ALL_MET, token="ffffff"), none)
        self.assertEqual(self.statuses(ALL_MET.replace(" #T", "")), none)
        self.assertEqual(self.statuses(ALL_MET.replace("#T", "#1")), none)  # an attempt number is no token
        self.assertEqual(self.statuses(ALL_MET, token=""), none)  # an attempt stored without a token counts no line
        self.assertEqual(self.statuses(ALL_MET.replace("#T", f"#{TOKEN.upper()}")), {"api": "met", "docs": "met"})

    def test_a_hedged_or_echoed_status_is_no_status(self) -> None:
        """Measured in review: each of these used to read as `met`."""
        for tail in (
            "met | unmet | unobserved - <the command you ran and what it showed>",  # the template, echoed
            "met/unmet - not sure",
            "met (not actually run)",
            "met?",
            "met -\u00a0",  # a no-break space is no evidence
            "met - \u3000 ",
            "met - **",
            "met\u00a0- ran it",
            "met - ran \x1b[32mok",  # an escape in the line: the backend could not read it the same way
            "met\u2028- ran it",  # a line separator inside the line
            "met\x0b- ran it",
            "met - ran\x00it",
            "unmet?",
            "unobserved (maybe)",
            "met - <the command you ran and what it showed>",  # the placeholder left as it is
            "met - <ran it>",
            "met - \u200b",  # a zero-width space: no letter or digit
            "met - -- ** --",
        ):
            with self.subTest(tail=tail):
                self.assertEqual(self.statuses(f"CRITERION api #T: {tail}")["api"], "unobserved")
        # Structure only, no phrase lists: these have a letter or digit and are no lone placeholder.
        for tail in ("met - not checked", "met: n/a", "met - ran <cmd> and saw 200", "met - ran it", "met: ran it", "met \u2013 ran it", "met\u2014ran it", "met-ran it"):
            with self.subTest(tail=tail):
                self.assertEqual(self.statuses(f"CRITERION api #T: {tail}")["api"], "met")


class SettleTests(unittest.TestCase):
    def test_accepted_needs_every_criterion_met_and_a_refusal_changes_nothing(self) -> None:
        """Mutation: accept with one unmet or unobserved, or write the attempt before refusing."""
        for text, reason, named in (
            ("CRITERION api #T: met - ok\nCRITERION docs #T: unmet - page missing", "criteria_unmet", "docs"),
            ("CRITERION api #T: met - ok\nCRITERION docs #T: met", "criteria_unobserved", "docs"),
            ("CRITERION api #T: unobserved - no network", "criteria_unobserved", "api, docs"),
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
                handoff(home, "feat", "check", "CRITERION api #T: met - ok\nCRITERION docs #T: unmet - 404")
                settled = call(action="settle", run="feat", node="check", outcome=outcome)
                self.assertEqual(last_attempt(record_of(home), "check")["criteria"], {"api": "met", "docs": "unmet"})
                self.assertEqual(settled["criteria"]["unmet"], ["docs"])
                self.assertIn("1/2 criteria met", settled["status_line"])
            with self.subTest(outcome=outcome, handoff="missing"), homes() as home:
                to_check(home)
                settled = call(action="settle", run="feat", node="check", outcome=outcome)
                self.assertEqual(settled["status"], "ok", settled)
                self.assertNotIn("criteria", last_attempt(record_of(home), "check"))

    def test_a_check_that_could_not_run_everything_is_refused_accepted_and_counted_when_blocked(self) -> None:
        """Measured on main: a verify node whose staging check could not run here was settled accepted with
        "reported", and the run came out verified. With criteria that settle is refused, and the blocked settle
        that follows still carries how far the goal got."""
        criteria = [{"id": f"c{index}", "text": f"Outcome {index} holds"} for index in range(1, dag_run.MAX_CRITERIA)]
        criteria.append({"id": "staging", "text": "It works on staging"})
        marked = "".join(f"CRITERION c{index} #T: met - test {index} passed\n" for index in range(1, dag_run.MAX_CRITERIA))
        marked += "CRITERION staging #T: unobserved - staging_check exit 3: no STAGING_TOKEN here\n"
        with homes() as home:
            to_check(home, criteria=criteria)
            handoff(home, "feat", "check", marked)
            refused = call(action="settle", run="feat", node="check", outcome="accepted",
                           reason="staging_check exit 3, reported")
            blocked = call(action="settle", run="feat", node="check", outcome="blocked", reason="no staging token")
        total = dag_run.MAX_CRITERIA
        self.assertEqual(refused["reason"], "criteria_unobserved", refused)
        self.assertEqual(blocked["state"], "needs_repair", blocked)
        self.assertEqual((blocked["criteria"]["total"], blocked["criteria"]["met"], blocked["criteria"]["unmet"],
                          blocked["criteria"]["unobserved"]), (total, total - 1, [], ["staging"]))
        self.assertEqual(blocked["criteria"]["items"][-1],
                         {"id": "staging", "text": "It works on staging", "status": "unobserved"})
        self.assertIn(f"{total - 1}/{total} criteria met", blocked["status_line"])
        self.assertIn(f"Goal criteria: {total - 1}/{total} criteria met; could not be checked: staging.", blocked["say"])

    def test_a_failed_producer_says_no_criteria_count_before_any_check(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=NODES, criteria=CRITERIA)
            failed = call(action="settle", run="feat", node="build", outcome="failed")
        self.assertEqual(failed["state"], "needs_repair")
        self.assertEqual(failed["criteria"]["met"], 0)
        self.assertNotIn("Goal criteria", failed["say"])

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
            handoff(home, "feat", "check", "CRITERION api #T: unmet - not a run with criteria")
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
                           read_handoff=lambda: (True, ""), now=at,
                           read_criteria=lambda: (True, "", marked(ALL_MET, token_of(record, "check")).split("\n")))
        # A record edited by hand past the settle rule: the verdict reads the statuses, not the outcome alone.
        next(item for item in record["nodes"] if item["id"] == "check")["attempts"][-1]["criteria"]["docs"] = "unmet"
        self.assertEqual(dag_run.goal_verdict(record, dag_run.derive(record, [], 5.0)),
                         ("unverified", ["criteria_unmet:docs"]))


class BackendTests(unittest.TestCase):
    def test_criterion_lines_come_back_with_the_file_test_in_one_command(self) -> None:
        with homes() as home, terminal_env():
            environment = Answers({"output": "OMH_HANDOFF_FILE\n", "returncode": 0})
            with Terminal("docker", environment).modules():
                to_check(home)
                environment.answer = self._answer(marked(ALL_MET, token_of(record_of(home), "check")).encode())
                accepted = call(action="settle", run="feat", node="check", outcome="accepted")
        self.assertEqual(accepted["verdict"], "verified", accepted)
        command = environment.calls[-1][0]
        self.assertIn(f"{{ head -c {dag_run.MAX_HANDOFF_READ_BYTES} ", command)
        for stage in ("{ LC_ALL=C tr '\\000' '\\001'; echo t$? >&3; }", "{ LC_ALL=C grep -F CRITERION; echo g$? >&3; }",
                      f"{{ tail -n {dag_run.CRITERION_LINES_KEPT}; echo l$? >&3; }}", "{ base64; echo b$? >&3; } >&4;",
                      f"echo {dag_tool._CRITERION_END}"):
            self.assertIn(stage, command)

    @staticmethod
    def _answer(data: bytes, *, end: bool = True, **fields: object) -> dict:
        encoded = base64.b64encode(data).decode()
        lines = ["OMH_HANDOFF_FILE", encoded[:40], encoded[40:], *([dag_tool._CRITERION_END] if end else [])]
        return {"output": "\n".join(lines) + "\n", "returncode": 0, **fields}

    def _settle_with(self, answer_for) -> dict:
        with homes() as home, terminal_env():
            environment = Answers({"output": "OMH_HANDOFF_FILE\n", "returncode": 0})
            with Terminal("docker", environment).modules():
                to_check(home)
                environment.answer = answer_for(token_of(record_of(home), "check"))
                return call(action="settle", run="feat", node="check", outcome="accepted")

    def test_a_cut_short_or_failed_read_is_unread_never_a_read(self) -> None:
        """Review probe D: a read Hermes timed out came back as whole lines of base64 that still decoded, and the
        dropped tail held the later `unmet` line that overrides the earlier `met`."""
        def cut(token: str) -> dict:
            data = marked("CRITERION api #T: met - first pass\nCRITERION docs #T: met - ok\n"
                          + "CRITERION note\n" * 6 + "CRITERION api #T: unmet - regression on the second run\n",
                          token).encode()
            whole = base64.b64encode(data[:57]).decode()  # 57 bytes encode to 76 characters, a whole line
            return {"output": f"OMH_HANDOFF_FILE\n{whole}\n[Command timed out after 10s]", "returncode": 124,
                    "hermes_timed_out": True}

        cases = {
            "timed out with decodable partial output": cut,
            "timed out with the end marker": lambda token: self._answer(marked(ALL_MET, token).encode(),
                                                                        returncode=124, hermes_timed_out=True),
            "a non-zero exit": lambda token: self._answer(marked(ALL_MET, token).encode(), returncode=1),
            "no end marker": lambda token: self._answer(marked(ALL_MET, token).encode(), end=False),
            "base64 missing": lambda token: {"output": "OMH_HANDOFF_FILE\nsh: base64: not found\n", "returncode": 1},
            "not base64": lambda token: {"output": f"OMH_HANDOFF_FILE\nnot base64!\nQQ\n{dag_tool._CRITERION_END}\n",
                                         "returncode": 0},
        }
        for label, answer_for in cases.items():
            with self.subTest(label):
                settled = self._settle_with(answer_for)
                # Unread: accepted stands with its handoff not checked, records nothing, and verifies nothing.
                self.assertEqual(settled["status"], "ok", settled)
                self.assertEqual(settled["verdict"], "unverified", settled)
                self.assertIn("handoff_not_checked:check", settled["verdict_reasons"])
                row = next(item for item in settled["nodes"] if item["id"] == "check")
                self.assertIs(row.get("handoff_checked"), False, row)
        # A file with no criterion line is a read that worked (grep's 1), with every criterion not checked.
        empty = self._settle_with(lambda token: {"output": f"OMH_HANDOFF_FILE\n\n{dag_tool._CRITERION_END}\n",
                                                 "returncode": 0})
        self.assertEqual(empty["reason"], "criteria_unobserved", empty)

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
                token = token_of(record_of(home), "check")
                elsewhere = inside.with_name("elsewhere.md")
                elsewhere.write_text(marked(ALL_MET, token), encoding="utf-8")
                os.symlink(elsewhere, inside)
                link = call(action="settle", run="feat", node="check", outcome="accepted")
                inside.unlink()
                inside.write_text(marked("Notes.\n  - CRITERION api #T: met - ran it\nCRITERION docs #T: unmet - 404\n",
                                         token), encoding="utf-8")
                unmet = call(action="settle", run="feat", node="check", outcome="accepted")
                inside.write_text("Notes.\n" + marked(ALL_MET, token), encoding="utf-8")
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


def _settle_path(record: dict, steps: list[tuple[str, str]], read=None) -> None:
    """Hand out and settle ``steps`` ((node, outcome)) through the engine, one second apart."""
    for index, (node_id, outcome) in enumerate(steps):
        at = 10.0 * (index + 1)
        dag_run.calls_for(record, dag_run.derive(record, [], at), free_slots=8, per_call=8, omh_home=Path("/h"),
                          now=at)
        dag_run.settle(record, dag_run.derive(record, [], at + 1), node_id, outcome, "", False,
                       read_handoff=lambda: (True, ""), now=at + 1,
                       read_criteria=(read or {}).get(
                           node_id, lambda: (True, "", marked(ALL_MET, token_of(record, node_id)).split("\n"))))


def told_token(result: dict) -> str:
    """The token the verify task in ``result``'s calls tells its child to write."""
    context = next(task["context"] for call_row in result["calls"] for task in call_row["tasks"])
    return re.search(r"CRITERION <id> #([0-9a-f]{6}):", context)[1]


class AttemptTests(unittest.TestCase):
    """A verify node's lines carry its attempt's own random token (`CRITERION <id> #<token>:`)."""

    def test_a_rerun_is_never_accepted_on_the_lines_its_previous_attempt_left(self) -> None:
        """Review probe A: attempt 1 wrote every criterion met and was settled failed; the re-run wrote nothing."""
        with homes() as home:
            to_check(home)
            first = token_of(record_of(home), "check")
            handoff(home, "feat", "check", ALL_MET)
            call(action="settle", run="feat", node="check", outcome="failed", reason="the curl failed")
            call(action="repair", run="feat", node="check", nodes=[node("fix", scope=("src/api.py",))])
            handoff(home, "feat", "fix")
            fixed = call(action="settle", run="feat", node="fix", outcome="accepted")
            rerun = call(action="settle", run="feat", node="check", outcome="accepted")
            handoff(home, "feat", "check", ALL_MET)
            accepted = call(action="settle", run="feat", node="check", outcome="accepted")
        second = told_token(fixed)
        self.assertNotEqual(second, first)
        self.assertEqual(rerun["reason"], "criteria_unobserved", rerun)
        self.assertIn(f"#{second}", rerun["say"])
        self.assertEqual((accepted["state"], accepted["verdict"]), ("done", "verified"), accepted)

    def test_lines_written_for_a_later_attempt_never_count(self) -> None:
        """Review probe E: attempt 1 also wrote lines for what it guessed attempt 2 would be."""
        with homes() as home:
            to_check(home)
            guesses = "".join(marked(ALL_MET, guess) for guess in ("2", "02", "1", "000000", "ffffff", "T"))
            handoff(home, "feat", "check", ALL_MET + guesses)
            call(action="settle", run="feat", node="check", outcome="failed")
            call(action="repair", run="feat", node="check", nodes=[node("fix", scope=("src/api.py",))])
            handoff(home, "feat", "fix")
            call(action="settle", run="feat", node="fix", outcome="accepted")
            rerun = call(action="settle", run="feat", node="check", outcome="accepted")
        self.assertEqual(rerun["reason"], "criteria_unobserved", rerun)

    def test_a_provider_error_retry_is_neither_read_nor_counted_and_hands_out_the_next_number(self) -> None:
        """Mutation: read the handoff on a provider-error retry, so the dead attempt records statuses."""
        with homes() as home:
            to_check(home)
            handoff(home, "feat", "check", ALL_MET)
            retried = call(action="settle", run="feat", node="check", outcome="failed", provider_error=True)
            first = record_of(home)
            stale = call(action="settle", run="feat", node="check", outcome="accepted")
        check = next(item for item in first["nodes"] if item["id"] == "check")
        self.assertEqual(check["attempts"][0]["outcome"], "retry")
        self.assertNotIn("criteria", check["attempts"][0])
        self.assertNotEqual(told_token(retried), check["attempts"][0]["token"])
        self.assertEqual(stale["reason"], "criteria_unobserved", stale)

    def test_a_provider_error_retry_reads_nothing(self) -> None:
        """Mutation: drop the retry exclusion, so a dead child's handoff is read (a backend call that can refuse)."""
        record = dag_run.new_record(PARENT, "feat", "", "", NODES, 1.0, criteria=CRITERIA)
        _settle_path(record, [("build", "accepted")])
        dag_run.calls_for(record, dag_run.derive(record, [], 30.0), free_slots=8, per_call=8, omh_home=Path("/h"),
                          now=30.0)
        reads: list[str] = []
        happened = dag_run.settle(record, dag_run.derive(record, [], 31.0), "check", "failed", "", True,
                                  read_handoff=lambda: reads.append("handoff") or (True, ""), now=31.0,
                                  read_criteria=lambda: reads.append("criteria") or (True, "", []))
        self.assertEqual((happened, reads), ("retry", []))

    def test_a_parked_check_resumes_under_the_next_number(self) -> None:
        with homes() as home:
            to_check(home)
            parked = token_of(record_of(home), "check")
            wake = time.time() + 120
            call(action="settle", run="feat", node="check", outcome="parked", handle="ci-run-7", wake_at=wake)
            with patch.object(dag_tool.time, "time", return_value=wake + 1):
                woken = call(action="ready", run="feat")
            with patch.object(dag_tool.time, "time", return_value=wake + 2 + dag_run.HANDOUT_STALE_SECONDS):
                reoffered = call(action="ready", run="feat")
        context = next(task["context"] for call_row in woken["calls"] for task in call_row["tasks"])
        self.assertIn("Resume the still-running wait: ci-run-7", context)
        self.assertNotEqual(told_token(woken), parked)
        # Offering the same attempt again (no child took it) keeps its token.
        self.assertEqual(told_token(reoffered), told_token(woken))

    def test_the_parent_doing_a_check_itself_is_told_the_line_and_its_token(self) -> None:
        """Mutation: drop the parent-lane criterion line, so a one-shot parent never learns the token."""
        with homes() as home, patch.object(dag_tool, "_single_query_session", return_value=True):
            slots_table(home)
            (home.hermes / "config.yaml").write_text("delegation:\n  oneshot_max_children: 2\n", encoding="utf-8")
            call(action="define", run="feat", nodes=NODES, criteria=CRITERIA)
            start(home, "child-build", "sa-build", "Node build [dag:feat/build]", now=time.time())
            start(home, "child-other", "sa-other", "Look something up", now=time.time())
            handoff(home, "feat", "build")
            mine = call(action="settle", run="feat", node="build", outcome="accepted")
            token = token_of(record_of(home), "check")
            handoff(home, "feat", "check", ALL_MET)
            done = call(action="settle", run="feat", node="check", outcome="accepted")
        self.assertEqual(mine["for_parent"], ["check"], mine)
        self.assertIn(f"In check's handoff write one line per criterion (api, docs): `CRITERION <id> #{token}: met",
                      mine["say"])
        self.assertEqual(done["verdict"], "verified", done)

    def test_the_unmet_say_names_what_checks_again(self) -> None:
        """Review probe 4: a verify node inside another node's repair group is superseded, never run again."""
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=NODES, criteria=CRITERIA)
            call(action="settle", run="feat", node="build", outcome="failed")
            call(action="repair", run="feat", node="build",
                 nodes=[node("fix", scope=("src/api.py",)), node("reverify", depends_on=("fix",), role="verify")])
            handoff(home, "feat", "fix")
            call(action="settle", run="feat", node="fix", outcome="accepted")
            handoff(home, "feat", "reverify", "CRITERION api #T: unmet - 500\nCRITERION docs #T: met - ok")
            grouped = call(action="settle", run="feat", node="reverify", outcome="accepted")
        self.assertEqual(grouped["reason"], "criteria_unmet", grouped)
        self.assertIn("part of build's repair group and does not run again; check checks the work", grouped["say"])
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("build", scope=("src/api.py",))], criteria=CRITERIA)
            call(action="settle", run="feat", node="build", outcome="failed")
            call(action="repair", run="feat", node="build",
                 nodes=[node("fix", scope=("src/api.py",)), node("reverify", depends_on=("fix",), role="verify")])
            handoff(home, "feat", "fix")
            call(action="settle", run="feat", node="fix", outcome="accepted")
            handoff(home, "feat", "reverify", "CRITERION api #T: unmet - 500")
            alone = call(action="settle", run="feat", node="reverify", outcome="accepted")
        self.assertIn("does not run again, so put a role=verify node in the new group", alone["say"])
        with homes() as home:
            to_check(home)
            handoff(home, "feat", "check", "CRITERION api #T: unmet - 500\nCRITERION docs #T: met - ok")
            own = call(action="settle", run="feat", node="check", outcome="accepted")
            call(action="settle", run="feat", node="check", outcome="failed")
            call(action="repair", run="feat", node="check",
                 nodes=[node("fix", scope=("src/api.py",)), node("recheck", depends_on=("fix",), role="verify")])
            handoff(home, "feat", "fix")
            call(action="settle", run="feat", node="fix", outcome="accepted")
            handoff(home, "feat", "recheck", "CRITERION api #T: unmet - 500")
            under_verify = call(action="settle", run="feat", node="recheck", outcome="accepted")
        self.assertIn("this check runs again once they pass", own["say"])
        self.assertIn("check runs again once they pass", under_verify["say"])


class ViewAgreementTests(unittest.TestCase):
    def test_the_views_count_each_check_by_its_last_attempt_as_the_verdict_does(self) -> None:
        """Review probe C: attempt 1 failed with every criterion met; the accepted re-run's handoff was not read."""
        record = dag_run.new_record(PARENT, "feat", "", "", NODES, 1.0, criteria=CRITERIA)
        _settle_path(record, [("build", "accepted"), ("check", "failed")])
        dag_run.repair(record, dag_run.derive(record, [], 25.0), "check", [node("fix", scope=("src/api.py",))], 25.0)
        _settle_path(record, [("fix", "accepted"), ("check", "accepted")],
                     read={"check": lambda: (False, "backend_unanswered", [])})
        derived = dag_run.derive(record, [], 100.0)
        result = json.loads(dag_tool._result("status", record, derived, None, now=100.0))
        self.assertEqual(dag_run.goal_verdict(record, derived),
                         ("unverified", ["handoff_not_checked:check", "criteria_unobserved:api,docs"]))
        self.assertIn("0/2 criteria met", result["status_line"])
        self.assertIn("Goal criteria: 0/2 criteria met; not checked yet: api, docs.", result["say"])
        self.assertEqual([item["status"] for item in result["criteria"]["items"]], ["unchecked", "unchecked"])

    def test_a_superseded_check_counts_for_nothing(self) -> None:
        """Mutation: drop the superseded skip, so a replaced repair group's check still shows its read."""
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=NODES, criteria=CRITERIA)
            call(action="settle", run="feat", node="build", outcome="failed")
            call(action="repair", run="feat", node="build",
                 nodes=[node("fix", scope=("src/api.py",)), node("reverify", depends_on=("fix",), role="verify")])
            handoff(home, "feat", "fix")
            call(action="settle", run="feat", node="fix", outcome="accepted")
            handoff(home, "feat", "reverify", ALL_MET)
            call(action="settle", run="feat", node="reverify", outcome="failed")
            call(action="repair", run="feat", node="reverify", nodes=[node("fix2", scope=("src/api.py",))])
            handoff(home, "feat", "fix2")
            settled = call(action="settle", run="feat", node="fix2", outcome="accepted")
        self.assertEqual({row["id"]: row["state"] for row in settled["nodes"]}["reverify"], "superseded")
        self.assertIn("0/2 criteria met", settled["status_line"])

    def test_a_failed_check_is_verify_failed_whatever_its_criteria_say(self) -> None:
        """Mutation: add criteria reasons to a verify_failed verdict, which turns it into unverified."""
        record = dag_run.new_record(PARENT, "feat", "", "", NODES, 1.0, criteria=CRITERIA)
        _settle_path(record, [("build", "accepted"), ("check", "failed")],
                     read={"check": lambda: (True, "", ["CRITERION api #T: unmet - 500"])})
        self.assertEqual(dag_run.goal_verdict(record, dag_run.derive(record, [], 50.0)),
                         ("verify_failed", ["verify_failed:check"]))


class ReadTests(unittest.TestCase):
    @unittest.skipIf(sys.platform == "win32", "needs a POSIX character device")
    def test_only_a_regular_file_is_read_on_this_host(self) -> None:
        """Mutation: drop the S_ISREG check, so a device reads as an empty handoff."""
        self.assertIsNone(dag_tool._host_head(Path(os.devnull)))

    @unittest.skipIf(sys.platform == "win32" or getattr(os, "geteuid", lambda: 0)() == 0,
                     "needs POSIX permissions and a user that is not root")
    def test_a_handoff_that_exists_but_cannot_be_opened_has_its_own_say(self) -> None:
        with homes() as home:
            to_check(home)
            path = handoff(home, "feat", "check", ALL_MET)
            path.chmod(0)
            try:
                refused = call(action="settle", run="feat", node="check", outcome="accepted")
                failed = call(action="settle", run="feat", node="check", outcome="failed")
                stored = record_of(home)
            finally:
                path.chmod(0o600)
        self.assertEqual(refused["reason"], dag_run.HANDOFF_UNREADABLE, refused)
        self.assertIn("is there but could not be opened", refused["say"])
        self.assertEqual(failed["status"], "ok", failed)
        self.assertNotIn("criteria", last_attempt(stored, "check"))

    def test_a_record_with_malformed_criteria_is_not_read(self) -> None:
        """Mutation: drop the record-shape check, so a hand-edited record reaches the views."""
        record = dag_run.new_record(PARENT, "feat", "", "", NODES, 1.0, criteria=CRITERIA)
        with TemporaryDirectory() as folder:
            path = Path(folder) / "feat.json"
            dag_run.write_run(path, record)
            self.assertIsNotNone(dag_run.read_run(path))
            for criteria in ("api", [{"id": "API", "text": "t"}], [CRITERIA[0], CRITERIA[0]], [{"id": "a", "text": 1}],
                             ["api"]):
                with self.subTest(criteria=criteria):
                    dag_run.write_run(path, {**record, "criteria": criteria})
                    self.assertIsNone(dag_run.read_run(path))

    @unittest.skipUnless(SANDBOX_SHELL, SANDBOX_SKIP)
    def test_the_host_and_a_terminal_read_the_same_bytes_the_same_way(self) -> None:
        """A NUL, invalid UTF-8, CRLF, a BOM, an escape or a line separator never reads differently on either side."""
        contents = {
            "nul and invalid utf-8": b"\x00\xff\xfe bytes\nCRITERION api #T: met - ran it\x00\nCRITERION docs #T: "
                                     b"met - grep \xff found it\n",
            "crlf and bom": "\ufeffCRITERION api #T: met - ran it\r\nCRITERION docs #T: unmet - 404\r\n".encode(),
            "escape": b"CRITERION api #T: met - \x1b[32mok\x1b[0m\n\x1b[0mCRITERION docs #T: met - ran it\n",
            "separators": "CRITERION api #T: met\u2028- ran it\nCRITERION docs #T: met\x0b- x\n".encode(),
            "bell": b"CRITERION api #T: met - ran it\x07\nCRITERION docs #T: met - ok\n",
            "line separators in the evidence": "CRITERION api #T: met - ran\u2028it\nCRITERION docs #T: met - a\u2029b\n"
                                               "CRITERION api #T: met - ok\n".encode(),
            # The last lines naming the marker are kept, the same number on both sides: docs' only line is dropped.
            "past the kept lines": b"CRITERION docs #T: met - early\n" + b"CRITERION api #T: met - ok\n" * 70,
        }
        ids = ["api", "docs"]
        contents = {label: data.replace(b"#T", f"#{TOKEN}".encode()) for label, data in contents.items()}
        expected = {"line separators in the evidence": {"api": "met", "docs": "unobserved"},
                    "past the kept lines": {"api": "met", "docs": "unobserved"}}
        for label, data in contents.items():
            with self.subTest(label), TemporaryDirectory() as root, terminal_env():
                sandbox = Sandbox(Path(root))
                told = "/sandbox-home/dev/check.md"
                sandbox.path(Path(told)).write_bytes(data)
                host_file = Path(root) / "host.md"
                host_file.write_bytes(data)
                with Terminal("ssh", sandbox).modules():
                    found, unread, lines = dag_tool.backend_criterion_lines(told, "task")
                host = dag_run.criterion_statuses(dag_run.criterion_lines(dag_tool._host_head(host_file)), ids, TOKEN)
                self.assertEqual((found, unread), (True, ""))
                self.assertEqual(dag_run.criterion_statuses(lines, ids, TOKEN), host)
                if label in expected:
                    self.assertEqual(host, expected[label])

    def test_the_host_keeps_the_last_marked_lines_and_refuses_line_separators(self) -> None:
        """Mutations: keep every marked line on the host, or let U+2028 / U+2029 into a criterion line."""
        ids = ["api", "docs"]
        many = (f"CRITERION docs #{TOKEN}: met - early\n" + f"CRITERION api #{TOKEN}: met - ok\n" * 70).encode()
        self.assertEqual(len([line for line in dag_run.criterion_lines(many) if line]), dag_run.CRITERION_LINES_KEPT)
        self.assertEqual(dag_run.criterion_statuses(dag_run.criterion_lines(many), ids, TOKEN),
                         {"api": "met", "docs": "unobserved"})
        for separator in ("\u2028", "\u2029", "\x85"):
            with self.subTest(separator=separator):
                line = f"CRITERION api #{TOKEN}: met - ran{separator}it"
                self.assertIsNone(dag_run.criterion_status(line, ids, TOKEN))
        nul = (b"\x00\xff\xfe bytes\nCRITERION api #T: met - ran it\x00\nCRITERION docs #T: met - grep \xff found\n"
               .replace(b"#T", f"#{TOKEN}".encode()))
        self.assertEqual(dag_run.criterion_statuses(dag_run.criterion_lines(nul), ids, TOKEN),
                         {"api": "unobserved", "docs": "met"})


if __name__ == "__main__":
    unittest.main()

"""A dag node's `review_focus`: what the parent will look for when it reads the node's work, and the shared-machine
line every writing build node is given.

The focus is one optional plain line. It reaches the node's own task right after its prompt, a verify node's task
lists the focus of each producer it follows, and a code-writing build node without one is linted (advice only).
"""

from __future__ import annotations

import time
import unittest

from _local_package import load_local_package

load_local_package()

from _delegation_state import PARENT, homes  # noqa: E402
from omh.plugin_bundle.omh import dag_run  # noqa: E402
from test_dag_tool import PROMPT, call, handoff, node, slots_table  # noqa: E402

FOCUS_PREFIX = "Review focus (what the parent will check when it reads your work): "
VERIFY_HEADING = "Review focus the producers were given (judge their work on these too):"
SHARED_MACHINE = ("Other agents share this machine: run only the builds and tests you need at once, and before you stop, "
                  "stop the background jobs you started and remove the temporary files you created.")


def focused(raw: dict, focus: object) -> dict:
    return {**raw, "review_focus": focus}


def context_of(record: dict, node_id: str, home) -> str:
    target = next(item for item in record["nodes"] if item["id"] == node_id)
    return dag_run.task_for(record, target, home.omh, dag_run.derive(record, [], time.time()))["context"]


class ReviewFocusFieldTests(unittest.TestCase):
    def test_define_stores_the_focus_as_one_stripped_line(self) -> None:
        with homes() as home:
            slots_table(home)
            result = call(action="define", run="feat", nodes=[
                focused(node("api", scope=("src/api.py",)), "  the 24px toolbar icon\n  is still recognizable  ")])
            self.assertEqual(result["status"], "ok", result)
            stored = dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))
        self.assertEqual(stored["nodes"][0]["review_focus"], "the 24px toolbar icon is still recognizable")

    def test_blank_or_null_is_absent_and_keeps_the_digest(self) -> None:
        plain = dag_run.new_record(PARENT, "feat", "", "", [node("api", scope=("a.py",))], 0)
        for value in ("", "   ", None):
            with self.subTest(value=value):
                record = dag_run.new_record(PARENT, "feat", "", "", [focused(node("api", scope=("a.py",)), value)], 0)
                self.assertNotIn("review_focus", record["nodes"][0])
                self.assertEqual(record["digest"], plain["digest"])
        given = dag_run.new_record(PARENT, "feat", "", "", [focused(node("api", scope=("a.py",)), "no new bytes")], 0)
        self.assertNotEqual(given["digest"], plain["digest"])

    def test_the_limit_is_400_characters_korean_included(self) -> None:
        for text in ("x" * 400, "가" * 400, "  " + "y" * 400 + "  "):
            with self.subTest(length=len(text.strip())):
                record = dag_run.new_record(PARENT, "feat", "", "", [focused(node("api"), text)], 0)
                self.assertEqual(record["nodes"][0]["review_focus"], text.strip())

    def test_an_overlong_or_garbage_value_is_refused(self) -> None:
        for value in ("x" * 401, "가" * 401, "\n\n", "\t\n", "ok\x00", "bell\x07", 7, ["a"], {"a": 1}):
            with self.subTest(value=repr(value)[:20]), homes():
                result = call(action="define", run="feat", nodes=[focused(node("api"), value)])
                self.assertEqual((result["status"], result["reason"]), ("refused", "invalid_review_focus"), result)
                self.assertIn("Node api", result["say"])

    def test_repair_and_extend_take_it_and_a_repair_inherits_nothing(self) -> None:
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[
                focused(node("api", scope=("a.py",)), "the API keeps its old field names"),
                node("verify", role="verify", depends_on=("api",), label="Verify")])
            call(action="settle", run="feat", node="api", outcome="failed")
            repaired = call(action="repair", run="feat", node="api", nodes=[
                node("api-fix", scope=("a.py",)), focused(node("api-doc", scope=("b.py",)), "b.py reads as before")])
            self.assertEqual(repaired["status"], "ok", repaired)
            for node_id in ("api-fix", "api-doc", "verify"):
                handoff(home, "feat", node_id)
                call(action="settle", run="feat", node=node_id, outcome="accepted")
            extended = call(action="extend", run="feat", nodes=[
                focused(node("craft", depends_on=("verify",), scope=("craft.py",)), "craft output matches"),
                node("verify-output", role="verify", depends_on=("craft",), label="Verify output")])
            self.assertEqual(extended["status"], "ok", extended)
            stored = {item["id"]: item for item in
                      dag_run.read_run(dag_run.record_path(home.omh, PARENT, "feat"))["nodes"]}
        self.assertNotIn("review_focus", stored["api-fix"])
        self.assertEqual(stored["api-doc"]["review_focus"], "b.py reads as before")
        self.assertEqual(stored["craft"]["review_focus"], "craft output matches")


class ReviewFocusTaskTests(unittest.TestCase):
    def test_the_focus_line_follows_the_prompt(self) -> None:
        with homes() as home:
            record = dag_run.new_record(PARENT, "feat", "", "", [
                focused(node("api", scope=("src/api.py",)), "가나다 no new prompt bytes in the frozen head"),
                node("ui", scope=("src/ui.py",))], time.time())
            api = context_of(record, "api", home)
            ui = context_of(record, "ui", home)
        self.assertTrue(api.startswith(
            f"{PROMPT}\n\n{FOCUS_PREFIX}가나다 no new prompt bytes in the frozen head\n\n"), api[:400])
        self.assertTrue(ui.startswith(f"{PROMPT}\n\nHandoff:"), ui[:400])
        self.assertNotIn("Review focus", ui)

    def test_a_verify_task_lists_each_producers_focus_and_its_own_once(self) -> None:
        with homes() as home:
            record = dag_run.new_record(PARENT, "feat", "", "", [
                focused(node("api", scope=("src/api.py",)), "old clients still parse the reply"),
                node("ui", scope=("src/ui.py",)),
                focused(node("docs", category="writing", scope=("docs/api.md",)), "every example runs"),
                focused(node("verify", role="verify", depends_on=("api", "ui", "docs"), label="Verify"),
                        "the full goal, not one node"),
            ], time.time())
            context = context_of(record, "verify", home)
        lines = context.split("\n")
        start = lines.index(VERIFY_HEADING)
        self.assertEqual(lines[start + 1:start + 3],
                         ["- api: old clients still parse the reply", "- docs: every example runs"])
        self.assertFalse(lines[start + 3].startswith("- "), lines[start + 3])
        self.assertNotIn("- ui:", context)
        self.assertEqual(context.count("the full goal, not one node"), 1)
        self.assertTrue(context.startswith(f"{PROMPT}\n\n{FOCUS_PREFIX}the full goal, not one node\n\n"))

    def test_a_verify_task_without_any_focus_has_no_heading(self) -> None:
        with homes() as home:
            record = dag_run.new_record(PARENT, "feat", "", "", [
                node("api", scope=("src/api.py",)),
                node("verify", role="verify", depends_on=("api",), label="Verify")], time.time())
            context = context_of(record, "verify", home)
        self.assertNotIn("Review focus", context)

    def test_a_record_stored_before_the_field_runs_unchanged(self) -> None:
        with homes() as home:
            record = dag_run.new_record(PARENT, "feat", "", "", [
                node("api", scope=("src/api.py",)),
                node("verify", role="verify", depends_on=("api",), label="Verify")], time.time())
            for item in record["nodes"]:
                self.assertNotIn("review_focus", item)
            before = dag_run.definition_digest(record["nodes"])
            context = context_of(record, "verify", home)
        self.assertEqual(before, record["digest"])
        self.assertNotIn(VERIFY_HEADING, context)


class ReviewFocusLintTests(unittest.TestCase):
    def test_only_a_code_writing_build_node_without_focus_is_linted(self) -> None:
        record = dag_run.new_record(PARENT, "feat", "", "", [
            node("base", role="baseline", scope=("base.log.py",)),
            node("api", depends_on=("base",), scope=("src/api.py",)),
            focused(node("ui", depends_on=("base",), scope=("src/ui.py",)), "the 24px icon is recognizable"),
            node("docs", category="writing", depends_on=("base",), scope=("docs/api.md",)),
            node("plain", depends_on=("base",)),
            node("rev", role="review", category="review", depends_on=("api", "ui"), scope=("review.py",)),
            node("verify", role="verify", depends_on=("api", "ui", "docs", "plain", "rev")),
        ], time.time())
        found = [item for item in record["lint"] if item.startswith("no_review_focus:")]
        self.assertEqual(found, ["no_review_focus:api"])

    def test_the_lint_never_refuses(self) -> None:
        with homes() as home:
            slots_table(home)
            result = call(action="define", run="feat", nodes=[node("api", scope=("src/api.py",))])
        self.assertEqual(result["status"], "ok", result)
        self.assertIn("no_review_focus:api", result["lint"])


class SharedMachineLineTests(unittest.TestCase):
    def test_only_a_build_node_with_a_write_scope_gets_the_line(self) -> None:
        with homes() as home:
            record = dag_run.new_record(PARENT, "feat", "", "", [
                node("api", scope=("src/api.py",)),
                node("plain"),
                {**node("explore", label="Explore the parser", role="review"), "read_only": True},
                node("rev", role="review", category="review", depends_on=("api",), scope=("review.md",)),
                node("verify", role="verify", depends_on=("api", "rev")),
            ], time.time())
            contexts = {item["id"]: context_of(record, item["id"], home) for item in record["nodes"]}
        self.assertLess(len(SHARED_MACHINE), 200)
        api = contexts.pop("api")
        self.assertEqual(api.count(SHARED_MACHINE), 1)
        self.assertLess(api.index("Commit only your own SCOPE paths"), api.index(SHARED_MACHINE))
        self.assertLess(api.index(SHARED_MACHINE), api.index("Stay inside your SCOPE"))
        for node_id, context in contexts.items():
            with self.subTest(node=node_id):
                self.assertNotIn(SHARED_MACHINE, context)


if __name__ == "__main__":
    unittest.main()

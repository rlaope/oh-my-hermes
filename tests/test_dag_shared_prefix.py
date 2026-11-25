"""Sibling dag tasks of one run start with the same bytes: the run-wide block first, the node's own block after it.

A provider prompt cache serves only an exact byte prefix, so `dag_run.task_for` puts the run goal and the commit,
the scope rule (the same bytes for every node of the run, whatever its role) ahead of the node's prompt; lines
only some nodes get (commit and shared-machine rules, review focus) stay in the node block.
"""

from __future__ import annotations

import os
import time
import unittest

from _local_package import load_local_package

load_local_package()

from _delegation_state import PARENT, homes  # noqa: E402
from omh.plugin_bundle.omh import dag_run  # noqa: E402
from test_dag_tool import node  # noqa: E402

GOAL = "Ship the export API with docs"
HEAD = "\n".join([
    f"Run goal (saved):\n{GOAL}\n",
    "The run goal is acceptance context, not permission to widen your SCOPE.",
    "",
    "Stay inside your SCOPE: other parts of this run work at the same time. If you cannot finish, "
    "say plainly that you are blocked and why; do not report blocked work as done.",
    "",
    "",
])
RULES = (("Commit only your own SCOPE paths: stage them by name (`git add -- <paths>`), never `git add -A`, "
          "`git add .` or `git commit -a`, and never `git stash`; the index and stash are shared with the parallel "
          "parts."),
         ("Other agents share this machine: run only the builds and tests you need at once, and before you stop, "
          "stop the background jobs you started and remove the temporary files you created."))
ESCALATE = ("If the task turns on a judgement you cannot settle with confidence (a design choice, a root cause you "
            "cannot pin down), do not guess: before editing, write ESCALATE: <the question> and what you found into "
            "the handoff, and stop.")


def _sample() -> dict:
    """A 3-node run: two sibling build nodes with their own prompts, and a verify node over both."""
    return dag_run.new_record(PARENT, "feat", "Feature", GOAL, [
        {**node("api", scope=("src/api.py",)), "prompt": "TASK: build the export API\nSTOP WHEN: green",
         "review_focus": "old clients still parse the reply"},
        {**node("docs", scope=("docs/api.md",)), "prompt": "TASK: document the export API\nSTOP WHEN: done"},
        node("verify", role="verify", depends_on=("api", "docs")),
    ], time.time())


def _contexts(record: dict, home) -> dict[str, str]:
    derived = dag_run.derive(record, [], time.time())
    return {str(item["id"]): dag_run.task_for(record, item, home.omh, derived)["context"] for item in record["nodes"]}


class SharedPrefixTests(unittest.TestCase):
    def test_sibling_tasks_share_the_whole_run_wide_block(self) -> None:
        with homes() as home:
            record = _sample()
            contexts = _contexts(record, home)
        api, docs = contexts["api"], contexts["docs"]
        shared = os.path.commonprefix([api, docs])
        self.assertTrue(api.startswith(HEAD), api[:600])
        self.assertTrue(docs.startswith(HEAD), docs[:600])
        self.assertGreaterEqual(len(shared), len(HEAD))
        # The node block starts right after the head: the prompts differ from their first byte.
        self.assertEqual(shared, HEAD + "TASK: ")

    def test_every_line_stays_and_only_the_order_changes(self) -> None:
        with homes() as home:
            record = _sample()
            context = _contexts(record, home)["api"]
            handoff = dag_run.node_handoff(record, home.omh, "api")
        self.assertEqual(context, HEAD + "\n".join([
            "TASK: build the export API\nSTOP WHEN: green", "",
            f"{dag_run.REVIEW_FOCUS_PREFIX}old clients still parse the reply", "",
            f"Handoff: before you stop, write your report to {handoff}: what you did, the files you changed, "
            "what VERIFY showed, and anything still open. The parent reads that file and your final message.",
            ESCALATE, *RULES,
        ]))

    def test_every_role_mix_shares_the_same_head_with_or_without_a_goal(self) -> None:
        mixes = {
            "writer+writer": ({}, {}),
            "writer+verify": ({}, {"role": "verify"}),
            "writer+review": ({}, {"role": "review"}),
            "writer+baseline": ({}, {"role": "baseline"}),
            "read_only+writer": ({"read_only": True, "write_scope": []}, {}),
        }
        for goal in (GOAL, None):
            heads = set()
            for name, (first, second) in mixes.items():
                with self.subTest(goal=goal, mix=name), homes() as home:
                    raw = [{**node("a", scope=("src/a.py",)), "prompt": "TASK: a", "review_focus": "a focus", **first},
                           {**node("b", scope=("src/b.py",)), "prompt": "TASK: b", **second}]
                    record = dag_run.new_record(PARENT, "mix", "Mix", goal, raw, time.time())
                    contexts = _contexts(record, home)
                    head = contexts["a"].split("\n\nTASK: ")[0] + "\n\n"
                    shared = os.path.commonprefix([contexts["a"], contexts["b"]])
                    self.assertIn("Stay inside your SCOPE", head)
                    self.assertGreaterEqual(len(shared), len(head))
                    self.assertTrue(contexts["b"].startswith(head))
                    heads.add(head)
            self.assertEqual(len(heads), 1, heads)
            self.assertEqual(heads.pop(), HEAD if goal else HEAD.split("\n\n", 2)[-1])

    def test_the_goal_keeps_its_marker(self) -> None:
        with homes() as home:
            record = _sample()
            task = dag_run.task_for(record, record["nodes"][1], home.omh, dag_run.derive(record, [], time.time()))
        self.assertEqual(task["goal"], "Node docs [dag:feat/docs]")

    def test_a_call_with_sibling_tasks_notes_that_their_start_is_not_staggered(self) -> None:
        with homes() as home:
            record = _sample()
            now = time.time()
            calls, _ = dag_run.calls_for(record, dag_run.derive(record, [], now), free_slots=4, per_call=4,
                                         omh_home=home.omh, now=now)
            single = _sample()
            alone, _ = dag_run.calls_for(single, dag_run.derive(single, [], now), free_slots=4, per_call=1,
                                         omh_home=home.omh, now=now)
        self.assertEqual([len(item["tasks"]) for item in calls], [2])
        self.assertEqual(calls[0]["note"], dag_run.SAME_LAYER_NOTE)
        self.assertNotIn("sleep", dag_run.SAME_LAYER_NOTE)
        self.assertEqual([len(item["tasks"]) for item in alone], [1, 1])
        self.assertTrue(all("note" not in item for item in alone))


if __name__ == "__main__":
    unittest.main()

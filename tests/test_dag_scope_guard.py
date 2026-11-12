"""`pre_tool_call` holds a dag-ulw node's child to the write scope its node declared.

The run is defined through `omh_dag` and the children start through the
delegation ledger's own `subagent_start` observer with the payload Hermes
sends, so the `[dag:run/node]` binding is the one a live run produces. The
write goes through the real hook entry with the child's session id.
"""

from __future__ import annotations

import os
import time
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

import test_dag_tool as dag_tests  # noqa: E402  (helpers only; a module import keeps its tests out of this file)
from _delegation_state import PARENT, homes, start  # noqa: E402
import json  # noqa: E402

from omh.plugin_bundle.omh import dag_run, dag_scope_guard, toolcall_rules  # noqa: E402
from omh.plugin_bundle.omh.hooks import nudge_budget, session_attendance  # noqa: E402
from omh.plugin_bundle.omh.hooks.tool_hooks import pre_tool_call  # noqa: E402

RUN = "feat"
NODES = [
    dag_tests.node("api", scope=("src/api.py", "src/api/")),
    dag_tests.node("ui", category="unspecified-low", scope=("src/ui.py",)),
    dag_tests.node("docs", category="writing", depends_on=("api",), scope=("docs/*.md",)),
    dag_tests.node("verify", category="unspecified-high", depends_on=("api", "ui", "docs"),
                   label="Verify the feature", role="verify"),
]


class _Run(unittest.TestCase):
    def setUp(self) -> None:
        context = homes()
        self.home = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.workspace = (self.home.omh.parent / "repo").resolve()
        (self.workspace / "src" / "api").mkdir(parents=True)
        cwd = mock.patch.dict(os.environ, {"TERMINAL_CWD": str(self.workspace)})
        cwd.start()
        self.addCleanup(cwd.stop)
        session_attendance.reset_session_attendance()
        nudge_budget.reset_nudge_budget()
        self.addCleanup(session_attendance.reset_session_attendance)
        self.addCleanup(nudge_budget.reset_nudge_budget)
        dag_tests.slots_table(self.home)
        defined = dag_tests.call(action="define", run=RUN, goal="feature works", nodes=NODES)
        self.assertEqual(defined["status"], "ok", defined)
        for node_id in ("api", "ui"):
            dag_tests.child_started(self.home, RUN, node_id)

    def write(self, session: str, path: str, *, tool: str = "write_file", args: dict | None = None) -> dict | None:
        return pre_tool_call(
            tool_name=tool,
            args=args if args is not None else {"path": path, "content": "x = 1\n"},
            session_id=session,
            task_id=session,
            turn_id="turn-1",
            **self.home.hooks(),
        )

    def assertBlocked(self, directive: dict | None, node_id: str) -> None:
        assert directive is not None
        self.assertEqual(directive["action"], "block")
        self.assertIn(f"dag-ulw node {node_id} in run {RUN}", directive["message"])


class ScopeIsEnforcedTest(_Run):
    def test_a_write_inside_the_scope_passes(self) -> None:
        self.assertIsNone(self.write("child-api", "src/api.py"))
        self.assertIsNone(self.write("child-api", str(self.workspace / "src" / "api.py")))

    def test_a_write_outside_the_scope_is_blocked(self) -> None:
        self.assertBlocked(self.write("child-api", "src/other.py"), "api")

    def test_a_write_into_a_sibling_nodes_scope_is_blocked(self) -> None:
        self.assertBlocked(self.write("child-api", "src/ui.py"), "api")
        self.assertBlocked(self.write("child-ui", "src/api.py"), "ui")

    def test_a_directory_entry_covers_what_is_under_it_and_nothing_beside_it(self) -> None:
        self.assertIsNone(self.write("child-api", "src/api/routes/v1.py"))
        self.assertBlocked(self.write("child-api", "src/apix.py"), "api")
        self.assertBlocked(self.write("child-api", "src/api2/x.py"), "api")

    def test_a_glob_entry_matches_the_workspace_relative_path(self) -> None:
        dag_tests.child_started(self.home, RUN, "docs")
        self.assertIsNone(self.write("child-docs", "docs/api.md"))
        self.assertBlocked(self.write("child-docs", "docs/api.py"), "docs")

    def test_a_v4a_patch_is_blocked_when_any_header_is_outside(self) -> None:
        body = "*** Begin Patch\n*** Update File: src/api.py\n@@\n-a\n+b\n*** Update File: src/ui.py\n@@\n-a\n+b\n"
        self.assertBlocked(self.write("child-api", "", tool="patch", args={"mode": "patch", "patch": body}), "api")

    def test_dot_dot_out_of_the_scope_is_blocked(self) -> None:
        self.assertBlocked(self.write("child-api", "src/api/../ui.py"), "api")

    def test_a_grandchild_follows_its_ancestors_node(self) -> None:
        start(self.home, "grandchild", "sa-g", "look something up", parent="child-api", parent_subagent="sa-api",
              now=time.time())
        self.assertIsNone(self.write("grandchild", "src/api/helper.py"))
        self.assertBlocked(self.write("grandchild", "src/ui.py"), "api")


class ReviewFindingsTest(_Run):
    """The four ways the first cut was wrong (independent review B1-B3, N1, N2), each driven through the hook."""

    def _set_scope(self, node_id: str, scope: list[str]) -> None:
        path = dag_run.record_path(self.home.omh, PARENT, RUN)
        record = dag_run.read_run(path)
        assert record is not None
        for node in record["nodes"]:
            if node["id"] == node_id:
                node["write_scope"] = scope
        dag_run.write_run(path, record)

    def test_define_pins_the_workspace_root(self) -> None:
        record = dag_run.read_run(dag_run.record_path(self.home.omh, PARENT, RUN))
        assert record is not None
        self.assertEqual(record["workspace_root"], os.path.realpath(self.workspace))

    def test_a_child_that_cd_s_is_judged_against_the_pinned_root(self) -> None:
        with mock.patch.dict(os.environ, {"TERMINAL_CWD": str(self.workspace / "src")}):
            self.assertIsNone(self.write("child-api", str(self.workspace / "src" / "api.py")))
            self.assertIsNone(self.write("child-api", "api.py"))
            self.assertBlocked(self.write("child-api", "ui.py"), "api")
        with mock.patch.dict(os.environ, {"TERMINAL_CWD": "/tmp"}):
            self.assertBlocked(self.write("child-api", str(self.workspace / "src" / "ui.py")), "api")

    def test_a_remote_runs_handoff_under_its_handoff_root_passes(self) -> None:
        path = dag_run.record_path(self.home.omh, PARENT, RUN)
        record = dag_run.read_run(path)
        assert record is not None
        record["backend"], record["handoff_root"] = "docker", str(self.workspace / ".omh" / "dag")
        dag_run.write_run(path, record)
        self.assertIsNone(self.write("child-api", dag_run.node_handoff(record, self.home.omh, "api")))
        self.assertBlocked(self.write("child-api", dag_run.node_handoff(record, self.home.omh, "ui")), "api")

    def test_a_bracketed_literal_path_covers_itself_and_not_its_sibling(self) -> None:
        self._set_scope("ui", ["app/[slug]/page.tsx", "src/routes/[id]/", "web/[lang]/*.md"])
        self.assertIsNone(self.write("child-ui", "app/[slug]/page.tsx"))
        self.assertIsNone(self.write("child-ui", "src/routes/[id]/view.ts"))
        self.assertBlocked(self.write("child-ui", "app/s/page.tsx"), "ui")
        self.assertBlocked(self.write("child-ui", "app/x/page.tsx"), "ui")
        self.assertIsNone(self.write("child-ui", "web/[lang]/intro.md"))
        self.assertBlocked(self.write("child-ui", "web/l/intro.md"), "ui")

    def test_a_child_renamed_by_compaction_is_still_held(self) -> None:
        self.home.session(PARENT, "m")
        self.home.session("child-api", "m", parent=PARENT)
        self.home.rotate("child-api", "child-api-seg2")
        self.assertBlocked(self.write("child-api-seg2", "src/ui.py"), "api")
        self.assertIsNone(self.write("child-api-seg2", "src/api.py"))

    def test_a_descendants_own_marker_cannot_move_it_to_another_node(self) -> None:
        start(self.home, "gc-ui", "sa-gc1", "help [dag:feat/ui]", parent="child-api", parent_subagent="sa-api",
              now=time.time())
        start(self.home, "gc-none", "sa-gc2", "help [dag:nope/x]", parent="child-api", parent_subagent="sa-api",
              now=time.time())
        self.assertBlocked(self.write("gc-ui", "src/ui.py"), "api")
        self.assertBlocked(self.write("gc-none", "src/other.py"), "api")


class AskRuleDoesNotOverrideTheScopeTest(_Run):
    """A toolcall rule with `"effect": "ask"` is held until this guard has judged the call.

    An `approve` lets the call run after a person's yes, so returning the rule's
    ask first would turn this guard's refusal into a prompt the person can pass.
    """

    def setUp(self) -> None:
        super().setUp()
        toolcall_rules._reset_state()
        self.addCleanup(toolcall_rules._reset_state)
        path = toolcall_rules.toolcall_rules_path(str(self.home.omh))
        path.parent.mkdir(parents=True, exist_ok=True)
        rule = {"name": "ask-before-write", "pattern": "write_file", "message": "Allow this file write?",
                "tools": ["write_file"], "effect": "ask", "repeat": "always"}
        path.write_text(json.dumps({"schema_version": toolcall_rules.TOOLCALL_RULES_SCHEMA_VERSION,
                                    "rules": [rule]}), encoding="utf-8")

    def test_a_write_outside_the_scope_is_still_blocked(self) -> None:
        self.assertBlocked(self.write("child-api", "src/other.py"), "api")

    def test_a_write_inside_the_scope_still_asks(self) -> None:
        directive = self.write("child-api", "src/api.py")
        assert directive is not None
        self.assertEqual(directive["action"], "approve")
        self.assertEqual(directive["rule_key"], "omh-toolcall-rule:ask-before-write")


class OtherCallsPassTest(_Run):
    def test_the_parent_writes_anywhere(self) -> None:
        self.assertIsNone(self.write(PARENT, "src/ui.py"))

    def test_the_nodes_own_handoff_report_passes_even_inside_the_workspace(self) -> None:
        handoff = dag_run.handoff_path(self.home.omh, PARENT, RUN, "api")
        path = dag_run.record_path(self.home.omh, PARENT, RUN)
        record = dag_run.read_run(path)
        assert record is not None
        record["workspace_root"] = str(self.home.omh.parent.resolve())
        dag_run.write_run(path, record)
        with mock.patch.dict(os.environ, {"TERMINAL_CWD": str(self.home.omh.parent)}):
            self.assertIsNone(self.write("child-api", str(handoff)))
            self.assertBlocked(self.write("child-api", str(handoff.with_name("ui.md"))), "api")

    def test_a_target_outside_the_workspace_passes(self) -> None:
        scratch = self.home.omh.parent / "scratch" / "probe.txt"
        self.assertIsNone(self.write("child-api", str(scratch)))

    def test_an_ordinary_child_is_not_held_to_anything(self) -> None:
        start(self.home, "plain-child", "sa-plain", "summarize the docs", now=time.time())
        self.assertIsNone(self.write("plain-child", "src/ui.py"))

    def test_a_settled_node_or_a_cancelled_run_holds_nothing(self) -> None:
        dag_tests.handoff(self.home, RUN, "api")
        settled = dag_tests.call(action="settle", run=RUN, node="api", outcome="accepted")
        self.assertEqual(settled["status"], "ok", settled)
        self.assertIsNone(self.write("child-api", "src/ui.py"))
        path = dag_run.record_path(self.home.omh, PARENT, RUN)
        record = dag_run.read_run(path)
        assert record is not None
        record["cancelled_at"] = time.time()
        dag_run.write_run(path, record)
        self.assertIsNone(self.write("child-ui", "src/api.py"))

    def test_a_node_with_no_write_scope_holds_nothing(self) -> None:
        dag_tests.handoff(self.home, RUN, "api")
        dag_tests.call(action="settle", run=RUN, node="api", outcome="accepted")
        dag_tests.handoff(self.home, RUN, "ui")
        dag_tests.call(action="settle", run=RUN, node="ui", outcome="accepted")
        dag_tests.handoff(self.home, RUN, "docs")
        dag_tests.call(action="settle", run=RUN, node="docs", outcome="accepted")
        dag_tests.child_started(self.home, RUN, "verify")
        self.assertIsNone(self.write("child-verify", "src/ui.py"))

    def test_a_broken_ledger_passes_and_warns_once(self) -> None:
        dag_scope_guard._warned = False
        self.addCleanup(setattr, dag_scope_guard, "_warned", False)
        with mock.patch.object(dag_scope_guard, "read_ledger", side_effect=OSError("denied")), \
                self.assertLogs("omh.dag_scope_guard", level="WARNING") as logs:
            self.assertIsNone(self.write("child-api", "src/ui.py"))
            self.assertIsNone(self.write("child-api", "src/other.py"))
        self.assertEqual(len(logs.records), 1)

    def test_reads_and_shell_commands_are_not_judged(self) -> None:
        self.assertIsNone(self.write("child-api", "", tool="read_file", args={"path": "src/ui.py"}))
        self.assertIsNone(self.write("child-api", "", tool="terminal", args={"command": "echo x > src/ui.py"}))


if __name__ == "__main__":
    unittest.main()

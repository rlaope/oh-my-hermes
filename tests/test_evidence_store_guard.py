"""`pre_tool_call` refuses a model write into the stores OMH's own code keeps.

Each case drives the real hook entry, `pre_tool_call(**kwargs)`, with the
argument shape Hermes sends (`args`), against a real temporary OMH home. The
dag-ulw handoff report is the one file under those stores a model is told to
write, so it must pass; a write the guard cannot resolve must pass too, since
a raising gate would skip every gate after it.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh import evidence_store_guard
from omh.plugin_bundle.omh.evidence_store_guard import EVIDENCE_STORES
from omh.plugin_bundle.omh.hooks import nudge_budget, session_attendance
from omh.plugin_bundle.omh.hooks.tool_hooks import pre_tool_call

SESSION = "20261105_101010_abc123"
KEY = "20261105_101010_abc123-0123456789abcdef"

STORE_TARGETS = {
    "journal/": "runtime/journal/decision_gates.jsonl",
    "delegation/": f"runtime/delegation/{KEY}.json",
    "dag/": f"runtime/dag/{KEY}/run-a.json",
    "research_receipts/": f"runtime/research_receipts/{KEY}.jsonl",
    "runs/": "runtime/runs/20260818T025406Z-plan/run.json",
    "todos/": f"runtime/todos/{KEY}.json",
    "todo.json": "runtime/todo.json",
}


class _Home(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.home = root / "omh"
        self.hermes = root / "hermes"
        self.workspace = root / "repo"
        for path in (self.home / "runtime", self.hermes, self.workspace):
            path.mkdir(parents=True)
        session_attendance.reset_session_attendance()
        nudge_budget.reset_nudge_budget()
        self.addCleanup(session_attendance.reset_session_attendance)
        self.addCleanup(nudge_budget.reset_nudge_budget)
        cwd = mock.patch.dict(os.environ, {"TERMINAL_CWD": str(self.workspace)})
        cwd.start()
        self.addCleanup(cwd.stop)

    def call(self, tool_name: str, args: dict, *, session: str = SESSION) -> dict | None:
        return pre_tool_call(
            tool_name=tool_name,
            args=args,
            session_id=session,
            task_id=session,
            turn_id="turn-1",
            omh_home=str(self.home),
            hermes_home=str(self.hermes),
        )

    def write(self, path: str, *, session: str = SESSION) -> dict | None:
        return self.call("write_file", {"path": path, "content": '{"schema_version": "x"}\n'}, session=session)

    def assertBlocked(self, directive: dict | None, store: str) -> None:
        assert directive is not None
        self.assertEqual(directive["action"], "block")
        self.assertIn(EVIDENCE_STORES[store], directive["message"])
        self.assertIn("Do not retry", directive["message"])


class EvidenceStoreWritesAreBlockedTest(_Home):
    def test_every_store_is_covered_by_a_case(self) -> None:
        self.assertEqual(set(STORE_TARGETS), set(EVIDENCE_STORES))

    def test_a_write_file_into_each_store_is_blocked(self) -> None:
        for index, (store, relative) in enumerate(STORE_TARGETS.items()):
            with self.subTest(store=store):
                self.assertBlocked(self.write(str(self.home / relative), session=f"{SESSION}-{index}"), store)

    def test_a_replace_patch_into_a_store_is_blocked(self) -> None:
        target = str(self.home / STORE_TARGETS["research_receipts/"])
        directive = self.call("patch", {"path": target, "old_string": "a", "new_string": "b"})
        self.assertBlocked(directive, "research_receipts/")

    def test_a_v4a_patch_is_blocked_when_any_one_header_is_a_store(self) -> None:
        body = (
            "*** Begin Patch\n"
            "*** Update File: src/app.py\n@@\n-a\n+b\n"
            f"*** Add File: {self.home / STORE_TARGETS['delegation/']}\n+{{}}\n"
            "*** End Patch\n"
        )
        self.assertBlocked(self.call("patch", {"mode": "patch", "patch": body}), "delegation/")

    def test_a_v4a_move_into_a_store_is_blocked(self) -> None:
        body = (
            "*** Begin Patch\n"
            f"*** Move File: notes.json -> {self.home / STORE_TARGETS['todo.json']}\n"
            "*** End Patch\n"
        )
        self.assertBlocked(self.call("patch", {"mode": "patch", "patch": body}), "todo.json")

    def test_dot_dot_tilde_and_symlink_routes_into_a_store_are_blocked(self) -> None:
        dotted = str(self.home / "runtime" / "dag" / ".." / "journal" / "decision_gates.jsonl")
        self.assertBlocked(self.write(dotted), "journal/")
        link = self.workspace / "evidence"
        link.symlink_to(self.home / "runtime", target_is_directory=True)
        self.assertBlocked(self.write("evidence/delegation/x.json", session=f"{SESSION}-link"), "delegation/")
        with mock.patch.dict(os.environ, {"HOME": str(self.home.parent)}):
            self.assertBlocked(self.write("~/omh/runtime/todo.json", session=f"{SESSION}-tilde"), "todo.json")

    def test_a_relative_path_from_a_workspace_inside_the_home_is_blocked(self) -> None:
        with mock.patch.dict(os.environ, {"TERMINAL_CWD": str(self.home / "runtime")}):
            self.assertBlocked(self.write("journal/events.jsonl"), "journal/")

    def test_a_case_changed_path_is_blocked(self) -> None:
        self.assertBlocked(self.write(str(self.home / "Runtime" / "Journal" / "events.jsonl")), "journal/")


class OtherWritesPassTest(_Home):
    def test_the_dag_handoff_report_passes(self) -> None:
        self.assertIsNone(self.write(str(self.home / f"runtime/dag/{KEY}/run-a/t1-build.md")))

    def test_writes_outside_the_stores_pass(self) -> None:
        for index, path in enumerate((
            "src/app.py",
            str(self.home / "runtime" / "plan-context" / "slug-context.md"),
            str(self.home / "memory" / "notes.md"),
            str(self.home / "runtime-notes.json"),
            str(self.home / "runtime" / "dag-notes.json"),
        )):
            with self.subTest(path=path):
                self.assertIsNone(self.write(path, session=f"{SESSION}-{index}"))

    def test_reads_and_shell_commands_are_not_judged(self) -> None:
        target = str(self.home / STORE_TARGETS["research_receipts/"])
        self.assertIsNone(self.call("read_file", {"path": target}))
        self.assertIsNone(self.call("terminal", {"command": f"echo x >> {target}"}, session=f"{SESSION}-t"))

    def test_an_unresolvable_target_passes_and_warns_once(self) -> None:
        evidence_store_guard._warned = False
        self.addCleanup(setattr, evidence_store_guard, "_warned", False)
        target = str(self.home / STORE_TARGETS["journal/"])
        with mock.patch.object(evidence_store_guard.os.path, "realpath", side_effect=OSError("denied")), \
                self.assertLogs("omh.evidence_store_guard", level="WARNING") as logs:
            self.assertIsNone(evidence_store_guard.evidence_write_directive(
                tool_name="write_file", tool_input={"path": target}, task_id=SESSION, omh_home=str(self.home)))
            self.assertIsNone(evidence_store_guard.evidence_write_directive(
                tool_name="write_file", tool_input={"path": target}, task_id=SESSION, omh_home=str(self.home)))
        self.assertEqual(len(logs.records), 1)
        self.assertIn("OSError", logs.output[0])


if __name__ == "__main__":
    unittest.main()

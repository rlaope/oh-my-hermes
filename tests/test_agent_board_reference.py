"""The agent-board reference describes `omh_agent_board prepare`; it must say what the engine accepts."""
from __future__ import annotations

import re
import unittest

from omh.skills.render import agent_board_reference_templates
from omh.workflows import agent_board
from omh.workflows.agent_board import _NO_TASK_ID, _OPERATIONS, _arguments


def _reference() -> str:
    (template,) = agent_board_reference_templates()
    return template.content


def _table_rows() -> dict[str, tuple[str, set[str], set[str]]]:
    rows: dict[str, tuple[str, set[str], set[str]]] = {}
    for line in _reference().split("\n## 4.")[0].split("## 3.")[1].splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0].startswith("`"):
            names = [set(re.findall(r"`([a-z_]+)`", cell)) for cell in cells[2:]]
            rows[cells[0].strip("`")] = (cells[1], names[0], names[1])
    return rows


class AgentBoardReferenceTests(unittest.TestCase):
    def test_operation_table_matches_the_engine(self) -> None:
        expected = {
            name: (
                "refused" if name in _NO_TASK_ID else "required",
                set(req.split()) - {"task_id"},
                set(opt.split()) - {"task_id"},
            )
            for name, (req, opt, _) in _OPERATIONS.items()
        }
        self.assertEqual(_table_rows(), expected)

    def test_task_id_column_matches_what_the_engine_accepts(self) -> None:
        for name, (required, _, _) in _table_rows().items():
            payload = {"coordination": "durable", "arguments": {}}
            if required == "required":
                payload["task_id"] = "t1"
            else:
                payload["task_id"] = "t1"
            with self.subTest(operation=name):
                try:
                    _arguments(name, payload, "r1", "default")
                except ValueError as exc:
                    # Any refusal here is about other arguments, never about where the task id sits.
                    self.assertNotIn(str(exc), {"invalid_reference"}) if required == "required" else self.assertEqual(
                        str(exc), "unexpected_task_id"
                    )
                else:
                    self.assertEqual(required, "required")

    def test_a_required_task_id_cannot_live_only_in_arguments(self) -> None:
        for name, (required, _, _) in _table_rows().items():
            if required != "required":
                continue
            with self.subTest(operation=name), self.assertRaises(ValueError) as caught:
                _arguments(name, {"coordination": "durable", "arguments": {"task_id": "t1"}}, "r1", "default")
            self.assertEqual(str(caught.exception), "invalid_reference")

    def test_limits_below_the_table_are_enforced(self) -> None:
        board = "default"
        for operation, payload in (
            ("complete", {"coordination": "durable", "arguments": {}, "task_id": "t1"}),
            ("block", {"coordination": "durable", "arguments": {"reason": "r", "kind": "other"}, "task_id": "t1"}),
            ("list", {"coordination": "durable", "arguments": {"status": "review"}}),
            ("create", {"coordination": "durable", "arguments": {"title": "t", "assignee": "a", "workspace_path": "p"}}),
        ):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                _arguments(operation, payload, "r1", board)
        body = _reference()
        for phrase in ("`complete` needs `summary` or `result`", "`needs_input`", "`review` and `scheduled`"):
            self.assertIn(phrase, body)

    def test_request_id_pattern_is_the_engines(self) -> None:
        self.assertIn(agent_board._REFERENCE.pattern.removesuffix("\\Z"), _reference())

    def test_documented_shapes_are_accepted_and_the_traps_are_refused(self) -> None:
        board = "default"
        research = {"coordination": "bounded_research", "arguments": {"tasks": [{"goal": "g", "context": "c"}]}}
        self.assertEqual(_arguments("research", research, "r1", board)["tool_name"], "delegate_task")
        comment = {"coordination": "durable", "arguments": {"body": "hi"}, "task_id": "t1"}
        self.assertEqual(_arguments("comment", comment, "r2", board)["arguments"]["task_id"], "t1")
        for operation, payload in (
            ("create", {"coordination": "bounded_research", "arguments": {"tasks": []}}),
            ("comment", {"coordination": "durable", "arguments": {"task_id": "t1", "body": "hi"}}),
            ("create", {"coordination": "durable", "arguments": {}}),
        ):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                _arguments(operation, payload, "r3", board)
        with self.assertRaises(ValueError):
            _arguments("list", {"coordination": "durable", "arguments": {}, "task_id": "t1"}, "r4", board)


if __name__ == "__main__":
    unittest.main()

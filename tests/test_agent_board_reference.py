"""The agent-board reference describes `omh_agent_board prepare`; it must say what the engine accepts."""
from __future__ import annotations

import re
import unittest

from omh.skills.render import agent_board_reference_templates
from omh.workflows import agent_board
from omh.workflows.agent_board import _OPERATIONS, _arguments


def _reference() -> str:
    (template,) = agent_board_reference_templates()
    return template.content


def _table_rows() -> dict[str, tuple[set[str], set[str]]]:
    rows: dict[str, tuple[set[str], set[str]]] = {}
    for line in _reference().split("\n## 4.")[0].split("## 3.")[1].splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0].startswith("`"):
            names = [set(re.findall(r"`([a-z_]+)`", cell)) for cell in cells[1:]]
            rows[cells[0].strip("`")] = (names[0], names[1])
    return rows


class AgentBoardReferenceTests(unittest.TestCase):
    def test_operation_table_matches_the_engine(self) -> None:
        expected = {name: (set(req.split()), set(opt.split())) for name, (req, opt, _) in _OPERATIONS.items()}
        self.assertEqual(_table_rows(), expected)

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

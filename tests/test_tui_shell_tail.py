"""A successful shell run shows the last lines it printed, with the count of the rest above them; other tools keep
their first lines (opencode's collapse-tool-output.ts shows shell output's tail)."""

from __future__ import annotations

from test_tui_transcript import LoopTestCase, ev


def numbered(count: int) -> str:
    return "\n".join(f"line {number}" for number in range(1, count + 1))


class ShellTailTests(LoopTestCase):
    def rows(self, name: str, result: dict[str, object]) -> list[str]:
        self.step(ev("tool.start", tool_id="t1", name=name, context="x"))
        self.step(ev("tool.complete", tool_id="t1", name=name, result=result, duration_s=0.1))
        return self.step(ev("message.complete", text="", status="complete"))

    def test_terminal_success_shows_last_lines_with_count_above(self) -> None:
        rows = self.rows("terminal", {"output": numbered(60), "exit_code": 0})
        self.assertEqual(rows[-4:], ["┃   ⎿  … +57 lines · ctrl+o shows all", "┃      line 58", "┃      line 59", "┃      line 60"])
        self.assertNotIn("┃      line 1", rows)

    def test_terminal_success_short_output_shows_all_without_more_row(self) -> None:
        rows = self.rows("terminal", {"output": numbered(2), "exit_code": 0})
        self.assertEqual(rows[-2:], ["┃   ⎿  line 1", "┃      line 2"])
        self.assertFalse([row for row in rows if "…" in row and "+" in row])

    def test_read_file_success_keeps_first_lines(self) -> None:
        rows = self.rows("web_extract", {"content": numbered(60)})
        self.assertEqual(rows[-4:], ["┃   ⎿  line 1", "┃      line 2", "┃      line 3", "┃      … +57 lines · ctrl+o shows all"])

    def test_terminal_failure_still_shows_last_lines(self) -> None:
        rows = self.rows("terminal", {"output": numbered(60), "exit_code": 1, "error": None})
        self.assertEqual(rows[-4:], ["┃   ⎿  … +57 lines · ctrl+o shows all", "┃      line 58", "┃      line 59", "┃      line 60"])

    def test_details_view_holds_the_last_forty(self) -> None:
        self.rows("terminal", {"output": numbered(60), "exit_code": 0})
        text = self.history(details=True)
        self.assertIn("┃      line 60", text)
        self.assertIn("┃      line 21", text)
        self.assertNotIn("┃      line 20", text)

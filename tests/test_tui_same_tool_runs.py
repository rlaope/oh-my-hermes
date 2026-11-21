"""Consecutive calls of one tool fold into one row with each call's command under it (the owner, 2026-11-20: "이런거
많이 쌓이는 문제도 있는데 같은 terminal이면 안에 본문만 쌓이는게 나으려나", six `terminal` calls in a row took
twenty rows). He picked this over Claude Code's one-line `Ran N shell commands`: the commands stay readable.

    ┃ ● terminal · 3 calls  0.9s
    ┃   ⎿  rg DBGM src  0.2s
    ┃      sed -n 1,9p app.py  0.3s
    ┃      pnpm test  0.4s

What each printed is left out of the run; the details view (ctrl+o) unfolds it into the calls' own rows. A call
with an answer under it, a diff, recalled records, or that failed or was refused keeps its own row, and so does a call of another
tool between two runs.
"""

from __future__ import annotations

import unittest

from omh.tui.transcript import (
    TOOL_DENIED,
    TOOL_ERROR,
    TOOL_OK,
    TOOL_RUNNING,
    ToolGroup,
    ToolRow,
    block_rows,
)
from test_tui_modes import make_app


def text(row) -> str:
    return "".join(span.text for span in row)


def rows_of(tools, *, expanded: bool = False, width: int = 80, now: float | None = None) -> list[str]:
    app, _client = make_app()
    return [text(row) for row in block_rows(ToolGroup(list(tools), done=True), width, app.theme, expanded=expanded,
                                            now=now)]


def call(tool_id: str, command: str, *, name: str = "terminal", status: str = TOOL_OK, took: float | None = 0.2,
         output: tuple[str, ...] = ("printed",), **fields) -> ToolRow:
    return ToolRow(tool_id, name, command, status, started_at=0.0, duration_s=took, output=output, **fields)


class SameToolRunTests(unittest.TestCase):
    def test_three_terminal_calls_are_one_row_and_their_commands(self) -> None:
        shown = rows_of([call("a", "rg DBGM src"), call("b", "sed -n 1,9p app.py", took=0.3),
                         call("c", "pnpm test", took=0.4)])
        self.assertEqual(shown, [
            "┃ ● terminal · 3 calls  0.9s",
            "┃   ⎿  rg DBGM src  0.2s",
            "┃      sed -n 1,9p app.py  0.3s",
            "┃      pnpm test  0.4s",
        ])
        self.assertNotIn("printed", "\n".join(shown))

    def test_the_details_view_unfolds_the_run_into_each_calls_rows_and_output(self) -> None:
        shown = rows_of([call("a", "echo one", output=("one",)), call("b", "echo two", output=("two",))],
                        expanded=True)
        self.assertEqual(shown, ["┃ ● terminal(echo one)  0.2s", "┃   ⎿  one", "", "",
                                 "┃ ● terminal(echo two)  0.2s", "┃   ⎿  two"])

    def test_a_single_call_keeps_its_own_row_and_output(self) -> None:
        self.assertEqual(rows_of([call("a", "echo one", output=("one",))]),
                         ["┃ ● terminal(echo one)  0.2s", "┃   ⎿  one"])

    def test_another_tool_between_splits_the_run(self) -> None:
        shown = rows_of([call("a", "echo one"), call("b", "echo two"), call("r", "README.md", name="read_file"),
                         call("c", "echo three")])
        self.assertEqual(shown[0], "┃ ● terminal · 2 calls  0.4s")
        self.assertIn("┃ ● read_file(README.md)  0.2s", shown)
        self.assertEqual(shown[-2:], ["┃ ● terminal(echo three)  0.2s", "┃   ⎿  printed"])

    def test_a_running_call_joins_the_run_which_reads_running_and_holds_its_total(self) -> None:
        shown = rows_of([call("a", "echo one"), call("b", "pnpm test --all", status=TOOL_RUNNING, took=None)])
        self.assertEqual(shown, ["┃ ○ terminal · 2 calls", "┃   ⎿  echo one  0.2s", "┃      pnpm test --all"])

    def test_a_failed_or_refused_call_keeps_its_own_row_and_says_why(self) -> None:
        for status in (TOOL_ERROR, TOOL_DENIED):
            with self.subTest(status=status):
                shown = rows_of([call("a", "echo one"), call("b", "false", status=status, output=("exit 1",)),
                                 call("c", "echo three")])
                self.assertFalse(any("calls" in row for row in shown), shown)
                self.assertIn("┃   ⎿  exit 1", shown)

    def test_a_call_with_an_answer_or_a_diff_keeps_its_own_row(self) -> None:
        answered = call("b", "rm -rf build", answers=[("allowed once · rm -rf build", "ok")])
        diffed = call("d", "calc.py", name="patch", inline_diff=b"--- a/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n-a\n+b\n")
        for tools in ([call("a", "echo one"), answered], [call("c", "x.py", name="patch"), diffed]):
            with self.subTest(second=tools[1].tool_id):
                self.assertFalse(any("calls" in row for row in rows_of(tools)), rows_of(tools))

    def test_a_recall_that_found_records_keeps_its_own_row_and_lists_them(self) -> None:
        found = call("b", "rotate tokens", name="omh_memory", output=("decision  rotate refresh tokens",), recalled_at=1.0)
        shown = rows_of([call("a", "deploy", name="omh_memory"), found])
        self.assertFalse(any("calls" in row for row in shown), shown)
        self.assertIn("decision  rotate refresh tokens", "\n".join(shown))

    def test_a_heredoc_script_reads_as_its_summary_in_the_run(self) -> None:
        shown = rows_of([call("a", "python3 - <<'EOF' ...", script="python3 script · 23 lines"), call("b", "ls")])
        self.assertEqual(shown[1], "┃   ⎿  python3 script · 23 lines  0.2s")

    def test_a_narrow_row_cuts_a_long_command_and_a_path_from_the_left(self) -> None:
        shown = rows_of([call("a", "git log --format='%h %ad %s' --date=short -- src/tui"),
                         call("b", "/very/long/path/to/some/deeply/nested/file.py", name="terminal")], width=40)
        self.assertTrue(all(len(row) <= 40 for row in shown), shown)
        self.assertTrue(shown[1].endswith("…  0.2s"), shown)
        self.assertTrue(shown[2].rstrip().endswith("file.py  0.2s"), shown)

    def test_plumbing_runs_still_fold_their_own_way(self) -> None:
        shown = rows_of([call("a", "omh-routing", name="skill_view"), call("b", "omh-plan", name="skill_view")])
        self.assertEqual(len(shown), 1)
        self.assertTrue(shown[0].startswith("┃ ● Loaded 2 skills"), shown)


if __name__ == "__main__":
    unittest.main()

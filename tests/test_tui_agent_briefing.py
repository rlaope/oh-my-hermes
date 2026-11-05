"""A finished subagent's briefing in the transcript: `● <name> finished`, its facts, and what it said under it.

The owner's ask of 2026-11-05: a finished subagent changed only its mark in
the agent list under the composer, and the transcript said nothing, so during
a long dag-ulw run nobody saw what each child concluded without opening its
log. Now each `subagent.complete` that finishes an agent the roster holds
writes one block (`transcript.AgentDoneBlock`), as Claude Code writes
`● Teammate @x finished` with its reply under it.

The rows are pinned here at every width, colour depth and outcome; the app
cases drive `App` over the recording client and the recorded relay frames
(`test_tui_subagents`), and read the transcript's blocks and the VT screen.
"""

from __future__ import annotations

import unittest

from _delegation_graphs import dag_export_run
from _tui_lines import line_text
from test_tui_agent_view import agent_event, agent_app
from test_tui_delegation_block import with_hud
from test_tui_modes import SID, drawn, make_app
from test_tui_subagents import FIRST, SECOND, feed
from omh.tui.gateway import Event
from omh.tui.style import NO_COLOR
from omh.tui.subagents import Roster
from omh.tui.theme import DEFAULT_THEME, look_ground, without_colour
from omh.tui.transcript import (
    AGENT_CANCELLED,
    AGENT_FAILED,
    AGENT_FINISHED,
    AGENT_INTERRUPTED,
    AgentDoneBlock,
    AssistantBlock,
    TurnSummaryBlock,
    block_rows,
)
from omh.tui.width import cell_width, line_width

REPLY = (
    "#2557 (d7caea5c3) and the **phase 2** branch (84979d473) both have their `CHANGELOG` entries directly above"
    " `## 4.0.6`.",
    'I\'m waiting for "your turn" before merging #2557.',
    "- one more line it said",
    "and another",
)


def texts(block: AgentDoneBlock, width: int, theme=DEFAULT_THEME) -> list[str]:
    return [line_text(row) for row in block_rows(block, width, theme)]


def blocks_of(app, kind: type) -> list:
    return [block for block in app.transcript.blocks if isinstance(block, kind)]


def held_of(app, kind: type) -> list:
    return [block for block in app.transcript._held if isinstance(block, kind)]


class BriefingRowsTests(unittest.TestCase):
    """`_agent_done_rows` through `block_rows`: the head row, the facts that fit, and at most two rows it said."""

    def test_a_finished_agent_reads_mark_name_word_and_facts_then_two_rows_of_its_reply_cut_with_an_ellipsis(self) -> None:
        rows = texts(AgentDoneBlock("ac-fix", AGENT_FINISHED, ("2m 14s", "↓1.2k"), REPLY), 150)
        self.assertEqual(rows[0], "● ac-fix finished  2m 14s · ↓1.2k")
        self.assertEqual(len(rows), 3, rows)
        # Markdown noise goes as the reply's own renderer drops it: no `**`, backticks or a heading's `#`.
        self.assertEqual(rows[1], "  #2557 (d7caea5c3) and the phase 2 branch (84979d473) both have their CHANGELOG"
                                  " entries directly above ## 4.0.6.")
        self.assertEqual(rows[2], '  I\'m waiting for "your turn" before merging #2557.…', "more was said: it ends in …")

    def test_a_reply_that_wraps_past_two_rows_is_cut_on_the_second(self) -> None:
        rows = texts(AgentDoneBlock("ac-fix", AGENT_FINISHED, ("4s",), (" ".join(["word"] * 60),)), 40)
        self.assertEqual(len(rows), 3, rows)
        self.assertTrue(rows[2].endswith("…"), rows)
        self.assertTrue(all(cell_width(row) <= 40 for row in rows), rows)

    def test_a_short_whole_reply_has_no_ellipsis(self) -> None:
        rows = texts(AgentDoneBlock("docs", AGENT_FINISHED, ("4s",), ("Done.", "Wrote docs/a.md.")), 80)
        self.assertEqual(rows, ["● docs finished  4s", "  Done.", "  Wrote docs/a.md."])

    def test_each_outcome_has_its_own_mark_and_word_and_only_a_completed_agent_is_green(self) -> None:
        theme = DEFAULT_THEME
        cases = {
            AGENT_FINISHED: ("●", theme.ok, theme.text),
            AGENT_FAILED: ("●", theme.error, theme.error),
            AGENT_INTERRUPTED: ("▪", theme.muted, theme.muted),
            AGENT_CANCELLED: ("○", theme.muted, theme.muted),
        }
        for outcome, (mark, mark_style, word_style) in cases.items():
            with self.subTest(outcome=outcome):
                head = block_rows(AgentDoneBlock("lane", outcome, ("3s",), ("why",)), 80, theme)[0]
                self.assertEqual(head[0].text, f"{mark} ")
                self.assertEqual(head[0].style, mark_style)
                self.assertTrue(head[1].style.bold, "the name is bold")
                self.assertEqual(head[2].text, f" {outcome}")
                self.assertEqual(head[2].style, word_style)
                self.assertEqual(head[0].style == theme.ok, outcome == AGENT_FINISHED)
                self.assertEqual(head[-1].style, theme.faint, "the facts are dim")

    def test_a_failure_shows_its_error_line_under_it(self) -> None:
        rows = texts(AgentDoneBlock("read the diff", AGENT_FAILED, ("31s",), ("provider timeout",)), 80)
        self.assertEqual(rows, ["● read the diff failed  31s", "  provider timeout"])

    def test_nothing_said_is_one_row(self) -> None:
        self.assertEqual(texts(AgentDoneBlock("lane", AGENT_INTERRUPTED, ("5s",)), 80), ["▪ lane interrupted  5s"])

    def test_a_narrow_row_drops_the_facts_from_the_last_then_cuts_the_name_and_keeps_the_word(self) -> None:
        block = AgentDoneBlock("a rather long lane name", AGENT_FINISHED, ("2m 14s", "↓1.2k"), REPLY)
        self.assertEqual(texts(block, 50)[0], "● a rather long lane name finished  2m 14s · ↓1.2k")
        self.assertEqual(texts(block, 44)[0], "● a rather long lane name finished  2m 14s")
        self.assertEqual(texts(block, 36)[0], "● a rather long lane name finished")
        self.assertEqual(texts(block, 24)[0], "● a rather lon… finished")
        for width in range(1, 60):
            with self.subTest(width=width):
                self.assertTrue(all(line_width(row) <= width for row in block_rows(block, width, DEFAULT_THEME)))

    def test_wide_characters_are_measured_in_cells(self) -> None:
        block = AgentDoneBlock("검토 작업 노드", AGENT_FINISHED, ("12s",), ("변경 사항을 모두 확인했고 테스트가 통과했습니다. " * 6,))
        for width in (20, 33, 47, 80):
            with self.subTest(width=width):
                rows = block_rows(block, width, DEFAULT_THEME)
                self.assertTrue(all(line_width(row) <= width for row in rows), [line_text(row) for row in rows])
                self.assertLessEqual(len(rows), 3)
        self.assertEqual(texts(block, 80)[0], "● 검토 작업 노드 finished  12s")

    def test_no_color_keeps_every_mark_and_word(self) -> None:
        theme = without_colour(DEFAULT_THEME)
        for outcome in (AGENT_FINISHED, AGENT_FAILED, AGENT_INTERRUPTED, AGENT_CANCELLED):
            with self.subTest(outcome=outcome):
                rows = block_rows(AgentDoneBlock("lane", outcome, ("3s",), ("why",)), 80, theme)
                self.assertEqual(line_text(rows[0]).split()[2], outcome)
                self.assertTrue(all(span.style.depth == NO_COLOR or span.style.fg is None for row in rows
                                    for span in row), "no colour reaches the rows")


class RosterFinishTests(unittest.TestCase):
    """`Roster.apply` names the agent a frame finished, once; `reply` keeps what it said."""

    def test_only_the_complete_that_finishes_an_agent_returns_it(self) -> None:
        roster = Roster()
        self.assertIsNone(roster.apply("subagent.start", {"subagent_id": FIRST, "goal": "a"}, 0.0))
        self.assertIsNone(roster.apply("subagent.complete", {"subagent_id": "", "status": "completed"}, 1.0),
                          "main has no id, so no frame finishes it")
        self.assertIsNone(roster.apply("subagent.complete", {"subagent_id": SECOND, "status": "completed"}, 1.0),
                          "a verdict on an agent never shown finishes none")
        finished = roster.apply("subagent.complete", {"subagent_id": FIRST, "status": "completed",
                                                      "summary": "line one\n\n**line two**"}, 2.0)
        self.assertIs(finished, roster.agents[FIRST])
        self.assertEqual(finished.reply, ("line one", "**line two**"))
        self.assertIsNone(roster.apply("subagent.complete", {"subagent_id": FIRST, "status": "failed"}, 3.0),
                          "a repeated complete changes nothing")


class AppBriefingTests(unittest.TestCase):
    """The app writes one block per agent a `subagent.complete` finishes, at a block boundary, in completion order."""

    def test_a_completion_while_nothing_is_live_is_written_at_once_with_its_facts(self) -> None:
        app, _client = agent_app(busy=False)
        agent_event(app, "complete", FIRST, status="completed", duration_seconds=134.0, output_tokens=1234,
                    summary="Found 3 call sites.\nAll in src/api/.")
        [block] = blocks_of(app, AgentDoneBlock)
        self.assertEqual(block, AgentDoneBlock("find usages of old_api in src/ and list every call site",
                                               AGENT_FINISHED, ("2m 14s", "↓1.2k"),
                                               ("Found 3 call sites.", "All in src/api/.")))
        screen = drawn(app)
        self.assertTrue(any(row.startswith("● find usages of old_api") and "finished" in row for row in screen), screen)
        self.assertIn("  Found 3 call sites.", [row.rstrip() for row in screen])

    def test_failed_interrupted_and_cancelled_agents_say_so(self) -> None:
        for status, outcome in (("failed", AGENT_FAILED), ("timeout", AGENT_FAILED), ("error", AGENT_FAILED),
                                ("interrupted", AGENT_INTERRUPTED), ("cancelled", AGENT_CANCELLED)):
            with self.subTest(status=status):
                app, _client = agent_app(busy=False)
                agent_event(app, "complete", FIRST, status=status, summary="provider timeout")
                [block] = blocks_of(app, AgentDoneBlock)
                self.assertEqual((block.outcome, block.said), (outcome, ("provider timeout",)))

    def test_a_completion_during_a_streaming_reply_waits_under_it_and_lands_at_the_boundary(self) -> None:
        app, _client = agent_app(busy=True, cols=100)
        app._on_event(Event("message.start", SID, {}))
        app._on_event(Event("message.delta", SID, {"text": "The first sentence of a paragraph that is still"}))
        agent_event(app, "complete", FIRST, status="completed", summary="Found 3 call sites.")
        self.assertEqual(blocks_of(app, AgentDoneBlock), [], "it never closes or splits the streaming reply")
        self.assertEqual(len(held_of(app, AgentDoneBlock)), 1)
        self.assertIsInstance(app.transcript.blocks[-1], AssistantBlock)
        self.assertFalse(app.transcript.blocks[-1].done)
        screen = [row.rstrip() for row in drawn(app)]
        reply = next(index for index, row in enumerate(screen) if "The first sentence" in row)
        brief = next(index for index, row in enumerate(screen) if row.startswith("● find usages"))
        self.assertLess(reply, brief, "shown under the live reply meanwhile")
        app._on_event(Event("message.delta", SID, {"text": " streaming.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"}))
        self.assertEqual(blocks_of(app, AgentDoneBlock), [])
        app._on_event(Event("message.complete", SID, {"text": "The first sentence of a paragraph that is still"
                                                              " streaming.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
                                                      "status": "complete"}))
        kinds = [type(block) for block in app.transcript.blocks[-3:]]
        self.assertEqual(kinds, [AssistantBlock, AgentDoneBlock, TurnSummaryBlock])
        history = [line_text(row) for row in app.transcript.history_lines(100, DEFAULT_THEME, details=False)]
        sentence = next(index for index, row in enumerate(history) if "The first sentence" in row)
        table = [index for index, row in enumerate(history) if row.split()[1:] in (["a", "b"], ["───", "───"], ["1", "2"])]
        brief = next(index for index, row in enumerate(history) if row.startswith("● find usages"))
        self.assertTrue(table and sentence < min(table) and max(table) < brief, history)
        self.assertEqual(table, list(range(min(table), max(table) + 1)), "the table is whole")

    def test_a_completion_under_a_running_call_waits_under_it_and_never_cuts_it_off(self) -> None:
        app, _client = agent_app(busy=True)
        app._on_event(Event("message.start", SID, {}))
        app._on_event(Event("tool.start", SID, {"tool_id": "t1", "name": "delegate_task", "context": "2 tasks"}))
        agent_event(app, "complete", FIRST, status="completed", summary="Found 3 call sites.")
        group = app.transcript.blocks[-1]
        self.assertFalse(group.done)
        self.assertEqual(group.tools[0].status, "running", "the delegating call still runs")
        self.assertEqual(len(held_of(app, AgentDoneBlock)), 1)

    def test_parallel_completions_are_one_block_each_in_the_order_they_finished(self) -> None:
        app, _client = agent_app(busy=True)
        app._on_event(Event("message.start", SID, {}))
        app._on_event(Event("message.delta", SID, {"text": "working"}))
        agent_event(app, "complete", SECOND, goal="read the diff for risks", status="completed", summary="no risks")
        agent_event(app, "complete", FIRST, status="failed", summary="boom")
        agent_event(app, "complete", FIRST, status="completed", summary="late repeat")
        app._on_event(Event("message.complete", SID, {"text": "working", "status": "complete"}))
        briefed = [(block.name, block.outcome) for block in blocks_of(app, AgentDoneBlock)]
        self.assertEqual(briefed, [("read the diff for risks", AGENT_FINISHED),
                                   ("find usages of old_api in src/ and list every call site", AGENT_FAILED)])

    def test_a_dag_nodes_child_is_named_by_its_node(self) -> None:
        app, _client = make_app(busy=False, clock=lambda: 0.0)
        with_hud(app, dag_export_run())
        agent_event(app, "start", FIRST, goal="implement the export button in the toolbar [dag:r1/button]")
        agent_event(app, "complete", FIRST, goal="implement the export button in the toolbar [dag:r1/button]",
                    status="completed", summary="Button added.")
        [block] = blocks_of(app, AgentDoneBlock)
        self.assertEqual(block.name, "Export button")

    def test_a_goal_no_node_binds_is_named_as_the_agent_list_names_it(self) -> None:
        app, _client = make_app(busy=False, clock=lambda: 0.0)
        with_hud(app, dag_export_run())
        agent_event(app, "start", FIRST, goal="Check the docs. DELIVERABLE: a list")
        agent_event(app, "complete", FIRST, goal="Check the docs. DELIVERABLE: a list", status="completed")
        [block] = blocks_of(app, AgentDoneBlock)
        self.assertEqual(block.name, "Check the docs")

    def test_on_a_scene_look_the_row_erases_on_the_looks_ground(self) -> None:
        # #2555: a scene look's rows erase on its ground (`screen.on_ground`); a briefing is drawn as any row is.
        environ = {"COLORTERM": "truecolor", "TERM": "xterm-256color", "OMH_TUI_WALLPAPER": "1"}
        app, _client = make_app(busy=False, cols=150, clock=lambda: 0.0, environ=environ)
        app.adopt_background("#1E1E1E")
        app.region = app._new_region(at_top=True)
        app.launch_look = "moonlit"
        app.theme = app._themed()
        node_goal = {"goal": "Export button [dag:r1/button]"}
        agent_event(app, "start", FIRST, **node_goal)
        agent_event(app, "complete", FIRST, **node_goal, status="completed", summary="Button added.")
        screen = drawn(app)
        row = next(index for index, line in enumerate(screen) if line.startswith("● Export button finished"))
        red, green, blue = (int(look_ground("moonlit", False)[at : at + 2], 16) for at in (1, 3, 5))
        for at in (row, row + 1):
            self.assertEqual(app.terminal.screen.attrs_at(at, 149), (48, 2, red, green, blue))

    def test_frames_that_finish_nothing_write_nothing(self) -> None:
        roster_app, _client = agent_app(busy=False)
        feed(roster_app.roster, "tool", 0.0, FIRST, tool_name="read_file")
        agent_event(roster_app, "thinking", FIRST, text="hm")
        agent_event(roster_app, "complete", "never-started", status="completed")
        self.assertEqual(blocks_of(roster_app, AgentDoneBlock), [])


if __name__ == "__main__":
    unittest.main()

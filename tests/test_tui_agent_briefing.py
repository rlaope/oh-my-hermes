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

import math
import unittest
from unittest.mock import patch

from _delegation_graphs import dag_export_run, graph, lane, root
from _tui_lines import line_text
from test_tui_agent_view import agent_event, agent_app
from test_tui_delegation_block import with_hud
from test_tui_modes import SID, drawn, make_app
from test_tui_subagents import FIRST, SECOND, feed
from omh.skin_pack import SKIN_THEMES
from omh.tui import transcript as transcript_module
from omh.tui.gateway import Event
from omh.tui.style import NO_COLOR
from omh.tui.subagents import Roster
from omh.tui.theme import (
    AGENT_HUES,
    DEFAULT_THEME,
    LAUNCH_PRESETS,
    TEXT_CONTRAST,
    _oklab,
    agent_style,
    build_theme,
    contrast_ratio,
    look_ground,
    readable_on,
    surface_for,
    with_launch_look,
    with_prompt_band,
    without_colour,
)
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

    def test_a_title_is_one_muted_row_between_the_head_and_what_it_said_cut_with_an_ellipsis(self) -> None:
        long = "Port notify module to the new router and keep the webhook retries on their backoff schedule"
        for outcome in (AGENT_FINISHED, AGENT_FAILED, AGENT_INTERRUPTED, AGENT_CANCELLED):
            with self.subTest(outcome=outcome):
                block = AgentDoneBlock("notify", outcome, ("1m 35s",), ("Ported.", "Retries kept."), title=long)
                rows = block_rows(block, 60, DEFAULT_THEME)
                self.assertEqual(line_text(rows[0]), f"{'▪' if outcome == AGENT_INTERRUPTED else '○' if outcome == AGENT_CANCELLED else '●'} notify {outcome}  1m 35s")
                self.assertEqual(line_text(rows[1]), "  Port notify module to the new router and keep the webhook…")
                self.assertEqual(rows[1][-1].style, DEFAULT_THEME.muted)
                self.assertEqual([line_text(row) for row in rows[2:]], ["  Ported.", "  Retries kept."])
        self.assertEqual(texts(AgentDoneBlock("notify", AGENT_FINISHED, ("4s",), (), title="Port notify"), 80),
                         ["● notify finished  4s", "  Port notify"], "a title row with nothing said")

    def test_a_title_row_keeps_to_the_width_in_cells_and_without_colour(self) -> None:
        block = AgentDoneBlock("docs", AGENT_FINISHED, ("12s",), ("변경 사항을 확인했습니다.",), title="인증 모듈 문서 정리 " * 8)
        for width in range(1, 60):
            with self.subTest(width=width):
                self.assertTrue(all(line_width(row) <= width for row in block_rows(block, width, DEFAULT_THEME)))
        rows = block_rows(block, 40, without_colour(DEFAULT_THEME))
        self.assertTrue(line_text(rows[1]).startswith("  인증 모듈") and line_text(rows[1]).endswith("…"), rows[1])
        self.assertTrue(all(span.style.depth == NO_COLOR or span.style.fg is None for row in rows for span in row))

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
        # The table is a box (#2590): its rows are the ones whose text opens with a border, `┌`, `│`, `├` or `└`.
        table = [index for index, row in enumerate(history) if row.split()[1:2] and row.split()[1][0] in "┌│├└"]
        self.assertEqual([history[index].split()[1:] for index in table if "│" in history[index]],
                         [["│", "a", "│", "b", "│"], ["│", "1", "│", "2", "│"]])
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
        self.assertEqual((block.name, block.title, block.handle), ("button", "Export button", True),
                         "its handle, then its label")
        rows = [row.rstrip() for row in drawn(app)]
        head = next(index for index, row in enumerate(rows) if row.startswith("● @button finished"))
        self.assertEqual(rows[head + 1 : head + 3], ["  Export button", "  Button added."])

    def test_a_node_whose_label_is_its_id_or_empty_has_no_title_row(self) -> None:
        for label in ("button", "BUTTON", ""):
            with self.subTest(label=label):
                graph = dag_export_run()
                next(node for node in graph["nodes"] if node["id"] == "d:r1:button")["title"] = label
                app, _client = make_app(busy=False, clock=lambda: 0.0)
                with_hud(app, graph)
                agent_event(app, "start", FIRST, goal="do it [dag:r1/button]")
                agent_event(app, "complete", FIRST, goal="do it [dag:r1/button]", status="failed", summary="boom")
                [block] = blocks_of(app, AgentDoneBlock)
                self.assertEqual((block.name, block.title), ("button", ""))

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
        row = next(index for index, line in enumerate(screen) if line.startswith("● @button finished"))
        red, green, blue = (int(look_ground("moonlit", False)[at : at + 2], 16) for at in (1, 3, 5))
        for at in (row, row + 1):
            self.assertEqual(app.terminal.screen.attrs_at(at, 149), (48, 2, red, green, blue))

    def test_a_completion_under_a_second_is_given_no_time(self) -> None:
        app, _client = agent_app(busy=False)  # the clock stands at 0: the agent ran no time at all
        agent_event(app, "complete", FIRST, status="completed", output_tokens=12)
        [block] = blocks_of(app, AgentDoneBlock)
        self.assertEqual(block.facts, ("↓12",))
        self.assertEqual(texts(block, 120)[0], "● find usages of old_api in src/ and list every call site finished  ↓12")

    def test_held_briefings_show_in_history_and_the_details_view(self) -> None:
        app, _client = agent_app(busy=True, cols=120)
        app._on_event(Event("message.start", SID, {}))
        app._on_event(Event("tool.start", SID, {"tool_id": "t1", "name": "delegate_task", "context": "2 tasks"}))
        agent_event(app, "complete", FIRST, status="completed", summary="Found 3 call sites.")
        self.assertEqual(blocks_of(app, AgentDoneBlock), [], "still held under the running call")
        shown = app.transcript.shown_blocks()
        self.assertEqual(shown[: len(app.transcript.blocks)], app.transcript.blocks)
        self.assertIsInstance(shown[-1], AgentDoneBlock)
        history = [line_text(row) for row in app.transcript.history_lines(120, DEFAULT_THEME)]
        self.assertTrue(any(row.startswith("● find usages") for row in history), history)
        app._details_view()
        pager = [row.rstrip() for row in drawn(app)]
        self.assertTrue(any(row.startswith("● find usages") for row in pager), pager)
        self.assertIn("  Found 3 call sites.", pager)

    def test_frames_that_finish_nothing_write_nothing(self) -> None:
        roster_app, _client = agent_app(busy=False)
        feed(roster_app.roster, "tool", 0.0, FIRST, tool_name="read_file")
        agent_event(roster_app, "thinking", FIRST, text="hm")
        agent_event(roster_app, "complete", "never-started", status="completed")
        self.assertEqual(blocks_of(roster_app, AgentDoneBlock), [])


class HeldBriefingFoldTests(unittest.TestCase):
    """Briefings held under a running `delegate_task` fold in the live region, so the call stays on screen; all of
    them are written whole, in the order they finished, at the boundary."""

    def run_delegation(self, rows: int, finished: int, dag: bool = False, long: bool = True):
        """`finished` children finish under one running `delegate_task`; with `dag`, each is a node of a dag run
        (`p<N>`, labelled `lane NN: check part N`), so its briefing carries a title row too."""
        app, _client = make_app(busy=True, rows=rows, cols=150, clock=lambda: 0.0)
        if dag:
            lanes = [lane(f"d:r1:p{number}", f"lane {number:02d}: check part {number}", "quick", "glm-5.3", "low",
                          "running", order=number + 1) for number in range(finished)]
            edges = [("root", item["id"], "dispatch") for item in lanes] + [("d:r1:p0", "d:r1:p1", "depends_on")]
            with_hud(app, graph([root(), *lanes], edges))
        app._on_event(Event("message.start", SID, {}))
        app._on_event(Event("tool.start", SID, {"tool_id": "t1", "name": "delegate_task", "context": f"{finished} tasks"}))
        for number in range(finished):
            goal = f"lane {number:02d}: check part {number}" + (f" [dag:r1/p{number}]" if dag else "")
            agent_event(app, "start", f"sa-{number}", goal=goal)
            status = "failed" if number % 7 == 3 else "completed"
            agent_event(app, "complete", f"sa-{number}", goal=goal, status=status, duration_seconds=30.0 + number,
                        summary=f"Part {number} checked" + ("; the long reply runs on " + "and on " * 30 if long else "."))
        drawn(app)  # a frame first: the next one sizes the held briefings by the rows this one left the tail
        return app

    def test_twenty_finished_under_a_running_call_keep_it_on_screen_and_the_live_region_bounded(self) -> None:
        for rows, dag in ((42, False), (30, False), (42, True), (30, True)):
            with self.subTest(rows=rows, dag=dag):
                app = self.run_delegation(rows, 20, dag)
                screen = [row.rstrip() for row in drawn(app)]
                self.assertTrue(any("delegate_task(20 tasks)" in row for row in screen), screen)
                more = [row for row in screen if row.startswith("● ") and " more " in row]
                self.assertEqual(len(more), 1, screen)
                live = app.transcript.live_lines(150, DEFAULT_THEME, max_rows=rows)
                self.assertLessEqual(len(live), 2 + rows // 4 + 2, [line_text(row) for row in live])
                newest = "● @p19 " if dag else "● lane 19"
                whole = [row for row in screen if row.startswith("● lane") or row.startswith("● @p")]
                self.assertTrue(whole and whole[-1].startswith(newest), "the newest is drawn whole")
                if dag:
                    self.assertIn("  lane 19: check part 19", screen, "with its title row")
                self.assertEqual(len(held_of(app, AgentDoneBlock)), 20, "every one is still held")

    def test_on_a_short_screen_the_call_row_wins_over_drawing_a_briefing_whole(self) -> None:
        # 150x16 with the agent list or a dag tree under the composer: the room the tail gets above its working rows
        # holds the call and one folded row, not a briefing whole, so the call stays on screen.
        for dag in (False, True):
            with self.subTest(dag=dag):
                app = self.run_delegation(16, 2, dag)
                screen = [row.rstrip() for row in drawn(app)]
                self.assertTrue(any("delegate_task(2 tasks)" in row for row in screen), screen)
                self.assertIn("● 2 finished", screen, "none drawn whole, so not `more`")
                self.assertEqual(len(held_of(app, AgentDoneBlock)), 2)

    def test_the_fold_row_counts_by_outcome_and_the_boundary_writes_every_one_whole_in_order(self) -> None:
        app = self.run_delegation(42, 8, long=False)
        screen = [row.rstrip() for row in drawn(app)]
        folded = held_of(app, AgentDoneBlock)[:-3]
        failed = sum(1 for block in folded if block.outcome == AGENT_FAILED)
        expected = f"● {len(folded) - failed} more finished · {failed} failed"
        self.assertIn(expected, screen)
        app._on_event(Event("tool.complete", SID, {"tool_id": "t1", "name": "delegate_task", "result": "{}"}))
        app._on_event(Event("message.complete", SID, {"text": "", "status": "complete"}))
        self.assertEqual([block.name for block in blocks_of(app, AgentDoneBlock)],
                         [f"lane {number:02d}: check part {number}" for number in range(8)])

    def test_three_or_fewer_are_all_drawn_whole(self) -> None:
        app = self.run_delegation(42, 3, long=False)
        screen = [row.rstrip() for row in drawn(app)]
        self.assertFalse([row for row in screen if " more " in row and row.startswith("● ")], screen)
        self.assertEqual(len([row for row in screen if row.startswith("● lane")]), 3)


MODULES = ("auth", "billing", "search", "upload", "export", "notify", "audit", "admin")
DARK = ("#0D1117", "#1E1E1E", "#000000")
LIGHT = ("#FFFFFF", "#F6F8FA")


def oklch_hue(colour: str) -> float:
    _lightness, a, b = _oklab(colour)
    return math.degrees(math.atan2(b, a)) % 360


def hue_gap(first: float, second: float) -> float:
    return min(abs(first - second), 360 - abs(first - second))


class HandleColourTests(unittest.TestCase):
    """A dag child's handle, `@<node id>`, in a hue of its own (`theme.agent_style`), after Claude Code's coloured
    `● Teammate @x finished` (the owner's ask of 2026-11-05: each agent its own colour)."""

    def test_a_handle_is_at_its_id_in_its_own_hue_whatever_the_outcome_and_the_mark_keeps_the_outcomes(self) -> None:
        theme = DEFAULT_THEME
        marks = {AGENT_FINISHED: theme.ok, AGENT_FAILED: theme.error, AGENT_INTERRUPTED: theme.muted,
                 AGENT_CANCELLED: theme.muted}
        for outcome, mark_style in marks.items():
            with self.subTest(outcome=outcome):
                head = block_rows(AgentDoneBlock("button", outcome, ("3s",), ("why",), handle=True), 80, theme)[0]
                self.assertEqual(head[1].text, "@button")
                self.assertEqual(head[1].style, agent_style("button", theme))
                self.assertTrue(head[1].style.bold)
                self.assertEqual(head[0].style, mark_style, "the mark is the outcome's, not the agent's")
        plain = block_rows(AgentDoneBlock("Check the docs", AGENT_FINISHED, ("3s",)), 80, theme)[0]
        self.assertEqual((plain[1].text, plain[1].style.fg), ("Check the docs", None), "no handle: no @, no hue")

    def test_the_hue_is_stable_across_calls_redraws_and_processes(self) -> None:
        # A literal, not re-derived: Python's `hash` is salted per process, so a colour picked by it would move.
        self.assertEqual(agent_style("auth", DEFAULT_THEME), DEFAULT_THEME.agents[5])
        self.assertEqual(agent_style("button", DEFAULT_THEME), agent_style("button", DEFAULT_THEME))
        block = AgentDoneBlock("auth", AGENT_FINISHED, ("3s",), ("Ported.",), handle=True)
        first, again = (block_rows(block, 120, DEFAULT_THEME)[0][1] for _ in range(2))
        self.assertEqual(first, again)
        transcript = transcript_module.Transcript()
        transcript.add_aside(block)
        history = transcript.history_lines(120, DEFAULT_THEME)
        self.assertEqual(next(row for row in history if line_text(row).startswith("● @auth"))[1], first)

    def test_different_handles_spread_over_the_hues(self) -> None:
        styles = {name: agent_style(name, DEFAULT_THEME) for name in MODULES}
        self.assertNotEqual(styles["auth"], styles["billing"])
        self.assertGreaterEqual(len({style.fg for style in styles.values()}), 5, styles)
        self.assertEqual(len({style.fg for style in DEFAULT_THEME.agents}), len(AGENT_HUES))

    def test_the_hues_keep_clear_of_every_state_hue_and_of_each_other(self) -> None:
        for skin in SKIN_THEMES:
            for background in (*DARK, *LIGHT):
                theme = build_theme(skin, background)
                states = {"ok": theme.ok.fg, "error": theme.error.fg, "running": theme.running.fg}
                for style in theme.agents:
                    for state, colour in states.items():
                        with self.subTest(theme=skin.short_name, background=background, hue=style.fg, state=state):
                            self.assertGreaterEqual(hue_gap(oklch_hue(style.fg), oklch_hue(colour)), 23)
        for side in (0, 1):
            hues = sorted(oklch_hue(pair[side]) for pair in AGENT_HUES)
            gaps = [hue_gap(first, second) for first, second in zip(hues, hues[1:] + hues[:1])]
            self.assertGreaterEqual(min(gaps), 25, (side, hues))

    def test_every_hue_reads_at_text_contrast_on_every_background_and_every_looks_ground(self) -> None:
        short = []
        for skin in SKIN_THEMES:
            for background in (*DARK, *LIGHT, None):
                surface = surface_for(skin, background)
                for look in LAUNCH_PRESETS:
                    theme = with_launch_look(build_theme(skin, background), skin, background, look)
                    short += [(skin.short_name, look, surface, style.fg) for style in theme.agents
                              if contrast_ratio(style.fg, surface) < TEXT_CONTRAST]
            for look in LAUNCH_PRESETS:  # a scene look's ground, as `App._themed` builds on it
                for light, after in ((False, "#0D1117"), (True, "#FFFFFF")):
                    ground = look_ground(look, light)
                    banded = with_prompt_band(build_theme(skin, ground), skin, ground, look)
                    theme = readable_on(with_launch_look(banded, skin, ground, look, scene=True), skin, ground, after)
                    short += [(skin.short_name, look, where, style.fg) for style in theme.agents
                              for where in (ground, after) if contrast_ratio(style.fg, where) < TEXT_CONTRAST]
        self.assertEqual(short, [])

    def test_no_color_is_a_plain_bold_handle(self) -> None:
        theme = without_colour(DEFAULT_THEME)
        head = block_rows(AgentDoneBlock("button", AGENT_FINISHED, ("3s",), handle=True), 80, theme)[0]
        self.assertEqual(line_text(head), "● @button finished  3s")
        self.assertTrue(head[1].style.bold)
        self.assertEqual(head[1].style.depth, NO_COLOR)
        self.assertEqual(agent_style("x", theme).depth, NO_COLOR)

    def test_a_narrow_row_cuts_the_handle_in_cells_and_keeps_the_word(self) -> None:
        block = AgentDoneBlock("a-rather-long-node-id", AGENT_FINISHED, ("2m 14s",), handle=True)
        self.assertEqual(texts(block, 24)[0], "● @a-rather-lo… finished")
        for width in range(1, 50):
            with self.subTest(width=width):
                self.assertTrue(all(line_width(row) <= width for row in block_rows(block, width, DEFAULT_THEME)))


class HandleNamingTests(unittest.TestCase):
    """Which agents get a handle: a dag node's child, bound by the HUD's graph or, before it binds, by its goal's
    marker; nothing else, since Hermes' subagent frames carry no name or role."""

    def test_a_dag_child_the_hud_has_not_bound_is_named_by_its_markers_node_with_its_short_title_under_it(self) -> None:
        for hud in (None, dag_export_run()):  # no HUD read yet; a graph that has no such node yet
            with self.subTest(hud=hud is not None):
                app, _client = make_app(busy=False, clock=lambda: 0.0)
                if hud is not None:
                    with_hud(app, hud)
                goal = "Write the release notes [dag:r1/notes]"
                agent_event(app, "start", FIRST, goal=goal)
                agent_event(app, "complete", FIRST, goal=goal, status="completed", summary="Done.")
                [block] = blocks_of(app, AgentDoneBlock)
                self.assertEqual((block.name, block.handle, block.title), ("notes", True, "Write the release notes"))
                rows = [row.rstrip() for row in drawn(app)]
                head = next(index for index, row in enumerate(rows) if row.startswith("● @notes finished"))
                self.assertEqual(rows[head + 1], "  Write the release notes")

    def test_an_agent_with_no_dag_node_keeps_its_short_title_without_a_handle(self) -> None:
        app, _client = agent_app(busy=False)
        agent_event(app, "complete", FIRST, status="completed", summary="Found 3 call sites.")
        [block] = blocks_of(app, AgentDoneBlock)
        self.assertFalse(block.handle)
        self.assertTrue(any(row.startswith("● find usages") for row in drawn(app)))


def dag_app(role: object = None, *, bind: bool = True):
    """An app whose HUD graph holds node `button` (its `role` set unless None), and a child of it that finished."""
    run = dag_export_run()
    node = next(item for item in run["nodes"] if item["id"] == "d:r1:button")
    if role is not None:
        node["role"] = role
    app, _client = make_app(busy=False, cols=120, clock=lambda: 0.0)
    with_hud(app, run if bind else None)
    goal = "implement the export button in the toolbar [dag:r1/button]"
    agent_event(app, "start", FIRST, goal=goal)
    agent_event(app, "complete", FIRST, goal=goal, status="failed" if role == "verify" else "completed",
                duration_seconds=95.0, output_tokens=2000, summary="Done.")
    [block] = blocks_of(app, AgentDoneBlock)
    return app, block


class RoleTests(unittest.TestCase):
    """The owner's pick of 2026-11-05: the node's role stands where Claude Code writes `Teammate`,
    `● build @notify finished`, plain; the handle keeps its own hue."""

    def test_each_role_stands_before_the_handle(self) -> None:
        for role in ("build", "baseline", "verify", "review"):
            with self.subTest(role=role):
                app, block = dag_app(role)
                self.assertEqual((block.role, block.name, block.handle), (role, "button", True))
                word = "failed" if role == "verify" else "finished"
                self.assertIn(f"● {role} @button {word}  1m 35s · ↓2k", [row.rstrip() for row in drawn(app)])
                head = block_rows(block, 120, DEFAULT_THEME)[0]
                self.assertEqual([span.text for span in head[:3]], ["● ", f"{role} ", "@button"])
                self.assertEqual(head[1].style, DEFAULT_THEME.text, "the role is plain")
                self.assertEqual(head[2].style, agent_style("button", DEFAULT_THEME), "the handle keeps its hue")

    def test_a_graph_that_records_no_role_or_another_word_gives_none(self) -> None:
        # A graph from an OMH before nodes exported their role, or a word that is not a role: nothing is guessed from
        # the label.
        for role in (None, "", "tester", 3):
            with self.subTest(role=role):
                app, block = dag_app(role)
                self.assertEqual((block.role, block.name), ("", "button"))
                self.assertTrue(any(row.startswith("● @button finished") for row in drawn(app)))

    def test_a_child_the_hud_holds_no_node_for_has_no_role(self) -> None:
        _app, block = dag_app("verify", bind=False)
        self.assertEqual((block.role, block.name, block.handle), ("", "button", True))

    def test_an_agent_with_no_node_has_no_role_and_no_handle(self) -> None:
        app, _client = agent_app(busy=False)
        agent_event(app, "complete", FIRST, status="completed", summary="Found 3 call sites.")
        [block] = blocks_of(app, AgentDoneBlock)
        self.assertEqual((block.role, block.handle), ("", False))
        self.assertTrue(any(row.startswith("● find usages of old_api") for row in drawn(app)))

    def test_no_color_keeps_the_role_and_a_plain_bold_handle(self) -> None:
        block = AgentDoneBlock("check", AGENT_FAILED, ("2m 10s",), ("boom",), handle=True, role="verify")
        rows = block_rows(block, 80, without_colour(DEFAULT_THEME))
        self.assertEqual(line_text(rows[0]), "● verify @check failed  2m 10s")
        self.assertTrue(rows[0][2].style.bold)
        self.assertTrue(all(span.style.depth == NO_COLOR or span.style.fg is None for row in rows for span in row))

    def test_a_narrow_row_drops_the_facts_then_cuts_the_handle_and_keeps_role_and_word(self) -> None:
        block = AgentDoneBlock("a-rather-long-node-id", AGENT_FINISHED, ("2m 14s", "↓1.2k"), handle=True,
                               role="baseline")
        self.assertEqual(texts(block, 60)[0], "● baseline @a-rather-long-node-id finished  2m 14s · ↓1.2k")
        self.assertEqual(texts(block, 50)[0], "● baseline @a-rather-long-node-id finished  2m 14s")
        self.assertEqual(texts(block, 30)[0], "● baseline @a-rather… finished")
        for width in range(1, 70):
            with self.subTest(width=width):
                self.assertTrue(all(line_width(row) <= width for row in block_rows(block, width, DEFAULT_THEME)))
        muted = block_rows(AgentDoneBlock("x", AGENT_INTERRUPTED, handle=True, role="review"), 40, DEFAULT_THEME)[0]
        role_span = next(span for span in muted if "review" in span.text)
        self.assertEqual(role_span.style, DEFAULT_THEME.muted, "an interrupted node's role is muted, as its word")


class RunHueTests(unittest.TestCase):
    """Within one dag run a handle's hue is its node's place in the run's definition order (`node_index`), so two
    nodes of a run share a hue only once all seven are used, and neighbours never do."""

    NAMES = ("auth", "billing", "search", "upload", "export", "notify", "audit", "admin")

    def run_app(self, run: str = "r1"):
        app, _client = make_app(busy=False, cols=150, clock=lambda: 0.0)
        lanes = [lane(f"d:{run}:{name}", f"Port {name}", "quick", "glm-5.3", "low", "running", order=index + 1)
                 for index, name in enumerate(self.NAMES)]
        for index, item in enumerate(lanes):
            item.update(role="build", node_index=index)
        edges = [("root", item["id"], "dispatch") for item in lanes] + [(f"d:{run}:auth", f"d:{run}:billing",
                                                                          "depends_on")]
        with_hud(app, graph([root(), *lanes], edges))
        for name in self.NAMES:
            goal = f"Port {name} [dag:{run}/{name}]"
            agent_event(app, "start", f"sa-{name}", goal=goal)
            agent_event(app, "complete", f"sa-{name}", goal=goal, status="completed", summary="Ported.")
        return app

    def handle_styles(self, app) -> list:
        return [block_rows(block, 150, DEFAULT_THEME)[0][2].style for block in blocks_of(app, AgentDoneBlock)]

    def test_the_first_seven_nodes_of_a_run_differ_and_neighbours_always_do(self) -> None:
        app = self.run_app()
        self.assertEqual([block.node_index for block in blocks_of(app, AgentDoneBlock)], list(range(8)))
        styles = self.handle_styles(app)
        self.assertEqual(len({style.fg for style in styles[:7]}), 7, "auth and admin may share; nothing earlier does")
        self.assertEqual(styles[7], styles[0], "the eighth starts the hues again")
        self.assertTrue(all(first != second for first, second in zip(styles, styles[1:])))

    def test_the_hue_holds_across_renders_history_and_a_reload_of_the_run(self) -> None:
        app = self.run_app()
        first = self.handle_styles(app)
        self.assertEqual(self.handle_styles(app), first)
        history = [row for row in app.transcript.history_lines(150, DEFAULT_THEME)
                   if line_text(row).startswith("● build @")]
        self.assertEqual([row[2].style for row in history], first)
        self.assertEqual(self.handle_styles(self.run_app()), first, "the same run read again keeps every hue")
        self.assertEqual(self.handle_styles(self.run_app("r2")), first, "another run may reuse the hues")

    def test_without_a_place_the_handle_falls_back_to_its_hash(self) -> None:
        _app, block = dag_app("build")  # the shared fixture's graph records no node_index
        self.assertIsNone(block.node_index)
        head = block_rows(block, 120, DEFAULT_THEME)[0]
        self.assertEqual(head[2].style, agent_style("button", DEFAULT_THEME))


class ShortScreenHeldTests(unittest.TestCase):
    """#2586 review: on a screen whose tail cannot hold the call, a spacer and the fold row, the call still wins."""

    def test_at_twelve_rows_the_call_stays_and_the_fold_row_drops_its_spacer_where_it_must(self) -> None:
        for dag in (False, True):
            with self.subTest(dag=dag):
                app = HeldBriefingFoldTests().run_delegation(12, 2, dag)
                screen = [row.rstrip() for row in drawn(app)]
                call = next(index for index, row in enumerate(screen) if "delegate_task(2 tasks)" in row)
                self.assertIn("● 2 finished", screen[call + 1 : call + 3], screen)
                self.assertEqual(len(held_of(app, AgentDoneBlock)), 2, "still held, written at the boundary")

    def test_with_room_for_the_call_alone_no_briefing_is_drawn(self) -> None:
        app = HeldBriefingFoldTests().run_delegation(10, 2, dag=True)
        screen = [row.rstrip() for row in drawn(app)]
        self.assertTrue(any("delegate_task(2 tasks)" in row for row in screen), screen)
        self.assertFalse([row for row in screen if row.startswith("● ")], screen)
        app._on_event(Event("tool.complete", SID, {"tool_id": "t1", "name": "delegate_task", "result": "{}"}))
        app._on_event(Event("message.complete", SID, {"text": "", "status": "complete"}))
        self.assertEqual(len(blocks_of(app, AgentDoneBlock)), 2)

    def test_under_a_streaming_reply_that_fills_the_tail_the_fold_row_stays(self) -> None:
        # #2591 review: a growing held table took every row of the tail and the fold row was dropped; a reply's top
        # rows give way instead, as the region keeps the bottom rows.
        app, _client = make_app(busy=True, rows=12, cols=150, clock=lambda: 0.0)
        app._on_event(Event("message.start", SID, {}))
        table = "| N | Value |\n| --- | --- |\n" + "".join(f"| {n} | v{n} |\n" for n in range(3))
        app._on_event(Event("message.delta", SID, {"text": "Intro line.\n\n" + table}))
        for number in range(2):
            goal = f"lane {number:02d}: check part {number}"
            agent_event(app, "start", f"sa-{number}", goal=goal)
            agent_event(app, "complete", f"sa-{number}", goal=goal, status="completed", summary="Checked.")
        drawn(app)
        screen = [row.rstrip() for row in drawn(app)]
        fold = screen.index("● 2 finished")
        self.assertTrue(screen[fold - 1].endswith("┘"), screen)
        self.assertTrue(screen[fold + 1].startswith("✻ Working"), screen)
        self.assertEqual(len(held_of(app, AgentDoneBlock)), 2)


class HeldUnderReplyCostTests(unittest.TestCase):
    def test_a_streaming_reply_is_not_rendered_whole_to_size_held_briefings(self) -> None:
        # #2586 review: sizing the held briefings rendered the whole live reply (`block_rows`) on every delta.
        app, _client = agent_app(busy=True, cols=100)
        app._on_event(Event("message.start", SID, {}))
        app._on_event(Event("message.delta", SID, {"text": "A long reply line.\n" * 200}))
        agent_event(app, "complete", FIRST, status="completed", summary="Found 3 call sites.")
        drawn(app)
        seen: list[type] = []
        real = transcript_module.block_rows

        def counting(block, *args, **kwargs):
            seen.append(type(block))
            return real(block, *args, **kwargs)

        with patch.object(transcript_module, "block_rows", counting):
            app._on_event(Event("message.delta", SID, {"text": "one more"}))
            app.transcript.live_lines(100, DEFAULT_THEME, max_rows=40, room=20)
        self.assertNotIn(AssistantBlock, seen)
        self.assertIn(AgentDoneBlock, seen)


if __name__ == "__main__":
    unittest.main()

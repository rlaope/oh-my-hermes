"""The delegation block in the OMH TUI: the tree under the info line at the heights people have, and `/dag`.

The agent view under the info line gets `layout.agent_view_cap` rows (seven
at most unless running lanes raise it), fewer than one frontier of boxes
takes, so the panel draws the delegation graph as its tree at every size (the
owner's call of 2026-10-21: the agent view goes under the prompt). `/dag`
draws the boxes, with Dependencies and Node details, full screen in a pager
that redraws from the HUD's newest read and takes keys (`DagPager`). The
layout cache cases drive `delegation_view` itself.
"""

from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from _delegation_graphs import dag_export_run, owner_mock, parallel, with_tokens  # noqa: E402
from _tui_lines import lines_text  # noqa: E402
from omh.plugin_bundle.omh import delegation_view  # noqa: E402
from omh.plugin_bundle.omh.delegation_view import render_delegation_view  # noqa: E402
from omh.tui.dag_pager import DAG_KEYS, DagPager  # noqa: E402
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, PAGE_DOWN, PAGE_UP, UP, Key  # noqa: E402
from omh.tui.keys import TAB as TAB_KEY  # noqa: E402
from omh.tui.layout import AGENT_VIEW_ROWS, agent_view_cap  # noqa: E402
from omh.tui.panels import agent_view_keep, panel_lines  # noqa: E402
from omh.tui.style import NO_COLOR, TRUECOLOR  # noqa: E402
from omh.tui.theme import DEFAULT_THEME  # noqa: E402
from test_tui_modes import make_app  # noqa: E402
from test_tui_muscle_memory import send  # noqa: E402

SIZES = [(rows, cols) for rows in (12, 24, 30, 40, 50) for cols in (40, 80, 100, 120)]
GRAPHS = {"three lanes": parallel(3), "owner mock-up": owner_mock(), "six lanes": parallel(6), "twelve": parallel(12)}

MOCK_24x80 = """\
  DAG · ulw-work hud-graph · 4 nodes · 3 edges · 2 running · 1 waiting · 1 done
  ◆ main · opus-5-5:high
  ├─ ● Refresh HUD docs    writing  opus-5-5:medium    running 2m 10s
  ├─ ✓ Polish HUD CLI      quick    glm-5.3-flash:low  done 1m 2s
  ├─ ● Update HUD tests    deep     opus-5-5:high      running 2m 8s
  └─ · Integration verify  inherit  opus-5-5           waits on 3 lanes
"""


def tier(rows: list[str]) -> str:
    if any("┌" in row for row in rows):
        return "box"
    if any(row.strip().startswith(("├─", "└─")) for row in rows):
        return "tree"
    return "header"


def payload_of(graph: dict) -> dict:
    return {"privacy": "metadata_only", "delegation_graph": graph}


def panel(graph: dict, rows: int, cols: int) -> list[str]:
    """The block as the agent view draws it at this size: in its cap, raised for the running lanes."""
    cap = agent_view_cap(rows, cols, agent_view_keep(payload_of(graph), cols))
    return lines_text(panel_lines(payload_of(graph), cols, cap, DEFAULT_THEME, 0.0))


class TreeTests(unittest.TestCase):
    def test_every_common_size_gets_the_tree_and_never_a_box(self) -> None:
        for name, graph in GRAPHS.items():
            for rows, cols in SIZES:
                with self.subTest(graph=name, size=(rows, cols)):
                    drawn = panel(graph, rows, cols)
                    self.assertEqual(tier(drawn), "tree")
                    self.assertLessEqual(len(drawn), agent_view_cap(rows, cols, 99))

    def test_the_owner_mock_up_under_the_info_line(self) -> None:
        self.assertEqual("\n".join(row.rstrip() for row in panel(owner_mock(), 24, 80)) + "\n", MOCK_24x80)

    def test_the_tree_under_the_info_line_says_each_lanes_count_where_its_row_has_room(self) -> None:
        counted = with_tokens(owner_mock(), {"a": 1234, "b": 62_000, "c": 45_600})
        self.assertEqual(
            [row.rstrip() for row in panel(counted, 24, 80)[2:5]],
            ["  ├─ ● Refresh HUD docs    writing  opus-5-5:medium    running 2m 10s · ↓1.2k",
             "  ├─ ✓ Polish HUD CLI      quick    glm-5.3-flash:low  done 1m 2s · ↓62k",
             "  ├─ ● Update HUD tests    deep     opus-5-5:high      running 2m 8s · ↓45.6k"],
        )
        self.assertEqual(panel(counted, 24, 60)[4].rstrip(), "  │    writing · opus-5-5:medium · running 2m 10s · ↓1.2k")
        self.assertEqual(panel(counted, 24, 40), panel(owner_mock(), 24, 40), "the model whole first, then a count")

    def test_running_lanes_raise_the_cap_up_to_a_third_of_the_screen_then_the_tree_says_how_many_more(self) -> None:
        twelve = panel(parallel(12), 24, 100)  # twelve running lanes: more than a third of 24 rows holds
        self.assertEqual(len(twelve), 24 // 3)
        self.assertTrue(twelve[-1].strip().startswith("└─ +"), twelve)
        self.assertIn("more nodes", twelve[-1])
        three = panel(parallel(3), 24, 100)
        self.assertEqual(len(three), 5, "the header, main and three lanes: the usual cap holds them")
        self.assertFalse([row for row in three if "more nodes" in row])

    def test_boxes_take_more_rows_than_the_view_usually_has(self) -> None:
        for name, graph in GRAPHS.items():
            with self.subTest(graph=name):
                boxes = render_delegation_view(graph, width=118, layout="box")
                self.assertEqual(boxes.layout, "box")
                self.assertGreater(len(boxes.lines), AGENT_VIEW_ROWS)


class LayoutCacheTests(unittest.TestCase):
    def test_new_durations_redraw_without_choosing_the_layout_again(self) -> None:
        graph = parallel(12)
        render_delegation_view(graph, width=118, max_lines=13)
        later = copy.deepcopy(graph)
        for node in later["nodes"][1:]:
            node["elapsed_seconds"] += 3_600 * 3  # a duration grows from minutes to hours
        with patch.object(delegation_view, "_choose", wraps=delegation_view._choose) as choose:
            redrawn = render_delegation_view(later, width=118, max_lines=13)
            self.assertEqual(choose.call_count, 0, "same structure: the kept decision is redrawn")
            changed = copy.deepcopy(later)
            changed["nodes"][1]["state"] = "done"
            render_delegation_view(changed, width=118, max_lines=13)
            self.assertEqual(choose.call_count, 1, "a state change is a new structure")
        self.assertEqual(redrawn.layout, render_delegation_view(graph, width=118, max_lines=13).layout)

    def test_a_box_is_as_wide_whatever_its_duration_reads(self) -> None:
        short, long = copy.deepcopy(parallel(3)), copy.deepcopy(parallel(3))
        for graph, elapsed in ((short, 5), (long, 3_599)):
            for node in graph["nodes"][1:]:
                # Every other line is short, so the status line (`running 5s`, `running 59m 59s`) is the widest.
                node.update(title="A", category="c", model="m", effort="", elapsed_seconds=elapsed)
        widths = []
        for graph in (short, long):
            rows = render_delegation_view(graph, width=118, layout="box").text_lines()
            widths.append([len(row) for row in rows[:rows.index("Node details")]])  # a card's status is not boxed
        self.assertEqual(widths[0], widths[1])


def with_hud(app, graph: dict | None, received_at: float | None = 0.0) -> None:
    """`app.hud` as a HUD snapshot of `graph`, read at `received_at` (None: a payload with no read time, which the
    `/dag` pager dates by its own clock)."""
    payload = {"privacy": "metadata_only"}
    if graph is not None:
        payload["delegation_graph"] = graph
    app.hud = type("Hud", (), {"payload": payload, "received_at": received_at})()


def screen(app) -> list[str]:
    """What the terminal shows now, after the app paints its frame."""
    app._render()
    return [row.rstrip() for row in app.terminal.screen.lines()]


def press(app, *keys: Key) -> list[str]:
    for key in keys:
        app._on_input(key)
    return screen(app)


TAB, SHIFT_TAB, SPACE = Key(TAB_KEY), Key(TAB_KEY, shift=True), Key(CHAR, " ")


class DagCommandTests(unittest.TestCase):
    def test_dag_opens_the_boxes_on_the_running_node_and_q_closes_it(self) -> None:
        app, client = make_app(rows=60, cols=100, environ={"COLORTERM": "truecolor", "TERM": "xterm-256color"})
        with_hud(app, dag_export_run())
        send(app, "/dag")
        self.assertIsInstance(app.pager, DagPager)
        rows = screen(app)
        self.assertEqual(rows[0], "OMH / DAG · 5 tasks")
        self.assertIn("│ [-] > Export button", "\n".join(rows), "it opens on the running node")
        self.assertIn("Node details", rows)
        self.assertEqual(rows[-2:], [f" {DAG_KEYS}", " delegation graph · rows 1-42/42"])
        self.assertNotIn("Runs", rows[-2], "one graph per conversation: no other run to switch to")
        spans = [span for line in app.pager.lines for span in line if span.text.strip()]
        self.assertTrue(all(span.style.depth == TRUECOLOR for span in spans))
        self.assertTrue(any(span.style.fg for span in spans if "│" in span.text), "the borders take their state's colour")
        app._on_input(Key(CHAR, "q"))
        self.assertIsNone(app.pager)
        send(app, "/dag")
        app._on_input(Key(ESCAPE))
        self.assertIsNone(app.pager, "Esc closes it too")
        self.assertEqual(client.calls, [], "nothing in /dag reaches the gateway")

    def test_tab_and_shift_tab_move_the_highlight_in_reading_order(self) -> None:
        app, client = make_app(rows=60, cols=100)
        with_hud(app, dag_export_run())
        send(app, "/dag")
        screen(app)
        order = []
        for key in (TAB, TAB, TAB, TAB, Key(CHAR, "n")):
            press(app, key)
            order.append(app.pager.node)
        self.assertEqual(order, ["d:r1:docs", "d:r1:cli", "d:r1:verify", "d:r1:api", "d:r1:button"], "and round again")
        for key in (SHIFT_TAB, Key(CHAR, "p")):
            press(app, key)
        self.assertEqual(app.pager.node, "d:r1:verify")
        rows = "\n".join(screen(app))
        self.assertIn("│ [-] > Verify export", rows)
        self.assertEqual(rows.count(" > "), 1, "one box is highlighted")
        self.assertIn("  ○ Verify export", rows, "the highlighted node has a card")
        self.assertEqual(client.calls, [])

    def test_space_or_enter_folds_and_d_switches_node_details(self) -> None:
        app, _client = make_app(rows=60, cols=100)
        with_hud(app, dag_export_run())
        send(app, "/dag")
        screen(app)
        rows = press(app, SPACE)
        self.assertIn("│ [+] > ● Export bu… · Running │", "\n".join(rows), "folded to one line: glyph, title, status word")
        self.assertNotIn("● Running 21s", "\n".join(rows[:20]))
        rows = press(app, Key(ENTER))
        self.assertIn("│ [-] > Export button", "\n".join(rows))
        rows = press(app, Key(CHAR, "d"))
        self.assertNotIn("Node details", rows)
        rows = press(app, Key(CHAR, "d"))
        self.assertIn("Node details", rows)

    def test_the_highlight_is_scrolled_into_view_and_the_arrows_scroll(self) -> None:
        app, _client = make_app(rows=16, cols=100)
        with_hud(app, dag_export_run())
        send(app, "/dag")
        rows = screen(app)
        self.assertEqual(app.pager.top, 5, "the running node it opens on is scrolled whole into the 14 rows")
        self.assertTrue(rows[8].startswith("┌") and rows[9].startswith("│ [-] > Export button")
                        and rows[13].startswith("└"), rows)
        rows = press(app, SHIFT_TAB, SHIFT_TAB)  # Export button, then back past Export API to Verify export
        self.assertEqual(app.pager.node, "d:r1:verify")
        self.assertTrue(any("[-] > Verify export" in row for row in rows[:14]), rows)
        top = app.pager.top
        press(app, Key(UP))
        self.assertEqual(app.pager.top, top - 1)
        press(app, Key(DOWN), Key(DOWN))
        self.assertEqual(app.pager.top, top + 1)
        press(app, Key(CHAR, "g"))
        self.assertEqual(app.pager.top, 0)
        press(app, Key(PAGE_DOWN))
        self.assertEqual(app.pager.top, 14, "PageDown moves a page: 16 rows less the two footer rows")
        press(app, Key(CHAR, "G"))
        self.assertEqual(app.pager.top, len(app.pager.lines) - 14, "G shows the last page")
        press(app, Key(PAGE_UP))
        self.assertEqual(app.pager.top, len(app.pager.lines) - 28)

    def test_dag_is_live_from_the_newest_hud_read(self) -> None:
        app, client = make_app(rows=60, cols=100)
        with_hud(app, dag_export_run())
        send(app, "/dag")
        self.assertIn("│ ● Running 21s", "\n".join(screen(app)))
        later = dag_export_run()
        later["nodes"][2].update(state="done", status="accepted", elapsed_seconds=40)
        later["nodes"][3].update(state="running", status="running", elapsed_seconds=5, model="claude-opus-5-5",
                                 effort="medium")
        with_hud(app, later)
        rows = "\n".join(screen(app))
        self.assertIn("✓ Accepted 40s", rows)
        self.assertIn("● Running 5s", rows)
        self.assertEqual(app.pager.node, "d:r1:button", "the highlight stays on its node while that node is drawn")
        with_hud(app, None)
        self.assertIn("✓ Accepted 40s", "\n".join(screen(app)), "a graph that aged out leaves the last drawing")
        self.assertEqual(client.calls, [])

    def test_a_drawing_kept_after_the_graph_is_gone_says_it_is_not_live(self) -> None:
        now = [100.0]
        app, _client = make_app(rows=60, cols=100, wall_clock=lambda: now[0])
        with_hud(app, dag_export_run(), received_at=100.0)
        send(app, "/dag")
        rows = screen(app)
        self.assertEqual(rows[0], "OMH / DAG · 5 tasks", "live: no note")
        now[0] = 112.0
        with_hud(app, None)
        rows = screen(app)
        self.assertEqual(rows[:2], ["not live · last update 12s ago", "OMH / DAG · 5 tasks"])
        note = app.pager.lines[0][0]
        self.assertEqual(note.style.fg, DEFAULT_THEME.muted.fg, "a word on `muted`, never on `dim`")
        now[0] = 185.0
        self.assertEqual(screen(app)[0], "not live · last update 1m 25s ago", "the age moves with the clock")
        press(app, Key(TAB_KEY))
        self.assertTrue(any("[-] > " in row for row in screen(app)), "the kept boxes still take the keys")
        with_hud(app, dag_export_run())
        self.assertEqual(screen(app)[0], "OMH / DAG · 5 tasks", "live again: the note goes")

    def test_the_not_live_age_is_the_datas_not_the_last_redraws(self) -> None:
        """Read at t=100, a Tab at t=200 redraws the same payload, the graph is gone at t=210: the data is 110 s old,
        and the note says so, not 10 s (the redraw)."""
        now = [100.0]
        app, _client = make_app(rows=60, cols=100, wall_clock=lambda: now[0])
        with_hud(app, dag_export_run(), received_at=None)  # no read time: dated when first drawn, not at each redraw
        send(app, "/dag")
        screen(app)
        now[0] = 200.0
        press(app, Key(TAB_KEY))
        now[0] = 210.0
        with_hud(app, None)
        self.assertEqual(screen(app)[0], "not live · last update 1m 50s ago")
        # The HUD's own read time, where it gives one, is the age's start: read at 90, opened at 100.
        now[0] = 100.0
        app, _client = make_app(rows=60, cols=100, wall_clock=lambda: now[0])
        with_hud(app, dag_export_run(), received_at=90.0)
        send(app, "/dag")
        screen(app)
        now[0] = 130.0
        with_hud(app, None)
        self.assertEqual(screen(app)[0], "not live · last update 40s ago")

    def test_dag_follows_the_terminals_depth(self) -> None:
        app, _client = make_app(rows=24, cols=100, environ={"NO_COLOR": "1"})
        with_hud(app, parallel(3))
        send(app, "/dag")
        screen(app)
        self.assertTrue(all(";" not in span.style.sgr() for line in app.pager.lines for span in line))
        self.assertEqual(app.color_depth, NO_COLOR)

    def test_no_graph_is_one_line_saying_so(self) -> None:
        for graph in (None, {"status": "inactive", "nodes": []}):
            with self.subTest(graph=graph):
                app, _client = make_app()
                with_hud(app, graph)
                send(app, "/dag")
                self.assertIsNone(app.pager)
                said = [getattr(block, "text", "") for block in app.transcript.blocks]
                self.assertIn("No delegation graph: this session has no recent delegated work.", said)


if __name__ == "__main__":
    unittest.main()

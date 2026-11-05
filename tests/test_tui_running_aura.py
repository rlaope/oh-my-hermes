"""The dag-ulw aura where work moves (owner "gogo" on the promo render, 2026-10-26): a running node's title in the tree
under the composer and its box in `/dag`, and one band over what an `omh_memory` recall found as it lands.

The aura moves only where the composer's does (`App._aura_moves`: truecolor, motion on, a background its band shows
on); everywhere else, for every node that does not run and every call that is not a recall that found something, the
drawing is the one it always was, span for span. Scrollback is never live (owner decision 2026-10-21): the graph
printed into the transcript and a recall's rows once taken draw as they always do.
"""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from _delegation_graphs import dag_export_run  # noqa: E402
from test_tui_dag_tree import tree_app  # noqa: E402
from test_tui_delegation_block import screen, with_hud  # noqa: E402
from test_tui_modes import make_app  # noqa: E402
from test_tui_muscle_memory import send  # noqa: E402
from omh.tui import dag_block  # noqa: E402
from omh.tui.dag_pager import DagPager  # noqa: E402
from omh.tui.dag_tree import tree_lines  # noqa: E402
from omh.tui.gateway import Event  # noqa: E402
from omh.tui.panels import dag_page_lines  # noqa: E402
from omh.tui.style import COLOR_256, NO_COLOR, TRUECOLOR, Span  # noqa: E402
from omh.tui.theme import build_theme, default_theme  # noqa: E402
from omh.tui.transcript import RECALL_GLINT_SECONDS, Transcript  # noqa: E402
from omh.tui.width import line_width  # noqa: E402

RUNNING_BOX = "d:r1:button"  # Export button, the export run's one running node


def text(line) -> str:
    return "".join(span.text for span in line)


def aura_colours(theme) -> set:
    return {style.fg for style in (*theme.aura, *theme.aura_glint)}


def styles_at(line, start: int, end: int) -> list:
    """The style of each cell of `line` from `start` to `end`."""
    found, cell = [], 0
    for span in line:
        for _char in span.text:
            if start <= cell < end:
                found.append(span.style)
            cell += 1
    return found


class TreeAuraTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app, _client = tree_app()
        self.graph = self.app.hud.payload["delegation_graph"]

    def lines(self, aura):
        return tree_lines(self.graph, self.app.roster, 120, 40, self.app.theme, 0, {}, None, aura=aura)[0]

    def test_a_running_nodes_title_runs_through_the_aura_and_its_band_moves(self) -> None:
        still, first, later = self.lines(None), self.lines(0), self.lines(5)
        self.assertEqual([text(line) for line in first], [text(line) for line in still], "the words are the words")
        row = next(line for line in first if "PR group 1:" in text(line))
        title = text(row).index("PR group 1:")
        colours = {style.fg for style in styles_at(row, title, title + len("PR group 1: #138300 #107931"))}
        self.assertLessEqual(colours, aura_colours(self.app.theme))
        self.assertGreater(len(colours), 3, "stepped across the title, not one colour")
        moved = next(line for line in later if "PR group 1:" in text(line))
        self.assertNotEqual(styles_at(row, title, title + 20), styles_at(moved, title, title + 20), "the band moved")

    def test_a_node_that_does_not_run_and_every_other_cell_draw_as_before(self) -> None:
        still, glowing = self.lines(None), self.lines(3)
        for before, after in zip(still, glowing):
            if text(before).lstrip().startswith(("▾ ⠋", "▸ ⠋")):
                continue  # a running node's row
            self.assertEqual(after, before, text(before))
        running = [(before, after) for before, after in zip(still, glowing) if before != after]
        self.assertEqual(len(running), 3, "the three running nodes, and only they")
        for before, after in running:
            glyph = next(span for span in before if "⠋" in span.text)
            self.assertEqual(next(span for span in after if "⠋" in span.text), glyph, "the glyph keeps the running blue")

    def test_the_app_draws_it_only_where_the_aura_moves(self) -> None:
        app = self.app
        app.color_depth, app.motion = TRUECOLOR, True
        self.assertIsNotNone(app._aura_phase())
        rows = app._tree_view(app.hud.payload, 120, 40)
        self.assertTrue(any(span.style.fg in aura_colours(app.theme) for line in rows for span in line))
        dark = app.theme
        for depth, motion, theme in ((COLOR_256, True, dark), (NO_COLOR, True, dark), (TRUECOLOR, False, dark),
                                     (TRUECOLOR, True, build_theme(default_theme(), "#808080"))):
            with self.subTest(depth=depth, motion=motion, theme=theme is dark):
                app.color_depth, app.motion, app.theme = depth, motion, theme
                self.assertIsNone(app._aura_phase())
                rows = app._tree_view(app.hud.payload, 120, 40)
                # The waiting dots and the counting times are the tree's own (`test_tui_dag_wait_view`): the same here.
                expected = tree_lines(self.graph, app.roster, 120, 40, theme, app._spinner_frame(), {}, None, depth,
                                      app.clock(), processes={}, wall=app.wall_clock(),
                                      received_at=app.hud.received_at,
                                      beat=int(app._ambient_clock()) if motion else None)[0]
                self.assertEqual(rows, expected, "exactly the tree it always drew")
        app.theme = dark


class DagPageAuraTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app, _client = make_app(rows=60, cols=100)
        with_hud(self.app, dag_export_run())
        self.payload = self.app.hud.payload

    def page(self, aura, depth: str = TRUECOLOR):
        lines, view = dag_page_lines(self.payload, 100, self.app.theme, depth, aura=aura)
        return lines, view

    def test_the_running_box_border_and_title_run_through_the_aura(self) -> None:
        still, view = self.page(None)
        glowing, _view = self.page(4)
        self.assertEqual([text(line) for line in glowing], [text(line) for line in still])
        top, bottom = next((first, last) for node_id, first, last in view.boxes if node_id == RUNNING_BOX)
        colours = aura_colours(self.app.theme)
        left = text(still[top]).index("┌")
        right = text(still[top]).index("┐", left)
        for at in range(top, bottom + 1):
            border = styles_at(glowing[at], left, left + 1) + styles_at(glowing[at], right, right + 1)
            self.assertTrue(all(style.fg in colours for style in border), at)
        title = text(still[top + 1]).index("Export button")
        self.assertTrue(all(style.fg in colours for style in styles_at(glowing[top + 1], title, title + 13)))
        status = text(still[top + 3]).index("Running")
        self.assertEqual(styles_at(glowing[top + 3], status, status + 7), styles_at(still[top + 3], status, status + 7),
                         "the status keeps its word's colour: the state is still told the same way")
        changed = {at for at, (before, after) in enumerate(zip(still, glowing)) if before != after}
        self.assertEqual(changed, set(range(top, bottom + 1)), "no other box, edge, section or card changes")
        moved, _view = self.page(9)
        self.assertNotEqual(moved[top], glowing[top], "the band moved along the border")

    def test_no_running_node_leaves_the_page_as_it_was(self) -> None:
        settled = dag_export_run()
        for node in settled["nodes"]:
            if node.get("state") == "running":
                node.update(state="done", status="accepted")
        with_hud(self.app, settled)
        self.payload = self.app.hud.payload
        self.assertEqual(self.page(4)[0], self.page(None)[0])

    def test_the_pager_follows_the_tick_only_where_the_aura_moves(self) -> None:
        app = self.app
        clock = [100.0]
        app.clock = lambda: clock[0]
        app.color_depth, app.motion = TRUECOLOR, True
        send(app, "/dag")
        self.assertIsInstance(app.pager, DagPager)
        first = list(app.pager.lines) if screen(app) else []
        clock[0] += 0.35
        screen(app)
        self.assertNotEqual(app.pager.lines, first, "the running box moved with the tick")
        for depth, motion in ((COLOR_256, True), (NO_COLOR, True), (TRUECOLOR, False)):
            with self.subTest(depth=depth, motion=motion):
                app.color_depth, app.motion = depth, motion
                app.pager.depth = depth
                screen(app)
                drawn = list(app.pager.lines)
                clock[0] += 0.35
                screen(app)
                self.assertEqual(app.pager.lines, drawn, "nothing moves")
                expected = dag_page_lines(app.hud.payload, 100, app.theme, depth,
                                          focus=_focus(app.pager))[0]
                self.assertEqual(app.pager.lines, expected, "the page it always drew")

    def test_a_graph_with_nothing_running_is_drawn_once_not_every_tick(self) -> None:
        from unittest.mock import patch

        from omh.tui import dag_pager

        app = self.app
        clock = [100.0]
        app.clock = lambda: clock[0]
        app.color_depth, app.motion = TRUECOLOR, True
        settled = dag_export_run()
        for node in settled["nodes"]:
            if node.get("state") == "running":
                node.update(state="done", status="accepted")
        for graph, draws in ((settled, 0), (dag_export_run(), 3)):
            with self.subTest(running=draws > 0):
                with_hud(app, graph)
                send(app, "/dag")
                screen(app)  # the first frame draws it (and again on the node it opens on)
                with patch.object(dag_pager, "dag_page_lines", wraps=dag_pager.dag_page_lines) as drawn:
                    for _ in range(3):
                        clock[0] += 0.35
                        screen(app)
                self.assertEqual(drawn.call_count, draws)
                app.pager = None

    def test_a_page_that_is_no_longer_live_stands_still(self) -> None:
        app = self.app
        app.color_depth, app.motion = TRUECOLOR, True
        send(app, "/dag")
        screen(app)
        still = dag_page_lines(app.hud.payload, 100, app.theme, TRUECOLOR, focus=_focus(app.pager))[0]
        with_hud(app, None, received_at=0.0)
        screen(app)
        self.assertEqual(app.pager.lines[1:], still, "under its note, the last drawing with no aura")

    def test_the_graph_printed_into_the_transcript_never_takes_it(self) -> None:
        block = dag_block.DagBlock("plan", dag_export_run())
        theme = self.app.theme
        rows = dag_block.rows(block, 100, theme)
        self.assertFalse(any(span.style.fg in aura_colours(theme) for line in rows for span in line))


def recall_result(records: list[dict] | None = None, **fields) -> dict:
    """An `omh_memory` recall's result as Hermes hands it over (decoded), in the shape the tool writes."""
    records = [
        {"record_id": "r1", "record_type": "decision", "summary": "rotate refresh tokens per session", "tags": []},
        {"record_id": "r2", "record_type": "fact", "summary": "the guard lives in src/auth/guard.py", "tags": []},
    ] if records is None else records
    return {"schema_version": "omh_memory_recall/v1", "status": "found", "records": records,
            "record_count": len(records), "plugin_tool": "omh_memory", "action": "recall",
            "source_backend": "bundle_memory", **fields}


class RecallGlintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = [100.0]
        self.transcript = Transcript(lambda: self.now[0])
        self.theme = make_app()[0].theme

    def complete(self, name: str, result: object, tool_id: str = "m1") -> None:
        self.transcript.apply(Event("tool.start", "s", {"tool_id": tool_id, "name": name, "context": "recall"}))
        self.transcript.apply(Event("tool.complete", "s", {"tool_id": tool_id, "name": name, "result": result,
                                                           "duration_s": 0.4}))

    def rows(self, at: float, glint: bool = True):
        self.now[0] = at
        return self.transcript.live_lines(80, self.theme, now=at, glint=glint)

    def glinting(self, rows) -> bool:
        colours = aura_colours(self.theme)
        return any(span.style.fg in colours for line in rows for span in line)

    def test_a_found_recall_lists_its_records_and_one_band_sweeps_them(self) -> None:
        self.complete("omh_memory", recall_result())
        start = self.rows(100.0)
        self.assertEqual([text(line) for line in start][1:], [
            "┃   ⎿  decision  rotate refresh tokens per session", "┃      fact      the guard lives in src/auth/guard.py"])
        frames = [self.rows(100.0 + step * RECALL_GLINT_SECONDS / 6) for step in range(1, 6)]
        self.assertTrue(all(self.glinting(rows) for rows in frames), "the band is on the rows through the sweep")
        self.assertEqual(len({tuple(rows) for rows in frames}), 5, "and it moves every frame")
        self.assertEqual([text(line) for line in frames[2]], [text(line) for line in start], "the words stay")
        call = frames[2][0]
        self.assertFalse(any(span.style.fg in aura_colours(self.theme) for span in call), "the call's own row does not")
        done = self.rows(100.0 + RECALL_GLINT_SECONDS + 0.05)
        self.assertFalse(self.glinting(done), "once: the sweep is over")
        self.assertEqual(done, self.transcript.live_lines(80, self.theme), "and it draws as it does with no clock")

    def test_a_record_reaches_the_terminal_without_escapes_or_control_characters_and_cut_to_the_width(self) -> None:
        hostile = [{"record_type": "deci\x1b[31msion\r", "summary": "line one\x1b]0;title\x07 \x00ok\rmore\nline two"},
                   {"record_type": "fact", "summary": "x" * 300}]
        self.complete("omh_memory", recall_result(hostile))
        rows = self.transcript.live_lines(80, self.theme)
        shown = [text(line) for line in rows][1:]
        self.assertEqual(shown[0], "┃   ⎿  decision  line one okmore", "the first line only, nothing unpainted in it")
        self.assertTrue(all("\x1b" not in row and "\r" not in row and "\x00" not in row for row in shown))
        self.assertTrue(all(line_width(line) <= 80 for line in rows), "cut to the width like any output row")
        self.assertTrue(shown[1].endswith("…"))

    def test_the_type_column_is_measured_in_cells_and_a_long_type_is_cut(self) -> None:
        self.complete("omh_memory", recall_result([{"record_type": "결정사항", "summary": "wide type"},
                                                   {"record_type": "fact", "summary": "narrow type"}]))
        shown = [text(line) for line in self.transcript.live_lines(120, self.theme)][1:]
        starts = {line_width((Span(row[: row.index(word)]),)) for row, word in zip(shown, ("wide type", "narrow type"))}
        self.assertEqual(len(starts), 1, f"one summary column in cells: {shown}")
        self.setUp()
        self.complete("omh_memory", recall_result([
            {"record_type": "a-record-type-far-longer-than-any-real-one", "summary": "still in sight"}]))
        shown = [text(line) for line in self.transcript.live_lines(120, self.theme)][1:]
        self.assertEqual(shown, ["┃   ⎿  a-record-ty…  still in sight"])

    def test_records_that_are_not_a_list_print_nothing_and_raise_nothing(self) -> None:
        for records in (5, "decision", {"record_type": "fact"}, None):
            with self.subTest(records=records):
                self.setUp()
                self.complete("omh_memory", {**recall_result(), "records": records})
                rows = self.transcript.live_lines(80, self.theme)
                self.assertEqual(len(rows), 1, [text(line) for line in rows])

    def test_a_recall_that_found_nothing_and_other_memory_actions_keep_todays_rows(self) -> None:
        """Today a decoded `omh_memory` result prints nothing under its row (it has no output field)."""
        cases = {
            "nothing found": recall_result([], status="nothing_found"),
            "a count of 0 under found": recall_result([], status="found"),
            "a refusal": {"status": "refused", "action": "recall", "reason": "query_invalid", "plugin_tool": "omh_memory"},
            "a capture": {"status": "saved", "action": "capture", "plugin_tool": "omh_memory"},
            "status": {"status": "ok", "action": "status", "plugin_tool": "omh_memory"},
            "a confirm": {"status": "confirmed", "action": "confirm", "plugin_tool": "omh_memory", "record_id": "r1"},
        }
        for name, result in cases.items():
            with self.subTest(name):
                self.setUp()
                self.complete("omh_memory", result)
                rows = self.transcript.live_lines(80, self.theme)
                self.assertEqual(len(rows), 1, [text(line) for line in rows])
                self.assertEqual(self.transcript.blocks[-1].tools[-1].output, ())

    def test_an_omh_remember_recall_lists_and_glints_like_omh_memory(self) -> None:
        # The audit's LOW #10: the band matched `omh_memory` only, while the
        # model's own recall tool is `omh_remember`, with the same result shape.
        self.complete("omh_remember", {**recall_result(), "plugin_tool": "omh_remember"})
        self.assertEqual([text(line) for line in self.transcript.live_lines(80, self.theme)][1:], [
            "┃   ⎿  decision  rotate refresh tokens per session", "┃      fact      the guard lives in src/auth/guard.py"])
        self.assertTrue(self.glinting(self.rows(100.0 + RECALL_GLINT_SECONDS / 2)))
        for name, result in {
            "a save": {"status": "remembered", "action": "save", "plugin_tool": "omh_remember", "record_id": "r1"},
            "a recall that found nothing": {**recall_result([], status="nothing_found"), "plugin_tool": "omh_remember"},
            "a refused recall": {"status": "refused", "action": "recall", "reason": "recall_disabled", "plugin_tool": "omh_remember"},
        }.items():
            with self.subTest(name):
                self.setUp()
                self.complete("omh_remember", result)
                self.assertFalse(self.glinting(self.rows(100.0 + RECALL_GLINT_SECONDS / 2)))
                self.assertIsNone(self.transcript.blocks[-1].tools[-1].recalled_at)

    def test_a_json_string_result_reads_the_same(self) -> None:
        import json

        self.complete("omh_memory", json.dumps(recall_result()))
        self.assertTrue(self.glinting(self.rows(100.0 + RECALL_GLINT_SECONDS / 2)))

    def test_nothing_else_glints(self) -> None:
        cases = {
            "a recall that found nothing": ("omh_memory", recall_result([], status="nothing_found")),
            "a refused recall": ("omh_memory", {"status": "refused", "action": "recall", "reason": "query_invalid"}),
            "a count under a status that is not found": ("omh_memory", recall_result(status="refused")),
            "a count that is not a number": ("omh_memory", recall_result(record_count=True)),
            "a capture": ("omh_memory", {**recall_result(), "action": "capture"}),
            "another tool with the same fields": ("search_files", {**recall_result(), "output": "x"}),
            "a broken JSON string": ("omh_memory", '{"action": "recall", "status": "found", '),
            "a terminal call that printed": ("terminal", {"output": "decision  rotate refresh tokens", "exit_code": 0}),
        }
        for name, (tool, result) in cases.items():
            with self.subTest(name):
                self.setUp()
                self.complete(tool, result)
                self.assertFalse(self.glinting(self.rows(100.0 + RECALL_GLINT_SECONDS / 2)))
                self.assertIsNone(self.transcript.blocks[-1].tools[-1].recalled_at)

    def test_where_the_aura_does_not_move_and_in_scrollback_it_draws_as_before(self) -> None:
        self.complete("omh_memory", recall_result())
        still = self.transcript.live_lines(80, self.theme)
        middle = 100.0 + RECALL_GLINT_SECONDS / 2
        self.assertEqual(self.rows(middle, glint=False), still, "no glint: motion off, 256 or 16 colours, no colour")
        self.now[0] = middle
        self.assertEqual(self.transcript.live_lines(80, self.theme, now=None, glint=True), still, "no clock")
        self.assertFalse(self.glinting(self.transcript.history_lines(80, self.theme)), "history never glints")
        self.transcript.apply(Event("message.complete", "s", {"text": "done"}))
        taken = self.transcript.take_stable_lines(80, self.theme)
        self.assertFalse(self.glinting(taken), "the rows as scrollback keeps them")
        self.assertIn("┃   ⎿  decision  rotate refresh tokens per session", [text(line) for line in taken])

    def test_the_app_glints_only_where_the_aura_moves(self) -> None:
        app, _client = make_app(busy=True, cols=80)
        clock = [50.0]
        app.clock = lambda: clock[0]
        app.transcript = Transcript(app.clock)
        app.transcript.apply(Event("tool.start", "s", {"tool_id": "m1", "name": "omh_memory"}))
        app.transcript.apply(Event("tool.complete", "s", {"tool_id": "m1", "name": "omh_memory",
                                                          "result": recall_result()}))
        clock[0] += RECALL_GLINT_SECONDS / 2
        for depth, motion, moves in ((TRUECOLOR, True, True), (COLOR_256, True, False), (NO_COLOR, True, False),
                                     (TRUECOLOR, False, False)):
            with self.subTest(depth=depth, motion=motion):
                app.color_depth, app.motion = depth, motion
                self.assertEqual(self.glinting(app._tail(80)), moves)


def _focus(pager):
    from omh.plugin_bundle.omh.delegation_view import Focus

    return Focus(pager.node, pager.folded, pager.details)


if __name__ == "__main__":
    unittest.main()

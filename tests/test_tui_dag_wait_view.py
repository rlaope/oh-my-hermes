"""A dag-ulw run waiting, under the composer (the owner, 2026-11-04: "좀 정적이기도하고 하단에 영역이 너무많기도해서",
then of the 8-row try "지금은 너무없고 너무 촘촘해": too little shown, too cramped).

A run of up to `dag_block.SMALL_GRAPH_LANES` lanes shows whole: every layer
and node, a done one-node layer on one dim row (`✓ layer 2 · <title>`), one
blank row between layer groups, open layer rows without the counts their
node rows say. A bigger run folds its settled layers into one `✓ layers 1–3`
row and opens the live layers and the one that comes next. The tree is at
most `agent_view.TREE_ROWS` rows (and a third of the screen); what does not
fit is one `+N more · /dag` row. A parked node is a waiting one (it was drawn
`?` and counted `unknown`), counted `parked`, with its time since it parked,
what its park recorded it waits on, and the spinner. Waiting rows carry slow
dots; times count on. An `unspecified-*` or unknown category draws no cell. A
plan declared while the run was open (`todo.dag_run`) is one line over that
run's tree; any other plan is drawn as before.

The graphs are dag run records', as `delegation_graph._dag_nodes` builds
them: the owner's screenshots (`screenshot_run`), and a five-layer run with
the parked node in layer 4 (`owners_run`).
"""

from __future__ import annotations

import re
import time
import unittest
from unittest.mock import patch

from _delegation_graphs import graph, lane, root
from test_tui_agent_view import mode_row, view_text, with_graph
from test_tui_modes import drawn, make_app
from omh.tui.background import BackgroundProcess, tool_call
from omh.tui.keys import CHAR, Key

RUN = "pr-a"
SONNET = "claude-sonnet-5-5"
PARKED_AT = 1_800_000_000.0
WAKE_AT = PARKED_AT + 1800
PROC = "proc_5f43a1c2"


def node_id(key: str) -> str:
    return f"d:{RUN}:{key}"


def owners_run(*, handle: str = PROC, reason: str = "", parked: bool = True) -> dict:
    """The owner's run: layers 1–3 done, layer 4 the baseline check parked on a background process, layer 5 two
    nodes waiting on it."""
    nodes = [root(SONNET, "high")]
    for order, (key, title, layer) in enumerate(
            (("t1", "Record fetch receipts", 1), ("t2", "Check draft citations", 2),
             ("t3", "Tell the research skills", 3)), start=1):
        done = lane(node_id(key), title, "unspecified-high", SONNET, "medium", "done", elapsed=200 + order,
                    order=order, group=f"layer {layer}", status="accepted")
        nodes.append({**done, "dag_node": key, "output_tokens": 2000 + order})
    baseline = lane(node_id("baseline"), "Full baseline check (before change)", "quick", SONNET, "medium",
                    "waiting", order=4, group="layer 4", status="parked")
    if parked:
        baseline.update(parked=True, parked_at=PARKED_AT, elapsed_seconds=87.0, wake_at=WAKE_AT, wait_handle=handle)
        if reason:
            baseline["wait_reason"] = reason
    nodes.append({**baseline, "dag_node": "baseline", "output_tokens": 4300})
    for order, (key, title) in enumerate((("t4", "Wire the receipts check"), ("verify", "Verify the run")), start=5):
        nodes.append({**lane(node_id(key), title, "unspecified-low", "?", "", "waiting", order=order, group="layer 5",
                             waits=1), "dag_node": key})
    edges = [("root", node_id("t1"), "dispatch"), (node_id("t1"), node_id("t2"), "depends_on"),
             (node_id("t2"), node_id("t3"), "depends_on"), (node_id("t1"), node_id("baseline"), "depends_on"),
             (node_id("t3"), node_id("baseline"), "depends_on"), (node_id("baseline"), node_id("t4"), "depends_on"),
             (node_id("baseline"), node_id("verify"), "depends_on")]
    built = graph(nodes, edges, name="citation receipts (PR A)", source="dag")
    built["dag_open"] = True
    return built


PROCESS = BackgroundProcess(PROC, None, False, None, "uv run python -m unittest discover -s tests", PARKED_AT, False,
                            False)
CALL = tool_call(PROCESS)  # `terminal(uv run python -m unittest disco…)`, as the info line's background row names it


def waiting_app(built: dict | None = None, *, rows: int = 50, cols: int = 120, busy: bool = False, **options: object):
    app, client = make_app(busy=busy, rows=rows, cols=cols, clock=lambda: 0.0, **options)
    app.bg_running = (PROCESS,)
    with_graph(app, owners_run() if built is None else built)
    drawn(app)
    return app, client


def rows_of(app) -> list[str]:
    return [row.rstrip() for row in view_text(app)]


def until() -> str:
    return time.strftime("%H:%M", time.localtime(WAKE_AT))


def screenshot_run() -> dict:
    """The owner's screenshots: layer 1 the parked baseline beside the done hook, layers 2 and 3 done, the closing
    gate in layer 4 and the review in layer 5, each waiting on 1 lane."""
    nodes = [root(SONNET, "high")]
    baseline = lane(node_id("baseline"), "기준선 전체 검사 (변경 전)", "quick", SONNET, "medium", "waiting", order=1,
                    group="layer 1", status="parked")
    baseline.update(parked=True, parked_at=PARKED_AT, elapsed_seconds=87.0, wake_at=WAKE_AT, wait_handle=PROC,
                    output_tokens=4300)
    nodes.append(baseline)
    for order, (key, title, layer) in enumerate((("t1", "웹 도구 영수증 자동 기록 (훅)", 1),
                                                 ("t2", "omh research receipts verify 명령", 2),
                                                 ("t3", "리서치 스킬 지침 + 재생성", 3)), start=2):
        nodes.append(lane(node_id(key), title, "unspecified-high", SONNET, "medium", "done", elapsed=60,
                          order=order, group=f"layer {layer}", status="accepted"))
    nodes.append(lane(node_id("gate"), "닫는 게이트: 전체 검사 + 스모크", "unspecified-low", "?", "", "waiting", order=5,
                      group="layer 4", waits=1))
    nodes.append(lane(node_id("review"), "코드 리뷰", "review", "?", "", "waiting", order=6, group="layer 5", waits=1))
    edges = [("root", node_id("baseline"), "dispatch"), ("root", node_id("t1"), "dispatch"),
             (node_id("t1"), node_id("t2"), "depends_on"), (node_id("t2"), node_id("t3"), "depends_on"),
             (node_id("baseline"), node_id("gate"), "depends_on"), (node_id("t3"), node_id("gate"), "depends_on"),
             (node_id("gate"), node_id("review"), "depends_on")]
    built = graph(nodes, edges, name="인용 영수증 (PR A)", source="dag")
    built["dag_open"] = True
    return built


class OwnersCaseTests(unittest.TestCase):
    """The owner's run whole at 150x42: every layer and node, the done ones dim on one row each, blank rows between
    groups, the parked node live."""

    def test_the_owners_run_reads_whole_in_fourteen_rows(self) -> None:
        for busy in (False, True):
            with self.subTest(busy=busy):
                app, _client = waiting_app(screenshot_run(), rows=42, cols=150, busy=busy)
                self.assertEqual(rows_of(app), [
                    "  DAG · 인용 영수증 (PR A) · 6 nodes · 5 edges · 1 parked · 2 waiting · 3 done",
                    "  ▾ layer 1 · 2 nodes",
                    "    ▾ ⠋ 기준선 전체 검사 (변경 전)               quick  · sonnet-5-5:medium · parked 1m 27s   · ↓4.3k",
                    f"        › waits on {CALL} · until {until()}",
                    "      ✓ 웹 도구 영수증 자동 기록 (훅)                     sonnet-5-5:medium · accepted 1m 0s",
                    "",
                    "  ✓ layer 2 · omh research receipts verify 명령           sonnet-5-5:medium · accepted 1m 0s",
                    "  ✓ layer 3 · 리서치 스킬 지침 + 재생성                   sonnet-5-5:medium · accepted 1m 0s",
                    "",
                    "  ▾ layer 4",
                    "      · 닫는 게이트: 전체 검사 + 스모크                                       waits on 1 lane ·",
                    "",
                    "  ▾ layer 5",
                    "      · 코드 리뷰                                review                     · waits on 1 lane ·",
                ])

    def test_a_done_layers_row_is_quiet(self) -> None:
        from omh.tui.dag_tree import tree_lines

        app, _client = waiting_app(screenshot_run(), rows=42, cols=150)
        lines, _state = tree_lines(screenshot_run(), app.roster, 150, 16, app.theme, 0, {}, None)
        row = next(line for line in lines if "omh research receipts verify" in "".join(span.text for span in line))
        title = next(span for span in row if "omh research" in span.text)
        self.assertEqual((title.style.fg, title.style.bold), (app.theme.muted.fg, app.theme.muted.bold))

    def test_the_parked_node_is_not_unknown(self) -> None:
        app, _client = waiting_app()
        shown = "\n".join(rows_of(app))
        self.assertNotIn("unknown", shown)
        self.assertNotIn(" ? ", shown)

    def test_the_wait_names_the_handle_itself_when_no_running_process_has_it(self) -> None:
        app, _client = waiting_app(owners_run(handle="gh-run-19868735137", reason="CI on the PR"))
        self.assertIn(f"        › waits on gh-run-19868735137 · until {until()} · CI on the PR", rows_of(app))

    def test_a_park_that_recorded_nothing_to_name_draws_no_wait_row(self) -> None:
        built = owners_run()
        baseline = next(node for node in built["nodes"] if node["id"] == node_id("baseline"))
        for key in ("wake_at", "wait_handle"):
            baseline.pop(key)
        app, _client = waiting_app(built)
        shown = rows_of(app)
        titles = [re.split(r"(?<=\S) {2,}", row)[0] for row in shown]
        self.assertIn("      ⠋ Full baseline check (before change)", titles)
        self.assertFalse([row for row in shown if "›" in row], "nothing guessed")

    def test_no_category_cell_for_unspecified_or_unknown(self) -> None:
        from omh.tui.dag_tree import _figure_parts

        app, _client = waiting_app()
        self.assertFalse([row for row in rows_of(app) if "unspecified" in row])
        self.assertEqual(_figure_parts({"category": "unspecified-high", "model": "glm-5.3", "state": "done"})[0], "")
        self.assertEqual(_figure_parts({"category": "?", "model": "?", "state": "waiting"})[0], "")
        self.assertEqual(_figure_parts({"category": "deep", "model": "glm-5.3", "state": "done"})[0], "deep")


class FoldTests(unittest.TestCase):
    """A small run shows whole; a big one folds its settled layers and opens the live layers and the next."""

    def big(self) -> dict:
        """The owner's run with eight more nodes done in layer 2 and twelve waiting nodes in three layers after it:
        26 lanes, past `SMALL_GRAPH_LANES`."""
        built = owners_run()
        for number in range(8):
            built["nodes"].insert(3, lane(node_id(f"pre-{number}"), f"Prep {number}", "quick", SONNET, "low", "done",
                                          elapsed=30, order=2, group="layer 2", status="accepted"))
            built["edges"].append({"from": node_id("t1"), "to": node_id(f"pre-{number}"), "kind": "depends_on"})
        for number in range(12):
            built["nodes"].append(lane(node_id(f"late-{number}"), f"Later step {number}", "quick", "?", "", "waiting",
                                       order=200 + number, group=f"layer {6 + number // 4}", waits=1))
            built["edges"].append({"from": node_id("t4"), "to": node_id(f"late-{number}"), "kind": "depends_on"})
        return built

    def test_a_small_run_shows_every_layer_and_node_at_any_size_that_holds_it(self) -> None:
        for rows in (42, 50, 72):
            with self.subTest(rows=rows):
                app, _client = waiting_app(screenshot_run(), rows=rows, cols=150)
                shown = rows_of(app)
                self.assertFalse([row for row in shown if "more" in row], shown)
                for title in ("기준선 전체 검사", "웹 도구 영수증", "omh research receipts verify", "리서치 스킬 지침",
                              "닫는 게이트", "코드 리뷰"):
                    self.assertTrue([row for row in shown if title in row], title)

    def test_a_big_run_folds_its_done_layers_and_keeps_its_live_node_in_the_cap(self) -> None:
        from omh.tui.agent_view import TREE_ROWS

        for rows in (40, 50, 72):
            with self.subTest(rows=rows):
                app, _client = waiting_app(self.big(), rows=rows)
                shown = rows_of(app)
                self.assertLessEqual(len(shown), min(TREE_ROWS, rows // 3), shown)
                self.assertTrue([row for row in shown if "▾ ⠋ Full baseline check" in row], shown)
                self.assertIn(f"        › waits on {CALL} · until {until()}", shown)
                self.assertIn("  ▾ layer 5 · 2 nodes", [re.sub(r" ·{1,3}$", "", row) for row in shown],
                              "the layer that comes next stays open")
                self.assertFalse([row for row in shown if "Prep" in row], "the done layers are folded")
        app, _client = waiting_app(self.big(), rows=72)
        self.assertIn("  ▸ ✓ layers 1–3 · 11 done", rows_of(app))
        app, _client = waiting_app(self.big(), rows=40)
        self.assertEqual(rows_of(app)[-1], "  +11 more · /dag", "at 13 rows the done layers' row gave way first")

    def test_a_row_of_done_nodes_gives_way_before_the_parked_nodes_wait(self) -> None:
        built = owners_run()
        for number in range(6):  # layer 4 also holds two running nodes and six done ones: 14 lanes
            built["nodes"].append(lane(node_id(f"done-{number}"), f"Done step {number}", "quick", SONNET, "low",
                                       "done", elapsed=30, order=50 + number, group="layer 4", status="accepted"))
        for number in range(2):
            built["nodes"].append(lane(node_id(f"run-{number}"), f"Running step {number}", "quick", SONNET, "low",
                                       "running", elapsed=30, order=60 + number, group="layer 4"))
        for key in [f"done-{number}" for number in range(6)] + ["run-0", "run-1"]:
            built["edges"].append({"from": node_id("t3"), "to": node_id(key), "kind": "depends_on"})
        app, _client = waiting_app(built, rows=33)  # a cap of 11
        shown = rows_of(app)
        self.assertIn(f"        › waits on {CALL} · until {until()}", shown)
        self.assertFalse([row for row in shown if "6 more · 6 done" in row], shown)
        self.assertEqual(shown[-1], "  +9 more · /dag", "the 3 done layers and the 6 done nodes")

    def test_in_a_big_run_the_layer_that_comes_next_is_past_the_done_ones(self) -> None:
        built = screenshot_run()  # the owner's layout, eight more done nodes in layer 2: 14 lanes, a big run
        for number in range(8):
            built["nodes"].append(lane(node_id(f"pre-{number}"), f"Prep {number}", "quick", SONNET, "low", "done",
                                       elapsed=30, order=20 + number, group="layer 2", status="accepted"))
            built["edges"].append({"from": node_id("t1"), "to": node_id(f"pre-{number}"), "kind": "depends_on"})
        app, _client = waiting_app(built, rows=72, cols=150)
        shown = [re.sub(r" ·{1,3}$", "", row) for row in rows_of(app)]
        self.assertIn("  ▸ ✓ layers 2–3 · 10 done", shown)
        self.assertIn("  ▾ layer 4", shown, "layers 2 and 3 are done: layer 4 comes next")
        self.assertTrue([row for row in shown if row.startswith("      · 닫는 게이트")], shown)
        self.assertIn("  ▸ layer 5 · 1 node · 1 waiting", shown)

    def test_a_shut_layer_counts_its_parked_node_as_parked(self) -> None:
        app, _client = waiting_app()
        self.assertIn("  ▸ layer 4 · 1 node · 1 parked", tree_text(owners_run(), app, {"layer:layer 4": False}))

    def test_layers_past_the_one_after_a_live_layer_stay_shut(self) -> None:
        app, _client = waiting_app(self.big(), rows=72, cols=160)
        with patch("omh.tui.agent_view.TREE_ROWS", 40):  # room for every row the defaults open
            shown = [re.sub(r" ·{1,3}$", "", row) for row in rows_of(app)]  # the waiting dots left off
        self.assertIn("  ▾ layer 5 · 2 nodes", shown)
        self.assertIn("  ▸ layer 6 · 4 nodes · 4 waiting", shown)
        self.assertIn("  ▸ layer 8 · 4 nodes · 4 waiting", shown)

    def test_the_done_row_opens_to_its_layers_and_left_folds_it_again(self) -> None:
        from omh.tui.keys import DOWN, LEFT, RIGHT, UP

        app, _client = waiting_app(self.big(), rows=72)
        app._on_input(Key(DOWN))
        for _ in range(10):
            app._on_input(Key(UP))
        self.assertEqual(app.tree_selected, "settled:layer 1")
        app._on_input(Key(RIGHT))
        self.assertEqual(app.tree_selected, "layer:layer 1", "the first of its layers is highlighted")
        opened = [row.replace("❯", " ", 1) for row in rows_of(app)]
        self.assertIn("  ▸ layer 1 · 1 node · 1 done", [re.sub(r" ·{1,3}$", "", row) for row in opened])
        app._on_input(Key(LEFT))  # a shut layer: Left goes to its parent, the done row
        self.assertEqual(app.tree_selected, "settled:layer 1")
        app._on_input(Key(LEFT))
        self.assertIn("▸ ✓ layers 1–3 · 11 done", " ".join(rows_of(app)))


def tree_text(built: dict, app, folds: dict | None = None, **live: object) -> list[str]:
    from omh.tui.dag_tree import tree_lines

    lines, _state = tree_lines(built, app.roster, 120, 20, app.theme, 0, folds or {}, None, **live)
    return ["".join(span.text for span in line).rstrip() for line in lines]


class MotionTests(unittest.TestCase):
    """The owner's second screenshot (the same run 10 minutes on, nothing changed): the rows under a live run move.
    A waiting row and a shut layer of waiting nodes carry slow dots; the parked and running times count on; done
    rows, the done layers' row and a run that is not alive stay still."""

    def test_only_waiting_rows_and_shut_waiting_layers_take_the_dots(self) -> None:
        app, _client = waiting_app()
        built = owners_run()
        steps = [tree_text(built, app, beat=beat) for beat in range(3)]
        moved = [at for at in range(len(steps[0])) if len({step[at] for step in steps}) > 1]
        waiting = ["      · Wire the receipts check                                          waits on 1 lane ·",
                   "      · Verify the run                                                   waits on 1 lane ·"]
        self.assertEqual([steps[0][at] for at in moved], waiting)
        self.assertEqual([steps[2][at][-4:] for at in moved], [" ···", " ···"], "one to three dots")
        shut = tree_text(built, app, {"layer:layer 5": False}, beat=1)
        self.assertIn("  ▸ layer 5 · 2 nodes · 2 waiting ··", shut, "a shut layer of waiting nodes moves too")
        self.assertFalse([at for at in moved if steps[0][at].startswith("  ✓")], "done rows stay still")

    def test_a_run_that_is_not_alive_draws_no_dots(self) -> None:
        app, _client = waiting_app()
        over = owners_run(parked=False)
        over["dag_open"] = False
        self.assertEqual(tree_text(over, app, beat=2), tree_text(over, app, beat=None))
        self.assertFalse([row for row in tree_text(over, app, beat=2) if row.endswith("·")])

    def test_the_parked_and_running_times_count_on_and_the_process_time_shows(self) -> None:
        app, _client = waiting_app()
        built = owners_run()
        running = lane(node_id("t5"), "Draft the docs", "writing", SONNET, "low", "running", elapsed=40, order=9,
                       group="layer 4")
        built["nodes"].append(running)
        built["edges"].append({"from": node_id("t3"), "to": node_id("t5"), "kind": "depends_on"})
        processes = {PROC: (CALL, PARKED_AT - 519)}

        def at(wall: float, read: float = PARKED_AT + 87) -> str:
            return "\n".join(tree_text(built, app, wall=wall, received_at=read, processes=processes))

        first, later = at(PARKED_AT + 87), at(PARKED_AT + 88)
        self.assertIn("parked 1m 27s", first)
        self.assertIn("parked 1m 28s", later)
        self.assertIn("running 40s", first)
        self.assertIn("running 41s", later)
        self.assertIn(f"waits on {CALL} 10m 06s · until {until()}", first)
        self.assertIn(f"waits on {CALL} 10m 07s", later)
        self.assertIn("running 40s", at(PARKED_AT + 88, read=0.0), "a read without its time adds nothing")

    def test_unfocused_the_motion_holds_and_the_times_redraw_once_a_second(self) -> None:
        from omh.tui.app import IDLE_READ_SECONDS, TICK_SECONDS
        from omh.tui.panels import HudSnapshot

        clock, wall = [100.0], [PARKED_AT + 87]
        app, _client = make_app(rows=50, cols=120, clock=lambda: clock[0], wall_clock=lambda: wall[0])
        app.bg_running = ()
        with_graph(app, owners_run())
        app.hud = HudSnapshot(app.hud.session_id, app.hud.payload, PARKED_AT + 87)
        drawn(app)
        self.assertTrue(app.tree_state.moves and app.tree_state.clocks)
        self.assertLessEqual(app._read_timeout(), TICK_SECONDS, "focused: the spinner's pace")
        app.decoder.unfocused_at = clock[0]
        before = rows_of(app)
        clock[0] += 0.5  # half a second: no new second, and the motion holds
        wall[0] += 0.5
        self.assertEqual(rows_of(app), before, "unfocused: spinner and dots hold")
        self.assertFalse(app._tree_spins())
        timeout = app._read_timeout()
        self.assertGreater(timeout, TICK_SECONDS, "no wake-up at the spinner's pace while unfocused")
        self.assertLessEqual(timeout, 1.0)
        self.assertLess(timeout, IDLE_READ_SECONDS)
        clock[0] += 0.6
        wall[0] += 0.6
        after = rows_of(app)
        self.assertEqual([row.replace("1m 27s", "1m 28s") for row in before], after,
                         "only the time moved: the spinner frame and the dots held")
        app.decoder.unfocused_at = None
        clock[0] += 0.1
        self.assertNotEqual(rows_of(app), after, "focus back: the motion goes on")


class SpinnerTests(unittest.TestCase):
    """The spinner turns on a running or parked node's row and nowhere else, at the spinner's pace, idle or not."""

    def test_only_the_live_rows_change_from_frame_to_frame(self) -> None:
        from omh.tui.dag_tree import tree_lines
        from omh.tui.panels import SPINNER_FRAMES

        app, _client = waiting_app()
        built = app.hud.payload["delegation_graph"]
        running = lane(node_id("t5"), "Draft the docs", "writing", SONNET, "low", "running", elapsed=40, order=9,
                       group="layer 4")
        built["nodes"].append(running)
        built["edges"].append({"from": node_id("t3"), "to": node_id("t5"), "kind": "depends_on"})

        def text(frame: int) -> list[str]:
            lines, _state = tree_lines(built, app.roster, 120, 20, app.theme, frame, {}, None)
            return ["".join(span.text for span in line) for line in lines]

        first, second = text(0), text(1)
        changed = [(a, b) for a, b in zip(first, second) if a != b]
        self.assertEqual(len(changed), 2, changed)
        for before, after in changed:
            self.assertTrue(("Draft the docs" in before) or ("Full baseline check" in before), before)
            self.assertIn(SPINNER_FRAMES[0], before)
            self.assertIn(SPINNER_FRAMES[1], after)

    def test_the_loop_ticks_for_a_parked_node_between_turns_and_not_without_one(self) -> None:
        from omh.tui.app import IDLE_READ_SECONDS

        app, _client = waiting_app()
        app.bg_running = ()  # the background row's clock would make a frame due on its own
        drawn(app)
        self.assertFalse(app._busy())
        self.assertTrue(app.tree_state.moves)
        self.assertLess(app._read_timeout(), IDLE_READ_SECONDS, "the spinner's tick is due")
        over = owners_run(parked=False)
        over["dag_open"] = False  # nothing live and the run not open: nothing moves, nothing counts
        still, _client = waiting_app(over)
        still.bg_running = ()
        drawn(still)
        self.assertFalse(still.tree_state.moves or still.tree_state.clocks)
        self.assertEqual(still._read_timeout(), IDLE_READ_SECONDS, "nothing turns: no tick")
        reduced, _client = waiting_app(environ={"OMH_TUI_REDUCED_MOTION": "1"})
        self.assertFalse(reduced.motion)
        self.assertFalse(reduced._tree_spins(), "with reduced motion nothing turns, so nothing ticks")


class PlanTests(unittest.TestCase):
    """The plan over a run's tree is drawn whole, as on main, and Ctrl+P folds and opens it (the owner, 2026-11-05: a
    plan folded on its own was confusing)."""

    PLAN = [{"text": "PR A: T1 receipts", "state": "done"}, {"text": "PR A: T2 citations", "state": "done"},
            {"text": "PR A: T3 skills", "state": "done"}, {"text": "PR A: baseline", "state": "active"},
            {"text": "PR A: T4 wire", "state": "pending"}, {"text": "PR A: verify", "state": "pending"}]

    def plan_rows(self, app) -> list[str]:
        return [row.strip() for row in drawn(app) if "[Plan]" in row or re.match(r"^\s*\[[ ✓•]\] ", row)]

    def test_the_plan_over_a_runs_tree_is_whole_and_ctrl_p_folds_it(self) -> None:
        app, _client = make_app(rows=50, cols=120, clock=lambda: 0.0)
        with_graph(app, owners_run(), self.PLAN)
        self.assertTrue(rows_of(app), "the run's tree is drawn")
        whole = self.plan_rows(app)
        self.assertEqual(len(whole), 7, whole)
        app._on_input(Key(CHAR, "p", ctrl=True))
        self.assertEqual(len(self.plan_rows(app)), 1, "folded to its header")
        app._on_input(Key(CHAR, "p", ctrl=True))
        self.assertEqual(self.plan_rows(app), whole)


class WaitingRowTests(unittest.TestCase):
    """Between turns, a background process Hermes will wake the session for is shown as the working row shows a turn
    (the owner, 2026-11-05: "걍 Musing마냥 … 계속 나오게"): `✻ Waiting… (10m 6s · terminal(…))`, in the working
    row's place, with its spinner and its clock; the info line is main's."""

    def app(self, *, notify: bool = True, watched: bool = False, busy: bool = False, tree: bool = True):
        clock, wall = [100.0], [PARKED_AT + 606]
        app, _client = make_app(busy=busy, rows=50, cols=150, clock=lambda: clock[0], wall_clock=lambda: wall[0])
        app.bg_session = app.stored_id
        app.bg_running = (BackgroundProcess(PROC, None, False, None, "uv run python -m unittest discover -s tests",
                                            PARKED_AT, notify, watched),)
        with_graph(app, owners_run() if tree else None)
        return app, clock, wall

    @staticmethod
    def waiting(app) -> list[str]:
        return [row for row in drawn(app) if "Waiting…" in row]

    def test_it_shows_in_the_working_rows_place_while_the_process_runs(self) -> None:
        from omh.tui.app import WORKING_GLYPHS

        for fields in ({"notify": True}, {"notify": False, "watched": True}):
            with self.subTest(**fields):
                app, _clock, _wall = self.app(**fields)
                screen = drawn(app)
                rule = next(at for at, row in enumerate(screen) if row.startswith("─"))
                (row,) = self.waiting(app)
                self.assertEqual(row[2:], f"Waiting… (10m 6s · {CALL})")
                self.assertIn(row[0], WORKING_GLYPHS)
                self.assertLess(screen.index(row), rule, "above the composer, where the working row stands")
                self.assertEqual(app._working_rows(), 1)
                self.assertIn("🔔 will ping you", mode_row(app), "the info line says what main says")

    def test_not_during_a_turn_not_for_a_process_that_wakes_nothing_and_gone_when_it_ends(self) -> None:
        app, _clock, _wall = self.app(busy=True)
        self.assertEqual(self.waiting(app), [], "during a turn the working row is the turn's")
        app, _clock, _wall = self.app(notify=False)
        self.assertEqual(self.waiting(app), [])
        self.assertEqual(app._working_rows(), 0)
        app, _clock, _wall = self.app()
        self.assertTrue(self.waiting(app))
        app.bg_running = ()
        self.assertEqual(self.waiting(app), [], "the process ended: the row goes")

    def test_the_spinner_turns_and_the_clock_ticks_and_unfocused_the_spinner_holds(self) -> None:
        from omh.tui.app import IDLE_READ_SECONDS, TICK_SECONDS

        app, clock, wall = self.app(tree=False)  # no tree's spinner to tick for: only the wait's row
        first = self.waiting(app)[0]
        self.assertLessEqual(app._read_timeout(), TICK_SECONDS, "focused: the spinner's pace")
        clock[0] += TICK_SECONDS * 1.5  # one spinner step on (a whole TICK_SECONDS can land a hair short in floats)
        self.assertNotEqual(self.waiting(app)[0][0], first[0], "the spinner turned")
        clock[0] += 1
        wall[0] += 1
        self.assertIn("(10m 7s ·", self.waiting(app)[0], "the clock ticked")
        app.decoder.unfocused_at = clock[0]
        held = self.waiting(app)[0]
        clock[0] += 0.5
        self.assertEqual(self.waiting(app)[0][0], held[0], "unfocused: the spinner holds")
        wall[0] += 0.25  # a quarter into the second: the next frame is due at the next second, no sooner
        self.assertAlmostEqual(app._read_timeout(), 0.75, places=6, msg="the clock asks for a frame each second")
        self.assertLess(app._read_timeout(), IDLE_READ_SECONDS)


class ParkedGraphTests(unittest.TestCase):
    """The graph reader maps a parked node to a waiting one with what it waits on (it fell through to `unknown`)."""

    def test_a_parked_node_is_waiting_with_its_park_and_its_time_since(self) -> None:
        from _delegation_state import PARENT, homes
        from test_dag_tool import call, node, slots_table
        from omh.plugin_bundle.omh.delegation_graph import build_delegation_graph
        from omh.plugin_bundle.omh.delegation_view import header_text, render_delegation_view
        from omh.plugin_bundle.omh.tools import dag_tool

        moment = time.time()
        with homes() as home:
            slots_table(home)
            home.session(PARENT, "claude-opus-5-5", effort="high")
            with patch.object(dag_tool.time, "time", return_value=moment):
                call(action="define", run="feat", nodes=[node("a"), node("b", depends_on=("a",))])
                said = call(action="settle", run="feat", node="a", outcome="parked", handle=PROC,
                            wake_at=moment + 600, reason="CI on the PR")
            self.assertEqual(said.get("status"), "ok", said)
            built = build_delegation_graph(home.omh, home.hermes, PARENT, now=moment + 87)
        parked = next(item for item in built["nodes"] if item["id"] == "d:feat:a")
        self.assertEqual((parked["state"], parked["status"], parked["parked"]), ("waiting", "parked", True))
        self.assertEqual((parked["parked_at"], parked["wake_at"], parked["wait_handle"], parked["wait_reason"]),
                         (moment, moment + 600, PROC, "CI on the PR"))
        self.assertAlmostEqual(parked["elapsed_seconds"], 87.0)
        self.assertTrue(built["dag_open"])
        self.assertNotIn("unknown", header_text(built))
        self.assertIn("Parked 1m 27s", render_delegation_view(built, width=120).text())  # the box view too


if __name__ == "__main__":
    unittest.main()

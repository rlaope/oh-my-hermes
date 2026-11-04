"""A dag-ulw run waiting, under the composer (the owner, 2026-11-04: "좀 정적이기도하고 하단에 영역이 너무많기도해서").

The tree under the composer is at most `agent_view.TREE_ROWS` rows: a run of
settled layers is one `✓ layers 1–3 · 3 done` row, only the layers with a
live node and the one after open, no blank row stands between two layers,
and what does not fit is one `+N more · /dag` row. A parked node is a waiting
one (it was drawn `?` and counted `unknown`), with its time since it parked,
what its park recorded it waits on, and the spinner, which turns only on a
running or parked node's row. An `unspecified-*` or unknown category draws no
cell. A plan declared while the run was open (`todo.dag_run`, stamped by
`omh_todo set` and the `todo_list` projection) is one line over that run's
tree; any other plan is drawn as before.

The graph is a dag run record's, as `delegation_graph._dag_nodes` builds it:
the owner's case, five layers, three done, one parked on a background
process, two waiting.
"""

from __future__ import annotations

import json
import re
import time
import unittest
from unittest.mock import patch

from _delegation_graphs import graph, lane, root
from test_tui_agent_view import view_text, with_graph
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


class OwnersCaseTests(unittest.TestCase):
    """The owner's run in `TREE_ROWS` rows: the done layers one row, the parked node live, nothing blank."""

    def test_the_waiting_run_reads_in_eight_rows(self) -> None:
        for busy in (False, True):
            with self.subTest(busy=busy):
                app, _client = waiting_app(busy=busy)
                self.assertEqual(rows_of(app), [
                    "  DAG · citation receipts (PR A) · 6 nodes · 6 edges · 1 parked · 2 waiting · 3 done",
                    "  ▸ ✓ layers 1–3 · 3 done",
                    "  ▾ layer 4 · 1 node · 1 parked",
                    "    ▾ ⠋ Full baseline check (before change)  quick · sonnet-5-5:medium · parked 1m 27s   · ↓4.3k",
                    f"        › waits on {CALL} · until {until()}",
                    "  ▾ layer 5 · 2 nodes · 2 waiting",
                    "      · Wire the receipts check                                          waits on 1 lane ·",
                    "      · Verify the run                                                   waits on 1 lane ·",
                ])

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


class FoldTests(unittest.TestCase):
    def test_the_layer_that_comes_next_opens_past_the_done_layers_within_the_cap(self) -> None:
        from omh.tui.agent_view import TREE_ROWS

        app, _client = waiting_app(screenshot_run(), cols=150)
        shown = [re.sub(r" ·{1,3}$", "", row) for row in rows_of(app)]
        self.assertLessEqual(len(shown), TREE_ROWS)
        self.assertEqual(shown[0], "  DAG · 인용 영수증 (PR A) · 6 nodes · 5 edges · 1 parked · 2 waiting · 3 done")
        self.assertEqual(shown[-1], "  +3 more · /dag", "the done layers' row gave way first, then layer 5")
        self.assertIn("  ▾ layer 4 · 1 node · 1 waiting", shown, "layer 2 and 3 are done: layer 4 comes next")
        self.assertTrue([row for row in shown if row.startswith("      · 닫는 게이트: 전체 검사 + 스모크")], shown)
        self.assertFalse([row for row in shown if "코드 리뷰" in row], "layer 5 stays shut or is counted")
        self.assertTrue([row for row in rows_of(app) if "닫는 게이트" in row and row.endswith("·")], "and it moves")

    """Settled layers fold into one row; only the live layers and the next one open; no blank rows; a cap."""

    def big(self) -> dict:
        """The owner's run with eight more nodes done in layer 2 and twelve waiting nodes in three layers after it."""
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

    def test_a_big_run_is_tree_rows_with_its_live_node_and_a_count_of_the_rest(self) -> None:
        from omh.tui.agent_view import TREE_ROWS

        for rows in (40, 50, 72):
            with self.subTest(rows=rows):
                app, _client = waiting_app(self.big(), rows=rows)
                shown = rows_of(app)
                self.assertEqual(len(shown), TREE_ROWS, shown)
                self.assertTrue([row for row in shown if "▾ ⠋ Full baseline check" in row], shown)
                self.assertIn(f"        › waits on {CALL} · until {until()}", shown,
                              "the parked node keeps its wait row; the cut takes the rows after it")
                self.assertEqual(shown[-1], "  +23 more · /dag", "the 11 done nodes gave way first, then layers 6–8")
                self.assertIn("  ▾ layer 5 · 2 nodes · 2 waiting", [re.sub(r" ·{1,3}$", "", row) for row in shown],
                              "the layer that comes next stays open")
                self.assertNotIn("", shown, "no blank row")

    def test_a_row_of_done_nodes_gives_way_before_the_parked_nodes_wait(self) -> None:
        built = owners_run()
        for number in range(6):  # layer 4 also holds two running nodes and six done ones
            built["nodes"].append(lane(node_id(f"done-{number}"), f"Done step {number}", "quick", SONNET, "low",
                                       "done", elapsed=30, order=50 + number, group="layer 4", status="accepted"))
        for number in range(2):
            built["nodes"].append(lane(node_id(f"run-{number}"), f"Running step {number}", "quick", SONNET, "low",
                                       "running", elapsed=30, order=60 + number, group="layer 4"))
        for key in [f"done-{number}" for number in range(6)] + ["run-0", "run-1"]:
            built["edges"].append({"from": node_id("t3"), "to": node_id(key), "kind": "depends_on"})
        app, _client = waiting_app(built)
        shown = rows_of(app)
        self.assertIn(f"        › waits on {CALL} · until {until()}", shown)
        self.assertFalse([row for row in shown if "6 more · 6 done" in row], shown)
        self.assertEqual(shown[-1], "  +11 more · /dag", "the 3 done layers, the 6 done nodes, layer 5's 2")

    def test_layers_past_the_one_after_a_live_layer_stay_shut(self) -> None:
        app, _client = waiting_app(self.big(), rows=72, cols=160)
        with patch("omh.tui.agent_view.TREE_ROWS", 40):  # room for every row the defaults open
            shown = [re.sub(r" ·{1,3}$", "", row) for row in rows_of(app)]  # the waiting dots left off
        self.assertIn("  ▾ layer 5 · 2 nodes · 2 waiting", shown)
        self.assertIn("  ▸ layer 6 · 4 nodes · 4 waiting", shown)
        self.assertIn("  ▸ layer 8 · 4 nodes · 4 waiting", shown)

    def test_the_done_row_opens_to_its_layers_and_left_folds_it_again(self) -> None:
        from omh.tui.keys import DOWN, LEFT, RIGHT, UP

        app, _client = waiting_app()
        app._on_input(Key(DOWN))
        for _ in range(4):
            app._on_input(Key(UP))
        self.assertEqual(app.tree_selected, "settled:layer 1")
        app._on_input(Key(RIGHT))
        self.assertEqual(app.tree_selected, "layer:layer 1", "the first of its layers is highlighted")
        opened = rows_of(app)
        self.assertIn("  ▸ layer 1 · 1 node · 1 done", [re.sub(r"^.❯?\s*", "  ", row) if row.startswith("❯") else row
                                                      for row in opened])
        app._on_input(Key(LEFT))  # a shut layer: Left goes to its parent, the done row
        self.assertEqual(app.tree_selected, "settled:layer 1")
        app._on_input(Key(LEFT))
        self.assertIn("▸ ✓ layers 1–3 · 3 done", " ".join(rows_of(app)))


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
        self.assertIn("  ▸ ✓ layers 1–3 · 3 done", shut, "the done layers' row stays still")

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


class PlanOnTreeTests(unittest.TestCase):
    """A plan declared while the run was open is one line over the run's tree; any other plan is drawn whole."""

    PLAN = [{"text": "PR A: T1 receipts", "state": "done"}, {"text": "PR A: T2 citations", "state": "done"},
            {"text": "PR A: T3 skills", "state": "done"}, {"text": "PR A: baseline", "state": "active"},
            {"text": "PR A: T4 wire", "state": "pending"}, {"text": "PR A: verify", "state": "pending"}]

    def plan_app(self, run: str | None, built: dict | None = None):
        app, client = make_app(rows=50, cols=120, clock=lambda: 0.0)
        with_graph(app, owners_run() if built is None else built, self.PLAN)
        if run is not None:
            app.hud.payload["todo"]["dag_run"] = run
        return app, client

    def plan_rows(self, app) -> list[str]:
        return [row.strip() for row in drawn(app) if "[Plan]" in row or re.match(r"^\s*\[[ ✓•]\] ", row)]

    def test_the_runs_own_plan_is_one_line_naming_the_item_it_is_on(self) -> None:
        app, _client = self.plan_app(RUN)
        self.assertEqual(self.plan_rows(app), ["[Plan] Plan │ 3/6 ▸ PR A: baseline"])

    def test_another_runs_plan_or_a_plan_of_no_run_is_drawn_whole(self) -> None:
        for run in (None, "pr-b"):
            with self.subTest(run=run):
                app, _client = self.plan_app(run)
                shown = self.plan_rows(app)
                self.assertGreater(len(shown), 1, shown)
                self.assertIn("[•] PR A: baseline", shown)

    def test_without_the_runs_tree_the_plan_is_drawn_whole(self) -> None:
        over = owners_run()
        for item in over["nodes"][1:]:
            item.update(state="done", status="accepted")
            item.pop("parked", None)
        over["dag_open"] = False
        app, _client = self.plan_app(RUN, over)  # the run is over and no turn runs: no tree
        self.assertEqual(rows_of(app), [])
        self.assertGreater(len(self.plan_rows(app)), 1)

    def test_ctrl_p_does_nothing_to_the_one_line_plan(self) -> None:
        app, _client = self.plan_app(RUN)
        before = self.plan_rows(app)
        app._on_input(Key(CHAR, "p", ctrl=True))
        self.assertEqual(self.plan_rows(app), before)
        self.assertFalse(app.plan_folded)


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


class TodoStampTests(unittest.TestCase):
    """`omh_todo set` and the `todo_list` projection stamp the run open in the session; an advance keeps it."""

    def test_a_list_declared_while_a_run_is_open_names_it_and_the_hud_projects_it(self) -> None:
        from _delegation_state import PARENT, homes
        from test_dag_tool import call, node, slots_table
        from omh.plugin_bundle.omh.runtime_reader import read_omh_todo
        from omh.plugin_bundle.omh.todo_store import read_todo_record
        from omh.plugin_bundle.omh.tools.todo_tool import omh_todo_handler

        items = [{"text": "Layer 1", "state": "active"}, {"text": "Layer 2", "state": "pending"}]
        advance = {"action": "advance", "item": 2, "item_text": "Layer 2", "state": "active"}
        with homes() as home:
            omh_todo_handler({"action": "set", "title": "before", "items": items}, session_id=PARENT)
            self.assertNotIn("dag_run", read_todo_record(home.omh, PARENT), "no run open: no stamp")
            slots_table(home)
            call(action="define", run="feat", nodes=[node("a")])
            omh_todo_handler(advance, session_id=PARENT)
            self.assertEqual(read_todo_record(home.omh, PARENT)["items"][1]["state"], "active", "the advance landed")
            self.assertNotIn("dag_run", read_todo_record(home.omh, PARENT), "an advance stamps no run")
            omh_todo_handler({"action": "set", "title": "run", "items": items}, session_id=PARENT)
            self.assertEqual(read_todo_record(home.omh, PARENT)["dag_run"], "feat")
            omh_todo_handler(advance, session_id=PARENT)
            self.assertEqual(read_todo_record(home.omh, PARENT)["items"][1]["state"], "active", "the advance landed")
            self.assertEqual(read_todo_record(home.omh, PARENT)["dag_run"], "feat", "an advance keeps it")
            self.assertEqual(read_omh_todo(session_ref=PARENT)["dag_run"], "feat")
            call(action="cancel", run="feat")
            omh_todo_handler({"action": "set", "title": "after", "items": items}, session_id=PARENT)
            self.assertNotIn("dag_run", read_todo_record(home.omh, PARENT), "a run that is over is no plan's")

    def test_the_todo_list_projection_stamps_the_open_run(self) -> None:
        from _delegation_state import PARENT, homes
        from test_dag_tool import call, node, slots_table
        from omh.plugin_bundle.omh.native_todo import project_native_todo
        from omh.plugin_bundle.omh.todo_store import read_todo_record

        todos = [{"id": "1", "content": "Layer 1", "status": "in_progress"}]
        with homes() as home:
            slots_table(home)
            call(action="define", run="feat", nodes=[node("a")])
            said = project_native_todo(tool_name="todo_list", args={"todos": todos},
                                       result=json.dumps({"todos": todos}), status="ok", session_ref=PARENT,
                                       omh_home=str(home.omh), hermes_home=str(home.hermes))
            self.assertEqual(said, "projected")
            self.assertEqual(read_todo_record(home.omh, PARENT)["dag_run"], "feat")

    def test_a_stamp_that_is_not_a_run_id_is_not_stored(self) -> None:
        from omh.plugin_bundle.omh.todo_store import build_todo_record

        items = [{"text": "one", "state": "pending"}]
        for value in ("", "Feat", "a/b", "x" * 40, 7, None):
            with self.subTest(value=value):
                self.assertNotIn("dag_run", build_todo_record("t", items, source="omh_todo", dag_run=value))
        self.assertEqual(build_todo_record("t", items, source="omh_todo", dag_run="feat-2")["dag_run"], "feat-2")


if __name__ == "__main__":
    unittest.main()

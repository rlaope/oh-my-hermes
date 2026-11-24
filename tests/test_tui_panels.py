"""The OMH TUI's HUD panels: the poller's session and cadence rules, and the rows under a budget.

Plan payloads come from the real `read_omh_hud` over a temp OMH home seeded
through the todo store. Agent rows and the subagent graph are the reader's
documented row shapes laid onto that payload, since seeding a Hermes state.db
is the reader's own tests' job. One case compares the rows with the ones the
Hermes status widget drew for the same payloads, recorded before the widget
was deleted, so the port keeps the look the widget's tests pinned.
"""

from __future__ import annotations

from collections.abc import Callable
import copy
from datetime import datetime, timezone
import json
import re
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
import unicodedata
import unittest

from _tui_lines import line_text, lines_text
from omh.plugin_bundle.omh.runtime_reader import read_omh_hud
from omh.plugin_bundle.omh.todo_store import build_todo_record, write_todo
from omh.tui.panels import (
    HUD_POLL_MAX_SECONDS,
    HUD_POLL_MIN_SECONDS,
    HudPoller,
    HudSnapshot,
    agent_view_count,
    agent_view_keep,
    graph_is_dag,
    panel_lines,
    plan_state,
    hud_chips,
    read_output_tokens,
)
from omh.tui.theme import DEFAULT_THEME
from omh.tui.width import line_width

THEME = DEFAULT_THEME


def hud_payload(items: list[dict] | None = None, *, title: str = "Plan") -> dict:
    """A real `read_omh_hud` payload over a temp OMH home holding `items` as its plan."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        omh_home = root / "omh"
        hermes_home = root / "hermes"
        omh_home.mkdir()
        hermes_home.mkdir()
        if items:
            write_todo(omh_home, build_todo_record(title, items, source="test"))
        return read_omh_hud(omh_home, hermes_home, package_version="3.0.2")


def phased_plan(count: int, *, phases: int, active: int) -> list[dict]:
    return [
        {
            "text": f"Task number {index}",
            "state": "active" if index == active else "done" if index < active else "pending",
            "phase": f"Phase {min(index, phases - 1)}",
        }
        for index in range(count)
    ]


def agent_row(index: int, **fields) -> dict:
    row = {
        "state": "running",
        "task_id": f"worker{index}",
        "action": f"Worker {index} action",
        "model": "anthropic/claude-opus-5-5",
        "effort": "high",
        "category": "architect",
        "elapsed_seconds": 30 + index,
        "tokens": 1200 * (index + 1),
    }
    row.update(fields)
    return row


def with_agents(payload: dict, rows: list[dict], *, hidden: int = 0) -> dict:
    payload = copy.deepcopy(payload)
    payload["active"] = True
    payload["subagents"].update(
        rows=rows,
        hidden_rows=hidden,
        active=len(rows) + hidden,
        running=sum(1 for row in rows if row.get("state", "running") == "running"),
    )
    return payload


def with_delegation(payload: dict, lanes: list[dict], *, source: str = "native", edges: list | None = None) -> dict:
    """A `delegation_graph/v1` of a root and ``lanes`` laid onto ``payload``; dispatch edges unless given."""
    payload = copy.deepcopy(payload)
    nodes = [{"id": "root", "kind": "root", "title": "main", "model": "claude-opus-5-5", "effort": "high",
              "state": "root", "status": "", "order": 0, "group": ""}]
    for index, lane in enumerate(lanes, start=1):
        nodes.append({"id": f"n{index}", "kind": "lane", "title": f"Lane {index}", "category": "quick",
                      "model": "glm-5.3-flash", "effort": "low", "state": "running", "status": "running",
                      "elapsed_seconds": 60 + index, "order": index, "group": "", "waits_on": 0, **lane})
    payload["delegation_graph"] = {
        "schema_version": "delegation_graph/v1", "status": "active", "scope": "session", "source": source,
        "name": "delegation", "hidden_nodes": 0,
        "nodes": nodes,
        "edges": edges if edges is not None else [
            {"from": "root", "to": node["id"], "kind": "dispatch"} for node in nodes[1:]
        ],
    }
    return payload


def with_graph(payload: dict, node_count: int) -> dict:
    payload = copy.deepcopy(payload)
    ids = [f"unit{index}" for index in range(node_count)]
    payload["graph"] = {
        "status": "active",
        "scope": "global",
        "frontier": ids[1:2],
        "edges": [[ids[0], other] for other in ids[1:]],
        "edge_count": max(0, node_count - 1),
        "hidden_nodes": 0,
        "nodes": [
            {
                "node_id": unit,
                "state": "completed" if index == 0 else "prepared_not_observed",
                "blocked_by": [],
                "in_frontier": index == 1,
            }
            for index, unit in enumerate(ids)
        ],
    }
    return payload


def item_rows(rows: list[str]) -> list[str]:
    return [row for row in rows if any(mark in row for mark in ("[•]", "[✓]", "[ ]"))]


def folded(rows: list[str]) -> tuple[int, int]:
    earlier = later = 0
    for row in rows:
        if row.startswith("... ("):
            count = int(row.split("(")[1].split(" ")[0])
            if "earlier" in row:
                earlier = count
            elif "later" in row:
                later = count
        elif re.fullmatch(r"✓ \d+ done", row):  # done items above the window fold into one row
            earlier = int(row.split()[1])
    return earlier, later


class PanelEmptyAndErrorTests(unittest.TestCase):
    def test_a_payload_with_nothing_to_show_draws_no_rows(self) -> None:
        payload = hud_payload()
        self.assertEqual(payload["todo"]["status"], "absent")
        for budget in (0, 1, 5, 40):
            with self.subTest(budget=budget):
                self.assertEqual(panel_lines(payload, 80, budget, THEME, 0.0), [])
        self.assertEqual(panel_lines(None, 80, 10, THEME, 0.0), [])
        # Anything the reader did not vouch for as metadata-only is not drawn.
        foreign = dict(payload, privacy="raw")
        self.assertEqual(panel_lines(with_agents(foreign, [agent_row(0)]), 80, 10, THEME, 0.0), [])

    def test_a_reader_failure_is_one_muted_notice(self) -> None:
        lines = panel_lines({"error": "OperationalError"}, 80, 5, THEME, 0.0)
        self.assertEqual(lines_text(lines), ["⚚ OMH HUD unavailable: OperationalError"])
        self.assertEqual(lines[0][0].style, THEME.muted)
        self.assertEqual(panel_lines({"error": "OperationalError"}, 80, 0, THEME, 0.0), [])


class PlanBlockTests(unittest.TestCase):
    def test_a_phased_plan_keeps_the_active_item_and_accounts_for_every_item(self) -> None:
        payload = hud_payload(phased_plan(12, phases=8, active=5), title="Release")
        roomy = lines_text(panel_lines(payload, 120, 40, THEME, 0.0))
        self.assertTrue(roomy[0].startswith("[Plan] Release │ 5/12 · 8 phases"), roomy[0])
        # The widget's cap: eight items, anchored just before the first open one.
        self.assertEqual(len(item_rows(roomy)), 8)
        self.assertEqual(folded(roomy), (4, 0))
        for budget in range(3, 16):
            with self.subTest(budget=budget):
                rows = lines_text(panel_lines(payload, 120, budget, THEME, 0.0))
                self.assertLessEqual(len(rows), budget)
                self.assertTrue(rows[0].startswith("[Plan] Release"))
                if len(rows) > 1:
                    self.assertIn("[•] Task number 5", "\n".join(rows))
                    earlier, later = folded(rows)
                    self.assertEqual(earlier + len(item_rows(rows)) + later, 12, rows)
                    # An item never loses the phase header it belongs under.
                    index = next(i for i, row in enumerate(rows) if "[•]" in row)
                    self.assertEqual(rows[index - 1], "Phase 5")

    def test_too_small_for_one_item_leaves_the_header_alone(self) -> None:
        payload = hud_payload(phased_plan(12, phases=8, active=5), title="Release")
        # One item needs its phase header and both folds: four rows under the header.
        for budget in (1, 2, 3, 4):
            with self.subTest(budget=budget):
                rows = lines_text(panel_lines(payload, 120, budget, THEME, 0.0))
                self.assertEqual(len(rows), 1, rows)
                self.assertTrue(rows[0].startswith("[Plan] Release │ 5/12"))
        self.assertEqual(len(panel_lines(payload, 120, 5, THEME, 0.0)), 5)

    def test_a_finished_plan_is_one_receipt_line_naming_its_skips(self) -> None:
        items = [
            {"text": "Research", "state": "done"},
            {"text": "Build", "state": "done"},
            {"text": "Polish", "state": "done", "blocked_reason": "not needed"},
        ]
        payload = hud_payload(items, title="Done plan")
        self.assertEqual(payload["todo"]["status"], "all_done")
        rows = lines_text(panel_lines(payload, 80, 10, THEME, 0.0))
        self.assertEqual(rows, ["[Plan] Done plan │ ✓ 2/3 (1 skipped)"])

    def test_the_parallel_shot_badge_rides_the_plan_header(self) -> None:
        payload = hud_payload(phased_plan(3, phases=1, active=1))
        live = copy.deepcopy(payload)
        live["parallel_shot"] = {"status": "observed", "open_count": 3, "peak_open_count": 5}
        header = lines_text(panel_lines(live, 120, 10, THEME, 0.0))[0]
        self.assertIn(" · parallel shot ×3", header)
        # Once every member closed: the measured peak, dimmed, with its age.
        history = copy.deepcopy(payload)
        history["parallel_shot"] = {
            "status": "observed",
            "open_count": 0,
            "peak_open_count": 2,
            "observed_at": "2026-10-13T00:00:00Z",
        }
        now = datetime(2026, 10, 13, 0, 0, 5, tzinfo=timezone.utc).timestamp()
        lines = panel_lines(history, 120, 10, THEME, now)
        self.assertIn(" · parallel shot ×2 (5s ago)", line_text(lines[0]))
        badge = next(span for span in lines[0] if "parallel shot" in span.text)
        self.assertEqual(badge.style, THEME.muted)

    def test_calls_that_never_overlapped_carry_no_parallel_shot_badge(self) -> None:
        # The plugin groups calls started within 1.5 s and measures how many were open at once
        # (`tool_bursts._latest_shot_from_entries`): a chain run one after another inside that window peaks at 1.
        payload = hud_payload(phased_plan(3, phases=1, active=1))
        now = datetime(2026, 10, 13, 0, 0, 3, tzinfo=timezone.utc).timestamp()

        def header(open_count: int, peak_open_count: int) -> str:
            shown = copy.deepcopy(payload)
            shown["parallel_shot"] = {
                "status": "observed",
                "open_count": open_count,
                "peak_open_count": peak_open_count,
                "observed_at": "2026-10-13T00:00:00Z",
            }
            return lines_text(panel_lines(shown, 120, 10, THEME, now))[0]

        for open_count, peak in ((0, 1), (1, 1), (0, 0), (1, 0)):
            with self.subTest(open_count=open_count, peak_open_count=peak):
                self.assertNotIn("parallel shot", header(open_count, peak))
        self.assertIn(" · parallel shot ×2 (3s ago)", header(0, 2))
        self.assertIn(" · parallel shot ×2 (3s ago)", header(1, 2))  # one call of a real overlap still running
        self.assertIn(" · parallel shot ×2", header(2, 2))
        self.assertNotIn("ago", header(2, 2))

    def test_an_active_item_moves_only_while_work_is_live(self) -> None:
        payload = hud_payload(phased_plan(3, phases=1, active=1))
        # This install never saw post_tool_call: liveness is unanswerable, so
        # the item keeps the always-live shape -- green, with the colour wave.
        live_row = next(line for line in panel_lines(payload, 120, 10, THEME, 0.0) if "[•]" in line_text(line))
        self.assertGreater(len(live_row), 2, "the wave splits the item text into spans")
        self.assertIn(THEME.ok.fg, {span.style.fg for span in live_row})
        stalled = copy.deepcopy(payload)
        stalled["activity"].update(post_tool_call_observed=True, live=False)
        stalled["todo"]["stall"]["status"] = "unchanged"
        stalled["todo"]["updated_age_seconds"] = 1200
        lines = panel_lines(stalled, 120, 10, THEME, 0.0)
        row = next(line for line in lines if "[•]" in line_text(line))
        self.assertEqual(row[0].style.fg, THEME.warn.fg)
        self.assertTrue(line_text(row).endswith("(unchanged 20m 0s)"), line_text(row))
        self.assertNotIn(" .", line_text(lines[0]), "no walking ellipsis on a plan that is not moving")

    def test_a_moving_plan_header_ends_with_its_count_at_every_frame(self) -> None:
        # The widget walked an ellipsis after it (` .`, ` ..`, ` ...`); a single dot read as a stray period (D7).
        payload = hud_payload(phased_plan(3, phases=1, active=1))
        for now in (0.0, 0.09, 0.3, 0.6, 0.9, 1.2):
            with self.subTest(now=now):
                header = line_text(panel_lines(payload, 120, 10, THEME, now)[0])
                self.assertEqual(header, "[Plan] Plan │ 1/3")

    def test_the_plan_state_says_open_done_or_nothing(self) -> None:
        self.assertEqual(plan_state(hud_payload(phased_plan(3, phases=1, active=1))), "open")
        self.assertEqual(plan_state(hud_payload([{"text": "a", "state": "done"}])), "done")
        self.assertEqual([plan_state(hud_payload([])), plan_state(None), plan_state({"error": "x"})], ["", "", ""])

    def test_without_show_plan_the_plan_block_is_left_out_and_the_agents_stay(self) -> None:
        payload = with_agents(hud_payload(phased_plan(3, phases=1, active=1)), [agent_row(0)])
        shown = lines_text(panel_lines(payload, 120, 20, THEME, 0.0))
        left = lines_text(panel_lines(payload, 120, 20, THEME, 0.0, show_plan=False))
        self.assertTrue(any(row.startswith("[Plan]") for row in shown))
        self.assertFalse([row for row in left if row.startswith("[Plan]") or "Task number" in row])
        self.assertEqual(left, shown[: len(left)])  # the agents block, as it was

    def test_hangul_titles_and_items_cut_on_whole_syllables(self) -> None:
        title = "패널 계획을 한국어로 길게 적은 제목입니다"
        items = [
            {
                "text": "첫 번째 작업은 화면 아래쪽 패널을 그리는 일입니다",
                "state": "active",
                "phase": "구현 단계",
            },
            {"text": "두 번째 작업", "state": "pending", "phase": "구현 단계"},
        ]
        # macOS hands Hangul over decomposed; the panel must still cut by syllable.
        payload = hud_payload(
            [dict(item, text=unicodedata.normalize("NFD", item["text"])) for item in items],
            title=unicodedata.normalize("NFD", title),
        )
        for width in (21, 30, 31, 45):
            with self.subTest(width=width):
                lines = panel_lines(payload, width, 10, THEME, 0.0)
                self.assertTrue(lines)
                for line in lines:
                    self.assertLessEqual(line_width(line), width, line_text(line))
                    for ch in line_text(line):
                        self.assertFalse(0x1100 <= ord(ch) <= 0x11FF, f"loose jamo in {line_text(line)!r}")
                self.assertTrue(line_text(lines[0]).endswith("…"), line_text(lines[0]))
                self.assertIn("패널", line_text(lines[0]))


class AgentsBlockTests(unittest.TestCase):
    def test_rows_carry_the_route_identity_and_a_spinner_from_now(self) -> None:
        payload = with_agents(
            hud_payload(),
            [
                agent_row(0),
                agent_row(1, state="done", category="critic", model="gpt-6.1-sol", effort="xhigh", route_origin="fallback"),
                agent_row(
                    2, state="queued", lane_backend="kanban", assignee="mbot", native_status="ready", model="kimi-k3", effort=""
                ),
                agent_row(3, dispatch_lane="maestro", executor_profile="claude_code", model="claude-fable-5-1"),
                agent_row(4, category="inherit", model="glm-5.3", effort=""),
            ],
        )
        rows = lines_text(panel_lines(payload, 160, 20, THEME, 0.0))
        # The reader marks OMH-side rows global, so the header carries the one marker.
        self.assertTrue(rows[0].startswith("● main │ [global] 5 agents · 3 running"), rows[0])
        body = "\n".join(rows)
        self.assertIn("category:architect(claude-opus-5-5:high)", body)
        self.assertIn("category:critic(gpt-6.1-sol:xhigh fallback)", body)
        self.assertIn("kanban/mbot(kimi-k3)", body)
        self.assertIn("(claude/maestro claude-fable-5-1)", body)
        self.assertIn("inherit(glm-5.3)", body)
        self.assertNotIn("anthropic/", body, "the route names the model, not who serves it")
        # Tokens sit in one column down the list.
        token_columns = {row.index("tokens") for row in rows[1:] if "tokens" in row}
        self.assertEqual(len(token_columns), 1, rows)
        # A running row's marker turns with the clock; a settled row's does not.
        later = lines_text(panel_lines(payload, 160, 20, THEME, 0.09))
        self.assertNotEqual(rows[1][0], later[1][0])
        self.assertEqual(rows[2][0], "✓")
        self.assertEqual(later[2][0], "✓")

    def test_a_running_rows_elapsed_ticks_between_polls(self) -> None:
        payload = with_agents(hud_payload(), [agent_row(0, elapsed_seconds=42)])
        fresh = lines_text(panel_lines(payload, 120, 5, THEME, 100.0, received_at=100.0))[1]
        later = lines_text(panel_lines(payload, 120, 5, THEME, 110.0, received_at=100.0))[1]
        self.assertIn("42s", fresh)
        self.assertIn("52s", later)

    def test_agents_over_budget_disclose_the_rest_on_a_more_row(self) -> None:
        rows = [agent_row(index) for index in range(8)]
        payload = with_agents(hud_payload(), rows, hidden=2)
        roomy = lines_text(panel_lines(payload, 120, 40, THEME, 0.0))
        # Five by default, but never fewer than are running: all eight run.
        self.assertEqual(len(roomy), 1 + 8 + 1)
        self.assertEqual(roomy[-1], "  +2 more")
        for budget in range(3, 10):
            with self.subTest(budget=budget):
                lines = lines_text(panel_lines(payload, 120, budget, THEME, 0.0))
                self.assertEqual(len(lines), budget)
                shown = len(lines) - 2
                self.assertEqual(lines[-1], f"  +{8 - shown + 2} more")
        # Too small for a row and its disclosure: the header's counts say it.
        self.assertEqual(lines_text(panel_lines(payload, 120, 2, THEME, 0.0)), [roomy[0]])

    def test_the_delegation_block_is_the_tree_and_keeps_its_header_past_the_plan_items(self) -> None:
        plan = hud_payload(phased_plan(3, phases=1, active=1))
        maestro = [agent_row(index, dispatch_lane="maestro", executor_profile="codex") for index in range(3)]
        payload = with_delegation(with_agents(plan, maestro), [{}, {}, {}])
        full = lines_text(panel_lines(payload, 120, 60, THEME, 0.0))
        self.assertFalse([row for row in full if "┌" in row], "boxes are /dag's, never the panel's")
        self.assertEqual([row for row in full if row.startswith(("  ├─", "  └─"))][-1][:16], "  └─ ● Lane 3   ")
        previous_dag = None
        for budget in range(len(full), -1, -1):
            with self.subTest(budget=budget):
                rows = lines_text(panel_lines(payload, 120, budget, THEME, 0.0))
                self.assertLessEqual(len(rows), budget)
                top = next((at for at, row in enumerate(rows) if row.startswith("  DAG ·")), None)
                end = next((at for at, row in enumerate(rows) if row.startswith("[Plan]")), len(rows))
                dag = rows[top:end] if top is not None else []
                agents = [row for row in rows if "maestro" in row]
                items = item_rows(rows)
                if previous_dag is not None:
                    self.assertLessEqual(len(dag), previous_dag, "the block never grows as the budget shrinks")
                previous_dag = len(dag)
                if agents:
                    self.assertTrue(any(row.startswith("  ├─") or row.startswith("  └─") for row in dag),
                                    f"agent rows stay only while the block is a full tree: {rows}")
                if len(dag) < 4 and dag:
                    self.assertEqual(agents, [], f"agent rows go before the tree shrinks to its last rows: {rows}")
                if agents:
                    self.assertEqual(len(items), 3, rows)
                if budget >= 1:
                    self.assertTrue(any(row.startswith("[Plan]") for row in rows), "the plan header is the last to go")
                if budget >= 2:
                    self.assertTrue(any(row.startswith("  DAG ·") for row in rows), "then the block's own header")

    def test_a_stuck_fanout_unit_is_never_drawn_running(self) -> None:
        payload = with_delegation(
            hud_payload(), [{"state": "stuck", "status": "stuck: same error", "elapsed_seconds": 400}], source="fanout"
        )
        lines = panel_lines(payload, 120, 30, THEME, 0.0)
        rows = lines_text(lines)
        stuck = next(index for index, row in enumerate(rows) if "! Lane 1" in row)
        self.assertIn("stuck 6m 40s: same error", rows[stuck])
        glyph = next(span for span in lines[stuck] if span.text == "!")
        self.assertEqual(glyph.style, THEME.warn)
        self.assertNotIn("running", rows[stuck])

    def test_native_lanes_are_drawn_once_and_maestro_rows_stay(self) -> None:
        native = agent_row(0, role="hermes-native")
        maestro = agent_row(1, dispatch_lane="maestro", executor_profile="codex")
        payload = with_delegation(with_agents(hud_payload(), [native, maestro]), [{"session_tail": "worker0"}])
        rows = lines_text(panel_lines(payload, 120, 40, THEME, 0.0))
        self.assertFalse(any("worker0" in row for row in rows), "the native row is in the delegation block")
        self.assertTrue(any("worker1" in row for row in rows), "a Maestro row is not a native lane")
        fanout = with_delegation(with_agents(hud_payload(), [native, maestro]), [{"session_tail": "worker0"}],
                                 source="fanout")
        rows = lines_text(panel_lines(fanout, 120, 40, THEME, 0.0))
        self.assertTrue(any("worker0" in row for row in rows), "a fanout graph does not stand in for native rows")

    def test_a_native_row_the_graph_does_not_draw_stays(self) -> None:
        natives = [agent_row(index, role="hermes-native") for index in range(3)]
        payload = with_delegation(with_agents(hud_payload(), natives), [{"session_tail": "worker1"}])
        rows = lines_text(panel_lines(payload, 120, 40, THEME, 0.0))
        self.assertEqual([index for index in range(3) if any(f"worker{index}" in row for row in rows)], [0, 2],
                         "only the lane the graph draws leaves the agents block")
        team_only = with_delegation(with_agents(hud_payload(), natives), [{}])  # no ledger lane, no session_tail
        rows = lines_text(panel_lines(team_only, 120, 40, THEME, 0.0))
        self.assertTrue(all(any(f"worker{index}" in row for row in rows) for index in range(3)))

    def test_one_count_line_while_the_graph_holds_the_native_lanes(self) -> None:
        natives = [agent_row(index, role="hermes-native", state=state)
                   for index, state in enumerate(("running", "failed", "done"))]
        lanes = [{"session_tail": f"worker{index}", "state": state, "status": state}
                 for index, state in enumerate(("running", "failed", "done"))]
        rows = lines_text(panel_lines(with_delegation(with_agents(hud_payload(), natives), lanes), 120, 40, THEME, 0.0))
        header = next(row for row in rows if row.startswith("● main │")).replace("[global] ", "")
        self.assertTrue(header.startswith("● main │ lanes in the graph below"), header)
        for word in ("running", "blocked", "failed", "done", "agent"):
            self.assertNotIn(f" {word}", header.split("•")[0].replace("lanes in the graph below", ""), header)
        counts = [row for row in rows if "running" in row and ("·" in row) and not row.lstrip().startswith(("│", "┌"))]
        self.assertEqual(len(counts), 1, f"one line counts the lanes: {counts}")
        self.assertIn("DAG · delegation", counts[0])

    def test_the_agents_header_counts_only_the_rows_it_still_lists(self) -> None:
        natives = [agent_row(index, role="hermes-native") for index in range(3)]
        payload = with_delegation(with_agents(hud_payload(), natives), [{"session_tail": "worker1"}])
        header = next(row for row in lines_text(panel_lines(payload, 120, 40, THEME, 0.0)) if row.startswith("● main │"))
        self.assertTrue(header.replace("[global] ", "").startswith("● main │ 2 other agents · 2 running"), header)
        plain = with_agents(hud_payload(), natives)
        header = next(row for row in lines_text(panel_lines(plain, 120, 40, THEME, 0.0)) if row.startswith("● main │"))
        self.assertTrue(header.replace("[global] ", "").startswith("● main │ 3 agents · 3 running"),
                        "with no graph the header is as it was")

    def test_the_delegation_block_is_drawn_while_the_roster_shows_the_agents(self) -> None:
        payload = with_delegation(with_agents(hud_payload(), [agent_row(0)]), [{}, {}])
        rows = lines_text(panel_lines(payload, 120, 40, THEME, 0.0, show_agents=False))
        self.assertFalse(any(row.startswith("● main") for row in rows))
        self.assertTrue(any(row.startswith("  DAG · delegation · 2 nodes · 0 edges") for row in rows), rows)  # lanes, not main

    def test_the_old_fanout_graph_field_is_no_longer_drawn(self) -> None:
        payload = with_graph(with_agents(hud_payload(), [agent_row(0)]), 3)
        rows = lines_text(panel_lines(payload, 120, 40, THEME, 0.0))
        self.assertFalse(any("DAG ·" in row or "[R]" in row for row in rows), rows)


class AgentViewPartTests(unittest.TestCase):
    """The agents and delegation blocks as the agent view under the info line draws them."""

    def test_running_rows_are_kept_before_done_ones_and_a_cut_of_done_rows_says_so(self) -> None:
        rows = [agent_row(0, state="done"), agent_row(1), agent_row(2, state="done"), agent_row(3, state="queued"),
                agent_row(4)]
        payload = with_agents(hud_payload(), rows)
        kept = lines_text(panel_lines(payload, 120, 4, THEME, 0.0, show_plan=False))
        self.assertEqual([row.split()[2] for row in kept[1:3]], ["worker1", "worker4"], kept)
        self.assertEqual(kept[3], "  +3 more")
        three = lines_text(panel_lines(payload, 120, 5, THEME, 0.0, show_plan=False))
        self.assertEqual([row.split()[2] for row in three[1:4]], ["worker1", "worker3", "worker4"], "in their order")
        self.assertEqual(three[4], "  +2 done")
        hidden = lines_text(panel_lines(with_agents(hud_payload(), rows, hidden=1), 120, 5, THEME, 0.0,
                                        show_plan=False))
        self.assertEqual(hidden[4], "  +3 more", "a row the reader did not list may be anything")

    def test_a_finished_run_counts_at_its_one_line_so_the_agents_block_keeps_its_running_rows(self) -> None:
        # Counted at its tree's full height (seven rows), the settled run left the block only its header at six rows.
        rows = [agent_row(0), agent_row(1), *(agent_row(index, state="done") for index in range(2, 6))]
        payload = with_delegation(with_agents(hud_payload(), rows), [{"state": "done", "status": "done"}] * 5)
        kept = lines_text(panel_lines(payload, 100, 6, THEME, 0.0, show_plan=False))
        self.assertEqual(len(kept), 6, kept)
        self.assertEqual([row.split()[2] for row in kept[1:3]], ["worker0", "worker1"], kept)
        self.assertEqual(kept[-2:], ["  +3 done", "  DAG · delegation · done 5/5"])

    def test_the_inset_shifts_the_agents_block_and_the_tree_keeps_its_own(self) -> None:
        payload = with_delegation(with_agents(hud_payload(), [agent_row(0, dispatch_lane="maestro")]), [{}])
        flush = lines_text(panel_lines(payload, 80, 20, THEME, 0.0, show_plan=False))
        inset = lines_text(panel_lines(payload, 80, 20, THEME, 0.0, show_plan=False, agents_inset=2))
        self.assertTrue(inset[0].startswith("  ● main │ "), inset)
        self.assertTrue(inset[1].startswith("  ⠋ "), inset)
        self.assertEqual([row for row in inset if row.startswith("  DAG ·")], [row for row in flush
                                                                             if row.startswith("  DAG ·")])
        self.assertTrue(all(line_width(line) <= 80 for line in panel_lines(payload, 80, 20, THEME, 0.0,
                                                                            show_plan=False, agents_inset=2)))

    def test_with_no_row_of_its_own_the_agents_block_draws_no_header_over_the_tree(self) -> None:
        rows = lines_text(panel_lines(with_delegation(hud_payload(), [{}, {}]), 100, 20, THEME, 0.0))
        self.assertTrue(rows[0].startswith("  DAG · delegation"), rows)
        self.assertFalse([row for row in rows if row.startswith("● main")])

    def test_a_dag_run_is_a_depends_on_edge_or_a_lane_dispatching_a_lane(self) -> None:
        flat = with_delegation(hud_payload(), [{}, {}])
        self.assertFalse(graph_is_dag(flat))
        depends = with_delegation(hud_payload(), [{}, {}], edges=[
            {"from": "root", "to": "n1", "kind": "dispatch"}, {"from": "n1", "to": "n2", "kind": "depends_on"}])
        self.assertTrue(graph_is_dag(depends))
        nested = with_delegation(hud_payload(), [{}, {}], edges=[
            {"from": "root", "to": "n1", "kind": "dispatch"}, {"from": "n1", "to": "n2", "kind": "dispatch"}])
        self.assertTrue(graph_is_dag(nested))
        for payload in (hud_payload(), None, {"error": "x"}, {"delegation_graph": {"status": "inactive"}}):
            self.assertFalse(graph_is_dag(payload))

    def test_a_settled_lane_is_what_the_graph_builder_calls_settled(self) -> None:
        from omh.plugin_bundle.omh.delegation_graph import SETTLED_STATES
        from omh.tui.panels import SETTLED_NODE_STATES

        self.assertEqual(SETTLED_NODE_STATES, SETTLED_STATES)

    def test_keep_is_the_rows_every_running_agent_needs_and_count_is_every_agent(self) -> None:
        rows = [agent_row(0), agent_row(1, state="done"), agent_row(2)]
        payload = with_agents(hud_payload(), rows, hidden=2)
        self.assertEqual(agent_view_keep(payload, 100), 1 + 2 + 1)  # header, two running, the `+N` row
        self.assertEqual(agent_view_count(payload), 5)
        self.assertEqual(agent_view_keep(with_agents(hud_payload(), [agent_row(1, state="done")]), 100), 0)
        twelve = with_delegation(hud_payload(), [{} for _ in range(12)])
        keep = agent_view_keep(twelve, 100)
        self.assertEqual(keep, 2 + 12, "the tree's header, main and the twelve running lanes")
        tree = lines_text(panel_lines(twelve, 100, keep, THEME, 0.0))
        self.assertFalse([row for row in tree if "more nodes" in row])
        self.assertTrue([row for row in lines_text(panel_lines(twelve, 100, keep - 1, THEME, 0.0)) if "more nodes" in row])
        self.assertEqual(agent_view_count(twelve), 12)
        self.assertEqual(agent_view_count(twelve, show_graph=False), 0)
        settled = with_delegation(hud_payload(), [{"state": "done", "status": "done"}] * 3)
        self.assertEqual(agent_view_keep(settled, 100), 0)
        self.assertEqual((agent_view_keep({"error": "x"}, 100), agent_view_count(None)), (0, 0))


class BudgetInvariantTests(unittest.TestCase):
    def test_no_budget_and_no_width_is_ever_exceeded(self) -> None:
        plan = hud_payload(phased_plan(12, phases=8, active=5), title="한국어 제목과 English title together")
        busy = with_graph(with_agents(plan, [agent_row(index) for index in range(7)], hidden=3), 5)
        busy["parallel_shot"] = {"status": "observed", "open_count": 4}
        payloads = {
            "plan": plan,
            "agents": with_agents(hud_payload(), [agent_row(index) for index in range(7)], hidden=1),
            "busy": busy,
            "error": {"error": "OperationalError"},
        }
        for name, payload in payloads.items():
            for width in (30, 80, 140):
                for budget in range(13):
                    with self.subTest(payload=name, width=width, budget=budget):
                        lines = panel_lines(payload, width, budget, THEME, 1234.5, received_at=1230.0)
                        self.assertLessEqual(len(lines), budget)
                        if budget:
                            self.assertTrue(lines)
                        for line in lines:
                            self.assertLessEqual(line_width(line), width, line_text(line))
                            self.assertTrue(all(span.text for span in line))


class HudChipsTests(unittest.TestCase):
    """The HUD's session-wide chips for the info line's right side: no `⚚ OMH` brand, no yolo chip."""

    def texts(self, *args: object, **options: object) -> list[str]:
        return [line_text(chip) for chip in hud_chips(*args, **options)]  # type: ignore[arg-type]

    def test_session_wide_chips_with_no_brand(self) -> None:
        payload = hud_payload()
        self.assertEqual(self.texts(payload, THEME), [])
        payload["repeat"] = {"status": "observed", "consecutive": 4, "period": 2, "intercepted": 1, "stage": "blocking"}
        payload["activity"].update(
            live=True, post_tool_call_observed=True, open_call_count=2, oldest_open_elapsed_seconds=12
        )
        payload["yolo"] = {"status": "observed", "enabled": True}
        chips = hud_chips(payload, THEME)
        self.assertEqual([line_text(chip) for chip in chips], ["repeat x4 cycle-of-2 blocked", "2 tools · 12s"])  # no yolo
        self.assertEqual(chips[0][0].style.fg, THEME.warn.fg)

    def test_the_in_flight_chip_drops_its_clock_while_a_question_waits_and_goes_when_no_turn_runs(self) -> None:
        payload = hud_payload()
        payload["repeat"] = {"status": "observed", "consecutive": 4, "period": 2, "intercepted": 1, "stage": "blocking"}
        payload["activity"].update(live=True, post_tool_call_observed=True, open_call_count=2, oldest_open_elapsed_seconds=12)
        self.assertEqual(self.texts(payload, THEME, question_waits=True), ["repeat x4 cycle-of-2 blocked", "2 tools"])
        self.assertEqual(self.texts(payload, THEME, turn_runs=False), ["repeat x4 cycle-of-2 blocked"])

    def test_liveness_is_not_claimed_where_it_cannot_be_read(self) -> None:
        payload = hud_payload()
        payload["activity"].update(live=True, post_tool_call_observed=False, open_call_count=2)
        self.assertNotIn("2 tools · 0s", self.texts(payload, THEME))
        self.assertEqual(self.texts(payload, THEME), [])

    def test_without_a_payload_there_are_no_chips(self) -> None:
        self.assertEqual(hud_chips(None, THEME), ())
        self.assertEqual(hud_chips({"error": "OSError"}, THEME), ())


class FakeReader:
    """Stands in for `read_omh_hud`: records each call and returns what `respond` says."""

    def __init__(self, respond: Callable[[str], dict] | None = None) -> None:
        self.calls: list[tuple[tuple, dict]] = []
        self.respond = respond or (lambda session: {"privacy": "metadata_only", "session": session})
        self.called = threading.Event()

    def __call__(self, *args, **kwargs) -> dict:
        self.calls.append((args, kwargs))
        self.called.set()
        return self.respond(kwargs["session_ref"])


class HudReaderImportTests(unittest.TestCase):
    def test_the_tui_imports_the_hud_reader_only_when_the_poller_first_reads(self) -> None:
        # A fresh interpreter: this process imported runtime_reader long ago.
        probe = (
            "import sys, tempfile\n"
            "import omh.tui.app\n"
            "from omh.tui.panels import HudPoller\n"
            "name = 'omh.plugin_bundle.omh.runtime_reader'\n"
            "print('after import:', name in sys.modules)\n"
            "with tempfile.TemporaryDirectory() as omh, tempfile.TemporaryDirectory() as hermes:\n"
            "    poller = HudPoller(omh, hermes)\n"
            "    poller.set_session('20261014_000000_aaaaaa')\n"
            "    poller.poll_once()\n"
            "print('after a read:', name in sys.modules)\n"
        )
        done = subprocess.run([sys.executable, "-P", "-c", probe], capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.splitlines(), ["after import: False", "after a read: True"])


class HudPollerTests(unittest.TestCase):
    def poller(self, reader: FakeReader) -> HudPoller:
        return HudPoller("/omh", "/hermes", package_version="9.9.9", reader=reader, clock=lambda: 50.0)

    def test_nothing_is_read_or_delivered_before_a_session(self) -> None:
        reader = FakeReader()
        poller = self.poller(reader)
        self.assertEqual(poller.poll_once(), HUD_POLL_MAX_SECONDS)
        self.assertEqual(reader.calls, [])
        self.assertIsNone(poller.take())

    def test_a_session_switch_empties_the_panel_and_reads_the_new_session(self) -> None:
        reader = FakeReader()
        poller = self.poller(reader)
        poller.set_session("stored-1")
        self.assertEqual(poller.take(), HudSnapshot("stored-1", None, 50.0))
        poller.poll_once()
        args, kwargs = reader.calls[-1]
        self.assertEqual(args, ("/omh", "/hermes"))
        self.assertEqual(
            kwargs,
            {"session_ref": "stored-1", "session_scoped": True, "tui_identity_expected": True, "package_version": "9.9.9"},
        )
        self.assertEqual(poller.take().payload["session"], "stored-1")
        self.assertIsNone(poller.take(), "a slot is taken once")
        # Compression rotates the stored id: the old plan must not outlive it.
        poller.set_session("stored-2")
        self.assertEqual(poller.take(), HudSnapshot("stored-2", None, 50.0))
        poller.poll_once()
        self.assertEqual(reader.calls[-1][1]["session_ref"], "stored-2")
        self.assertEqual(poller.take().session_id, "stored-2")
        poller.set_session("stored-2")
        self.assertIsNone(poller.take(), "naming the same session again changes nothing")

    def test_a_read_that_finishes_after_a_switch_is_discarded(self) -> None:
        holder: dict[str, HudPoller] = {}

        def respond(session: str) -> dict:
            if session == "stored-1":
                holder["poller"].set_session("stored-2")
            return {"privacy": "metadata_only", "session": session}

        poller = holder["poller"] = self.poller(FakeReader(respond))
        poller.set_session("stored-1")
        poller.take()
        self.assertEqual(poller.poll_once(), HUD_POLL_MIN_SECONDS)
        self.assertEqual(poller.take(), HudSnapshot("stored-2", None, 50.0))

    def test_unchanged_payloads_back_off_to_eight_seconds(self) -> None:
        payloads = [{"privacy": "metadata_only", "rows": [{"state": "running", "elapsed_seconds": 1}]}]
        poller = self.poller(FakeReader(lambda session: copy.deepcopy(payloads[-1])))
        poller.set_session("stored-1")
        intervals = [poller.poll_once() for _ in range(4)]
        self.assertEqual(intervals, [HUD_POLL_MIN_SECONDS, 4.0, HUD_POLL_MAX_SECONDS, HUD_POLL_MAX_SECONDS])
        # A figure that drifts every poll is delivered, but is not a change.
        poller.take()
        payloads.append({"privacy": "metadata_only", "rows": [{"state": "running", "elapsed_seconds": 9}]})
        self.assertEqual(poller.poll_once(), HUD_POLL_MAX_SECONDS)
        self.assertEqual(poller.take().payload["rows"][0]["elapsed_seconds"], 9)
        payloads.append({"privacy": "metadata_only", "rows": [{"state": "done", "elapsed_seconds": 9}]})
        self.assertEqual(poller.poll_once(), HUD_POLL_MIN_SECONDS)

    def test_a_newly_watched_session_wakes_the_thread_and_restarts_the_back_off(self) -> None:
        # A subagent that starts while the poll is backed off gets its first count at the next fast read, not after
        # waiting out an eight-second interval.
        payload = {"privacy": "metadata_only", "rows": []}
        poller = self.poller(FakeReader(lambda session: copy.deepcopy(payload)))
        poller.set_session("stored-1")
        for _ in range(3):
            poller.poll_once()  # backed off to eight seconds
        self.assertEqual(poller._interval, HUD_POLL_MAX_SECONDS)
        poller._wake.clear()
        poller.watch_tokens(("child-a",))
        self.assertTrue(poller._wake.is_set())
        self.assertEqual(poller._interval, HUD_POLL_MIN_SECONDS)
        for _ in range(3):
            poller.poll_once()
        poller._wake.clear()
        poller.watch_tokens(("child-a",))  # the same sessions wake nothing
        self.assertFalse(poller._wake.is_set())
        self.assertEqual(poller._interval, HUD_POLL_MAX_SECONDS)
        poller.watch_tokens(("child-a", "child-b"))  # a second child starts while the first is still watched
        self.assertTrue(poller._wake.is_set())
        self.assertEqual(poller._interval, HUD_POLL_MIN_SECONDS)
        for _ in range(3):
            poller.poll_once()
        for fewer in (("child-b",), ()):  # one finished, then both: fewer sessions wake nothing
            poller._wake.clear()
            poller.watch_tokens(fewer)
            self.assertFalse(poller._wake.is_set(), fewer)
            self.assertEqual(poller._interval, HUD_POLL_MAX_SECONDS)

    def test_a_refresh_wakes_the_thread_for_a_read_now_and_restarts_the_back_off(self) -> None:
        payload = {"privacy": "metadata_only", "rows": []}
        poller = self.poller(FakeReader(lambda session: copy.deepcopy(payload)))
        poller.set_session("stored-1")
        for _ in range(3):
            poller.poll_once()  # backed off to eight seconds
        poller._wake.clear()
        poller.refresh()
        self.assertTrue(poller._wake.is_set())  # the wait the thread is in ends now
        self.assertEqual(poller.poll_once(), 4.0)  # the back-off starts over from two seconds

    def test_a_reader_failure_is_a_notice_and_backs_off(self) -> None:
        def respond(session: str) -> dict:
            raise sqlite3.OperationalError("database is locked")

        poller = self.poller(FakeReader(respond))
        poller.set_session("stored-1")
        poller.take()
        self.assertEqual(poller.poll_once(), HUD_POLL_MIN_SECONDS)
        snapshot = poller.take()
        self.assertEqual(snapshot.payload, {"error": "OperationalError"})
        self.assertEqual(
            lines_text(panel_lines(snapshot.payload, 80, 4, THEME, 0.0)), ["⚚ OMH HUD unavailable: OperationalError"]
        )
        self.assertEqual(poller.poll_once(), 4.0)

    def test_a_new_snapshot_wakes_the_loop_and_an_unchanged_one_does_not(self) -> None:
        payloads = iter([{"session": "stored-1", "n": 1}, {"session": "stored-1", "n": 1}, {"session": "stored-1", "n": 2}])
        poller = self.poller(FakeReader(lambda session: next(payloads)))
        woken: list[None] = []
        poller.on_snapshot = lambda: woken.append(None)
        poller.set_session("stored-1")
        poller.take()
        for _ in range(3):
            poller.poll_once()
        self.assertEqual(len(woken), 2)  # the first payload and the changed third, not the repeat

    def test_start_hands_the_thread_the_loops_wake(self) -> None:
        woken = threading.Event()
        poller = HudPoller("/omh", "/hermes", reader=FakeReader())
        poller.start(wake=woken.set)
        self.addCleanup(poller.stop)
        poller.set_session("stored-1")
        self.assertTrue(woken.wait(2.0), "the first snapshot of a session wakes the loop")
        self.assertEqual(poller.take().payload["session"], "stored-1")

    def test_the_thread_waits_for_a_session_delivers_and_stops_promptly(self) -> None:
        reader = FakeReader()
        poller = HudPoller("/omh", "/hermes", reader=reader)
        poller.start()
        self.addCleanup(poller.stop)
        self.assertFalse(reader.called.wait(0.2), "no read before a session is named")
        self.assertIsNone(poller.take())
        poller.set_session("stored-1")
        self.assertTrue(reader.called.wait(2.0), "naming a session wakes the thread at once")
        deadline = time.monotonic() + 2.0
        snapshot = poller.take()
        while (snapshot is None or snapshot.payload is None) and time.monotonic() < deadline:
            time.sleep(0.01)
            snapshot = poller.take() or snapshot
        self.assertEqual(snapshot.payload["session"], "stored-1")
        started = time.monotonic()
        poller.stop()
        self.assertLess(time.monotonic() - started, 0.5, "stop must not wait out the two-second interval")
        self.assertFalse(poller._thread.is_alive())


def state_db(home: Path, rows: dict[str, object]) -> Path:
    """A state.db under `home` whose `sessions` rows are `rows` (session id to `output_tokens`), as Hermes keeps them."""
    path = home / "state.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0)"
        )
        connection.executemany("INSERT INTO sessions (id, output_tokens) VALUES (?, ?)", rows.items())
    connection.close()
    return path


class ReadOutputTokensTests(unittest.TestCase):
    """`read_output_tokens`: the watched child sessions' counts in one read-only query, and nothing on any failure."""

    def test_it_reads_each_named_session_the_database_holds(self) -> None:
        with TemporaryDirectory() as home:
            state_db(Path(home), {"child-a": 1200, "child-b": 0, "child-c": None, "parent": 9000})
            self.assertEqual(
                read_output_tokens(home, ("child-a", "child-b", "child-c", "child-gone")),
                {"child-a": 1200, "child-b": 0},
            )

    def test_an_id_is_a_value_never_query_text(self) -> None:
        # Hermes makes the ids, but a quote in one must still name only that row: the ids are bound, not spliced.
        hostile = ("x') OR 1=1 --", "' OR '1'='1", 'child-a"; DROP TABLE sessions; --', "%", "*", "it's")
        with TemporaryDirectory() as home:
            path = state_db(Path(home), {"child-a": 1200, "parent": 9000, "it's": 7})
            self.assertEqual(read_output_tokens(home, hostile), {"it's": 7})
            with sqlite3.connect(path) as connection:
                count = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            connection.close()
            self.assertEqual(count, 3)

    def test_it_opens_the_database_read_only(self) -> None:
        from unittest import mock

        real = sqlite3.connect
        opened: list[tuple[str, object, str]] = []

        def spy(database, *args, **kwargs):  # the real connection, after a write is tried through it
            connection = real(database, *args, **kwargs)
            try:
                connection.execute("UPDATE sessions SET output_tokens = 0")
                outcome = "written"
            except sqlite3.OperationalError as error:
                outcome = str(error)
            opened.append((database, kwargs.get("uri"), outcome))
            return connection

        with TemporaryDirectory() as home:
            state_db(Path(home), {"child-a": 5})
            with mock.patch("omh.tui.panels.sqlite3.connect", spy):
                self.assertEqual(read_output_tokens(home, ("child-a",)), {"child-a": 5})
        self.assertEqual(len(opened), 1, "one connection for the read")
        database, uri, outcome = opened[0]
        self.assertTrue(database.startswith("file:") and database.endswith("?mode=ro"), database)
        self.assertIs(uri, True)
        self.assertIn("readonly", outcome)

    def test_a_home_whose_path_holds_a_hash_or_a_question_mark_is_read(self) -> None:
        # A URI reads `#` as the start of a fragment and `?` as the start of the query: the path is quoted.
        name = "odd#home" if os.name == "nt" else "odd#home?x"  # Windows allows no `?` in a file name
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / name
            home.mkdir()
            state_db(home, {"child-a": 1200})
            self.assertEqual(read_output_tokens(str(home), ("child-a",)), {"child-a": 1200})

    def test_a_child_hermes_rotated_counts_every_segment_it_wrote_in(self) -> None:
        # The frames keep naming the child's first session; Hermes' rotating compaction (`in_place: false`) goes on in a
        # new row that counts from 0, so the read follows the continuation. A delegate the child started is its own
        # conversation and is not counted.
        from _hermes_session_rows import compacted, row, write_sessions

        with TemporaryDirectory() as home:
            child = {"parent": "parent", "source": "subagent", "delegate_from": "parent"}
            path = write_sessions(
                Path(home),
                row("parent"),
                compacted("child-a", at=1050.0, **child),
                compacted("child-a2", at=1100.0, started_at=1050.0, **{**child, "parent": "child-a"}),
                row("child-a3", started_at=1100.0, **{**child, "parent": "child-a2"}),
                row("grandchild", parent="child-a", source="subagent", delegate_from="child-a"),
                row("child-b", **child),
            )
            with sqlite3.connect(path) as connection:
                connection.execute("ALTER TABLE sessions ADD COLUMN output_tokens INTEGER DEFAULT 0")
                connection.executemany("UPDATE sessions SET output_tokens = ? WHERE id = ?", [
                    (1200, "child-a"), (700, "child-a2"), (300, "child-a3"), (5000, "grandchild"), (40, "child-b")])
            connection.close()
            self.assertEqual(read_output_tokens(home, ("child-a", "child-b")), {"child-a": 2200, "child-b": 40})

    def test_it_never_creates_or_changes_the_database(self) -> None:
        with TemporaryDirectory() as home:
            self.assertEqual(read_output_tokens(home, ("child-a",)), {})
            self.assertEqual(list(Path(home).iterdir()), [], "an absent state.db is not created")
            path = state_db(Path(home), {"child-a": 5})
            before = (path.read_bytes(), sorted(item.name for item in Path(home).iterdir()))
            read_output_tokens(home, ("child-a",))
            self.assertEqual((path.read_bytes(), sorted(item.name for item in Path(home).iterdir())), before)

    def test_an_unreadable_database_reads_as_no_counts(self) -> None:
        with TemporaryDirectory() as home:
            root = Path(home)
            self.assertEqual(read_output_tokens(None, ("child-a",)), {})
            self.assertEqual(read_output_tokens(7, ("child-a",)), {})
            self.assertEqual(read_output_tokens("", ("child-a",)), {})
            self.assertEqual(read_output_tokens("bad\0home", ("child-a",)), {})
            (root / "state.db").mkdir()
            self.assertEqual(read_output_tokens(home, ("child-a",)), {}, "a directory named state.db")
            (root / "state.db").rmdir()
            (root / "state.db").write_bytes(b"not a database" * 100)
            self.assertEqual(read_output_tokens(home, ("child-a",)), {}, "a file that is not SQLite")
            (root / "state.db").unlink()
            with sqlite3.connect(root / "state.db") as connection:
                connection.execute("CREATE TABLE other (id TEXT)")
            connection.close()
            self.assertEqual(read_output_tokens(home, ("child-a",)), {}, "a database with no sessions table yet")

    def test_a_locked_database_reads_as_no_counts_within_the_busy_wait(self) -> None:
        with TemporaryDirectory() as home:
            path = state_db(Path(home), {"child-a": 5})
            # Closed before the folder is removed: Windows will not unlink a file a connection still holds.
            writer = sqlite3.connect(path, isolation_level=None)
            try:
                writer.execute("PRAGMA journal_mode=DELETE")
                writer.execute("BEGIN EXCLUSIVE")
                started = time.monotonic()
                self.assertEqual(read_output_tokens(home, ("child-a",)), {})
                self.assertLess(time.monotonic() - started, 2.0)
                writer.execute("ROLLBACK")
            finally:
                writer.close()
            self.assertEqual(read_output_tokens(home, ("child-a",)), {"child-a": 5})

    def test_without_a_session_to_read_it_opens_nothing(self) -> None:
        from unittest import mock

        with TemporaryDirectory() as home:
            state_db(Path(home), {"child-a": 5})
            with mock.patch("omh.tui.panels.sqlite3.connect") as connect:
                self.assertEqual(read_output_tokens(home, ()), {})
            connect.assert_not_called()


class HudPollerTokenTests(unittest.TestCase):
    """Each HUD read also takes the watched subagents' output tokens, from the state.db of the home it read."""

    def poller(self, home: str, payloads: list[dict]) -> HudPoller:
        reader = FakeReader(lambda session: {**payloads[-1], "hermes_home": home})
        poller = HudPoller("/omh", "/hermes", package_version="9.9.9", reader=reader, clock=lambda: 50.0)
        poller.set_session("stored-1")
        poller.take()
        return poller

    def test_a_snapshot_carries_the_watched_sessions_counts(self) -> None:
        with TemporaryDirectory() as home:
            path = state_db(Path(home), {"child-a": 300, "child-b": 700})
            poller = self.poller(home, [{"privacy": "metadata_only"}])
            poller.poll_once()
            self.assertEqual(poller.take().output_tokens, {}, "nothing is watched yet")
            poller.watch_tokens(("child-a", "child-b"))
            poller.poll_once()
            self.assertEqual(poller.take().output_tokens, {"child-a": 300, "child-b": 700})
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE sessions SET output_tokens = output_tokens + 300 WHERE id = 'child-a'")
            connection.close()
            poller.poll_once()
            self.assertEqual(poller.take().output_tokens, {"child-a": 600, "child-b": 700})
            poller.watch_tokens(())
            poller.poll_once()
            self.assertEqual(poller.take().output_tokens, {})

    def test_a_count_that_moved_keeps_the_poll_at_two_seconds(self) -> None:
        with TemporaryDirectory() as home:
            path = state_db(Path(home), {"child-a": 300})
            poller = self.poller(home, [{"privacy": "metadata_only"}])
            poller.watch_tokens(("child-a",))
            self.assertEqual([poller.poll_once() for _ in range(3)], [HUD_POLL_MIN_SECONDS, 4.0, HUD_POLL_MAX_SECONDS])
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE sessions SET output_tokens = 900 WHERE id = 'child-a'")
            connection.close()
            self.assertEqual(poller.poll_once(), HUD_POLL_MIN_SECONDS)
            self.assertEqual(poller.take().output_tokens, {"child-a": 900})

    def test_a_payload_without_a_home_or_an_unreadable_database_gives_no_counts(self) -> None:
        reader = FakeReader()  # a payload without `hermes_home`, as a failed read's is
        poller = HudPoller("/omh", "/hermes", reader=reader, clock=lambda: 50.0)
        poller.set_session("stored-1")
        poller.take()
        poller.watch_tokens(("child-a",))
        poller.poll_once()
        self.assertEqual(poller.take().output_tokens, {})
        with TemporaryDirectory() as home:
            (Path(home) / "state.db").write_bytes(b"not a database")
            poller = self.poller(home, [{"privacy": "metadata_only"}])
            poller.watch_tokens(("child-a",))
            poller.poll_once()
            snapshot = poller.take()
            self.assertEqual((snapshot.payload["privacy"], snapshot.output_tokens), ("metadata_only", {}))

    def test_the_watch_is_bounded_by_the_rosters_cap(self) -> None:
        from omh.tui.subagents import ROSTER_CAP

        with TemporaryDirectory() as home:
            state_db(Path(home), {f"child-{index}": index + 1 for index in range(80)})
            poller = self.poller(home, [{"privacy": "metadata_only"}])
            poller.watch_tokens(tuple(f"child-{index}" for index in range(80)))
            poller.poll_once()
            self.assertEqual(len(poller.take().output_tokens), ROSTER_CAP)


def parity_cases() -> list[dict]:
    """Three payloads at six widths: a long phased plan with agents and a graph, a small one, and one carrying escapes."""
    items = [
        {
            "text": f"Task number {index} with a fairly long description to truncate",
            "state": "active" if index == 5 else "done" if index < 5 else "pending",
            "phase": f"Phase {min(index, 7)}",
        }
        for index in range(12)
    ]
    items[2]["blocked_reason"] = "not needed"
    items[7]["blocked_reason"] = "needs the owner's call on the layout of the panel"
    items.append({"text": "Subtask", "state": "pending", "depth": 1})
    rows = [
        agent_row(0, turn_count=3, tool_count=12, cost_usd=0.0431, cost_approximate=True, tokens_per_second=41.6,
                  cache_hit_percentage=88, context_percentage=40, fallback_count=1),
        agent_row(1, state="done", category="critic", model="gpt-6.1-sol", effort="xhigh", route_origin="fallback"),
        agent_row(2, state="queued", lane_backend="kanban", assignee="mbot", native_status="ready", model="kimi-k3"),
        agent_row(3, dispatch_lane="maestro", executor_profile="claude_code", model="claude-fable-5-1"),
        agent_row(
            4, state="blocked", action="Blocked worker 한글 제목", category="inherit", cost_usd=0, cost_status="included"
        ),
    ]
    full = with_graph(with_agents(hud_payload(items, title="Parity plan"), rows), 3)
    full["graph"]["nodes"][2].update(state="failed", blocked_by=["unit0", "unit1"])
    small = with_agents(hud_payload(items[:3], title="Small plan"), rows[:2])
    # Escape sequences and ordinary punctuation reaching the renderers: both drop the whole
    # sequence (not only its ESC byte) and keep the apostrophe, comma and question mark. The
    # todo record layer already drops ESC bytes, so the raw text is put into the payload the
    # renderers read, after it was built.
    raw = [
        "Ship the \x1b[31mred\x1b[0m fix, it's ready?",
        "Read \x1b]8;;https://example.test\x07the link\x1b]8;;\x07 then \x1b[2Jstop",
        "cut \x1b[31",
    ]
    escaped = with_agents(
        hud_payload([{"text": f"item {index}", "state": "active" if index == 0 else "pending"} for index in range(3)],
                    title="placeholder"),
        rows[:2],
    )
    escaped["todo"]["title"] = "Esc\x1b[1m plan, person's"
    for key in ("items", "display_items"):
        for item, text in zip(escaped["todo"][key], raw):
            item["text"] = text
    return [
        {"payload": payload, "cols": cols}
        for cols in (60, 80, 99, 100, 140, 200)
        for payload in (full, small, escaped)
    ]


# The rows the Hermes status widget drew for `parity_cases()`, recorded from
# `omh-status.mjs` before it was deleted: the panels are its port, and the
# widget's own tests pinned this look. Deterministic for these payloads (two
# recordings seconds apart matched), so a difference is the panel changing.
PANEL_ROWS = Path(__file__).resolve().parent / "fixtures" / "tui_panel_rows.json"


class PanelRowsTests(unittest.TestCase):
    def test_plan_and_agent_rows_read_exactly_as_the_widget_drew_them(self) -> None:
        cases = parity_cases()
        recorded = json.loads(PANEL_ROWS.read_text(encoding="utf-8"))
        self.assertEqual([(row["cols"], row["plan"]) for row in recorded],
                         [(case["cols"], case["payload"]["todo"]["title"]) for case in cases])
        for case, rows in zip(cases, recorded, strict=True):
            with self.subTest(cols=case["cols"], plan=rows["plan"]):
                mine = [line_text(line).rstrip() for line in panel_lines(case["payload"], case["cols"], 100, THEME, 0.0)]
                plan_at = next(index for index, row in enumerate(mine) if row.startswith("[Plan]"))
                # The widget's dock-top ended with the composer rule, and its
                # dock-bottom opened with a rule and the branded header, which
                # the TUI's info line and `● main │` header replace; the
                # recording leaves those out. The widget also ended a moving
                # plan's header with a walking ellipsis (` .` at this frame),
                # which read as a stray dot (audit D7); the TUI draws none, so it
                # comes off the recorded header and nothing else.
                header, *items = rows["plan_rows"]
                # The widget folded the done items above the window as `... (N earlier tasks)`; since the owner's
                # pass of 2026-10-28 the panel says `✓ N done` for them, and nothing else on the rows moved.
                items = [re.sub(r"^\.\.\. \((\d+) earlier tasks?\)$", r"✓ \1 done", item) for item in items]
                self.assertEqual(mine[plan_at:], [header.removesuffix(" ."), *items])
                # The widget opened the agents block with its fanout graph (`  [global] DAG ·` and one
                # `  [R]/[+]/[!]` row per unit). The panel draws the delegation block from
                # `delegation_graph` in its place, and these payloads carry none, so those recorded
                # rows are the one part of the recording the panel no longer draws.
                recorded_agents = [row for row in rows["agent_rows"] if not row.startswith("  [")]
                self.assertEqual(mine[1:plan_at], recorded_agents)
                self.assertGreater(len(mine[1:plan_at]), 1)


class PunctuationTests(unittest.TestCase):
    def test_ordinary_punctuation_in_plan_text_survives_and_controls_do_not(self) -> None:
        from omh.tui.panels import _sanitize

        self.assertEqual(_sanitize("Answer nothing on the person's behalf, ok?"), "Answer nothing on the person's behalf, ok?")
        self.assertEqual(_sanitize("a\x1b[31mb\x07c"), "abc")


if __name__ == "__main__":
    unittest.main()


class NativePlanDepthTests(unittest.TestCase):
    """A `todo_list` plan's subtasks (Hermes' `parent`) keep their depth through the record into the panel."""

    def test_the_recorded_plans_subtasks_are_drawn_under_their_parent(self) -> None:
        from test_tui_gateway_contract import recorded_events
        from omh.plugin_bundle.omh.native_todo import native_todo_items

        (todos,) = [payload["todos"] for kind, payload in recorded_events("parity") if kind == "todo.updated"]
        items = native_todo_items(todos)
        self.assertEqual([item.get("depth", 0) for item in items], [0, 1, 1])
        rows = lines_text(panel_lines(hud_payload(items), 80, 10, THEME, 0.0))
        self.assertEqual(rows[1:4], ["[ ] Ship the change", "  [•] Write the tests", "  [ ] Write the code"])

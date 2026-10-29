"""The OMH TUI's subagent roster (`omh.tui.subagents`): the fold of gateway events, its bounds, and its rows.

Payloads. `tests/fixtures/tui_gateway/subagent_relay.jsonl` holds frames that
Hermes 6c61c3e27d's own relay and payload builder produced for a scripted run
(its header says how, and what was driven but never emitted). It is not a
recording of a live session. `RelayFixtureTests` replays it whole. The other
cases build each payload from that fixture's first payload with keys changed,
removed or mistyped, so the identity keys are the recorded ones and only the
field under test is constructed. The one exception is the random-payload
case, whose frames are junk by construction.

Expected rows are literals. A click span is checked against the rendered row
by measuring the row with the `width` helpers, never by asking the roster.
"""

from __future__ import annotations

import json
from pathlib import Path
import random
import unittest

from _tui_lines import line_text, lines_text
from omh.tui.panels import SPINNER_FRAMES
from omh.tui.style import Line, Style
from omh.tui.subagents import (
    LOG_ROW_CAP,
    MAIN_ID,
    ROSTER_CAP,
    ROW_CHARS,
    TAIL_CHARS,
    TOKEN_SETTLE_SECONDS,
    Agent,
    Roster,
)
from omh.tui.theme import DEFAULT_THEME as THEME
from omh.tui.theme import kind_style
from omh.tui.width import cluster_width, clusters, is_control, line_width

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tui_gateway" / "subagent_relay.jsonl"
FIRST = "sa-0-1a2b3c4d"
SECOND = "sa-1-5e6f7a8b"
ESC = "\x1b"


def _frames() -> list[tuple[str, dict[str, object]]]:
    rows = FIXTURE.read_text(encoding="utf-8").splitlines()
    return [(frame["type"], frame["payload"]) for frame in map(json.loads, rows[1:])]


FRAMES = _frames()
IDENTITY = {key: value for key, value in FRAMES[0][1].items() if key != "text"}


def payload(subagent_id: str = FIRST, **changes: object) -> dict[str, object]:
    """The recorded identity keys under `subagent_id`, with `changes` laid over them."""
    return {**IDENTITY, "subagent_id": subagent_id, **changes}


def feed(roster: Roster, kind: str, now: float = 0.0, subagent_id: str = FIRST, **changes: object) -> None:
    """One frame of a child. Like the relay's frames, it repeats the goal, model, tool count and child session the
    child's earlier frames gave, unless `changes` names them."""
    held = roster.agents.get(subagent_id)
    said = (
        {"goal": held.goal, "model": held.model, "tool_count": held.tool_count,
         "child_session_id": held.child_session_id}
        if held is not None else {}
    )
    roster.apply(f"subagent.{kind}", payload(subagent_id, **{**said, **changes}), now)


def replayed() -> Roster:
    roster = Roster()
    for index, (event_type, frame) in enumerate(FRAMES):
        roster.apply(event_type, frame, 100.0 + index)
    return roster


def started(*subagent_ids: str, now: float = 0.0) -> Roster:
    roster = Roster()
    for subagent_id in subagent_ids:
        feed(roster, "start", now, subagent_id)
    return roster


def log_rows(roster: Roster, subagent_id: str = FIRST) -> list[tuple[str, ...]]:
    return [tuple(row) for row in roster.agents[subagent_id].log]


def cells(text: str, start: int, end: int) -> str:
    """What `text` shows in cells `start` to `end` (exclusive), measured cluster by cluster."""
    shown: list[str] = []
    column = 0
    for cluster in clusters(text):
        width = cluster_width(cluster)
        if start <= column and column + width <= end:
            shown.append(cluster)
        column += width
    return "".join(shown)


def style_of(line: Line, text: str) -> Style:
    for span in line:
        if text in span.text:
            return span.style
    raise AssertionError(f"{text!r} is in no span of {line_text(line)!r}")


def every_row(roster: Roster, width: int = 60, now: float = 50.0) -> list[Line]:
    """Every row the roster can draw at `width`: the agent view, collapsed and whole, the list, and each agent's log
    view."""
    rows: list[Line] = roster.view_lines(width, THEME, 0, 3, now) + roster.view_lines(width, THEME, 0, ROSTER_CAP + 1, now)
    rows.extend(roster.list_lines(width, THEME, MAIN_ID, 0, ROSTER_CAP + 1, now)[0])
    for subagent_id in roster.agents:
        rows.extend(roster.log_lines(subagent_id, width, THEME, now))
    return rows


class RelayFixtureTests(unittest.TestCase):
    """Hermes' own frames, replayed in emit order."""

    def test_the_recorded_frames_hold_no_spawn_requested_and_no_text(self) -> None:
        # The driver handed the relay both; the fixture header says where each one stopped.
        self.assertEqual(
            sorted({event_type for event_type, _ in FRAMES}),
            ["subagent.complete", "subagent.progress", "subagent.start", "subagent.thinking", "subagent.tool"],
        )

    def test_every_frame_carries_the_identity_the_fold_relies_on(self) -> None:
        for event_type, frame in FRAMES:
            with self.subTest(event_type=event_type):
                self.assertLessEqual({"goal", "subagent_id", "model", "tool_count"}, set(frame))

    def test_replay_ends_with_one_completed_and_one_timed_out_agent(self) -> None:
        roster = replayed()
        self.assertEqual(list(roster.agents), [FIRST, SECOND])
        first, second = roster.agents[FIRST], roster.agents[SECOND]
        self.assertEqual(
            (first.status, first.tool_count, first.last_tool, first.model, first.duration),
            ("completed", 6, "read_file", "deepseek-v4.1-flash", 12.34),
        )
        self.assertEqual(first.goal, "find usages of old_api in src/ and list every call site")
        self.assertEqual((first.started_at, first.finished_at), (100.0, 111.0))
        # The fixture completes the second agent twice: `timeout`, then `failed`. The first verdict stays.
        self.assertEqual((second.status, second.duration, second.finished_at), ("timeout", 30.0, 112.0))

    def test_replay_logs_thinking_each_tool_call_and_the_summary(self) -> None:
        self.assertEqual(
            log_rows(replayed()),
            [
                ("thinking", "I will grep for old_api first", ""),
                ("tool", "search_files", "old_api"),
                ("tool", "read_file", "src/api/client.py"),
                ("tool", "terminal", ""),
                ("tool", "read_file", "src/f0.py"),
                ("tool", "read_file", "src/f1.py"),
                ("tool", "read_file", "src/f2.py"),
                ("text", "old_api is called in 3 files:", ""),
                ("text", "- src/api/client.py", ""),
                ("text", "- src/f0.py", ""),
                ("text", "- src/f1.py", ""),
            ],
        )

    def test_a_completion_without_a_summary_logs_its_text(self) -> None:
        # The recorded `timeout` frame has `text` and no `summary`; the hidden-reasoning frame added no row.
        self.assertEqual(log_rows(replayed(), SECOND), [("text", "provider timeout", "")])

    def test_the_progress_frame_adds_no_row_because_its_tools_were_already_logged(self) -> None:
        roster = Roster()
        for index, (event_type, frame) in enumerate(FRAMES):
            before = len(roster.agents[FIRST].log) if FIRST in roster.agents else 0
            roster.apply(event_type, frame, float(index))
            if event_type == "subagent.progress":
                self.assertEqual(len(roster.agents[FIRST].log), before)
                self.assertIn("search_files, read_file", str(frame["text"]))
                return
        self.fail("the fixture has no subagent.progress frame")

    def test_replay_renders(self) -> None:
        # The completed agent's `subagent.complete` counted 340 output tokens; the timed-out one's counted none.
        roster = replayed()
        self.assertEqual(
            lines_text(roster.view_lines(70, THEME, 0, 7, 500.0)),
            [  # each row's title, then the model it ran on leading its figures; a row's count without the word
                "  ● main",
                "  ○ find usages of old_ap…  deepseek-v4.1-flash · 12s · 6 tools · ↓340",
                "  ✗ read the diff for risks        deepseek-v4.1-flash · 30s · 0 tools",
            ],
        )
        rows, ids = roster.list_lines(70, THEME, SECOND, 0, 6, 500.0)
        self.assertEqual(
            lines_text(rows),
            [
                "  ● main",
                "  ○ find usages of old_ap…  deepseek-v4.1-flash · 12s · 6 tools · ↓340",
                "❯ ✗ read the diff for risks        deepseek-v4.1-flash · 30s · 0 tools",
            ],
        )
        self.assertEqual(ids, (MAIN_ID, FIRST, SECOND))
        self.assertEqual(
            lines_text(roster.log_lines(FIRST, 70, THEME, 500.0))[:5],
            [
                "find usages of old_api in src/ and list every call site",
                "completed · 12s · 6 tools · ↓340\N{NO-BREAK SPACE}tokens · deepseek-v4.1-flash",
                "",
                "▸ I will grep for old_api first",
                "● search_files  old_api",
            ],
        )


class FoldTests(unittest.TestCase):
    def test_start_makes_a_running_agent_timed_from_now(self) -> None:
        roster = Roster()
        feed(roster, "start", 7.0)
        agent = roster.agents[FIRST]
        self.assertEqual((agent.status, agent.started_at, agent.finished_at, agent.duration), ("running", 7.0, None, None))
        self.assertEqual((agent.tool_count, agent.last_tool, list(agent.log)), (0, "", []))
        self.assertEqual(agent.name, "find usages of")

    def test_a_name_leaves_off_a_colon_its_last_word_ended_on_and_keeps_a_dot(self) -> None:
        # Found live: `↪ steering child beta:: …` and `· Interrupted child alpha:.` from goals `child beta: …`.
        for goal, name in (("child alpha: count to ten slowly", "child alpha"), ("review;", "review"), (":", ":"),
                           ("use e.g. this one", "use e.g. this"), ("bump to v1.2.", "bump to v1.2.")):
            self.assertEqual(Agent("a1", "running", 0.0, goal=goal).name, name, goal)

    def test_spawn_requested_queues_and_start_then_times_the_run_not_the_wait(self) -> None:
        roster = Roster()
        feed(roster, "spawn_requested", 1.0)
        self.assertEqual((roster.agents[FIRST].status, roster.agents[FIRST].started_at), ("queued", 1.0))
        feed(roster, "start", 9.0)
        self.assertEqual((roster.agents[FIRST].status, roster.agents[FIRST].started_at), ("running", 9.0))

    def test_a_late_spawn_requested_does_not_demote_a_running_agent(self) -> None:
        roster = started(FIRST, now=3.0)
        feed(roster, "spawn_requested", 8.0)
        self.assertEqual((roster.agents[FIRST].status, roster.agents[FIRST].started_at), ("running", 3.0))

    def test_tool_takes_the_count_the_frame_carries_and_logs_the_call(self) -> None:
        roster = started(FIRST)
        feed(roster, "tool", tool_count=4, tool_name="terminal", tool_preview="npm test", text="npm test")
        agent = roster.agents[FIRST]
        self.assertEqual((agent.tool_count, agent.last_tool), (4, "terminal"))
        self.assertEqual(log_rows(roster), [("tool", "terminal", "npm test")])

    def test_tool_preview_falls_back_to_text_and_a_nameless_call_is_a_tool(self) -> None:
        roster = started(FIRST)
        feed(roster, "tool", text="only text")
        feed(roster, "tool", tool_name="read_file")
        self.assertEqual(log_rows(roster), [("tool", "tool", "only text"), ("tool", "read_file", "")])
        self.assertEqual(roster.agents[FIRST].last_tool, "read_file")

    def test_thinking_logs_its_line_and_an_empty_one_logs_nothing(self) -> None:
        roster = started(FIRST)
        feed(roster, "thinking", text="first\nsecond   line")
        feed(roster, "thinking", text="   ")
        feed(roster, "thinking")
        self.assertEqual(log_rows(roster), [("thinking", "first second line", "")])

    def test_progress_updates_the_count_and_logs_nothing(self) -> None:
        roster = started(FIRST)
        feed(roster, "progress", tool_count=5, text="🔀 [set 1 · 1/2] a, b, c, d, e")
        self.assertEqual((roster.agents[FIRST].tool_count, log_rows(roster)), (5, []))

    def test_complete_keeps_the_status_hermes_names(self) -> None:
        for status in ("completed", "interrupted", "failed", "error", "timeout"):
            with self.subTest(status=status):
                roster = started(FIRST)
                feed(roster, "complete", 5.0, status=status)
                self.assertEqual(roster.agents[FIRST].status, status)

    def test_complete_reads_any_other_status_as_completed(self) -> None:
        for status in ("running", "queued", "weird", "", None, 3, ["failed"], {"status": "failed"}):
            with self.subTest(status=status):
                roster = started(FIRST)
                feed(roster, "complete", 5.0, status=status)
                self.assertEqual(roster.agents[FIRST].status, "completed")

    def test_complete_reads_the_status_whatever_its_case(self) -> None:
        roster = started(FIRST)
        feed(roster, "complete", 5.0, status="Timeout")
        self.assertEqual(roster.agents[FIRST].status, "timeout")

    def test_elapsed_is_hermes_duration_once_finished_with_one(self) -> None:
        roster = started(FIRST, now=10.0)
        self.assertEqual(roster.agents[FIRST].elapsed(14.5), 4.5)
        feed(roster, "complete", 20.0, status="completed", duration_seconds=3)
        agent = roster.agents[FIRST]
        self.assertEqual((agent.finished_at, agent.duration), (20.0, 3.0))
        self.assertIsInstance(agent.duration, float)
        self.assertEqual(agent.elapsed(999.0), 3.0)

    def test_elapsed_falls_back_to_the_clock_when_the_duration_is_unusable(self) -> None:
        for duration in (None, "3", True, -1, float("nan"), float("inf"), 10**400, [3], 1_000_000_001):
            with self.subTest(duration=duration):
                roster = started(FIRST, now=10.0)
                feed(roster, "complete", 25.0, duration_seconds=duration)
                agent = roster.agents[FIRST]
                self.assertIsNone(agent.duration)
                self.assertEqual(agent.elapsed(999.0), 15.0)

    def test_elapsed_is_never_negative(self) -> None:
        self.assertEqual(Agent(FIRST, "running", 10.0).elapsed(4.0), 0.0)

    def test_a_later_frame_replaces_goal_and_model_only_when_it_carries_them(self) -> None:
        roster = started(FIRST)
        feed(roster, "tool", goal="", model="")
        self.assertEqual(roster.agents[FIRST].goal, "find usages of old_api in src/ and list every call site")
        self.assertEqual(roster.agents[FIRST].model, "deepseek-v4.1-flash")
        feed(roster, "tool", goal="a new goal", model="glm-5.3")
        self.assertEqual((roster.agents[FIRST].goal, roster.agents[FIRST].model), ("a new goal", "glm-5.3"))

    def test_complete_takes_the_identity_its_frame_carries(self) -> None:
        roster = started(FIRST)
        feed(roster, "complete", 5.0, tool_count=9, model="glm-5.3")
        self.assertEqual((roster.agents[FIRST].tool_count, roster.agents[FIRST].model), (9, "glm-5.3"))

    def test_an_event_that_is_not_a_subagent_lifecycle_event_changes_nothing(self) -> None:
        # `subagent.text` is the one the relay is handed and the gateway keeps off the parent session.
        for event_type in ("subagent.text", "subagent.unknown", "subagent", "message.delta", "", None, 5, ["subagent.start"]):
            with self.subTest(event_type=event_type):
                roster = Roster()
                roster.apply(event_type, payload(text="reply text"), 1.0)  # type: ignore[arg-type]
                self.assertEqual(roster.agents, {})

    def test_agents_keep_the_order_they_first_reported_in(self) -> None:
        roster = started("sa-b", "sa-a", "sa-c")
        feed(roster, "tool", subagent_id="sa-a")
        self.assertEqual(roster.ids(), (MAIN_ID, "sa-b", "sa-a", "sa-c"))

    def test_clear_drops_every_agent(self) -> None:
        roster = started("sa-a", "sa-b")
        roster.clear()
        self.assertEqual((roster.agents, roster.ids()), ({}, (MAIN_ID,)))


class NameTests(unittest.TestCase):
    def test_the_name_is_the_first_words_of_the_goal_that_fit_sixteen_cells(self) -> None:
        cases = {
            "review": "review",
            "read the diff for risks": "read the diff",
            "exactly sixteen! and more": "exactly sixteen!",
            "exactly sixteen!x and more": "exactly",
            "supercalifragilisticexpialidocious goal": "supercalifragil…",
            "한글 검색 에이전트 실행": "한글 검색",
            "가나다라마바사아자차카": "가나다라마바사…",
            "": "agent",
            "   ": "agent",
        }
        for goal, name in cases.items():
            with self.subTest(goal=goal):
                self.assertEqual(Agent(FIRST, "running", 0.0, goal=goal).name, name)


class OutOfOrderTests(unittest.TestCase):
    def test_a_tool_before_start_makes_the_agent_and_start_then_changes_nothing(self) -> None:
        roster = Roster()
        feed(roster, "tool", 4.0, tool_count=1, tool_name="read_file", tool_preview="a.py")
        agent = roster.agents[FIRST]
        self.assertEqual((agent.status, agent.started_at, agent.tool_count), ("running", 4.0, 1))
        feed(roster, "start", 9.0, tool_count=1)
        self.assertEqual((agent.status, agent.started_at, agent.tool_count), ("running", 4.0, 1))
        self.assertEqual(log_rows(roster), [("tool", "read_file", "a.py")])

    def test_thinking_and_progress_before_start_make_the_agent_too(self) -> None:
        for kind in ("thinking", "progress"):
            with self.subTest(kind=kind):
                roster = Roster()
                feed(roster, kind, 4.0, text="x")
                self.assertEqual(roster.agents[FIRST].status, "running")

    def test_a_second_complete_changes_nothing(self) -> None:
        roster = started(FIRST, now=1.0)
        feed(roster, "complete", 5.0, status="failed", duration_seconds=4.0, summary="boom", tool_count=2)
        feed(roster, "complete", 9.0, status="completed", duration_seconds=8.0, summary="fine", tool_count=7, goal="other")
        agent = roster.agents[FIRST]
        self.assertEqual((agent.status, agent.finished_at, agent.duration, agent.tool_count), ("failed", 5.0, 4.0, 2))
        self.assertEqual(agent.goal, "find usages of old_api in src/ and list every call site")
        self.assertEqual(log_rows(roster), [("text", "boom", "")])

    def test_a_complete_for_an_agent_never_seen_makes_no_agent(self) -> None:
        roster = started(FIRST)
        feed(roster, "complete", 5.0, "sa-9-unknown", status="completed", summary="done")
        self.assertEqual(list(roster.agents), [FIRST])

    def test_a_finished_agent_ignores_every_later_frame(self) -> None:
        for kind in ("spawn_requested", "start", "progress", "thinking", "tool"):
            with self.subTest(kind=kind):
                roster = started(FIRST, now=1.0)
                feed(roster, "complete", 5.0, status="interrupted", summary="stopped", tool_count=2)
                feed(roster, kind, 9.0, text="late", tool_name="late_tool", tool_count=8, goal="late goal", model="late")
                agent = roster.agents[FIRST]
                self.assertEqual((agent.status, agent.started_at, agent.finished_at), ("interrupted", 1.0, 5.0))
                self.assertEqual((agent.tool_count, agent.last_tool, agent.model), (2, "", "deepseek-v4.1-flash"))
                self.assertEqual(agent.goal, "find usages of old_api in src/ and list every call site")
                self.assertEqual(log_rows(roster), [("text", "stopped", "")])

    def test_an_agent_dropped_by_clear_comes_back_when_it_reports_again(self) -> None:
        roster = started(FIRST, now=1.0)
        roster.clear()
        feed(roster, "tool", 6.0, tool_count=3, tool_name="terminal")
        self.assertEqual((roster.agents[FIRST].status, roster.agents[FIRST].started_at), ("running", 6.0))


class MalformedPayloadTests(unittest.TestCase):
    def test_a_payload_that_is_not_an_object_changes_nothing(self) -> None:
        for bad in (None, [], "subagent", 3, [("subagent_id", FIRST)]):
            with self.subTest(bad=bad):
                roster = Roster()
                roster.apply("subagent.start", bad, 1.0)
                self.assertEqual(roster.agents, {})

    def test_a_frame_without_a_usable_id_changes_nothing(self) -> None:
        # Blank after strip too: the gateway contract refuses such an id in a call (`call_problem`).
        for bad in (None, "", " ", "\t\n", 7, ["sa-1"], {"id": "sa-1"}, True, "x" * 129):
            with self.subTest(bad=bad):
                roster = Roster()
                roster.apply("subagent.start", payload(bad), 1.0)  # type: ignore[arg-type]
                self.assertEqual(roster.agents, {})
        roster = Roster()
        roster.apply("subagent.start", {key: value for key, value in IDENTITY.items() if key != "subagent_id"}, 1.0)
        self.assertEqual(roster.agents, {})

    def test_an_id_with_spaces_around_its_text_is_kept_as_it_came(self) -> None:
        roster = Roster()
        roster.apply("subagent.start", payload(" sa-1 "), 1.0)
        self.assertEqual(list(roster.agents), [" sa-1 "])

    def test_the_longest_id_accepted_is_128_characters(self) -> None:
        roster = Roster()
        roster.apply("subagent.start", payload("x" * 128), 1.0)
        self.assertEqual(list(roster.agents), ["x" * 128])

    def test_a_mistyped_field_is_skipped_and_the_rest_of_the_frame_is_kept(self) -> None:
        roster = started(FIRST)
        feed(roster, "tool", tool_count=2, tool_name="read_file", tool_preview="a.py")
        for bad_count in ("3", True, -1, 7.5, 5.0, None, [3], 10**400, 1_000_000):
            feed(roster, "tool", goal=5, model=["m"], tool_count=bad_count, tool_name={"n": 1}, tool_preview=9, text=4)
        agent = roster.agents[FIRST]
        self.assertEqual(agent.goal, "find usages of old_api in src/ and list every call site")
        self.assertEqual((agent.model, agent.tool_count, agent.last_tool), ("deepseek-v4.1-flash", 2, "tool"))
        self.assertIs(type(agent.tool_count), int)
        self.assertEqual(log_rows(roster), [("tool", "read_file", "a.py")] + [("tool", "tool", "")] * 9)
        feed(roster, "thinking", text=["not", "text"])
        feed(roster, "complete", 3.0, status=["failed"], summary={"s": 1}, text=None)
        self.assertEqual((agent.status, len(agent.log)), ("completed", 10))

    def test_the_largest_tool_count_accepted_is_999999(self) -> None:
        roster = started(FIRST)
        feed(roster, "tool", tool_count=999_999)
        self.assertEqual(roster.agents[FIRST].tool_count, 999_999)

    def test_random_payloads_never_raise_and_never_draw_a_control_character(self) -> None:
        rng = random.Random(20261013)
        junk = [
            None, True, False, 0, -3, 7, 2.5, float("nan"), float("inf"), 10**400, "", "text", "a\nb", "tab\there",
            f"{ESC}[31mred{ESC}[0m", f"{ESC}]8;;http://x{ESC}\\link", "\x07bell\x00nul\x9b2J", "한글 🚀", [], ["x"], {},
            {"k": "v"}, "x" * 5000, "completed", "failed", "timeout", "sa-0", "sa-1", "sa-2",
        ]
        keys = [
            "subagent_id", "goal", "model", "tool_count", "tool_name", "tool_preview", "text", "status", "summary",
            "duration_seconds", "depth", "parent_id",
        ]
        kinds = ["spawn_requested", "start", "progress", "thinking", "tool", "complete", "text", "bogus"]
        roster = Roster()
        for step in range(3000):
            frame = {key: rng.choice(junk) for key in rng.sample(keys, rng.randint(0, len(keys)))}
            if rng.random() < 0.7:
                frame["subagent_id"] = rng.choice(["sa-0", "sa-1", "sa-2"])
            roster.apply(f"subagent.{rng.choice(kinds)}", frame, float(step))
            if step % 100 == 0:
                roster.ingest_tail(rng.choice(["sa-0", "sa-1", "nope"]), rng.choice(junk), rng.choice(junk))  # type: ignore[arg-type]
                for width in (4, 9, 40):
                    for row in every_row(roster, width, float(step)):
                        self.assertLessEqual(line_width(row), width)
                        self.assertFalse([ch for span in row for ch in span.text if is_control(ch)])
        self.assertLessEqual({"sa-0", "sa-1", "sa-2"}, set(roster.agents))
        self.assertLessEqual(len(roster.agents), ROSTER_CAP)


class LogCapTests(unittest.TestCase):
    def _filled(self, rows: int) -> Roster:
        roster = started(FIRST)
        for index in range(rows):
            feed(roster, "thinking", text=f"row {index}")
        return roster

    def test_the_log_holds_four_hundred_rows(self) -> None:
        self.assertEqual(LOG_ROW_CAP, 400)
        agent = self._filled(400).agents[FIRST]
        self.assertEqual((len(agent.log), agent.dropped, agent.log[0].text, agent.log[-1].text), (400, 0, "row 0", "row 399"))

    def test_a_full_log_drops_its_oldest_row_and_counts_it(self) -> None:
        agent = self._filled(437).agents[FIRST]
        self.assertEqual((len(agent.log), agent.dropped, agent.log[0].text, agent.log[-1].text), (400, 37, "row 37", "row 436"))

    def test_the_log_view_opens_by_saying_how_many_rows_were_dropped(self) -> None:
        cases = {400: "▸ row 0", 401: "… 1 earlier row dropped", 437: "… 37 earlier rows dropped"}
        for rows, first_log_row in cases.items():
            with self.subTest(rows=rows):
                view = lines_text(self._filled(rows).log_lines(FIRST, 60, THEME, 0.0))
                self.assertEqual(view[2], "")
                self.assertEqual(view[3], first_log_row)
                self.assertEqual(len(view), 3 + 400 + (1 if rows > 400 else 0))

    def test_summary_rows_count_against_the_cap_too(self) -> None:
        roster = self._filled(399)
        feed(roster, "complete", 1.0, summary="one\ntwo\nthree")
        agent = roster.agents[FIRST]
        self.assertEqual((len(agent.log), agent.dropped, agent.log[0].text, agent.log[-1].text), (400, 2, "row 2", "three"))

    def test_a_long_row_is_cut_and_marked(self) -> None:
        self.assertEqual(ROW_CHARS, 600)
        roster = started(FIRST)
        feed(roster, "thinking", text="t" * 601)
        feed(roster, "tool", tool_name="n" * 81, tool_preview="p" * 601)
        feed(roster, "complete", 1.0, summary="s" * 601)
        self.assertEqual(
            log_rows(roster),
            [("thinking", "t" * 600 + "…", ""), ("tool", "n" * 80 + "…", "p" * 600 + "…"), ("text", "s" * 600 + "…", "")],
        )

    def test_a_row_at_the_limit_is_not_marked(self) -> None:
        roster = started(FIRST)
        feed(roster, "thinking", text="t" * 600)
        feed(roster, "tool", tool_name="n" * 80, tool_preview="p" * 600)
        self.assertEqual(log_rows(roster), [("thinking", "t" * 600, ""), ("tool", "n" * 80, "p" * 600)])

    def test_goal_and_model_are_cut_and_marked(self) -> None:
        roster = Roster()
        feed(roster, "start", goal="g" * 501, model="m" * 81)
        self.assertEqual((roster.agents[FIRST].goal, roster.agents[FIRST].model), ("g" * 500 + "…", "m" * 80 + "…"))
        feed(roster, "tool", goal="g" * 500, model="m" * 80)
        self.assertEqual((roster.agents[FIRST].goal, roster.agents[FIRST].model), ("g" * 500, "m" * 80))

    def test_a_summary_past_two_thousand_characters_is_not_read(self) -> None:
        roster = started(FIRST)
        feed(roster, "complete", 1.0, summary="\n".join(["a" * 499] * 6))
        self.assertEqual([len(row.text) for row in roster.agents[FIRST].log], [499, 499, 499, 499])


class RosterCapTests(unittest.TestCase):
    def _full(self) -> Roster:
        return started(*[f"sa-{index}" for index in range(ROSTER_CAP)])

    def test_the_roster_holds_sixty_four_agents(self) -> None:
        self.assertEqual(ROSTER_CAP, 64)
        roster = self._full()
        self.assertEqual((len(roster.agents), roster.evicted), (64, 0))

    def test_one_more_pushes_out_the_agent_seen_longest_ago_when_none_has_finished(self) -> None:
        roster = self._full()
        feed(roster, "start", subagent_id="sa-new")
        self.assertEqual((len(roster.agents), roster.evicted), (64, 1))
        self.assertNotIn("sa-0", roster.agents)
        self.assertEqual(list(roster.agents)[0], "sa-1")
        self.assertEqual(list(roster.agents)[-1], "sa-new")

    def test_seen_longest_ago_counts_the_last_frame_not_the_first(self) -> None:
        roster = self._full()
        feed(roster, "tool", subagent_id="sa-0")  # the first agent introduced, still busy
        feed(roster, "thinking", subagent_id="sa-2", text="a thought")
        feed(roster, "start", subagent_id="sa-new")
        self.assertIn("sa-0", roster.agents)
        self.assertNotIn("sa-1", roster.agents)
        self.assertEqual(list(roster.agents)[:2], ["sa-0", "sa-2"])  # recency never reorders what is drawn
        feed(roster, "start", subagent_id="sa-newer")
        self.assertNotIn("sa-3", roster.agents)
        self.assertIn("sa-2", roster.agents)
        self.assertEqual(roster.evicted, 2)

    def test_one_more_pushes_out_the_oldest_finished_agent_first(self) -> None:
        roster = self._full()
        feed(roster, "complete", subagent_id="sa-40", status="failed")
        feed(roster, "complete", subagent_id="sa-20", status="completed")
        feed(roster, "start", subagent_id="sa-new")
        self.assertNotIn("sa-20", roster.agents)
        self.assertIn("sa-40", roster.agents)
        self.assertIn("sa-0", roster.agents)
        feed(roster, "start", subagent_id="sa-newer")
        self.assertNotIn("sa-40", roster.agents)
        self.assertEqual((len(roster.agents), roster.evicted), (64, 2))

    def test_a_frame_for_an_agent_already_held_pushes_nobody_out(self) -> None:
        roster = self._full()
        feed(roster, "tool", subagent_id="sa-63")
        self.assertEqual((len(roster.agents), roster.evicted), (64, 0))

    def test_the_count_says_when_the_cap_pushed_agents_out_until_clear(self) -> None:
        roster = self._full()
        self.assertEqual(roster.count_text(), "64 agents")
        feed(roster, "start", subagent_id="sa-new")
        self.assertEqual(roster.count_text(), "64+ agents")
        roster.clear()
        self.assertEqual((roster.evicted, roster.count_text()), (0, ""))
        feed(roster, "start", goal="a " * 200)
        self.assertEqual(roster.count_text(), "1 agent")


class CleaningTests(unittest.TestCase):
    DIRTY = f"{ESC}[31mred{ESC}[0m\x07 {ESC}]8;;http://x{ESC}\\link{ESC}]8;;{ESC}\\ a\tb\x00c\x9b2Jd\r"

    def _dirty_roster(self) -> Roster:
        roster = Roster()
        feed(roster, "start", goal=self.DIRTY, model=self.DIRTY)
        feed(roster, "thinking", text=self.DIRTY)
        feed(roster, "tool", tool_name=self.DIRTY, tool_preview=self.DIRTY)
        feed(roster, "complete", 1.0, summary=f"{self.DIRTY}\n{self.DIRTY}")
        feed(roster, "start", subagent_id=SECOND, goal=self.DIRTY)
        roster.ingest_tail(SECOND, f"{self.DIRTY}\n{self.DIRTY}\n")
        return roster

    def test_stored_strings_are_clean(self) -> None:
        roster = self._dirty_roster()
        agent = roster.agents[FIRST]
        self.assertEqual((agent.goal, agent.model, agent.last_tool), ("red link a bcd", "red link a bcd", "red link a bcd"))
        self.assertEqual(
            log_rows(roster),
            [
                ("thinking", "red link a bcd", ""),
                ("tool", "red link a bcd", "red link a bcd"),
                ("text", "red link a bcd", ""),
                ("text", "red link a bcd", ""),
            ],
        )
        self.assertEqual(log_rows(roster, SECOND), [("text", "red link a bcd", "")] * 2)

    def test_no_escape_or_control_character_reaches_a_rendered_row(self) -> None:
        roster = self._dirty_roster()
        for width in (1, 9, 30, 120):
            rows = every_row(roster, width)
            self.assertTrue(rows)
            for row in rows:
                with self.subTest(width=width, row=line_text(row)):
                    self.assertFalse([ch for span in row for ch in span.text if is_control(ch)])
                    self.assertNotIn("[31m", line_text(row))
                    self.assertNotIn("8;;", line_text(row))
        self.assertIn("● red link a bcd  red link a bcd", lines_text(every_row(roster, 120)))

    def test_an_escape_sequence_cut_by_the_length_limit_leaves_no_debris(self) -> None:
        roster = Roster()
        feed(roster, "start", goal="g" * 495 + f"{ESC}[38;2;255;0;0mtail")
        self.assertEqual(roster.agents[FIRST].goal, "g" * 495 + "…")

    def test_a_goal_of_many_lines_is_one_line(self) -> None:
        roster = Roster()
        feed(roster, "start", goal="  fix the\n\n   parser \r\n and\ttest  ")
        self.assertEqual(roster.agents[FIRST].goal, "fix the parser and test")


class ViewTests(unittest.TestCase):
    """The agent view under the info line: the list's rows with none highlighted, collapsed into one last row when
    more agents than it has rows for."""

    def test_there_is_no_view_without_an_agent_or_without_rows(self) -> None:
        self.assertEqual(Roster().view_lines(80, THEME, 0, 7, 0.0), [])
        for max_rows in (0, -1):
            self.assertEqual(started(FIRST).view_lines(80, THEME, 0, max_rows, 0.0), [])

    def test_each_status_has_its_glyph_and_colour(self) -> None:
        roster = Roster()
        feed(roster, "start", subagent_id="sa-run", goal="explore")
        feed(roster, "start", subagent_id="sa-done", goal="review")
        feed(roster, "complete", subagent_id="sa-done", status="completed")
        feed(roster, "spawn_requested", subagent_id="sa-wait", goal="wait")
        for status in ("failed", "error", "timeout", "interrupted"):
            feed(roster, "start", subagent_id=f"sa-{status}", goal=status)
            feed(roster, "complete", subagent_id=f"sa-{status}", status=status)
        rows = roster.view_lines(40, THEME, 2, 20, 0.0)
        self.assertEqual([line_text(row)[:4] for row in rows],
                         ["  ● ", "  ⠹ ", "  ○ ", "  ◌ ", "  ✗ ", "  ✗ ", "  ✗ ", "  ▪ "])
        for row, glyph, style in zip(rows, "●⠹○◌✗✗✗▪", (THEME.running, THEME.running, THEME.muted, THEME.muted,
                                                       THEME.error, THEME.error, THEME.error, THEME.muted)):
            with self.subTest(glyph=glyph):
                self.assertEqual(style_of(row, glyph), style)
        # What still runs or waits reads in the text colour; a finished agent's goal is muted.
        self.assertEqual([style_of(row, line_text(row)[4:].split("  ")[0]) for row in rows[1:]],
                         [THEME.text, THEME.muted, THEME.text, THEME.muted, THEME.muted, THEME.muted, THEME.muted])

    def test_the_spinner_frame_picks_the_running_glyph(self) -> None:
        self.assertEqual(SPINNER_FRAMES, "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
        roster = started(FIRST)
        for frame, glyph in ((0, "⠋"), (4, "⠼"), (9, "⠏"), (10, "⠋"), (23, "⠸")):
            with self.subTest(frame=frame):
                self.assertEqual(line_text(roster.view_lines(40, THEME, frame, 7, 0.0)[1])[:4], f"  {glyph} ")

    def test_the_view_is_the_lists_rows_with_none_highlighted(self) -> None:
        roster = started("sa-a", "sa-b", now=3.0)
        view = lines_text(roster.view_lines(56, THEME, 0, 7, 20.0))
        listed = lines_text(roster.list_lines(56, THEME, "sa-a", 0, 7, 20.0)[0])
        self.assertEqual(view[0], "  ● main")
        self.assertEqual(len(view), len(listed), "Down highlights a row and moves none")
        self.assertEqual([row[2:] for row in view], [row[2:] for row in listed])
        self.assertEqual([row[:2] for row in listed], ["  ", "❯ ", "  "])

    def test_an_agent_waiting_for_a_worker_shows_the_wait_on_its_clock(self) -> None:
        roster = Roster()
        feed(roster, "spawn_requested", 10.0, "sa-wait", goal="wait for a worker")
        row = line_text(roster.view_lines(50, THEME, 0, 7, 45.0)[1])
        # The wait leads the model's figures; where both do not fit, the model alone (#2223 review R2).
        self.assertEqual(row, "  ◌ wait for a worker" + " " * 10 + "deepseek-v4.1-flash")
        wide = line_text(roster.view_lines(70, THEME, 0, 7, 45.0)[1])
        self.assertTrue(wide.endswith("  deepseek-v4.1-flash · waiting 35s"), wide)
        feed(roster, "start", 50.0, "sa-wait")
        self.assertEqual(line_text(roster.view_lines(50, THEME, 0, 7, 52.0)[1]), "  ⠋ wait for a worker     deepseek-v4.1-flash · 2s")

    def test_more_agents_than_rows_keep_the_running_ones_and_count_the_rest_on_the_last_row(self) -> None:
        roster = Roster()
        for index, status in enumerate(("completed", "running", "failed", "completed", "running", "queued")):
            subagent_id = f"sa-{index}"
            feed(roster, "spawn_requested" if status == "queued" else "start", subagent_id=subagent_id,
                 goal=f"task {index} {status}")
            if status in ("completed", "failed"):
                feed(roster, "complete", subagent_id=subagent_id, status=status)
        cases = {
            7: ["● main", "task 0 completed", "task 1 running", "task 2 failed", "task 3 completed", "task 4 running",
                "task 5 queued"],
            6: ["● main", "task 1 running", "task 2 failed", "task 4 running", "task 5 queued", "○ 2 done"],
            5: ["● main", "task 1 running", "task 4 running", "task 5 queued", "+3 more · 1 failed · 2 done"],
            4: ["● main", "task 1 running", "task 4 running", "+4 more · 1 waiting · 1 failed · 2 done"],
            3: ["● main", "task 1 running", "+5 more · 1 running · 1 waiting · 1 failed · 2 done"],
            2: ["task 1 running", "+5 more · 1 running · 1 waiting · 1 failed · 2 done"],  # main gives its row up
            1: ["+6 more · 2 running · 1 waiting · 1 failed · 2 done"],
        }
        for max_rows, expected in cases.items():
            with self.subTest(max_rows=max_rows):
                rows = lines_text(roster.view_lines(80, THEME, 0, max_rows, 0.0))
                self.assertEqual(len(rows), min(max_rows, 7))
                shown = [row[2:].split("  ")[0].replace("⠋ ", "").replace("○ task", "task").replace("✗ ", "")
                         .replace("◌ ", "") for row in rows]
                self.assertEqual(shown, expected)

    def test_the_collapsed_row_is_muted_and_no_row_exceeds_its_width(self) -> None:
        roster = started(*[f"sa-{index}" for index in range(9)])
        for width in range(1, 90):
            for max_rows in (1, 3, 7):
                for row in roster.view_lines(width, THEME, 0, max_rows, 0.0):
                    self.assertLessEqual(line_width(row), width)
        last = roster.view_lines(80, THEME, 0, 3, 0.0)[-1]
        self.assertEqual(line_text(last), "  +8 more · 8 running")
        self.assertEqual(style_of(last, "+8 more"), THEME.muted)


class ListTests(unittest.TestCase):
    def _roster(self) -> Roster:
        roster = Roster()
        feed(roster, "start", 10.0, "sa-a", goal="find usages of old_api in the tree")
        feed(roster, "tool", 11.0, "sa-a", tool_count=4)
        feed(roster, "start", 16.0, "sa-b", goal="read the diff for risks")
        feed(roster, "tool", 17.0, "sa-b", tool_count=1)
        return roster

    def test_there_is_no_list_without_an_agent_or_without_rows(self) -> None:
        self.assertEqual(Roster().list_lines(60, THEME, MAIN_ID, 0, 6, 0.0), ([], ()))
        for max_rows in (0, -1):
            self.assertEqual(self._roster().list_lines(60, THEME, MAIN_ID, 0, max_rows, 0.0), ([], ()))

    def test_rows_are_marker_glyph_goal_and_right_aligned_figures(self) -> None:
        rows, ids = self._roster().list_lines(56, THEME, "sa-b", 2, 6, 20.0)
        self.assertEqual(
            lines_text(rows),
            [
                "  ● main",
                "  ⠹ find usages of…  deepseek-v4.1-flash · 10s · 4 tools",  # the title is cut first
                "❯ ⠹ read the diff fo…  deepseek-v4.1-flash · 4s · 1 tool",
            ],
        )
        self.assertEqual(ids, (MAIN_ID, "sa-a", "sa-b"))
        self.assertEqual([line_width(row) for row in rows], [8, 56, 56])

    def test_only_the_selected_row_is_the_menu_bar_and_it_spans_the_width(self) -> None:
        rows, _ = self._roster().list_lines(50, THEME, "sa-a", 0, 6, 20.0)
        self.assertEqual([{span.style for span in row} == {THEME.menu_current} for row in rows], [False, True, False])
        self.assertEqual(style_of(rows[0], "●"), THEME.running)
        self.assertEqual(style_of(rows[0], "main"), THEME.text)
        self.assertEqual(style_of(rows[2], "⠋"), THEME.running)
        self.assertEqual(style_of(rows[2], "read the diff"), THEME.text)
        self.assertEqual(style_of(rows[2], "deepseek-v4.1-flash · 4s"), THEME.muted)
        rows, _ = self._roster().list_lines(50, THEME, MAIN_ID, 0, 6, 20.0)
        self.assertEqual(line_text(rows[0]), "❯ ● main" + " " * 42)
        self.assertEqual({span.style for span in rows[0]}, {THEME.menu_current})

    def test_an_unknown_selection_highlights_nothing_and_shows_the_top(self) -> None:
        rows, ids = self._roster().list_lines(50, THEME, "sa-gone", 0, 2, 20.0)
        self.assertEqual(ids, (MAIN_ID, "sa-a"))
        self.assertFalse([row for row in rows if THEME.menu_current in {span.style for span in row}])
        self.assertTrue(all(line_text(row).startswith("  ") for row in rows))

    def test_a_finished_agent_shows_its_final_time(self) -> None:
        roster = self._roster()
        feed(roster, "complete", 30.0, "sa-a", status="completed", duration_seconds=75.2, tool_count=5)
        rows, _ = roster.list_lines(60, THEME, MAIN_ID, 0, 6, 9999.0)
        self.assertEqual(line_text(rows[1]), "  ○ find usages of …  deepseek-v4.1-flash · 1m 15s · 5 tools")
        self.assertTrue(line_text(rows[2]).endswith(" · 2h 46m · 1 tool"), line_text(rows[2]))

    def test_the_list_scrolls_only_as_far_as_the_selection_needs(self) -> None:
        roster = started(*[f"sa-{index}" for index in range(10)])
        ids = roster.ids()
        self.assertEqual(len(ids), 11)
        expected_start = {0: 0, 1: 0, 5: 0, 6: 1, 7: 2, 9: 4, 10: 5}
        for index, row_id in enumerate(ids):
            rows, shown = roster.list_lines(60, THEME, row_id, 0, 6, 0.0)
            with self.subTest(selected=index):
                self.assertEqual(len(rows), 6)
                self.assertIn(row_id, shown)
                start = ids.index(shown[0])
                self.assertEqual(shown, ids[start : start + 6])
                if index in expected_start:
                    self.assertEqual(start, expected_start[index])
                marked = [line_text(row).startswith("❯ ") for row in rows]
                self.assertEqual(marked, [shown_id == row_id for shown_id in shown])

    def test_a_list_shorter_than_its_room_shows_every_row(self) -> None:
        rows, shown = self._roster().list_lines(60, THEME, "sa-b", 0, 6, 20.0)
        self.assertEqual((len(rows), shown), (3, (MAIN_ID, "sa-a", "sa-b")))

    def test_one_row_of_room_shows_the_selected_row(self) -> None:
        rows, shown = self._roster().list_lines(60, THEME, "sa-b", 0, 1, 20.0)
        self.assertEqual((len(rows), shown), (1, ("sa-b",)))

    def test_narrow_rows_keep_the_model_then_the_title_alone(self) -> None:
        roster = self._roster()
        cases = {
            80: "  ⠋ find usages of old_api in the tree       deepseek-v4.1-flash · 10s · 4 tools",
            52: "  ⠋ find usages of old_a…  deepseek-v4.1-flash · 10s",
            42: "  ⠋ find usages of o…  deepseek-v4.1-flash",
            36: "  ⠋ find usages of old_api in the t…",
            20: "  ⠋ find usages of …",
            8: "  ⠋ fin…",
            4: "  ⠋ ",
            2: " …",
            0: "",
        }
        for width, text in cases.items():
            with self.subTest(width=width):
                rows, _ = roster.list_lines(width, THEME, MAIN_ID, 0, 6, 20.0)
                self.assertEqual(line_text(rows[1]), text)

    def test_no_row_exceeds_its_width_with_wide_goals(self) -> None:
        roster = Roster()
        feed(roster, "start", 0.0, "sa-a", goal="한글 검색 에이전트 실행 그리고 결과 정리")
        feed(roster, "start", 0.0, "sa-b", goal="🚀 deploy 🚀 the 🚀 release 🚀 now")
        for selected in (MAIN_ID, "sa-a", "sa-b"):
            for width in range(0, 70):
                rows, _ = roster.list_lines(width, THEME, selected, 0, 6, 5.0)
                for row in rows:
                    self.assertLessEqual(line_width(row), width)
        rows, _ = roster.list_lines(30, THEME, "sa-a", 0, 6, 5.0)
        self.assertEqual(line_text(rows[1]), "❯ ⠋ 한글 검색 에이전트 실행 … ")  # no room for the model: the title alone
        self.assertEqual(line_width(rows[1]), 30)
        rows, _ = roster.list_lines(60, THEME, "sa-a", 0, 6, 5.0)
        self.assertTrue(line_text(rows[1]).endswith("  deepseek-v4.1-flash · 5s · 0 tools"), line_text(rows[1]))

    def test_an_agent_without_a_goal_is_named_agent(self) -> None:
        roster = Roster()
        feed(roster, "start", goal="")
        self.assertEqual(line_text(roster.list_lines(40, THEME, MAIN_ID, 0, 6, 0.0)[0][1])[:9], "  ⠋ agent")
        self.assertEqual(line_text(roster.view_lines(40, THEME, 0, 6, 0.0)[1])[:9], "  ⠋ agent")
        self.assertEqual(lines_text(roster.log_lines(FIRST, 40, THEME, 0.0))[0], "agent")


class TokenTests(unittest.TestCase):
    """Output tokens: the child's state.db row read while it runs, then `subagent.complete`'s count."""

    def _roster(self) -> Roster:
        roster = Roster()
        feed(roster, "start", 10.0, "sa-a", goal="find usages of old_api in the tree", child_session_id="child-a")
        feed(roster, "tool", 11.0, "sa-a", tool_count=3)
        feed(roster, "start", 16.0, "sa-b", goal="read the diff for risks", child_session_id="child-b")
        return roster

    def row(self, roster: Roster, index: int, width: int = 70, now: float = 20.0) -> str:
        return line_text(roster.list_lines(width, THEME, MAIN_ID, 0, 6, now)[0][index])

    def test_every_running_agents_child_session_is_watched(self) -> None:
        roster = self._roster()
        self.assertEqual(roster.token_sessions(20.0), ("child-a", "child-b"))
        roster.clear()
        self.assertEqual(roster.token_sessions(20.0), ())

    def test_an_agent_without_a_usable_child_session_is_never_watched(self) -> None:
        roster = Roster()
        for subagent_id, session in (("sa-a", ""), ("sa-b", "   "), ("sa-c", 7), ("sa-d", "x" * 129)):
            roster.apply("subagent.start", payload(subagent_id, child_session_id=session), 0.0)
        bare = {key: value for key, value in payload("sa-e").items() if key != "child_session_id"}
        roster.apply("subagent.start", bare, 0.0)
        roster.apply("subagent.start", payload("sa-f", child_session_id="y" * 128), 0.0)
        self.assertEqual(len(roster.agents), 6)
        self.assertEqual(roster.token_sessions(0.0), ("y" * 128,))

    def test_a_read_count_shows_on_the_row_and_in_the_log_header(self) -> None:
        roster = self._roster()
        roster.ingest_tokens({"child-a": 1234})
        self.assertEqual(self.row(roster, 1), "  ⠋ find usages of old_a…  deepseek-v4.1-flash · 10s · 3 tools · ↓1.2k")
        self.assertEqual(self.row(roster, 2), "  ⠋ read the diff for risks         deepseek-v4.1-flash · 4s · 0 tools")  # no count
        self.assertEqual(lines_text(roster.view_lines(70, THEME, 0, 6, 20.0))[1], self.row(roster, 1))
        self.assertEqual(
            lines_text(roster.log_lines("sa-a", 80, THEME, 20.0))[1],
            "running · 10s · 3 tools · ↓1.2k\N{NO-BREAK SPACE}tokens · deepseek-v4.1-flash",
        )
        self.assertEqual(lines_text(roster.log_lines("sa-b", 80, THEME, 20.0))[1], "running · 4s · 0 tools · deepseek-v4.1-flash")
        roster.ingest_tokens({"child-a": 2500, "child-b": 80})
        self.assertTrue(self.row(roster, 1).endswith("10s · 3 tools · ↓2.5k"))
        self.assertTrue(self.row(roster, 2).endswith("4s · 0 tools · ↓80"))

    def test_no_count_is_never_drawn_as_zero(self) -> None:
        roster = self._roster()
        roster.ingest_tokens({"child-a": 0})  # the row's default before the child's first call
        for count in ("12", 3.5, True, -1, 10**12 + 1, None):
            roster.ingest_tokens({"child-b": count})
        self.assertEqual([agent.output_tokens for agent in roster.agents.values()], [None, None])
        self.assertFalse([row for row in every_row(roster, 80) if "↓" in line_text(row)])
        roster.ingest_tokens({"child-a": 900})
        roster.ingest_tokens({"child-a": 0})
        roster.ingest_tokens({})
        self.assertEqual(roster.agents["sa-a"].output_tokens, 900, "a later read without a count takes none away")

    def test_complete_gives_the_final_count_and_ends_the_watch(self) -> None:
        roster = self._roster()
        roster.ingest_tokens({"child-a": 1000})
        feed(roster, "complete", 30.0, "sa-a", status="completed", duration_seconds=20.0, output_tokens=1500)
        self.assertEqual(roster.agents["sa-a"].output_tokens, 1500)
        self.assertEqual(roster.token_sessions(30.0), ("child-b",))
        roster.ingest_tokens({"child-a": 1490})  # a read taken before the last call's tokens landed
        self.assertEqual(roster.agents["sa-a"].output_tokens, 1500)
        self.assertEqual(self.row(roster, 1, now=40.0), "  ○ find usages of old_a…  deepseek-v4.1-flash · 20s · 3 tools · ↓1.5k")

    def test_complete_without_a_count_keeps_the_last_read_and_takes_one_more(self) -> None:
        # Hermes' failure path (`finish_failed`) sends no count, and the tokens of the call that ended the child land
        # in its row just after the frame: the row stays watched long enough for one more read.
        roster = self._roster()
        roster.ingest_tokens({"child-b": 500})
        feed(roster, "complete", 30.0, "sa-b", status="error", duration_seconds=14.0)
        self.assertEqual(roster.agents["sa-b"].output_tokens, 500)
        self.assertEqual(roster.token_sessions(30.0), ("child-a", "child-b"))
        roster.ingest_tokens({"child-b": 750})
        self.assertEqual(roster.agents["sa-b"].output_tokens, 750)
        self.assertEqual(roster.token_sessions(30.0 + TOKEN_SETTLE_SECONDS), ("child-a", "child-b"))
        self.assertEqual(roster.token_sessions(30.0 + TOKEN_SETTLE_SECONDS + 0.5), ("child-a",))
        self.assertEqual(self.row(roster, 2, now=60.0), "  ✗ read the diff for ris…  deepseek-v4.1-flash · 14s · 0 tools · ↓750")
        replayed_roster = replayed()  # the recorded timeout: no read, no count, no token part
        self.assertNotIn("↓", line_text(replayed_roster.list_lines(70, THEME, MAIN_ID, 0, 6, 500.0)[0][2]))

    def test_a_complete_with_a_mistyped_count_gives_none(self) -> None:
        for count in ("340", 3.5, True, -1, 10**12 + 1, None):
            with self.subTest(count=count):
                roster = self._roster()
                feed(roster, "complete", 30.0, "sa-a", status="completed", output_tokens=count)
                self.assertIsNone(roster.agents["sa-a"].output_tokens)
                self.assertIn("child-a", roster.token_sessions(30.0))
        roster = self._roster()
        feed(roster, "complete", 30.0, "sa-a", status="completed", output_tokens=0)  # a child that made no call
        self.assertEqual(roster.token_sessions(30.0), ("child-b",))
        self.assertNotIn("↓", self.row(roster, 1))

    def test_the_log_header_never_parts_a_count_from_its_unit(self) -> None:
        roster = self._roster()
        roster.ingest_tokens({"child-a": 1234})
        def facts(width: int) -> list[str]:  # the status rows: from `running` to the blank row under them
            rows = lines_text(roster.log_lines("sa-a", width, THEME, 20.0))
            start = next(at for at, row in enumerate(rows) if row.startswith("running"))
            return rows[start : rows.index("", start)]

        for width in range(12, 81):
            with self.subTest(width=width):
                self.assertNotIn("↓1.2k\n", "\n".join(facts(width)))
                self.assertFalse([row for row in facts(width) if row.startswith("tokens")], facts(width))
        self.assertEqual(facts(32)[:2], ["running · 10s · 3 tools ·", "↓1.2k\N{NO-BREAK SPACE}tokens ·"])
        self.assertTrue(self.row(roster, 1).endswith(" · ↓1.2k"), "a row is cut, never wrapped, and drops the word")

    def test_counts_are_compact(self) -> None:
        roster = self._roster()
        cases = {950: "↓950", 1000: "↓1k", 1234: "↓1.2k", 456_900: "↓456.9k", 3_000_000: "↓3M"}
        for count, text in cases.items():
            with self.subTest(count=count):
                roster.ingest_tokens({"child-a": count})
                row = self.row(roster, 1, 80)
                self.assertTrue(row.endswith(f"  deepseek-v4.1-flash · 10s · 3 tools · {text}"), row)

    def test_a_waiting_agent_shows_only_its_wait(self) -> None:
        roster = Roster()
        feed(roster, "spawn_requested", 10.0, "sa-q", goal="queued work", child_session_id="child-q")
        roster.ingest_tokens({"child-q": 40})
        self.assertTrue(self.row(roster, 1).endswith("  deepseek-v4.1-flash · waiting 10s"), self.row(roster, 1))

    def test_a_narrowing_row_keeps_the_model_longest(self) -> None:
        # The approved order (#2223 review R2): everything, then no tokens, then the model and the time, then the
        # model alone, then nothing; a figure dropped never comes back as the row narrows.
        roster = self._roster()
        roster.ingest_tokens({"child-a": 1234})
        cases = {
            66: "  ⠋ find usages of o…  deepseek-v4.1-flash · 10s · 3 tools · ↓1.2k",
            60: "  ⠋ find usages of old…  deepseek-v4.1-flash · 10s · 3 tools",
            45: "  ⠋ find usages o…  deepseek-v4.1-flash · 10s",
            40: "  ⠋ find usages of…  deepseek-v4.1-flash",
            35: "  ⠋ find usages of old_api in the …",
            20: "  ⠋ find usages of …",
        }
        for width, text in cases.items():
            with self.subTest(width=width):
                self.assertEqual(line_text(roster.list_lines(width, THEME, MAIN_ID, 0, 6, 20.0)[0][1]), text)
        steps = ("deepseek-v4.1-flash · 10s · 3 tools · ↓1.2k", "deepseek-v4.1-flash · 10s · 3 tools",
                 "deepseek-v4.1-flash · 10s", "deepseek-v4.1-flash", "")
        seen = []
        for width in range(90, -1, -1):
            row = roster.list_lines(width, THEME, MAIN_ID, 0, 6, 20.0)[0][1]
            text = line_text(row)
            with self.subTest(width=width):
                self.assertLessEqual(line_width(row), width)
                right = text.rsplit("  ", 1)[-1] if "  " in text.strip() else ""
                self.assertIn(right, steps, text)
            if not seen or seen[-1] != right:
                seen.append(right)
        self.assertEqual(seen, list(steps))  # each step once, in order


class LogViewTests(unittest.TestCase):
    def _roster(self) -> Roster:
        roster = Roster()
        feed(roster, "start", 10.0, goal="find usages of old_api and list every call site in the tree")
        feed(roster, "thinking", 11.0, text="I will grep for old_api first and then read each file that matches")
        feed(roster, "tool", 12.0, tool_count=1, tool_name="search_files", tool_preview="old_api in src and tests")
        return roster

    def test_the_view_is_header_blank_row_and_log_wrapped_to_the_width(self) -> None:
        self.assertEqual(
            lines_text(self._roster().log_lines(FIRST, 40, THEME, 25.0)),
            [
                "find usages of old_api and list every",
                "call site in the tree",
                "running · 15s · 1 tool ·",
                "deepseek-v4.1-flash",
                "",
                "▸ I will grep for old_api first and then",
                "  read each file that matches",
                "● search_files  old_api in src and tests",
            ],
        )

    def test_the_log_rows_are_wrapped_once_per_change_and_only_the_header_follows_the_clock(self) -> None:
        roster = self._roster()
        first = roster.log_lines(FIRST, 40, THEME, 25.0)
        again = roster.log_lines(FIRST, 40, THEME, 26.0)
        self.assertEqual(lines_text(again)[2], "running · 16s · 1 tool ·")
        self.assertTrue(all(new is old for new, old in zip(again[5:], first[5:], strict=True)))  # not wrapped again
        feed(roster, "tool", 27.0, tool_count=2, tool_name="read_file", tool_preview="src/api.py")
        grown = roster.log_lines(FIRST, 40, THEME, 27.0)
        self.assertEqual(lines_text(grown)[-1], "● read_file  src/api.py")
        narrow = roster.log_lines(FIRST, 30, THEME, 27.0)  # a new width wraps again
        self.assertNotEqual(lines_text(narrow)[5:], lines_text(grown)[5:])
        self.assertTrue(all(line_width(row) <= 30 for row in narrow))
        from omh.tui.theme import theme_named
        amber = theme_named("amber")
        self.assertEqual(style_of(roster.log_lines(FIRST, 40, THEME, 27.0)[-1], "read_file"), kind_style("read_file", THEME))
        self.assertEqual(style_of(roster.log_lines(FIRST, 40, amber, 27.0)[-1], "read_file"), kind_style("read_file", amber))
        roster.ingest_tail(FIRST, "replaced by the tail\n")
        self.assertEqual(lines_text(roster.log_lines(FIRST, 40, THEME, 28.0))[-1], "replaced by the tail")

    def test_the_view_uses_the_theme_roles(self) -> None:
        rows = self._roster().log_lines(FIRST, 120, THEME, 25.0)
        self.assertEqual(style_of(rows[0], "find usages"), THEME.running)  # the goal in the agent's own state
        self.assertEqual(style_of(rows[1], "running"), THEME.running)
        self.assertEqual(style_of(rows[1], "15s"), THEME.muted)
        self.assertEqual(rows[2], ())
        self.assertEqual(style_of(rows[3], "▸"), THEME.muted)
        self.assertEqual(style_of(rows[3], "I will grep"), THEME.thinking)
        self.assertEqual(style_of(rows[4], "●"), THEME.dim)  # the log keeps no outcome: a neutral mark
        self.assertEqual(style_of(rows[4], "search_files"), kind_style("search_files", THEME))  # the file hue
        self.assertEqual(style_of(rows[4], "old_api in src"), THEME.muted)

    def test_the_status_word_takes_the_colour_of_its_glyph(self) -> None:
        for status, style in (("failed", THEME.error), ("completed", THEME.muted), ("interrupted", THEME.muted)):
            with self.subTest(status=status):
                roster = self._roster()
                feed(roster, "complete", 30.0, status=status, summary="the reply")
                rows = roster.log_lines(FIRST, 120, THEME, 99.0)
                self.assertEqual(line_text(rows[1]), f"{status} · 20s · 1 tool · deepseek-v4.1-flash")
                self.assertEqual(style_of(rows[1], status), style)
                self.assertEqual((line_text(rows[-1]), style_of(rows[-1], "the reply")), ("the reply", THEME.text))

    def test_an_agent_with_no_output_says_so(self) -> None:
        roster = Roster()
        feed(roster, "start", goal="review", model="")
        rows = roster.log_lines(FIRST, 40, THEME, 3.0)
        self.assertEqual(lines_text(rows), ["review", "running · 3s · 0 tools", "", "no output yet"])
        self.assertEqual(style_of(rows[3], "no output"), THEME.muted)

    def test_an_id_the_roster_does_not_hold_has_no_view(self) -> None:
        roster = self._roster()
        self.assertEqual(roster.log_lines("sa-gone", 40, THEME, 0.0), [])
        self.assertEqual(roster.log_lines(MAIN_ID, 40, THEME, 0.0), [])

    def test_no_row_exceeds_the_width(self) -> None:
        roster = self._roster()
        feed(roster, "tool", 13.0, tool_name="한글도구", tool_preview="가나다라마바사 🚀 아자차카타파하")
        feed(roster, "complete", 14.0, summary="결과: 세 파일에서 호출됨 🚀\n- src/api/client.py")
        for _ in range(LOG_ROW_CAP):
            feed(roster, "thinking")  # ignored: the agent finished
        for width in range(4, 60):
            for row in roster.log_lines(FIRST, width, THEME, 20.0):
                self.assertLessEqual(line_width(row), width)
        # Narrower than a prefix and a 2-cell glyph, `wrap` gives that glyph a row of its own.
        for width in range(-2, 4):
            for row in roster.log_lines(FIRST, width, THEME, 20.0):
                self.assertLessEqual(line_width(row), 4)


class IngestTailTests(unittest.TestCase):
    TAIL = "12:00:01 tool     | -> read_file(a.py)\n12:00:02 result   | read_file ok 0.1s: def a()\n"

    def test_a_tail_seeds_an_empty_log(self) -> None:
        roster = started(FIRST)
        roster.ingest_tail(FIRST, self.TAIL)
        self.assertEqual(
            log_rows(roster),
            [("text", "12:00:01 tool     | -> read_file(a.py)", ""), ("text", "12:00:02 result   | read_file ok 0.1s: def a()", "")],
        )
        self.assertEqual((roster.agents[FIRST].dropped, roster.agents[FIRST].tail_cut), (0, False))

    def test_a_tail_replaces_what_the_events_accumulated(self) -> None:
        roster = started(FIRST)
        for index in range(LOG_ROW_CAP + 5):
            feed(roster, "thinking", text=f"row {index}")
        roster.ingest_tail(FIRST, "only line")
        agent = roster.agents[FIRST]
        self.assertEqual((log_rows(roster), agent.dropped), ([("text", "only line", "")], 0))
        self.assertEqual(lines_text(roster.log_lines(FIRST, 60, THEME, 0.0))[3:], ["only line"])

    def test_events_after_a_tail_append_to_it(self) -> None:
        roster = started(FIRST)
        roster.ingest_tail(FIRST, "from the tail")
        feed(roster, "tool", tool_name="terminal")
        self.assertEqual(log_rows(roster), [("text", "from the tail", ""), ("tool", "terminal", "")])

    def test_a_cut_tail_loses_its_partial_first_line_and_the_view_says_so(self) -> None:
        roster = started(FIRST)
        roster.ingest_tail(FIRST, "ult   | half a line\n" + self.TAIL, truncated=True)
        self.assertEqual(len(roster.agents[FIRST].log), 2)
        self.assertEqual(roster.agents[FIRST].log[0].text, "12:00:01 tool     | -> read_file(a.py)")
        view = lines_text(roster.log_lines(FIRST, 80, THEME, 0.0))
        self.assertEqual(view[3:5], ["… earlier output not shown", "12:00:01 tool     | -> read_file(a.py)"])

    def test_only_a_true_flag_counts_as_cut(self) -> None:
        for flag in (False, None, "false", 1, "true"):
            with self.subTest(flag=flag):
                roster = started(FIRST)
                roster.ingest_tail(FIRST, "first\nsecond", truncated=flag)  # type: ignore[arg-type]
                self.assertEqual((len(roster.agents[FIRST].log), roster.agents[FIRST].tail_cut), (2, False))

    def test_a_whole_tail_after_a_cut_one_clears_the_notice(self) -> None:
        roster = started(FIRST)
        roster.ingest_tail(FIRST, "half\nwhole", truncated=True)
        self.assertTrue(roster.agents[FIRST].tail_cut)
        roster.ingest_tail(FIRST, "all of it")
        self.assertFalse(roster.agents[FIRST].tail_cut)
        self.assertEqual(lines_text(roster.log_lines(FIRST, 80, THEME, 0.0))[3:], ["all of it"])

    def test_a_tail_longer_than_the_log_keeps_its_last_rows_and_counts_the_rest(self) -> None:
        roster = started(FIRST)
        roster.ingest_tail(FIRST, "\n".join(f"line {index}" for index in range(LOG_ROW_CAP + 12)))
        agent = roster.agents[FIRST]
        self.assertEqual((len(agent.log), agent.dropped, agent.log[0].text, agent.log[-1].text), (400, 12, "line 12", "line 411"))
        self.assertEqual(lines_text(roster.log_lines(FIRST, 80, THEME, 0.0))[3], "… 12 earlier rows dropped")
        feed(roster, "tool", tool_name="terminal")
        self.assertEqual((len(agent.log), agent.dropped, agent.log[0].text), (400, 13, "line 13"))

    def test_a_cut_tail_longer_than_the_log_says_only_that_earlier_output_is_missing(self) -> None:
        # The gateway cut it first, so the rows the cap dropped are not all that is missing: no number.
        roster = started(FIRST)
        roster.ingest_tail(FIRST, "\n".join(f"line {index}" for index in range(LOG_ROW_CAP + 12)), truncated=True)
        agent = roster.agents[FIRST]
        self.assertEqual((len(agent.log), agent.dropped, agent.tail_cut), (400, 11, True))
        view = lines_text(roster.log_lines(FIRST, 80, THEME, 0.0))
        self.assertEqual(view[3:5], ["… earlier output not shown", "line 12"])
        self.assertEqual(len(view), 3 + 1 + 400)

    def test_only_the_last_characters_of_an_oversized_tail_are_read(self) -> None:
        # 300 lines of 199 characters: the last 32768 characters open inside line 136, so 137 is the first whole one.
        roster = started(FIRST)
        roster.ingest_tail(FIRST, "\n".join(f"{index:04d}" + "z" * 195 for index in range(300)))
        agent = roster.agents[FIRST]
        self.assertEqual((len(agent.log), agent.dropped, agent.tail_cut), (163, 0, True))
        self.assertEqual((agent.log[0].text[:4], agent.log[-1].text[:4]), ("0137", "0299"))

    def test_a_tail_past_the_character_bound_keeps_its_end_and_counts_as_cut(self) -> None:
        self.assertEqual(TAIL_CHARS, 32768)
        roster = started(FIRST)
        roster.ingest_tail(FIRST, "x" * 40000 + "\nkept line\nlast line")
        self.assertEqual(log_rows(roster), [("text", "kept line", ""), ("text", "last line", "")])
        self.assertTrue(roster.agents[FIRST].tail_cut)
        whole = "a" * (TAIL_CHARS - 5) + "\nend"
        self.assertEqual(len(whole), TAIL_CHARS - 1)
        roster.ingest_tail(FIRST, whole + "!")
        self.assertEqual(([row.text for row in roster.agents[FIRST].log][1], roster.agents[FIRST].tail_cut), ("end!", False))

    def test_a_long_tail_line_is_cut_and_marked(self) -> None:
        roster = started(FIRST)
        roster.ingest_tail(FIRST, "y" * 601 + "\n" + "z" * 600)
        self.assertEqual([row.text for row in roster.agents[FIRST].log], ["y" * 600 + "…", "z" * 600])

    def test_a_tail_with_no_line_keeps_the_log_it_would_have_replaced(self) -> None:
        for empty in ("", "\n\n", "   \n\t\n", f"{ESC}[0m\n"):
            with self.subTest(empty=empty):
                roster = started(FIRST)
                feed(roster, "thinking", text="kept")
                roster.ingest_tail(FIRST, empty)
                roster.ingest_tail(FIRST, "half a line only", truncated=True)
                self.assertEqual((log_rows(roster), roster.agents[FIRST].tail_cut), ([("thinking", "kept", "")], False))

    def test_a_late_tail_never_replaces_a_finished_agents_log(self) -> None:
        for status in ("completed", "failed", "interrupted"):
            with self.subTest(status=status):
                roster = started(FIRST)
                feed(roster, "complete", 1.0, status=status, summary="the reply")
                roster.ingest_tail(FIRST, self.TAIL)
                self.assertEqual(log_rows(roster), [("text", "the reply", "")])
                self.assertFalse(roster.agents[FIRST].tail_cut)

    def test_a_finished_agent_with_an_empty_log_takes_a_tail(self) -> None:
        roster = started(FIRST)
        feed(roster, "complete", 1.0, summary="")
        self.assertEqual(log_rows(roster), [])
        roster.ingest_tail(FIRST, "only line")
        self.assertEqual(log_rows(roster), [("text", "only line", "")])
        roster.ingest_tail(FIRST, "a later tail")  # and once it holds that, it is frozen too
        self.assertEqual(log_rows(roster), [("text", "only line", "")])

    def test_an_unknown_id_or_a_tail_that_is_not_text_changes_nothing(self) -> None:
        roster = started(FIRST)
        feed(roster, "thinking", text="kept")
        roster.ingest_tail("sa-gone", self.TAIL)
        roster.ingest_tail(MAIN_ID, self.TAIL)
        for bad in (None, 5, ["line"], {"text": "line"}, b"line"):
            roster.ingest_tail(FIRST, bad)  # type: ignore[arg-type]
        self.assertEqual((list(roster.agents), log_rows(roster)), ([FIRST], [("thinking", "kept", "")]))


if __name__ == "__main__":
    unittest.main()

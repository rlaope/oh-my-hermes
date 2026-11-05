"""The subagent roster in the OMH TUI's loop: which events feed it, what empties it, and the agent view it draws.

Every case drives an `App` over the recording client from `test_tui_modes`.
The subagent frames are the ones Hermes 6c61c3e27d built
(`tests/fixtures/tui_gateway/subagent_relay.jsonl`, replayed whole or up to a
point), re-addressed to the app's live session; a case that needs a frame the
recording does not hold builds it from the recorded identity keys with
`test_tui_subagents.payload`. What is on screen is read back from the VT
screen the scripted terminal paints into.

The agent view stands under the info line (the owner's call of 2026-10-21),
so the info line is no longer the screen's last row that is not blank while
there are agents: `view_rows` counts the rows under it.
"""

from __future__ import annotations

import re
import unittest
from unittest import mock

from _tui_lines import badge_text, line_text, RULE_ROW, without_badge
from test_tui_app import info_index
from test_tui_modes import SID, RecordingClient, answer, drawn, make_app, show_mode, type_text
from test_tui_subagents import FIRST, FRAMES, SECOND, cells, payload
from omh.tui.app import App
from omh.tui.layout import AGENT_VIEW_ROWS, agent_view_cap
from omh.tui.modes import chip_column, info_line, mode_label
from omh.tui.frame import BROWSING_HINT, INFO_INSET as INFO_INSET_CELLS, MODE_ACCEPT, MODE_NORMAL, MODE_PLAN
from omh.tui.gateway import Event, ServerRequest
from omh.tui.keys import BACKSPACE, CHAR, ENTER, Key
from omh.tui.panels import SPINNER_FRAMES
from omh.tui.style import Span
from omh.tui.subagents import Roster
from omh.tui.theme import DEFAULT_THEME
from omh.tui.transcript import AGENT_FAILED, AGENT_FINISHED, AgentDoneBlock, NoticeBlock
from omh.tui.width import line_width

STARTS = FRAMES[:2]  # both recorded agents started, neither finished
SPIN = SPINNER_FRAMES[0]  # a clock at 0 draws the spinner's first frame
CHIP = "2 agents · ↓ agents"
# Each agent row: its short title, then the model it runs on leading its figures (the rail and kind colours,
# 2026-10-22: "어떤 모델로 들어갔는지도 안보이고"), the title cut first where the row is narrow.
VIEW = [
    "  ● main",
    f"  {SPIN} find usages of old_api in src/ and list…  deepseek-v4.1-flash · 0s · 0 tools",
    f"  {SPIN} read the diff for risks                   deepseek-v4.1-flash · 0s · 0 tools",
]


def relay(app: App, frames: list[tuple[str, dict[str, object]]] = FRAMES, session_id: str = SID) -> None:
    """Hermes' recorded subagent frames, as events of `session_id`."""
    for event_type, frame in frames:
        app._on_event(Event(event_type, session_id, frame))


def agent_event(app: App, kind: str, subagent_id: str = FIRST, **changes: object) -> None:
    app._on_event(Event(f"subagent.{kind}", SID, payload(subagent_id, **changes)))


def agent_app(*, busy: bool = True, frames: list[tuple[str, dict[str, object]]] = STARTS, **options: object) -> tuple[App, RecordingClient]:
    """An app at clock 0 whose live session has the recorded agents running."""
    options.setdefault("clock", lambda: 0.0)
    app, client = make_app(busy=busy, **options)
    relay(app, frames)
    return app, client


def view_rows(app: App) -> int:
    """How many rows the agent view under the info line takes now, as a fresh frame gives them (none on a terminal
    too small for it)."""
    drawn(app)
    return app.frame_budget.agents


def screen_info_index(app: App, screen: list[str]) -> int:
    """The info line's row on `screen`: the region's last row (where the region knows it, else the screen's last row
    that is not blank), less the agent view's rows under it, blank ones included."""
    rows = view_rows(app)
    last = app.region.last_row(app.size[1])
    return (info_index(screen) if last is None else last) - rows


def mode_row(app: App) -> str:
    """The info line, drawn afresh: the row over the agent view, which is the region's last rows."""
    screen = drawn(app)
    return screen[screen_info_index(app, screen)]


def view_text(app: App) -> list[str]:
    """The agent view's rows as drawn, under the info line."""
    screen = drawn(app)
    info = screen_info_index(app, screen)
    return screen[info + 1 : info + 1 + view_rows(app)]


def info_text(app: App) -> str:
    """The info line after the inset it starts with under the composer, and after its badge (`without_badge`)."""
    row = without_badge(mode_row(app))
    if not row.startswith(" " * INFO_INSET_CELLS):
        raise AssertionError(f"the info line does not start {INFO_INSET_CELLS} cells in: {row!r}")
    return row[INFO_INSET_CELLS:]


def info_left(app: App) -> str:
    """The info line's left side, after its inset: its right side (model, context, effort) stands 3 cells or more
    away."""
    return re.split(r" {3,}", info_text(app))[0]


class BidiControlTests(unittest.TestCase):
    """Bidi embeddings and overrides in gateway text never reach the terminal, so what is drawn is what was measured."""

    BIDI = "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"

    def test_the_views_cells_match_the_screen_with_bidi_controls_in_the_goals(self) -> None:
        app, _client = make_app(busy=True, clock=lambda: 0.0, cols=120)
        agent_event(app, "start", FIRST, goal=f"\u202efind usages{self.BIDI} of old_api")
        second_goal = "read\u2067 the diff\u2069 for risks"
        agent_event(app, "start", SECOND, goal=second_goal)
        agent_event(app, "tool", SECOND, goal=second_goal, tool_name="read\u202e_file", tool_preview="\u2066a.py")
        rows = view_text(app)
        writes = "".join(app.terminal.writes)  # type: ignore[attr-defined]
        self.assertFalse(any(ch in writes for ch in self.BIDI))
        self.assertTrue(rows[1].startswith(f"  {SPIN} find usages of old_api  "), rows)
        self.assertTrue(rows[2].startswith(f"  {SPIN} read the diff for risks  "), rows)
        self.assertTrue(all(len(row) == 120 for row in rows[1:]), "every cell measured is a cell drawn")
        self.assertEqual(app.roster.agents[SECOND].last_tool, "read_file")

    def test_an_approvals_command_row_shows_the_command_in_the_order_it_runs(self) -> None:
        app, _client = make_app()
        command = "echo safe \u202e~ fr- mr ;\u202c done"
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": command, "description": "\u2066rm\u2069"}))
        screen = drawn(app)
        writes = "".join(app.terminal.writes)  # type: ignore[attr-defined]
        self.assertFalse(any(ch in writes for ch in self.BIDI))
        # The `;` is a separator whatever the controls around it draw: each command on a row of its own, in order.
        rows = [line.strip("▌ ") for line in screen]
        self.assertEqual(rows[rows.index("echo safe ~ fr- mr") + 1], "done", screen)


class RosterFeedTests(unittest.TestCase):
    def test_every_subagent_event_of_the_live_session_is_folded(self) -> None:
        app, _client = make_app()
        relay(app)
        self.assertEqual(list(app.roster.agents), [FIRST, SECOND])
        first, second = app.roster.agents[FIRST], app.roster.agents[SECOND]
        self.assertEqual((first.status, first.tool_count, first.last_tool), ("completed", 6, "read_file"))
        self.assertEqual((second.status, second.duration), ("timeout", 30.0))
        self.assertEqual(len(first.log), 11)  # one thinking line, six tool calls, the four lines of the reply

    def test_the_fold_is_the_rosters_own(self) -> None:
        # Nothing between the event and `Roster.apply`: the app's roster is what the roster alone would hold.
        app, _client = make_app(clock=lambda: 7.0)
        relay(app)
        alone = Roster()
        for event_type, frame in FRAMES:
            alone.apply(event_type, frame, 7.0)
        self.assertEqual(app.roster.agents, alone.agents)

    def test_events_of_another_session_are_dropped(self) -> None:
        app, _client = make_app()
        relay(app, session_id="someone-else")
        relay(app, session_id="")
        app._on_event(Event(FRAMES[0][0], None, FRAMES[0][1]))
        self.assertEqual(app.roster.agents, {})

    def test_a_subagent_event_adds_to_the_transcript_only_the_briefing_of_an_agent_it_finished(self) -> None:
        app, _client = make_app()
        relay(app, [frame for frame in FRAMES if frame[0] != "subagent.complete"])
        self.assertEqual(app.transcript.blocks, [])
        relay(app)  # the recording's completes: one per agent finished, the second agent's repeated one ignored
        self.assertEqual([(type(block), block.outcome) for block in app.transcript.blocks],
                         [(AgentDoneBlock, AGENT_FINISHED), (AgentDoneBlock, AGENT_FAILED)])

    def test_a_payload_that_is_not_a_subagents_never_raises_into_the_loop(self) -> None:
        app, _client = make_app(busy=True)
        junk: list[object] = [
            None, [], "text", 7, {}, {"subagent_id": 5}, {"subagent_id": ""}, {"subagent_id": "x" * 500},
            {"subagent_id": FIRST, "goal": ["not", "text"], "tool_count": "many", "model": {"a": 1}},
            {"subagent_id": FIRST, "status": 5, "duration_seconds": float("nan"), "summary": b"bytes"},
            {"subagent_id": FIRST, "tool_name": None, "tool_preview": {"deep": [1, 2]}, "text": 3.5},
        ]
        for kind in ("start", "thinking", "tool", "progress", "complete", "spawn_requested", "text", "", "unknown.kind"):
            for frame in junk:
                app._on_event(Event(f"subagent.{kind}", SID, frame))  # type: ignore[arg-type]
                drawn(app)  # and whatever it left behind still draws
        self.assertLessEqual(set(app.roster.agents), {FIRST})
        self.assertFalse([block for block in app.transcript.blocks if isinstance(block, NoticeBlock)])


class RosterClearTests(unittest.TestCase):
    def test_a_prompt_that_starts_a_turn_empties_the_roster(self) -> None:
        app, client = agent_app(busy=False)
        type_text(app, "the next task")
        self.assertEqual(len(app.roster.agents), 2)  # typing alone changes nothing
        app._on_input(Key(ENTER))
        self.assertEqual(client.named("prompt.submit"), [{"session_id": SID, "text": "the next task"}])
        self.assertEqual(app.roster.agents, {})

    def test_a_prompt_queued_behind_the_running_turn_keeps_the_agents_until_it_is_sent(self) -> None:
        app, client = agent_app(busy=True)
        type_text(app, "after this")
        app._on_input(Key(ENTER))
        self.assertEqual(client.named("prompt.submit"), [])
        self.assertEqual(len(app.roster.agents), 2)
        app._on_event(Event("message.complete", SID, {"text": "done"}))  # the turn ends: the queue drains
        self.assertEqual(client.named("prompt.submit"), [{"session_id": SID, "text": "after this", "queued": True}])
        self.assertEqual(app.roster.agents, {})

    def test_a_local_command_and_a_steer_start_no_turn_and_keep_the_agents(self) -> None:
        app, client = agent_app(busy=True)
        for typed in ("/queue", "/steer look at the tests too"):
            type_text(app, typed)
            app._on_input(Key(ENTER))
        self.assertEqual(client.named("session.steer"), [{"session_id": SID, "text": "look at the tests too"}])
        self.assertEqual(len(app.roster.agents), 2)

    def test_a_new_session_empties_the_roster(self) -> None:
        app, client = agent_app(busy=False)
        type_text(app, "/new")
        app._on_input(Key(ENTER))
        self.assertEqual(len(app.roster.agents), 2)  # still this session until Hermes opened the next
        answer(app, client, {"session_id": "live-2", "stored_session_id": "stored-2", "info": {}})
        self.assertEqual(app.roster.agents, {})

    def test_switching_sessions_empties_the_roster(self) -> None:
        app, client = agent_app(busy=False)
        type_text(app, "/sessions another-stored-id")
        app._on_input(Key(ENTER))
        answer(app, client, {"session_id": "live-3", "stored_session_id": "another-stored-id", "info": {}, "messages": []})
        self.assertEqual(app.roster.agents, {})

    def test_a_session_that_could_not_be_opened_keeps_the_agents(self) -> None:
        app, client = agent_app(busy=False)
        type_text(app, "/new")
        app._on_input(Key(ENTER))
        answer(app, client, error={"code": 5000, "message": "no room"})
        self.assertEqual(len(app.roster.agents), 2)

    def test_an_agent_that_reports_after_the_roster_was_emptied_comes_back(self) -> None:
        app, _client = agent_app(busy=False)
        type_text(app, "next")
        app._on_input(Key(ENTER))
        agent_event(app, "tool", SECOND, tool_name="read_file", tool_count=1)
        self.assertEqual(list(app.roster.agents), [SECOND])


class ViewTests(unittest.TestCase):
    def test_the_view_joins_under_the_info_line_with_the_first_agent_and_leaves_with_the_next_prompt(self) -> None:
        app, _client = make_app(busy=True, cols=80, clock=lambda: 0.0)
        self.assertEqual((info_left(app), view_rows(app)), ("", 0))  # the line names no key while a turn runs
        relay(app, STARTS[:1])
        self.assertEqual(info_left(app), "1 agent · ↓ agents")
        self.assertEqual(view_text(app), VIEW[:2])
        relay(app, STARTS[1:])
        self.assertEqual(info_left(app), CHIP)
        self.assertEqual(view_text(app), VIEW)
        app.turn_pending = False
        type_text(app, "next")
        app._on_input(Key(ENTER))
        self.assertEqual((info_left(app), view_rows(app)), ("", 0))

    def test_composer_then_info_line_then_the_view_with_the_plan_above_the_composer(self) -> None:
        from test_tui_panels import hud_payload
        from omh.tui.panels import HudSnapshot

        app, _client = agent_app()
        app.hud = HudSnapshot(app.stored_id, hud_payload([{"text": "Ship it", "state": "active"}]), 0.0)
        screen = drawn(app)
        top = next(index for index, row in enumerate(screen) if row.startswith(RULE_ROW))
        info = screen_info_index(app, screen)
        self.assertTrue(screen[top - 3].startswith("[Plan]"), screen)
        self.assertEqual(screen[top - 2].strip(), "[•] Ship it")
        self.assertEqual(screen[top - 1], "", "a blank row between the plan and the rule")
        self.assertEqual(screen[top - 4], "", "and one between the tip and the plan")
        self.assertTrue(screen[top + 1].startswith("❯ ") and screen[top + 2].startswith(RULE_ROW), screen)
        self.assertEqual(info, top + 3)
        self.assertEqual(screen[info + 1 :], [*VIEW, *[""] * (len(screen) - info - 1 - len(VIEW))])

    def test_a_finished_turn_keeps_its_view_with_each_agents_verdict(self) -> None:
        app, _client = agent_app(busy=False, frames=FRAMES, cols=80)
        self.assertEqual(info_left(app), CHIP)
        rows = view_text(app)
        self.assertEqual([row[:4] for row in rows], ["  ● ", "  ✓ ", "  ✗ "])

    def test_a_narrow_row_drops_the_right_side_and_keeps_the_count_whole(self) -> None:
        patched = mock.patch("omh.tui.app.__version__", "9.9.9")  # the badge's version, fixed: the gap is a width
        patched.start()
        self.addCleanup(patched.stop)
        app, _client = agent_app()
        self.assertEqual(info_text(app).rstrip(), CHIP + " " * 23 + "ctrl+t effort")
        narrow, _client = agent_app(cols=30)
        self.assertEqual(info_text(narrow), CHIP)

    def test_the_spinner_turns_with_the_clock(self) -> None:
        now = [0.0]
        app, _client = agent_app(clock=lambda: now[0])
        now[0] = 0.25  # two ticks of a tenth of a second on
        self.assertTrue(view_text(app)[1].startswith(f"  {SPINNER_FRAMES[2]} find usages of"))

    def test_the_mode_label_comes_first_then_the_count_then_the_hints(self) -> None:
        expected = {
            MODE_NORMAL: CHIP,
            MODE_ACCEPT: f"⏵⏵ accept all on · {CHIP} · (⇧⇥ plan)",  # approvals Hermes turned off itself
            MODE_PLAN: f"⏸ plan mode on · {CHIP} · (⇧⇥ to cycle)",
        }
        for mode, row in expected.items():
            with self.subTest(mode=mode):
                app, _client = agent_app(cols=120)
                show_mode(app, mode)
                self.assertEqual(info_left(app), row)

    def test_the_right_side_stays_while_the_count_leaves_it_room(self) -> None:
        app, _client = agent_app(cols=120)
        app.effort = "high"
        row = info_text(app)
        self.assertTrue(row.startswith(CHIP), row)
        self.assertTrue(row.endswith("effort high"), row)
        self.assertEqual(len(mode_row(app)), 120)  # after its inset, to the last cell

    def test_cut_short_the_right_side_goes_first_then_the_hint_and_never_the_label(self) -> None:
        label = "⏵⏵ accept all on"
        right = ((Span("effort xhigh", DEFAULT_THEME.muted),),)
        hint = "(⇧⇥ to cycle)"
        def row_at(width: int) -> str:
            # As `App._agent_chip` sizes it: whole, else the count alone, in the room after the label.
            room = width - chip_column(MODE_ACCEPT, DEFAULT_THEME)
            said = next((form for form in (CHIP, "2 agents") if len(form) <= room), "")
            chip = (Span(said, DEFAULT_THEME.hint),) if said else ()
            return line_text(
                info_line(mode=MODE_ACCEPT, width=width,
                          theme=DEFAULT_THEME, chip=chip, right=right)
            )

        for width in range(10, 170):
            row = row_at(width)
            with self.subTest(width=width):
                self.assertLessEqual(len(row), width)
                self.assertTrue(row.startswith(label if width >= len(label) else "⏵⏵ accept"), row)
                if len(f"{label} · {CHIP}") <= width:
                    self.assertTrue(row.startswith(f"{label} · {CHIP}"), row)  # whole before a cell goes to the rest
                elif len(f"{label} · 2 agents") <= width:
                    self.assertTrue(row.startswith(f"{label} · 2 agents"), row)  # then the count alone
                if "effort" in row:
                    self.assertTrue(row.endswith("effort xhigh"), row)
        full = f"{label} · {CHIP} · {hint}"
        rows = {width: row_at(width) for width in (len(full) + 15, len(full) + 14, len(full))}
        self.assertEqual(rows, {
            len(full) + 15: f"{full}   effort xhigh",
            len(full) + 14: full,
            len(full): full,
        })

    def test_the_count_starts_right_after_the_label_and_at_the_edge_without_one(self) -> None:
        self.assertEqual(chip_column(MODE_NORMAL, DEFAULT_THEME), 0)
        for mode in (MODE_ACCEPT, MODE_PLAN):
            with self.subTest(mode=mode):
                label = mode_label(mode, DEFAULT_THEME)
                self.assertEqual(chip_column(mode, DEFAULT_THEME), line_width(label) + 3)
                app, _client = agent_app(cols=120)
                show_mode(app, mode)
                start = INFO_INSET_CELLS + chip_column(mode, DEFAULT_THEME)
                self.assertEqual(cells(without_badge(mode_row(app)), start, start + len(CHIP)), CHIP)
        self.assertEqual(mode_label(MODE_NORMAL, DEFAULT_THEME), ())

    def test_a_count_with_no_room_for_what_down_opens_says_the_count_alone(self) -> None:
        app, _client = agent_app(cols=20)  # 18 cells after the inset: one short of the count whole
        self.assertTrue(info_text(app).startswith("2 agents"), info_text(app))
        self.assertNotIn("↓", info_text(app))
        self.assertEqual(app._agent_chip(8), (Span("2 agents", DEFAULT_THEME.hint),))
        self.assertEqual(app._agent_chip(7), ())

    def test_the_view_is_under_the_info_line_wherever_the_agent_list_can_open(self) -> None:
        # Two rows from 6 rows (a quarter, raised by the running agents up to a third), the whole view from 9.
        # A turn runs, so the tail keeps its working row: from 6 and 7 rows that leaves the view one row, the count;
        # from 9 rows the whole view.
        collapsed = ["  +2 more · 2 running"]
        for rows, view in ((6, collapsed), (7, collapsed), (9, VIEW), (10, VIEW), (24, VIEW)):
            with self.subTest(rows=rows):
                app, _client = agent_app(rows=rows)
                self.assertEqual(view_text(app), view)
                self.assertTrue([row for row in drawn(app) if "Working" in row], "the working row stays")
                self.assertTrue(app._list_available())
        for rows, cols in ((5, 80), (24, 19)):  # too small: no view, and no list to open; the count stays
            with self.subTest(rows=rows, cols=cols):
                app, _client = agent_app(rows=rows, cols=cols)
                self.assertEqual(view_rows(app), 0)
                self.assertNotIn("● main", "\n".join(drawn(app)))
                self.assertFalse(app._list_available())
                self.assertNotIn("↓", mode_row(app))

    def test_an_open_question_keeps_the_count_on_the_info_line_and_the_view_under_it(self) -> None:
        from omh.tui.gateway import ServerRequest

        app, _client = agent_app(cols=80)
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        # Down moves the approval's choice there, so the count does not offer the list.
        self.assertTrue(info_text(app).startswith("2 agents · ↑↓ pick · enter confirms"), info_text(app))
        self.assertEqual(view_text(app), VIEW)
        for kind, frame in (("clarify", {"questions": [{"qid": "q1", "question": "Which file?"}]}), ("vault.code", {})):
            with self.subTest(question=kind):
                asked, _client = agent_app(cols=80)
                asked._on_server_request(ServerRequest("srq-2", kind, frame))
                self.assertFalse(asked._list_available())
                self.assertNotIn("↓ agents", info_text(asked))

    def test_typing_keeps_the_count_and_the_view_and_takes_away_what_down_would_not_open(self) -> None:
        # The hint after it may change (a draft takes Esc from the interrupt); the count and the view do not. Down
        # walks the input history while the composer holds text, so `↓ agents` goes until it is empty again.
        app, _client = agent_app()
        view = view_text(app)
        self.assertTrue(info_text(app).startswith(CHIP), info_text(app))
        for char in "what are they doing":
            app._on_input(Key(CHAR, char))
        self.assertTrue(info_text(app).startswith("2 agents"), info_text(app))
        self.assertNotIn("↓ agents", info_text(app))
        self.assertEqual(view_text(app), view)
        app._set_composer("")
        self.assertTrue(info_text(app).startswith(CHIP), info_text(app))


class TokenTests(unittest.TestCase):
    """The view's token figures: the poller is told which child sessions to read, and each snapshot's counts land on
    their agents' rows."""

    def snapshot(self, app: App, counts: dict[str, int], session: str | None = None) -> None:
        from omh.tui.panels import HudSnapshot

        snapshot = HudSnapshot(app.stored_id if session is None else session, {"privacy": "metadata_only"}, 0.0, counts)
        app.poller.take = lambda: snapshot  # type: ignore[method-assign]
        app._take_hud()

    def test_the_running_agents_are_watched_and_a_snapshots_counts_reach_their_rows(self) -> None:
        app, _client = agent_app()
        app._take_hud()
        self.assertEqual(app.poller.watched, ("child-session-0", "child-session-1"))
        self.snapshot(app, {"child-session-0": 1234})
        rows = view_text(app)
        self.assertEqual(rows[1], f"  {SPIN} find usages of old_api in src/ …  deepseek-v4.1-flash · 0s · 0 tools · ↓1.2k")
        self.assertEqual(rows[2], VIEW[2], "no count yet: no token part")

    def test_a_snapshot_of_another_session_brings_no_counts(self) -> None:
        app, _client = agent_app()
        self.snapshot(app, {"child-session-0": 1234}, session="another-session")
        self.assertEqual(view_text(app), VIEW)

    def test_a_finished_agents_count_is_its_completes_and_it_leaves_the_watch(self) -> None:
        app, _client = agent_app(frames=FRAMES)  # the first completes with 340 output tokens, the second times out
        app._take_hud()
        self.assertEqual(app.poller.watched, ("child-session-1",), "the timed-out one is read once more")
        self.snapshot(app, {"child-session-0": 999, "child-session-1": 75})
        rows = view_text(app)
        self.assertTrue(rows[1].endswith("12s · 6 tools · ↓340"), rows[1])
        self.assertTrue(rows[2].endswith("30s · 0 tools · ↓75"), rows[2])

    def test_a_complete_that_comes_before_its_last_calls_tokens_still_settles_on_the_final_count(self) -> None:
        # Measured against Hermes d923a5eb48: `subagent.complete` can arrive before the delta of the child's last
        # call lands in its state.db row, so a read taken just after the frame can still miss that call.
        clock = [0.0]
        app, _client = agent_app(clock=lambda: clock[0])
        self.snapshot(app, {"child-session-0": 1000, "child-session-1": 500})
        # Success: complete's own count is final, whatever a read taken before the last delta landed says.
        agent_event(app, "complete", FIRST, status="completed", duration_seconds=12.0, output_tokens=1500)
        self.snapshot(app, {"child-session-0": 1300, "child-session-1": 500})
        self.assertTrue(view_text(app)[1].endswith("12s · 0 tools · ↓1.5k"), view_text(app)[1])
        # Hermes' failure path sends no count: the row keeps being read, and the read after the last delta settles it.
        clock[0] = 20.0
        agent_event(app, "complete", SECOND, status="error", duration_seconds=20.0, child_session_id="child-session-1")
        self.assertTrue(view_text(app)[2].endswith("20s · 0 tools · ↓500"), view_text(app)[2])
        self.snapshot(app, {"child-session-0": 1500, "child-session-1": 750})
        self.assertEqual(app.poller.watched, ("child-session-1",))
        self.assertTrue(view_text(app)[2].endswith("20s · 0 tools · ↓750"), view_text(app)[2])
        clock[0] = 31.0  # past the settle window: the finished row is no longer read
        app._take_hud()
        self.assertEqual(app.poller.watched, ())
        self.assertTrue(view_text(app)[2].endswith("20s · 0 tools · ↓750"))


if __name__ == "__main__":
    unittest.main()


class OneAgentSurfaceTests(unittest.TestCase):
    """The roster (view, list) is the one agent surface: the HUD's agents block steps aside while it holds agents, and
    neither is ever drawn above the composer."""

    def hud(self, app: App) -> None:
        from test_tui_panels import agent_row, hud_payload, with_agents
        from omh.tui.panels import HudSnapshot

        payload = with_agents(hud_payload([{"text": "Ship it", "state": "active"}]), [agent_row(0), agent_row(1)])
        app.hud = HudSnapshot(app.stored_id, payload, 0.0)

    def slot(self, app: App) -> list[str]:
        return [line_text(line) for line in app._slot_lines(80, 30)]

    def test_the_agents_block_is_drawn_under_the_info_line_only_while_the_roster_is_empty(self) -> None:
        app, _client = agent_app()
        self.hud(app)
        self.assertEqual([row for row in self.slot(app) if not row.startswith(("[Plan]", "[•]"))], [])
        self.assertEqual(view_text(app), VIEW)
        app.roster.clear()
        self.assertEqual([row for row in self.slot(app) if not row.startswith(("[Plan]", "[•]"))], [])
        rows = view_text(app)
        self.assertTrue(rows[0].startswith("  ● main │ [global] 2 agents · 2 running"), rows)
        self.assertEqual([row[4:18] for row in rows[1:]], ["[sub] worker0 ", "[sub] worker1 "], rows)
        self.assertEqual(info_left(app), "2 agents", "no list to open from the HUD's rows")

    def test_idle_with_agents_still_running_the_view_says_which_and_no_state_word_does(self) -> None:
        # The status line's `idle · 2 agents running` is gone with the status line: the view marks each agent.
        app, _client = agent_app(busy=False, cols=80)
        self.assertEqual(info_left(app), CHIP)
        self.assertEqual(view_text(app), VIEW)
        relay(app, FRAMES)
        self.assertEqual([row[:4] for row in view_text(app)], ["  ● ", "  ✓ ", "  ✗ "])
        for state in ("idle", "running", "agents running"):
            self.assertNotIn(state, mode_row(app))

    def test_the_view_keeps_its_cap_and_a_running_agent_raises_it_up_to_a_third_of_the_screen(self) -> None:
        for rows in (12, 16, 24, 40):
            with self.subTest(rows=rows):
                app, _client = agent_app(rows=rows)
                for number in range(12):
                    agent_event(app, "start", f"sa-more-{number}", goal=f"task {number}")
                    agent_event(app, "complete", f"sa-more-{number}", goal=f"task {number}", status="completed")
                # The two recorded agents still run: main, those two and the `+N` row, up to a third of the screen.
                usual = max(min(AGENT_VIEW_ROWS, rows // 4), min(4, rows // 3))
                self.assertEqual(view_rows(app), usual, "done agents never raise it")
                for number in range(12):
                    agent_event(app, "start", f"sa-run-{number}", goal=f"run {number}")
                shown = view_text(app)
                # Fourteen running (the two recorded ones too) want main, fourteen rows and the `+N` row: a third
                # of the screen is the most they get.
                self.assertEqual(len(shown), {12: 4, 16: 5, 24: 8, 40: 13}[rows])
                self.assertEqual(len(shown), agent_view_cap(rows, 80, 16))
                self.assertFalse([row for row in shown if "task " in row], "a done agent never takes a running one's row")
                self.assertTrue(shown[-1].endswith(" running · 12 done"), shown[-1])


def with_graph(app: App, graph: dict | None, plan: list[dict] | None = None) -> None:
    """A HUD snapshot holding `graph` as the conversation's delegation graph (and `plan` as its plan)."""
    from test_tui_panels import hud_payload
    from omh.tui.panels import HudSnapshot

    payload = hud_payload(plan)
    if graph is not None:
        payload["delegation_graph"] = graph
    app.hud = HudSnapshot(app.stored_id, payload, 0.0)


def pinned(app: App) -> list[str]:
    """Ctrl+L, then output past the screen: the region on the screen's last row, its place certain."""
    app._on_input(Key(CHAR, "l", ctrl=True))
    drawn(app)
    app.transcript.add_notice("\n".join(f"line {number}" for number in range(80)))
    return drawn(app)


def box_top(screen: list[str]) -> int | None:
    return next((index for index, row in enumerate(screen) if row.startswith(RULE_ROW)), None)


class DagViewTests(unittest.TestCase):
    """A DAG run's folding tree under the info line (`dag_tree`): a third of the screen from the start, one line once
    the run is over, and the keys Down gives it in its own rows. tests/test_tui_dag_tree.py pins the tree itself."""

    def tree_app(self, rows: int, graph: dict, **options: object) -> App:
        app, _client = make_app(busy=True, rows=rows, cols=120, clock=lambda: 0.0, **options)
        with_graph(app, graph)
        return app

    def test_the_staged_export_tree_is_whole_at_40_rows_and_folded_at_24_keeping_its_running_lane(self) -> None:
        from _delegation_graphs import export_run

        # The folding tree (the owner's pick of 2026-10-22) in place of the box-drawing tree: no `◆ main` row, a
        # label row per stage, a blank row between two stages.
        whole = view_text(self.tree_app(40, export_run(staged=True)))
        self.assertEqual(len(whole), 11, whole)  # header, three stages, five lanes, two blanks: under 40 // 3
        self.assertFalse([row for row in whole if "more" in row])
        self.assertEqual([row.strip()[:12] for row in whole[:2]], ["DAG · export", "▾ stage 1 · "])
        folded = [row.rstrip() for row in view_text(self.tree_app(24, export_run(staged=True)))]
        self.assertLessEqual(len(folded), 24 // 3)
        self.assertIn("  ▸ stage 1 · 1 node · 1 done", folded, "the done stage shuts first")
        self.assertIn("    ▸ 2 more · 2 waiting", folded, "the busy stage's quiet lanes fold into one row")
        self.assertTrue([row for row in folded if "⠋ Export button" in row and "running" in row], folded)

    def test_the_cap_is_a_third_of_the_screen_whatever_runs(self) -> None:
        from _delegation_graphs import parallel

        # Nothing running: the non-DAG cap would be min(7, rows // 4), 6 at 24 rows and 7 at 40; the tree, twenty
        # waiting lanes that fold no further, still gets a third of the screen, its last row the count of the rest.
        idle = parallel(20)
        for node in idle["nodes"][1:]:
            node.update(state="waiting", status="waiting")
        idle["edges"].append({"from": "l0", "to": "l1", "kind": "depends_on"})
        for rows in (24, 40):
            with self.subTest(rows=rows):
                shown = view_text(self.tree_app(rows, idle))
                self.assertEqual(len(shown), rows // 3)
                self.assertEqual(shown[-1].rstrip(), f"  … {20 - (rows // 3 - 2)} more nodes · ↓ to browse")
        # The same run's six-row tree without stages (one unnamed group draws no label row) fits whole at 24 rows.
        from _delegation_graphs import export_run

        flat = view_text(self.tree_app(24, export_run()))
        self.assertEqual(len(flat), 6)
        self.assertFalse([row for row in flat if "more" in row])

    def ended(self, app: App) -> App:
        app.turn_pending = False  # the turn is over: the run's tree folds now, not while the turn runs
        return app

    def test_a_run_whose_every_lane_settled_leaves_the_view_once_the_turn_ends(self) -> None:
        # It was one summary line, kept until the graph lingered out of the HUD (15 minutes) and drawn as the whole
        # tree again while the next turn ran; the owner (2026-10-26) wants it gone as the run ends. The run's end
        # print in the transcript says the same, and `/dag` draws the whole graph.
        from _delegation_graphs import export_run

        done = {"api": "done", "ui": "done", "docs": "done", "cli": "done", "verify": "done"}
        for rows in (24, 40):
            with self.subTest(rows=rows):
                self.assertEqual(view_text(self.ended(self.tree_app(rows, export_run(done, staged=True)))), [])
                failed = export_run({**done, "docs": "failed", "verify": "interrupted"}, staged=True)
                self.assertEqual(view_text(self.ended(self.tree_app(rows, failed))), [])
        one_left = export_run({**done, "verify": "running"}, staged=True)
        self.assertGreater(len(view_text(self.ended(self.tree_app(40, one_left)))), 1, "a lane still running keeps the tree")
        unread = export_run(done, staged=True)
        unread["hidden_nodes"] = 2  # lanes the reader left out may still run
        self.assertGreater(len(view_text(self.ended(self.tree_app(40, unread)))), 1)

    def test_a_run_that_settles_while_the_turn_runs_keeps_its_tree_until_the_turn_ends(self) -> None:
        # The blank band (2026-10-23): on the bottom rows a view that folds mid-turn gives up its rows, which stay
        # blank between the transcript and the working row until output fills them. The fold waits for the turn's
        # end, when the run's end print and the turn's summary line fill them.
        from _delegation_graphs import export_run

        done = {"api": "done", "ui": "done", "docs": "done", "cli": "done", "verify": "done"}
        running = view_text(self.tree_app(40, export_run(done, staged=True)))
        self.assertGreater(len(running), 1, running)
        self.assertTrue(running[0].startswith("  DAG · export feature · 5 nodes"), running)
        self.assertEqual(view_text(self.ended(self.tree_app(40, export_run(done, staged=True)))), [])

    def test_a_tree_that_shrinks_mid_run_keeps_its_rows_on_the_bottom_rows_until_the_turn_ends(self) -> None:
        # The mid-run blank band (2026-10-23 audit): a tree that drew fewer rows while the turn ran gave them up, and
        # on the bottom rows they stayed blank between the transcript and the working row. The tree keeps them,
        # blank under it, until the turn ends.
        from _delegation_graphs import parallel

        def run(lanes: int) -> dict:
            graph = parallel(lanes)
            graph["edges"] = [{"from": "root", "to": "l0", "kind": "dispatch"}] + [
                {"from": "l0", "to": f"l{number}", "kind": "depends_on"} for number in range(1, lanes)]
            return graph

        app = self.tree_app(40, run(8))
        pinned(app)
        tall = view_rows(app)
        with_graph(app, run(3))  # the graph reader now keeps fewer of the run's lanes
        held = view_text(app)
        self.assertEqual(len(held), tall)
        tree = len(held)
        while tree and not held[tree - 1].strip():
            tree -= 1
        self.assertLess(tree, tall, "the tree itself shrank; its rows stay under it, blank")
        self.assertTrue(held[tree - 1].strip().startswith("⠋ Lane 2 migrate"), held)
        app.turn_pending = False
        self.assertLess(view_rows(app), tall, "the hold ends with the turn")

    @staticmethod
    def chained(lanes: int) -> dict:
        """`lanes` running lanes, the first a layer of its own and the rest after it: a dag run's tree."""
        from _delegation_graphs import parallel

        graph = parallel(lanes)
        graph["edges"] = [{"from": "root", "to": "l0", "kind": "dispatch"}] + [
            {"from": "l0", "to": f"l{number}", "kind": "depends_on"} for number in range(1, lanes)]
        return graph

    @staticmethod
    def held(app: App) -> int:
        """The blank rows under the tree's last drawn row."""
        rows = view_text(app)
        under = 0
        while under < len(rows) and not rows[len(rows) - 1 - under].strip():
            under += 1
        return under

    def test_the_hold_ends_with_a_turn_that_draws_no_tree_and_on_a_new_session(self) -> None:
        # The review of 2fb605957: the hold was dropped only where a tree, or its summary line, was drawn between
        # turns. A turn that ended with the graph gone (a settled graph that went quiet) left it, and the next turn's
        # first tree drew the old height's rows blank under it (20 held, 15 of them blank).
        app = self.tree_app(40, self.chained(8))
        pinned(app)
        view_rows(app)  # a frame drawn on the bottom rows: the tree's height is held from here
        with_graph(app, self.chained(3))
        self.assertGreater(self.held(app), 0)
        with_graph(app, None)
        app.turn_pending = False
        self.assertEqual(view_text(app), [], "between the turns no tree is drawn")
        app.turn_pending = True  # the next turn, and a smaller run, with the region still on the bottom rows
        with_graph(app, self.chained(2))
        self.assertEqual(app.region.last_row(40), 39)
        self.assertEqual(self.held(app), 0)
        # A new session drops a hold too, before anything is drawn.
        app.tree_hold = 20
        app.turn_pending = False
        client = app.client
        type_text(app, "/new")
        app._on_input(Key(ENTER))
        answer(app, client, {"session_id": "live-2", "stored_session_id": "stored-2", "info": {}})
        self.assertEqual(app.tree_hold, 0)

    def test_the_held_rows_never_pass_the_views_cap(self) -> None:
        # A taller composer or a slot lowers the view's cap mid-turn: the hold gives way, so the composer and the
        # info line stay on the screen.
        app = self.tree_app(24, self.chained(8))
        pinned(app)
        view_rows(app)
        with_graph(app, self.chained(2))
        self.assertGreater(self.held(app), 0)
        self.assertLessEqual(len(app._agent_view(120, 24, 3)), 3)
        app.composer.replace(0, len(app.composer.text), "\n".join(f"draft line {number}" for number in range(6)))
        screen = drawn(app)
        self.assertTrue(any(row.startswith("❯ draft line 0") for row in screen), screen)
        self.assertLessEqual(len(view_text(app)), app.frame_budget.agents)

    def test_down_in_a_dag_run_gives_the_tree_the_keys_in_its_own_rows_and_nothing_moves(self) -> None:
        from _delegation_graphs import parallel
        from omh.tui.keys import DOWN, ESCAPE

        # The reviewer's two cases for the list this replaced: a tree taller than the roster, and one shorter. Down
        # now gives the keys to the tree's own rows (its nodes name the agents `x`, `s` and Enter act on), so the
        # view keeps its rows whatever the roster holds.
        for lanes, agents in ((8, 2), (3, 9)):
            with self.subTest(lanes=lanes, agents=agents):
                graph = parallel(lanes)
                graph["edges"].append({"from": "l0", "to": "l1", "kind": "depends_on"})
                app = self.tree_app(24, graph)
                for number in range(agents):
                    agent_event(app, "start", f"sa-{number}", goal=f"task {number}")
                before = pinned(app)
                info, height = screen_info_index(app, before), view_rows(app)
                self.assertEqual(before[info + 1].strip()[:5], "DAG ·")
                app._on_input(Key(DOWN))
                during = drawn(app)
                self.assertEqual((screen_info_index(app, during), view_rows(app)), (info, height))
                self.assertEqual(box_top(during), box_top(before), "the composer's rules stay")
                self.assertEqual(during[info - 2].strip(), BROWSING_HINT, "the composer's row says how to browse")
                self.assertEqual(app.tree_selected, "l0", "on the first running lane")
                self.assertEqual(app.listed, (), "the roster's list is not what Down opened")
                self.assertEqual(during[info + 1].strip()[:5], "DAG ·", "the tree stays in its rows")
                app._on_input(Key(DOWN))
                app._on_input(Key(ESCAPE))
                after = drawn(app)
                self.assertEqual((screen_info_index(app, after), box_top(after)), (info, box_top(before)))
                self.assertIsNone(app.tree_selected)
                self.assertEqual(after[info + 1].strip()[:5], "DAG ·", "the tree is back in the same rows")


class RoomTests(unittest.TestCase):
    def test_a_view_given_fewer_rows_than_its_cap_ends_on_its_count_row(self) -> None:
        # 12 rows, a plan in the slot and a turn running: the tail keeps its working row and the view gets two rows,
        # under its cap of four. Drawn again in those two rows, its last row still counts what it cannot show.
        app, _client = make_app(busy=True, rows=12, cols=80, clock=lambda: 0.0)
        with_graph(app, None, [{"text": "Build", "state": "done"}, {"text": "Test", "state": "active"},
                               {"text": "Ship", "state": "pending"}])
        for number in range(7):
            agent_event(app, "start", f"sa-{number}", goal=f"task {number}")
            if number >= 3:
                agent_event(app, "complete", f"sa-{number}", goal=f"task {number}", status="completed")
        screen = drawn(app)
        self.assertEqual(app.frame_budget.agents, 2)
        shown = view_text(app)
        self.assertTrue(shown[0].startswith("  ⠋ task 0  ") and shown[0].endswith("0s · 0 tools"), shown)
        self.assertEqual(shown[1], "  +6 more · 2 running · 4 done")
        self.assertTrue([row for row in screen if row.startswith("✻ Working")], "the working row stays")
        self.assertTrue([row for row in screen if row.startswith("[Plan]")], "and so does the plan")

    PLAN = [{"text": "Build", "state": "done"}, {"text": "Test", "state": "active"},
            {"text": "Ship", "state": "pending"}]

    def small_app(self, running: int, done: int, *, plan: bool = True, graph: dict | None = None,
                  cols: int = 80, rows: int = 12) -> App:
        """`rows` rows (12) and a turn running: `running` agents running and `done` done, the plan in the slot (four
        rows) unless `plan` is False, and `graph` as the conversation's delegation graph."""
        app, _client = make_app(busy=True, rows=rows, cols=cols, clock=lambda: 0.0)
        with_graph(app, graph, self.PLAN if plan else None)
        for number in range(running + done):
            agent_event(app, "start", f"sa-{number}", goal=f"task {number}")
            if number >= running:
                # Folded into the roster alone: the app would also brief each in the transcript (`AgentDoneBlock`),
                # whose rows would move the region these cases place on the screen.
                app.roster.apply("subagent.complete", payload(f"sa-{number}", goal=f"task {number}",
                                                              status="completed"), 0.0)
        return app

    def test_on_the_bottom_rows_the_view_keeps_its_rows_when_the_turn_ends_so_the_composer_stays(self) -> None:
        # The #2188 review's case: once the turn ends the working row leaves, and the view (two rows of the four it
        # wants) took that row, pulling the composer's box up one row until the next turn gave it back.
        app = self.small_app(running=3, done=4)
        busy = pinned(app)
        top = box_top(busy)
        self.assertEqual(app.frame_budget.agents, 2)
        self.assertTrue(busy[top - 5].startswith("✻ Working"), busy)
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        idle = drawn(app)
        self.assertEqual((box_top(idle), app.frame_budget.agents), (top, 2))
        self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (top, 2), "and so does the next frame")
        self.assertEqual(idle[top - 5], "", "the working row's place stays blank above the plan")
        self.assertEqual(idle[top - 4 : top], busy[top - 4 : top], "the plan has not moved")
        app.turn_pending = True  # a turn runs again, the agents still listed: the working row takes its place back
        again = drawn(app)
        self.assertEqual((box_top(again), app.frame_budget.agents), (top, 2))
        self.assertTrue(again[top - 5].startswith("✻ Working"), again)

    def test_a_dag_trees_rows_stay_through_the_turns_end_and_the_next_prompt(self) -> None:
        from _delegation_graphs import export_run

        app = self.small_app(running=0, done=0, graph=export_run(), cols=120)
        top = box_top(pinned(app))
        rows = app.frame_budget.agents
        self.assertGreater(rows, 0)
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (top, rows))
        type_text(app, "next")
        app._on_input(Key(ENTER))  # a new turn: the tree stays, the working row comes back
        self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (top, rows))

    def test_a_menu_that_squeezed_the_view_during_the_turn_is_not_what_the_view_keeps_after_it(self) -> None:
        # 16 rows: the `/` menu above the composer takes a row of the view's five and the composer goes down one;
        # closing it while the turn runs gives the row back, as before. The turn's last frame, not the menu's, is
        # what the view keeps once the turn ends.
        app = self.small_app(running=3, done=4, plan=False, rows=16)
        top = box_top(pinned(app))
        self.assertEqual(app.frame_budget.agents, 5)
        type_text(app, "/")
        self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (top + 1, 4))
        app._on_input(Key(BACKSPACE))
        self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (top, 5))
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (top, 5))

    def test_a_squeeze_open_as_the_turn_ends_is_not_held_once_it_closes(self) -> None:
        # Only the working row's place is held. A draft, the `/` menu or an approval that squeezed the view as the
        # turn ended gives the view its rows back once it is cleared, closed or answered.
        with self.subTest("a three-line draft, 12 rows and the plan"):
            app = self.small_app(running=3, done=4)
            top = box_top(pinned(app))
            type_text(app, "a")
            for char in "bc":
                app._on_input(Key(ENTER, alt=True))
                type_text(app, char)
            self.assertEqual(view_rows(app), 0, "the draft's rows leave the view none")
            app._on_event(Event("message.complete", SID, {"text": "done"}))
            drawn(app)
            for _ in range(5):
                app._on_input(Key(BACKSPACE))
            self.assertEqual(app.composer.text, "")
            self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (top, 2), "as the turn left it")
        with self.subTest("the `/` menu, 16 rows"):
            app = self.small_app(running=3, done=4, plan=False, rows=16)
            top = box_top(pinned(app))
            type_text(app, "/")
            self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (top + 1, 4))
            app._on_event(Event("message.complete", SID, {"text": "done"}))
            self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (top + 1, 4))
            app._on_input(Key(BACKSPACE))
            self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (top, 5))
        with self.subTest("an approval, 12 rows"):
            app = self.small_app(running=3, done=4, plan=False)
            top = box_top(pinned(app))
            self.assertEqual(app.frame_budget.agents, 4)
            app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
            # The approval's rule over its choices (2026-10-28) is the slot's within its cap, here the view's third row.
            self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (None, 2))
            app._on_event(Event("message.complete", SID, {"text": "done"}))
            self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (None, 2))
            app.slot_opened_at = app.clock() - 10.0  # past the delay that drops keys pressed as it opened
            app._on_input(Key(ENTER))
            self.assertIsNone(app.slot)
            self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (top, 4))

    def test_a_menu_opened_after_the_turn_squeezes_the_view_no_more_than_it_did_before(self) -> None:
        # 12 rows, no plan: the view had its four rows while the turn ran. A `/` menu opened once it ended takes the
        # one row the view must give up, as on a terminal with nothing held, not that row and the working row's.
        app = self.small_app(running=3, done=4, plan=False)
        top = box_top(pinned(app))
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (top, 4))
        type_text(app, "/")
        self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (top + 1, 3))
        app._on_input(Key(BACKSPACE))
        self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (top, 4))

    def test_working_rows_that_drop_mid_turn_go_to_the_view_at_once(self) -> None:
        # Nothing is held while the turn runs. 16 rows, the plan and a four-line draft leave the view two rows beside
        # the working row and its tip; the interrupt takes the tip away, and the very next frame gives that row to
        # the view, as `layout.allocate`'s tail_floor says. A hold applied there would keep it out for one frame.
        app = self.small_app(running=3, done=4, rows=16)
        pinned(app)
        type_text(app, "a")
        for char in "bcd":
            app._on_input(Key(ENTER, alt=True))
            type_text(app, char)
        self.assertEqual((box_top(drawn(app)), app.frame_budget.agents, app._working_rows()), (7, 2, 2))
        app._interrupt()  # what the interrupt keys reach while a turn runs
        self.assertEqual((box_top(drawn(app)), app.frame_budget.agents, app._working_rows()), (6, 3, 1))

    def test_a_turn_drawn_above_the_bottom_rows_holds_nothing_when_its_answer_brings_them_down(self) -> None:
        # Above the bottom rows the composer follows the content, so a turn drawn there keeps no rows: the answer
        # that brings the region down to the bottom rows must not shrink the view one frame later.
        app = self.small_app(running=3, done=4)
        app._on_input(Key(CHAR, "l", ctrl=True))
        drawn(app)
        self.assertNotEqual(app.region.last_row(12), 11)
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        app.transcript.add_notice("\n".join(f"answer line {number}" for number in range(40)))
        first = (box_top(drawn(app)), app.frame_budget.agents)
        self.assertEqual(app.region.last_row(12), 11)
        self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), first)

    def test_a_region_that_leaves_the_bottom_rows_drops_the_hold(self) -> None:
        # Ctrl+L, and the full redraw a resize ends in, start the region on a clean screen's top rows: there the view
        # takes the rows it wants, and output that brings it back down does not bring the old hold back.
        for name, leave in (
            ("ctrl+l", lambda app: app._on_input(Key(CHAR, "l", ctrl=True))),
            ("a resize and back", self.resize_and_back),
        ):
            with self.subTest(name):
                app = self.small_app(running=3, done=4)
                pinned(app)
                app._on_event(Event("message.complete", SID, {"text": "done"}))
                self.assertEqual(view_rows(app), 2)
                leave(app)
                self.assertEqual(view_rows(app), 3)
                app.transcript.add_notice("\n".join(f"more {number}" for number in range(40)))
                self.assertEqual(view_rows(app), 3)
                self.assertEqual(app.region.last_row(12), 11)

    @staticmethod
    def resize_and_back(app: App) -> None:
        for rows in (13, 12):
            app.terminal.screen.resize(rows, 80)  # type: ignore[attr-defined]
            app._on_resize()
            app._full_redraw()
            drawn(app)

    def test_a_view_that_wants_more_rows_takes_them_and_one_that_wants_fewer_gives_them_up(self) -> None:
        # One agent running: the view wants three rows and gets two while the turn runs, and keeps two after it.
        app = self.small_app(running=1, done=4)
        top = box_top(pinned(app))
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (top, 2))
        # A second running agent wants a fourth row: the view takes the free row, so the composer goes up for it.
        agent_event(app, "start", "sa-new", goal="task new")
        self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (top - 1, 3))
        # That drops the hold: when the agent finishes the view does not snap back, so the composer stays.
        agent_event(app, "complete", "sa-new", goal="task new", status="completed")
        self.assertEqual((box_top(drawn(app)), app.frame_budget.agents), (top - 1, 3))
        # The next prompt empties the roster: the view gives every row up, none left blank under the info line.
        type_text(app, "next")
        app._on_input(Key(ENTER))
        emptied = drawn(app)
        self.assertEqual(app.frame_budget.agents, 0)
        self.assertEqual(app.region.last_row(12), 11)
        self.assertIn(badge_text(), emptied[11], "the info line is the screen's last row")
        # An agent of the new turn wants rows again, and gets them: no hold of an emptied view is kept.
        agent_event(app, "start", "sb-0", goal="task b0")
        self.assertEqual([row[:12] for row in view_text(app)], ["  ● main", "  ⠋ task b0 "])

    def test_another_session_does_not_keep_the_last_ones_hold(self) -> None:
        from _delegation_graphs import export_run

        app = self.small_app(running=3, done=4)
        pinned(app)
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertEqual(view_rows(app), 2)  # held at the turn's two rows
        type_text(app, "/new")
        app._on_input(Key(ENTER))
        answer(app, app.client, {"session_id": "live-2", "stored_session_id": "stored-2", "info": {}})
        # `/new` redraws nothing, so the region is still on the bottom rows. The new session's tree (a third of 12
        # rows is four) gets the three rows the plan leaves it, not what the last session's turn left the view.
        with_graph(app, export_run(), self.PLAN)
        self.assertEqual(view_rows(app), 3)
        self.assertEqual(app.region.last_row(12), 11)

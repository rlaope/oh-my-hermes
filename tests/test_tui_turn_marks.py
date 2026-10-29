"""Outcome bands, the queue's tag, and where a steer lands.

Your prompt sits on no band: a dim `>` and dim text, as Claude Code shows it.
A band (an outcome's) fills to the right edge by an erase in its background
rather than by spaces. A prompt the queue sent once the turn before it ended
says `⧗ from queue`. A steer shows as
`↪ steer · <text>` under what is running until Hermes answers, and is
written into the transcript at the next block boundary after that, so it
never closes a running tool group (whose calls would read as cut off) or
splits a streaming reply. A turn's done line sits right above the panel
however tall its last tool group was.
"""

from __future__ import annotations

import re
import unittest

from _tui_lines import line_text, lines_text
from test_tui_modes import CTRL_ENTER, SID, answer, drawn, make_app, type_text
from test_tui_panels import hud_payload, phased_plan
from test_tui_theme import DARK_BACKGROUNDS, LIGHT_BACKGROUNDS, contrast
from omh.skin_pack import SKIN_THEMES
from omh.tui.app import SLOT_ARM_SECONDS
from omh.tui.gateway import Event, Response, ServerRequest
from omh.tui.keys import CHAR, ENTER, ESCAPE, RIGHT, Key
from omh.tui.panels import HudSnapshot
from omh.tui.screen import ERASE_TO_LINE_END, paint_line
from omh.tui.style import SGR_RESET, Span, Style, fill
from omh.tui.theme import DEFAULT_THEME as THEME
from omh.tui.theme import DEFAULT_LAUNCH, build_theme, is_light, with_prompt_band
from omh.tui.transcript import (
    NOTICE_ERROR,
    NOTICE_OK,
    NOTICE_WARN,
    OUTPUT_FAILED,
    STEER_QUEUED,
    TOOL_DENIED,
    TOOL_ERROR,
    TOOL_OK,
    TOOL_RUNNING,
    AssistantBlock,
    CommandBlock,
    NoticeBlock,
    SteerBlock,
    ToolGroup,
    ToolRow,
    TurnSummaryBlock,
    UserBlock,
    block_rows,
    rail_cell,
)


def ev(kind: str, **payload: object) -> Event:
    return Event(kind, SID, payload)


# A theme measured against a background the terminal reported: only then is there a band to paint.
REPORTED = build_theme(SKIN_THEMES[0], "#1E1E1E")


def unrailed(rows: list) -> list:
    """`rows` without the rail a tool call's rows hang on (a painted cell and a space): what is on a band beside it."""
    return [row[2:] if row and row[0].style.gutter else row for row in rows]


class BandTests(unittest.TestCase):
    def test_a_prompt_runs_on_the_look_s_band_wherever_a_background_was_reported(self) -> None:
        # Round 4 drew your prompt with no band, a dim `>` and dim text on a dim rail; the owner's pick of 2026-10-27
        # puts it on the launch look's band, to the right edge, on every theme and reported background, and on none
        # when no background was reported.
        for skin in SKIN_THEMES:
            for background in (None, *LIGHT_BACKGROUNDS, *DARK_BACKGROUNDS):
                theme = with_prompt_band(build_theme(skin, background), skin, background, DEFAULT_LAUNCH)
                rows = block_rows(UserBlock("first line\nsecond line"), 40, theme)
                with self.subTest(theme=skin.short_name, background=background):
                    self.assertEqual(lines_text(rows), ["  ❯ first line", "    second line"])
                    band = {theme.prompt_band.bg} if background is not None else {None}
                    self.assertEqual({span.style.bg for row in rows for span in row}, band)

    def test_the_fill_erases_to_the_edge_in_its_background_and_a_full_row_erases_nothing(self) -> None:
        band = Style(bg="#102030")
        painted = paint_line((Span("› go", band), fill(band)), 20)
        self.assertTrue(painted.endswith(f"{band.sgr()}{ERASE_TO_LINE_END}{SGR_RESET}"), repr(painted))
        self.assertEqual(paint_line((Span("› go"),), 20), f"› go{ERASE_TO_LINE_END}")  # no fill: a plain erase
        self.assertEqual(paint_line((Span("› go"), Span("")), 20), f"› go{ERASE_TO_LINE_END}")  # empty, no background
        self.assertNotIn(ERASE_TO_LINE_END, paint_line((Span("x" * 20, band), fill(band)), 20))


class OutcomeBandTests(unittest.TestCase):
    """Owner decision 6: an outcome's row sits on a band, green for what the person allowed, red for a denial or an
    error notice, and a failed command's output red too.

    Every span on the band's background and an
    erase to the right edge, so a copy carries no trailing spaces. Words on a
    band reach 4.5:1 against it and marks 3:1; with no background reported
    there is no band. Warnings and running rows carry none. Since the rail and
    kind colours (2026-10-22) a tool call's own rows carry no band: a failed or
    denied call says so by its red `✗` and its red rail (`test_a_failed_or_denied_call_is_its_red_rail_and_mark`),
    and the person's answer under a call is banded beside the call's rail.
    """

    DENIAL = "You denied this command — it did not run."

    def outcomes(self, theme: object) -> list[tuple[str, list]]:
        """(band role, rows) for every kind of row that carries a band."""
        failed = ToolGroup([ToolRow("t1", "terminal", "pytest -q", TOOL_ERROR, duration_s=1.2, output=("1 failed",))], done=True)
        denied = ToolGroup([ToolRow("t2", "terminal", "rm -rf ./build", TOOL_DENIED, duration_s=0.1, output=(self.DENIAL,))],
                           done=True)
        command = CommandBlock("!false", [("partial output", OUTPUT_FAILED), ("exit 1", NOTICE_ERROR)], done=True)
        summarized = ToolGroup([ToolRow("t3", "read_file", "/nope.txt", TOOL_ERROR, duration_s=0.1,
                                        summary="read_file could not open the path", output=("File not found",))], done=True)
        allowed = ToolGroup([ToolRow("t4", "terminal", "ls", TOOL_OK, duration_s=0.1, output=("a.txt",),
                                     answers=[("allowed once · ls", NOTICE_OK)])], done=True)
        refused = ToolGroup([ToolRow("t5", "terminal", "rm -rf ./dist", TOOL_DENIED, duration_s=0.1, output=(self.DENIAL,),
                                     answers=[("denied · rm -rf ./dist", NOTICE_ERROR)])], done=True)
        del failed, denied, summarized  # a call's own rows carry no band: its rail and its mark say how it ended
        return [
            ("ok_band", block_rows(NoticeBlock("allowed once · ls", NOTICE_OK), 60, theme)),  # type: ignore[arg-type]
            ("ok_band", unrailed(block_rows(allowed, 60, theme)[1:2])),  # type: ignore[arg-type]  # the answer under its call
            ("error_band", unrailed(block_rows(refused, 60, theme)[1:2])),  # type: ignore[arg-type]  # the refusal under it
            ("error_band", block_rows(NoticeBlock("denied · rm -rf ./build", NOTICE_ERROR), 60, theme)),  # type: ignore[arg-type]
            ("error_band", block_rows(NoticeBlock("The turn ended with an error.", NOTICE_ERROR), 60, theme)),  # type: ignore[arg-type]
            ("error_band", unrailed(block_rows(command, 60, theme)[1:])),  # type: ignore[arg-type]  # its output
        ]

    def test_every_outcome_row_is_on_its_band_to_the_edge_and_every_word_reads_on_it(self) -> None:
        for skin in SKIN_THEMES:
            for background in (*LIGHT_BACKGROUNDS, *DARK_BACKGROUNDS):
                theme = build_theme(skin, background)
                for role, rows in self.outcomes(theme):
                    band = getattr(theme, role)
                    for row in rows:
                        with self.subTest(theme=skin.short_name, background=background, row=line_text(row)):
                            self.assertEqual(row[-1], fill(band))  # an erase, not spaces
                            self.assertEqual(line_text(row), line_text(row).rstrip())
                            for span in row:
                                self.assertEqual(span.style.bg, band.bg)
                                if span.style.fg and span.text.strip():
                                    minimum = 4.5 if any(char.isalnum() for char in span.text) else 3.0
                                    self.assertGreaterEqual(contrast(span.style.fg, band.bg), minimum, span.text)

    def test_bands_are_light_on_a_light_terminal_and_dark_on_a_dark_one(self) -> None:
        for skin in SKIN_THEMES:
            for background in (*LIGHT_BACKGROUNDS, *DARK_BACKGROUNDS):
                theme = build_theme(skin, background)
                for role in ("ok_band", "error_band"):
                    with self.subTest(theme=skin.short_name, background=background, role=role):
                        band = getattr(theme, role).bg
                        self.assertEqual(is_light(band), background in LIGHT_BACKGROUNDS)
                        self.assertNotEqual(band, background)
        light = build_theme(SKIN_THEMES[0], "#FFFFFF")
        self.assertNotEqual(light.ok_band.bg, light.error_band.bg)  # green is not red

    def test_a_background_the_person_names_with_theme_light_or_dark_is_banded(self) -> None:
        # No guess there: the person said which background it is, though the terminal did not.
        for word, light in (("light", True), ("dark", False)):
            with self.subTest(theme=word):
                app, _client = make_app()
                app.adopt_background(None)
                type_text(app, f"/theme {word}")
                app._on_input(Key(ENTER))
                for role in ("ok_band", "error_band"):
                    band = getattr(app.theme, role).bg
                    self.assertIsNotNone(band, role)
                    self.assertEqual(is_light(band), light, role)
                type_text(app, "/theme auto")
                app._on_input(Key(ENTER))
                self.assertIsNone(app.theme.error_band.bg)  # back to following a terminal that reports nothing

    def test_a_dark_background_colorfgbg_names_is_banded_as_theme_dark_bands_it(self) -> None:
        dark, _client = make_app()
        dark.adopt_background(None)
        type_text(dark, "/theme dark")
        dark._on_input(Key(ENTER))
        for value, expected in (("15;0", dark.theme), ("7;0", dark.theme), ("15;default;0", dark.theme),
                                ("0;15", build_theme(SKIN_THEMES[0], "#FFFFFF"))):
            with self.subTest(colorfgbg=value):
                app, _client = make_app()
                app.adopt_background(None, {"COLORFGBG": value})  # the terminal did not answer OSC 11
                for role in ("ok_band", "error_band"):
                    self.assertIsNotNone(getattr(app.theme, role).bg, role)
                    self.assertEqual(getattr(app.theme, role), getattr(expected, role), role)
        for environ in ({}, {"COLORFGBG": "garbage"}, {"COLORFGBG": "15;99"}):
            with self.subTest(environ=environ):  # nothing reported: no band
                app, _client = make_app()
                app.adopt_background(None, environ)
                self.assertEqual([app.theme.ok_band.bg, app.theme.error_band.bg], [None] * 2)
        app, _client = make_app()
        app.adopt_background("#FFFFFF", {"COLORFGBG": "15;0"})  # an answer outranks the variable
        self.assertTrue(is_light(app.theme.error_band.bg))

    def test_with_no_background_reported_nothing_is_banded(self) -> None:
        for skin in SKIN_THEMES:
            theme = build_theme(skin, None)
            for _role, rows in self.outcomes(theme):
                with self.subTest(theme=skin.short_name):
                    self.assertEqual({span.style.bg for row in rows for span in row}, {None})

    def test_a_denial_shows_one_mark_the_failures_red_one(self) -> None:
        theme = build_theme(SKIN_THEMES[0], "#FFFFFF")
        failed = block_rows(ToolGroup([ToolRow("t1", "terminal", "pytest -q", TOOL_ERROR, duration_s=1.2,
                                                output=("1 failed",))], done=True), 60, theme)
        denied = block_rows(ToolGroup([ToolRow("t2", "terminal", "rm -rf ./build", TOOL_DENIED, duration_s=0.1,
                                                output=(self.DENIAL,))], done=True), 60, theme)
        rows = lines_text([*failed, *denied])
        self.assertFalse([row for row in rows if "⊘" in row], rows)
        self.assertEqual(denied[0][:3], failed[0][:3])  # the same rail and the same mark
        self.assertEqual([span.text for span in denied[0][:3]], [" ", " ", "✗"])
        self.assertIn("    ⎿  " + self.DENIAL, rows)  # told apart from a failure by its words, not only its colour

    def test_a_failed_or_denied_call_is_its_red_rail_and_mark_on_no_band(self) -> None:
        # The rail and kind colours (2026-10-22): no fill behind a call; its state is its rail's colour and its mark.
        for skin in SKIN_THEMES:
            for background in (*LIGHT_BACKGROUNDS, *DARK_BACKGROUNDS):
                theme = build_theme(skin, background)
                for status in (TOOL_ERROR, TOOL_DENIED):
                    rows = block_rows(ToolGroup([ToolRow("t1", "terminal", "pytest -q", status, duration_s=1.2,
                                                         output=("1 failed",))], done=True), 60, theme)
                    with self.subTest(theme=skin.short_name, background=background, status=status):
                        self.assertEqual({span.style.bg for row in rows for span in row}, {None})
                        self.assertEqual({row[0] for row in rows}, {rail_cell(theme.error)})
                        self.assertEqual(rows[0][2], Span("✗", theme.error))
                        self.assertGreaterEqual(contrast(theme.error.fg, background), 3.0)

    def test_warnings_and_running_rows_carry_no_band(self) -> None:
        theme = build_theme(SKIN_THEMES[0], "#FFFFFF")
        running = ToolGroup([ToolRow("t1", "terminal", "sleep 9", TOOL_RUNNING, started_at=0.0)])
        for rows in (block_rows(NoticeBlock("careful", NOTICE_WARN), 60, theme), block_rows(running, 60, theme, now=0.7)):
            self.assertEqual({span.style.bg for row in rows for span in row}, {None})


class FromQueueTests(unittest.TestCase):
    def test_a_prompt_the_queue_sent_says_so_and_a_typed_one_does_not(self) -> None:
        app, client = make_app(busy=True)
        type_text(app, "next one")
        app._on_input(Key(ENTER))
        app._on_event(ev("message.complete", text="done"))
        self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": "next one", "queued": True}))
        users = [block for block in app.transcript.blocks if isinstance(block, UserBlock)]
        self.assertEqual([line_text(block_rows(block, 80, THEME)[0]) for block in users], ["  ❯ next one  ⧗ from queue"])
        typed = block_rows(UserBlock("typed"), 80, THEME)[0]
        self.assertEqual(line_text(typed), "  ❯ typed")

    def test_the_tag_waits_for_room(self) -> None:
        row = block_rows(UserBlock("a long prompt that fills the row", from_queue=True), 36, THEME)[0]
        self.assertEqual(line_text(row), "  ❯ a long prompt that fills the row")  # the rail, then no room for the tag

    def test_the_tag_reads_on_the_terminals_background(self) -> None:
        for skin in SKIN_THEMES:
            for background in (*LIGHT_BACKGROUNDS, *DARK_BACKGROUNDS):
                theme = build_theme(skin, background)
                row = block_rows(UserBlock("next", from_queue=True), 80, theme)[0]
                (tag,) = [span for span in row if "from queue" in span.text]
                with self.subTest(theme=skin.short_name, background=background):
                    self.assertGreaterEqual(contrast(tag.style.fg, background), 4.5)


class SteerPlacementTests(unittest.TestCase):
    def steer(self, app: object, text: str) -> None:
        type_text(app, text)  # type: ignore[arg-type]
        app._on_input(CTRL_ENTER)  # type: ignore[attr-defined]

    def test_a_steer_during_a_running_tool_leaves_the_tool_running_and_lands_after_its_group(self) -> None:
        app, client = make_app(busy=True)
        app._on_event(ev("message.start"))
        app._on_event(ev("tool.start", tool_id="t1", name="terminal", context="pytest"))
        self.steer(app, "only the failing test")
        live = lines_text(app.transcript.live_lines(80, THEME))
        self.assertEqual(live[-1], "↪ steer · only the failing test")  # under what is running, until Hermes answers
        answer(app, client, {"status": "queued", "text": "only the failing test"})
        group = app.transcript.blocks[-1]
        self.assertIsInstance(group, ToolGroup)
        self.assertEqual(group.tools[0].status, TOOL_RUNNING)  # not cut off by the steer
        self.assertEqual(lines_text(app.transcript.live_lines(80, THEME))[-1], "↪ steer queued by Hermes · only the failing test")
        app._on_event(ev("tool.complete", tool_id="t1", name="terminal", result={"output": "1 passed"}))
        app._on_event(ev("message.delta", text="Running only that test now."))
        kinds = [type(block) for block in app.transcript.blocks]
        self.assertEqual(kinds, [ToolGroup, SteerBlock, AssistantBlock])
        self.assertEqual(app.transcript.blocks[0].tools[0].status, TOOL_OK)
        self.assertEqual(app.transcript.blocks[1].state, STEER_QUEUED)

    def test_the_steer_command_is_its_own_echo_and_leaves_a_running_tool_running(self) -> None:
        # Found live: `> /steer ...` echoed as a command closed the tool group and marked the running call `▪`.
        app, client = make_app(busy=True)
        app._on_event(ev("message.start"))
        app._on_event(ev("tool.start", tool_id="t1", name="terminal", context="sleep 6"))
        type_text(app, "/steer also echo steered")
        app._on_input(Key(ENTER))
        answer(app, client, {"status": "queued", "text": "also echo steered"})
        (group,) = app.transcript.blocks
        self.assertEqual(group.tools[0].status, TOOL_RUNNING)
        self.assertEqual(lines_text(app.transcript.live_lines(80, THEME))[-1], "↪ steer queued by Hermes · also echo steered")
        self.assertEqual(app.composer.history[-1], "/steer also echo steered")  # Up still finds what was typed

    def test_a_steer_during_a_streaming_reply_does_not_split_it(self) -> None:
        app, client = make_app(busy=True)
        app._on_event(ev("message.start"))
        app._on_event(ev("message.delta", text="First half, "))
        self.steer(app, "shorter please")
        answer(app, client, {"status": "queued", "text": "shorter please"})
        app._on_event(ev("message.delta", text="second half."))
        app._on_event(ev("message.complete", text="First half, second half.", status="complete"))
        replies = [block.text for block in app.transcript.blocks if isinstance(block, AssistantBlock)]
        self.assertEqual(replies, ["First half, second half."])
        kinds = [type(block).__name__ for block in app.transcript.blocks]
        self.assertEqual(kinds[:2], ["AssistantBlock", "SteerBlock"])

    def test_a_steer_hermes_answers_with_another_call_keeps_all_the_reply_showed(self) -> None:
        # Found live: Hermes read the steer before a second model call with no `message.interim` between, so the
        # second call's text streamed onto the first's, and `message.complete` (the last call's text only) replaced
        # the whole block: the first reply left the screen and scrollback. Now nothing that streamed is rewritten;
        # the steer row goes under the reply, as Hermes' answer put it.
        app, client = make_app(busy=True, rows=16)
        app._on_event(ev("message.start"))
        app._on_event(ev("message.delta", text="SLOW-START the first "))
        self.steer(app, "steer me")
        answer(app, client, {"status": "queued", "text": "steer me"})
        app._on_event(ev("message.delta", text="reply SLOW-END "))
        app._on_event(ev("message.delta", text="Reply #2 to: steer me. REPLY-END-2"))
        app._on_event(ev("message.complete", text="Reply #2 to: steer me. REPLY-END-2", status="complete"))
        replies = [block.text for block in app.transcript.blocks if isinstance(block, AssistantBlock)]
        self.assertEqual(replies, ["SLOW-START the first reply SLOW-END Reply #2 to: steer me. REPLY-END-2"])
        drawn(app)
        screen = "\n".join(app.terminal.screen.history())  # type: ignore[attr-defined]  # scrollback and the screen
        for words in ("SLOW-START the first reply SLOW-END", "Reply #2 to: steer me. REPLY-END-2",
                      "↪ steer queued by Hermes · steer me"):
            self.assertEqual(screen.count(words), 1, screen)
        self.assertLess(screen.index("REPLY-END-2"), screen.index("↪ steer queued by Hermes"), screen)

    def test_the_screen_shows_the_steer_waiting_then_once_in_scrollback(self) -> None:
        app, client = make_app(busy=True, rows=16)
        app._on_event(ev("message.start"))
        app._on_event(ev("tool.start", tool_id="t1", name="terminal", context="ls"))
        self.steer(app, "and the docs")
        self.assertIn("↪ steer · and the docs", drawn(app))
        answer(app, client, {"status": "queued", "text": "and the docs"})
        app._on_event(ev("tool.complete", tool_id="t1", name="terminal", result={"output": ""}))
        app._on_event(ev("message.complete", text="done", status="complete"))
        drawn(app)
        screen = app.terminal.screen.history()  # type: ignore[attr-defined]  # scrollback and the screen
        self.assertEqual(screen.count("↪ steer queued by Hermes · and the docs"), 1, screen)
        self.assertNotIn("↪ steer · and the docs", screen)

    def test_a_refused_steer_reads_in_amber_and_waits_in_the_queue(self) -> None:
        app, client = make_app(busy=True)
        self.steer(app, "keep this")
        answer(app, client, error={"code": 4010, "message": "agent does not support steer"})
        (block,) = [block for block in app.transcript.blocks if isinstance(block, SteerBlock)]
        (row,) = block_rows(block, 100, THEME)
        self.assertEqual(line_text(row), "⧗ queued — Hermes refused the steer (agent does not support steer) · keep this")
        self.assertEqual({span.style for span in row}, {THEME.warn})
        self.assertEqual([text for text, *_ in app.queued], ["keep this"])


class UnansweredSteerTests(unittest.TestCase):
    """A steer Hermes never answers is settled when its call expires: its text comes back, and is never sent again.

    Hermes may have taken it (an answer lost is no refusal), so nothing goes
    out for it, idle or not; the text returns to the composer, and to the
    draft a question gives back, never into an answer to Hermes.
    """

    BACK = "⧗ back in the composer — Hermes did not answer the steer in 120 s · use the other file"

    def steered(self, clock: Clock, busy_after: bool) -> tuple[object, object, int]:
        app, client = make_app(busy=True, clock=clock)
        app._on_event(ev("message.start"))
        type_text(app, "use the other file")
        app._on_input(CTRL_ENTER)
        steer = len(client.calls)
        if not busy_after:
            app._on_event(ev("message.complete", text="done", status="complete"))
        type_text(app, "an unrelated draft")  # the person moved on
        clock.now += 3600  # far past any call's answer time
        app._expire_calls()
        return app, client, steer

    def test_an_unanswered_steer_during_the_turn_comes_back_and_its_row_leaves_the_live_region(self) -> None:
        app, client, steer = self.steered(Clock(), busy_after=True)
        self.assertEqual(app.composer.text, "an unrelated draft\nuse the other file")
        self.assertFalse(app.queued)  # not queued: Hermes may have taken it
        app._on_event(ev("message.complete", text="done", status="complete"))
        taken = lines_text(app.transcript.take_stable_lines(100, THEME))  # what reaches scrollback
        self.assertNotIn("steer", " ".join(lines_text(app.transcript.live_lines(100, THEME))))  # nothing held back
        self.assertIn(self.BACK, taken)
        self.assertEqual([method for method, _params in client.calls], ["session.steer"])  # nothing sent for it

    def test_an_unanswered_steer_after_its_turn_ended_is_not_sent_as_a_prompt(self) -> None:
        app, client, steer = self.steered(Clock(), busy_after=False)
        self.assertEqual([method for method, _params in client.calls], ["session.steer"])
        self.assertFalse(app._busy())
        self.assertEqual(app.composer.text, "an unrelated draft\nuse the other file")
        app._on_response(Response(steer, {"status": "queued"}, None))  # Hermes' late answer: it had taken it
        self.assertIn(steer, client.forgotten)
        self.assertEqual([method for method, _params in client.calls], ["session.steer"])
        self.assertEqual(app.composer.text, "an unrelated draft\nuse the other file")  # given back once
        rows = [line_text(row) for block in app.transcript.blocks if isinstance(block, SteerBlock)
                for row in block_rows(block, 100, THEME)]
        self.assertEqual(rows, [self.BACK])

    def agent_steered(self, clock: Clock) -> tuple[object, object, int]:
        from test_tui_agent_view import STARTS, agent_app, relay
        from omh.tui.keys import DOWN

        app, client = agent_app(busy=True, frames=[], clock=clock)
        app._on_event(ev("message.start"))
        relay(app, STARTS)
        app._on_input(Key(DOWN))
        app._on_input(Key(CHAR, "s"))
        type_text(app, "skip tests")
        app._on_input(Key(ENTER))
        return app, client, len(client.calls)

    def test_an_unanswered_agent_steer_gives_its_text_back_and_says_hermes_did_not_answer(self) -> None:
        clock = Clock()
        app, client, _steer = self.agent_steered(clock)
        clock.now += 3600
        app._expire_calls()
        self.assertEqual(app.composer.text, "skip tests")
        app._on_event(ev("message.complete", text="done", status="complete"))
        taken = lines_text(app.transcript.take_stable_lines(100, THEME))
        self.assertNotIn("steer", " ".join(lines_text(app.transcript.live_lines(100, THEME))))
        self.assertIn(
            "⧗ back in the composer — Hermes did not answer the steer in 120 s · find usages of: skip tests", taken
        )
        self.assertNotIn("prompt.submit", [method for method, _params in client.calls])

    def test_an_agent_steer_given_back_while_a_masked_question_is_open_stays_out_of_the_answer(self) -> None:
        clock = Clock()
        app, client, _steer = self.agent_steered(clock)
        app._on_server_request(ServerRequest("srq-1", "sudo", {"prompt": "[sudo] password"}))
        clock.now += SLOT_ARM_SECONDS  # keys in the first moment are ignored
        type_text(app, "hunter")  # the answer, masked
        clock.now += 3600
        app._expire_calls()
        self.assertEqual(app.composer.text, "hunter")
        app._on_input(Key(ENTER))
        self.assertEqual(client.answers, [("srq-1", {"result": {"value": "hunter"}})])
        self.assertEqual(app.composer.text, "skip tests")  # back once the question closed

    def test_an_agent_steer_refused_while_a_clarify_question_is_open_stays_out_of_the_answer(self) -> None:
        clock = Clock()
        app, client, steer = self.agent_steered(clock)
        app._on_server_request(ServerRequest("srq-1", "clarify", {"questions": [{"qid": "q0", "question": "Which branch?"}]}))
        clock.now += SLOT_ARM_SECONDS
        type_text(app, "main")
        app._on_response(Response(steer, None, {"code": 4009, "message": "no tool call left."}))
        self.assertEqual(app.composer.text, "main")
        app._on_input(Key(ENTER))
        self.assertEqual(client.answers, [("srq-1", {"result": {"answers": {"q0": "main"}}})])
        self.assertEqual(app.composer.text, "skip tests")
        held = [line for line in lines_text(app.transcript.live_lines(140, THEME)) if "steer" in line]
        self.assertEqual(
            held, ["⧗ back in the composer — Hermes did not take the steer (no tool call left) · find usages of: skip tests"]
        )


class CommandPlacementTests(unittest.TestCase):
    """A command typed while a tool runs is held under it, as a steer is, and never cuts the running call off."""

    COMMANDS = ("/details", "/effort high", "/keys", "/todos", "/model", "/queue", "/steer")  # bare /model, /steer: no echo

    def mid_tool(self, command: str) -> tuple[object, object]:
        app, client = make_app(busy=True)
        app._on_event(ev("message.start"))
        app._on_event(ev("tool.start", tool_id="t1", name="terminal", context="pytest -q"))
        type_text(app, command)
        app._on_input(Key(ENTER))
        if app.pager is not None:  # /keys: the key list, left with q
            app._on_input(Key(CHAR, "q"))
        return app, client

    def test_every_command_mid_tool_leaves_one_call_and_the_done_line_counts_it_once(self) -> None:
        for command in self.COMMANDS:
            with self.subTest(command=command):
                app, _client = self.mid_tool(command)
                group = app.transcript.blocks[-1]
                self.assertIsInstance(group, ToolGroup)
                self.assertFalse(group.done)  # still the live block
                app._on_event(ev("tool.complete", tool_id="t1", name="terminal", result={"output": "1 passed"}))
                app._on_event(ev("message.complete", text="done", status="complete"))
                calls = [(tool.name, tool.status) for block in app.transcript.blocks
                         if isinstance(block, ToolGroup) for tool in block.tools]
                self.assertEqual(calls, [("terminal", TOOL_OK)])
                summaries = [block.tools for block in app.transcript.blocks if isinstance(block, TurnSummaryBlock)]
                self.assertEqual(summaries, [1])

    def test_details_mid_turn_reaches_the_running_call(self) -> None:
        app, _client = self.mid_tool("/details")
        self.assertTrue(app.transcript.details_expanded)
        self.assertIs(type(app.transcript.blocks[-1]), ToolGroup)
        self.assertFalse(app.transcript.blocks[-1].done)

    def test_the_echo_and_its_output_wait_under_the_call_then_land_after_its_group(self) -> None:
        app, _client = self.mid_tool("/queue")
        live = lines_text(app.transcript.live_lines(80, THEME))
        self.assertEqual(live[-2:], ["  ❯ /queue", "    ⎿  Nothing is queued."])  # under what runs, its output under it
        app._on_event(ev("tool.complete", tool_id="t1", name="terminal", result={"output": "1 passed"}))
        app._on_event(ev("message.delta", text="All green."))
        kinds = [type(block).__name__ for block in app.transcript.blocks]
        self.assertEqual(kinds, ["ToolGroup", "CommandBlock", "AssistantBlock"])
        self.assertEqual(app.transcript.blocks[1].parts, [("Nothing is queued.", "info")])

    def test_between_turns_a_command_is_written_at_once(self) -> None:
        app, _client = make_app()
        type_text(app, "/queue")
        app._on_input(Key(ENTER))
        (block,) = app.transcript.blocks
        self.assertEqual((block.command, block.done), ("/queue", True))

    def test_an_echo_still_waiting_for_hermes_stays_held_past_a_boundary_and_is_written_once(self) -> None:
        app, client = self.mid_tool("/usage")
        app._on_event(ev("tool.complete", tool_id="t1", name="terminal", result={"output": "1 passed"}))
        app._on_event(ev("message.delta", text="Checking the cost."))  # a boundary while /usage is still out
        self.assertNotIn("CommandBlock", [type(block).__name__ for block in app.transcript.blocks])
        answer(app, client, {"output": "Session cost: $0.01"})
        app._on_event(ev("message.complete", text="Checking the cost.", status="complete"))
        echoes = [block for block in app.transcript.blocks if type(block).__name__ == "CommandBlock"]
        self.assertEqual([(block.command, block.parts) for block in echoes], [("/usage", [("Session cost: $0.01", "info")])])

    def test_a_commands_call_that_expires_mid_tool_says_so_under_its_echo_and_the_call_runs_on(self) -> None:
        clock = Clock()
        app, _client = make_app(busy=True, clock=clock)
        app._on_event(ev("message.start"))
        app._on_event(ev("tool.start", tool_id="t1", name="terminal", context="pytest -q"))
        type_text(app, "/usage")
        app._on_input(Key(ENTER))
        clock.now += 3600
        app._expire_calls()
        group = app.transcript.blocks[-1]
        self.assertIsInstance(group, ToolGroup)
        self.assertEqual(group.tools[0].status, TOOL_RUNNING)
        self.assertEqual(lines_text(app.transcript.live_lines(140, THEME))[-2:],
                         ["  ❯ /usage", "    ⎿  ⚠ Hermes has not answered slash.exec in 120 s; the OMH TUI stopped waiting for it."])

    def usage_out_past_the_turn(self) -> tuple[object, object, int]:
        """`/usage` typed over a running tool, the turn ended with it still out, and the next prompt streaming."""
        app, client = self.mid_tool("/usage")
        usage = len(client.calls)
        app._on_event(ev("tool.complete", tool_id="t1", name="terminal", result={"output": "1 passed"}))
        app._on_event(ev("message.complete", text="done", status="complete"))
        type_text(app, "next prompt")
        app._on_input(Key(ENTER))
        app._on_event(ev("message.start"))
        app._on_event(ev("message.delta", text="Second reply "))
        return app, client, usage

    def test_a_command_still_out_at_the_turns_end_is_written_above_that_turns_done_line(self) -> None:
        app, client, usage = self.usage_out_past_the_turn()
        kinds = [type(block).__name__ for block in app.transcript.blocks]
        self.assertEqual(kinds[:4], ["ToolGroup", "AssistantBlock", "CommandBlock", "TurnSummaryBlock"])
        self.assertEqual(app.transcript.blocks[2].command, "/usage")  # dated in the turn it was typed in
        app._on_response(Response(usage, {"output": "Session cost: $0.01"}, None))
        app._on_event(ev("message.complete", text="Second reply done.", status="complete"))
        replies = [block.text for block in app.transcript.blocks if isinstance(block, AssistantBlock)]
        self.assertEqual(replies, ["done", "Second reply done."])  # the late output did not split the reply
        echoes = [(block.command, block.parts) for block in app.transcript.blocks if isinstance(block, CommandBlock)]
        self.assertEqual(echoes, [("/usage", []), ("/usage", [("Session cost: $0.01", "info")])])
        kinds = [type(block).__name__ for block in app.transcript.blocks]
        self.assertEqual(kinds[-3:], ["AssistantBlock", "CommandBlock", "TurnSummaryBlock"])  # under a repeat echo

    def test_a_refusal_that_comes_after_the_turns_end_goes_under_a_repeat_echo_and_splits_no_reply(self) -> None:
        app, client, usage = self.usage_out_past_the_turn()
        app._on_response(Response(usage, None, {"code": 5000, "message": "usage is unavailable"}))
        app._on_event(ev("message.delta", text="goes on."))
        replies = [block.text for block in app.transcript.blocks if isinstance(block, AssistantBlock)]
        self.assertEqual(replies, ["done", "Second reply goes on."])
        held = lines_text(app.transcript.live_lines(100, THEME))
        self.assertEqual(held[-2:], ["  ❯ /usage", "    ⎿  ✗ Usage is unavailable."])

    def test_output_for_an_echo_already_closed_waits_under_a_running_call(self) -> None:
        app, client = make_app()
        type_text(app, "/usage")
        app._on_input(Key(ENTER))
        type_text(app, "run the tests")
        app._on_input(Key(ENTER))  # the prompt closes the echo; /usage is still out
        app._on_event(ev("message.start"))
        app._on_event(ev("tool.start", tool_id="t1", name="terminal", context="pytest -q"))
        app._on_response(Response(1, {"output": "Session cost: $0.01"}, None))
        group = app.transcript.blocks[-1]
        self.assertIsInstance(group, ToolGroup)
        self.assertEqual(group.tools[0].status, TOOL_RUNNING)  # the repeated echo did not cut the call off
        self.assertEqual(lines_text(app.transcript.live_lines(80, THEME))[-2:], ["  ❯ /usage", "    ⎿  Session cost: $0.01"])


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class TurnDoneLineTests(unittest.TestCase):
    def test_a_turn_closes_with_its_facts_in_one_dim_line_and_no_rule(self) -> None:
        (row,) = block_rows(TurnSummaryBlock(34, 3, 1200), 50, THEME)
        self.assertEqual(line_text(row), "  ✻ 34s · 3 tools · ↓1.2k")
        self.assertNotIn("─", line_text(row))  # no rule (the rule and the glyphs now share the one neutral grey)

    def test_a_turn_without_tools_says_nothing_of_tools(self) -> None:
        (row,) = block_rows(TurnSummaryBlock(2, 0, 40), 30, THEME)
        self.assertEqual(line_text(row), "  ✻ 2s · ↓40")


class FinishedPlanTests(unittest.TestCase):
    """A plan whose every item is done leaves the panel once no turn runs, as Claude Code's list goes once done."""

    OPEN = phased_plan(3, phases=1, active=2)
    DONE = [dict(item, state="done") for item in phased_plan(3, phases=1, active=2)]

    def setUp(self) -> None:
        self.app, _client = make_app(rows=30, cols=100)
        self.app.stored_id = "stored"

    def take(self, items: list[dict]) -> None:
        """A HUD read the poller hands over, as `_take_hud` takes it."""
        snapshot = HudSnapshot("stored", hud_payload(items), 100.0)
        self.app.poller.take = lambda: snapshot  # type: ignore[method-assign]
        self.app._take_hud()

    def headers(self) -> list[str]:
        # The header's right edge names what Ctrl+P does now (`ctrl+p fold`); the plan's own words come before it.
        return [re.sub(r" {2,}ctrl\+p (fold|expand)$", "", row) for row in drawn(self.app) if row.startswith("[Plan]")]

    def notices(self) -> list[str]:
        return [block.text for block in self.app.transcript.blocks if isinstance(block, NoticeBlock)]

    def turn(self, prompt: str) -> None:
        self.app._submit_prompt(prompt)
        self.app._on_event(ev("message.start"))

    def test_the_turn_that_finishes_the_plan_ends_with_it_in_the_transcript_and_off_the_panel(self) -> None:
        self.take(self.OPEN)
        self.turn("finish the plan")
        self.assertEqual(self.headers(), ["[Plan] Plan │ 2/3"])
        self.take(self.DONE)
        self.assertEqual(self.headers(), ["[Plan] Plan │ ✓ 3/3"])  # still the turn's: it shows done until the turn ends
        self.app._on_event(ev("message.complete", text="Done.", status="complete"))
        self.assertEqual(self.headers(), [])
        # The retired header reads as the live one did a moment before (review B NIT 3).
        self.assertEqual(self.notices(), ["\n".join(["[Plan] Plan │ ✓ 3/3", "Phase 0", "  [✓] Task number 0",
                                                     "  [✓] Task number 1", "  [✓] Task number 2"])])
        kinds = [type(block).__name__ for block in self.app.transcript.blocks]
        self.assertLess(kinds.index("NoticeBlock"), kinds.index("TurnSummaryBlock"))  # above the done line
        self.turn("something unrelated")
        self.take(self.DONE)  # the next poll still reads the finished plan
        self.assertEqual(self.headers(), [])
        self.assertEqual(len(self.notices()), 1)

    def test_a_plan_already_finished_when_the_session_opens_is_not_drawn_and_says_nothing(self) -> None:
        self.take(self.DONE)
        self.assertEqual((self.headers(), self.notices()), ([], []))

    def test_a_plan_with_an_item_left_stays_between_turns_and_a_new_plan_is_drawn_again(self) -> None:
        self.take(self.OPEN)
        self.turn("start it")
        self.app._on_event(ev("message.complete", text="Later.", status="complete"))
        self.assertEqual(self.headers(), ["[Plan] Plan │ 2/3"])
        self.take(self.DONE)  # finished between turns, by a poll
        self.assertEqual(self.headers(), [])
        self.take(phased_plan(4, phases=1, active=0))
        self.assertEqual(self.headers(), ["[Plan] Plan │ 0/4"])


class SettledTailTests(unittest.TestCase):
    """The rows a settled tool group gives back are filled by its own lines, never left blank under the done line."""

    def app_with_plan(self, rows: int, cols: int, earlier: int) -> tuple[object, list[float]]:
        now = [100.0]
        app, _client = make_app(rows=rows, cols=cols, clock=lambda: now[0])
        app.stored_id = "stored"
        app.hud = HudSnapshot("stored", hud_payload(phased_plan(4, phases=1, active=1)), now[0])
        for index in range(earlier):  # transcript rows above the region before the turn
            app.transcript.add_notice(f"earlier line {index}")
        app._render()
        return app, now

    def test_the_done_line_sits_one_spacer_row_above_the_panel_however_tall_the_last_group_was(self) -> None:
        for tools in (1, 4, 12):
            with self.subTest(tools=tools):
                app, now = self.app_with_plan(40, 100, earlier=60)  # a screen already full of transcript
                app._submit_prompt("run the tools")
                app._render()
                app._on_event(ev("message.start"))
                for index in range(tools):
                    now[0] += 0.1
                    app._on_event(ev("tool.start", tool_id=f"t{index}", name="read_file", context=f"f{index}.py"))
                    app._render()
                for index in range(tools):
                    app._on_event(ev("tool.complete", tool_id=f"t{index}", name="read_file", result={"content": "x"}))
                    app._render()
                app._on_event(ev("message.delta", text="All read."))
                app._render()
                app._on_event(ev("message.complete", text="All read.", status="complete"))
                app._render()
                screen = app.terminal.screen.lines()
                plan = next(index for index, line in enumerate(screen) if "[Plan]" in line)
                done = max(index for index, line in enumerate(screen[:plan]) if line.startswith("  ✻ "))
                # The spacer row every block opens with, then the panel. On the bottom rows the region keeps its
                # height as the turn ends, but not the rows only the running turn had and nothing takes at its end:
                # the blank row over the plan (2026-10-27 spacing) and, under a tall group, the sticky prompt row
                # and the blank row over it. Those stood here as blank rows until the next prompt (the owner's report
                # of 2026-10-28); the region gives them up and the composer rises by them.
                self.assertEqual(plan - done - 1, 1, "\n".join(screen[done - 1 : plan + 1]))
                self.assertEqual(set(screen[done + 1 : plan]), {""}, "\n".join(screen[done - 1 : plan + 1]))

    def test_the_prompt_and_its_sticky_echo_are_never_on_screen_together(self) -> None:
        # A reply streams line by line under the prompt: the prompt shows until it scrolls off, the echo after.
        for rows, cols, earlier in ((24, 80, 0), (24, 80, 60), (40, 100, 0), (40, 100, 60)):
            with self.subTest(rows=rows, cols=cols, earlier=earlier):
                app, now = self.app_with_plan(rows, cols, earlier)
                app._submit_prompt("run the tools")
                app._render()
                app._on_event(ev("message.start"))
                app._render()
                echoed = 0
                for index in range(rows * 2):
                    now[0] += 0.05
                    app._on_event(ev("message.delta", text=f"line {index}\n"))
                    app._render()
                    screen = app.terminal.screen.lines()
                    prompt = any(line.startswith("  ❯ run the tools") for line in screen)
                    echo = any(line.startswith("↳ you: run the tools") for line in screen)
                    self.assertFalse(prompt and echo, f"line {index}: the prompt and its echo are both on screen")
                    self.assertTrue(prompt or echo, f"line {index}: the prompt scrolled off and nothing echoes it")
                    echoed += echo
                self.assertGreater(echoed, 0, "the prompt never scrolled off")

    def assert_prompt_xor_echo(self, app: object, where: str) -> bool:
        """Exactly one of the prompt and its sticky echo is on screen; True when it is the echo."""
        screen = app.terminal.screen.lines()  # type: ignore[attr-defined]
        prompt = any(line.startswith("  ❯ run the tools") for line in screen)
        echo = any(line.startswith("↳ you: run the tools") for line in screen)
        self.assertFalse(prompt and echo, f"{where}: the prompt and its echo are both on screen\n" + "\n".join(screen))
        self.assertTrue(prompt or echo, f"{where}: the prompt scrolled off and nothing echoes it")
        return echo

    def test_a_tall_tool_batch_never_shows_the_prompt_and_its_echo_together(self) -> None:
        # The blank row above the prompt is not the prompt's: counted, the echo came one row early, over the prompt.
        shapes = ((24, 80, 60, 8), (24, 80, 60, 14), (24, 80, 0, 14), (40, 100, 60, 14), (24, 80, 0, 2), (40, 100, 0, 2),
                  (40, 100, 0, 8))
        for rows, cols, earlier, tools in shapes:
            with self.subTest(rows=rows, cols=cols, earlier=earlier, tools=tools):
                app, now = self.app_with_plan(rows, cols, earlier)
                app._submit_prompt("run the tools")
                app._render()
                app._on_event(ev("message.start"))
                app._render()
                for index in range(tools):
                    now[0] += 0.1
                    app._on_event(ev("tool.start", tool_id=f"t{index}", name="read_file", context=f"f{index}.py"))
                    app._render()
                    self.assert_prompt_xor_echo(app, f"tool {index} started")
                for index in range(tools):
                    app._on_event(ev("tool.complete", tool_id=f"t{index}", name="read_file", result={"content": "x"}))
                    app._render()
                    self.assert_prompt_xor_echo(app, f"tool {index} completed")

    def test_the_frame_and_its_flush_are_one_write_so_no_state_between_them_shows(self) -> None:
        # Written apart, the frame (echo drawn) showed for a moment over the prompt the flush had not yet moved.
        from omh.tui.screen import SYNC_BEGIN

        for rows, cols, earlier, tools in ((24, 80, 0, 14), (24, 80, 60, 8), (40, 100, 0, 14)):
            with self.subTest(rows=rows, cols=cols, earlier=earlier, tools=tools):
                app, now = self.app_with_plan(rows, cols, earlier)
                app._submit_prompt("run the tools")
                app._render()
                screen = app.terminal.screen
                feed = screen.feed
                synced: list[int] = []

                def checked(text: str) -> None:  # every write reaches the screen as one feed
                    feed(text)
                    synced[-1] += text.count(SYNC_BEGIN)
                    self.assert_prompt_xor_echo(app, "after one write")

                screen.feed = checked  # type: ignore[method-assign]
                events = [ev("message.start")]
                events += [ev("tool.start", tool_id=f"t{n}", name="read_file", context=f"f{n}.py") for n in range(tools)]
                events += [ev("tool.complete", tool_id=f"t{n}", name="read_file", result={"content": "x"}) for n in range(tools)]
                events += [ev("message.delta", text=f"reply {n}\n") for n in range(rows)]  # the group settles at once
                for event in events:
                    now[0] += 0.1
                    app._on_event(event)
                    synced.append(0)
                    app._render()
                self.assertLessEqual(max(synced), 1, "a render wrote more than one synchronized update")
                self.assertIn(1, synced)

    def test_a_resize_redraw_mid_turn_never_shows_the_prompt_and_its_echo_together(self) -> None:
        # The redraw takes the session again from its top: only the rows from the prompt on are the prompt's,
        # and the banner it prints again ahead of them is not.
        cases = ((40, 100, 0, False), (40, 100, 60, False), (24, 80, 0, False), (24, 80, 60, False), (24, 80, 0, True))
        for rows, cols, earlier, banner in cases:
            with self.subTest(rows=rows, cols=cols, earlier=earlier, banner=banner):
                app, now = self.app_with_plan(rows, cols, earlier)
                if banner:
                    app.banner_record = {"cwd": "~/project", "resumed": ""}
                app._submit_prompt("run the tools")
                app._render()
                app._on_event(ev("message.start"))
                app._render()
                for index in range(2):
                    now[0] += 0.05
                    app._on_event(ev("message.delta", text=f"line {index}\n"))
                    app._render()
                app.terminal.screen.resize(rows, cols - 10)  # type: ignore[attr-defined]
                app._on_resize()
                now[0] += 1.0
                app._render_when_due()
                self.assert_prompt_xor_echo(app, "after the resize redraw")
                echoed = False
                for index in range(2, rows * 2):
                    now[0] += 0.05
                    app._on_event(ev("message.delta", text=f"line {index}\n"))
                    app._render()
                    echoed = self.assert_prompt_xor_echo(app, f"line {index} after the redraw") or echoed
                self.assertTrue(echoed, "the prompt never scrolled off after the redraw")


class ApprovalOutcomeTests(unittest.TestCase):
    COMMAND = "rm -rf ./build"

    def asked(self) -> tuple[object, object, Clock]:
        clock = Clock()
        app, client = make_app(busy=True, clock=clock)
        app._on_event(ev("message.start"))
        app._on_event(ev("tool.start", tool_id="t1", name="terminal", context=self.COMMAND))
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": self.COMMAND, "description": "delete"}))
        clock.now += SLOT_ARM_SECONDS + 0.1
        return app, client, clock

    def outcome(self, app: object) -> tuple[str, object]:
        """The first row under the call's row, and its mark's style: where the answer is written (after the rail)."""
        (group,) = app.transcript.blocks  # type: ignore[attr-defined]
        row = block_rows(group, 80, THEME)[1]
        return line_text(row), row[4].style

    def test_a_denial_reads_in_red_under_the_call_and_leaves_it_running(self) -> None:
        app, client, _clock = self.asked()
        app._on_input(Key(CHAR, "d"))
        self.assertEqual(client.answers, [("srq-1", {"result": {"choice": "deny"}})])
        self.assertEqual(self.outcome(app), (f"    ⎿  ✗ denied · {self.COMMAND}", THEME.error))
        (group,) = app.transcript.blocks
        self.assertEqual(group.tools[0].status, TOOL_RUNNING)  # Hermes reports what the call did next

    def test_allowing_reads_in_green(self) -> None:
        for keys, words in (([Key(RIGHT)], "allowed once"), ([Key(RIGHT), Key(RIGHT)], "allowed for this session")):
            with self.subTest(words=words):
                app, _client, _clock = self.asked()
                for key in (*keys, Key(ENTER)):
                    app._on_input(key)
                self.assertEqual(self.outcome(app), (f"    ⎿  ✓ {words} · {self.COMMAND}", THEME.ok))

    def test_the_denied_path_reads_in_order_under_its_call(self) -> None:
        app, _client, _clock = self.asked()
        app._on_input(Key(CHAR, "d"))
        blocked = {"output": "", "exit_code": -1, "status": "blocked", "error": None,
                   "user_summary": "You denied this command — it did not run."}
        app._on_event(ev("tool.complete", tool_id="t1", name="terminal", duration_s=0.1, result=blocked))
        app._on_event(ev("message.complete", text="", status="interrupted"))
        rows = [row for row in lines_text(app.transcript.take_stable_lines(80, REPORTED)) if row]
        self.assertTrue(rows[0].startswith(f"  ✗ terminal({self.COMMAND})"), rows)
        # One mark for a denial (round 2): the call's red `✗`; its answer row keeps its words and drops its own.
        self.assertEqual(rows[1:4], [f"    ⎿  denied · {self.COMMAND}", "    ⎿  You denied this command — it did not run.",
                                     "⚠ Interrupted."])
        self.assertEqual(sum(row.count("✗") for row in rows[:3]), 1)

    def test_the_answer_goes_under_the_call_that_asked_not_the_first_of_the_turn(self) -> None:
        # Review B: `✓ allowed once · …` stood above `⏺ read_file(README.md)`, the turn's first call.
        app, _client, clock = self.asked_after_a_read()
        app._on_input(Key(RIGHT))
        app._on_input(Key(ENTER))
        (group,) = app.transcript.blocks
        rows = lines_text(block_rows(group, 80, THEME))
        self.assertEqual(rows, ["  ● read_file(README.md)  0.1s", "    ⎿  Read 1 line", "", f"  ○ terminal({self.COMMAND})",
                                f"    ⎿  ✓ allowed once · {self.COMMAND}"])

    def asked_after_a_read(self) -> tuple[object, object, Clock]:
        clock = Clock()
        app, client = make_app(busy=True, clock=clock)
        app._on_event(ev("message.start"))
        app._on_event(ev("tool.start", tool_id="t0", name="read_file", context="README.md"))
        app._on_event(ev("tool.complete", tool_id="t0", name="read_file", duration_s=0.1, result={"content": "hello"}))
        app._on_event(ev("tool.start", tool_id="t1", name="terminal", context=self.COMMAND))
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": self.COMMAND, "description": "delete"}))
        clock.now += SLOT_ARM_SECONDS + 0.1
        return app, client, clock

    def test_each_answer_goes_under_the_last_running_call_of_its_kind(self) -> None:
        # A request names no call: a clarify answer goes under the last running `clarify`, any other answer under
        # the last running other call.
        clock = Clock()
        app, _client = make_app(busy=True, clock=clock)
        app._on_event(ev("message.start"))
        app._on_event(ev("tool.start", tool_id="t1", name="terminal", context="sleep 30"))
        app._on_event(ev("tool.start", tool_id="t2", name="clarify", context="Which colour?"))
        app._on_event(ev("tool.start", tool_id="t3", name="terminal", context=self.COMMAND))
        question = {"questions": [{"qid": "q0", "question": "Which colour?", "choices": ["red", "blue"]}]}
        app._on_server_request(ServerRequest("srq-2", "clarify", question))
        clock.now += SLOT_ARM_SECONDS + 0.1
        app._on_input(Key(ENTER))
        app._on_server_request(ServerRequest("srq-3", "approval", {"command": self.COMMAND, "description": "delete"}))
        clock.now += SLOT_ARM_SECONDS + 0.1
        app._on_input(Key(CHAR, "d"))
        (group,) = app.transcript.blocks
        self.assertEqual([tool.answers for tool in group.tools],
                         [[], [("red · Which colour?", NOTICE_OK)], [(f"denied · {self.COMMAND}", NOTICE_ERROR)]])

    def test_with_every_call_of_the_live_group_finished_the_answer_is_a_row_of_its_own(self) -> None:
        # A subagent's approval can arrive after the turn's own calls finished: none of them asked it.
        app, _client, _clock = self.asked_after_a_read()
        app._on_event(ev("tool.complete", tool_id="t1", name="terminal", duration_s=0.1, result={"output": ""}))
        app._on_input(Key(RIGHT))
        app._on_input(Key(ENTER))
        notice, group = app.transcript.blocks
        self.assertEqual((notice.text, notice.level), (f"allowed once · {self.COMMAND}", NOTICE_OK))
        self.assertEqual([tool.answers for tool in group.tools], [[], []])

    def test_a_clarify_hermes_withdraws_is_answered_under_the_clarify_not_the_call_beside_it(self) -> None:
        app, _client = make_app(busy=True, clock=Clock())
        app._on_event(ev("message.start"))
        app._on_event(ev("tool.start", tool_id="t1", name="clarify", context="Which colour?"))
        app._on_event(ev("tool.start", tool_id="t2", name="terminal", context="sleep 30"))
        question = {"questions": [{"qid": "q0", "question": "Which colour?", "choices": ["red", "blue"]}]}
        app._on_server_request(ServerRequest("srq-2", "clarify", question))
        app._on_withdrawn({"id": "srq-2", "reason": "timeout"})
        (group,) = app.transcript.blocks
        self.assertEqual([tool.answers for tool in group.tools], [[("timed out · Which colour?", NOTICE_ERROR)], []])

    def test_a_clarify_that_closed_unanswered_says_so_once_under_its_call(self) -> None:
        # Hermes withdraws the request (`timeout`) or the person cancels it, then the clarify returns its `outcome`:
        # the answer row already says how the wait ended. A notice of Hermes' says why, and stays. The call's red `✗`
        # is the one mark (#2223 review 8): the answer row under it keeps its words.
        cases = (
            ("timeout", "timed_out", "", ["    ⎿  timed out · Which colour?"]),
            ("timeout", "timed_out", "No answer within 300 s.",
             ["    ⎿  timed out · Which colour?", "    ⎿  No answer within 300 s."]),
            ("", "cancelled", "", ["    ⎿  cancelled · Which colour?"]),
        )
        for reason, outcome, notice, under in cases:
            with self.subTest(outcome=outcome, notice=notice):
                clock = Clock()
                app, _client = make_app(busy=True, clock=clock)
                app._on_event(ev("message.start"))
                app._on_event(ev("tool.start", tool_id="t1", name="clarify", context="Which colour?"))
                question = {"questions": [{"qid": "q0", "question": "Which colour?", "choices": ["red", "blue"]}]}
                app._on_server_request(ServerRequest("srq-2", "clarify", question))
                if reason:
                    app._on_withdrawn({"id": "srq-2", "reason": reason})
                else:
                    clock.now += SLOT_ARM_SECONDS + 0.1
                    app._on_input(Key(ESCAPE))
                result = {"responses": [], "outcome": outcome, **({"notice": notice} if notice else {})}
                app._on_event(ev("tool.complete", tool_id="t1", name="clarify", result=result))
                (group,) = app.transcript.blocks
                rows = lines_text(block_rows(group, 80, THEME))
                self.assertTrue(rows[0].startswith("  ✗ clarify(Which colour?)"), rows)
                self.assertEqual(rows[1:], under)

    def test_over_a_streaming_reply_the_answer_waits_for_the_boundary(self) -> None:
        clock = Clock()
        app, _client = make_app(busy=True, clock=clock)
        app._on_event(ev("message.start"))
        app._on_event(ev("message.delta", text="Deleting it now"))
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": self.COMMAND}))
        clock.now += SLOT_ARM_SECONDS + 0.1
        app._on_input(Key(CHAR, "d"))
        app._on_event(ev("message.delta", text=", or not: you said no."))
        app._on_event(ev("message.complete", text="Deleting it now, or not: you said no.", status="complete"))
        kinds = [type(block).__name__ for block in app.transcript.blocks]
        self.assertEqual(kinds[:2], ["AssistantBlock", "NoticeBlock"])
        self.assertEqual([block.text for block in app.transcript.blocks if isinstance(block, AssistantBlock)],
                         ["Deleting it now, or not: you said no."])  # one reply, not split by the answer



class NewSessionSpacerTests(unittest.TestCase):
    def test_the_new_sessions_first_line_is_set_off_from_the_last_session_by_a_spacer(self) -> None:
        # Review B NIT 8: `· New session <id>.` sat right under the previous session's done line.
        from test_tui_modes import drawn, make_app

        app, _client = make_app(rows=24, cols=80)
        app._on_input(Key(CHAR, "l", ctrl=True))
        app._submit_prompt("hello")
        app._on_event(ev("message.start"))
        app._on_event(ev("message.complete", text="Hi.", status="complete"))
        drawn(app)
        app._on_new_session({"session_id": "live-2", "stored_session_id": "stored-2"})
        screen = drawn(app)
        row = next(index for index, line in enumerate(screen) if "New session stored-2." in line)
        self.assertEqual(screen[row - 1], "")
        self.assertTrue(screen[row - 2].startswith("  ✻"), screen)  # the done line, one blank row above
        app._full_redraw()  # a redraw starts the new session's transcript at the top: no spacer over it
        self.assertTrue(drawn(app)[0].strip())


if __name__ == "__main__":
    unittest.main()

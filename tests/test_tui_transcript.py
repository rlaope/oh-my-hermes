"""The OMH TUI transcript model and its flush policy (`omh.tui.transcript`).

Event payloads are copied from real Hermes 6c61c3e27d `tui_gateway` recordings
(`tests/fixtures/tui_gateway/`, session and approval), trimmed to the fields the
transcript reads. Every step of every sequence runs through `LoopTestCase.step`,
which plays the app loop (apply, take stable lines, read live lines) and holds
the inline-scrollback invariant: the lines taken so far followed by the live
lines equal `history_lines(details=False)`. So no line is ever taken twice,
none goes missing, and nothing already in scrollback would need a repaint.
"""

from __future__ import annotations

from dataclasses import replace
import time
import unicodedata
import unittest
from unittest.mock import patch

from _tui_lines import lines_text
from omh.tui import markdown
from omh.tui.gateway import Event
from omh.tui.style import Line, Span
from omh.tui import transcript as transcript_module
from omh.skin_pack import default_theme
from omh.tui.theme import DEFAULT_THEME as THEME
from omh.tui.theme import with_launch_look
from omh.tui.transcript import (
    STEER_QUEUED,
    GUTTER,
    OUTPUT_PREVIEW_ROWS,
    AssistantBlock,
    CommandBlock,
    SteerBlock,
    ThinkingBlock,
    ToolGroup,
    ToolRow,
    Transcript,
    block_rows,
    rail_cell,
    tool_result_status,
)
from omh.tui.width import is_control, line_width

SID = "b6af062a"
WIDTH = 60
REPLY_RAIL = (rail_cell(THEME.brand), Span(" ", GUTTER))  # what a reply's rows hang on

PLAIN_ANSWER = "ok\n\nI'm Hermes, your agent — `/help` lists the commands."
DENIED_RESULT = {
    "output": "",
    "exit_code": -1,
    "error": "BLOCKED: Command denied by user. The user has NOT consented to this action.",
    "status": "blocked",
    "user_summary": "You denied this command — it did not run.",
}


def ev(event_type: str, /, **payload: object) -> Event:
    return Event(type=event_type, session_id=SID, payload=dict(payload))


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class LoopTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.transcript = Transcript(clock=self.clock)
        self.taken: list[Line] = []

    def step(self, event: Event | None = None, *, at: float | None = None, width: int = WIDTH) -> list[str]:
        """One frame of the app loop; returns the texts of the lines this frame flushed."""
        if at is not None:
            self.clock.now = at
        if event is not None:
            self.transcript.apply(event)
        fresh = self.transcript.take_stable_lines(width, THEME)
        self.assertEqual(self.transcript.take_stable_lines(width, THEME), [], "a line was offered twice")
        self.taken.extend(fresh)
        live = self.transcript.live_lines(width, THEME)
        self.assertEqual(self.taken + live, self.transcript.history_lines(width, THEME, details=False))
        for rows in (1, 2, 5):  # asked for its last rows only, the tail ends exactly as the whole one does
            self.assertEqual(self.transcript.live_lines(width, THEME, max_rows=rows)[-rows:], live[-rows:])
        return lines_text(fresh)

    def user(self, text: str) -> list[str]:
        self.transcript.add_user(text)
        return self.step()

    def live(self, width: int = WIDTH) -> list[str]:
        return lines_text(self.transcript.live_lines(width, THEME))

    def history(self, details: bool = True) -> list[str]:
        return lines_text(self.transcript.history_lines(WIDTH, THEME, details=details))


class LiveTailMemoTests(LoopTestCase):
    """The live tail is rendered again only when the transcript changed: a spinner tick re-renders nothing."""

    def no_render(self, *args: object, **kwargs: object) -> list:
        raise AssertionError("the live tail was rendered again")

    def test_an_unchanged_tail_is_not_rendered_again_and_any_change_is(self) -> None:
        self.user("go")
        self.step(ev("message.start"))
        self.step(ev("message.delta", text="a paragraph that has not ended yet " * 20))
        self.step(ev("reasoning.delta", text="still thinking"))
        before = self.transcript.live_lines(WIDTH, THEME)
        with patch("omh.tui.transcript.render_lines", self.no_render), patch("omh.tui.transcript.block_rows", self.no_render):
            self.assertEqual(self.transcript.live_lines(WIDTH, THEME), before)
        self.step(ev("reasoning.delta", text=" and more"))
        self.assertIn("▸ thinking… still thinking and more", self.live())
        self.transcript.toggle_details()
        self.assertEqual(self.live()[-1], "  still thinking and more")
        self.assertEqual(lines_text(self.transcript.live_lines(14, THEME))[-3:], ["  still", "  thinking and", "  more"])

    def test_a_tail_asked_for_fewer_rows_renders_only_the_blocks_it_needs(self) -> None:
        # Nothing taken yet (no frame between the events), so every block is still in the live tail.
        self.transcript.add_user("go")
        self.transcript.apply(ev("message.start"))
        self.transcript.apply(ev("reasoning.delta", text="first thought"))
        self.transcript.apply(ev("tool.start", tool_id="t1", name="terminal", context="ls"))
        self.assertEqual(len(lines_text(self.transcript.live_lines(WIDTH, THEME))), 5)
        rendered: list[object] = []
        real = __import__("omh.tui.transcript", fromlist=["block_rows"]).block_rows

        def counting(block: object, *args: object, **kwargs: object) -> list:
            rendered.append(block)
            return real(block, *args, **kwargs)

        with patch("omh.tui.transcript.block_rows", counting):
            self.assertEqual(lines_text(self.transcript.live_lines(WIDTH, THEME, max_rows=1))[-1:], ["  ○ terminal(ls)"])
        self.assertEqual(rendered, [self.transcript.blocks[-1]])

    def test_only_the_last_block_is_ever_live(self) -> None:
        # Why `_render_live` gives the whole limit to the block it renders first: live thinking is always that block.
        self.transcript.add_user("go")
        for event in (
            ev("message.start"),
            ev("reasoning.delta", text="first thought"),
            ev("tool.start", tool_id="t1", name="terminal", context="ls"),
            ev("reasoning.delta", text="second thought"),
            ev("message.delta", text="an answer"),
        ):
            self.transcript.apply(event)
            self.assertEqual([block for block in self.transcript.blocks[:-1] if not block.done], [])
        self.assertEqual(
            [type(block).__name__ for block in self.transcript.blocks],
            ["UserBlock", "ThinkingBlock", "ToolGroup", "ThinkingBlock", "AssistantBlock"],
        )


class LimitedThinkingTests(LoopTestCase):
    def test_expanded_live_thinking_asked_for_its_last_rows_wraps_only_its_last_lines(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("reasoning.delta", text="\n".join(f"thought number {n} goes on for a while" for n in range(200))))
        self.transcript.toggle_details()  # expanded, the live block is no longer what history shows: no `step` now
        whole = self.transcript.live_lines(WIDTH, THEME)
        wrapped: list[object] = []
        real = __import__("omh.tui.transcript", fromlist=["wrap_prefixed"]).wrap_prefixed

        def counting(*args: object, **kwargs: object) -> list:
            wrapped.append(args[0])
            return real(*args, **kwargs)

        with patch("omh.tui.transcript.wrap_prefixed", counting):
            last = self.transcript.live_lines(WIDTH, THEME, max_rows=4)
        self.assertEqual(last[-4:], whole[-4:])
        self.assertEqual(lines_text(last)[-1], "  thought number 199 goes on for a while")
        self.assertEqual(len(wrapped), 4)  # one source line per row here, not all 200

    def test_any_limit_ends_as_the_whole_expanded_thinking_does(self) -> None:
        text = "\n\nfirst line\n\n" + "a long line that wraps over several rows at this width " * 4 + "\nlast\n\n"
        self.step(ev("message.start"))
        self.step(ev("reasoning.delta", text=text))
        self.transcript.toggle_details()
        whole = self.transcript.live_lines(30, THEME)
        for rows in range(1, len(whole) + 2):
            with self.subTest(rows=rows):
                self.assertEqual(self.transcript.live_lines(30, THEME, max_rows=rows)[-rows:], whole[-rows:])


class SpacingTests(LoopTestCase):
    def test_one_blank_row_separates_blocks_and_none_opens_the_transcript(self) -> None:
        self.user("first")
        self.step(ev("message.start"))
        self.step(ev("reasoning.delta", text="thinking it over"))
        self.step(ev("tool.start", tool_id="t1", name="terminal", context="ls"))
        self.step(ev("tool.complete", tool_id="t1", name="terminal", result={"exit_code": 0}, duration_s=0.5))
        self.step(ev("message.delta", text="done\n"))
        self.step(ev("message.complete", text="done", status="complete"))
        self.user("second")
        expected = ["  ❯ first", "", "▸ thought for 0.0s", "", "  ● terminal(ls)  0.5s", "", "  ⚚ Hermes", "    done", "", "  ❯ second"]
        self.assertEqual(lines_text(self.taken), expected)
        self.assertEqual(self.history(details=False), expected)

    def test_a_resumed_reply_renders_like_a_streamed_one(self) -> None:
        self.user("hi")
        self.transcript.add_assistant("**hello** there\n\n```sh\nls\n```")
        self.transcript.add_assistant("   ")
        self.assertEqual(self.step(), ["", "  ⚚ Hermes", "    hello there", " ", "    sh", "    ls"])
        self.assertEqual(len(self.transcript.blocks), 2)


class PromptRowTests(LoopTestCase):
    """`prompt_row`: where the last take's lines hold the newest prompt's first row; None when they hold no prompt."""

    def take(self) -> list[str]:
        return lines_text(self.transcript.take_stable_lines(WIDTH, THEME))

    def test_only_a_prompt_sets_it_after_the_blank_row_above_it(self) -> None:
        self.transcript.add_notice("a notice")
        self.assertTrue(self.take())
        self.assertIsNone(self.transcript.prompt_row)
        self.transcript.add_user("first")
        taken = self.take()
        self.assertEqual(self.transcript.prompt_row, 1)  # the blank row above the prompt is not the prompt's
        self.assertEqual(taken[1], "  ❯ first")
        for event in (ev("message.start"), ev("tool.start", tool_id="t1", name="terminal", context="ls"),
                      ev("tool.complete", tool_id="t1", name="terminal", result={"exit_code": 0}, duration_s=0.5)):
            self.transcript.apply(event)
        self.transcript.apply(ev("message.delta", text="done\n"))  # the tool group settles: a take with no prompt
        self.assertTrue(self.take())
        self.assertIsNone(self.transcript.prompt_row)
        self.assertEqual(self.take(), [])
        self.assertIsNone(self.transcript.prompt_row)  # an empty take holds no prompt either


class RetakeTests(LoopTestCase):
    def test_retake_offers_the_whole_transcript_again_at_a_new_width(self) -> None:
        self.user("first question that is long enough to wrap at a narrow width")
        self.step(ev("message.start"))
        self.step(ev("message.delta", text="line one of the answer\nline two is still streaming"))
        self.transcript.retake()
        narrow = self.transcript.take_stable_lines(30, THEME)
        live = self.transcript.live_lines(30, THEME)
        self.assertEqual(narrow + live, self.transcript.history_lines(30, THEME, details=False))
        self.assertEqual(self.transcript.take_stable_lines(30, THEME), [], "a retaken line was offered twice")
        self.assertIn("line two is still streaming", " ".join(text.strip() for text in lines_text(live)))


class RetakeTailTests(LoopTestCase):
    """A full redraw prints the last rows of the session, from a block boundary, under one row naming what it left out."""

    def session(self, turns: int) -> None:
        for turn in range(turns):
            self.user(f"question {turn}")
            self.step(ev("message.start"))
            self.step(ev("message.delta", text=f"answer {turn}, line one\nline two\n"))
            self.step(ev("message.complete", text=f"answer {turn}, line one\nline two", status="complete"))

    def test_only_the_last_blocks_that_fit_are_taken_again_under_a_row_naming_the_rest(self) -> None:
        # 40 blocks: a prompt is 2 rows with the blank row above it, a reply 4 (its `⚚ Hermes` header too).
        self.session(20)
        self.transcript.retake_tail(WIDTH, THEME, max_rows=10)
        again = lines_text(self.transcript.take_stable_lines(WIDTH, THEME))
        self.assertEqual(again[0], "⋯ 37 earlier messages · /history shows all")
        self.assertEqual(again[1:], self.history(details=False)[-10:])  # reply 18, prompt 19, reply 19: 4 + 2 + 4
        self.assertEqual(again[2], "  ⚚ Hermes")
        self.assertEqual(lines_text(self.transcript.take_stable_lines(WIDTH, THEME)), [])

    def test_a_session_that_fits_is_taken_again_whole_with_no_row_above_it(self) -> None:
        self.session(2)
        self.transcript.retake_tail(WIDTH, THEME, max_rows=100)
        self.assertEqual(lines_text(self.transcript.take_stable_lines(WIDTH, THEME)), self.history(details=False))

    def test_the_last_finished_block_is_taken_again_however_tall(self) -> None:
        self.user("go")
        self.step(ev("message.start"))
        reply = "\n".join(f"row {n}" for n in range(30))
        self.step(ev("message.delta", text=reply + "\n"))
        self.step(ev("message.complete", text=reply, status="complete"))
        self.transcript.retake_tail(WIDTH, THEME, max_rows=5)
        again = lines_text(self.transcript.take_stable_lines(WIDTH, THEME))
        self.assertEqual(again[0], "⋯ 1 earlier message · /history shows all")
        self.assertEqual(len(again), 33)  # the row, a spacer, the reply's header and all 30 of its rows

    def test_the_live_block_stays_live_and_is_never_counted_as_left_out(self) -> None:
        self.session(3)
        self.user("again")
        self.step(ev("message.start"))
        self.step(ev("message.delta", text="still streaming"))
        self.transcript.retake_tail(WIDTH, THEME, max_rows=3)
        again = lines_text(self.transcript.take_stable_lines(WIDTH, THEME))
        self.assertEqual(again, ["⋯ 6 earlier messages · /history shows all", "", "  ❯ again"])
        self.assertEqual(self.live(), ["", "  ⚚ Hermes", "    still streaming"])

    def test_the_take_after_it_renders_no_kept_block_again(self) -> None:
        # QA P3: measuring rendered every kept block, then the take rendered each again; a long session's settled
        # resize blocked the loop for both.
        self.session(20)
        self.transcript.retake_tail(WIDTH, THEME, max_rows=10)
        with patch("omh.tui.transcript.block_rows", wraps=block_rows) as rows, \
                patch("omh.tui.transcript.render_lines", wraps=transcript_module.render_lines) as replies:
            again = lines_text(self.transcript.take_stable_lines(WIDTH, THEME))
        self.assertEqual((rows.call_count, replies.call_count), (0, 0))
        self.assertEqual(again[1:], self.history(details=False)[-10:])

    def test_a_look_switched_since_the_measure_is_rendered_in_the_new_look(self) -> None:
        # A launch look is another theme (a call's rail is the look's accent): rows measured in the old one are not
        # reused.
        self.session(2)
        self.step(ev("tool.start", tool_id="t1", name="terminal", context="ls"))
        self.step(ev("tool.complete", tool_id="t1", name="terminal", result={"exit_code": 0}, duration_s=0.5))
        self.step(ev("message.complete", text="done", status="complete"))
        looked = with_launch_look(THEME, default_theme(), None, "ember")
        self.assertNotEqual(self.transcript.history_lines(WIDTH, looked, details=False),
                            self.transcript.history_lines(WIDTH, THEME, details=False))
        self.transcript.retake_tail(WIDTH, THEME, max_rows=100)
        taken = self.transcript.take_stable_lines(WIDTH, looked)
        self.assertEqual(taken + self.transcript.live_lines(WIDTH, looked),
                         self.transcript.history_lines(WIDTH, looked, details=False))

    def test_what_changed_since_the_measure_or_another_width_is_rendered_as_it_is_now(self) -> None:
        self.session(3)
        self.transcript.retake_tail(WIDTH, THEME, max_rows=100)
        self.transcript.add_notice("came after the measure")
        self.assertEqual(lines_text(self.transcript.take_stable_lines(WIDTH, THEME)), self.history(details=False))
        self.transcript.retake_tail(WIDTH, THEME, max_rows=100)
        self.assertEqual(lines_text(self.transcript.take_stable_lines(30, THEME)),
                         lines_text(self.transcript.history_lines(30, THEME, details=False)))


class BlockCapTests(LoopTestCase):
    """At most `BLOCK_CAP` blocks are held; the oldest ones already printed go first."""

    def test_printed_blocks_past_the_cap_are_dropped_oldest_first(self) -> None:
        with patch("omh.tui.transcript.BLOCK_CAP", 10):
            for number in range(25):  # each printed at once (no `step`: history no longer holds what was dropped)
                self.transcript.add_notice(f"notice {number}")
                self.transcript.take_stable_lines(WIDTH, THEME)
        self.assertEqual(len(self.transcript.blocks), 10)
        self.assertEqual(self.transcript.dropped, 15)
        self.assertEqual(self.history()[0], "· notice 15")
        self.assertEqual(self.live(), [])

    def test_blocks_not_printed_yet_are_never_dropped(self) -> None:
        with patch("omh.tui.transcript.BLOCK_CAP", 10):
            for number in range(25):
                self.transcript.add_notice(f"notice {number}")
        self.assertEqual((len(self.transcript.blocks), self.transcript.dropped), (25, 0))
        taken = lines_text(self.transcript.take_stable_lines(WIDTH, THEME))
        self.assertEqual((taken[0], taken[-1]), ("· notice 0", "· notice 24"))

    def test_a_redraw_after_drops_counts_them_and_says_history_holds_only_the_rest(self) -> None:
        with patch("omh.tui.transcript.BLOCK_CAP", 10):
            for number in range(25):  # each printed at once (no `step`: history no longer holds what was dropped)
                self.transcript.add_notice(f"notice {number}")
                self.transcript.take_stable_lines(WIDTH, THEME)
        self.transcript.retake_tail(WIDTH, THEME, max_rows=4)
        again = lines_text(self.transcript.take_stable_lines(WIDTH, THEME))
        self.assertEqual(again, ["⋯ 23 earlier messages · /history shows the last 10", "", "· notice 23", "", "· notice 24"])

    def test_blocks_past_the_cap_go_once_printed_without_waiting_for_a_new_block(self) -> None:
        with patch("omh.tui.transcript.BLOCK_CAP", 10):
            for number in range(25):  # none printed yet, as a resumed session's history arrives
                self.transcript.add_notice(f"notice {number}")
            self.transcript.take_stable_lines(WIDTH, THEME)
            self.assertEqual((len(self.transcript.blocks), self.transcript.dropped), (10, 15))

    def test_a_redraw_of_blocks_past_the_cap_counts_them_and_holds_only_the_cap(self) -> None:
        with patch("omh.tui.transcript.BLOCK_CAP", 10):
            for number in range(25):
                self.transcript.add_notice(f"notice {number}")
            self.transcript.retake_tail(WIDTH, THEME, max_rows=4)
            again = lines_text(self.transcript.take_stable_lines(WIDTH, THEME))
        self.assertEqual(again, ["⋯ 23 earlier messages · /history shows the last 10", "", "· notice 23", "", "· notice 24"])
        self.assertEqual(len(self.transcript.blocks), 10)

    def test_a_turns_answer_is_still_known_after_its_own_blocks_push_older_ones_out(self) -> None:
        with patch("omh.tui.transcript.BLOCK_CAP", 10):
            for number in range(8):
                self.transcript.add_notice(f"notice {number}")
                self.transcript.take_stable_lines(WIDTH, THEME)
            self.transcript.apply(ev("message.start"))
            self.transcript.apply(ev("message.delta", text="the answer"))
            for number in range(5):  # the turn's own blocks, each printed: four of the oldest go
                self.transcript.add_notice(f"turn notice {number}")
                self.transcript.take_stable_lines(WIDTH, THEME)
            self.assertEqual(self.transcript.dropped, 4)
            self.transcript.apply(ev("message.complete", text="the answer"))
        answers = [block.text for block in self.transcript.blocks if isinstance(block, AssistantBlock)]
        self.assertEqual(answers, ["the answer"])

    def test_an_edits_diff_is_kept_as_the_text_hermes_sent_encoded(self) -> None:
        self.transcript.cwd = "/repo"
        self.step(ev("message.start"))
        self.step(ev("tool.start", tool_id="e1", name="patch", context="/repo/src/app.py"))
        self.step(ev("tool.complete", tool_id="e1", name="patch", result={"success": True}, inline_diff=PATCH_INLINE_DIFF))
        (row,) = self.transcript.blocks[-1].tools
        self.assertEqual(row.inline_diff, PATCH_INLINE_DIFF.encode("utf-8"))
        self.assertFalse(hasattr(row, "diff"))

    def test_a_live_groups_diff_is_parsed_once_and_let_go_when_the_group_is_done(self) -> None:
        real = __import__("omh.tui.transcript", fromlist=["parse_inline_diff"]).parse_inline_diff
        parsed: list[str] = []

        def counting(text: str) -> object:
            parsed.append(text)
            return real(text)

        self.transcript.cwd = "/repo"
        self.step(ev("message.start"))
        self.step(ev("tool.start", tool_id="e1", name="patch", context="/repo/src/app.py"))
        with patch("omh.tui.transcript.parse_inline_diff", counting):
            self.step(ev("tool.complete", tool_id="e1", name="patch", result={"success": True}, inline_diff=PATCH_INLINE_DIFF))
            self.step(ev("tool.start", tool_id="t2", name="terminal", context="ls"))  # the live group changes twice
            self.step(ev("tool.start", tool_id="t3", name="terminal", context="pwd"))
        self.assertEqual(len(parsed), 1)
        self.step(ev("message.complete", text="done"))
        self.assertIsNone(self.transcript.blocks[-2].tools[0].held_lines)

    def test_an_edits_diff_with_a_lone_surrogate_is_kept_and_drawn(self) -> None:
        # JSON can carry an escaped lone surrogate ("\udce9", a byte surrogateescape left in a file's text).
        diff = PATCH_INLINE_DIFF + "\n\x1b[38;2;255;255;255;48;2;20;90;20m+name = 'caf\udce9'\x1b[0m"
        self.transcript.cwd = "/repo"
        self.step(ev("message.start"))
        self.step(ev("tool.start", tool_id="e1", name="patch", context="/repo/src/app.py"))
        self.step(ev("tool.complete", tool_id="e1", name="patch", result={"success": True}, inline_diff=diff))
        (row,) = self.transcript.blocks[-1].tools
        self.assertTrue(any("caf\udce9" in line.text for line in row.diff_lines()))
        self.assertTrue(any("caf\udce9" in text for text in self.history()))

    def test_an_edits_diff_is_held_in_less_memory_than_its_parsed_lines(self) -> None:
        import sys

        rows = "\n".join(f"\x1b[38;2;255;255;255;48;2;20;90;20m+    value_{n} = compute(row_{n})\x1b[0m" for n in range(200))
        diff = f"  ┊ review diff\n\x1b[38;2;180;160;255ma/src/app.py → b/src/app.py\x1b[0m\n{rows}"
        row = ToolRow(tool_id="e1", name="patch", inline_diff=diff.encode("utf-8"))
        parsed = row.diff_lines()
        held = sys.getsizeof(row.inline_diff)
        self.assertLess(held, sys.getsizeof(diff))  # the str is widened to two bytes a character by `┊` and `→`
        self.assertLess(held, sum(sys.getsizeof(line) + sys.getsizeof(line.text) for line in parsed))


class ToolPathArgumentTests(LoopTestCase):
    def test_a_path_argument_keeps_its_file_name_when_cut(self) -> None:
        path = "/private/tmp/claude-501/" + "y" * 60 + "/project/hello.py"
        self.step(ev("message.start"))
        self.step(ev("tool.start", tool_id="t1", name="patch", context=path))
        row = [line for line in self.live(width=50) if "patch" in line][0]
        self.assertIn("hello.py", row)
        self.assertIn("…", row)

    def test_prose_arguments_are_still_cut_at_the_end(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("tool.start", tool_id="t1", name="terminal", context="echo " + "z" * 80))
        row = [line for line in self.live(width=50) if "terminal" in line][0]
        self.assertIn("echo", row)


class SessionRelativePathTests(LoopTestCase):
    def test_paths_inside_the_session_cwd_show_relative_to_it(self) -> None:
        self.transcript.cwd = "/work/project"
        self.step(ev("message.start"))
        self.step(ev("tool.start", tool_id="t1", name="patch", context="/work/project/src/app.py"))
        diff = "\x1b[1ma//work/project/src/app.py → b//work/project/src/app.py\x1b[0m\n@@ -1 +1 @@\n-a\n+b"
        self.step(ev("tool.complete", tool_id="t1", name="patch", result={"exit_code": 0}, inline_diff=diff))
        live = self.live()
        self.assertIn("  ● patch(src/app.py)", "\n".join(live))
        self.assertIn("    ⎿  src/app.py", live)

    def test_a_cwd_of_root_leaves_absolute_paths_absolute(self) -> None:
        self.transcript.cwd = "/"
        self.step(ev("message.start"))
        self.step(ev("tool.start", tool_id="t1", name="read_file", context="/etc/hosts"))
        self.assertIn("read_file(/etc/hosts)", "\n".join(self.live()))

    def test_paths_outside_the_cwd_and_prose_stay_as_they_are(self) -> None:
        self.transcript.cwd = "/work/project"
        self.step(ev("message.start"))
        self.step(ev("tool.start", tool_id="t1", name="read_file", context="/etc/hosts"))
        self.step(ev("tool.start", tool_id="t2", name="terminal", context="ls /work/project/src"))
        joined = "\n".join(self.live())
        self.assertIn("read_file(/etc/hosts)", joined)
        self.assertIn("terminal(ls /work/project/src)", joined)

class PlainTurnTests(LoopTestCase):
    def test_plain_turn_flushes_per_completed_line_and_fully_at_complete(self) -> None:
        self.assertEqual(self.user("Reply with exactly the word: ok"), ["  ❯ Reply with exactly the word: ok"])
        self.assertEqual(self.step(ev("message.start")), [])
        self.assertTrue(self.transcript.running)
        self.step(ev("thinking.delta", text="ヽ(>∀<☆)☆ formulating..."))
        self.assertEqual(self.transcript.activity, "ヽ(>∀<☆)☆ formulating...")
        self.step(ev("thinking.delta", text=""))
        self.assertEqual(self.transcript.activity, "")
        self.assertEqual(self.step(ev("message.delta", text="ok\n\n")), ["", "  ⚚ Hermes", "    ok"])
        self.assertEqual(self.step(ev("message.delta", text="I")), [])
        self.step(ev("message.delta", text="'m Hermes,"))
        self.step(ev("message.delta", text=" your agent — `/help` lists the commands."))
        self.assertEqual(self.live(), [" ", "    I'm Hermes, your agent — /help lists the commands."])  # one rail
        self.step(ev("reasoning.available", text=PLAIN_ANSWER))
        flushed = self.step(ev("message.complete", text=PLAIN_ANSWER, status="complete", usage={"total": 13874}))
        self.assertEqual(flushed, [" ", "    I'm Hermes, your agent — /help lists the commands."])
        self.assertEqual(self.live(), [])
        self.assertFalse(self.transcript.running)
        self.assertFalse(any(isinstance(block, ThinkingBlock) for block in self.transcript.blocks))
        self.assertEqual(
            self.history(),
            [
                "  ❯ Reply with exactly the word: ok",
                "",
                "  ⚚ Hermes",
                "    ok",
                " ",
                "    I'm Hermes, your agent — /help lists the commands.",
            ],
        )

    def test_live_lines_shrink_as_lines_flush(self) -> None:
        self.transcript.apply(ev("message.start"))
        self.transcript.apply(ev("message.delta", text="line one\nline two\npartial"))
        self.assertEqual(self.live(), ["  ⚚ Hermes", "    line one", "    line two", "    partial"])
        self.assertEqual(self.step(), ["  ⚚ Hermes", "    line one", "    line two"])
        self.assertEqual(self.live(), ["    partial"])
        # Who said it: `⚚ Hermes` bold in the rail's hue on a header row of its own, apart from a call's state colours.
        self.assertEqual(self.taken[0][:3], (rail_cell(THEME.brand), Span(" ", GUTTER), Span("⚚ Hermes", replace(THEME.brand, bold=True))))

    def test_a_long_paragraph_streaming_wraps_only_its_last_rows_each_frame(self) -> None:
        # Found by the QA perf lane: every frame wrapped the whole paragraph, so one long paragraph cost O(n^2).
        wrapped: list[int] = []
        real = markdown.wrap_line

        def counting(line: Line, cells: int) -> list[Line]:
            wrapped.append(sum(len(span.text) for span in line))
            return real(line, cells)

        self.step(ev("message.start"))
        for index in range(1200):
            self.transcript.apply(ev("message.delta", text=("**bold** ", "`code` ", "한국어 ", "token ")[index % 4]))
            if index % 40 == 0:
                self.step()  # a frame: the step holds its rows to the whole paragraph's render
        wrapped.clear()
        with patch("omh.tui.markdown.wrap_line", counting):
            self.transcript.apply(ev("message.delta", text="tail "))
            self.transcript.live_lines(WIDTH, THEME, max_rows=10)
        self.assertLess(sum(wrapped), 400, wrapped)  # the paragraph is ~8,000 characters
        self.step(ev("message.complete", text="", status="complete"))

    def test_a_trailing_blank_line_waits_for_the_text_after_it(self) -> None:
        self.step(ev("message.start"))
        self.assertEqual(self.step(ev("message.delta", text="1\n\n")), ["  ⚚ Hermes", "    1"])
        self.assertEqual(self.step(ev("message.delta", text="\n")), [])
        self.assertEqual(self.step(ev("message.delta", text="2\n")), [" ", " ", "    2"])
        self.assertEqual(self.step(ev("message.complete", text="1\n\n\n2", status="complete")), [])

    def test_any_chunking_of_the_stream_flushes_the_same_lines(self) -> None:
        answer = "# Plan\n\n- step **one**\n- step two\n\n```python\nx = 1\n```\nDone, see [docs](https://x.y)."
        expected: list[str] | None = None
        for size in (1, 2, 3, 7, 50):
            with self.subTest(chunk=size):
                self.setUp()
                self.step(ev("message.start"))
                for start in range(0, len(answer), size):
                    self.step(ev("message.delta", text=answer[start : start + size]))
                self.step(ev("message.complete", text=answer, status="complete"))
                self.assertEqual(self.live(), [])
                expected = expected or lines_text(self.taken)
                self.assertEqual(lines_text(self.taken), expected)
        self.assertEqual(
            expected,
            ["  ⚚ Hermes", "    Plan", " ", "    • step one", "    • step two", " ", "    python", "    x = 1",
             "    Done, see docs (https://x.y)."],
        )

    def test_an_open_fence_stays_code_across_the_flush_boundary(self) -> None:
        self.step(ev("message.start"))
        flushed = self.step(ev("message.delta", text="Here:\n```python\nx = None  # one\n"))
        self.assertEqual(flushed, ["  ⚚ Hermes", "    Here:", "    python", "    x = None  # one"])
        self.assertEqual(
            self.taken[-1],
            (*REPLY_RAIL, Span("  ", GUTTER), Span("x = ", THEME.text), Span("None", THEME.syntax_keyword), Span("  ", THEME.text),
             Span("# one", THEME.syntax_comment)),
        )
        self.assertEqual(self.step(ev("message.delta", text="y = '*no*'\n``")), ["    y = '*no*'"])
        self.assertEqual(self.taken[-1], (*REPLY_RAIL, Span("  ", GUTTER), Span("y = ", THEME.text), Span("'*no*'", THEME.syntax_string)))
        self.assertEqual(self.live(), ["    ``"])
        self.assertEqual(self.step(ev("message.delta", text="`\nafter *it*")), [])
        self.assertEqual(self.live(), ["    after it"])
        self.assertEqual(self.step(ev("message.complete", text="", status="complete")), ["    after it"])

    def test_a_docstring_open_across_flushes_stays_a_string_for_any_chunking(self) -> None:
        answer = 'Code:\n```python\ndef f():\n    """Doc.\n\n    # not a comment\n    """\n    return 1  # one\n```\nDone.'
        expected: list[Line] | None = None
        for size in (1, 4, 9, 200):
            with self.subTest(chunk=size):
                self.setUp()
                self.step(ev("message.start"))
                for start in range(0, len(answer), size):
                    self.step(ev("message.delta", text=answer[start : start + size]))
                self.step(ev("message.complete", text=answer, status="complete"))
                expected = expected or list(self.taken)
                self.assertEqual(self.taken, expected)
        # Row 0 is the reply's `⚚ Hermes` header.
        self.assertEqual(expected[6], (*REPLY_RAIL, Span("  ", GUTTER), Span("    # not a comment", THEME.syntax_string)))
        self.assertEqual(expected[7], (*REPLY_RAIL, Span("  ", GUTTER), Span('    """', THEME.syntax_string)))
        self.assertEqual(expected[8][-1], Span("# one", THEME.syntax_comment))

    def test_a_resize_changes_only_lines_not_yet_taken(self) -> None:
        self.step(ev("message.start"))
        long_line = "alpha beta gamma delta epsilon zeta eta theta"
        self.assertEqual(self.step(ev("message.delta", text=long_line + "\n" + long_line), width=80),
                         ["  ⚚ Hermes", "    " + long_line])
        narrow = self.live(width=20)
        self.assertEqual(narrow, ["    alpha beta gamma", "    delta epsilon", "    zeta eta theta"])
        self.transcript.apply(ev("message.complete", text="", status="complete"))
        fresh = self.transcript.take_stable_lines(20, THEME)
        self.assertEqual(lines_text(fresh), narrow)
        self.assertEqual(self.transcript.take_stable_lines(80, THEME), [])

    def test_authoritative_text_replaces_the_stream_only_where_nothing_was_taken(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("message.delta", text="Hello wrld"))
        self.step(ev("message.complete", text="Hello world", status="complete"))
        self.assertEqual(self.history(), ["  ⚚ Hermes", "    Hello world"])
        self.setUp()
        self.step(ev("message.start"))
        self.step(ev("message.delta", text="first\nsecond"))
        self.step(ev("message.complete", text="FIRST\nsecond", status="complete"))
        self.assertEqual(self.history(), ["  ⚚ Hermes", "    first", "    second"])

    def test_text_that_never_streamed_arrives_with_complete(self) -> None:
        self.step(ev("message.start"))
        self.assertEqual(self.step(ev("message.complete", text="blue", status="complete")), ["  ⚚ Hermes", "    blue"])

    def test_control_characters_never_reach_a_line(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("message.delta", text="\x1b[2Jboom\x07\n"))
        self.step(ev("message.complete", text="", status="complete"))
        self.assertEqual(lines_text(self.taken), ["  ⚚ Hermes", "    boom"])
        self.assertFalse(any(is_control(ch) for row in self.taken for span in row for ch in span.text))

    def test_user_text_is_plain_wrapped_and_composed(self) -> None:
        decomposed = unicodedata.normalize("NFD", "한글")
        self.assertEqual(self.user(decomposed + " **not bold**\nsecond line"), ["  ❯ 한글 **not bold**", "    second line"])


class ReasoningAndToolTests(LoopTestCase):
    def test_reasoning_flushes_as_one_collapsed_row_then_the_tool_group(self) -> None:
        self.user("Use your terminal tool to run: rm -rf ./omh-m0-probe-dir")
        self.step(ev("message.start"), at=100.0)
        self.step(ev("thinking.delta", text="(⌐■_■) analyzing..."))
        self.step(ev("thinking.delta", text=""))
        self.step(ev("reasoning.delta", text="The"), at=110.0)
        self.step(ev("reasoning.delta", text=" user asks"))
        self.step(ev("reasoning.delta", text=" to run `rm -rf ./omh-m0-probe-dir`.\n\nLet me just run it."))
        self.assertEqual(self.live(), ["", "▸ thinking… Let me just run it."])

        self.assertTrue(self.transcript.toggle_details())
        self.assertEqual(
            self.live(),
            ["", "▾ thinking…", "  The user asks to run `rm -rf ./omh-m0-probe-dir`.", "", "  Let me just run it."],
        )
        self.transcript.toggle_details()

        flushed = self.step(ev("tool.generating", name="terminal"), at=114.2)
        self.assertEqual(flushed, ["", "▸ thought for 4.2s"])
        self.assertEqual(self.live(), ["", "  ◌ terminal"])
        self.step(
            ev(
                "tool.start",
                tool_id="call_3e3b1bebaaee48e68c56001e",
                name="terminal",
                context="rm -rf ./omh-m0-probe-dir",
                args={"command": "rm -rf ./omh-m0-probe-dir"},
            ),
            at=114.3,
        )
        self.assertEqual(self.live(), ["", "  ○ terminal(rm -rf ./omh-m0-probe-dir)"])  # running: a blue `○`
        self.step(ev("session.usage", usage={"total": 27946}))
        self.step(
            ev(
                "tool.complete",
                tool_id="call_3e3b1bebaaee48e68c56001e",
                name="terminal",
                args={"command": "rm -rf ./omh-m0-probe-dir"},
                duration_s=1.9490349292755127,
                result={
                    "output": "",
                    "exit_code": 0,
                    "error": None,
                    "approval": "Command was flagged (recursive delete) and auto-approved by smart approval.",
                },
            )
        )
        self.assertEqual(self.live(), ["", "  ● terminal(rm -rf ./omh-m0-probe-dir)  1.9s"])
        self.step(ev("thinking.delta", text="(◔_◔) brainstorming..."))
        flushed = self.step(ev("message.delta", text="\n\nRan it"))
        self.assertEqual(flushed, ["", "  ● terminal(rm -rf ./omh-m0-probe-dir)  1.9s"])
        self.step(ev("message.delta", text=" — exit code 0."))
        self.step(ev("reasoning.available", text="Ran it — exit code 0."))
        flushed = self.step(
            ev("message.complete", text="Ran it — exit code 0.", status="complete", reasoning="The user asks ...")
        )
        self.assertEqual(flushed, ["", "  ⚚ Hermes", "    Ran it — exit code 0."])
        self.assertEqual(self.history(details=False), lines_text(self.taken))
        self.assertEqual(
            self.history(),
            [
                "  ❯ Use your terminal tool to run: rm -rf ./omh-m0-probe-dir",
                "",
                "▾ thought for 4.2s",
                "  The user asks to run `rm -rf ./omh-m0-probe-dir`.",
                "",
                "  Let me just run it.",
                "",
                "  ● terminal(rm -rf ./omh-m0-probe-dir)  1.9s",
                "",
                "  ⚚ Hermes",
                "    Ran it — exit code 0.",
            ],
        )

    def test_expanding_details_never_reaches_a_taken_block(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("reasoning.delta", text="weighing options"), at=100.0)
        self.step(ev("message.delta", text="Answer."), at=101.0)
        self.transcript.toggle_details()
        self.assertEqual(lines_text(self.taken), ["▸ thought for 1.0s"])
        self.assertEqual(self.live(), ["", "  ⚚ Hermes", "    Answer."])

    def test_each_call_is_its_own_row_with_what_it_printed_under_it_and_no_group_header(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("tool.generating", name="read_file"))
        self.step(ev("tool.generating", name="search_files"))
        self.step(ev("tool.start", tool_id="a", name="read_file", context="src/a.py"), at=1.0)
        self.assertEqual(self.live(), ["  ○ read_file(src/a.py)", "", "  ◌ search_files"])
        self.step(ev("tool.start", tool_id="b", name="search_files", args={"pattern": "needle"}), at=1.1)
        self.step(ev("tool.complete", tool_id="a", name="read_file", duration_s=0.5, result={"content": "x"}))
        self.step(ev("tool.complete", tool_id="b", name="search_files", duration_s=0.7, result={"error": "rg failed"}))
        self.step(ev("tool.start", tool_id="c", name="terminal", context="pytest"), at=3.0)
        self.step(ev("tool.complete", tool_id="c", name="terminal", result={"output": "1 failed", "exit_code": 1}), at=5.0)
        flushed = self.step(ev("message.delta", text="Done."))
        self.assertEqual(
            flushed,
            [
                "  ● read_file(src/a.py)  0.5s",
                "    ⎿  Read 1 line",
                "",
                "  ✗ search_files(needle)  0.7s",
                "    ⎿  rg failed",
                "",
                "  ✗ terminal(pytest)  2.0s",
                "    ⎿  1 failed",
            ],
        )
        self.assertEqual(self.taken[0][0], rail_cell(THEME.accent))  # the launch look's rail; the mark says done
        # A failure's first line is grey like any result; its rail and its `✗` say it failed.
        self.assertEqual(self.taken[4][-1].style, THEME.faint)
        self.assertEqual([self.taken[row][0] for row in (3, 4)], [rail_cell(THEME.error)] * 2)  # search_files' rail
        self.step(ev("message.complete", text="Done.", status="complete"))
        self.assertIn("    ⎿  rg failed", self.history())
        self.assertIn("    ⎿  1 failed", self.history())

    def test_tools_that_ran_one_after_another_are_a_row_each(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("tool.start", tool_id="a", name="read_file", context="a.py"))
        self.step(ev("tool.complete", tool_id="a", name="read_file", duration_s=0.1, result={"content": ""}))
        self.step(ev("tool.start", tool_id="b", name="read_file", context="b.py"))
        self.step(ev("tool.complete", tool_id="b", name="read_file", duration_s=0.1, result={"content": ""}))
        flushed = self.step(ev("message.complete", text="", status="complete"))
        self.assertEqual(flushed, ["  ● read_file(a.py)  0.1s", "    ⎿  Read 0 lines", "", "  ● read_file(b.py)  0.1s",
                                   "    ⎿  Read 0 lines"])  # a blank row between two calls

    def test_a_denied_approval_shows_as_denied(self) -> None:
        self.user("Use your terminal tool to run exactly this shell command: rm -rf ./omh-m0-probe-dir")
        self.step(ev("message.start"))
        self.step(ev("tool.generating", name="terminal"))
        self.step(
            ev(
                "tool.start",
                tool_id="call_2cbc0bb1284b47f68922176c",
                name="terminal",
                context="rm -rf ./omh-m0-probe-dir",
                args={"command": "rm -rf ./omh-m0-probe-dir"},
            )
        )
        self.step(
            ev(
                "tool.complete",
                tool_id="call_2cbc0bb1284b47f68922176c",
                name="terminal",
                args={"command": "rm -rf ./omh-m0-probe-dir"},
                duration_s=0.09538984298706055,
                result=DENIED_RESULT,
            )
        )
        flushed = self.step(ev("message.delta", text="\n\nIt was blocked — the command did not run."))
        # One mark for a denial, the red `✗` on a red rail, and the person's words under it.
        self.assertEqual(flushed, ["", "  ✗ terminal(rm -rf ./omh-m0-probe-dir)  0.1s",
                                   "    ⎿  You denied this command — it did not run."])
        self.assertEqual(self.taken[-2][0], rail_cell(THEME.error))
        self.step(ev("message.complete", text="It was blocked — the command did not run.", status="complete"))
        history = self.history()
        row = history.index("  ✗ terminal(rm -rf ./omh-m0-probe-dir)  0.1s")
        self.assertEqual(history[row + 1 : row + 3], ["    ⎿  You denied this command — it did not run.", ""])  # once

    def test_result_status_reads_the_result_shapes_hermes_sends(self) -> None:
        self.assertEqual(tool_result_status(DENIED_RESULT), "denied")
        self.assertEqual(tool_result_status({"approved": False, "user_consent": False}), "denied")
        self.assertEqual(tool_result_status({"error": "rg failed"}), "error")
        self.assertEqual(tool_result_status({"output": "", "exit_code": 2, "error": None}), "error")
        self.assertEqual(tool_result_status({"success": False}), "error")
        self.assertEqual(tool_result_status({"output": "", "exit_code": 0, "error": None}), "ok")
        self.assertEqual(
            tool_result_status({"responses": [{"status": "answered", "user_response": "blue"}], "outcome": "submitted"}),
            "ok",
        )
        self.assertEqual(tool_result_status("plain text result"), "ok")
        self.assertEqual(tool_result_status(None), "ok")

    def test_tool_rows_stay_one_line_and_keep_the_duration(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("tool.start", tool_id="a", name="terminal", context="x" * 200))
        self.step(ev("tool.complete", tool_id="a", name="terminal", duration_s=12.0, result={"exit_code": 0}))
        self.step(ev("message.complete", text="", status="complete"), width=40)
        row = lines_text(self.taken)[0]
        self.assertEqual(row, "  ● terminal(" + "x" * 18 + "…)  12.0s")  # the rail takes two cells
        self.assertEqual(line_width(self.taken[0]), 40)

    def test_interim_commentary_is_sealed_before_the_tools(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("message.delta", text="Let me check the file."))
        flushed = self.step(ev("message.interim", text="Let me check the file.", already_streamed=True))
        self.assertEqual(flushed, ["  ⚚ Hermes", "    Let me check the file."])
        self.step(ev("tool.start", tool_id="a", name="read_file", context="a.py"))
        self.step(ev("tool.complete", tool_id="a", name="read_file", duration_s=0.1, result={"content": "ok"}))
        self.step(ev("message.delta", text="\n\nIt is fine."))
        self.step(ev("message.complete", text="It is fine.", status="complete"))
        self.assertEqual(
            self.history(details=False),
            ["  ⚚ Hermes", "    Let me check the file.", "", "  ● read_file(a.py)  0.1s", "    ⎿  Read 1 line", "", "  ⚚ Hermes", "    It is fine."],
        )

    def test_interim_text_that_never_streamed_becomes_its_own_block_once(self) -> None:
        self.step(ev("message.start"))
        self.assertEqual(self.step(ev("message.interim", text="Checking.", already_streamed=False)), ["  ⚚ Hermes", "    Checking."])
        self.step(ev("message.complete", text="Checking.", status="complete"))
        self.assertEqual(sum(isinstance(block, AssistantBlock) for block in self.transcript.blocks), 1)


class ToolDraftTests(LoopTestCase):
    """`tool.generating` (a name, no id) drafts a placeholder row; only `tool.start` and `tool.complete` make calls.

    Measured against Hermes 6c61c3e27d: a streamed attempt Hermes discards
    (`turn_truncation._retry_truncated_tool_call`, arguments it cannot repair)
    has sent its `tool.generating` and nothing after it, and a deferred tool
    reached through the `tool_call` bridge drafts as `tool_call` and starts
    under the name of the tool it reached (`tool_executor._unwrap_tool_search_call`).
    """

    def end_turn(self, seconds: float, status: str = "complete") -> list[str]:
        self.step(ev("message.complete", text="", status=status))
        self.transcript.add_turn_summary(seconds, None)
        self.step()
        return lines_text(self.taken)

    def test_a_bridge_draft_becomes_the_call_it_reached_in_its_place(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("tool.generating", name="tool_call"))
        self.assertEqual(self.live(), ["  ◌ tool_call"])
        self.step(ev("tool.start", tool_id="call_1", name="todo_list", context="planning 3 task(s)"))
        self.assertEqual(self.live(), ["  ○ todo_list(planning 3 task(s))"])
        self.step(ev("tool.complete", tool_id="call_1", name="todo_list", result={"todos": []}, duration_s=0.0))
        taken = self.end_turn(2.0)
        self.assertEqual(taken[0], "  ● todo_list(planning 3 task(s))  0.0s")
        self.assertNotIn("tool_call", "\n".join(taken))
        self.assertEqual(taken[-1], "  ✻ 2s · 1 tool")

    def test_a_draft_of_the_same_name_is_claimed_before_a_bridge_draft(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("tool.generating", name="tool_call"))
        self.step(ev("tool.generating", name="read_file"))
        self.step(ev("tool.start", tool_id="a", name="read_file", context="a.py"))
        self.assertEqual(self.live(), ["  ◌ tool_call", "", "  ○ read_file(a.py)"])
        self.step(ev("tool.start", tool_id="b", name="todo_list", context="planning 1 task(s)"))
        self.assertEqual(self.live(), ["  ○ todo_list(planning 1 task(s))", "", "  ○ read_file(a.py)"])

    def test_two_bridge_drafts_become_their_calls_in_the_order_they_started(self) -> None:
        # Each start claims the first unclaimed bridge draft, so the rows keep the order the calls began in.
        self.step(ev("message.start"))
        self.step(ev("tool.generating", name="tool_call"))
        self.step(ev("tool.generating", name="tool_call"))
        self.step(ev("tool.start", tool_id="a", name="todo_list", context="planning 1 task(s)"))
        self.assertEqual(self.live(), ["  ○ todo_list(planning 1 task(s))", "", "  ◌ tool_call"])
        self.step(ev("tool.start", tool_id="b", name="web_search", context="hermes agent"))
        self.assertEqual(self.live(), ["  ○ todo_list(planning 1 task(s))", "", "  ○ web_search(hermes agent)"])

    def test_a_streamed_attempt_hermes_discards_leaves_no_row_and_no_count(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("tool.generating", name="write_file"))  # the attempt Hermes discards
        self.step(ev("tool.generating", name="write_file"))  # the attempt it keeps
        self.step(ev("tool.start", tool_id="w1", name="write_file", context="notes.md"))
        self.step(ev("tool.complete", tool_id="w1", name="write_file", result={"bytes_written": 3}, duration_s=0.1))
        taken = self.end_turn(4.0)
        self.assertEqual(taken[0], "  ● write_file(notes.md)  0.1s")
        self.assertNotIn("◌", "\n".join(taken))
        self.assertNotIn("▪", "\n".join(taken))
        self.assertEqual(taken[-1], "  ✻ 4s · 1 tool")

    def test_discarded_attempts_under_their_own_reasoning_leave_no_group_behind(self) -> None:
        # The shape of the capture: each attempt sent its reasoning, then drafted the bridge and write_file.
        self.step(ev("message.start"))
        for attempt in range(4):
            self.step(ev("reasoning.delta", text=f"plan it {attempt}"))
            self.step(ev("tool.generating", name="tool_call"))
            self.step(ev("tool.generating", name="write_file"))
        self.step(ev("reasoning.delta", text="plan it"))
        self.step(ev("tool.generating", name="tool_call"))
        self.step(ev("tool.start", tool_id="call_9", name="todo_list", context="planning 3 task(s)"))
        self.step(ev("tool.complete", tool_id="call_9", name="todo_list", result={"todos": []}, duration_s=0.0))
        taken = self.end_turn(12.0)
        text = "\n".join(taken)
        for absent in ("▪", "◌", "write_file", "tool_call", "Tool calls"):
            self.assertNotIn(absent, text)
        self.assertEqual(text.count("  ● todo_list(planning 3 task(s))  0.0s"), 1)
        self.assertEqual(taken[-1], "  ✻ 12s · 1 tool")

    def test_a_draft_that_never_starts_leaves_no_row(self) -> None:
        for status in ("complete", "interrupted"):
            with self.subTest(status=status):
                self.setUp()
                self.step(ev("message.start"))
                self.step(ev("tool.generating", name="terminal"))
                self.assertEqual(self.live(), ["  ◌ terminal"])
                taken = self.end_turn(1.0, status)
                self.assertNotIn("terminal", "\n".join(taken))
                self.assertEqual(taken[-1], "  ✻ 1s")  # no tools to count

    def test_a_call_the_turn_cut_off_while_it_ran_still_reads_as_interrupted_and_counts(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("tool.generating", name="terminal"))
        self.step(ev("tool.start", tool_id="t1", name="terminal", context="sleep 60"))
        taken = self.end_turn(3.0, "interrupted")
        self.assertEqual(taken[0], "  ▪ terminal(sleep 60)")
        self.assertEqual(taken[-1], "  ✻ 3s · 1 tool")


class SteeredReplyTests(unittest.TestCase):
    """Once the person steered, `message.complete` never removes or rewrites what streamed: Hermes reads a steer
    before its next model call, a reply that made no tool call is not sealed between the calls, and the final
    carries the last call's text only."""

    def setUp(self) -> None:
        self.transcript = Transcript(clock=FakeClock())

    def replies(self) -> list[object]:
        return [(type(block).__name__[0], getattr(block, "text", "")) for block in self.transcript.blocks
                if isinstance(block, (AssistantBlock, SteerBlock))]

    def stream(self, first: str, last: str, final: str, agent: str = "") -> list[object]:
        """A reply streamed as `first`, a steer Hermes took, then `last`, ending on `final`, and the turn's end."""
        self.transcript.apply(ev("message.start"))
        self.transcript.apply(ev("message.delta", text=first))
        steer = self.transcript.add_steer("s1", agent=agent)
        self.transcript.steer_answered(steer, STEER_QUEUED)
        self.transcript.apply(ev("message.delta", text=last))
        self.transcript.apply(ev("message.complete", text=final, status="complete"))
        self.transcript.add_turn_summary(1.0, None)
        return self.replies()

    def test_two_calls_keep_all_that_streamed_and_the_steer_row_goes_under_them(self) -> None:
        self.assertEqual(self.stream("First answer.\n", "Second answer.", "Second answer."),
                         [("A", "First answer.\nSecond answer."), ("S", "s1")])

    def test_what_the_final_adds_past_the_stream_is_added_spaces_aside(self) -> None:
        footer = "\n\nWarning: 1 edit failed"
        self.assertEqual(self.stream("One call ", "that  ends.", "One call that ends." + footer),
                         [("A", "One call that  ends." + footer), ("S", "s1")])

    def test_a_final_that_differs_inside_adds_nothing_and_rewrites_nothing(self) -> None:
        for final in ("Second answer!", "Second", "Second  answer.\n\nFirst."):
            with self.subTest(final=final):
                self.setUp()
                self.assertEqual(self.stream("First.\n", "Second answer.", final),
                                 [("A", "First.\nSecond answer."), ("S", "s1")])

    def test_a_final_whose_first_word_never_streamed_shows_under_the_reply(self) -> None:
        # Review 3 (W3): Hermes wrote a warning in place of the last call's reply.
        warning = "⚠️ The model produced only internal reasoning and no final answer, despite retries."
        self.assertEqual(self.stream("Let me check.", "", warning), [("A", "Let me check."), ("S", "s1"), ("A", warning)])

    def test_without_a_steer_of_the_persons_own_the_final_is_adopted_as_before(self) -> None:
        self.assertEqual(self.stream("Hello wrld", "", "Hello world", agent="child alpha")[0], ("A", "Hello world"))
        self.setUp()
        self.transcript.apply(ev("message.start"))
        self.transcript.apply(ev("message.delta", text="Hello wrld"))
        self.transcript.apply(ev("message.complete", text="Hello world", status="complete"))
        self.assertEqual(self.replies(), [("A", "Hello world")])

    def test_a_steer_counts_for_its_own_turn_only(self) -> None:
        self.stream("First.", "", "First.")
        self.transcript.apply(ev("message.start"))
        self.transcript.apply(ev("message.delta", text="Hello wrld"))
        self.transcript.apply(ev("message.complete", text="Hello world", status="complete"))
        self.assertEqual(self.replies()[-1], ("A", "Hello world"))

    def test_settling_a_megabyte_reply_is_linear(self) -> None:
        # The owner's bound: settling never scans the stream more than a fixed number of times.
        body = "word and more " * 75_000  # about 1 MB
        start = time.perf_counter()
        replies = self.stream(body, "", body + "\n\nfooter")
        self.assertLess(time.perf_counter() - start, 3.0)
        self.assertEqual(" ".join(replies[0][1].split()), " ".join((body + "footer").split()))
        self.setUp()
        start = time.perf_counter()
        self.stream(body, "", "z" * 1_000_000)  # no opening in common: a bounded search, then its own block
        self.assertLess(time.perf_counter() - start, 3.0)


class TurnEndTests(LoopTestCase):
    def test_interrupted_turn_keeps_the_partial_reply_and_says_so(self) -> None:
        self.user("Write the numbers from 1 to 300, one per line, nothing else.")
        self.step(ev("message.start"))
        self.step(ev("tool.generating", name="terminal"))
        self.step(ev("tool.start", tool_id="call_b51f", name="terminal", context="seq 1 300", args={"command": "seq 1 300"}))
        self.step(
            ev(
                "tool.complete",
                tool_id="call_b51f",
                name="terminal",
                duration_s=0.060745954513549805,
                result={"output": "1\n2\n3\n4\n5\n[trimmed: 295 more lines]", "exit_code": 0, "error": None},
            )
        )
        flushed = self.step(ev("message.delta", text="\n\n1\n2\n"))
        self.assertEqual(
            flushed, ["", "  ● terminal(seq 1 300)  0.1s", "    ⎿  1", "       2", "       3", "       … +3 lines · ctrl+o shows all", "", "  ⚚ Hermes", "    1", "    2"]
        )
        flushed = self.step(ev("message.complete", text="1\n2", status="interrupted", partial=True))
        self.assertEqual(flushed, ["", "⚠ Interrupted."])
        self.assertEqual(self.taken[-1][0].style, THEME.warn)
        self.assertFalse(self.transcript.running)

    def test_a_tool_still_running_at_the_interrupt_is_marked_interrupted(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("tool.start", tool_id="a", name="terminal", context="sleep 60"))
        flushed = self.step(ev("message.complete", text="", status="interrupted"))
        self.assertEqual(flushed, ["  ▪ terminal(sleep 60)", "", "⚠ Interrupted."])

    def test_an_error_with_no_reply_shows_only_the_error(self) -> None:
        self.user("hi")
        self.step(ev("message.start"))
        flushed = self.step(
            ev("message.complete", text="Error: provider returned 500", status="error", error="provider returned 500")
        )
        self.assertEqual(flushed, ["", "✗ provider returned 500"])
        self.assertEqual(self.taken[-1][0].style, THEME.error)
        self.assertFalse(any(isinstance(block, AssistantBlock) for block in self.transcript.blocks))

    def test_an_error_after_a_partial_reply_keeps_the_reply(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("message.delta", text="Partial answer\nsecond"))
        self.step(ev("message.complete", text="Partial answer\nsecond", status="error", error="stream cut", partial=True))
        self.assertEqual(self.history(), ["  ⚚ Hermes", "    Partial answer", "    second", "", "✗ stream cut"])

    def test_an_error_without_error_text_still_says_the_turn_failed(self) -> None:
        self.step(ev("message.start"))
        self.assertEqual(self.step(ev("message.complete", status="error")), ["✗ The turn ended with an error."])

    def test_status_updates_are_transient(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("status.update", kind="compacting", text="Compacting context…"))
        self.assertEqual(self.transcript.status, "Compacting context…")
        self.step(ev("status.update", kind="status"))
        self.assertEqual(self.transcript.status, "Compacting context…")
        self.step(ev("message.complete", text="done", status="complete", warning="Context is 90% full."))
        self.assertEqual(self.transcript.status, "")
        self.assertEqual(self.history(), ["  ⚚ Hermes", "    done", "", "⚠ Context is 90% full."])

    def test_notices_flush_at_once_in_their_level_style(self) -> None:
        self.transcript.add_notice("Ctrl+C again to exit")
        self.transcript.add_notice("approval declined", "warn")
        self.transcript.add_notice("gateway exited", "error")
        self.assertEqual(self.step(), ["· Ctrl+C again to exit", "", "⚠ approval declined", "", "✗ gateway exited"])
        self.assertEqual([row[0].style for row in self.taken if row], [THEME.muted, THEME.warn, THEME.error])

    def test_unknown_events_and_bad_payloads_change_nothing(self) -> None:
        self.step(ev("session.info", running=True))
        self.step(Event(type="message.delta", session_id=SID, payload={"text": 42}))
        self.step(ev("tool.complete"))
        self.assertEqual(self.history(), ["  ● tool"])


SGR_RED = "\x1b[38;2;255;80;80m"
SGR_RESET = "\x1b[0m"
OSC8_OPEN = "\x1b]8;;https://example.com\x1b\\"
OSC8_CLOSE = "\x1b]8;;\x1b\\"
CURSOR_MOVES = "\x1b[2A\x1b[10;5H\x1b[K"


def painted(text: str) -> str:
    """`text` wrapped in the escape kinds gateway text may carry: SGR colour, an OSC 8 link, cursor moves."""
    return f"{CURSOR_MOVES}{SGR_RED}{OSC8_OPEN}{text}{OSC8_CLOSE}{SGR_RESET}"


class EscapeHygieneTests(LoopTestCase):
    """Every entry point where gateway text becomes a Line drops whole escape sequences, never just ESC."""

    def assert_clean(self, rows: list[Line]) -> None:
        for row in rows:
            for span in row:
                self.assertFalse(any(is_control(ch) for ch in span.text), span.text)
                for debris in ("[38;2", "[0m", "]8;;", "[2A", "[10;5H", "[K"):
                    self.assertNotIn(debris, span.text)

    def test_no_entry_point_leaves_escape_debris(self) -> None:
        self.user(painted("user prompt"))
        self.step(ev("message.start"))
        self.step(ev("thinking.delta", text=painted("spinner text")))
        self.assertEqual(self.transcript.activity, "spinner text")
        self.step(ev("status.update", kind="status", text=painted("Compacting…")))
        self.assertEqual(self.transcript.status, "Compacting…")
        self.step(ev("reasoning.delta", text=painted("weighing it")))
        self.assertEqual(self.live(), ["", "▸ thinking… weighing it"])
        self.step(ev("tool.generating", name=painted("terminal")))
        self.step(ev("tool.start", tool_id="t1", name=painted("terminal"), context=painted("ls -la")))
        self.step(
            ev(
                "tool.complete",
                tool_id="t1",
                name=painted("terminal"),
                duration_s=0.5,
                summary=painted("listed 3 files"),
                result={"exit_code": 0},
            )
        )
        self.step(ev("message.delta", text=painted("**answer** line") + "\n"))
        self.step(ev("message.complete", text="", status="complete", warning=painted("context is 90% full")))
        self.transcript.add_notice(painted("a notice"), "warn")
        self.step()
        self.assert_clean(self.taken)
        history = self.history()
        self.assert_clean(self.transcript.history_lines(WIDTH, THEME, details=True))
        self.assertEqual(
            history,
            [
                "  ❯ user prompt",
                "",
                "▾ thought for 0.0s",
                "  weighing it",
                "",
                "  ● terminal(ls -la)  0.5s",
                "    ⎿  listed 3 files",
                "",
                "  ⚚ Hermes",
                "    answer line",
                "",
                "⚠ context is 90% full",
                "",
                "⚠ a notice",
            ],
        )


# A `patch` completion shaped like Hermes 6c61c3e27d's: the parsed PatchResult dict, and
# `inline_diff` as `render_edit_diff_with_delta` writes it (review header, SGR on every line).
PATCH_DIFF = "--- a/src/app.py\n+++ b/src/app.py\n@@ -1,2 +1,2 @@\n import os\n-print('hello')\n+print('안녕 🌏')\n"
PATCH_ARGS = {"mode": "replace", "path": "src/app.py", "old_string": "print('hello')", "new_string": "print('안녕 🌏')"}
PATCH_INLINE_DIFF = "\n".join(
    [
        "  ┊ review diff",
        "\x1b[38;2;180;160;255ma/src/app.py → b/src/app.py\x1b[0m",
        "\x1b[38;2;120;120;140m@@ -1,2 +1,2 @@\x1b[0m",
        "\x1b[38;2;150;150;150m import os\x1b[0m",
        "\x1b[38;2;255;255;255;48;2;120;20;20m-print('hello')\x1b[0m",
        "\x1b[38;2;255;255;255;48;2;20;90;20m+print('안녕 🌏')\x1b[0m",
    ]
)


def big_inline_diff(added: int) -> str:
    rows = ["  ┊ review diff", "\x1b[38;2;180;160;255ma/big.py → b/big.py\x1b[0m", "\x1b[38;2;120;120;140m@@ -0,0 +1 @@\x1b[0m"]
    rows.extend(f"\x1b[38;2;255;255;255;48;2;20;90;20m+row {number}\x1b[0m" for number in range(1, added + 1))
    return "\n".join(rows)


class InlineDiffTests(LoopTestCase):
    def edit(self, inline_diff: str | None, result: object, tool_id: str = "call_patch") -> None:
        self.step(ev("tool.generating", name="patch"))
        self.step(ev("tool.start", tool_id=tool_id, name="patch", context="src/app.py", args=PATCH_ARGS))
        payload: dict[str, object] = {"tool_id": tool_id, "name": "patch", "args": PATCH_ARGS, "duration_s": 0.31,
                                      "result": result}
        if inline_diff is not None:
            payload["inline_diff"] = inline_diff
        self.step(ev("tool.complete", **payload))

    def test_an_edit_shows_its_diff_under_its_row_through_the_whole_turn(self) -> None:
        self.user("Say hello in Korean in src/app.py")
        self.step(ev("message.start"))
        self.step(ev("message.delta", text="Editing the greeting.\n"))
        self.step(ev("message.interim", text="Editing the greeting.", already_streamed=True))
        self.edit(PATCH_INLINE_DIFF, {"success": True, "diff": PATCH_DIFF, "files_modified": ["src/app.py"]})
        live = self.live()
        self.assertEqual(live[live.index("  ● patch(src/app.py)  0.3s") + 1], "    ⎿  src/app.py")
        flushed = self.step(ev("message.delta", text="\n\nDone — it prints 안녕 now."))
        diff = self.taken[-4:]
        self.step(ev("message.complete", text="Done — it prints 안녕 now.", status="complete"))
        self.assertEqual(
            flushed,
            [
                "",
                "  ● patch(src/app.py)  0.3s",
                "    ⎿  src/app.py",
                "     1  import os",
                "     2 -print('hello')" + " " * 38,  # the diff's band ends at the edge, beside the rail
                "     2 +print('안녕 🌏')" + " " * 36,
            ],
        )
        self.assertEqual([row[-1].style for row in diff], [THEME.label, THEME.code, THEME.diff_remove, THEME.diff_add])
        self.assertEqual([line_width(row) for row in diff[-2:]], [WIDTH, WIDTH])
        self.assertFalse(any(is_control(ch) for row in self.taken for span in row for ch in span.text))
        self.assertEqual(self.history(details=False), lines_text(self.taken))
        self.assertEqual(self.history()[-2:], ["  ⚚ Hermes", "    Done — it prints 안녕 now."])

    def test_a_long_diff_is_capped_until_history_shows_it_all(self) -> None:
        self.step(ev("message.start"))
        self.edit(big_inline_diff(40), {"success": True})
        flushed = self.step(ev("message.complete", text="", status="complete"))
        # the tool row, then the first 24 diff lines less the hunk header that became the gutter, then the count
        self.assertEqual(len(flushed), 1 + 23 + 1)
        self.assertEqual(flushed[-2].rstrip(), "    22 +row 22")
        self.assertEqual(flushed[-1], "       … +18 lines · ctrl+o shows all")
        self.assertEqual(self.taken[-1][-1].style, THEME.muted)
        full = self.history(details=True)
        self.assertEqual(len(full), 1 + 41)
        self.assertEqual(full[-1].rstrip(), "    40 +row 40")
        self.assertNotIn("       … +18 lines · ctrl+o shows all", full)

    def test_toggled_details_show_the_whole_live_diff_and_never_reach_a_taken_one(self) -> None:
        self.step(ev("message.start"))
        self.edit(big_inline_diff(30), {"success": True})
        self.assertEqual(self.live()[-1], "       … +8 lines · ctrl+o shows all")
        self.transcript.toggle_details()
        self.assertEqual(self.live()[-1].rstrip(), "    30 +row 30")
        self.transcript.toggle_details()
        self.step(ev("message.complete", text="", status="complete"))
        self.transcript.toggle_details()
        self.assertEqual(lines_text(self.taken)[-1], "       … +8 lines · ctrl+o shows all")
        self.assertEqual(self.live(), [])

    def test_a_denied_edit_without_a_diff_shows_nothing_extra_and_a_failed_one_its_error(self) -> None:
        self.step(ev("message.start"))
        self.edit(None, {"approved": False, "user_consent": False}, tool_id="a")
        self.edit("", {"success": False, "error": "old_string not found in src/app.py"}, tool_id="b")
        self.edit("  ┊ review diff", {"success": False, "error": "no change"}, tool_id="c")
        flushed = self.step(ev("message.complete", text="", status="complete"))
        self.assertEqual(
            flushed,
            [
                "  ✗ patch(src/app.py)  0.3s",
                "    ⎿  denied",
                "",
                "  ✗ patch(src/app.py)  0.3s",
                "    ⎿  old_string not found in src/app.py",
                "",
                "  ✗ patch(src/app.py)  0.3s",
                "    ⎿  no change",
            ],
        )

    def test_a_diff_takes_the_width_of_the_frame_that_flushes_it_and_retake_rewraps_it(self) -> None:
        self.step(ev("message.start"))
        self.edit(PATCH_INLINE_DIFF, {"success": True}, tool_id="w")
        self.assertTrue(all(line_width(row) == 30 for row in self.transcript.live_lines(30, THEME)[-2:]))
        self.step(ev("message.complete", text="", status="complete"), width=44)
        self.assertTrue(all(line_width(row) == 44 for row in self.taken[-2:]))
        self.assertEqual(self.transcript.take_stable_lines(30, THEME), [])
        self.transcript.retake()
        again = self.transcript.take_stable_lines(30, THEME)
        self.assertEqual(again, self.transcript.history_lines(30, THEME, details=False))
        self.assertTrue(all(line_width(row) == 30 for row in again[-2:]))



class BridgeToolRowTests(unittest.TestCase):
    """Hermes' tool bridge (`tool_call`, `tool_search`, `tool_describe`) previews a call as a label, `<what> · <detail>`."""

    def row_text(self, name: str, context: str, expanded: bool = False) -> str:
        from _tui_lines import line_text

        transcript = Transcript(lambda: 0.0)
        transcript.apply(Event("message.start", "s", {}))
        transcript.apply(Event("tool.start", "s", {"tool_id": "t1", "name": name, "context": context}))
        transcript.apply(Event("tool.complete", "s", {"tool_id": "t1", "name": name, "result": {}}))
        group = next(block for block in transcript.blocks if isinstance(block, ToolGroup))
        return line_text(block_rows(group, 80, THEME, expanded)[0])

    def test_its_label_never_reads_as_the_transcripts_own_tool_count(self) -> None:
        # Review B NIT 11: `✓ tool_describe  Reading tool details · 1 tool` read as a count of tools. In the
        # transcript the call folds into `Read tool details`; the details view unfolds it, label and all.
        self.assertEqual(self.row_text("tool_describe", "Reading tool details · 1 tool"), "  ● Read tool details  0.0s")
        row = self.row_text("tool_describe", "Reading tool details · 1 tool", expanded=True)
        self.assertIn("Reading tool details: 1 tool", row)
        self.assertNotIn("· 1 tool", row)
        self.assertIn("GitHub: Create issue", self.row_text("tool_call", "GitHub · Create issue"))

    def test_another_tools_context_is_shown_as_it_came(self) -> None:
        self.assertIn("notes · draft.md", self.row_text("read_file", "notes · draft.md"))


if __name__ == "__main__":
    unittest.main()


class CommandOutputTests(LoopTestCase):
    """A command the person runs is echoed, and what it prints stays under the echo in the transcript."""

    def test_the_echo_waits_live_and_its_output_lands_under_it(self) -> None:
        self.transcript.add_command("/model")
        self.assertEqual(self.step(), [])  # still waiting for the command's output
        self.assertEqual(self.live(), ["  ❯ /model"])
        self.transcript.add_output("Current model: deepseek/deepseek-v4.1-flash-ultrafast")
        self.assertEqual(self.step(), [])  # more may come until the command is over
        self.transcript.close_command()
        self.assertEqual(self.step(), ["  ❯ /model", "    ⎿  Current model: deepseek/deepseek-v4.1-flash-ultrafast"])

    def test_a_notice_while_the_echo_is_open_is_the_commands_output_in_its_level(self) -> None:
        self.transcript.add_command("/theme nope")
        self.transcript.add_notice("No theme named nope.", "warn")
        self.transcript.close_command()
        self.assertEqual(self.step(), ["  ❯ /theme nope", "    ⎿  ⚠ No theme named nope."])  # a glyph, not only a hue
        self.assertEqual(self.taken[-1][-1].style, THEME.warn)

    def test_several_outputs_stack_under_one_echo_until_it_closes(self) -> None:
        self.transcript.add_command("/reload-skills")
        self.transcript.add_output("Skills reloaded.")
        self.transcript.add_notice("Hermes' command catalog: two skills share a name", "warn")
        self.transcript.close_command()
        self.assertEqual(
            self.step(), ["  ❯ /reload-skills", "    ⎿  Skills reloaded.", "       ⚠ Hermes' command catalog: two skills share a name"]
        )

    def test_an_echo_closed_without_output_flushes_alone_and_the_next_block_follows(self) -> None:
        self.transcript.add_command("/details")
        self.transcript.add_user("go on")
        self.assertEqual(self.step(), ["  ❯ /details", "", "  ❯ go on"])

    def test_output_that_comes_after_the_echo_closed_repeats_it(self) -> None:
        self.transcript.add_command("/usage")
        self.transcript.add_user("next prompt")
        self.step()
        self.transcript.add_output("Session cost: $0.01", command="/usage")
        self.assertEqual(self.step(), ["", "  ❯ /usage", "    ⎿  Session cost: $0.01"])

    def test_long_output_shows_its_first_rows_and_counts_the_rest_for_history(self) -> None:
        self.transcript.add_command("/context")
        self.transcript.add_output("\n".join(f"row {number}" for number in range(30)))
        self.transcript.close_command()
        flushed = self.step()
        self.assertEqual(len(flushed), 1 + OUTPUT_PREVIEW_ROWS + 1)
        self.assertEqual(flushed[1], "    ⎿  row 0")
        self.assertEqual(flushed[OUTPUT_PREVIEW_ROWS], f"       row {OUTPUT_PREVIEW_ROWS - 1}")
        self.assertEqual(flushed[-1], f"       … +{30 - OUTPUT_PREVIEW_ROWS} rows · ctrl+o shows all")
        self.assertEqual(self.history()[-1], "       row 29")

    def test_the_count_names_rows_since_it_counts_them_at_this_width(self) -> None:
        # The same output wraps to more rows on a narrower terminal; the word says what is counted.
        self.transcript.add_command("/context")
        self.transcript.add_output("\n".join(f"row {number} " + "x" * 30 for number in range(20)))
        self.transcript.close_command()
        (block,) = self.transcript.blocks
        for width in (100, 40):
            rows = lines_text(block_rows(block, width, THEME))
            self.assertRegex(rows[-1], r"… \+\d+ rows · ctrl\+o shows all")

    def test_whole_output_is_never_cut(self) -> None:
        self.transcript.add_command("/help")
        self.transcript.add_output("\n".join(f"row {number}" for number in range(30)), whole=True)
        self.transcript.close_command()
        self.assertEqual(len(self.step()), 1 + 30)

    def test_the_block_is_one_command_and_its_output(self) -> None:
        self.transcript.add_command("/model")
        self.transcript.add_output("x")
        self.transcript.close_command()
        block = self.transcript.blocks[-1]
        self.assertIsInstance(block, CommandBlock)
        self.assertEqual((block.command, block.done), ("/model", True))


class WithdrawCommandTests(LoopTestCase):
    """`withdraw_command` takes back the open echo only while it has printed nothing, and only that echo."""

    def run_call(self) -> None:
        self.step(ev("message.start"))
        self.step(ev("tool.start", tool_id="t1", name="terminal", context="make test"))

    def test_an_open_echo_goes_before_it_is_printed(self) -> None:
        block = self.transcript.add_command("/dag-ulw fix it")
        self.assertEqual(self.step(), [])
        self.assertIn("  ❯ /dag-ulw fix it", self.live())
        self.assertIs(self.transcript.withdraw_command(), block)
        self.assertEqual(self.step(), [])
        self.assertEqual((self.transcript.blocks, self.live()), ([], []))

    def test_an_echo_held_under_a_running_call_leaves_the_tail_at_once(self) -> None:
        self.run_call()
        block = self.transcript.add_command("/dag-ulw fix it")
        self.assertIn("  ❯ /dag-ulw fix it", self.live())
        self.assertIs(self.transcript.withdraw_command(), block)
        self.assertNotIn("  ❯ /dag-ulw fix it", self.live())  # the tail drawn before is not reused
        self.step()

    def test_an_echo_with_output_under_it_stays(self) -> None:
        block = self.transcript.add_command("/usage")
        self.transcript.add_output("Session cost: $0.01")
        self.assertIsNone(self.transcript.withdraw_command())
        self.assertEqual(self.transcript.blocks, [block])

    def test_a_closed_echo_stays(self) -> None:
        block = self.transcript.add_command("/dag-ulw fix it")
        self.transcript.close_command(block)
        self.step()
        self.assertIsNone(self.transcript.withdraw_command())
        self.assertEqual(self.transcript.blocks, [block])

    def test_of_two_held_echoes_of_one_line_the_open_one_goes(self) -> None:
        self.run_call()
        first = self.transcript.add_command("/dag-ulw fix it")
        second = self.transcript.add_command("/dag-ulw fix it")  # equal as dataclasses: the same text
        self.assertIs(self.transcript.withdraw_command(), second)
        self.transcript.close_command(first)
        self.transcript.apply(ev("tool.complete", tool_id="t1", name="terminal", result={"output": "ok"}))
        self.transcript.apply(ev("message.complete", text="done", status="complete"))  # writes what was held
        echoes = [block for block in self.transcript.blocks if isinstance(block, CommandBlock)]
        self.assertEqual(len(echoes), 1)
        self.assertIs(echoes[0], first)


class ToolOutputTests(LoopTestCase):
    """Each tool row shows the first lines of what the tool printed; a failed one, its error's first line."""

    def run_tool(self, result: object, name: str = "terminal", **payload: object) -> list[str]:
        self.step(ev("message.start"))
        self.step(ev("tool.start", tool_id="t1", name=name, context="seq 1 300"))
        self.step(ev("tool.complete", tool_id="t1", name=name, result=result, duration_s=0.06, **payload))
        return self.step(ev("message.complete", text="", status="complete"))

    def test_the_first_three_lines_of_the_output_and_a_count_of_the_rest(self) -> None:
        # Recorded from Hermes 6c61c3e27d (session fixture, the interrupted turn's `seq 1 300`).
        flushed = self.run_tool({"output": "1\n2\n3\n4\n5\n[trimmed: 295 more lines]", "exit_code": 0, "error": None})
        self.assertEqual(flushed[0], "  ● terminal(seq 1 300)  0.1s")
        self.assertEqual(self.taken[-5][:3], (rail_cell(THEME.accent), Span(" ", GUTTER), Span("●", THEME.ok)))
        self.assertEqual(flushed[1:], ["    ⎿  1", "       2", "       3", "       … +3 lines · ctrl+o shows all"])  # under the call
        self.assertEqual(self.taken[-1][-1].style, THEME.faint)

    def test_a_failed_tool_shows_its_errors_first_line_in_the_error_colour(self) -> None:
        flushed = self.run_tool({"output": "", "exit_code": 2, "error": "ls: x.py: No such file or directory\nmore"})
        self.assertEqual(self.taken[-2][:3], (rail_cell(THEME.error), Span(" ", GUTTER), Span("✗", THEME.error)))
        self.assertEqual(flushed[1:], ["    ⎿  ls: x.py: No such file or directory"])
        self.assertEqual(self.taken[-1][0], rail_cell(THEME.error))  # what it said is grey: the rail says it failed
        self.assertEqual(self.taken[-1][-1].style, THEME.faint)

    def test_a_command_that_failed_by_its_exit_code_shows_the_end_of_what_it_printed(self) -> None:
        # Hermes' terminal tool reports a non-zero exit as output plus exit_code with error None
        # (tools/terminal_tool_result.py); pytest's summary is at the end, its banner at the start.
        output = "\n".join(["==== test session starts ====", "collected 3 items", "", "test_x.py .F.", "",
                             "FAILED test_x.py::test_b - assert 1 == 2", "==== 1 failed, 2 passed in 0.10s ===="])
        flushed = self.run_tool({"output": output, "exit_code": 1, "error": None})
        self.assertEqual(self.taken[-5][2], Span("✗", THEME.error))
        self.assertEqual(flushed[1:], ["    ⎿  … +2 lines · ctrl+o shows all", "       test_x.py .F.",
                                       "       FAILED test_x.py::test_b - assert 1 == 2",
                                       "       ==== 1 failed, 2 passed in 0.10s ===="])
        self.assertEqual(self.taken[-1][-1].style, THEME.faint)
        self.assertEqual(self.taken[-4][-1].style, THEME.faint)  # the count, above what it counts

    def test_a_tool_that_printed_nothing_adds_no_row(self) -> None:
        self.assertEqual(len(self.run_tool({"output": "", "exit_code": 0, "error": None})), 1)

    def test_a_tool_whose_result_holds_no_text_adds_no_row(self) -> None:
        self.assertEqual(len(self.run_tool({"responses": [{"status": "answered"}]}, name="clarify")), 1)

    def test_an_edit_with_a_diff_shows_the_diff_and_no_output(self) -> None:
        diff = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-a\n+b"
        flushed = self.run_tool({"success": True, "output": "patched x.py"}, name="patch", inline_diff=diff)
        self.assertNotIn("patched x.py", "\n".join(flushed))

    def test_details_show_more_of_the_output(self) -> None:
        self.run_tool({"output": "\n".join(f"row {number}" for number in range(10)), "exit_code": 0})
        detailed = self.history(details=True)
        self.assertIn("       row 9", detailed)

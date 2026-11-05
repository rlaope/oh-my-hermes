"""A clarify question with choices, drawn the way Claude Code draws AskUserQuestion.

Two rules across the width frame it; the asked sentence is bold and the
context before it dim; a `label — description` choice shows its description
dim under its label; its keys are on its own row under the bottom rule. The
picker's own words are English whatever language the question is in; only the
model's question and choices keep theirs. What a pick sends back is Hermes'
own choice string, whatever the row shows.
"""

from __future__ import annotations

import unittest

from _tui_lines import line_text, lines_text
from test_tui_modes import SID, drawn, make_app
from omh.tui import prompts
from omh.tui.gateway import Event, ServerRequest
from omh.tui.keys import CHAR, DOWN, ENTER, Key
from omh.tui.style import NO_COLOR
from omh.tui.theme import DEFAULT_THEME, without_colour
from omh.tui.transcript import _call_summary
from omh.tui.width import cell_width

# The owner's question of 2026-11-05, as the model wrote it: context, then the asked sentence.
KOREAN = {
    "questions": [{
        "qid": "q0",
        "question": (
            "PR #2565에서 `distribution (macos-latest)` 한 개만 세 번 연속으로 러너를 받지 못하고 15분 만에 "
            "취소됐습니다. 세 번 모두 실행 단계 0개, 러너 이름 없음이었습니다. 나머지 11개는 통과했습니다. "
            "어떻게 할까요?"
        ),
        "choices": [
            "지금 머지 — macOS 결과 없이 머지하고 PR B 시작 (Recommended)",
            "재실행 — 러너가 잡힐 때까지 재실행하고 통과하면 머지",
            "대기",
        ],
        "multi_select": False,
    }],
}
ENGLISH = {
    "questions": [{
        "qid": "q0",
        "question": "The quality bar is 0.95 and the run scored 0.981 on recall. Merge the alternative anyway?",
        "choices": ["Merge — every other gate passed (Recommended)", "Close — keep the bar as registered"],
        "multi_select": False,
    }],
}


def slot(params: dict) -> prompts.PromptSlot:
    opened = prompts.open_request("srq-1", "clarify", params)
    assert isinstance(opened, prompts.PromptSlot)
    return opened


def text(params: dict, width: int = 150, rows: int = 30, **kwargs) -> list[str]:
    return lines_text(slot(params).lines(width, DEFAULT_THEME, rows, **kwargs))


class FrameTests(unittest.TestCase):
    def test_a_korean_question_keeps_its_words_and_the_picker_keeps_english(self) -> None:
        drawn = text(KOREAN, waited="14m 42s")
        rule = prompts.FRAME_RULE * 150
        self.assertEqual(drawn[0], rule)
        self.assertEqual(drawn[-2], rule)
        self.assertEqual(drawn[-1], "  Enter to select · ↑↓ to navigate · Esc to cancel · 14m 42s")
        self.assertEqual(drawn[-9:-2], [
            "▌ ",
            "▌ ❯ 1. 지금 머지 (Recommended)",
            "▌      macOS 결과 없이 머지하고 PR B 시작",
            "▌   2. 재실행",
            "▌      러너가 잡힐 때까지 재실행하고 통과하면 머지",
            "▌   3. 대기",
            "▌   4. Type something.",
        ])
        self.assertEqual(drawn[-10], "▌ 어떻게 할까요?")

    def test_english_question_gets_english_keys_and_claude_codes_free_text_row(self) -> None:
        drawn = text(ENGLISH)
        self.assertEqual(drawn[1:-2], [
            "▌ The quality bar is 0.95 and the run scored 0.981 on recall.",
            "▌ Merge the alternative anyway?",
            "▌ ",
            "▌ ❯ 1. Merge (Recommended)",
            "▌      every other gate passed",
            "▌   2. Close",
            "▌      keep the bar as registered",
            "▌   3. Type something.",
        ])
        self.assertEqual(drawn[-1], "  Enter to select · ↑↓ to navigate · Esc to cancel")

    def test_the_asked_sentence_is_bold_and_the_context_dim(self) -> None:
        rows = slot(ENGLISH).lines(150, DEFAULT_THEME, 30)
        context = next(span for span in rows[1] if "quality bar" in span.text)
        asked = next(span for span in rows[2] if "Merge the alternative" in span.text)
        self.assertEqual(context.style, DEFAULT_THEME.muted)
        self.assertTrue(asked.style.bold)
        self.assertFalse(context.style.bold)

    def test_no_color_keeps_the_layout_and_the_bold_question(self) -> None:
        theme = without_colour(DEFAULT_THEME)
        rows = slot(ENGLISH).lines(150, theme, 30)
        self.assertEqual(lines_text(rows), text(ENGLISH))
        asked = next(span for span in rows[2] if "Merge the alternative" in span.text)
        self.assertTrue(asked.style.bold)
        self.assertEqual(asked.style.depth, NO_COLOR)

    def test_a_narrow_terminal_wraps_and_shortens_the_key_row(self) -> None:
        drawn = text(KOREAN, width=60)
        self.assertEqual(drawn[0], prompts.FRAME_RULE * 60)
        self.assertEqual(drawn[-1], "  Enter to select · ↑↓ to navigate · Esc to cancel")
        for row in drawn:
            self.assertLessEqual(cell_width(row), 60, row)
        self.assertIn("▌ ❯ 1. 지금 머지 (Recommended)", drawn)

    def test_ctrl_o_view_has_no_key_row_and_no_rules(self) -> None:
        # The pager has keys of its own (Esc goes back), so the picker's key row would be wrong there.
        whole = lines_text(slot(KOREAN).whole_lines(150, DEFAULT_THEME))
        self.assertTrue(all(row.startswith(prompts.SLOT_BAR) for row in whole), whole)
        self.assertFalse([row for row in whole if "Esc" in row or prompts.FRAME_RULE * 10 in row], whole)
        self.assertEqual(whole[-1], "▌   4. Type something.")

    def test_long_context_is_capped_and_ctrl_o_shows_all_of_it(self) -> None:
        long = {"questions": [{**KOREAN["questions"][0],
                               "question": "배경 설명입니다. " * 60 + "어떻게 할까요?"}]}
        drawn = text(long, width=80)
        context = drawn[1 : drawn.index("▌ 어떻게 할까요?")]
        self.assertEqual(len(context), prompts.LEAD_ROWS)
        self.assertTrue(context[-1].endswith(prompts.MORE_FORMS), context[-1])
        whole = lines_text(slot(long).whole_lines(80, DEFAULT_THEME))
        joined = "".join(row.removeprefix("▌ ") for row in whole)
        self.assertEqual(joined.count("설명입니다."), 60)  # wrapping eats the space a row breaks at

    def test_short_rows_drop_the_frame_and_the_context_before_the_asked_sentence(self) -> None:
        self.assertEqual(text(KOREAN, width=80, rows=5), [
            "▌ 어떻게 할까요? … ctrl+o shows all",
            "▌ ❯ 1. 지금 머지 (Recommended)",
            "▌      macOS 결과 없이 머지하고 PR B 시작 … ctrl+o shows all",
            "  Enter to select · ↑↓ to navigate · Esc to cancel",
        ])
        self.assertEqual(text(KOREAN, width=80, rows=13)[0], prompts.FRAME_RULE * 80)  # the rules once nothing is cut
        self.assertEqual(len(text(KOREAN, rows=2)), 2)
        self.assertEqual(text(KOREAN, rows=1), ["▌ ❯ 1. 지금 머지 (Recommended) … ctrl+o shows all"])

    def test_the_key_row_needs_three_rows(self) -> None:
        self.assertEqual(prompts.FRAMED_FOOTER_MIN_ROWS, 3)
        for rows in (1, 2):
            with self.subTest(rows=rows):
                drawn = text(ENGLISH, rows=rows)
                self.assertFalse([row for row in drawn if "Esc to cancel" in row], drawn)
                self.assertTrue(all(row.startswith(prompts.SLOT_BAR) for row in drawn), drawn)
        drawn = text(ENGLISH, rows=3)
        self.assertEqual(drawn[-1], "  Enter to select · ↑↓ to navigate · Esc to cancel")
        self.assertEqual(len(drawn), 3)

    def test_the_key_row_follows_the_state(self) -> None:
        clarify = slot(KOREAN)
        clarify.handle_key(Key(CHAR, "x"))  # opens the text field
        self.assertEqual(lines_text(clarify.lines(150, DEFAULT_THEME, 30))[-1], "  Enter to send · ↑↓ back to the choices · Esc to cancel")
        multi = {"questions": [{**ENGLISH["questions"][0], "multi_select": True}]}
        drawn = text(multi)
        self.assertEqual(drawn[-1],
                         "  Space to tick · Enter to send · ↑↓ to navigate · Esc to cancel")
        self.assertIn("▌ Merge the alternative anyway? (choose one or more)", drawn)
        closed = {"questions": [{**ENGLISH["questions"][0], prompts.CLOSED_CHOICES: True}]}
        self.assertEqual(text(closed)[-1], "  Enter to select · ↑↓ to navigate · Esc to cancel")
        self.assertNotIn("▌   3. Type something.", text(closed))

    def test_a_framed_question_leaves_the_info_line_to_its_own_key_row(self) -> None:
        self.assertTrue(slot(KOREAN).framed)
        self.assertFalse(slot({"questions": [{"qid": "q0", "question": "Why?"}]}).framed)
        self.assertFalse(prompts.open_request("srq-2", "approval", {"command": "ls"}).framed)


class AnswerTests(unittest.TestCase):
    def test_a_pick_answers_with_hermes_string(self) -> None:
        self.assertEqual(slot(KOREAN).handle_key(Key(ENTER)).frame,
                         {"result": {"answers": {"q0": "지금 머지 — macOS 결과 없이 머지하고 PR B 시작 (Recommended)"}}})
        clarify = slot(ENGLISH)
        clarify.handle_key(Key(DOWN))
        self.assertEqual(clarify.handle_key(Key(ENTER)).frame,
                         {"result": {"answers": {"q0": "Close — keep the bar as registered"}}})

    def test_choice_parts(self) -> None:
        cases = {
            "a — b (Recommended)": ("a (Recommended)", "b"),
            "머지 — 지금 머지 (recommended) ": ("머지 (Recommended)", "지금 머지"),  # Hermes' tag, in Hermes' words
            "a — b — c": ("a", "b — c"),
            "plain": ("plain", ""),
            "blue-green deploy": ("blue-green deploy", ""),  # a dash in a word never splits
            "2024—2026": ("2024—2026", ""),  # no spaces around it: not the separator
            " — only a description": ("— only a description", ""),
            "(Recommended) 머지": ("(Recommended) 머지", ""),
        }
        for choice, parts in cases.items():
            with self.subTest(choice=choice):
                self.assertEqual(prompts._choice_parts(choice), parts)


class QuestionPartsTests(unittest.TestCase):
    def test_the_last_sentence_ending_in_a_question_mark_is_asked(self) -> None:
        cases = {
            "Context here. More context. Merge it?": ("Context here. More context.", "Merge it?"),
            "OPT-L을 머지할까요? 품질은 기준 미달입니다.": ("", "OPT-L을 머지할까요? 품질은 기준 미달입니다."),
            "Opus costs 5x.\nSwitch this session to claude-opus-5-5?": ("Opus costs 5x.", "Switch this session to claude-opus-5-5?"),
            "어디에 만들까요？ (선택)": ("", "어디에 만들까요？ (선택)"),
            "First paragraph.\n\nSecond paragraph, no question": ("First paragraph.", "Second paragraph, no question"),
            "No question at all. Just this": ("", "No question at all. Just this"),
            "": ("", ""),
        }
        for question, parts in cases.items():
            with self.subTest(question=question):
                self.assertEqual(prompts.question_parts(question), parts)

    def test_nothing_is_dropped(self) -> None:
        question = KOREAN["questions"][0]["question"]
        lead, asked = prompts.question_parts(question)
        self.assertEqual(f"{lead} {asked}", question)


class AppTests(unittest.TestCase):
    """Through the app: the info line, the waiting row and the tool row while a framed question is open."""

    def open(self, params: dict) -> "tuple[object, list[float]]":
        from omh.tui.gateway import Event, ServerRequest
        from test_tui_modes import SID, make_app

        now = [1000.0]
        app, _client = make_app(busy=True, rows=30, cols=150, clock=lambda: now[0])
        app._on_event(Event("tool.start", SID, {"tool_id": "c1", "name": "clarify", "args": params,
                                                "context": params["questions"][0]["question"][:80]}))
        app._on_server_request(ServerRequest("srq-1", "clarify", params))
        return app, now

    def test_the_wait_moves_from_its_own_row_to_the_key_row_after_a_minute(self) -> None:
        from omh.tui.app import STATE_WAITING

        app, now = self.open(KOREAN)
        tail = [line_text(row) for row in app._tail(150)]
        self.assertFalse([row for row in tail if STATE_WAITING in row], tail)
        footer = line_text(app._slot_lines(150, 30)[-1])
        self.assertEqual(footer, "  Enter to select · ↑↓ to navigate · Esc to cancel")
        now[0] += 14 * 60 + 42
        self.assertEqual(line_text(app._slot_lines(150, 30)[-1]), footer + " · 14m 42s")
        self.assertNotIn("Esc", line_text(app._info_line(150)))

    def test_an_approval_keeps_its_waiting_row_and_info_line_keys(self) -> None:
        from omh.tui.app import STATE_WAITING
        from omh.tui.gateway import ServerRequest
        from test_tui_modes import make_app

        app, _client = make_app(busy=True, rows=30, cols=150)
        app._on_server_request(ServerRequest("srq-9", "approval", {"command": "rm -rf ./build", "description": "x"}))
        self.assertTrue([row for row in app._tail(150) if STATE_WAITING in line_text(row)])
        self.assertIn("esc denies", line_text(app._info_line(150)))

    def test_the_tool_row_counts_the_choices_instead_of_repeating_the_question(self) -> None:
        app, _now = self.open(KOREAN)
        rows = [line_text(row) for row in app._tail(150)]
        call = next(row for row in rows if "clarify" in row)
        self.assertIn("clarify(3 choices)", call)
        self.assertNotIn("할까요", call)

    def test_a_short_slot_gives_the_keys_back_to_the_info_line(self) -> None:
        from omh.tui.gateway import ServerRequest
        from test_tui_modes import make_app

        for rows, on_info in ((30, False), (6, False), (5, True)):
            with self.subTest(rows=rows):
                app, _client = make_app(busy=True, rows=rows, cols=100)
                app._on_server_request(ServerRequest("srq-1", "clarify", ENGLISH))
                cap = app._slot_cap(100, rows)
                self.assertEqual(cap < prompts.FRAMED_FOOTER_MIN_ROWS, on_info, cap)
                info = line_text(app._info_line(100))
                self.assertEqual("esc cancels" in info, on_info, info)
                slot_rows = [line_text(row) for row in app._slot_lines(100, rows)]
                self.assertEqual(any("Esc to cancel" in row for row in slot_rows), not on_info, slot_rows)


class ToolRowTests(unittest.TestCase):
    def test_the_clarify_row_counts_choices_or_questions(self) -> None:
        def summary(args: object) -> str:
            return _call_summary({"name": "clarify", "args": args, "context": "Ship it? Now."})

        self.assertEqual(summary({"questions": KOREAN["questions"]}), "3 choices")
        self.assertEqual(summary({"questions": [{"question": "q", "choices": ["only"]}]}), "1 choice")
        self.assertEqual(summary({"questions": [{"question": "a", "choices": ["x", "y"]}, {"question": "b"}]}),
                         "2 questions")
        # Absent or malformed arguments, or a question with no choices: the row reads as any tool's.
        for args in (None, {}, {"questions": []}, {"questions": "q"}, {"questions": [1]},
                     {"questions": [{"question": "Why?"}]}, {"questions": [{"question": "q", "choices": [1, 2]}]}):
            with self.subTest(args=args):
                self.assertEqual(summary(args), "Ship it? Now.")
        self.assertEqual(_call_summary({"name": "terminal", "context": "ls -la"}), "ls -la")


class FramedWaitLayoutTests(unittest.TestCase):
    """While a turn waits on a framed question, `_tail` draws no waiting row (the key row carries the clock), so the
    layout keeps no row for one either: on a short terminal the reply's last line stands above the question, not a
    blank row kept for a working row that is never drawn (#2575's review of #2573)."""

    def test_on_a_short_terminal_the_replys_last_line_stays_above_the_question(self) -> None:
        for rows, cols in ((8, 40), (9, 80), (10, 40)):
            with self.subTest(rows=rows, cols=cols):
                app, _client = make_app(busy=True, rows=rows, cols=cols)
                app._on_event(Event("message.delta", SID, {"text": "short reply"}))
                app._on_server_request(ServerRequest("srq-1", "clarify", {"session_id": SID, "questions": [
                    {"qid": "q0", "question": "Which color?", "choices": ["red", "blue"], "multi_select": False}]}))
                screen = drawn(app)
                at = next(index for index, line in enumerate(screen) if "Which color" in line)
                self.assertEqual(screen[at - 1], "┃   short reply")
                self.assertEqual(app._working_rows(), 0)
                self.assertFalse([line for line in screen if "Waiting" in line or "Working" in line])

    def test_an_approval_keeps_its_waiting_row(self) -> None:
        app, _client = make_app(busy=True, rows=24, cols=80)
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        drawn(app)
        self.assertEqual(app._working_rows(), 1)


if __name__ == "__main__":
    unittest.main()

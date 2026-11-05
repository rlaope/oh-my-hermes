"""A clarify question with choices, drawn the way Claude Code draws AskUserQuestion.

Two rules across the width frame it; the asked sentence is bold and the
context before it dim; a `label — description` choice shows its description
dim under its label; its keys are on its own row under the bottom rule, in
Korean on a question written in Korean. What a pick sends back is Hermes' own
choice string, whatever the row shows.
"""

from __future__ import annotations

import unittest

from _tui_lines import line_text, lines_text
from omh.tui import prompts
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
    def test_korean_question_between_two_rules_with_its_own_korean_key_row(self) -> None:
        drawn = text(KOREAN, waited="14m 42s")
        rule = prompts.FRAME_RULE * 150
        self.assertEqual(drawn[0], rule)
        self.assertEqual(drawn[-2], rule)
        self.assertEqual(drawn[-1], "  Enter 선택 · ↑↓ 이동 · 1-9 바로 선택 · 입력하면 직접 답변 · Esc 취소 · 14m 42s")
        self.assertEqual(drawn[-9:-2], [
            "▌ ",
            "▌ ❯ 1. 지금 머지 (권장)",
            "▌      macOS 결과 없이 머지하고 PR B 시작",
            "▌   2. 재실행",
            "▌      러너가 잡힐 때까지 재실행하고 통과하면 머지",
            "▌   3. 대기",
            "▌   4. 직접 입력",
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
        self.assertEqual(drawn[-1], "  Enter to select · ↑↓ to navigate · 1-9 picks · type to answer · Esc to cancel")

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
        self.assertEqual(drawn[-1], "  Enter 선택 · ↑↓ 이동 · Esc 취소")
        for row in drawn:
            self.assertLessEqual(cell_width(row), 60, row)
        self.assertIn("▌ ❯ 1. 지금 머지 (권장)", drawn)

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
            "▌ ❯ 1. 지금 머지 (권장)",
            "▌      macOS 결과 없이 머지하고 PR B 시작 … ctrl+o shows all",
            "  Enter 선택 · ↑↓ 이동 · 1-9 바로 선택 · 입력하면 직접 답변 · Esc 취소",
        ])
        self.assertEqual(text(KOREAN, width=80, rows=13)[0], prompts.FRAME_RULE * 80)  # the rules once nothing is cut
        self.assertEqual(len(text(KOREAN, rows=2)), 2)
        self.assertEqual(text(KOREAN, rows=1), ["▌ ❯ 1. 지금 머지 (권장) … ctrl+o shows all"])

    def test_the_key_row_follows_the_state(self) -> None:
        clarify = slot(KOREAN)
        clarify.handle_key(Key(CHAR, "x"))  # opens the text field
        self.assertEqual(lines_text(clarify.lines(150, DEFAULT_THEME, 30))[-1], "  Enter 보내기 · ↑↓ 선택지로 · Esc 취소")
        multi = {"questions": [{**ENGLISH["questions"][0], "multi_select": True}]}
        drawn = text(multi)
        self.assertEqual(drawn[-1],
                         "  Space to tick · Enter to send · ↑↓ to navigate · type to answer · Esc to cancel")
        self.assertIn("▌ Merge the alternative anyway? (choose one or more)", drawn)
        closed = {"questions": [{**ENGLISH["questions"][0], prompts.CLOSED_CHOICES: True}]}
        self.assertEqual(text(closed)[-1], "  Enter to select · ↑↓ to navigate · 1-9 picks · Esc to cancel")
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
            ("a — b (Recommended)", False): ("a (Recommended)", "b"),
            ("a — b (Recommended)", True): ("a (권장)", "b"),
            ("a — b — c", False): ("a", "b — c"),
            ("plain", True): ("plain", ""),
            ("blue-green deploy", False): ("blue-green deploy", ""),  # a dash in a word never splits
            ("2024—2026", False): ("2024—2026", ""),  # no spaces around it: not the separator
            (" — only a description", False): ("— only a description", ""),
            ("머지 (Recommended)", True): ("머지 (권장)", ""),
            ("(Recommended) 머지", True): ("(Recommended) 머지", ""),
        }
        for (choice, korean), parts in cases.items():
            with self.subTest(choice=choice, korean=korean):
                self.assertEqual(prompts._choice_parts(choice, korean), parts)


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
        self.assertEqual(footer, "  Enter 선택 · ↑↓ 이동 · 1-9 바로 선택 · 입력하면 직접 답변 · Esc 취소")
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

    def test_the_tool_row_says_the_asked_sentence(self) -> None:
        app, _now = self.open(KOREAN)
        rows = [line_text(row) for row in app._tail(150)]
        call = next(row for row in rows if "clarify" in row)
        self.assertIn("clarify(어떻게 할까요?)", call)
        self.assertNotIn("PR #2565", call)


class KoreanQuestionTests(unittest.TestCase):
    def test_which_questions_read_as_korean(self) -> None:
        cases = {
            "어느 저장소로 생성할까요?": True,
            "GitHub device 승인이 끝났나요?": True,  # as many Korean words as English ones
            "MVP 범위에 넣을 기능을 골라 주세요.": True,
            KOREAN["questions"][0]["question"]: True,
            "Which color do you prefer?": False,
            "OMH degraded (`UnattributableSessionError: no session`) 다시 할까요?": False,
            "": False,
        }
        for question, korean in cases.items():
            with self.subTest(question=question):
                self.assertEqual(prompts._korean_question(question), korean)


class ToolRowTests(unittest.TestCase):
    def test_the_clarify_row_says_the_asked_sentence_not_the_whole_question(self) -> None:
        payload = {"name": "clarify", "args": {"questions": KOREAN["questions"]},
                   "context": KOREAN["questions"][0]["question"][:80]}
        self.assertEqual(_call_summary(payload), "어떻게 할까요?")
        long = {"name": "clarify", "args": {"questions": [{"question": "Why " * 40 + "?"}]}}
        self.assertEqual(cell_width(_call_summary(long)), 60)
        self.assertTrue(_call_summary(long).endswith("…"))
        # A call that carries no question falls back to Hermes' context, then to nothing new.
        self.assertEqual(_call_summary({"name": "clarify", "context": "Ship it? Now."}), "Ship it? Now.")
        self.assertEqual(_call_summary({"name": "terminal", "context": "ls -la"}), "ls -la")


if __name__ == "__main__":
    unittest.main()

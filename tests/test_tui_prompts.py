"""The OMH TUI's prompt slot for server-to-client requests."""

from __future__ import annotations

from dataclasses import replace
import json
import sys
import unittest

from _tui_lines import line_text, lines_text
from omh.tui import prompts
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, LEFT, RIGHT, UP, Key, Paste
from omh.tui.style import Span, fill, is_fill
from omh.tui.theme import DEFAULT_THEME, theme_named
from omh.tui.width import line_width

# Shapes recorded from Hermes 6c61c3e27d (tests/fixtures/tui_gateway).
APPROVAL = {
    "session_id": "f05e2691",
    "command": "rm -rf ./omh-m0-probe-dir",
    "pattern_key": "recursive delete",
    "pattern_keys": ["recursive delete"],
    "description": "recursive delete",
    "allow_permanent": True,
    "allow_session": True,
    "request_id": "421ace443ef640baa09f80731226646e",
    "choices": ["once", "session", "always", "deny"],
}
CLARIFY = {
    "session_id": "b6af062a",
    "questions": [
        {"qid": "q0", "question": "Which color do you prefer?", "choices": ["red (Recommended)", "blue"], "multi_select": False},
    ],
}
CTRL_C = Key(CHAR, "c", ctrl=True)


def bar_styles(rows: list) -> set:
    """The style of each row's first cells, after checking they are the bar (a same-style span may follow it merged)."""
    for row in rows:
        assert row[0].text.startswith(prompts.SLOT_BAR), row
    return {row[0].style for row in rows}


def unbarred(text: str) -> str:
    """A slot row's text without the `▌ ` bar every slot row hangs off."""
    assert text.startswith(prompts.SLOT_BAR), text
    return text[len(prompts.SLOT_BAR) :]


def body(text: list[str]) -> list[str]:
    """A slot's rows behind its bar, without it: a framed clarify question's rules, key row and blank row left out."""
    return [unbarred(row) for row in text if row.startswith(prompts.SLOT_BAR) and unbarred(row).strip()]


def without_marker(text: str) -> str:
    """A slot row's text without the cut marker at its end, if it has one."""
    for form in prompts.MORE_FORMS:
        if text.endswith(form):
            return text[: -len(form)]
    return text


def slot(method: str, params: dict) -> prompts.PromptSlot:
    opened = prompts.open_request("srq-1", method, params)
    assert isinstance(opened, prompts.PromptSlot)
    return opened


class ApprovalTests(unittest.TestCase):
    def test_hermes_always_is_offered_only_when_listed_below_the_session_and_deny_comes_first(self) -> None:
        self.assertEqual(slot("approval", APPROVAL).approval_choices(), ("deny", "once", "session", "always", "tell"))
        cases = (
            (["once", "session", "deny"], ("deny", "once", "session", "tell")),  # allow_permanent false
            (["once", "deny"], ("deny", "once", "tell")),  # smart-denied: one operation only
            ([], ("deny", "once", "session", "tell")),  # no list: never the permanent allow
        )
        for offered, shown in cases:
            with self.subTest(offered=offered):
                self.assertEqual(slot("approval", {**APPROVAL, "choices": offered}).approval_choices(), shown)
        self.assertEqual(slot("approval", {k: v for k, v in APPROVAL.items() if k != "choices"}).approval_choices(),
                         ("deny", "once", "session", "tell"))

    def test_always_says_what_it_allows_and_that_hermes_saves_it(self) -> None:
        self.assertEqual(slot("approval", APPROVAL).approval_label("always"),
                         "always allow recursive delete (Hermes saves it)")
        self.assertEqual(slot("approval", {**APPROVAL, "description": ""}).approval_label("always"),
                         "always allow commands like this (Hermes saves it)")

    def test_always_is_reached_only_by_the_arrows_and_enter(self) -> None:
        approval = slot("approval", APPROVAL)
        for char in "aA4":
            self.assertIsNone(approval.handle_key(Key(CHAR, char)))
        for _ in range(3):
            approval.handle_key(Key(DOWN))
        self.assertEqual(approval.handle_key(Key(ENTER)).frame, {"result": {"choice": "always"}})

    def test_an_approval_is_answered_by_picking(self) -> None:
        approval = slot("approval", APPROVAL)
        self.assertTrue(approval.picking)
        self.assertFalse(approval.wants_text)

    def test_enter_on_an_untouched_approval_denies(self) -> None:
        answer = slot("approval", APPROVAL).handle_key(Key(ENTER))
        self.assertEqual(answer.frame, {"result": {"choice": "deny"}})

    def test_one_step_down_from_deny_reaches_allow_once_never_the_session(self) -> None:
        for key in (DOWN, RIGHT):
            with self.subTest(key=key):
                approval = slot("approval", APPROVAL)
                approval.handle_key(Key(key))
                self.assertEqual(approval.handle_key(Key(ENTER)).frame, {"result": {"choice": "once"}})

    def test_up_then_enter_typed_ahead_still_denies(self) -> None:
        # Up then Enter is the composer's recall-and-resend. Deny is the first row, so Up
        # moves nothing and the Enter answers deny, however many times Up was pressed.
        for presses in (1, 2, 5):
            for key in (UP, LEFT):
                with self.subTest(key=key, presses=presses):
                    approval = slot("approval", APPROVAL)
                    for _ in range(presses):
                        self.assertIsNone(approval.handle_key(Key(key)))
                    self.assertEqual(approval.handle_key(Key(ENTER)).frame, {"result": {"choice": "deny"}})

    def test_the_selection_stops_at_either_end_instead_of_wrapping(self) -> None:
        approval = slot("approval", APPROVAL)
        for _ in range(9):
            approval.handle_key(Key(DOWN))
        self.assertEqual(approval.selected, len(approval.approval_choices()) - 1)  # the tell row, last
        last = approval.handle_key(Key(ENTER))
        self.assertEqual((last.frame, last.tell), ({"result": {"choice": "deny"}}, True))
        approval = slot("approval", APPROVAL)
        approval.handle_key(Key(DOWN))
        for _ in range(3):
            approval.handle_key(Key(UP))
        self.assertEqual(approval.handle_key(Key(ENTER)).frame, {"result": {"choice": "deny"}})

    def test_a_letter_can_only_deny(self) -> None:
        # A key typed for the composer must never allow a command: o, s, y and the rest do nothing.
        for char in ("o", "s", "y", "a", "O", "S", "Y"):
            with self.subTest(char=char):
                self.assertIsNone(slot("approval", APPROVAL).handle_key(Key(CHAR, char)))
        for char in ("d", "n", "D", "N"):
            with self.subTest(char=char):
                self.assertEqual(slot("approval", APPROVAL).handle_key(Key(CHAR, char)).frame, {"result": {"choice": "deny"}})

    def test_a_digit_picks_no_approval_choice_and_moves_nothing(self) -> None:
        # Digits pick clarify choices; on an approval they would be allow shortcuts, so they do nothing.
        for start in (0, 1):
            for char in "0123456789":
                with self.subTest(char=char, start=start):
                    approval = slot("approval", APPROVAL)
                    approval.selected = start
                    self.assertIsNone(approval.handle_key(Key(CHAR, char)))
                    self.assertEqual(approval.selected, start)

    def test_a_paste_answers_nothing(self) -> None:
        approval = slot("approval", APPROVAL)
        self.assertIsNone(approval.handle_key(Paste("y\n")))
        self.assertEqual(approval.handle_key(Key(ENTER)).frame, {"result": {"choice": "deny"}})

    def test_escape_and_ctrl_c_send_an_explicit_deny(self) -> None:
        for key in (Key(ESCAPE), CTRL_C):
            with self.subTest(key=key):
                approval = slot("approval", APPROVAL)
                approval.handle_key(Key(DOWN))
                self.assertEqual(approval.handle_key(key).frame, {"result": {"choice": "deny"}})

    def test_a_session_choice_hermes_did_not_offer_is_not_shown(self) -> None:
        approval = slot("approval", {**APPROVAL, "choices": ["once", "deny"]})
        self.assertEqual(approval.approval_choices(), ("deny", "once", "tell"))
        text = lines_text(approval.lines(60, DEFAULT_THEME, max_rows=6))
        self.assertEqual([unbarred(row) for row in text[-3:]],
                         ["❯ ✗ deny", "  ✓ allow once", "  ✎ no, and tell Hermes what to do instead"])

    def test_submitted_text_does_not_answer_an_approval(self) -> None:
        approval = slot("approval", APPROVAL)
        self.assertIsNone(approval.submit_text("yes"))

    def test_the_choices_stand_one_per_row_deny_first_and_marked(self) -> None:
        approval = slot("approval", {**APPROVAL, "command": "one\ntwo"})
        text = lines_text(approval.lines(60, DEFAULT_THEME, max_rows=8))
        self.assertIn("Hermes asks to run recursive delete", text[0])
        self.assertEqual([unbarred(row) for row in text[1:6]],
                         ["  one", "  two", "❯ ✗ deny", "  ✓ allow once", "  ✓ allow this session"])
        approval.handle_key(Key(DOWN))
        text = lines_text(approval.lines(60, DEFAULT_THEME, max_rows=8))
        self.assertEqual([unbarred(row) for row in text[3:6]], ["  ✗ deny", "❯ ✓ allow once", "  ✓ allow this session"])

    def test_no_number_and_no_key_hint_is_drawn_on_the_choices(self) -> None:
        # Allowing takes the arrows and Enter: nothing on the rows reads as a shortcut. The keys are on the info line.
        text = lines_text(slot("approval", APPROVAL).lines(80, DEFAULT_THEME, max_rows=6))
        for row in text[-3:]:
            with self.subTest(row=row):
                self.assertFalse(any(char.isdigit() for char in row), row)
                self.assertNotIn("enter", row)

    def test_the_keys_say_the_arrows_enter_and_deny(self) -> None:
        keys = slot("approval", APPROVAL).keys
        self.assertEqual(keys[0], "↑↓ pick · enter confirms · d or esc denies and stops")
        self.assertTrue(all("esc denies and stops" in form for form in keys), keys)
        self.assertEqual(keys, tuple(sorted(keys, key=len, reverse=True)))

    def test_with_no_turn_running_the_keys_say_deny_and_nothing_about_stopping(self) -> None:
        approval = slot("approval", APPROVAL)
        idle = approval.keys_while(False)
        self.assertEqual(idle[0], "↑↓ pick · enter confirms · d or esc denies")
        self.assertTrue(all(form.endswith("esc denies") for form in idle), idle)
        self.assertEqual(approval.keys_while(True), approval.keys)
        self.assertEqual(slot("clarify", CLARIFY).keys_while(False), slot("clarify", CLARIFY).keys)

    def test_the_slots_rows_never_say_its_keys(self) -> None:
        # The info line says them (`keys_while`), at every height.
        approval = slot("approval", {**APPROVAL, "command": "one\ntwo", "choices": ["once", "deny"]})
        for width, rows in ((60, 8), (24, 12)):
            with self.subTest(width=width):
                self.assertFalse([row for row in lines_text(approval.lines(width, DEFAULT_THEME, rows)) if "esc" in row])

    def test_lines_show_command_and_choices_within_budget(self) -> None:
        rows = slot("approval", APPROVAL).lines(60, DEFAULT_THEME, max_rows=6)
        text = lines_text(rows)
        self.assertIn("rm -rf ./omh-m0-probe-dir", "\n".join(text))
        self.assertEqual(unbarred(text[2]), "❯ ✗ deny")
        self.assertTrue(all(line_width(row) <= 60 for row in rows))

    def test_a_tight_budget_keeps_the_header_and_the_highlighted_choice(self) -> None:
        approval = slot("approval", {**APPROVAL, "command": "x " * 200})
        text = lines_text(approval.lines(40, DEFAULT_THEME, max_rows=2))
        self.assertEqual(unbarred(text[0]), "⚠ Hermes asks to run recursiv … ctrl+o")
        self.assertEqual(unbarred(text[1]), "❯ ✗ deny")
        approval.handle_key(Key(DOWN))
        approval.handle_key(Key(DOWN))
        # From three rows the command's first row stands between the header and the highlighted choice.
        self.assertEqual([unbarred(row) for row in lines_text(approval.lines(40, DEFAULT_THEME, max_rows=3))[1:]],
                         ["  x x x x x x x x x x x x x x … ctrl+o", "❯ ✓ allow this session"])
        self.assertEqual(lines_text(approval.lines(40, DEFAULT_THEME, max_rows=1)), ["▌ ❯ ✓ allow this session … ctrl+o"])

    def test_a_long_command_shows_its_head_then_how_much_was_cut(self) -> None:
        # The shape a live run cut wrong: a multi-line `python3 -c` script, tail shown, head lost.
        command = 'python3 -c "\ndef is_prime(n):\n    if n < 2:\n        return False\n' + "    pass\n" * 8 + '"'
        approval = slot("approval", {**APPROVAL, "command": command, "description": "script execution via -e/-c flag",
                                     "choices": ["once", "session", "deny"]})  # each choice one row at this width
        rows = approval.lines(60, DEFAULT_THEME, max_rows=5 + len(approval.approval_choices()))
        text = lines_text(rows)
        total = command.count("\n") + 1
        self.assertEqual(len(rows), 5 + len(approval.approval_choices()))
        self.assertIn("script execution", text[0])
        self.assertEqual([unbarred(row) for row in text[1:4]], ['  python3 -c "', "  def is_prime(n):", "      if n < 2:"])
        self.assertEqual(unbarred(text[4]), f"  … +{total - 3} more lines · ctrl+o shows all")
        self.assertEqual(rows[4][1].style, DEFAULT_THEME.muted)
        self.assertEqual(unbarred(text[5]), "❯ ✗ deny")

    def test_one_spare_row_shows_the_commands_first_row_and_the_marker_after_it(self) -> None:
        approval = slot("approval", {**APPROVAL, "command": "first line\nsecond line\nthird line"})
        text = lines_text(approval.lines(60, DEFAULT_THEME, max_rows=5))
        self.assertEqual(unbarred(text[1]), "  first line … ctrl+o shows all")
        self.assertEqual(unbarred(text[2]), "❯ ✗ deny")

    def test_a_command_that_fits_is_shown_whole_with_no_marker(self) -> None:
        approval = slot("approval", {**APPROVAL, "command": "one\ntwo"})
        text = lines_text(approval.lines(60, DEFAULT_THEME, max_rows=8))
        self.assertEqual([unbarred(row) for row in text[1:3]], ["  one", "  two"])
        self.assertEqual(len(text), 3 + len(approval.approval_choices()))
        self.assertFalse(any("more line" in row for row in text))

    def test_the_highlighted_choice_stays_visible_at_every_width_and_budget(self) -> None:
        for selected in range(3):
            approval = slot("approval", APPROVAL)
            approval.selected = selected
            label = ("deny", "allow once", "allow this session")[selected]
            for width in range(18, 120, 7):
                for max_rows in range(1, 9):
                    with self.subTest(selected=selected, width=width, max_rows=max_rows):
                        rows = approval.lines(width, DEFAULT_THEME, max_rows=max_rows)
                        self.assertLessEqual(len(rows), max_rows)
                        self.assertTrue(all(line_width(row) <= width for row in rows))
                        marked = [unbarred(line_text(row)) for row in rows if unbarred(line_text(row)).startswith("❯")]
                        self.assertEqual(len(marked), 1, marked)
                        shown = without_marker(marked[0])[4:].rstrip("…")  # past the mark and the icon
                        self.assertTrue(shown and label.startswith(shown), marked)

    def test_every_row_hangs_off_a_warn_bar_and_the_command_reads_as_code(self) -> None:
        approval = slot("approval", {**APPROVAL, "command": "one\ntwo"})
        rows = approval.lines(60, DEFAULT_THEME, max_rows=8)
        self.assertEqual(bar_styles(rows), {DEFAULT_THEME.warn})
        self.assertEqual([row[1].style for row in rows[1:3]], [DEFAULT_THEME.code, DEFAULT_THEME.code])

    def test_each_choice_reads_in_its_tone_and_the_highlighted_one_is_bold_in_it(self) -> None:
        # The owner's screenshot of 2026-10-28: plain-text choices read like the command rows above them.
        approval = slot("approval", APPROVAL)
        approval.handle_key(Key(DOWN))
        rows = approval.lines(80, DEFAULT_THEME, max_rows=7)[2:7]  # under the header and the command's row
        styles = {span.text.strip(" ▌❯✗✓★✎"): span.style for row in rows for span in row if span.text.strip(" ▌❯✗✓★✎")}
        self.assertEqual(styles, {
            "deny": DEFAULT_THEME.error, "allow once": DEFAULT_THEME.pick_ok, "allow this session": DEFAULT_THEME.ok,
            "always allow recursive delete (Hermes saves it)": DEFAULT_THEME.warn,
            "no, and tell Hermes what to do instead": DEFAULT_THEME.muted,
        })
        self.assertEqual(rows[1][0], Span("▌ ", DEFAULT_THEME.warn))  # the bar keeps its colour
        self.assertEqual(rows[1][1], Span("❯ ✓ allow once", DEFAULT_THEME.pick_ok))  # the mark and icon in its tone too
        self.assertTrue(DEFAULT_THEME.pick_ok.bold)

    def test_the_highlighted_choice_runs_on_its_tone_s_band_to_the_right_edge(self) -> None:
        theme = theme_named("sky", "#1E2030")  # a reported background: the bands are painted
        for downs, tone in ((0, "pick_error"), (1, "pick_ok"), (2, "pick_ok"), (3, "pick_warn"), (4, "pick_muted")):
            with self.subTest(tone=tone):
                approval = slot("approval", APPROVAL)
                for _ in range(downs):
                    approval.handle_key(Key(DOWN))
                current = next(row for row in approval.lines(80, theme, max_rows=20) if "❯" in line_text(row))
                band = getattr(theme, tone)
                self.assertIsNotNone(band.bg)
                self.assertEqual(current[-1], fill(band))  # `screen.paint_line` runs it to the edge
                self.assertEqual({span.style for span in current[1:]}, {band})
        unbanded = slot("approval", APPROVAL).lines(80, DEFAULT_THEME, max_rows=20)  # no background reported: no band
        self.assertFalse([row for row in unbanded if is_fill(row[-1])])


LONG_COMMAND = "\n".join(f"echo line {n}" for n in range(1, 21))
# Each shape is cut somewhere at a small enough budget: a command, a header, a list, a question, a value prompt's text.
CUT_SHAPES = (
    ("approval", {**APPROVAL, "command": LONG_COMMAND}),
    ("approval", {**APPROVAL, "description": "a description that runs on long enough to wrap " * 2}),
    ("clarify", {"questions": [{"qid": "q", "question": "Pick one", "choices": [f"choice {n}" for n in range(1, 9)]}]}),
    ("clarify", {"questions": [{"qid": "q", "question": "Why " * 40}]}),
    ("sudo", {"command": "apt install " + "pkg " * 40}),
    ("secret", {"env_var": "A_VERY_LONG_ENVIRONMENT_VARIABLE_NAME_FOR_THE_TOKEN"}),
)


class CutMarkerTests(unittest.TestCase):
    def test_every_cut_names_ctrl_o_at_every_height_and_width_and_nothing_else_does(self) -> None:
        for method, params in CUT_SHAPES:
            question = slot(method, params)
            for width in (19, 24, 30, 40, 60, 80, 120):
                # Every row the slot has room for, against the rows it shows: an approval's spacing (blank rows and
                # the rule over its choices) is the first to give way, and dropping it cuts nothing. (Ctrl+O's view
                # draws an approval's command whole instead of by command, so it is not the measure here.)
                whole = [row for row in question.lines(width, DEFAULT_THEME, sys.maxsize)
                         if line_text(row).removeprefix(prompts.SLOT_BAR).strip(" ─")]
                for max_rows in range(1, len(whole) + 2):
                    with self.subTest(method=method, width=width, max_rows=max_rows):
                        rows = question.lines(width, DEFAULT_THEME, max_rows)
                        text = lines_text(rows)
                        self.assertLessEqual(len(rows), max_rows)
                        self.assertTrue(all(line_width(row) <= width for row in rows))
                        self.assertEqual(any("ctrl+o" in row for row in text), len(whole) > max_rows, text)

    def test_a_six_row_terminal_shows_the_commands_first_row_with_the_marker(self) -> None:
        # Four slot rows: the header, the command's head, and the choices scrolled to keep deny.
        text = lines_text(slot("approval", {**APPROVAL, "command": LONG_COMMAND}).lines(80, DEFAULT_THEME, 4))
        self.assertEqual(
            [unbarred(row) for row in text],
            ["⚠ Hermes asks to run recursive delete · 20 commands", "  echo line 1 … ctrl+o shows all", "❯ ✗ deny",
             "  ✓ allow once"],
        )

    def test_the_markers_keep_the_keys_name_on_a_narrow_slot(self) -> None:
        text = [unbarred(row) for row in lines_text(slot("approval", {**APPROVAL, "command": LONG_COMMAND}).lines(24, DEFAULT_THEME, 10))]
        # The header wraps to three rows here (`· 20 commands`), which leaves the command two rows and its count
        # marker one: the first command's row still comes before the marker.
        self.assertEqual(text[3:6], ["  echo line 1", "  echo line 2", "  … +18 · ctrl+o"], text)
        self.assertEqual([row for row in text if "ctrl+o" in row], ["  … +18 · ctrl+o", "  … more · ctrl+o"], text)
        self.assertEqual(text[-1], "  … more · ctrl+o")  # the tell row is cut below the list, and says so

    def test_the_header_wraps_instead_of_being_cut(self) -> None:
        approval = slot("approval", {**APPROVAL, "description": "recursive delete of the whole build tree"})
        text = [unbarred(row) for row in lines_text(approval.lines(30, DEFAULT_THEME, 16))]
        header = text[: text.index("  ✦ OMH also sees: recursive")]
        self.assertEqual(header, ["⚠ Hermes asks to run", "  recursive delete of the", "  whole build tree"])
        self.assertFalse([row for row in text if row.endswith("…") or "ctrl+o" in row], text)

    def test_a_value_prompts_label_wraps_too(self) -> None:
        secret = slot("secret", {"env_var": "A_LONG_TOKEN_NAME_FOR_THE_API"})
        text = [unbarred(row) for row in lines_text(secret.lines(30, DEFAULT_THEME, 6))]
        label = text[:-1]  # the hint is the last row
        self.assertEqual(label[0], "🔑 Hermes needs")
        self.assertEqual("".join(row.strip() for row in label[1:]), "A_LONG_TOKEN_NAME_FOR_THE_API")
        self.assertTrue(all(row.startswith("   ") for row in label[1:]), label)

    def test_the_whole_question_has_every_row_and_no_marker(self) -> None:
        approval = slot("approval", {**APPROVAL, "command": LONG_COMMAND})
        approval.handle_key(Key(DOWN))
        text = [unbarred(row) for row in lines_text(approval.whole_lines(60, DEFAULT_THEME))]
        self.assertEqual(text[0], "⚠ Hermes asks to run recursive delete · 20 commands")
        self.assertEqual(text[1:23], ["", *(f"  echo line {n}" for n in range(1, 21)), ""])
        labels = [approval.approval_label(choice) for choice in approval.approval_choices()]
        icons = [prompts.APPROVAL_TONES[choice][0] for choice in approval.approval_choices()]
        self.assertEqual(text[23:25], ["  " + "─" * (60 - len(prompts.SLOT_BAR) - 4), ""])
        self.assertEqual(text[25:], [("❯ " if index == 1 else "  ") + f"{icon} {label}"
                                     for index, (icon, label) in enumerate(zip(icons, labels))])
        self.assertEqual(labels[:3], ["deny", "allow once", "allow this session"])  # no keys: the pager has its own
        self.assertFalse([row for row in text if "ctrl+o" in row])


class WaitingCountTests(unittest.TestCase):
    def test_each_question_counts_what_waits_behind_it_after_its_first_words(self) -> None:
        cases = (
            ("approval", APPROVAL, "⚠ Hermes asks to run recursive delete"),
            ("clarify", CLARIFY, "Which color do you prefer?"),
            ("sudo", {"command": "apt install x"}, "🔑 Hermes needs your sudo password"),
        )
        for method, params, head in cases:
            with self.subTest(method=method):
                question = slot(method, params)
                self.assertEqual(body(lines_text(question.lines(120, DEFAULT_THEME, 8)))[0], head)
                self.assertEqual(body(lines_text(question.lines(120, DEFAULT_THEME, 8, waiting=1)))[0],
                                 f"{head} · 1 more question waiting")
                self.assertEqual(body(lines_text(question.lines(120, DEFAULT_THEME, 8, waiting=3)))[0],
                                 f"{head} · 3 more questions waiting")


class ApprovalLayoutTests(unittest.TestCase):
    """The approval's rows after the always and tell rows joined them (owner decisions 8 and 9)."""

    LABELS = ["deny", "allow once", "allow this session", "always allow recursive delete (Hermes saves it)",
              "no, and tell Hermes what to do instead"]

    def test_the_rows_go_deny_once_session_always_then_tell(self) -> None:
        text = [unbarred(row) for row in lines_text(slot("approval", APPROVAL).lines(80, DEFAULT_THEME, 12))]
        icons = "✗✓✓★✎"
        self.assertEqual(text[-5:], ["❯ ✗ " + self.LABELS[0], *(f"  {icon} {label}" for icon, label in zip(icons[1:], self.LABELS[1:]))])
        without = [unbarred(row) for row in lines_text(
            slot("approval", {**APPROVAL, "choices": ["once", "session", "deny"]}).lines(80, DEFAULT_THEME, 12))]
        self.assertEqual(without[-4:], ["❯ ✗ deny", "  ✓ allow once", "  ✓ allow this session", "  ✎ " + self.LABELS[-1]])

    def test_deny_stays_first_and_highlighted(self) -> None:
        for offered in (APPROVAL["choices"], ["once", "session", "deny"], ["once", "deny"], []):
            with self.subTest(offered=offered):
                approval = slot("approval", {**APPROVAL, "choices": offered})
                self.assertEqual((approval.selected, approval.approval_choices()[0]), (0, "deny"))
                self.assertEqual(approval.handle_key(Key(ENTER)).frame, {"result": {"choice": "deny"}})

    def test_the_arrows_stop_at_both_ends_so_up_then_enter_still_denies(self) -> None:
        approval = slot("approval", APPROVAL)
        for _ in range(12):
            approval.handle_key(Key(DOWN))
        self.assertEqual(approval.selected, 4)
        for _ in range(12):
            approval.handle_key(Key(UP))
        self.assertEqual(approval.selected, 0)
        self.assertEqual(approval.handle_key(Key(ENTER)).frame, {"result": {"choice": "deny"}})

    def test_no_digit_and_no_letter_but_d_or_n_picks_a_row_wherever_the_highlight_is(self) -> None:
        for start in range(5):
            for char in "0123456789atTyYs":
                with self.subTest(start=start, char=char):
                    approval = slot("approval", APPROVAL)
                    approval.selected = start
                    self.assertIsNone(approval.handle_key(Key(CHAR, char)))
                    self.assertEqual(approval.selected, start)

    def test_esc_d_and_ctrl_c_deny_and_stop_from_any_row_and_never_open_the_tell_composer(self) -> None:
        for start in range(5):
            for key in (Key(ESCAPE), Key(CHAR, "d"), Key(CHAR, "n"), CTRL_C):
                with self.subTest(start=start, key=key):
                    approval = slot("approval", APPROVAL)
                    approval.selected = start
                    answer = approval.handle_key(key)
                    self.assertEqual((answer.frame, answer.tell, answer.stops), ({"result": {"choice": "deny"}}, False, True))

    def test_enter_on_deny_stops_too_and_only_a_deny_the_person_gave_does(self) -> None:
        approval = slot("approval", APPROVAL)
        self.assertTrue(approval.handle_key(Key(ENTER)).stops)
        approval = slot("approval", APPROVAL)
        approval.handle_key(Key(UP))
        self.assertTrue(approval.handle_key(Key(ENTER)).stops)  # Up then Enter typed ahead: denies, and stops
        for downs in (1, 2, 3, 4):  # allow once, this session, always, and the tell row: none stops
            with self.subTest(downs=downs):
                approval = slot("approval", APPROVAL)
                for _ in range(downs):
                    approval.handle_key(Key(DOWN))
                self.assertFalse(approval.handle_key(Key(ENTER)).stops)
        self.assertFalse(slot("approval", APPROVAL).decline().stops)  # the TUI's own decline (a session left)
        self.assertFalse(slot("clarify", CLARIFY).handle_key(Key(ESCAPE)).stops)
        self.assertFalse(slot("sudo", {}).handle_key(Key(ESCAPE)).stops)

    def test_the_tell_row_denies_and_asks_for_the_composer(self) -> None:
        approval = slot("approval", APPROVAL)
        for _ in range(4):
            approval.handle_key(Key(DOWN))
        answer = approval.handle_key(Key(ENTER))
        self.assertEqual(answer, prompts.Answer("srq-1", {"result": {"choice": "deny"}}, tell=True))


class SlotBarTests(unittest.TestCase):
    def test_a_question_or_a_value_prompt_hangs_off_an_accent_bar(self) -> None:
        for method, params in (("clarify", CLARIFY), ("sudo", {"session_id": "s"}), ("secret", {"env_var": "API_KEY"})):
            with self.subTest(method=method):
                rows = slot(method, params).lines(60, DEFAULT_THEME, max_rows=6)
                # A framed clarify question's rules and key row hang off nothing; its question and choices do.
                rows = [row for row in rows if line_text(row).startswith(prompts.SLOT_BAR)]
                self.assertTrue(rows)
                # A question is no state: grey. A framed clarify's bar is a gutter, which a drag never copies.
                framed = method == "clarify"
                self.assertEqual(bar_styles(rows), {replace(DEFAULT_THEME.muted, gutter=framed, joins=framed)})
                self.assertTrue(all(line_width(row) <= 60 for row in rows))


class ClarifyTests(unittest.TestCase):
    def test_a_number_picks_that_choice(self) -> None:
        answer = slot("clarify", CLARIFY).handle_key(Key(CHAR, "2"))
        self.assertEqual(answer.frame, {"result": {"answers": {"q0": "blue"}}})

    def test_a_question_with_choices_is_picked_and_one_without_is_typed(self) -> None:
        self.assertTrue(slot("clarify", CLARIFY).picking)
        self.assertFalse(slot("clarify", {"questions": [{"qid": "q", "question": "Why?"}]}).picking)

    def test_the_choices_stand_one_per_row_numbered_with_the_text_field_last(self) -> None:
        text = lines_text(slot("clarify", CLARIFY).lines(80, DEFAULT_THEME, 10))
        self.assertEqual(
            body(text),
            ["Which color do you prefer?", "❯ 1. red (Recommended)", "  2. blue", "  3. Type something."],
        )

    def test_arrows_move_and_stop_at_either_end_and_enter_picks_the_highlighted(self) -> None:
        clarify = slot("clarify", CLARIFY)
        clarify.handle_key(Key(UP))
        self.assertEqual(clarify.selected, 0)
        clarify.handle_key(Key(DOWN))
        self.assertEqual(clarify.handle_key(Key(ENTER)).frame, {"result": {"answers": {"q0": "blue"}}})
        clarify = slot("clarify", CLARIFY)
        for _ in range(6):
            clarify.handle_key(Key(DOWN))
        self.assertEqual(clarify.selected, 2)  # the text field's row, and no further

    def test_enter_or_the_number_on_the_text_fields_row_opens_the_field_with_nothing_typed(self) -> None:
        for keys in ([Key(DOWN), Key(DOWN), Key(ENTER)], [Key(CHAR, "3")]):
            with self.subTest(keys=keys):
                clarify = slot("clarify", CLARIFY)
                for key in keys:
                    self.assertIsNone(clarify.handle_key(key))
                self.assertTrue(clarify.typing)
                self.assertFalse(clarify.picking)
                self.assertEqual(clarify.selected, 2)
                self.assertEqual(clarify.keys[0], "type your answer · enter sends · ↑↓ back to the choices · esc cancels")

    def test_a_character_that_picks_nothing_opens_the_field_and_is_typed_there(self) -> None:
        for key in (Key(CHAR, "g"), Key(CHAR, "0"), Key(CHAR, "4"), Key(CHAR, "²"), Key(CHAR, "한"), Paste("green")):
            with self.subTest(key=key):
                clarify = slot("clarify", CLARIFY)
                self.assertEqual(clarify.handle_key(key), prompts.TypeIt(key))
                self.assertTrue(clarify.typing)

    def test_keys_that_type_nothing_do_not_open_the_field(self) -> None:
        for key in (Key(LEFT), Key(RIGHT), Key(CHAR, "g", ctrl=True), Key(CHAR, "g", alt=True)):
            with self.subTest(key=key):
                clarify = slot("clarify", CLARIFY)
                self.assertIsNone(clarify.handle_key(key))
                self.assertTrue(clarify.picking)

    def test_with_the_field_open_the_arrows_go_back_to_the_list(self) -> None:
        clarify = slot("clarify", CLARIFY)
        clarify.handle_key(Key(CHAR, "g"))
        self.assertIsNone(clarify.handle_key(Key(UP)))
        self.assertTrue(clarify.picking)
        self.assertEqual(clarify.selected, 1)
        clarify.handle_key(Key(CHAR, "3"))
        self.assertIsNone(clarify.handle_key(Key(DOWN)))
        self.assertEqual((clarify.picking, clarify.selected), (True, 2))

    def test_with_the_field_open_a_digit_or_a_paste_is_the_fields(self) -> None:
        clarify = slot("clarify", CLARIFY)
        clarify.handle_key(Key(CHAR, "3"))
        self.assertIsNone(clarify.handle_key(Key(CHAR, "1")))
        self.assertIsNone(clarify.handle_key(Paste("blue")))
        self.assertTrue(clarify.typing)
        self.assertEqual(clarify.answers, {})

    def test_typed_text_answers_freely(self) -> None:
        clarify = slot("clarify", CLARIFY)
        clarify.handle_key(Key(CHAR, "g"))
        self.assertEqual(clarify.submit_text(" green ").frame, {"result": {"answers": {"q0": "green"}}})

    def test_an_empty_answer_from_the_field_goes_back_to_the_list(self) -> None:
        clarify = slot("clarify", CLARIFY)
        clarify.handle_key(Key(CHAR, "3"))
        self.assertIsNone(clarify.submit_text("  "))
        self.assertTrue(clarify.picking)
        self.assertEqual(clarify.answers, {})

    def test_empty_submit_from_the_list_picks_the_highlighted_choice(self) -> None:
        clarify = slot("clarify", CLARIFY)
        clarify.handle_key(Key(DOWN))
        self.assertEqual(clarify.submit_text("").frame, {"result": {"answers": {"q0": "blue"}}})

    def test_multiple_questions_answer_once_at_the_end(self) -> None:
        params = {"questions": [{"qid": "a", "question": "A?"}, {"qid": "b", "question": "B?", "choices": ["x", "y"]}]}
        clarify = slot("clarify", params)
        self.assertFalse(clarify.picking)
        self.assertIsNone(clarify.submit_text("first"))
        self.assertTrue(clarify.picking)
        self.assertEqual(clarify.handle_key(Key(CHAR, "1")).frame, {"result": {"answers": {"a": "first", "b": "x"}}})

    def test_the_next_question_opens_on_its_list(self) -> None:
        params = {"questions": [{"qid": "a", "question": "A?", "choices": ["p", "q"]}, {"qid": "b", "question": "B?", "choices": ["x", "y"]}]}
        clarify = slot("clarify", params)
        clarify.handle_key(Key(CHAR, "g"))
        self.assertIsNone(clarify.submit_text("green"))
        self.assertEqual((clarify.picking, clarify.selected), (True, 0))
        self.assertEqual(body(lines_text(clarify.lines(80, DEFAULT_THEME, 10)))[0], "B? (2/2)")

    def test_escape_cancels_with_no_answers_from_the_list_and_from_the_field(self) -> None:
        self.assertEqual(slot("clarify", CLARIFY).handle_key(Key(ESCAPE)).frame, {"result": {}})
        clarify = slot("clarify", CLARIFY)
        clarify.handle_key(Key(CHAR, "g"))
        self.assertEqual(clarify.handle_key(Key(ESCAPE)).frame, {"result": {}})

    def test_the_keys_say_esc_cancels_because_it_cancels_every_question(self) -> None:
        clarify = slot("clarify", CLARIFY)
        self.assertEqual(clarify.keys[0], "↑↓ or 1-9 · enter picks · type to answer · esc cancels")
        clarify.handle_key(Key(CHAR, "g"))
        for form in (*slot("clarify", CLARIFY).keys, *clarify.keys):
            with self.subTest(form=form):
                self.assertIn("esc cancels", form)
                self.assertNotIn("skips", form)

    def test_a_clarify_with_no_question_is_declined_at_once_with_a_notice(self) -> None:
        for params in ({}, {"questions": []}, {"questions": [{"question": "no qid"}, "not a dict"]}):
            with self.subTest(params=params):
                opened = prompts.open_request("srq-2", "clarify", params)
                self.assertIsInstance(opened, prompts.ImmediateAnswer)
                self.assertEqual(opened.answer.frame, {"result": {}})
                self.assertIn("clarify", opened.notice)

    def test_only_the_digits_one_to_nine_pick_a_choice(self) -> None:
        for char in ("²", "٣", "0", "١"):
            with self.subTest(char=char):
                self.assertNotIsInstance(slot("clarify", CLARIFY).handle_key(Key(CHAR, char)), prompts.Answer)
        self.assertEqual(slot("clarify", CLARIFY).handle_key(Key(CHAR, "1")).frame, {"result": {"answers": {"q0": "red (Recommended)"}}})

    def test_a_list_too_long_for_its_rows_scrolls_to_keep_the_highlighted_one(self) -> None:
        params = {"questions": [{"qid": "q", "question": "Pick one", "choices": [f"choice {n}" for n in range(1, 9)]}]}
        clarify = slot("clarify", params)
        for _ in range(6):
            clarify.handle_key(Key(DOWN))
        text = body(lines_text(clarify.lines(60, DEFAULT_THEME, 5)))  # four rows and the key row
        # The question is whole, so the cut is marked beside the choices, counting what it left out.
        self.assertEqual(text, ["Pick one", "  6. choice 6", "❯ 7. choice 7", "  … +7 more choices · ctrl+o shows all"])
        self.assertEqual(lines_text(clarify.lines(60, DEFAULT_THEME, 1)), ["▌ ❯ 7. choice 7 … ctrl+o shows all"])

    def test_a_question_without_choices_keeps_its_typed_answer_hint(self) -> None:
        text = lines_text(slot("clarify", {"questions": [{"qid": "q", "question": "Why?"}]}).lines(60, DEFAULT_THEME, 6))
        self.assertEqual([unbarred(row) for row in text], ["? Why?", "  type an answer and press enter · esc cancels"])


LONG_CHOICES = {
    "questions": [{
        "qid": "q0",
        "question": "Which rollout?",
        "choices": [
            "Blue/green with a full traffic switch after smoke tests pass on the green fleet (Recommended)",
            "Canary at 5% then 25% then 100% with automatic rollback on error budget burn",
            "Rolling update, one node at a time",
        ],
    }],
}


class WrappedChoiceTests(unittest.TestCase):
    def test_a_long_choice_wraps_under_its_number_and_keeps_its_recommended_tag(self) -> None:
        text = body(lines_text(slot("clarify", LONG_CHOICES).lines(80, DEFAULT_THEME, 12)))
        self.assertEqual(text, [
            "Which rollout?",
            "❯ 1. Blue/green with a full traffic switch after smoke tests pass on the green",
            "     fleet (Recommended)",
            "  2. Canary at 5% then 25% then 100% with automatic rollback on error budget",
            "     burn",
            "  3. Rolling update, one node at a time",
            "  4. Type something.",
        ])

    def test_rows_are_counted_not_choices(self) -> None:
        # Seven rows and the key row hold every choice whole; one fewer cuts one and says so, keeping the
        # highlighted one whole.
        clarify = slot("clarify", LONG_CHOICES)
        self.assertFalse([row for row in lines_text(clarify.lines(80, DEFAULT_THEME, 8)) if "ctrl+o" in row])
        for selected, label in ((0, "fleet (Recommended)"), (1, "burn")):
            with self.subTest(selected=selected):
                clarify.selected = selected
                rows = lines_text(clarify.lines(80, DEFAULT_THEME, 7))
                self.assertLessEqual(len(rows), 7)
                text = body(rows)
                self.assertTrue([row for row in text if "ctrl+o" in row], text)
                marked = text.index(next(row for row in text if row.startswith("❯")))
                self.assertEqual(text[marked + 1].strip(), label)  # its second row too

    def test_a_highlighted_choice_taller_than_the_room_shows_its_first_rows_with_the_marker(self) -> None:
        clarify = slot("clarify", LONG_CHOICES)
        text = body(lines_text(clarify.lines(30, DEFAULT_THEME, 4)))  # three rows and the key row
        self.assertEqual(text[:2], ["Which rollout?", "❯ 1. Blue/green with a full"])  # the question is whole
        self.assertTrue(text[2].startswith("     traffic") and text[2].endswith(" … ctrl+o"), text)

    def test_an_approval_choice_wraps_at_a_narrow_width_instead_of_being_cut(self) -> None:
        approval = slot("approval", {**APPROVAL, "command": "ls"})
        approval.selected = 2
        text = [unbarred(row) for row in lines_text(approval.lines(16, DEFAULT_THEME, 12))]
        self.assertEqual(text[-3:], ["❯ ✓ allow this", "    session", "  … ctrl+o"])  # always and tell are cut below


# Hermes 6c61c3e27d's wire shape for a multi-select question (`server._clarify_block`).
MULTI = {
    "questions": [
        {"qid": "q0", "question": "Which toppings?", "choices": ["cheese (Recommended)", "ham", "olives"], "multi_select": True},
    ],
}
SPACE = Key(CHAR, " ")


def submitted(clarify: prompts.PromptSlot) -> prompts.Answer | None:
    """Down to the multi-select question's Submit row (the list stops there), then Enter."""
    for _ in range(len(clarify._current_choices()) + 2):
        clarify.handle_key(Key(DOWN))
    return clarify.handle_key(Key(ENTER))  # type: ignore[return-value]


def hermes_reads(value: str) -> list[str]:
    """What Hermes' `clarify_tool._clean_answer` makes of a multi-select answer string: a JSON list, else one answer."""
    parsed = json.loads(value)
    assert isinstance(parsed, list), value
    return parsed


class MultiSelectTests(unittest.TestCase):
    def test_a_multi_select_question_says_so_and_boxes_each_choice(self) -> None:
        text = body(lines_text(slot("clarify", MULTI).lines(80, DEFAULT_THEME, 12)))
        self.assertEqual(text, [
            "Which toppings? (choose one or more)",
            "❯ [ ] 1. cheese (Recommended)",
            "  [ ] 2. ham",
            "  [ ] 3. olives",
            "      4. Type something.",
            "      Submit",
        ])
        self.assertIn("space", slot("clarify", MULTI).keys[0])

    def test_space_ticks_and_unticks_and_enter_sends_the_ticked_as_inks_json_list(self) -> None:
        clarify = slot("clarify", MULTI)
        clarify.handle_key(Key(DOWN))
        self.assertIsNone(clarify.handle_key(SPACE))
        clarify.handle_key(Key(UP))
        self.assertIsNone(clarify.handle_key(SPACE))
        self.assertEqual(body(lines_text(clarify.lines(80, DEFAULT_THEME, 12)))[1:3],
                         ["❯ [x] 1. cheese (Recommended)", "  [x] 2. ham"])
        clarify.handle_key(Key(DOWN))
        clarify.handle_key(Key(DOWN))
        clarify.handle_key(SPACE)
        clarify.handle_key(SPACE)  # olives on, then off again
        answer = submitted(clarify)
        value = answer.frame["result"]["answers"]["q0"]
        self.assertEqual(value, '["ham","cheese (Recommended)"]')  # in the order ticked, no spaces, as JSON.stringify
        self.assertEqual(hermes_reads(value), ["ham", "cheese (Recommended)"])

    def test_a_digit_ticks_its_choice(self) -> None:
        clarify = slot("clarify", MULTI)
        self.assertIsNone(clarify.handle_key(Key(CHAR, "3")))
        self.assertIsNone(clarify.handle_key(Key(CHAR, "1")))
        self.assertEqual(clarify.handle_key(Key(CHAR, "5")), prompts.TypeIt(Key(CHAR, "5")))  # Submit has no digit
        self.assertEqual(submitted(clarify).frame, {"result": {"answers": {"q0": '["olives","cheese (Recommended)"]'}}})

    def test_enter_on_a_choice_ticks_it_and_never_sends(self) -> None:
        # The owner's report of 2026-11-06: one press on a tick-box question sent it. Enter, Space, a digit and an
        # empty submit each tick or untick; only the Submit row sends.
        clarify = slot("clarify", MULTI)
        clarify.handle_key(Key(DOWN))
        self.assertIsNone(clarify.handle_key(Key(ENTER)))
        self.assertIsNone(clarify.submit_text(""))  # the empty composer submit is Enter on the highlighted row
        self.assertIsNone(clarify.handle_key(Key(ENTER)))
        self.assertEqual(clarify.ticked, ["ham"])
        self.assertEqual(clarify.question_index, 0)
        self.assertIn("❯ [x] 2. ham", body(lines_text(clarify.lines(80, DEFAULT_THEME, 12))))
        self.assertEqual(submitted(clarify).frame, {"result": {"answers": {"q0": '["ham"]'}}})

    def test_the_submit_row_sends_and_with_nothing_ticked_reads_skipped(self) -> None:
        clarify = slot("clarify", MULTI)
        for _ in range(4):
            clarify.handle_key(Key(DOWN))
        self.assertIsNone(clarify.handle_key(SPACE))  # Space never sends
        self.assertEqual(clarify.selected, 4)
        self.assertEqual(lines_text(clarify.lines(80, DEFAULT_THEME, 12))[-1],
                         "  Enter to send · ↑↓ to navigate · Esc to cancel")
        clarify.handle_key(Key(DOWN))  # the list stops at Submit
        frame = clarify.handle_key(Key(ENTER)).frame
        self.assertEqual(frame, {"result": {"answers": {"q0": ""}}})
        self.assertEqual(clarify.outcomes(frame), [(False, "skipped · Which toppings?")])

    def test_the_typed_answer_joins_the_ticked_choices(self) -> None:
        clarify = slot("clarify", MULTI)
        clarify.handle_key(Key(CHAR, "2"))
        for _ in range(3):
            clarify.handle_key(Key(DOWN))
        self.assertIsNone(clarify.handle_key(SPACE))  # the field's row has no box: Space does nothing there
        self.assertFalse(clarify.typing)
        self.assertIsNone(clarify.handle_key(Key(ENTER)))
        self.assertTrue(clarify.typing)
        value = clarify.submit_text(" pineapple ").frame["result"]["answers"]["q0"]
        self.assertEqual(hermes_reads(value), ["ham", "pineapple"])

    def test_a_letter_still_opens_the_field_and_its_answer_is_a_list(self) -> None:
        clarify = slot("clarify", MULTI)
        self.assertEqual(clarify.handle_key(Key(CHAR, "p")), prompts.TypeIt(Key(CHAR, "p")))
        self.assertEqual(clarify.submit_text("pineapple").frame, {"result": {"answers": {"q0": '["pineapple"]'}}})

    def test_labels_past_ascii_go_as_they_are_like_json_stringify(self) -> None:
        clarify = slot("clarify", {"questions": [{**MULTI["questions"][0], "choices": ["치즈", "ham"]}]})
        clarify.handle_key(SPACE)
        self.assertEqual(submitted(clarify).frame, {"result": {"answers": {"q0": '["치즈"]'}}})

    def test_the_ticks_belong_to_their_question(self) -> None:
        second = {"qid": "q1", "question": "Which sauces?", "choices": ["red", "white"], "multi_select": True}
        clarify = slot("clarify", {"questions": [MULTI["questions"][0], second]})
        clarify.handle_key(SPACE)
        self.assertIsNone(clarify.handle_key(Key(ENTER)))  # Enter unticks: question 1 stays open
        self.assertEqual((clarify.question_index, clarify.ticked), (0, []))
        clarify.handle_key(Key(ENTER))
        self.assertEqual(body(lines_text(clarify.lines(80, DEFAULT_THEME, 12)))[-1], "      Next")  # more follow
        self.assertIsNone(submitted(clarify))  # Next moves on to question 2
        self.assertEqual(clarify.ticked, [])
        drawn = body(lines_text(clarify.lines(80, DEFAULT_THEME, 12)))
        self.assertIn("❯ [ ] 1. red", drawn)
        self.assertEqual(drawn[-1], "      Submit")
        answer = clarify.handle_key(Key(CHAR, "2"))
        self.assertIsNone(answer)
        self.assertEqual(submitted(clarify).frame,
                         {"result": {"answers": {"q0": '["cheese (Recommended)"]', "q1": '["white"]'}}})

    def test_a_single_select_question_is_unchanged(self) -> None:
        for params in (CLARIFY, {"questions": [{**MULTI["questions"][0], "multi_select": False}]}):
            with self.subTest(params=params):
                question = slot("clarify", params)
                text = body(lines_text(question.lines(80, DEFAULT_THEME, 12)))
                self.assertFalse([row for row in text if "[ ]" in row or "one or more" in row], text)
                self.assertEqual(question.handle_key(SPACE), prompts.TypeIt(SPACE))  # Space types, as any character
                self.assertNotIn("space", slot("clarify", params).keys[0])
        self.assertEqual(slot("clarify", CLARIFY).handle_key(Key(CHAR, "2")).frame, {"result": {"answers": {"q0": "blue"}}})
        self.assertEqual(slot("clarify", CLARIFY).handle_key(Key(ENTER)).frame,
                         {"result": {"answers": {"q0": "red (Recommended)"}}})
        self.assertFalse([row for row in body(lines_text(slot("clarify", CLARIFY).lines(80, DEFAULT_THEME, 12)))
                          if "Submit" in row])


class ShortSlotTests(unittest.TestCase):
    """A 40x15 terminal (review B NIT 5): what the slot cuts is marked where it is cut, and ticks are not lost."""

    FRUIT = {"questions": [{
        "qid": "q0", "multi_select": True,
        "question": "Which fruits should go in the salad? Pick every one you want, there is no limit at all on how many",
        "choices": ["apple, sliced thin and kept in lemon water so it does not brown before serving (Recommended)",
                    "banana", "cherry"],
    }]}

    def test_an_approval_whose_last_rows_are_cut_says_more_choices_under_them(self) -> None:
        command = "\n".join(f"rm -rf ./tmp-r{n:02}" for n in range(10))
        approval = slot("approval", {**APPROVAL, "command": command, "choices": ["once", "session", "always", "deny"]})
        text = [unbarred(row) for row in lines_text(approval.lines(40, DEFAULT_THEME, 8))]
        self.assertEqual(len(text), 8)
        self.assertEqual(text[-1], "  … more choices · ctrl+o shows all")
        self.assertFalse([row for row in text if "tell Hermes" in row])
        choices = text[text.index("❯ ✗ deny") :]
        self.assertFalse(any(char.isdigit() for row in choices for char in row), text)  # no digit picks an approval

    def test_a_multi_select_question_keeps_its_cut_marker_off_the_question_text(self) -> None:
        clarify = slot("clarify", self.FRUIT)
        text = body(lines_text(clarify.lines(40, DEFAULT_THEME, 9)))  # eight rows and the key row
        question = text[: next(index for index, row in enumerate(text) if row.startswith("❯"))]
        self.assertEqual(question[-1], "or more)")  # the question whole, its note's end on its own last row
        self.assertFalse([row for row in question if "ctrl+o" in row], text)
        self.assertTrue(text[-1].endswith("ctrl+o"), text)  # the cut is marked with the choices

    def test_a_ticked_choice_scrolled_out_of_the_list_is_still_counted(self) -> None:
        clarify = slot("clarify", self.FRUIT)
        clarify.handle_key(SPACE)  # ticks apple
        clarify.handle_key(Key(DOWN))
        text = body(lines_text(clarify.lines(40, DEFAULT_THEME, 9)))  # eight rows and the key row
        self.assertFalse([row for row in text if "apple" in row], text)
        marker = next(row for row in text if "ctrl+o" in row)
        self.assertIn("1 ticked", marker)  # under the list: the Type something and Submit rows are cut there too

    def test_nothing_cut_means_no_marker_and_no_count(self) -> None:
        clarify = slot("clarify", self.FRUIT)
        clarify.handle_key(SPACE)
        self.assertFalse([row for row in lines_text(clarify.lines(80, DEFAULT_THEME, 14)) if "ctrl+o" in row])


class OutcomeTests(unittest.TestCase):
    def test_an_empty_or_missing_answer_reads_skipped_as_hermes_counts_it(self) -> None:
        # clarify_tool._response_status: None and "" are both "skipped" when the qid is present.
        for value in ("", None):
            with self.subTest(value=value):
                rows = slot("clarify", CLARIFY).outcomes({"result": {"answers": {"q0": value}}})
                self.assertEqual(rows, [(False, "skipped · Which color do you prefer?")])

    def test_empty_items_of_a_multi_select_answer_are_left_out_as_hermes_leaves_them_out(self) -> None:
        # clarify_tool._clean_answer keeps only items with text; with none left the answer reads as skipped.
        question = slot("clarify", MULTI)
        self.assertEqual(question.outcomes({"result": {"answers": {"q0": '["", "ham", " "]'}}}),
                         [(True, "ham · Which toppings?")])
        self.assertEqual(question.outcomes({"result": {"answers": {"q0": '["", " "]'}}}),
                         [(False, "skipped · Which toppings?")])

    def test_a_question_the_answers_do_not_name_gets_no_row(self) -> None:
        self.assertEqual(slot("clarify", CLARIFY).outcomes({"result": {"answers": {}}}), [])

    def test_a_multi_select_question_without_a_string_choice_is_answered_and_read_as_text(self) -> None:
        # The slot asks for text where no choice is a string (`_multi`); its outcome reads the answer the same way,
        # rather than parse the typed words as a JSON list after the answer went out.
        question = slot("clarify", {"questions": [{"qid": "q0", "question": "How many?", "choices": [1, 2],
                                                   "multi_select": True}]})
        answer = question.submit_text("three, please")
        self.assertEqual(answer.frame, {"result": {"answers": {"q0": "three, please"}}})  # type: ignore[union-attr]
        self.assertEqual(question.outcomes(answer.frame), [(True, "three, please · How many?")])  # type: ignore[union-attr]


class ValuePromptTests(unittest.TestCase):
    def test_sudo_and_secret_are_masked_and_answer_with_the_submitted_value(self) -> None:
        for method in ("sudo", "secret"):
            with self.subTest(method=method):
                value = slot(method, {"command": "apt install x", "env_var": "TOKEN_X"})
                self.assertTrue(value.masked)
                self.assertEqual(value.submit_text("hunter2").frame, {"result": {"value": "hunter2"}})

    def test_the_slot_keeps_no_copy_of_a_submitted_value(self) -> None:
        value = slot("sudo", {"command": "apt install x"})
        value.submit_text("hunter2")
        self.assertNotIn("hunter2", repr(value))

    def test_declining_a_value_prompt_sends_an_empty_value(self) -> None:
        self.assertEqual(slot("vault.code", {}).handle_key(Key(ESCAPE)).frame, {"result": {"value": ""}})


class ImmediateAnswerTests(unittest.TestCase):
    def test_desktop_only_requests_are_answered_unsupported_with_a_notice(self) -> None:
        for method in ("terminal.read", "preview.read", "preview.act", "window.read", "tour", "display.install.sudo"):
            with self.subTest(method=method):
                opened = prompts.open_request("srq-9", method, {})
                self.assertIsInstance(opened, prompts.ImmediateAnswer)
                self.assertEqual(opened.answer.request_id, "srq-9")
                self.assertEqual(opened.answer.frame["error"]["code"], -32601)
                self.assertIn(method, opened.notice)

    def test_vault_unlock_is_declined_with_an_empty_value_and_names_hermes(self) -> None:
        opened = prompts.open_request("srq-9", "vault.unlock_prompt", {"backend": "1password"})
        self.assertEqual(opened.answer.frame, {"result": {"value": ""}})
        self.assertIn("hermes --tui", opened.notice)

    def test_an_unknown_future_request_is_still_answered(self) -> None:
        opened = prompts.open_request("srq-9", "future.request", {})
        self.assertIsInstance(opened, prompts.ImmediateAnswer)
        self.assertEqual(opened.answer.frame["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()

"""Round 4, the Claude Code look in the transcript: per-call rows, results under `⎿`, the working row; since the
rail and kind colours (2026-10-22) each block hangs on a rail: one painted cell and a space.

Each tool call is one row on a rail in the launch look's accent (red when it
failed or was denied, as its band is; owner's pick of 2026-10-29): its state's mark
(`○` running blue, `●` done green, `✗` failed or denied red), the tool's name
bold in its family's hue and what it ran on in parentheses, its duration at
the end. What it printed goes under `  ⎿  `; a read or a load says in one
line what it read instead of echoing its first lines (in the details view,
where a run of loads is unfolded). Result shapes are Hermes 6c61c3e27d's
(`tools/file_tools.py`, `tools/skills_tool.py`, `tools/file_operations_common.py`).

While a turn runs the working row reads `✶ Synthesizing… (1m 24s · ↓4.2k
tokens · thinking with high effort · esc to interrupt)`: a glyph that turns,
Hermes' activity as a verb with its kaomoji and dots taken off, and under it
one tip a turn (`  ⎿  Tip: …`) where the rows allow.

Your prompt reads `  ❯ 오마이 헤르메스란`: a dim rail, the composer's dim `❯` and
dim text with no band, as a command's echo does (with no rail). A turn closes with a dim `  ✻ 5s · 3 tools · ↓1.3k`
and no rule after it.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import unittest
from unittest import mock

from _tui_lines import RULE_ROW, line_text, lines_text, without_badge
from test_tui_modes import drawn, make_app, show_mode, type_text
from omh.skin_pack import SKIN_THEMES
from omh.tui.app import (
    CYCLE_TIP,
    HERMES_OWN_CYCLE_TIP,
    INTERRUPTING,
    TICK_SECONDS,
    TIP_MIN_ROWS,
    TIPS,
    WORKING_GLYPHS,
    queue_lines,
    working_verb,
)
from omh.tui.frame import MODE_ACCEPT, MODE_PLAN, sticky_line
from omh.tui.diff_view import DIFF_ADDED, DIFF_FILE, DIFF_HUNK, DIFF_INDENT, DiffLine, diff_rows
from omh.tui.gateway import Event
from omh.tui.composer import PROMPT
from omh.tui.history import HistorySearch
from omh.tui.keys import CHAR, Key
from omh.tui.session_picker import FILTER_PROMPT
from omh.tui.style import Span, is_fill
from omh.tui.theme import DEFAULT_THEME as THEME
from omh.tui.theme import LAUNCH_PRESETS, TEXT_CONTRAST, build_theme, contrast_ratio, kind_style, with_prompt_band
from omh.tui.transcript import (
    GUTTER,
    NOTICE_INFO,
    PULSE_SECONDS,
    TOOL_DENIED,
    TOOL_ERROR,
    TOOL_OK,
    TOOL_RUNNING,
    CommandBlock,
    ToolGroup,
    ToolRow,
    Transcript,
    USER_MARK,
    TurnSummaryBlock,
    UserBlock,
    block_rows,
    rail_cell,
)
from omh.tui.width import line_width

SID = "s"


def rows_of(tool: ToolRow, width: int = 60, theme=THEME, now: float | None = None, expanded: bool = False) -> list:
    return block_rows(ToolGroup([tool], done=tool.status != TOOL_RUNNING), width, theme, expanded, now=now)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def completed(name: str, result: object, context: str = "x", details: bool = False) -> list[str]:
    """The rows a call that completed with `result` flushes, or the details view shows (`details`)."""
    transcript = Transcript(clock=Clock())
    transcript.apply(Event("message.start", SID, {}))
    transcript.apply(Event("tool.start", SID, {"tool_id": "t", "name": name, "context": context}))
    transcript.apply(Event("tool.complete", SID, {"tool_id": "t", "name": name, "duration_s": 0.2, "result": result}))
    transcript.apply(Event("message.complete", SID, {"text": "", "status": "complete"}))
    if details:
        return lines_text(transcript.history_lines(60, THEME, details=True))
    return lines_text(transcript.take_stable_lines(60, THEME))


class ToolRowTests(unittest.TestCase):
    def test_a_call_is_its_mark_then_its_name_and_what_it_ran_on_in_parentheses(self) -> None:
        (row,) = rows_of(ToolRow("t", "terminal", "rm -rf ./tmp-cache", TOOL_OK, duration_s=1.9))
        self.assertEqual(line_text(row), "  ● terminal(rm -rf ./tmp-cache)  1.9s")
        # The rail in the launch look's accent, then the mark in its state's colour.
        self.assertEqual(row[:3], (rail_cell(THEME.accent), Span(" ", GUTTER), Span("●", THEME.ok)))
        self.assertEqual([span.style for span in row if span.text == "terminal"], [kind_style("terminal", THEME)])
        self.assertEqual(row[-1].style, THEME.faint)  # the duration, under the args' grey

    def test_the_mark_is_green_done_red_failed_or_denied_and_blue_while_it_runs_on_the_looks_rail(self) -> None:
        # The DAG border rule on the mark: running blue, failed red, done green, and each state its own glyph, so the
        # colour is never the only thing that says it. The rail is the launch look's accent (owner, 2026-10-29), but
        # a failure's, which stays red as its band does.
        for status, glyph, style, rail in ((TOOL_OK, "●", THEME.ok, THEME.accent),
                                           (TOOL_ERROR, "✗", THEME.error, THEME.error),
                                           (TOOL_DENIED, "✗", THEME.error, THEME.error),
                                           (TOOL_RUNNING, "○", THEME.running, THEME.accent)):
            with self.subTest(status=status):
                rows = rows_of(ToolRow("t", "terminal", "ls", status, started_at=0.0, duration_s=0.1, output=("x",)))
                self.assertEqual(rows[0][2], Span(glyph, style))
                self.assertEqual({row[0] for row in rows}, {rail_cell(rail)})  # one rail down the whole call
        self.assertEqual(THEME.running.fg, "#58A6FF")  # the owner's approved shade, apart from the graph's edge stops
        self.assertNotIn(THEME.accent.fg, {THEME.ok.fg, THEME.error.fg, THEME.running.fg})
        running = ToolRow("t", "terminal", "ls", TOOL_RUNNING, started_at=0.0)
        pulsed = rows_of(running, now=PULSE_SECONDS * 1.5)[0]
        self.assertEqual(pulsed[2], Span("○", THEME.dim))  # its dim half; the rail holds still
        self.assertEqual(pulsed[0], rail_cell(THEME.accent))
        self.assertFalse([row for row in rows_of(ToolRow("t", "terminal", "ls", TOOL_OK)) if "✓" in line_text(row)])

    def test_on_a_light_terminal_each_mark_reads_against_what_it_sits_on(self) -> None:
        for skin in SKIN_THEMES:
            theme = build_theme(skin, "#FFFFFF")
            for status in (TOOL_OK, TOOL_ERROR, TOOL_DENIED, TOOL_RUNNING):
                row = rows_of(ToolRow("t", "terminal", "ls", status, started_at=0.0), theme=theme)[0]
                with self.subTest(theme=skin.short_name, status=status):
                    self.assertEqual({span.style.bg for span in row}, {None})  # no band behind a call
                    for span in (row[0], row[2]):  # the rail and the mark
                        self.assertGreaterEqual(contrast_ratio(span.style.fg, "#FFFFFF"), 3.0)

    def test_a_call_with_nothing_to_show_has_no_parentheses(self) -> None:
        (row,) = rows_of(ToolRow("t", "todo_list", "", TOOL_OK, duration_s=0.0))
        self.assertEqual(line_text(row), "  ● todo_list  0.0s")

    def test_a_long_argument_is_cut_inside_its_parentheses_and_a_path_from_the_left(self) -> None:
        (row,) = rows_of(ToolRow("t", "terminal", "x" * 200, TOOL_OK, duration_s=12.0), width=40)
        self.assertEqual(line_text(row), "  ● terminal(" + "x" * 18 + "…)  12.0s")  # the rail takes two cells
        self.assertEqual(line_width(row), 40)
        (row,) = rows_of(ToolRow("t", "read_file", "/repo/a/very/deep/tree/of/dirs/file.py", TOOL_OK), width=32)
        self.assertEqual(line_text(row), "  ● read_file(…/of/dirs/file.py)")

    def test_what_it_printed_goes_under_the_result_mark_with_the_rest_counted(self) -> None:
        tool = ToolRow("t", "terminal", "seq 5", TOOL_OK, duration_s=0.1, output=("1", "2", "3", "4", "5"))
        self.assertEqual(
            lines_text(rows_of(tool)),
            ["  ● terminal(seq 5)  0.1s", "    ⎿  1", "       2", "       3", "       … +2 lines · ctrl+o shows all"],
        )
        failed = ToolRow("t", "terminal", "pytest", TOOL_ERROR, duration_s=2.0, output=("a", "b", "c", "1 failed"))
        self.assertEqual(lines_text(rows_of(failed))[1:], ["    ⎿  … +1 line · ctrl+o shows all", "       b",
                                                           "       c", "       1 failed"])

    def test_a_diff_hangs_under_the_result_mark(self) -> None:
        diff = "a/src/app.py → b/src/app.py\n@@ -1,2 +1,2 @@\n import os\n-print('a')\n+print('b')"
        tool = ToolRow("t", "patch", "src/app.py", TOOL_OK, duration_s=0.3, inline_diff=diff.encode("utf-8"))
        shown = [row.rstrip() for row in lines_text(rows_of(tool))]
        self.assertEqual(shown, ["  ● patch(src/app.py)  0.3s", "    ⎿  src/app.py", "     1  import os",
                                 "     2 -print('a')", "     2 +print('b')"])
        self.assertEqual(DIFF_INDENT, len("  ⎿  "))  # the code starts where a result's words do

    def test_the_lead_takes_only_an_indent_and_a_narrow_diff_has_none_to_take(self) -> None:
        lead = (Span("  "), Span("⎿  ", THEME.dim))
        file_first = (DiffLine(DIFF_FILE, "a.py"), DiffLine(DIFF_HUNK, "@@ -1 +1 @@"), DiffLine(DIFF_ADDED, "+x"))
        self.assertEqual(diff_rows(file_first, 40, THEME, lead=lead)[0], (*lead, Span("a.py", THEME.label)))
        code_first = file_first[1:]  # the gutter, not an indent, opens its first row
        self.assertEqual(diff_rows(code_first, 40, THEME, lead=lead), diff_rows(code_first, 40, THEME))
        self.assertEqual(diff_rows(file_first, 10, THEME, lead=lead), diff_rows(file_first, 10, THEME))


class SummarisedReadTests(unittest.TestCase):
    def test_a_read_file_says_how_many_lines_it_read(self) -> None:
        content = "     1|# OMH\n     2|line\n     3|end\n"
        self.assertEqual(completed("read_file", {"content": content, "total_lines": 715}),
                         ["  ● read_file(x)  0.2s", "    ⎿  Read 3 lines"])
        self.assertEqual(completed("read_file", {"content": "     1|one", "total_lines": 1})[1], "    ⎿  Read 1 line")

    def test_a_binary_read_or_a_failed_call_is_not_summarised(self) -> None:
        self.assertEqual(completed("read_file", {"error": "File not found: x"})[1:], ["    ⎿  File not found: x"])
        binary = completed("read_file", {"content": "", "is_binary": True, "error": None})
        self.assertNotIn("Read", "\n".join(binary))
        # Hermes' SearchResult always carries total_count, a failed search too: its error is what it says.
        self.assertEqual(completed("search_files", {"total_count": 0, "error": "rg failed"})[1:], ["    ⎿  rg failed"])

    def test_a_skill_view_names_the_skill_it_loaded(self) -> None:
        # In the transcript a load is folded into its `Loaded N skills` row; the details view unfolds it.
        loaded = {"success": True, "name": "omh-docs", "content": "---\nname: omh-docs\n---\n# body"}
        self.assertEqual(completed("skill_view", loaded, "omh-docs"), ["  ● Loaded 1 skill · omh-docs  0.2s"])
        self.assertEqual(completed("skill_view", loaded, details=True)[1:], ["    ⎿  loaded skill omh-docs"])
        stub = {"success": True, "status": "unchanged", "name": "omh-docs", "file": "SKILL.md", "dedup": True}
        self.assertEqual(completed("skill_view", stub, details=True)[1:], ["    ⎿  loaded skill omh-docs"])
        linked = {"success": True, "name": "omh-docs", "file": "references/api.md", "content": "# api"}
        self.assertEqual(completed("skill_view", linked, details=True)[1:],
                         ["    ⎿  loaded references/api.md from skill omh-docs"])

    def test_a_search_says_how_many_it_found(self) -> None:
        matches = [{"path": "a.py", "line": 1, "content": "needle"}]
        self.assertEqual(completed("search_files", {"total_count": 12, "matches": matches * 12})[1:],
                         ["    ⎿  12 matches"])
        self.assertEqual(completed("search_files", {"total_count": 1, "matches": matches})[1:], ["    ⎿  1 match"])
        self.assertEqual(completed("search_files", {"total_count": 3, "files": ["a", "b", "c"]})[1:],
                         ["    ⎿  3 files"])
        capped = {"total_count": 50, "matches_text": "a.py\n  1: x", "truncated": True, "total_count_is_lower_bound": True}
        self.assertEqual(completed("search_files", capped)[1:], ["    ⎿  50+ matches"])
        self.assertEqual(completed("search_files", {"total_count": 0})[1:], ["    ⎿  0 matches"])

    def test_a_search_keeps_hermes_warning_under_its_count(self) -> None:
        # 6c61c3e27d tools/file_operations_search.py: a zero-match probe's hint, the line-oriented note.
        warned = {"total_count": 0, "warning": "0 results found. Note: search is line-oriented.\nUse context=N."}
        self.assertEqual(completed("search_files", warned)[1:],
                         ["    ⎿  0 matches", "       0 results found. Note: search is line-oriented."])

    def test_the_details_view_shows_the_same_one_line(self) -> None:
        transcript = Transcript(clock=Clock())
        transcript.apply(Event("tool.start", SID, {"tool_id": "t", "name": "read_file", "context": "a.py"}))
        transcript.apply(Event("tool.complete", SID, {"tool_id": "t", "name": "read_file", "result": {"content": "a\nb"}}))
        self.assertEqual(lines_text(transcript.history_lines(60, THEME, details=True))[1:], ["    ⎿  Read 2 lines"])

    def test_terminal_output_keeps_its_lines(self) -> None:
        self.assertEqual(completed("terminal", {"output": "hello\nworld", "exit_code": 0})[1:],
                         ["    ⎿  hello", "       world"])


class WorkingVerbTests(unittest.TestCase):
    def test_hermes_spinner_text_loses_its_face_and_its_dots(self) -> None:
        # Hermes 6c61c3e27d writes f"{face} {verb}..." (agent/turn_iteration_prep.py), faces from KAWAII_THINKING
        # and verbs from THINKING_VERBS or a locale's display.thinking_verbs, some of them two words.
        for text, verb in (("(⌐■_■) analyzing...", "Analyzing"), ("( •_•)>⌐■-■ brainstorming...", "Brainstorming"),
                           ("( ͡° ͜ʖ ͡°) pondering...", "Pondering"), ("٩(๑❛ᴗ❛๑)۶ kafa yoruyor...", "Kafa yoruyor"),
                           ("(°ロ°) 思案中...", "思案中"), ("ಠ_ಠ synthesizing...", "Synthesizing"),
                           ("(⊙_⊙) يتأمّل...", "يتأمّل")):  # locales/ar.yaml: a shadda, a combining mark, in the verb
            with self.subTest(text=text):
                self.assertEqual(working_verb(text), verb)

    def test_every_face_hermes_and_its_skins_ship_is_taken_off(self) -> None:
        # 6c61c3e27d: KawaiiSpinner.KAWAII_THINKING (agent/display.py) and the skins' thinking_faces
        # (hermes_cli/skin_engine.py); none has an ASCII letter or digit.
        faces = ("(｡•́︿•̀｡)", "(◔_◔)", "(¬‿¬)", "( •_•)>⌐■-■", "(⌐■_■)", "(´･_･`)", "◉_◉", "(°ロ°)", "( ˘⌣˘)♡",
                 "ヽ(>∀<☆)☆", "٩(๑❛ᴗ❛๑)۶", "(⊙_⊙)", "(¬_¬)", "( ͡° ͜ʖ ͡°)", "ಠ_ಠ", "(⚔)", "(⛨)", "(▲)", "(⌁)", "(<>)",
                 "(Ψ)", "(∿)", "(≈)", "(◌)", "(◉)", "(◬)", "(○)", "(●)", "(✦)", "(◇)", "(🔥)")
        for face in faces:
            with self.subTest(face=face):
                self.assertEqual(working_verb(f"{face} pondering..."), "Pondering")

    def test_hermes_diagnostics_that_end_in_dots_keep_their_words(self) -> None:
        # 6c61c3e27d: the stall notices (agent/chat_completion_nonstream.py, agent/chat_completion_helpers.py), the
        # retry status (agent/turn_recovery.py) and the compaction status (agent/conversation_compression.py).
        for text, verb in (
            ("⚠ no response from provider in 120s — reconnecting...", "No response from provider in 120s — reconnecting"),
            ("⚠ no output from provider for 45s — reconnecting...", "No output from provider for 45s — reconnecting"),
            ("⏳ Retrying in 5.0s (attempt 1/3)...", "Retrying in 5.0s (attempt 1/3)"),
            ("🗜️ Compacting context — summarizing earlier conversation so I can continue...",
             "Compacting context — summarizing earlier conversation so I can continue"),
        ):
            with self.subTest(text=text):
                self.assertEqual(working_verb(text), verb)

    def test_other_text_loses_only_a_glyph_before_its_words(self) -> None:
        wait = "⏳ waiting on deepseek/deepseek-v4 — no response for 30s"  # agent/chat_completion_wait_notice.py
        self.assertEqual(working_verb(wait), "Waiting on deepseek/deepseek-v4 — no response for 30s")
        self.assertEqual(working_verb("compressing context…"), "Compressing context")
        self.assertEqual(working_verb("Reading the router"), "Reading the router")

    def test_a_face_alone_or_nothing_leaves_no_verb(self) -> None:
        for text in ("(◔_◔)...", "", "   ", "..."):
            with self.subTest(text=text):
                self.assertEqual(working_verb(text), "")


def working_rows(app, cols: int = 100) -> list[str]:
    """The rows under the live transcript while a turn runs: the working row, then any tip."""
    return [line for line in lines_text(app._tail(cols)) if line][-2:]


# A completion menu row: the pointer or its blank column, a name, then its summary (not the composer or the info line).
MENU_ROW = re.compile(r"(❯|\s) /\S+ {2,}\S")


class WorkingRowTests(unittest.TestCase):
    def busy(self, rows: int = 24, **options: object):
        clock = Clock()
        app, _client = make_app(busy=True, rows=rows, clock=clock, **options)
        app.busy_since = clock.now
        return app, clock

    def test_the_row_reads_glyph_verb_and_its_facts(self) -> None:
        app, clock = self.busy()
        app.transcript.activity = "(⌐■_■) synthesizing..."
        app.effort = "xhigh"
        app.turn_shown = 4200
        clock.now += 84
        working = working_rows(app)[0]
        self.assertEqual(working[2:], "Synthesizing… (1m 24s · ↓4.2k tokens · thinking with xhigh effort · esc to interrupt)")
        self.assertIn(working[0], WORKING_GLYPHS)

    def test_without_words_from_hermes_it_is_working_and_an_unknown_effort_is_left_out(self) -> None:
        for effort in ("", "default", "none"):  # none: thinking is off
            with self.subTest(effort=effort):
                app, _clock = self.busy()
                app.effort = effort
                self.assertEqual(working_rows(app)[0][2:], "Working… (0s · esc to interrupt)")
        app, _clock = self.busy()
        # A face with no verb leaves the slot `Working`; a status goes after the facts, dim (2026-10-28).
        app.transcript.activity, app.transcript.status = "(◔_◔)...", "compressing context"
        self.assertEqual(working_rows(app)[0][2:], "Working… (0s · esc to interrupt) · Compressing context")

    def test_a_status_never_takes_the_verb_slot_and_gives_way_first(self) -> None:
        # The owner's screenshot of 2026-10-28: `✳ OMH — recalled 4 memories… (18m 6s · ↓1.6k tokens …)`.
        app, clock = self.busy()
        app.effort = "high"
        app.transcript.activity = "(⌐■_■) pondering..."
        app.transcript.status = "🧠 OMH — recalled 4 memories"
        clock.now += 1086
        rows = working_rows(app, 140)
        self.assertEqual(rows[0][2:], "Pondering… (18m 6s · thinking with high effort · esc to interrupt) · "
                                      "OMH — recalled 4 memories")
        app.transcript.activity = "🧠 OMH — recalled 4 memories"  # the same words on the activity channel
        app.transcript.status = ""
        self.assertTrue(working_rows(app, 140)[0][2:].startswith("Pondering… (18m 6s"))  # the verb holds
        self.assertEqual(working_rows(app, 60)[0][2:], "Pondering… (18m 6s · esc to interrupt)")  # status goes first

    def test_a_stall_notice_keeps_its_cause_and_how_long_on_the_row(self) -> None:
        app, _clock = self.busy()
        app.effort = ""
        app.transcript.activity = "⚠ no response from provider in 120s — reconnecting..."
        self.assertEqual(working_rows(app)[0][2:], "No response from provider in 120s — reconnecting… (0s · esc to interrupt)")
        self.assertEqual(line_width(app._tail(30)[-2]), 30)  # a narrow row is cut at the edge

    def test_a_narrow_row_drops_the_effort_before_the_interrupt(self) -> None:
        app, clock = self.busy()
        app.transcript.activity, app.effort = "(⌐■_■) synthesizing...", "high"
        clock.now += 84
        self.assertEqual(working_rows(app, 60)[0][2:], "Synthesizing… (1m 24s · esc to interrupt)")  # the info line says it
        self.assertEqual(working_rows(app, 80)[0][2:], "Synthesizing… (1m 24s · thinking with high effort · esc to interrupt)")
        self.assertEqual(working_rows(app, 30)[0][2:], "Synthesizing…")  # nothing in parentheses fits whole

    def test_a_narrow_row_drops_whole_parts_and_never_cuts_one(self) -> None:
        # Review B at 40 columns: `✶ Working… (4s · ↓170 tokens · esc to i…`.
        app, clock = self.busy()
        app.effort = "high"
        app.turn_shown = 170
        clock.now += 4
        for width, said in ((100, "Working… (4s · ↓170 tokens · thinking with high effort · esc to interrupt)"),
                            (60, "Working… (4s · ↓170 tokens · esc to interrupt)"), (40, "Working… (4s · esc to interrupt)"),
                            (30, "Working… (esc to interrupt)"), (20, "Working…")):
            with self.subTest(width=width):
                self.assertEqual(working_rows(app, width)[0][2:], said)

    def test_the_glyph_turns_through_claude_codes_set_and_holds_under_reduced_motion(self) -> None:
        app, clock = self.busy()
        seen = []
        for _ in range(len(WORKING_GLYPHS)):
            clock.now += TICK_SECONDS
            seen.append(app._tail(100)[-2][0])
        self.assertEqual({span.text for span in seen}, set("·✢✳✶✻✽"))
        self.assertEqual({span.style for span in seen}, {THEME.accent})  # the launch look's, not a state's
        still, clock = self.busy(environ={"OMH_TUI_REDUCED_MOTION": "1"})
        held = set()
        for _ in range(len(WORKING_GLYPHS)):
            clock.now += TICK_SECONDS
            held.add(still._tail(100)[-2][0].text)
        self.assertEqual(held, {WORKING_GLYPHS[0]})

    def test_the_interrupting_row_lines_up_with_the_working_row(self) -> None:
        app, _clock = self.busy()
        app.interrupting = True
        (row,) = [line for line in app._tail(100) if INTERRUPTING in line_text(line)]
        self.assertEqual(line_text(row), f"{WORKING_GLYPHS[0]} {INTERRUPTING} (0s)")
        self.assertEqual((row[0].style, row[2].style), (THEME.warn, THEME.warn))

    def test_one_tip_a_turn_under_the_working_row_in_turn(self) -> None:
        app, clock = self.busy()
        tips = []
        for _ in range(len(TIPS) + 1):
            working, tip = working_rows(app)
            self.assertTrue(working[2:].startswith("Working…"), working)
            self.assertEqual(working_rows(app)[1], tip)  # the same tip all turn
            tips.append(tip)
            clock.now += 30
            app.busy_since = clock.now  # the next turn
        self.assertEqual(tips[:-1], [f"  ⎿  Tip: {text}" for text in TIPS])
        self.assertEqual(tips[-1], tips[0])

    def test_the_shift_tab_tip_says_what_the_key_does_while_hermes_has_approvals_off(self) -> None:
        app, _clock = self.busy()
        app.tip_index = TIPS.index(CYCLE_TIP) - 1  # this turn's tip is Shift+Tab's
        app.approvals_off, app.yolo_by_tui = True, False  # Hermes turned them off on its own
        self.assertEqual(working_rows(app)[1], f"  ⎿  Tip: {HERMES_OWN_CYCLE_TIP}")
        app.yolo_by_tui = True  # the TUI's own accept all: Shift+Tab goes on to plan mode
        self.assertEqual(working_rows(app)[1], f"  ⎿  Tip: {CYCLE_TIP}")

    def test_no_tip_on_a_short_terminal_or_without_the_working_row(self) -> None:
        short, _clock = self.busy(rows=TIP_MIN_ROWS - 1)
        self.assertFalse([line for line in lines_text(short._tail(100)) if "Tip:" in line])
        tall, _clock = self.busy(rows=TIP_MIN_ROWS)
        self.assertTrue([line for line in lines_text(tall._tail(100)) if "Tip:" in line])
        waiting, clock = self.busy()  # a question: the waiting row stands in its place
        waiting.waiting_since = clock.now
        self.assertFalse([line for line in lines_text(waiting._tail(100)) if "Tip:" in line])
        stopping, _clock = self.busy()
        stopping.interrupting = True
        self.assertFalse([line for line in lines_text(stopping._tail(100)) if "Tip:" in line])

    def test_the_tip_stays_as_a_menu_or_the_agent_list_opens_and_takes_no_row_of_theirs(self) -> None:
        app, _clock = self.busy(rows=TIP_MIN_ROWS)
        type_text(app, "/")
        screen = drawn(app)
        self.assertTrue([line for line in screen if "Tip:" in line], screen)  # nothing above the composer moved
        menu = [line for line in screen if MENU_ROW.match(line)]
        self.assertEqual(len(menu), 5, screen)
        alone, _clock = self.busy(rows=TIP_MIN_ROWS)
        type_text(alone, "/")
        with mock.patch("omh.tui.app.TIP_MIN_ROWS", TIP_MIN_ROWS + 1):  # the same frame with no tip
            self.assertEqual([line for line in drawn(alone) if MENU_ROW.match(line)], menu)
        listing, _clock = self.busy()
        listing.list_selected = 0  # the agent list has the keys
        self.assertTrue([line for line in lines_text(listing._tail(100)) if "Tip:" in line])

class PromptRowTests(unittest.TestCase):
    def test_without_a_prompt_band_a_prompt_is_a_dim_mark_and_dim_text_and_no_fill(self) -> None:
        for theme in (THEME, build_theme(SKIN_THEMES[0], "#1E1E1E"), build_theme(SKIN_THEMES[0], "#FFFFFF")):
            rows = block_rows(UserBlock("first line\nsecond line"), 40, theme)
            with self.subTest(theme=theme.name):
                self.assertEqual(lines_text(rows), ["  ❯ first line", "    second line"])
                self.assertEqual({row[0] for row in rows}, {rail_cell(theme.dim)})  # a grey rail down the prompt
                self.assertEqual(rows[0][2], Span("❯ ", theme.dim))
                self.assertEqual({span.style for row in rows for span in row[3:]}, {theme.muted})  # after the lead
                self.assertEqual({span.style.bg for row in rows for span in row}, {None})  # no prompt_band set: no fill

    def test_a_sent_prompt_runs_on_the_launch_look_s_band_to_the_right_edge(self) -> None:
        # Owner's pick of 2026-10-27 ("보낸프롬프트 배경색"): every row of a sent prompt, a wrapped and a blank one
        # too, on one band that ends at the right edge (a fill, not padding), its words at 4.5:1 on it.
        for background in ("#0D1117", "#FFFFFF"):
            for look in LAUNCH_PRESETS:
                theme = with_prompt_band(build_theme(SKIN_THEMES[0], background), SKIN_THEMES[0], background, look)
                rows = block_rows(UserBlock("first line\n\n" + "word " * 12), 30, theme)
                with self.subTest(background=background, look=look):
                    self.assertEqual(len(rows), 5)  # the first line, the blank one, and the long one wrapped onto three
                    self.assertTrue(all(is_fill(row[-1]) and row[-1].style.bg == theme.prompt_band.bg for row in rows))
                    self.assertEqual({span.style.bg for row in rows for span in row}, {theme.prompt_band.bg})
                    words = [span for row in rows for span in row[3:-1] if span.text.strip()]
                    self.assertTrue(words)
                    for span in words:
                        self.assertGreaterEqual(contrast_ratio(span.style.fg, theme.prompt_band.bg), TEXT_CONTRAST)

    def test_a_prompt_the_queue_sent_says_so_in_the_same_dim(self) -> None:
        (row,) = block_rows(UserBlock("next one", from_queue=True), 40, THEME)
        self.assertEqual(line_text(row), "  ❯ next one  ⧗ from queue")
        self.assertEqual(row[-1].style, THEME.muted)

    def test_the_sticky_reminder_and_the_queue_read_apart_from_a_prompt(self) -> None:
        prompt = line_text(block_rows(UserBlock("fix it"), 40, THEME)[0])
        sticky = line_text(sticky_line("fix it", 40, THEME))
        (queued,) = lines_text(queue_lines(["fix it"], 40, 3, THEME))
        self.assertEqual([prompt[:4], sticky[:7], queued[:2]], ["  ❯ ", "↳ you: ", "⧗ "])

    def test_a_command_echoes_as_a_prompt_does_in_the_hint_colour(self) -> None:
        rows = block_rows(CommandBlock("/model", [("Current model: x", NOTICE_INFO)], done=True), 40, THEME)
        # On the prompt's dim rail (#2223 review 7), so a bare `❯` on the left edge is only ever the composer.
        self.assertEqual(lines_text(rows), ["  ❯ /model", "    ⎿  Current model: x"])
        self.assertEqual({row[0] for row in rows}, {rail_cell(THEME.dim)})
        self.assertEqual((rows[0][2], rows[0][3].style), (Span("❯ ", THEME.dim), THEME.hint))


class DoneLineTests(unittest.TestCase):
    def test_the_done_line_is_one_dim_line_without_a_rule(self) -> None:
        (row,) = block_rows(TurnSummaryBlock(5.0, 3, 1300), 80, THEME)
        self.assertEqual(line_text(row), "  ✻ 5s · 3 tools · ↓1.3k")
        self.assertNotIn("─", line_text(row))
        self.assertEqual([span.style for span in row if span.text.strip()], [THEME.dim, THEME.muted])

    def test_the_wait_on_you_stays_beside_the_time(self) -> None:
        (row,) = block_rows(TurnSummaryBlock(30.0, 1, None, waited=27.0), 80, THEME)
        self.assertEqual(line_text(row), "  ✻ 30s (27s waiting on you) · 1 tool")

    def test_a_narrow_terminal_keeps_the_time_and_a_wide_one_adds_nothing(self) -> None:
        (narrow,) = block_rows(TurnSummaryBlock(5.0, 3, 1300), 12, THEME)
        self.assertEqual(line_text(narrow), "  ✻ 5s")
        (wide,) = block_rows(TurnSummaryBlock(5.0, 3, 1300), 200, THEME)
        self.assertEqual(line_text(wide), "  ✻ 5s · 3 tools · ↓1.3k")

    def test_a_narrow_line_drops_whole_facts_tokens_then_tools_then_the_wait(self) -> None:
        # Review B at 40 columns: `  ✻ 9s (2s waiting on you) · 1 tool · ↓…`.
        block = TurnSummaryBlock(9.0, 1, 1200, waited=2.0)
        for width, said in ((43, "  ✻ 9s (2s waiting on you) · 1 tool · ↓1.2k"), (40, "  ✻ 9s (2s waiting on you) · 1 tool"),
                            (30, "  ✻ 9s (2s waiting on you)"), (20, "  ✻ 9s")):
            with self.subTest(width=width):
                (row,) = block_rows(block, width, THEME)
                self.assertEqual(line_text(row), said)
        (tiny,) = block_rows(block, 5, THEME)  # under the time alone, the row is cut at the edge
        self.assertEqual(line_width(tiny), 5)


class InfoLineInsetTests(unittest.TestCase):
    def test_the_info_line_starts_where_the_composers_text_does(self) -> None:
        app, _client = make_app(rows=24, cols=80)
        screen = [row for row in drawn(app) if row]
        composer, info = screen[-3], screen[-1]
        self.assertTrue(composer.startswith(PROMPT), screen)
        self.assertEqual(info.index("["), len(PROMPT))  # the badge under the composer's text, two cells in
        self.assertTrue(info.startswith("  [⚚ OMH Native]   "), info)  # the badge alone on the left
        self.assertEqual(line_width(app._info_line(80)), 80)  # the right side still ends on the last cell

    def test_a_tiny_terminal_draws_no_rules_and_the_line_starts_on_the_edge(self) -> None:
        app, _client = make_app(rows=5, cols=80)
        show_mode(app, MODE_ACCEPT)  # no badge on a tiny terminal: the mode's label is the line's first cell
        screen = [row for row in drawn(app) if row]
        self.assertTrue(screen[-1].startswith("⏵⏵ accept all on"), screen)
        self.assertFalse([row for row in screen if row.startswith(RULE_ROW)], screen)


class ShortcutsHintTests(unittest.TestCase):
    """The line names no `?` key (owner, 2026-10-28): the launch card lists `? every shortcut`, and `?` on an empty
    composer still opens the list."""

    def test_the_line_never_says_the_shortcuts_hint_and_the_key_still_opens_the_list(self) -> None:
        app, _client = make_app(cols=100)
        for typed in ("", "/", "model"):  # the slash menu opens over the `/`
            type_text(app, typed)
            row = line_text(app._info_line(100))
            with self.subTest(composer=app.composer.text):
                self.assertNotIn("shortcuts", row)
                self.assertTrue(row.endswith("ctrl+t effort"), row)  # the right side stays
        app._set_composer("")
        app._on_input(Key(CHAR, "?"))
        self.assertEqual(app.composer.text, "")  # `?` opened the list instead of typing itself
        self.assertIsNotNone(app.pager)

    def test_a_mode_keeps_its_label_and_where_shift_tab_goes_while_text_is_typed(self) -> None:
        for mode, said in ((MODE_ACCEPT, "⏵⏵ accept all on (⇧⇥ to cycle)"), (MODE_PLAN, "⏸ plan mode on (⇧⇥ to cycle)")):
            with self.subTest(mode=mode):
                app, _client = make_app(cols=100)
                show_mode(app, mode)
                app.yolo_by_tui = app.approvals_off  # accept as the TUI turns it on: Shift+Tab walks every mode
                type_text(app, "hello")
                self.assertTrue(without_badge(line_text(app._info_line(100))).startswith(f"  {said}"))


class PromptMarkTests(unittest.TestCase):
    """One mark for what you type (review B, NIT-3): the composer's `❯`, the echo's, a picker's filter row's, and the
    history search's match row's."""

    def test_the_filter_row_and_the_search_match_use_the_composers_mark(self) -> None:
        self.assertEqual(FILTER_PROMPT.strip(), PROMPT.strip())
        self.assertEqual(USER_MARK, PROMPT)
        search = HistorySearch(["git push"], "")
        search.handle_key(Key(CHAR, "g"))
        (match, _query) = search.lines(60, THEME, 4)
        self.assertEqual(match[0], Span(PROMPT, THEME.prompt))


# A real resume's `messages` (tests/fixtures/tui_gateway/resume_history.json): one turn of five calls, an edit among them.
RESUME = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "tui_gateway" / "resume_history.json").read_text(encoding="utf-8")
)["messages"]
RESUME_CWD = "/fixture/demo"


class ResumedHistoryTests(unittest.TestCase):
    """A resumed session's calls are drawn by the live rows' code: `● name(args)`, the edit's diff under `⎿`."""

    def history(self, width: int = 100) -> list:
        app, _client = make_app(rows=40, cols=width)
        app.transcript.cwd = RESUME_CWD
        app._draw_history(RESUME)
        return [line for line in app.transcript.take_stable_lines(width, THEME)]

    def test_each_recorded_call_is_one_row_with_a_neutral_mark_and_a_blank_row_between_as_live(self) -> None:
        # Since the rail and kind colours (2026-10-22) a live turn puts a blank row between two calls; a record too.
        lines = self.history()
        texts = lines_text(lines)
        first, after = texts.index("  ● read_file(README.md)"), texts.index("  ● terminal(sleep 6 + 1 command)")
        self.assertEqual(texts[first + 1 : first + 5], ["", "  ● read_file(calc.py)", "", "  ● patch(calc.py)"])
        diff = texts[first + 5 : after - 1]
        self.assertTrue(diff and all(text.startswith("  ") for text in diff), texts)  # the diff, on the edit's rail
        self.assertEqual(texts[after - 1 : after + 4],
                         ["", "  ● terminal(sleep 6 + 1 command)", "", "  ● terminal(ls does-not-exist)", ""])
        self.assertEqual(texts[after + 4], "  ⚚ Hermes", texts)  # the reply's header, then its words
        self.assertTrue(texts[after + 5].startswith("    Done — div added to calc.py"), texts)
        calls = [lines[index] for index in (first, first + 2, first + 4, after, after + 2)]
        # The record says what ran, not how it ended: neither green nor red, its mark grey on the look's rail.
        self.assertEqual({row[0] for row in calls}, {rail_cell(THEME.accent)})
        self.assertEqual({row[2] for row in calls}, {Span("●", THEME.dim)})
        self.assertNotIn("·", "".join(texts[first : after + 3]))  # no old-style `· name  args` row

    def test_a_record_whose_result_metadata_is_not_a_mapping_draws_its_row_alone(self) -> None:
        for junk in ("inline_diff", ["inline_diff"], 7):
            with self.subTest(junk=junk):
                app, _client = make_app(rows=40, cols=100)
                app._draw_history([{"role": "tool", "name": "patch", "context": "calc.py", "tool_call_id": "c1",
                                    "display_metadata": {"tool_result_metadata": junk}}])
                self.assertEqual(lines_text(app.transcript.take_stable_lines(100, THEME)), ["  ● patch(calc.py)"])

    def test_the_edit_shows_the_diff_a_live_call_shows(self) -> None:
        texts = lines_text(self.history())
        start = texts.index("  ● patch(calc.py)") + 1
        recorded = texts[start : texts.index("  ● terminal(sleep 6 + 1 command)") - 1]  # up to the blank row
        patch = next(message for message in RESUME if message.get("name") == "patch")
        transcript = Transcript(clock=Clock())
        transcript.cwd = RESUME_CWD
        transcript.apply(Event("message.start", SID, {}))
        transcript.apply(Event("tool.start", SID, {"tool_id": "t", "name": "patch", "context": "calc.py"}))
        inline_diff = patch["display_metadata"]["tool_result_metadata"]["inline_diff"]
        transcript.apply(Event("tool.complete", SID, {"tool_id": "t", "name": "patch", "inline_diff": inline_diff}))
        transcript.apply(Event("message.complete", SID, {"text": "", "status": "complete"}))
        live = lines_text(transcript.take_stable_lines(100, THEME))
        self.assertTrue(live[0].startswith("  ● patch(calc.py)"), live)
        self.assertEqual(recorded, live[1:])
        self.assertTrue(recorded and recorded[0].startswith("    ⎿  "), recorded)


def installation() -> str:
    return " ".join((Path(__file__).resolve().parents[1] / "docs" / "INSTALLATION.md").read_text(encoding="utf-8").split())


class DocumentedLookTests(unittest.TestCase):
    def test_installation_shows_the_rows_the_code_draws(self) -> None:
        prose = installation()
        (row,) = rows_of(ToolRow("t", "terminal", "rm -rf ./tmp-cache", TOOL_OK, duration_s=1.9))
        shown = " ".join(line_text(row).split())  # the prose is read with its runs of spaces joined
        self.assertTrue(f"(`{shown}`)" in prose, shown)
        content = "\n".join(f"{number:6}|x" for number in range(1, 716))
        said = [
            completed("read_file", {"content": content})[1],
            completed("skill_view", {"success": True, "name": "omh-docs", "content": "x"}, details=True)[1],
            completed("skill_view", {"success": True, "name": "omh-docs", "file": "references/api.md"}, details=True)[1],
            completed("search_files", {"total_count": 12, "matches": []})[1],
            completed("search_files", {"total_count": 3, "files": ["a", "b", "c"]})[1],
            completed("search_files", {"total_count": 50, "matches": [], "total_count_is_lower_bound": True})[1],
        ]
        for line in said:
            with self.subTest(line=line):
                self.assertTrue(f"`{line.removeprefix('    ⎿  ')}`" in prose, line)

    def test_installation_shows_the_working_row_the_code_draws(self) -> None:
        prose = installation()
        clock = Clock()
        app, _client = make_app(busy=True, clock=clock)
        app.busy_since = clock.now
        app.transcript.activity, app.effort = "(⌐■_■) synthesizing...", "high"
        app.turn_shown = 4200
        clock.now += 84
        working, tip = working_rows(app)
        self.assertTrue(f"`✶ {working[2:]}`" in prose, working)
        self.assertTrue(f"(`{' '.join(tip.split())}`)" in prose, tip)
        self.assertTrue("(`· ✢ ✳ ✶ ✻ ✽`)" in prose)
        self.assertEqual(set(WORKING_GLYPHS), set("·✢✳✶✻✽"))
        self.assertTrue(f"On a terminal {TIP_MIN_ROWS} rows tall or more a tip sits under it" in prose)
        app.interrupting, app.turn_shown = True, 0  # the example has written nothing yet
        (row,) = [line for line in lines_text(app._tail(100)) if INTERRUPTING in line]
        self.assertTrue(f"`{row.replace('1m 24s', '12s')}`" in prose, row)


    def test_installation_shows_the_prompt_and_the_done_line_the_code_draws(self) -> None:
        prose = installation()
        (done,) = block_rows(TurnSummaryBlock(34.0, 3, 1200), 80, THEME)
        self.assertTrue(f"(`{line_text(done).strip()}`)" in prose, line_text(done))
        echo = block_rows(CommandBlock("/model", done=True), 80, THEME)[0]
        self.assertTrue(f"(`{line_text(echo).strip()}`)" in prose, line_text(echo))  # after the rail's two cells
        self.assertTrue("the composer's dim `❯` and dim text with no band behind it" in prose)


if __name__ == "__main__":
    unittest.main()

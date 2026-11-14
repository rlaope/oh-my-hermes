"""A clarify question the model asked with no reply, its explanation written only as reasoning.

The owner's report of 2026-11-14: a picker opened with nothing above it to
say what it was about. The turn's assistant row in `state.db` had an empty
`content` and the explanation in `reasoning`; with Hermes'
`display.show_reasoning` off the TUI never received it. The picker now reads
that row (read-only, matched by the clarify's own call id) and shows the
reasoning dim above the question.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from _tui_lines import lines_text
from test_tui_modes import SID, drawn, make_app
from omh.tui import prompts
from omh.tui.gateway import Event, ServerRequest
from omh.tui.silent_lead import read_silent_lead
from omh.tui.theme import DEFAULT_THEME

STORED = "local-abc"
CALL = "toolu_01PrjRxSkV5m2sK6xPcpzb4q"
# The owner's turn, as Hermes stored it: no reply text, the explanation in `reasoning`.
REASONING = ("OMH가 빨라진다고 말하려면 먼저 직접 잰 숫자가 필요하니, 같은 작업 10건을 OMH 켠 상태와 끈 상태로 "
             "돌려 시간·턴 수·도구 호출 수를 비교하는 것부터 시작하겠습니다.")
QUESTION = {"questions": [{
    "qid": "q0", "question": "어디부터 시작할까요?",
    "choices": ["1번 측정 도구 — 켠 상태와 끈 상태를 같은 작업으로 비교", "기획 문서만"], "multi_select": False,
}]}

_SCHEMA = ("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL,"
           " content TEXT, tool_calls TEXT, tool_name TEXT, timestamp REAL NOT NULL, reasoning TEXT)")


def calls(name: str, call: str) -> str:
    """A `tool_calls` column as Hermes writes it (`id` and `call_id` both carry the call's id)."""
    return json.dumps([{"id": call, "call_id": call, "type": "function",
                        "function": {"name": name, "arguments": "{}"}}])


def write_rows(home: Path, *rows: tuple[str, str, str | None, str | None, str | None]) -> None:
    """(session, role, content, reasoning, tool_calls) rows, in order, into `<home>/state.db` in WAL mode."""
    connection = sqlite3.connect(home / "state.db")
    try:
        connection.execute("PRAGMA journal_mode=wal")
        connection.execute(_SCHEMA)
        for index, (session, role, content, reasoning, tool_calls) in enumerate(rows):
            connection.execute(
                "INSERT INTO messages (session_id, role, content, reasoning, tool_calls, timestamp)"
                " VALUES (?, ?, ?, ?, ?, ?)", (session, role, content, reasoning, tool_calls, 1000.0 + index))
        connection.commit()
    finally:
        connection.close()


class ReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())

    def read(self, call: str = CALL, session: str = STORED) -> str:
        return read_silent_lead(str(self.home), session, call)

    def test_a_clarify_row_with_no_reply_gives_its_reasoning(self) -> None:
        write_rows(self.home, (STORED, "user", "질문", None, None),
                   (STORED, "assistant", "", REASONING + "\n\n", calls("clarify", CALL)))
        self.assertEqual(self.read(), REASONING)

    def test_a_row_that_said_something_gives_nothing(self) -> None:
        write_rows(self.home, (STORED, "assistant", "설명했습니다.", REASONING, calls("clarify", CALL)))
        self.assertEqual(self.read(), "")

    def test_a_row_without_reasoning_gives_nothing(self) -> None:
        write_rows(self.home, (STORED, "assistant", "", None, calls("clarify", CALL)))
        self.assertEqual(self.read(), "")

    def test_another_tool_or_another_call_gives_nothing(self) -> None:
        # An older turn's row (its clarify is not the one opening) and a terminal call never lend their reasoning.
        write_rows(self.home, (STORED, "assistant", "", REASONING, calls("terminal", CALL)))
        self.assertEqual(self.read(), "")
        self.assertEqual(self.read(call="toolu_other"), "")

    def test_only_the_newest_assistant_row_of_this_session_counts(self) -> None:
        write_rows(self.home, (STORED, "assistant", "", REASONING, calls("clarify", CALL)),
                   ("local-other", "assistant", "", "다른 세션", calls("clarify", "toolu_x")),
                   (STORED, "assistant", "", "새 턴", calls("terminal", "toolu_y")))
        self.assertEqual(self.read(), "")
        self.assertEqual(self.read(call="toolu_x", session="local-other"), "다른 세션")

    def test_no_home_no_session_no_call_or_no_store_gives_nothing(self) -> None:
        self.assertEqual(read_silent_lead("", STORED, CALL), "")
        self.assertEqual(read_silent_lead(str(self.home), "", CALL), "")
        self.assertEqual(read_silent_lead(str(self.home), STORED, ""), "")
        self.assertEqual(self.read(), "")
        self.assertFalse((self.home / "state.db").exists())  # nothing is created where there was no store

    def test_a_closed_store_is_read_without_leaving_files_beside_it(self) -> None:
        write_rows(self.home, (STORED, "assistant", "", REASONING, calls("clarify", CALL)))
        before = sorted(os.listdir(self.home))
        self.assertEqual(self.read(), REASONING)
        self.assertEqual(sorted(os.listdir(self.home)), before)

    def test_a_store_that_is_not_sqlite_gives_nothing(self) -> None:
        (self.home / "state.db").write_bytes(b"not a database")
        self.assertEqual(self.read(), "")


class SlotTests(unittest.TestCase):
    def slot(self, lead: str = REASONING) -> prompts.PromptSlot:
        opened = prompts.open_request("srq-1", "clarify", QUESTION)
        assert isinstance(opened, prompts.PromptSlot)
        opened.silent_lead = lead
        return opened

    def test_the_lead_is_drawn_dim_above_the_asked_sentence(self) -> None:
        rows = self.slot().lines(150, DEFAULT_THEME, 30)
        text = lines_text(rows)
        asked = text.index("▌ 어디부터 시작할까요?")
        self.assertEqual(" ".join(row[2:] for row in text[asked - 2:asked]), REASONING)  # wrapped onto two rows
        lead_span = next(span for span in rows[asked - 2] if span.text.startswith("OMH가"))
        self.assertEqual(lead_span.style, DEFAULT_THEME.muted)

    def test_a_long_lead_keeps_three_rows_and_ctrl_o_shows_it_whole(self) -> None:
        slot = self.slot(" ".join([REASONING] * 6))
        cut = [row for row in lines_text(slot.lines(60, DEFAULT_THEME, 30)) if "OMH" in row or "…" in row]
        self.assertLessEqual(len(cut), prompts.LEAD_ROWS)
        whole = "".join(lines_text(slot.whole_lines(60, DEFAULT_THEME)))
        self.assertEqual(whole.count("OMH가"), 6)

    def test_no_lead_draws_the_question_as_before(self) -> None:
        self.assertEqual(lines_text(self.slot("").lines(150, DEFAULT_THEME, 30)),
                         lines_text(prompts.open_request("srq-1", "clarify", QUESTION).lines(150, DEFAULT_THEME, 30)))

    def test_a_question_without_choices_shows_it_too(self) -> None:
        opened = prompts.open_request("srq-1", "clarify", {"questions": [{"qid": "q0", "question": "이름은?"}]})
        assert isinstance(opened, prompts.PromptSlot)
        opened.silent_lead = REASONING
        text = lines_text(opened.lines(150, DEFAULT_THEME, 30))
        self.assertTrue(text[0].startswith("▌ OMH가"), text)
        asked = next(index for index, row in enumerate(text) if "? 이름은?" in row)
        self.assertGreater(asked, 0)


class AppTests(unittest.TestCase):
    """Through the app, as a live turn opens a clarify: `tool.start` for the call, then the server request."""

    def open_question(self, rows: tuple, call: str = CALL) -> tuple[list[str], object]:
        home = Path(tempfile.mkdtemp())
        write_rows(home, *rows)
        app, _client = make_app(busy=True, rows=30, cols=120, environ={"HERMES_HOME": str(home)})
        app.stored_id = STORED
        app._on_event(Event("message.start", SID, {}))
        app._on_event(Event("tool.start", SID, {"tool_id": call, "name": "clarify", "args": QUESTION}))
        app._on_server_request(ServerRequest("srq-1", "clarify", QUESTION))
        return drawn(app), app

    def test_the_owners_turn_shows_what_the_model_meant_to_say(self) -> None:
        screen, _app = self.open_question(((STORED, "assistant", "", REASONING, calls("clarify", CALL)),))
        joined = "\n".join(screen)
        self.assertIn("OMH가 빨라진다고", joined)
        self.assertLess(joined.index("OMH가 빨라진다고"), joined.index("어디부터 시작할까요?"))

    def test_a_turn_that_wrote_a_reply_shows_no_lead(self) -> None:
        screen, _app = self.open_question(((STORED, "assistant", "설명", REASONING, calls("clarify", CALL)),))
        self.assertNotIn("OMH가 빨라진다고", "\n".join(screen))

    def test_an_older_turns_reasoning_never_reaches_a_new_question(self) -> None:
        # The row on disk is another call's (its own row not written yet): nothing is drawn rather than the wrong text.
        screen, _app = self.open_question(((STORED, "assistant", "", REASONING, calls("clarify", "toolu_old")),))
        self.assertNotIn("OMH가 빨라진다고", "\n".join(screen))

    def test_without_a_hermes_home_nothing_is_read(self) -> None:
        app, _client = make_app(busy=True, rows=30, cols=120)
        seen: list[tuple[str, str, str]] = []
        app.read_silent_lead = lambda *args: seen.append(args) or ""
        app.stored_id = STORED
        app._on_event(Event("tool.start", SID, {"tool_id": CALL, "name": "clarify", "args": QUESTION}))
        app._on_server_request(ServerRequest("srq-1", "clarify", QUESTION))
        self.assertEqual(seen, [("", STORED, CALL)])
        self.assertEqual(app.slot.silent_lead, "")  # type: ignore[union-attr]

    def test_an_approval_reads_nothing(self) -> None:
        app, _client = make_app(busy=True, rows=30, cols=120)
        seen: list[tuple] = []
        app.read_silent_lead = lambda *args: seen.append(args) or "x"
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "ls", "description": "list"}))
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()

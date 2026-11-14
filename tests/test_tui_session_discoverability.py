"""The session picker's listing: one row per conversation, newest activity first, and the picker's previews only
from an owner that advertises them. A stored row another runtime persisted open is listed resumable=False, so the
picker reads its history instead of resuming it.
"""

from __future__ import annotations

import unittest

from omh.tui.attach.gateway_attach import TO_CLIENT, TO_OWNER, Adapter
from omh.tui.session_picker import session_rows


def _ids() -> object:
    counter = iter(range(1, 1000))
    return lambda: f"id-{next(counter)}"


def _call(request_id: object, method: str, params: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def _answer(request_id: object, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _adapter(capabilities: list[str]) -> Adapter:
    adapter = Adapter({}, None, files=None, new_id=_ids())  # type: ignore[arg-type]
    [(_, describe)] = adapter.describe()
    adapter.from_owner(_answer(describe["id"], {"session_create": {"sources": ["tui"], "parameters": []},
                                                "capabilities": capabilities}))
    return adapter


def _list(adapter: Adapter, params: dict) -> tuple[dict, dict]:
    """The live call, the stored call, and the merged answer: what the picker is handed."""
    [(target, live)] = adapter.from_client(_call(7, "session.list", params))
    assert target == TO_OWNER and live["method"] == "session.list"
    return live, params


class ListingTests(unittest.TestCase):
    def test_title_is_forwarded_without_picker_scope_or_limit_rewrite(self):
        for capabilities in ([], ['session-list-picker-v1']):
            adapter = _adapter(capabilities)
            live, _ = _list(adapter, {'title': 'Exact title'})
            self.assertEqual(live['params'], {'title': 'Exact title'})
            answer = adapter.from_owner(_answer(live['id'], {'sessions': []}))
            self.assertEqual(answer[0][0], TO_CLIENT)

    def test_readonly_title_paths_and_multiline_truncation(self):
        from test_tui_modes import make_app
        from omh.tui.gateway import Response
        from _tui_lines import line_text
        for method in ('_resume_looked_up', '_resume_titled'):
            app, client = make_app()
            before = (app.sid, app.stored_id)
            row = {'id': 'elsewhere', 'title': 'Exact title', 'resumable': False}
            getattr(app, method)('Exact title', {}, {'sessions': [row]}, '', app.switch_seq)
            self.assertEqual(client.calls[-1][0], 'session.transcript')
            app._on_response(Response(len(client.calls), {'rows': [
                {'role': 'user', 'text': '\nfirst  \n\nsecond\x00\n'}], 'next_cursor': 'older'}, None))
            text = '\n'.join(line_text(line) for line in app.pager.lines)
            self.assertIn('first\n\nsecond', text)
            self.assertIn('older history remains on the server', text)
            self.assertNotIn('\x00', text)
            self.assertEqual(before, (app.sid, app.stored_id))

    def test_merge_limit_is_applied_after_activity_sort(self):
        adapter = _adapter([])
        live, _ = _list(adapter, {'limit': 1})
        [(_, stored)] = adapter.from_owner(_answer(live['id'], {'sessions': [
            {'id': 'new-start', 'started_at': 900, 'activity_at': 900}]}))
        [(_, answer)] = adapter.from_owner(_answer(stored['id'], {'sessions': [
            {'id': 'old-start', 'started_at': 100, 'activity_at': 1000}]}))
        self.assertEqual([r['id'] for r in answer['result']['sessions']], ['old-start'])

    def test_the_picker_is_asked_for_only_from_an_owner_that_advertises_it(self) -> None:
        for capabilities, expected in (([], {"limit": 200}), (["session-list-picker-v1"], {"limit": 200, "picker": True})):
            live, _ = _list(_adapter(capabilities), {"limit": 5})
            self.assertEqual(live["params"], expected)
            self.assertEqual(_adapter(capabilities).capabilities, frozenset(capabilities))

    def test_live_and_stored_are_one_row_per_conversation_newest_activity_first(self) -> None:
        adapter = _adapter(["session-list-picker-v1"])
        live, _ = _list(adapter, {"limit": 3})
        stored_call = adapter.from_owner(_answer(live["id"], {"sessions": [
            {"id": "old", "started_at": 100.0, "message_count": 4},
            {"id": "tip", "title": "Release notes", "activity_at": 300.0, "message_count": 2},
        ]}))
        [(target, stored)] = stored_call
        self.assertEqual(stored["params"], {"limit": 200, "picker": True, "scope": "stored"})
        # The stored feed names the conversation the live row is only the tip of; its title and freshness win.
        [(_, answer)] = adapter.from_owner(_answer(stored["id"], {"sessions": [
            {"id": "root", "resolved_id": "tip", "preview": "ship it", "activity_at": 900.0, "message_count": 6},
            {"id": "fresh", "activity_at": 500.0},
        ]}))
        sessions = answer["result"]["sessions"]
        # The live row keeps the id it answers under (it is the one that can resume); the stored row's title,
        # preview and freshness merge into it, and its own empty row is not listed twice.
        self.assertEqual([row["id"] for row in sessions], ["tip", "fresh", "old"])
        self.assertEqual((sessions[0]["title"], sessions[0]["preview"]), ("Release notes", "ship it"))
        self.assertEqual(sessions[0]["message_count"], 6)
        self.assertEqual([row.get("activity_at") or row.get("started_at") for row in sessions],
                         [900.0, 500.0, 100.0])

    def test_a_row_either_half_calls_not_resumable_is_listed_read_only(self) -> None:
        adapter = _adapter([])
        live, _ = _list(adapter, {"limit": 9})
        [(_, stored)] = adapter.from_owner(_answer(live["id"], {"sessions": [
            {"id": "elsewhere", "resumable": False, "owner_runtime": "other", "activity_at": 60.0},
            {"id": "mine", "activity_at": 50.0},
        ]}))
        [(_, answer)] = adapter.from_owner(_answer(stored["id"], {"sessions": []}))
        rows = session_rows(answer["result"])
        self.assertEqual([(row.id, row.resumable, row.owner_runtime, row.read_only) for row in rows],
                         [("elsewhere", False, "other", True), ("mine", True, "", False)])

    def test_a_row_timed_in_milliseconds_sorts_with_one_timed_in_seconds(self) -> None:
        adapter = _adapter([])
        live, _ = _list(adapter, {"limit": 5})
        [(_, stored)] = adapter.from_owner(_answer(live["id"], {"sessions": [
            {"id": "millis", "activity_at": 1_700_000_000_000},
            {"id": "seconds", "activity_at": 1_600_000_000},
        ]}))
        [(_, answer)] = adapter.from_owner(_answer(stored["id"], {"sessions": []}))
        self.assertEqual([row["id"] for row in answer["result"]["sessions"]], ["millis", "seconds"])


# What a stock Hermes answers today (NousResearch/hermes-agent 3b42157858): live rows by start, stored rows with the
# picker's `last_active_at` when asked `picker: true`, and never `activity_at`, `resumable` or `owner_runtime`.
STOCK_LIVE = {"sessions": [{"id": "tip", "session_id": "tip", "title": "", "started_at": 500.0, "message_count": 1,
                            "running": False}], "scope": "live"}
STOCK_STORED = {"sessions": [
    {"id": "root", "session_id": "tip", "resolved_id": "tip", "title": "Release notes", "started_at": 100.0,
     "message_count": 9, "running": False, "preview": "ship it", "last_active_at": 900.0},
    {"id": "other", "session_id": "other", "resolved_id": "other", "title": "Older", "started_at": 300.0,
     "message_count": 2, "running": False, "last_active_at": 400.0},
], "scope": "stored"}


class StockHermesTests(unittest.TestCase):
    """Against a Hermes without the companion change the listing still works and every row resumes as before."""

    def test_a_stock_listing_merges_orders_by_last_activity_and_every_row_resumes(self) -> None:
        adapter = _adapter(["session-transcript-v1", "session-list-picker-v1"])
        live, _ = _list(adapter, {"limit": 50})
        [(_, stored)] = adapter.from_owner(_answer(live["id"], STOCK_LIVE))
        [(_, answer)] = adapter.from_owner(_answer(stored["id"], STOCK_STORED))
        rows = session_rows(answer["result"])
        self.assertEqual([(row.id, row.title, row.activity_at, row.read_only) for row in rows],
                         [("tip", "Release notes", 900.0, False), ("other", "Older", 400.0, False)])

    def test_a_stored_row_alone_is_timed_by_the_pickers_last_active_at(self) -> None:
        [row] = session_rows({"sessions": [{"id": "a", "started_at": 100.0, "last_active_at": 900.0}]})
        self.assertEqual(row.activity_at, 900.0)
        [row] = session_rows({"sessions": [{"id": "a", "started_at": 100.0}]})
        self.assertEqual(row.activity_at, 100.0)

    def test_the_tui_itself_never_sends_a_scope_or_picker_key(self) -> None:
        from omh.tui import gateway_contract as contract

        self.assertEqual(contract.call_problem("session.list", {"limit": 50}), "")
        for key in ("scope", "picker"):
            with self.subTest(key=key):
                self.assertIn(key, contract.call_problem("session.list", {"limit": 50, key: "stored"}))


class ReadOnlyRowTests(unittest.TestCase):
    """A row Hermes lists as not resumable is read with `session.transcript`, never resumed, renamed or deleted."""

    LISTED = {"sessions": [
        {"id": "elsewhere", "title": "Held by another runtime", "started_at": 1_791_900_000.0, "message_count": 4,
         "resumable": False, "owner_runtime": "other"},
        {"id": "mine", "title": "Mine", "started_at": 1_791_800_000.0, "message_count": 2},
    ]}

    def opened(self):
        from test_tui_modes import drawn, make_app
        from test_tui_resume_feedback import reply, resume

        app, client = make_app()
        resume(app)
        reply(app, client, self.LISTED)
        assert app.picker is not None
        drawn(app)
        return app, client

    def test_enter_on_a_read_only_row_reads_its_transcript_in_a_pager(self) -> None:
        from _tui_lines import line_text
        from omh.tui.app import TRANSCRIPT_ROW_CUT
        from omh.tui.gateway import Response
        from omh.tui.keys import ENTER, Key

        app, client = self.opened()
        before = (app.sid, app.stored_id)
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls[-1],
                         ("session.transcript", {"session_id": "elsewhere", "order": "latest", "limit": 500}))
        self.assertNotIn("session.resume", [method for method, _params in client.calls])
        app._on_response(Response(len(client.calls), {"session_id": "elsewhere", "rows": [
            {"role": "user", "text": "hello", "row_kind": "message"},
            {"role": "assistant", "text": "a long head", "row_kind": "message", "truncated": True},
        ], "next_cursor": None, "reset": True}, None))
        assert app.pager is not None
        text = [line_text(line) for line in app.pager.lines]
        self.assertEqual(text, ["user: hello", "", "assistant: a long head", TRANSCRIPT_ROW_CUT])
        self.assertEqual(before, (app.sid, app.stored_id))

    def test_a_hermes_without_session_transcript_says_so_and_the_session_goes_on(self) -> None:
        from test_tui_modes import notices
        from omh.tui.gateway import Response
        from omh.tui.keys import ENTER, Key

        app, client = self.opened()
        app._on_input(Key(ENTER))
        app._on_response(Response(len(client.calls), None, {"code": -32601, "message": "unknown method"}))
        self.assertIsNone(app.exit_code)
        self.assertIsNone(app.pager)
        self.assertTrue(any("did not show Held by another runtime" in notice for notice in notices(app)))

    def test_ctrl_r_and_ctrl_d_on_a_read_only_row_send_nothing_and_say_why(self) -> None:
        from test_tui_modes import drawn
        from omh.tui.keys import CHAR, ENTER, Key

        app, client = self.opened()
        sent = len(client.calls)
        app._on_input(Key(CHAR, "d", ctrl=True))
        app._on_input(Key(CHAR, "d", ctrl=True))
        self.assertEqual(len(client.calls), sent)
        self.assertTrue(any("another runtime owns this session" in line for line in drawn(app)))
        app._on_input(Key(CHAR, "r", ctrl=True))
        app._on_input(Key(CHAR, "x"))
        app._on_input(Key(ENTER))
        self.assertEqual(len(client.calls), sent)

    def test_enter_on_a_resumable_row_still_resumes_it(self) -> None:
        from omh.tui.keys import DOWN, ENTER, Key

        app, client = self.opened()
        app._on_input(Key(DOWN))
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls[-1][0], "session.resume")
        self.assertEqual(client.calls[-1][1].get("session_id"), "mine")

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

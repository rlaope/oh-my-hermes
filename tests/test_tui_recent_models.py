"""Recently used models first in bare `/model` (opencode `dialog-model.tsx:65-91`, its `Recent` category).

A switch Hermes confirmed puts its model and provider at the front of `<omh_home>/tui/recent-models.json` (at most
five, no repeats); one Hermes deferred or asked to confirm first records nothing. With an empty filter the picker
lists those still in Hermes' list under `Recent`, then the whole list; a typed filter, a stale entry, a corrupt file,
and a launch without an OMH home show no group.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from _test_temp_root import make_test_tempdir
from _tui_lines import lines_text
from test_tui_modes import SID, RecordingClient, answer, make_app, notices
from test_tui_muscle_memory import OPTIONS, send
from omh.tui.app import App
from omh.tui.gateway import Event, Response
from omh.tui.keys import CHAR, ENTER, Key
from omh.tui.model_picker import (
    ALL_GROUP, RECENT_GROUP, RECENT_LIMIT, RECENT_SCHEMA, ModelPicker, model_rows, read_recent, record_recent,
    recent_path,
)
from omh.tui.theme import DEFAULT_THEME

OPUS = ("claude-opus-5-5", "anthropic")
FABLE = ("claude-fable-5", "anthropic")


class HomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(self.enterContext(make_test_tempdir("omh-recent-models-"))) / ".omh"

    def app(self) -> tuple[App, RecordingClient]:
        return make_app(environ={"OMH_HOME": str(self.home)})

    def switch(self, app: App, client: RecordingClient, model: str, provider: str, result: dict | None = None) -> None:
        send(app, f"/model {model} --provider {provider}")
        self.assertEqual(client.calls[-1][0], "config.set")
        answer(app, client, result if result is not None else {"key": "model", "value": model, "scope": "session"})

    def stored(self) -> list[tuple[str, str]]:
        record = json.loads(recent_path(self.home).read_text(encoding="utf-8"))
        self.assertEqual(record["schema_version"], RECENT_SCHEMA)
        return [(entry["model"], entry["provider"]) for entry in record["models"]]


class RecordTests(HomeTests):
    def test_a_confirmed_switch_goes_to_the_front_and_a_second_reorders(self) -> None:
        app, client = self.app()
        self.switch(app, client, *OPUS)
        self.assertEqual(self.stored(), [OPUS])
        self.switch(app, client, *FABLE)
        self.assertEqual(self.stored(), [FABLE, OPUS])
        self.switch(app, client, *OPUS)
        self.assertEqual(self.stored(), [OPUS, FABLE])  # moved, not repeated

    def test_six_switches_keep_the_last_five(self) -> None:
        app, client = self.app()
        names = [f"m{number}" for number in range(6)]
        for name in names:
            self.switch(app, client, name, "anthropic")
        self.assertEqual(RECENT_LIMIT, 5)
        self.assertEqual(self.stored(), [(name, "anthropic") for name in reversed(names[1:])])

    def test_a_pick_in_the_picker_is_recorded_once_hermes_confirms_it(self) -> None:
        app, client = self.app()
        send(app, "/model")
        answer(app, client, OPTIONS)
        for char in "opus-5-5":
            app._on_input(Key(CHAR, char))
        app._on_input(Key(ENTER))
        self.assertFalse(recent_path(self.home).exists())  # sent, not yet answered
        answer(app, client, {"key": "model", "value": "claude-opus-5-5", "scope": "session"})
        self.assertEqual(self.stored(), [OPUS])

    def test_a_deferred_or_guarded_switch_records_nothing(self) -> None:
        for result in (
            {"key": "model", "value": "claude-opus-5-5", "deferred": True},
            {"key": "model", "value": "", "confirm_required": True, "confirm_message": "Opus costs 5x."},
        ):
            with self.subTest(result=result):
                recent_path(self.home).unlink(missing_ok=True)
                app, client = self.app()
                self.switch(app, client, *OPUS, result=result)
                self.assertFalse(recent_path(self.home).exists())

    def test_a_refused_switch_records_nothing(self) -> None:
        app, client = self.app()
        send(app, "/model claude-opus-5-5 --provider anthropic")
        answer(app, client, None, {"code": 4002, "message": "unknown model"})
        self.assertFalse(recent_path(self.home).exists())

    def test_the_model_hermes_confirmed_is_recorded_not_the_alias_sent(self) -> None:
        app, client = self.app()
        self.switch(app, client, "sonnet", "anthropic", result={"key": "model", "value": "claude-sonnet-4-6"})
        self.assertEqual(app.model, "claude-sonnet-4-6")
        self.assertEqual(self.stored(), [("claude-sonnet-4-6", "anthropic")])

    def test_a_switch_naming_no_provider_records_the_provider_hermes_confirmed(self) -> None:
        app, client = self.app()
        send(app, "/model opus")
        # Hermes' stdio entry announces the switched session (`session.info`) before it answers the call.
        app._on_event(Event("session.info", SID, {"model": "claude-opus-5-5", "provider": "anthropic"}))
        answer(app, client, {"key": "model", "value": "claude-opus-5-5", "scope": "session"})
        self.assertIn("This session now runs claude-opus-5-5.", notices(app))
        self.assertEqual(self.stored(), [OPUS])

    def test_a_second_switch_sent_before_the_first_answer_keeps_the_first_route(self) -> None:
        # Review round 2: /model opus, its session.info, then /model sonnet before opus' answer; Hermes' real order.
        app, client = self.app()
        send(app, "/model opus")
        first = len(client.calls)
        app._on_event(Event("session.info", SID, {"model": "claude-opus-5-5", "provider": "anthropic"}))
        send(app, "/model sonnet")
        self.assertEqual([name for name, _ in client.calls[first - 1:]], ["config.set", "config.set"])
        app._on_response(Response(first, {"key": "model", "value": "claude-opus-5-5", "scope": "session"}, None))
        app._on_event(Event("session.info", SID, {"model": "claude-sonnet-4-6", "provider": "anthropic"}))
        answer(app, client, {"key": "model", "value": "claude-sonnet-4-6", "scope": "session"})
        self.assertEqual(self.stored(), [("claude-sonnet-4-6", "anthropic"), OPUS])

    def test_switching_to_the_model_already_running_reads_its_fresh_info(self) -> None:
        app, client = self.app()
        app._on_event(Event("session.info", SID, {"model": "claude-opus-5-5", "provider": "anthropic"}))
        send(app, "/model claude-opus-5-5")
        app._on_event(Event("session.info", SID, {"model": "claude-opus-5-5", "provider": "anthropic"}))
        answer(app, client, {"key": "model", "value": "claude-opus-5-5", "scope": "session"})
        self.assertEqual(self.stored(), [OPUS])

    def test_the_provider_in_hermes_answer_wins_over_the_one_sent(self) -> None:
        app, client = self.app()
        self.switch(app, client, "opus", "claude", result={"key": "model", "value": "claude-opus-5-5",
                                                            "provider": "anthropic"})  # the shared owner's answer
        self.assertEqual(self.stored(), [OPUS])

    def test_a_switch_hermes_names_no_provider_for_records_nothing(self) -> None:
        app, client = self.app()
        # Said before the switch went out: it is the session's old route, not what Hermes confirmed for this one.
        app._on_event(Event("session.info", SID, {"model": "claude-opus-5-5", "provider": "openrouter"}))
        send(app, "/model claude-opus-5-5")
        app._on_event(Event("session.info", SID, {"model": "claude-fable-5", "provider": "anthropic"}))  # not this model
        answer(app, client, {"key": "model", "value": "claude-opus-5-5", "scope": "session"})
        self.assertIn("This session now runs claude-opus-5-5.", notices(app))
        self.assertFalse(recent_path(self.home).exists())

    def test_without_an_omh_home_nothing_is_written(self) -> None:
        app, client = make_app()
        self.switch(app, client, *OPUS)
        self.assertEqual(app.model, "claude-opus-5-5")
        self.assertFalse(recent_path(self.home).exists())
        self.assertFalse(self.home.exists())

    def test_the_store_skips_what_is_not_two_plain_words(self) -> None:
        self.assertFalse(record_recent(self.home, "x --global", "anthropic"))
        self.assertFalse(record_recent(self.home, "m", ""))
        self.assertFalse(recent_path(self.home).exists())
        recent_path(self.home).parent.mkdir(parents=True, exist_ok=True)
        recent_path(self.home).write_text(json.dumps({"schema_version": RECENT_SCHEMA, "models": [
            {"model": "ok", "provider": "p"}, {"model": "--global", "provider": "p"}, "junk", {"model": "ok", "provider": "p"},
        ]}), encoding="utf-8")
        self.assertEqual(read_recent(self.home), [("ok", "p")])


class PickerTests(HomeTests):
    def write(self, pairs: list[tuple[str, str]]) -> None:
        recent_path(self.home).parent.mkdir(parents=True, exist_ok=True)
        recent_path(self.home).write_text(json.dumps({"schema_version": RECENT_SCHEMA, "models": [
            {"model": model, "provider": provider} for model, provider in pairs]}), encoding="utf-8")

    def opened(self) -> ModelPicker:
        app, client = self.app()
        send(app, "/model")
        self.assertEqual(client.calls, [("model.options", {"session_id": SID})])
        answer(app, client, OPTIONS)
        picker = app.model_picker
        assert picker is not None
        return picker

    def test_recent_rows_come_first_under_their_heading_and_a_stale_one_is_skipped(self) -> None:
        self.write([FABLE, ("gone-model", "anthropic"), OPUS])
        picker = self.opened()
        everything = model_rows(OPTIONS)
        shown = picker.visible()
        self.assertEqual([(row.model, row.provider) for row in shown[:2]], [FABLE, OPUS])
        self.assertEqual(shown[2:], everything)  # the whole list after, unchanged
        rows = lines_text(picker.lines(100, DEFAULT_THEME, len(shown) + 6))
        self.assertEqual(rows[2].strip(), RECENT_GROUP)
        self.assertIn("claude-fable-5", rows[3])
        self.assertIn("claude-opus-5-5", rows[4])
        self.assertEqual(rows[5].strip(), ALL_GROUP)
        self.assertNotIn("gone-model", "\n".join(rows))

    def test_enter_on_a_recent_row_switches_to_it(self) -> None:
        self.write([OPUS])
        picker = self.opened()
        picker.index = 0
        action = picker.handle_key(Key(ENTER))
        assert action is not None and action.row is not None
        self.assertEqual(action.row.arg, "claude-opus-5-5 --provider anthropic --session")

    def test_a_typed_filter_shows_no_recent_group(self) -> None:
        self.write([OPUS])
        picker = self.opened()
        for char in "opus-5-5":
            picker.handle_key(Key(CHAR, char))
        self.assertEqual([(row.model, row.provider) for row in picker.visible()], [OPUS])  # once, not twice
        rows = lines_text(picker.lines(100, DEFAULT_THEME, 20))
        self.assertFalse(any(row.strip() in (RECENT_GROUP, ALL_GROUP) for row in rows), rows)

    def test_a_corrupt_or_foreign_file_shows_no_group_and_no_error(self) -> None:
        for text in ("{not json", "[" * 100_000, json.dumps({"schema_version": "other/v1", "models": []}), "[]"):
            with self.subTest(text=text[:20]):
                recent_path(self.home).parent.mkdir(parents=True, exist_ok=True)
                recent_path(self.home).write_text(text, encoding="utf-8")
                app, client = self.app()
                send(app, "/model")
                answer(app, client, OPTIONS)
                picker = app.model_picker
                assert picker is not None
                self.assertEqual(picker.visible(), model_rows(OPTIONS))
                rows = lines_text(picker.lines(100, DEFAULT_THEME, 20))
                self.assertFalse(any(row.strip() == RECENT_GROUP for row in rows), rows)
                self.assertEqual(notices(app), [])

    def test_no_recent_file_and_no_omh_home_show_no_group(self) -> None:
        picker = self.opened()
        self.assertEqual(picker.visible(), model_rows(OPTIONS))
        app, client = make_app()
        send(app, "/model")
        answer(app, client, OPTIONS)
        assert app.model_picker is not None
        self.assertEqual(app.model_picker.recent, [])
        self.assertFalse(self.home.exists())


if __name__ == "__main__":
    unittest.main()

"""The OMH TUI's declared slice of Hermes' gateway protocol."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest

from omh.tui import gateway_contract as contract


class ServerRequestTreatmentTests(unittest.TestCase):
    def test_every_server_request_hermes_advertises_has_a_treatment(self) -> None:
        # The 13 names `client.capabilities` returned from Hermes 6c61c3e27d.
        advertised = {
            "approval", "clarify", "display.install.sudo", "preview.act", "preview.read", "secret", "sudo",
            "terminal.read", "tour", "vault.code", "vault.save_login", "vault.unlock_prompt", "window.read",
        }
        self.assertEqual(set(contract.SERVER_REQUESTS), advertised)

    def test_approval_is_declined_with_an_explicit_deny(self) -> None:
        # An error answer withdraws an approval instead of denying it.
        decline = contract.server_request_treatment("approval").decline
        self.assertEqual(decline, {"result": {"choice": "deny"}})

    def test_clarify_decline_carries_no_answers(self) -> None:
        self.assertEqual(contract.server_request_treatment("clarify").decline, {"result": {}})

    def test_secret_prompts_are_masked(self) -> None:
        for method in ("sudo", "secret"):
            with self.subTest(method=method):
                self.assertTrue(contract.server_request_treatment(method).masked)
        self.assertFalse(contract.server_request_treatment("approval").masked)

    def test_an_unknown_request_is_answered_unsupported_not_ignored(self) -> None:
        treatment = contract.server_request_treatment("future.request")
        self.assertFalse(treatment.shown)
        self.assertEqual(treatment.decline["error"]["code"], contract.METHOD_NOT_FOUND)


class ClientMethodTests(unittest.TestCase):
    def test_undeclared_params_names_only_the_extra_keys(self) -> None:
        self.assertEqual(contract.undeclared_params("session.create", {"cols": 80, "cwd": "/w"}), [])
        self.assertEqual(contract.undeclared_params("session.create", {"cols": 80, "title": "x"}), ["title"])

    def test_every_declared_method_is_one_the_tui_calls(self) -> None:
        # CLIENT_METHODS is "the methods the TUI calls": each name appears as a literal in a TUI module.
        modules = [path for path in Path(contract.__file__).parent.glob("*.py") if path.name != "gateway_contract.py"]
        literals = {
            node.value
            for path in modules
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertEqual(sorted(set(contract.CLIENT_METHODS) - literals), [])

    def test_the_two_calls_this_phase_adds_carry_exactly_what_hermes_names(self) -> None:
        # Read from Hermes 6c61c3e27d's registry (tui_gateway/contracts/): ConfigSetParams is key, value,
        # session_id, scope, confirm_expensive_model, profile; SessionCorrectionParams is session_id, text, profile.
        # `confirm_expensive_model` goes only with a model the person said to switch to anyway.
        self.assertEqual(contract.CLIENT_METHODS["config.set"], {"key", "value", "session_id", "confirm_expensive_model"})
        self.assertEqual(contract.CLIENT_METHODS["session.steer"], {"session_id", "text"})
        self.assertEqual(contract.CLIENT_METHODS["session.redirect"], {"session_id", "text"})  # same params model
        self.assertEqual(set(contract.CONFIG_SET_VALUES), {"yolo", "reasoning"})
        self.assertEqual(contract.CONFIG_SET_VALUES["yolo"], {"on", "off"})
        # hermes_constants.VALID_REASONING_EFFORTS in 6c61c3e27d, plus none (parse_reasoning_effort: thinking off).
        self.assertEqual(
            contract.REASONING_LEVELS, ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
        )
        self.assertEqual(contract.CONFIG_SET_VALUES["reasoning"], set(contract.REASONING_LEVELS))

    def test_a_config_set_is_sendable_only_for_one_session_with_an_explicit_value(self) -> None:
        good = {"key": "yolo", "value": "on", "session_id": "live-1"}
        self.assertEqual(contract.call_problem("config.set", good), "")
        self.assertEqual(contract.call_problem("config.set", {**good, "key": "reasoning", "value": "high"}), "")
        refused = {
            "a scope": {**good, "scope": "global"},
            "a session scope too": {**good, "scope": "session"},
            "no session id": {"key": "yolo", "value": "on"},
            "an empty session id": {**good, "session_id": ""},
            "a null session id": {**good, "session_id": None},
            "no value (a toggle)": {"key": "yolo", "session_id": "live-1"},
            "an empty value": {**good, "value": ""},
            "a bool value": {**good, "value": True},
            "a yolo word Hermes also reads": {**good, "value": "1"},
            "an effort as a yolo value": {**good, "value": "high"},
            "another key": {**good, "key": "approvals.mode", "value": "off"},
            # A model value that could widen the switch: `--global` writes every new session's default.
            "the model key with --global": {**good, "key": "model", "value": "x --global"},
            "no key": {"value": "on", "session_id": "live-1"},
        }
        for name, params in refused.items():
            with self.subTest(name):
                self.assertNotEqual(contract.call_problem("config.set", params), "")

    def test_a_rewind_is_sendable_only_with_both_truncation_keys_as_hermes_requires(self) -> None:
        # PromptSubmitParams in Hermes 6c61c3e27d's contracts/prompt_voice.py; the recorded refusal (4029) of the
        # first call below and the recorded rewind of the second are in tests/fixtures/tui_gateway/parity.jsonl.
        recorded = [
            row["frame"]["params"]
            for row in recorded_rows("parity", "unconfirmed_truncate", "rewind_turn")
            if row["dir"] == "out" and row["frame"].get("method") == "prompt.submit"
        ]
        unconfirmed, confirmed = recorded
        self.assertEqual(contract.call_problem("prompt.submit", confirmed), "")
        self.assertIn("confirm_truncate", contract.call_problem("prompt.submit", unconfirmed))
        base = {"session_id": "live-1", "text": "again"}
        refused = {
            "a confirmation alone": {**base, "confirm_truncate": True},
            "a false confirmation": {**base, "truncate_before_row_id": 7, "confirm_truncate": False},
            "a row id that is no int": {**base, "truncate_before_row_id": "7", "confirm_truncate": True},
            "a row id that is a bool": {**base, "truncate_before_row_id": True, "confirm_truncate": True},
            "the ordinal form": {**base, "truncate_before_user_ordinal": 1, "confirm_truncate": True},
        }
        for name, params in refused.items():
            with self.subTest(name):
                self.assertNotEqual(contract.call_problem("prompt.submit", params), "")
        self.assertEqual(contract.call_problem("prompt.submit", base), "")
        self.assertEqual(contract.CLIENT_METHODS["session.history"], {"session_id"})

    def test_a_reasoning_config_set_takes_effort_levels_only(self) -> None:
        # Under the same key Hermes reads these as display settings and writes them to config.yaml.
        effort = {"key": "reasoning", "session_id": "live-1"}
        for level in contract.REASONING_LEVELS:
            with self.subTest(level=level):
                self.assertEqual(contract.call_problem("config.set", {**effort, "value": level}), "")
        for word in ("show", "hide", "on", "off", "full", "all", "clamp", "collapse", "short", "HIGH", "", "hgih"):
            with self.subTest(word=word):
                self.assertNotEqual(contract.call_problem("config.set", {**effort, "value": word}), "")
        self.assertNotEqual(contract.call_problem("config.set", {"key": "reasoning", "value": "high"}), "")

    def test_call_problem_names_undeclared_keys_for_every_method(self) -> None:
        self.assertEqual(contract.call_problem("session.create", {"cols": 80, "cwd": "/w"}), "")
        self.assertIn("title", contract.call_problem("session.create", {"cols": 80, "title": "x"}))
        self.assertIn("scope", contract.call_problem("config.set", {"key": "yolo", "scope": "global"}))
        self.assertEqual(contract.call_problem("session.steer", {"session_id": "live-1", "text": "x"}), "")

    def test_every_key_of_an_undeclared_method_is_undeclared(self) -> None:
        self.assertEqual(contract.undeclared_params("voice.toggle", {"on": True}), ["on"])

    def test_only_the_calls_a_session_does_without_are_optional(self) -> None:
        optional = {"commands.catalog", "config.get", "model.options", "session.list", "skills.reload"}
        self.assertEqual(contract.OPTIONAL_METHODS, optional)
        self.assertLessEqual(contract.OPTIONAL_METHODS, set(contract.CLIENT_METHODS))

    def test_drift_errors_are_param_rejection_and_unknown_method_only(self) -> None:
        self.assertTrue(contract.is_drift_error({"code": 4000, "message": "extra fields"}))
        self.assertTrue(contract.is_drift_error({"code": -32601, "message": "unknown method"}))
        self.assertFalse(contract.is_drift_error({"code": 4090, "message": "lease"}))
        self.assertFalse(contract.is_drift_error("unknown method"))


TUI_DIR = Path(contract.__file__).parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "tui_gateway"


# `panels` reads OMH's own HUD snapshot (`read_omh_hud`), never a gateway frame: its `yolo` and `queued` are OMH's.
NOT_GATEWAY_READERS = frozenset({"gateway_contract.py", "panels.py"})


def tui_modules() -> dict[str, ast.Module]:
    """Every TUI module that reads what the gateway sends, parsed."""
    return {
        path.name: ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(TUI_DIR.glob("*.py"))
        if path.name not in NOT_GATEWAY_READERS
    }


def recorded_rows(name: str, *segments: str) -> list[dict]:
    """The rows of the named segments of a recorded fixture, in order."""
    lines = (FIXTURES / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    header, rows = json.loads(lines[0])["fixture"], [json.loads(line) for line in lines[1:]]
    return [row for segment in segments for row in rows[slice(*header["segments"][segment])]]


def recorded_events(name: str) -> list[tuple[str, dict]]:
    """(type, payload) of every event a recorded fixture holds, whichever of the two row shapes it uses."""
    lines = (FIXTURES / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()[1:]
    events = []
    for row in map(json.loads, lines):
        params = row.get("frame", {}).get("params", {}) if "frame" in row else row
        if row.get("dir", "in") == "in" and isinstance(params.get("type"), str):
            events.append((params["type"], params.get("payload", {})))
    return events


class InboundTests(unittest.TestCase):
    """The names, fields and values the TUI keys on in what Hermes sends, declared once."""

    def test_the_declared_shapes_are_the_ones_hermes_names(self) -> None:
        # Read from Hermes 6c61c3e27d's registry (tui_gateway/contracts/): the six event(...) calls for
        # SubagentEventPayload in events.py, CorrectionStatus in sessions.py, SubagentTailResult's fields in
        # profiles_vault_complete_foreign_subagents.py, and SessionLiveInfo's yolo and reasoning_effort in common.py.
        self.assertEqual(
            contract.SUBAGENT_EVENTS,
            ("subagent.spawn_requested", "subagent.start", "subagent.progress", "subagent.thinking", "subagent.tool",
             "subagent.complete"),
        )
        self.assertTrue(all(name.startswith(contract.SUBAGENT_EVENT_PREFIX) for name in contract.SUBAGENT_EVENTS))
        self.assertEqual(contract.STEER_STATUSES, {"queued", "redirected", "rejected"})
        self.assertLessEqual({contract.STEER_QUEUED, contract.STEER_REJECTED}, contract.STEER_STATUSES)
        tail_result = {"subagent_id", "available", "text", "truncated"}
        self.assertLessEqual({contract.TAIL_AVAILABLE, contract.TAIL_TEXT, contract.TAIL_TRUNCATED}, tail_result)
        self.assertEqual((contract.SESSION_INFO_YOLO, contract.SESSION_INFO_REASONING_EFFORT), ("yolo", "reasoning_effort"))

    def test_recorded_frames_carry_the_declared_shapes(self) -> None:
        relayed = recorded_events("subagent_relay")
        self.assertTrue(relayed)
        for event_type, _payload in relayed:
            with self.subTest(event_type=event_type):
                self.assertIn(event_type, contract.SUBAGENT_EVENTS)
        infos = [payload for name in ("session", "approval") for kind, payload in recorded_events(name) if kind == "session.info"]
        self.assertTrue(infos)
        for payload in infos:
            self.assertIsInstance(payload[contract.SESSION_INFO_YOLO], bool)
            self.assertIsInstance(payload[contract.SESSION_INFO_REASONING_EFFORT], str)

    def test_notifications_are_the_apps_and_carry_the_declared_fields(self) -> None:
        # NotificationShowPayload / NotificationClearPayload in Hermes 6c61c3e27d's contracts/events.py; the frames
        # are derived from the source that builds them (tests/fixtures/tui_gateway/notifications.jsonl's header).
        self.assertLessEqual({"notification.show", "notification.clear"}, set(contract.APP_EVENTS))
        self.assertEqual(contract.NOTIFICATION_LEVELS, {"info", "warn", "error", "success"})
        frames = recorded_events("notifications")
        self.assertEqual({kind for kind, _payload in frames}, {"notification.show", "notification.clear"})
        for kind, payload in frames:
            with self.subTest(kind=kind, payload=payload):
                self.assertIsInstance(payload[contract.NOTIFICATION_KEY], str)
                if kind == "notification.show":
                    self.assertIsInstance(payload[contract.NOTIFICATION_TEXT], str)
                    self.assertIn(payload[contract.NOTIFICATION_LEVEL], contract.NOTIFICATION_LEVELS)
                    ttl = payload[contract.NOTIFICATION_TTL_MS]
                    self.assertTrue(ttl is None or isinstance(ttl, int))
                    self.assertEqual(ttl is not None, payload[contract.NOTIFICATION_KIND] == contract.NOTIFICATION_TTL_KIND)

    def test_the_roster_folds_exactly_the_declared_subagent_events(self) -> None:
        from omh.tui.subagents import Roster

        self.assertEqual(set(Roster()._handlers), set(contract.SUBAGENT_EVENTS))

    def test_the_transcript_folds_exactly_the_declared_transcript_events(self) -> None:
        from omh.tui.transcript import Transcript

        self.assertEqual(set(Transcript()._handlers), set(contract.TRANSCRIPT_EVENTS))

    def test_the_app_takes_exactly_the_declared_app_events_and_hands_every_other_type_on(self) -> None:
        from test_tui_modes import SID, make_app
        from omh.tui.gateway import Event

        for event_type in sorted(contract.HANDLED_EVENTS | contract.UNREAD_EVENTS | {"message.finished"}):
            with self.subTest(event_type=event_type):
                app, _client = make_app(busy=True)
                folded: list[str] = []
                app.transcript.apply = lambda event: folded.append(event.type)  # type: ignore[method-assign]
                app.roster.apply = lambda kind, payload, now: folded.append(kind)  # type: ignore[method-assign]
                app._on_event(Event(event_type, SID, {}))
                self.assertEqual(folded == [], event_type in contract.APP_EVENTS)

    def test_every_event_type_is_declared_once_and_every_recorded_one_is_declared(self) -> None:
        # 77: `len(tui_gateway.contracts.registry.EVENTS)` in Hermes 6c61c3e27d, plus the two newer ones the app takes
        # (`skills.changed`, `session.replay_gap`).
        self.assertEqual(contract.HANDLED_EVENTS & contract.UNREAD_EVENTS, frozenset())
        self.assertEqual(len(contract.HANDLED_EVENTS | contract.UNREAD_EVENTS), 77 + 2)
        recorded = {
            kind
            for name in ("session", "approval", "subagent_relay", "notifications", "parity")
            for kind, _payload in recorded_events(name)
        }
        self.assertLessEqual(recorded, contract.HANDLED_EVENTS | contract.UNREAD_EVENTS)

    def test_the_tui_reads_these_shapes_through_the_contract_only(self) -> None:
        fields = {
            contract.SESSION_INFO_YOLO, contract.SESSION_INFO_REASONING_EFFORT, contract.TAIL_AVAILABLE, contract.TAIL_TRUNCATED,
        }
        for name, module in tui_modules().items():
            for node in ast.walk(module):
                with self.subTest(module=name, line=getattr(node, "lineno", 0)):
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        # A subagent name written out is a method the TUI calls, never an event it reads.
                        if node.value.startswith(contract.SUBAGENT_EVENT_PREFIX):
                            self.assertIn(node.value, contract.CLIENT_METHODS)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
                        literal = node.args[0] if node.args and isinstance(node.args[0], ast.Constant) else None
                        self.assertNotIn(getattr(literal, "value", None), fields)
                    if isinstance(node, ast.Compare):
                        compared = [part for part in (node.left, *node.comparators) if isinstance(part, ast.Constant)]
                        self.assertFalse({part.value for part in compared} & contract.STEER_STATUSES)
        (on_tail,) = [
            node for node in ast.walk(tui_modules()["agent_view.py"])
            if isinstance(node, ast.FunctionDef) and node.name == "_on_tail"
        ]
        literal_gets = [
            node.args[0].value
            for node in ast.walk(on_tail)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
            and node.args and isinstance(node.args[0], ast.Constant)
        ]
        self.assertEqual(literal_gets, [])  # `text` too: it is the tail's own field, read by its declared name


def recorded_turns(name: str) -> list[list[tuple[str, dict]]]:
    """The events of each submitted turn in a recorded session: those after one `prompt.submit` until the next."""
    lines = (FIXTURES / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()[1:]
    turns: list[list[tuple[str, dict]]] = []
    for row in map(json.loads, lines):
        frame = row["frame"]
        if row["dir"] == "out" and frame.get("method") == "prompt.submit":
            turns.append([])
        elif turns and row["dir"] == "in" and frame.get("method") == "event":
            turns[-1].append((frame["params"]["type"], frame["params"].get("payload", {})))
    return turns


class TurnDriftNoticeTests(unittest.TestCase):
    """A submitted turn that brings no event the TUI shows, only undeclared types, says so once."""

    RENAMED = ["message.begin", "message.chunk", "message.chunk", "message.chunk", "message.end"]

    def run_turn(self, events: list[tuple[str, dict]], app=None):
        from test_tui_modes import SID, make_app
        from omh.tui.gateway import Event

        if app is None:
            app, _client = make_app()
        app._send_prompt("go")
        for event_type, payload in events:
            app._on_event(Event(event_type, SID, payload))
        return app

    def drift_notices(self, app) -> list[str]:
        from test_tui_modes import notices
        from omh.tui.transcript import NOTICE_WARN

        return [text for text in notices(app, NOTICE_WARN) if "`omh doctor`" in text]

    def test_no_recorded_turn_shows_it(self) -> None:
        turns = [*recorded_turns("session"), *recorded_turns("approval"), recorded_events("subagent_relay")]
        self.assertEqual(len(turns), 6)
        for index, turn in enumerate(turns):
            with self.subTest(turn=index):
                self.assertTrue(turn)
                self.assertEqual(self.drift_notices(self.run_turn(turn)), [])

    def test_one_unknown_event_among_known_ones_says_nothing_wherever_it_comes(self) -> None:
        turn = recorded_turns("session")[0]
        for position in (0, 1, 2, len(turn)):
            with self.subTest(position=position):
                events = [*turn[:position], ("message.queued", {}), *turn[position:]]
                self.assertEqual(self.drift_notices(self.run_turn(events)), [])

    def test_declared_types_the_tui_does_not_show_never_count(self) -> None:
        events = [("session.info", {}), ("session.title", {}), ("todo.updated", {}), ("notice", {})] * 3
        self.assertEqual(self.drift_notices(self.run_turn(events)), [])

    def test_a_turn_of_renamed_events_says_so_once_naming_them_even_after_session_info(self) -> None:
        app = self.run_turn([("session.info", {}), ("session.title", {}), *[(name, {}) for name in self.RENAMED]])
        (notice,) = self.drift_notices(app)
        self.assertIn("(message.begin, message.chunk)", notice)
        self.assertIn("Esc interrupts the turn", notice)

    def test_types_already_named_say_nothing_on_a_later_turn_and_a_new_type_does(self) -> None:
        # A Hermes that streams the same new type ahead of every turn names it once, not on every turn.
        app = self.run_turn([(name, {}) for name in self.RENAMED])
        app.turn_pending = False  # the person interrupted it; nothing Hermes sent ended it
        self.run_turn([(name, {}) for name in self.RENAMED], app)
        self.assertEqual(len(self.drift_notices(app)), 1)
        app.turn_pending = False
        self.run_turn([("message.begin", {}), ("message.chunk", {}), ("message.flush", {})], app)
        (_first, second) = self.drift_notices(app)
        self.assertIn("(message.begin, message.chunk, message.flush)", second)

    def test_the_count_starts_again_with_each_turn(self) -> None:
        app = self.run_turn([("message.begin", {}), ("message.begin", {})])
        app.turn_pending = False
        self.run_turn([("message.chunk", {}), ("message.chunk", {})], app)
        self.assertEqual(self.drift_notices(app), [])

    def test_a_session_change_ends_the_watch(self) -> None:
        # The new session's turn is running, so only `_adopt_session` can end the old turn's watch.
        app = self.run_turn([("message.begin", {}), ("message.chunk", {})])
        app._adopt_session({"session_id": "live-2", "running": True, "info": {}})
        from omh.tui.gateway import Event

        app._on_event(Event("message.chunk", "live-2", {}))
        self.assertEqual(self.drift_notices(app), [])

    def test_a_refused_submit_ends_the_watch(self) -> None:
        from test_tui_modes import SID, answer, make_app
        from omh.tui.gateway import Event

        app, client = make_app()
        app._send_prompt("go")
        answer(app, client, error={"code": 5009, "message": "session busy"})
        for name in self.RENAMED:
            app._on_event(Event(name, SID, {}))
        self.assertEqual(self.drift_notices(app), [])


if __name__ == "__main__":
    unittest.main()

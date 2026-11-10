"""Claude Code's command names, where Hermes has the command under another name or not at all.

`/cost` runs Hermes' `/usage` and `/permissions` its `/approvals`, under the
echo of the name typed. `/todos` prints this session's whole plan. Bare
`/model` (or `/model --refresh`) opens a picker of the models Hermes offers
(`model.options`) and switches this session to the one picked with
`config.set model` `<name> --provider <slug> --session`, as `/model <name>
[--provider <slug>]` does; any other flag goes to Hermes' `/model` as typed.
`/export` first says what Hermes exports (a profile archive, not this
transcript) and runs on the second try. Answers are the recorded Hermes
6c61c3e27d frames in `tests/fixtures/tui_gateway/parity.jsonl`.
"""

from __future__ import annotations

from collections import deque
import unittest

from _tui_lines import lines_text
from test_tui_gateway_contract import recorded_rows
from test_tui_modes import SID, answer, drawn, make_app, notices, type_text
from test_tui_panels import hud_payload
from omh.tui import app as app_module
from omh.tui import gateway_contract as contract
from omh.tui import slash
from omh.tui.app import MODEL_OPTIONS_REFUSED, PLACEHOLDER, REFUSAL_SENTENCES, SLOT_ARM_SECONDS, App
from omh.tui.gateway import Event, Response
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, Key
from omh.tui.model_picker import CLOSE, PICK, ModelPicker, model_rows
from omh.tui.panels import HudSnapshot, plan_text
from omh.tui.theme import DEFAULT_THEME
from omh.tui.transcript import NOTICE_INFO, NOTICE_WARN, CommandBlock


def recorded(segment: str) -> tuple[dict, dict]:
    """The recorded call's params and its result."""
    rows = recorded_rows("parity", segment)
    call = next(row["frame"] for row in rows if row["dir"] == "out")
    reply = next(row["frame"] for row in rows if row["dir"] == "in")
    return call["params"], reply["result"]


OPTIONS_PARAMS, OPTIONS = recorded("model_options")


def send(app: App, text: str) -> None:
    type_text(app, text)
    app._on_input(Key(ENTER))


def answer_call(app: App, client: object, method: str, result: dict | None = None, error: dict | None = None) -> None:
    """Answer the newest call of `method` (a call's id is its place in `client.calls`, from 1)."""
    request_id = max(number for number, (name, _params) in enumerate(client.calls, 1) if name == method)
    app._on_response(Response(request_id, result, error))


def sent(client: object, method: str) -> list[dict]:
    return [params for name, params in client.calls if name == method]


def commands(app: App) -> list[str]:
    return [block.command for block in app.transcript.blocks if isinstance(block, CommandBlock)]


class RenamedCommandTests(unittest.TestCase):
    def test_claude_codes_names_run_hermes_commands_under_the_name_typed(self) -> None:
        for typed, sent in (("/cost", "usage"), ("/permissions smart", "approvals smart")):
            with self.subTest(typed=typed):
                app, client = make_app()
                send(app, typed)
                self.assertEqual(client.calls, [("slash.exec", {"command": sent, "session_id": SID})])
                self.assertEqual(commands(app), [typed])
                answer(app, client, {"output": "Session cost: $0.01"})
                self.assertEqual(app.transcript.blocks[-1].parts, [("Session cost: $0.01", NOTICE_INFO)])

    def test_the_menu_offers_them_and_says_which_hermes_command_runs(self) -> None:
        offered = {completion.name: completion.summary for completion in slash.completions("")}
        self.assertIn("/usage", offered["cost"])
        self.assertIn("/approvals", offered["permissions"])
        for name, target in (("cost", "usage"), ("permissions", "approvals")):
            command = slash.parse_slash(f"/{name}").command
            self.assertEqual((command.route, command.target), (slash.RENAMED, target))


class TodosTests(unittest.TestCase):
    ITEMS = [
        {"text": "Read the router", "state": "done", "phase": "Survey"},
        {"text": "Split chat.py", "state": "active", "phase": "Change"},
        {"text": "Move the helpers", "state": "pending", "phase": "Change", "depth": 1},
        {"text": "Run the suite", "state": "pending", "phase": "Change"},
    ]

    def test_the_whole_plan_prints_under_the_echo(self) -> None:
        app, client = make_app()
        app.hud = HudSnapshot("stored", hud_payload(self.ITEMS, title="Router split"), 0.0)
        send(app, "/todos")
        self.assertEqual(client.calls, [])
        (block,) = [block for block in app.transcript.blocks if isinstance(block, CommandBlock)]
        self.assertEqual(block.command, "/todos")
        self.assertEqual(
            block.parts[0][0].split("\n"),
            [
                "[Plan] Router split │ 1/4",  # the panel's own header
                "Survey",
                "  [✓] Read the router",
                "Change",
                "  [•] Split chat.py",
                "    [ ] Move the helpers",
                "  [ ] Run the suite",
            ],
        )

    def test_no_plan_says_so(self) -> None:
        self.assertEqual(plan_text(None), "")
        self.assertEqual(plan_text(hud_payload()), "")
        app, _client = make_app()
        send(app, "/todos")
        self.assertIn("No plan in this session yet", notices(app)[-1])


class ModelPickerTests(unittest.TestCase):
    def test_the_rows_are_every_providers_models_in_hermes_order(self) -> None:
        listed = {**OPTIONS, "model": "gpt-5.4-mini", "provider": "copilot"}  # a current model a provider lists
        rows = model_rows(listed)
        self.assertEqual(len(rows), sum(len(provider["models"]) for provider in OPTIONS["providers"]))
        self.assertEqual((rows[0].model, rows[0].provider, rows[0].provider_name), ("claude-fable-5.1", "anthropic", "Anthropic"))
        self.assertEqual(rows[2].arg, "claude-opus-5-5 --provider anthropic --session")

    def test_a_name_that_is_not_one_plain_word_is_left_out(self) -> None:
        result = {
            "model": "m",
            "provider": "p",
            "providers": [
                {"slug": "p", "name": "P", "models": ["m", "x --global", "-v", "a\x1b[31mb", "", 3, "ok/model"]},
                {"slug": "--global", "name": "Bad", "models": ["m"]},
                {"slug": "q", "name": "Q\x1b]0;t\x07", "models": "not a list"},
                # Hermes' /model reads a leading U+2012-U+2015 dash before a flag word as `--` (model_switch.py).
                {"slug": "p", "name": "P", "models": [DASH + "global" for DASH in "\u2012\u2013\u2014\u2015\u2010"]},
                {"slug": "\u2014session", "name": "Bad", "models": ["m"]},
                {"slug": "p", "name": "P", "models": ["model\u2014v2"]},  # a dash inside a word stays one word
            ],
        }
        rows = model_rows(result)
        self.assertEqual(
            [(row.model, row.provider, row.current) for row in rows],
            [("m", "p", True), ("ok/model", "p", False), ("model\u2014v2", "p", False)],
        )

    def test_the_current_model_is_marked_and_highlighted_typing_filters_and_esc_closes(self) -> None:
        result = {**OPTIONS, "model": "gpt-5.4-mini", "provider": "copilot"}
        picker = ModelPicker(model_rows(result), current="gpt-5.4-mini")
        rows = lines_text(picker.lines(100, DEFAULT_THEME, 20))
        self.assertIn("now gpt-5.4-mini", rows[0])
        highlighted = [row for row in rows[1:] if row.lstrip("❯ ").startswith("●")]
        self.assertEqual(len(highlighted), 1)
        self.assertIn("gpt-5.4-mini", highlighted[0])
        self.assertEqual(picker.handle_key(Key(ENTER)).row.model, "gpt-5.4-mini")
        picker = ModelPicker(model_rows(OPTIONS), current=OPTIONS["model"])
        for char in "opus-5-5":
            picker.handle_key(Key(CHAR, char))
        action = picker.handle_key(Key(ENTER))
        self.assertEqual((action.kind, action.row.provider), (PICK, "anthropic"))
        self.assertEqual(ModelPicker(model_rows(OPTIONS), current="").handle_key(Key(ESCAPE)).kind, CLOSE)


class ModelCommandTests(unittest.TestCase):
    def opened(self) -> tuple[App, object]:
        app, client = make_app()
        send(app, "/model")
        self.assertEqual(client.calls, [("model.options", {"session_id": SID})])  # the keys the recording sent
        answer(app, client, OPTIONS)
        self.assertIsNotNone(app.model_picker)
        screen = drawn(app)
        self.assertTrue(any(line.startswith(" Model (") for line in screen), screen)  # in the slot, over the composer
        self.assertFalse(any(PLACEHOLDER in line for line in screen), screen)  # the picker has the keys, not the composer
        return app, client

    def test_bare_model_lists_hermes_models_and_the_pick_switches_this_session(self) -> None:
        app, client = self.opened()
        for char in "opus-5-5":
            app._on_input(Key(CHAR, char))
        app._on_input(Key(ENTER))
        self.assertIsNone(app.model_picker)
        value = "claude-opus-5-5 --provider anthropic --session"
        self.assertEqual(client.calls[-1], ("config.set", {"key": "model", "value": value, "session_id": SID}))
        self.assertEqual(commands(app), ["/model claude-opus-5-5"])  # one echo, the pick's, as the row names it
        answer(app, client, {"key": "model", "value": "claude-opus-5-5", "scope": "session"})
        self.assertEqual(app.model, "claude-opus-5-5")
        self.assertIn("This session now runs claude-opus-5-5.", notices(app))

    def test_esc_closes_the_picker_and_switches_nothing(self) -> None:
        app, client = self.opened()
        calls = len(client.calls)
        app._on_input(Key(ESCAPE))
        self.assertIsNone(app.model_picker)
        self.assertEqual(len(client.calls), calls)
        self.assertEqual(app.composer.text, "")
        self.assertEqual(commands(app), [])  # no `› /model` left standing empty

    def test_model_with_a_name_switches_as_hermes_own_tui_sends_it(self) -> None:
        # `--session` goes only when typed (Ink's `modelValueForConfigSet` sends the arguments as typed), so without
        # it Hermes' stdio entry applies `model.persist_switch_by_default` as its own typed `/model` does.
        cases = (
            ("gpt-5.4 --provider copilot", "gpt-5.4 --provider copilot"),
            ("gpt-5.4 --provider copilot --session", "gpt-5.4 --provider copilot --session"),
            ("gpt-5.4 --session --provider copilot", "gpt-5.4 --provider copilot --session"),
            ("gpt-5.4", "gpt-5.4"),
            ("gpt-5.4 --session", "gpt-5.4 --session"),
        )
        for typed, value in cases:
            with self.subTest(typed=typed):
                app, client = make_app()
                send(app, f"/model {typed}")
                self.assertEqual(client.calls, [("config.set", {"key": "model", "value": value, "session_id": SID})])

    def test_any_other_flag_goes_to_hermes_as_typed(self) -> None:
        for typed in ("gpt-5.4 --global", "gpt-5.4 --once", "--provider copilot", "gpt-5.4 --refresh"):
            with self.subTest(typed=typed):
                app, client = make_app()
                send(app, f"/model {typed}")
                self.assertEqual(client.calls, [("slash.exec", {"command": f"model {typed}", "session_id": SID})])

    def test_model_refresh_opens_the_picker_over_a_list_hermes_asks_for_again(self) -> None:
        app, client = make_app()
        send(app, "/model --refresh")
        self.assertEqual(client.calls, [("model.options", {"session_id": SID, "refresh": True})])
        self.assertEqual(contract.call_problem(*client.calls[0]), "")
        answer(app, client, OPTIONS)
        self.assertIsNotNone(app.model_picker)
        self.assertNotIn("nsupported", "\n".join(notices(app)))

    def test_a_switch_hermes_defers_says_so_and_changes_nothing_shown(self) -> None:
        app, client = make_app()
        app.model = "deepseek-v4.1-flash"
        send(app, "/model claude-opus-5-5")
        answer(app, client, {"key": "model", "value": "claude-opus-5-5", "deferred": True})
        self.assertEqual(app.model, "deepseek-v4.1-flash")
        self.assertIn("This session switches to claude-opus-5-5 when its next turn starts.", notices(app))

    def guarded(self, now: list[float]) -> tuple[App, object]:
        """`/model claude-opus-5-5` answered `confirm_required`: the slot asks, keep first and selected."""
        app, client = make_app(clock=lambda: now[0])
        app.model = FLASH
        send(app, "/model claude-opus-5-5")
        answer(app, client, {"key": "model", "value": "", "confirm_required": True, "confirm_message": "Opus costs 5x."})
        self.assertEqual(app.model, FLASH)
        slot = app.slot
        self.assertIsNotNone(slot)
        self.assertTrue(slot.picking)  # the composer is hidden: only the choices answer it
        (question,) = slot.params["questions"]
        self.assertEqual(question["question"], "Opus costs 5x.\nSwitch this session to claude-opus-5-5?")
        self.assertEqual(question["choices"], [f"Keep {FLASH}", "Switch to claude-opus-5-5 anyway"])
        screen = "\n".join(drawn(app))
        self.assertIn("Switch to claude-opus-5-5 anyway", screen)
        self.assertNotIn("Other (type your answer)", screen)
        self.assertEqual(slot.keys[0], "↑↓ or 1-9 · enter picks · esc cancels")  # nothing to type
        keep = {"result": {"answers": {"confirm": f"Keep {FLASH}"}}}
        self.assertEqual(slot.outcomes(keep), [(True, f"Keep {FLASH}")])  # the choice alone, not Hermes' message again
        now[0] += SLOT_ARM_SECONDS
        return app, client

    def test_a_guarded_model_is_asked_about_and_switch_anyway_sends_the_confirmation(self) -> None:
        now = [100.0]
        app, client = self.guarded(now)
        app._on_input(Key(DOWN))
        app._on_input(Key(DOWN))  # the choices end there: no text field's row
        app._on_input(Key(ENTER))
        self.assertIsNone(app.slot)
        self.assertEqual(client.answers, [])  # the TUI's own question: nothing went to Hermes for it
        confirmed = {"key": "model", "value": "claude-opus-5-5", "session_id": SID, "confirm_expensive_model": True}
        self.assertEqual(client.calls[-1], ("config.set", confirmed))
        answer(app, client, {"key": "model", "value": "claude-opus-5-5"})
        self.assertEqual(app.model, "claude-opus-5-5")

    def test_keep_or_esc_switches_nothing_and_a_late_second_ask_is_reported(self) -> None:
        for key in (Key(ENTER), Key(ESCAPE), Key(CHAR, "x")):
            with self.subTest(key=key):
                now = [100.0]
                app, client = self.guarded(now)
                calls = len(client.calls)
                app._on_input(key)
                if key.name == CHAR:
                    self.assertIsNotNone(app.slot)  # a letter opens no field and answers nothing
                    continue
                self.assertIsNone(app.slot)
                self.assertEqual(len(client.calls), calls)
                self.assertEqual(app.model, FLASH)
                self.assertIn(f"Model not switched: this session stays on {FLASH}.", notices(app))
        now = [100.0]
        app, client = self.guarded(now)
        app._on_input(Key(DOWN))
        app._on_input(Key(ENTER))
        answer(app, client, {"key": "model", "value": "", "confirm_required": True, "confirm_message": "Opus costs 5x."})
        self.assertIsNone(app.slot)  # asked once: a confirmed switch refused again is reported, never re-asked
        self.assertIn("the session changed before the confirmation landed", notices(app, NOTICE_WARN)[-1])

    def test_a_flag_a_shared_gateway_refuses_reads_as_what_to_do_instead(self) -> None:
        app, client = make_app()
        send(app, "/model gpt-5.4 --global")
        answer(app, client, error={"code": 4001, "message": "unsupported_command", "data": {"reason": "unsupported_command"}})
        said = notices(app)[-1]
        self.assertNotIn("unsupported", said.lower())
        self.assertIn("hermes model", said)

    def test_bare_model_waits_in_the_queue_and_opens_the_picker_once_the_turn_ends(self) -> None:
        # A pick switches the session, which Hermes does between turns: the whole command waits for the turn's end.
        app, client = make_app(busy=True)
        send(app, "/model")
        self.assertEqual(client.calls, [])
        self.assertEqual([line.text for line in app.queued], ["/model"])
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertEqual(client.calls[-1], ("model.options", {"session_id": SID}))
        self.assertEqual(app.queued, deque())

    def test_a_queued_guarded_model_holds_the_prompt_behind_it_until_its_confirm_is_settled(self) -> None:
        # #2726 review: the confirm opened after config.set was answered, so the prompt went on the old model.
        now = [100.0]
        app, client = make_app(busy=True, clock=lambda: now[0])
        send(app, "/model claude-opus-5-5")
        send(app, "go on with it")
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertEqual(client.calls[-1][0], "config.set")
        answer(app, client, {"key": "model", "value": "", "confirm_required": True, "confirm_message": "Opus costs 5x."})
        self.assertIsNotNone(app.slot)
        self.assertEqual(client.named("prompt.submit"), [])  # the confirm is open: the prompt waits
        now[0] += SLOT_ARM_SECONDS
        app._on_input(Key(DOWN))
        app._on_input(Key(ENTER))  # switch anyway
        self.assertEqual(client.calls[-1][1].get("confirm_expensive_model"), True)
        self.assertEqual(client.named("prompt.submit"), [])  # the confirmed switch is still out
        answer(app, client, {"key": "model", "value": "claude-opus-5-5"})
        self.assertEqual(app.model, "claude-opus-5-5")
        self.assertEqual(client.named("prompt.submit"), [{"session_id": SID, "text": "go on with it", "queued": True}])

    def test_a_queued_bare_model_holds_the_prompt_through_its_pick_and_the_confirm_it_asks(self) -> None:
        now = [100.0]
        app, client = make_app(busy=True, clock=lambda: now[0])
        send(app, "/model")
        send(app, "go on with it")
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        answer(app, client, OPTIONS)
        self.assertIsNotNone(app.model_picker)
        self.assertEqual(client.named("prompt.submit"), [])  # the picker is open
        for char in "opus-5-5":
            app._on_input(Key(CHAR, char))
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls[-1][0], "config.set")
        app._drain_after_queued_command()  # the loop's step after the pick: the switch it sent is the command's
        self.assertEqual(client.named("prompt.submit"), [])  # the pick's switch is out
        answer(app, client, {"key": "model", "value": "", "confirm_required": True, "confirm_message": "Opus costs 5x."})
        self.assertEqual(client.named("prompt.submit"), [])  # its confirm is open
        now[0] += SLOT_ARM_SECONDS
        app._on_input(Key(ENTER))  # keep the model
        self.assertIsNone(app.slot)
        self.assertEqual(client.named("prompt.submit"), [])
        app._drain_after_queued_command()  # the loop's step after that key: nothing of the command's is left
        self.assertEqual(client.named("prompt.submit"), [{"session_id": SID, "text": "go on with it", "queued": True}])

    def test_a_hermes_without_model_options_costs_the_picker_not_the_session(self) -> None:
        app, client = make_app()
        send(app, "/model")
        answer(app, client, error={"code": -32601, "message": "Method not found"})
        self.assertIsNone(app.exit_code)
        self.assertIsNone(app.model_picker)

    def test_the_contract_declares_model_options_with_the_session_and_refresh(self) -> None:
        self.assertEqual(contract.CLIENT_METHODS["model.options"], {"session_id", "refresh"})
        self.assertEqual(set(OPTIONS_PARAMS), {"session_id"})
        self.assertEqual(contract.call_problem("model.options", OPTIONS_PARAMS), "")
        self.assertIn("model.options", contract.OPTIONAL_METHODS)


FLASH = "deepseek/deepseek-v4.1-flash-ultrafast"
OPUS_SWITCH = "claude-opus-5-5 --provider claude-proxy --session"


class DefaultModelTests(unittest.TestCase):
    """Hermes' configured default model moves while the session runs: the session follows it at a turn's end, once.

    The launch reads the config file's mtime and the default (`model.options`
    naming no session); each turn's end reads the mtime, and the default again
    when the mtime moved. Only a move of the default switches, never a session
    model that differs from it.
    """

    def launched(self, model: str = FLASH, default: tuple[str, str] = (FLASH, "og")) -> tuple[App, object]:
        app, client = make_app()
        app.model = model
        app._read_default()
        self.assertEqual(client.calls, [("config.get", {"key": "mtime"}), ("model.options", {})])
        for method, params in client.calls:
            self.assertEqual(contract.call_problem(method, params), "")
        answer_call(app, client, "config.get", {"mtime": 100.0})
        answer_call(app, client, "model.options", {"model": default[0], "provider": default[1], "providers": []})
        return app, client

    def end_turn(self, app: App, client: object, mtime: float, default: tuple[str, str] | None = None) -> None:
        """A turn ends; Hermes says the config's mtime and, when it is asked again, the default."""
        app.turn_pending = True
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        answer_call(app, client, "config.get", {"mtime": mtime})
        if default is not None:
            answer_call(app, client, "model.options", {"model": default[0], "provider": default[1], "providers": []})

    def test_a_default_moved_during_a_turn_switches_the_session_once_at_its_end(self) -> None:
        app, client = self.launched()
        self.end_turn(app, client, 200.0, ("claude-opus-5-5", "claude-proxy"))
        self.assertEqual(sent(client, "config.set"), [{"key": "model", "value": OPUS_SWITCH, "session_id": SID}])
        answer_call(app, client, "config.set", {"key": "model", "value": "claude-opus-5-5", "scope": "session"})
        self.assertEqual(app.model, "claude-opus-5-5")  # the info line's model
        said = "Hermes' default model is now claude-opus-5-5 (claude-proxy); this session switched to it."
        self.assertEqual(notices(app).count(said), 1)
        self.end_turn(app, client, 200.0)  # nothing moved since: no read, no switch
        self.assertEqual(len(sent(client, "model.options")), 2)
        self.end_turn(app, client, 300.0, ("claude-opus-5-5", "claude-proxy"))  # another edit, same default
        self.assertEqual(len(sent(client, "model.options")), 3)
        self.assertEqual(len(sent(client, "config.set")), 1)

    def test_a_model_picked_with_slash_model_stays_while_the_default_does_not_move(self) -> None:
        app, client = self.launched(model="claude-opus-5-5")  # resumed on another model than the default
        self.end_turn(app, client, 100.0)
        send(app, "/model gpt-5.4 --provider copilot")
        answer_call(app, client, "config.set", {"key": "model", "value": "gpt-5.4", "scope": "session"})
        self.end_turn(app, client, 100.0)
        self.end_turn(app, client, 150.0, (FLASH, "og"))  # the config file changed, its default did not
        self.assertEqual(app.model, "gpt-5.4")
        self.assertEqual([params["value"] for params in sent(client, "config.set")], ["gpt-5.4 --provider copilot"])
        self.assertFalse(any("default model" in said for said in notices(app)))

    def test_the_switch_waits_for_a_turn_that_runs_and_goes_at_its_end(self) -> None:
        app, client = self.launched()
        app.turn_pending = True
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        answer_call(app, client, "config.get", {"mtime": 200.0})
        app.turn_pending = True  # a queued prompt went before the default was read
        answer_call(app, client, "model.options", {"model": "claude-opus-5-5", "provider": "claude-proxy"})
        self.assertEqual(sent(client, "config.set"), [])  # never inside a turn
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertEqual(sent(client, "config.set"), [{"key": "model", "value": OPUS_SWITCH, "session_id": SID}])

    def test_a_refused_switch_leaves_the_session_where_it_was(self) -> None:
        app, client = self.launched()
        self.end_turn(app, client, 200.0, ("claude-opus-5-5", "claude-proxy"))
        answer_call(app, client, "config.set", error={"code": 4001, "message": "model_resolution_failed",
                                                      "data": {"reason": "model_resolution_failed"}})
        self.assertEqual(app.model, FLASH)
        said = notices(app, NOTICE_WARN)[-1]
        self.assertTrue(said.startswith("Hermes' default model is now claude-opus-5-5 (claude-proxy); "
                                        f"this session stays on {FLASH}. Hermes found no provider"), said)
        self.assertNotIn("model_resolution_failed", said)
        self.end_turn(app, client, 200.0)  # not asked again until the default moves again
        self.assertEqual(len(sent(client, "config.set")), 1)

    def test_a_guarded_default_is_asked_about_and_kept_or_switched(self) -> None:
        for switch in (False, True):
            with self.subTest(switch=switch):
                now = [100.0]
                app, client = make_app(clock=lambda: now[0])
                app.model = FLASH
                app._read_default()
                answer_call(app, client, "config.get", {"mtime": 100.0})
                answer_call(app, client, "model.options", {"model": FLASH, "provider": "og"})
                self.end_turn(app, client, 200.0, ("claude-opus-5-5", "claude-proxy"))
                answer_call(app, client, "config.set", {"key": "model", "value": "", "confirm_required": True,
                                                        "confirm_message": "Opus costs 5x."})
                (question,) = app.slot.params["questions"]
                self.assertTrue(question["question"].startswith(
                    "Hermes' default model is now claude-opus-5-5 (claude-proxy). Opus costs 5x."), question)
                now[0] += SLOT_ARM_SECONDS
                if switch:
                    app._on_input(Key(DOWN))
                app._on_input(Key(ENTER))
                if switch:
                    self.assertEqual(sent(client, "config.set")[-1],
                                     {"key": "model", "value": OPUS_SWITCH, "session_id": SID, "confirm_expensive_model": True})
                    answer_call(app, client, "config.set", {"key": "model", "value": "claude-opus-5-5"})
                    self.assertEqual(app.model, "claude-opus-5-5")
                else:
                    self.assertEqual(len(sent(client, "config.set")), 1)
                    self.assertEqual(app.model, FLASH)
                    self.assertIn(f"this session stays on {FLASH}.", notices(app, NOTICE_WARN)[-1])

    def test_a_switch_a_new_turn_came_before_is_tried_again_at_that_turns_end(self) -> None:
        app, client = self.launched()
        self.end_turn(app, client, 200.0, ("claude-opus-5-5", "claude-proxy"))
        answer_call(app, client, "config.set", error={"code": 4001, "message": "stale_generation",
                                                      "data": {"reason": "stale_generation"}})
        self.assertFalse(any("default model" in said for said in notices(app)))
        self.end_turn(app, client, 200.0)
        self.assertEqual(len(sent(client, "config.set")), 2)
        answer_call(app, client, "config.set", {"key": "model", "value": "claude-opus-5-5"})
        self.assertEqual(app.model, "claude-opus-5-5")

    def methods(self, client: object) -> list[str]:
        return [name for name, _params in client.calls]

    def test_a_default_moved_while_idle_switches_before_the_next_turn_starts(self) -> None:
        app, client = self.launched()
        before = len(client.calls)
        send(app, "hello")  # Hermes' config was edited while no turn ran
        self.assertEqual(self.methods(client)[before:], ["config.get"])  # the prompt waits for the check
        self.assertEqual(sent(client, "prompt.submit"), [])
        answer_call(app, client, "config.get", {"mtime": 300.0})
        answer_call(app, client, "model.options", {"model": "claude-opus-5-5", "provider": "claude-proxy"})
        self.assertEqual(sent(client, "prompt.submit"), [])  # still waiting: the switch goes first
        answer_call(app, client, "config.set", {"key": "model", "value": "claude-opus-5-5"})
        self.assertEqual(self.methods(client)[before:], ["config.get", "model.options", "config.set", "prompt.submit"])
        self.assertEqual(sent(client, "prompt.submit"), [{"session_id": SID, "text": "hello"}])
        said = notices(app)
        self.assertIn("Hermes' default model is now claude-opus-5-5 (claude-proxy); this session switched to it.", said)
        self.assertEqual(app.model, "claude-opus-5-5")

    def test_a_config_that_did_not_move_lets_the_prompt_go_after_one_mtime_read(self) -> None:
        app, client = self.launched()
        before = len(client.calls)
        send(app, "hello")
        send(app, "and then")  # typed while the first waits: it queues behind it
        answer_call(app, client, "config.get", {"mtime": 100.0})
        self.assertEqual(self.methods(client)[before:], ["config.get", "prompt.submit"])
        self.assertEqual(sent(client, "prompt.submit"), [{"session_id": SID, "text": "hello"}])
        self.assertEqual([line.text for line in app.queued], ["and then"])

    def test_a_model_picked_with_slash_model_is_not_undone_before_a_prompt(self) -> None:
        app, client = self.launched()
        send(app, "/model gpt-5.4 --provider copilot")
        answer_call(app, client, "config.set", {"key": "model", "value": "gpt-5.4"})
        send(app, "hello")
        answer_call(app, client, "config.get", {"mtime": 150.0})  # another edit; the default did not move
        answer_call(app, client, "model.options", {"model": FLASH, "provider": "og"})
        self.assertEqual(len(sent(client, "config.set")), 1)
        self.assertEqual(sent(client, "prompt.submit"), [{"session_id": SID, "text": "hello"}])
        self.assertEqual(app.model, "gpt-5.4")

    def test_a_guarded_default_found_before_a_prompt_holds_it_until_answered(self) -> None:
        for switch in (False, True):
            with self.subTest(switch=switch):
                now = [100.0]
                app, client = make_app(clock=lambda: now[0])
                app.model = FLASH
                app._read_default()
                answer_call(app, client, "config.get", {"mtime": 100.0})
                answer_call(app, client, "model.options", {"model": FLASH, "provider": "og"})
                send(app, "hello")
                answer_call(app, client, "config.get", {"mtime": 300.0})
                answer_call(app, client, "model.options", {"model": "claude-opus-5-5", "provider": "claude-proxy"})
                answer_call(app, client, "config.set", {"key": "model", "value": "", "confirm_required": True,
                                                        "confirm_message": "Opus costs 5x."})
                self.assertIsNotNone(app.slot)
                self.assertEqual(sent(client, "prompt.submit"), [])  # held while the question is open
                now[0] += SLOT_ARM_SECONDS
                if switch:
                    app._on_input(Key(DOWN))
                app._on_input(Key(ENTER))
                if switch:
                    self.assertEqual(sent(client, "prompt.submit"), [])  # the confirmed switch goes first
                    answer_call(app, client, "config.set", {"key": "model", "value": "claude-opus-5-5"})
                self.assertEqual(sent(client, "prompt.submit"), [{"session_id": SID, "text": "hello"}])
                self.assertEqual(app.model, "claude-opus-5-5" if switch else FLASH)

    def held(self) -> tuple[App, object]:
        """A prompt held for the default check, its mtime read not answered yet."""
        app, client = self.launched()
        send(app, "hello")
        self.assertEqual(sent(client, "prompt.submit"), [])
        return app, client

    def test_a_held_prompt_goes_back_to_the_draft_when_another_session_opens(self) -> None:
        app, client = self.held()
        app._adopt_session({"session_id": "live-2", "info": {"model": FLASH}})  # /new, a switch or a resume answered
        self.assertEqual(app.composer.text, "hello")
        answer_call(app, client, "config.get", {"mtime": 100.0})
        self.assertEqual(sent(client, "prompt.submit"), [])  # never into the session it was not typed in

    def test_a_held_prompt_never_goes_to_a_session_other_than_its_own(self) -> None:
        app, client = self.held()
        app.sid = "live-2"  # the session changed by a path that did not adopt it yet
        answer_call(app, client, "config.get", {"mtime": 100.0})
        self.assertEqual(sent(client, "prompt.submit"), [])
        self.assertEqual(app.composer.text, "hello")

    def test_the_same_session_adopted_again_keeps_the_held_prompt(self) -> None:
        app, client = self.held()
        app._adopt_session({"session_id": SID, "info": {"model": FLASH}})
        answer_call(app, client, "config.get", {"mtime": 100.0})
        self.assertEqual(sent(client, "prompt.submit"), [{"session_id": SID, "text": "hello"}])

    def test_a_first_prompt_before_the_launch_read_answers_goes_at_once(self) -> None:
        app, client = make_app()
        app._read_default()  # asked, not answered yet
        send(app, "hello")
        self.assertEqual(sent(client, "prompt.submit"), [{"session_id": SID, "text": "hello"}])

    def test_a_session_already_on_the_new_default_is_left_as_it_is(self) -> None:
        app, client = self.launched()
        app.model = "claude-opus-5-5"  # `/model claude-opus-5-5 --global` moved both
        self.end_turn(app, client, 200.0, ("claude-opus-5-5", "claude-proxy"))
        self.assertEqual(sent(client, "config.set"), [])

    def test_without_the_launchs_read_nothing_is_measured(self) -> None:
        app, client = make_app()
        app.turn_pending = True
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertEqual(client.calls, [])


class RefusalSentenceTests(unittest.TestCase):
    """A refusal's reason code is said in words that name what to do instead; the code itself is never shown."""

    def test_each_reason_reads_as_its_sentence_with_hermes_hint_after_it(self) -> None:
        for reason, sentence in REFUSAL_SENTENCES.items():
            with self.subTest(reason=reason):
                app, client = make_app()
                send(app, "/compress here 2")
                answer(app, client, error={"code": 4001, "message": reason, "data": {"reason": reason}})
                self.assertEqual(notices(app)[-1], sentence)
                self.assertNotIn(reason, sentence)
        app, client = make_app()
        send(app, "/export")
        send(app, "/export")
        hint = "Run `hermes profile export [name] -o <file>` in a terminal."
        answer(app, client, error={"code": 4001, "message": "unsupported_command",
                                   "data": {"reason": "unsupported_command", "detail": hint}})
        self.assertEqual(notices(app)[-1], f"{REFUSAL_SENTENCES['unsupported_command']} {hint}")

    def test_a_reason_without_a_sentence_reads_as_hermes_wrote_it(self) -> None:
        app, client = make_app()
        send(app, "/compress")
        answer(app, client, error={"code": 4001, "message": "the summary model is down"})
        self.assertEqual(notices(app)[-1], "The summary model is down.")

    def test_a_typed_model_flag_a_shared_gateway_refuses_names_the_way_to_the_default(self) -> None:
        app, client = make_app()
        send(app, "/model --refresh x")
        answer(app, client, error={"code": 4001, "message": "unsupported_command", "data": {"reason": "unsupported_command"}})
        self.assertEqual(notices(app)[-1], MODEL_OPTIONS_REFUSED)

    def test_the_contract_lets_config_set_model_carry_only_a_switch_by_name(self) -> None:
        def problem(value: str) -> str:
            return contract.call_problem("config.set", {"key": "model", "value": value, "session_id": SID})

        self.assertEqual(problem(OPUS_SWITCH), "")
        self.assertEqual(problem("claude-opus-5-5 --session"), "")
        self.assertEqual(problem("claude-opus-5-5"), "")  # typed without --session: Hermes' own persistence rule
        self.assertEqual(problem("claude-opus-5-5 --provider claude-proxy"), "")
        for value in ("claude-opus-5-5 --global", "claude-opus-5-5 --session --session", "x --provider y --session --global",
                      "x --provider \u2014global --session", "x --once --session", ""):
            with self.subTest(value=value):
                self.assertTrue(problem(value))
        self.assertTrue(contract.call_problem("config.set", {"key": "model", "value": OPUS_SWITCH}))  # no session
        confirmed = {"key": "model", "value": OPUS_SWITCH, "session_id": SID, "confirm_expensive_model": True}
        self.assertEqual(contract.call_problem("config.set", confirmed), "")
        for wrong in ({**confirmed, "confirm_expensive_model": False},
                      {"key": "yolo", "value": "on", "session_id": SID, "confirm_expensive_model": True}):
            self.assertTrue(contract.call_problem("config.set", wrong))


class ExportTests(unittest.TestCase):
    def test_the_first_export_says_what_hermes_exports_and_the_second_runs_it(self) -> None:
        app, client = make_app()
        send(app, "/export")
        self.assertEqual(client.calls, [])
        self.assertIn("profile archive", notices(app)[-1])
        self.assertIn("/export again", notices(app)[-1])
        send(app, "/export -o profile.tar.gz")
        self.assertEqual(client.calls, [("slash.exec", {"command": "export -o profile.tar.gz", "session_id": SID})])
        send(app, "/export")
        self.assertEqual(client.calls[-1], ("slash.exec", {"command": "export", "session_id": SID}))



def command_parts(app: App) -> list[list[str]]:
    """Each command echo's rows under it, in order."""
    blocks = [*app.transcript.blocks, *app.transcript._held]
    return [[text for text, _level in block.parts] for block in blocks if isinstance(block, CommandBlock)]


class ModelSwitchFeedbackTests(unittest.TestCase):
    """A switch shows it is out under its echo until Hermes answers, and the answer says what Hermes did (audit A, 3
    and 4; audit B, 7). The client here answers only when the test says, as a slow gateway would."""

    SWITCHING = app_module.MODEL_SWITCHING_LINE.format(model="gpt-5.4")

    def test_a_pending_row_stands_under_the_echo_until_the_answer_takes_its_place(self) -> None:
        app, client = make_app()
        send(app, "/model gpt-5.4")
        self.assertEqual(command_parts(app), [[self.SWITCHING]])
        self.assertTrue(any(self.SWITCHING in line for line in drawn(app)))  # drawn while Hermes has not answered
        answer(app, client, {"key": "model", "value": "gpt-5.4", "scope": "session"})
        self.assertEqual(command_parts(app), [[app_module.MODEL_SWITCHED_NOTICE.format(model="gpt-5.4")]])
        self.assertFalse(any(self.SWITCHING in line for line in drawn(app)))

    def test_a_refusal_or_no_answer_replaces_the_pending_row_too(self) -> None:
        app, client = make_app()
        send(app, "/model gpt-5.4")
        answer(app, client, None, {"code": 4002, "message": "model 'gpt-5.4' not found"})
        (parts,) = command_parts(app)
        self.assertNotIn(self.SWITCHING, parts)
        self.assertEqual(len(parts), 1)
        now = [100.0]
        app, client = make_app(clock=lambda: now[0])
        send(app, "/model gpt-5.4")
        now[0] += 3600
        app._expire_calls()
        seconds = app_module.CALL_ANSWER_SECONDS_BY_METHOD.get("config.set", app_module.CALL_ANSWER_SECONDS)
        self.assertEqual(command_parts(app), [[app_module.CALL_EXPIRED_NOTICE.format(method="config.set", seconds=seconds)]])

    def test_a_switch_hermes_made_global_says_it_is_the_default_for_new_sessions_too(self) -> None:
        for scope, notice in (("global", app_module.MODEL_SWITCHED_GLOBAL_NOTICE),
                              ("session", app_module.MODEL_SWITCHED_NOTICE), (None, app_module.MODEL_SWITCHED_NOTICE)):
            with self.subTest(scope=scope):
                app, client = make_app()
                send(app, "/model gpt-5.4")
                answer(app, client, {"key": "model", "value": "gpt-5.4", "scope": scope})
                self.assertEqual(command_parts(app), [[notice.format(model="gpt-5.4")]])

    def dropped(self, app: App) -> None:
        app._on_event(Event("notification.show", SID, {
            "text": "Stayed on m-a: switching to gpt-5.4 needs confirmation. Pick it again to confirm.",
            "level": "warn", "kind": "ttl", "ttl_ms": 12000, "key": app_module.MODEL_SWITCH_DROPPED_KEY}))

    def test_a_deferred_switch_hermes_drops_at_turn_start_is_a_lasting_row_naming_it(self) -> None:
        # Typed during a turn, /model waits for its end (`RUNS_DURING_TURN`); Hermes still defers a switch for a
        # session whose agent runs on a compute host, and for one that lands as a turn starts.
        app, client = make_app()
        send(app, "/model gpt-5.4")
        answer(app, client, {"key": "model", "value": "gpt-5.4", "deferred": True, "scope": "session"})
        self.assertIn(app_module.MODEL_DEFERRED_NOTICE.format(model="gpt-5.4"), notices(app))
        self.dropped(app)
        self.assertIsNone(app.notification)  # not the 12 s row above the composer
        said = [block.text for block in [*app.transcript.blocks, *app.transcript._held] if hasattr(block, "text")]
        self.assertIn(app_module.MODEL_DROPPED_NOTICE.format(
            model="gpt-5.4",
            reason="Stayed on m-a: switching to gpt-5.4 needs confirmation. Pick it again to confirm."), said)

    def test_a_drop_two_turns_after_the_deferral_does_not_name_that_old_switch(self) -> None:
        app, client = make_app()
        send(app, "/model gpt-5.4")
        answer(app, client, {"key": "model", "value": "gpt-5.4", "deferred": True, "scope": "session"})
        app.turns_ended += 2  # the turn it was held for has come and gone
        self.dropped(app)
        said = [block.text for block in [*app.transcript.blocks, *app.transcript._held] if hasattr(block, "text")]
        self.assertTrue(any(text.startswith("A model switch held for this turn did not happen") for text in said))
        self.assertFalse(any(text.startswith("The switch to gpt-5.4") for text in said))

    def test_a_drop_with_no_deferred_switch_of_this_tui_still_lands_and_other_notifications_do_not(self) -> None:
        app, _client = make_app()
        self.dropped(app)
        self.assertTrue(any(block.text.startswith("A model switch held for this turn did not happen")
                            for block in app.transcript.blocks if hasattr(block, "text")))
        app._on_event(Event("notification.show", SID, {"text": "Indexing", "level": "info", "key": "other"}))
        self.assertIsNotNone(app.notification)
        self.assertFalse(any(getattr(block, "text", "") == "Indexing" for block in app.transcript.blocks))


class ModelPickerLoadingTests(unittest.TestCase):
    """Bare /model opens its picker at once: typing while the list loads filters it, Enter waits, Esc cancels
    (audit A, 5); the current row switches nothing (6); the echo names the model, not the flags (audit B, 10)."""

    def test_typing_while_the_list_loads_is_the_filter_and_enter_waits(self) -> None:
        app, client = make_app()
        send(app, "/model")
        self.assertTrue(app.model_picker.loading)
        self.assertTrue(any(app_module.LIST_WAIT_LINE in line for line in drawn(app)))
        type_text(app, "opus-5-5")
        app._on_input(Key(ENTER))  # before the list: nothing is sent, nothing goes as a prompt
        self.assertEqual(client.calls, [("model.options", {"session_id": SID})])
        self.assertEqual(app.composer.text, "")
        answer(app, client, OPTIONS)
        self.assertFalse(app.model_picker.loading)
        self.assertEqual(app.model_picker.query, "opus-5-5")
        self.assertEqual([row.model for row in app.model_picker.visible()], ["claude-opus-5-5"])
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls[-1][1]["value"], "claude-opus-5-5 --provider anthropic --session")

    def test_esc_while_the_list_loads_closes_it_and_the_list_opens_nothing(self) -> None:
        app, client = make_app()
        send(app, "/model")
        app._on_input(Key(ESCAPE))
        self.assertIsNone(app.model_picker)
        self.assertFalse(any(app_module.LIST_WAIT_LINE in line for line in drawn(app)))
        answer(app, client, OPTIONS)
        self.assertIsNone(app.model_picker)
        self.assertEqual(notices(app), [])

    def test_a_refused_list_closes_the_loading_picker(self) -> None:
        app, client = make_app()
        send(app, "/model")
        answer(app, client, None, {"code": 5001, "message": "boom"})
        self.assertIsNone(app.model_picker)
        self.assertEqual(len(notices(app)), 1)

    def test_the_current_row_switches_nothing(self) -> None:
        app, client = make_app()
        send(app, "/model")
        answer(app, client, OPTIONS)
        self.assertTrue(app.model_picker.visible()[app.model_picker.index].current)
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [("model.options", {"session_id": SID})])
        self.assertIsNone(app.model_picker)
        self.assertEqual(notices(app), [app_module.MODEL_ALREADY_NOTICE.format(model=OPTIONS["model"])])
        self.assertEqual(commands(app), [])

    def test_a_pick_echoes_the_model_and_sends_its_flags(self) -> None:
        app, client = make_app()
        send(app, "/model")
        answer(app, client, OPTIONS)
        app._on_input(Key(DOWN))
        app._on_input(Key(ENTER))
        self.assertEqual(commands(app), ["/model claude-fable-5.1"])
        self.assertEqual(client.calls[-1][1]["value"], "claude-fable-5.1 --provider anthropic --session")


if __name__ == "__main__":
    unittest.main()

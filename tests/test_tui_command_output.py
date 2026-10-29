"""What a slash command prints stays in the transcript, under an echo of the command.

The pager opens only when the person asks for one (`/history`, `/keys`,
`/logs`, Ctrl+O); a command's output, however long, is the transcript's: the
echo `> /name arg`, its output under `⎿`, the first rows of a long one and a
count of the rest naming Ctrl+O, whose details view shows it in full. Driven through the
recording client of `test_tui_modes`, answering each call by hand. A command that turns out
to send a prompt shown as the command (a skill) is one row, the prompt's: one case runs it
against the replay gateway of `test_tui_app` too.
"""

from __future__ import annotations

import unittest

from _tui_gateway_replay import Scenario, spans
from _tui_lines import line_text, lines_text
from test_tui_app import NO_TERMIOS, AppTestCase, Step, startup_answers
from test_tui_modes import PLAN_PROMPT, SID, answer, drawn, make_app, notices, type_text
from omh.tui import gateway_contract as contract
from omh.tui.app import App
from omh.tui.gateway import Event, Response
from omh.tui.keys import DOWN, ENTER, TAB, UP, Key
from omh.tui.theme import DEFAULT_THEME as THEME
from omh.tui.transcript import (
    NOTICE_INFO, NOTICE_WARN, OUTPUT_MARKED, OUTPUT_PREVIEW_ROWS, CommandBlock, NoticeBlock, UserBlock, block_rows,
)


def send(app: App, text: str) -> None:
    type_text(app, text)
    app._on_input(Key(ENTER))


def last(app: App) -> object:
    return app.transcript.blocks[-1]


SKILL_LINE = "/dag-ulw check every upstream pr and rebase what needs it"
# Hermes 0.22.2's answers for a skill command (tui_gateway/methods_tools.py `_dispatch_skill`): `slash.exec` refuses
# it with 4018, and `command.dispatch` builds the turn, naming in `display` the invocation a UI shows for it.
SKILL_REFUSAL = {"code": contract.NOT_MINE, "message": "skill command: use command.dispatch for /dag-ulw"}
SKILL_TURN = {
    "type": "skill",
    "message": "[SYSTEM: the dag-ulw skill body]\n\ncheck every upstream pr and rebase what needs it",
    "name": "dag-ulw",
    "display": SKILL_LINE,
}


def run_skill(app: App, client: object, line: str = SKILL_LINE, turn: dict = SKILL_TURN) -> None:
    send(app, line)
    answer(app, client, error=SKILL_REFUSAL)  # type: ignore[arg-type]
    answer(app, client, turn)  # type: ignore[arg-type]


def prompt_rows(app: App) -> list[str]:
    """The `  ❯` rows printed so far (the rail's two cells, then the mark), scrollback included: each echo's
    (`  ❯ /name`) and each prompt's first row, both on the prompt's rail; the composer's own `❯` row has none
    (#2223 review 7)."""
    app._render()
    return [row.rstrip() for row in app.terminal.screen.history() if row.startswith("  ❯ ")]  # type: ignore[attr-defined]


def end_turn(app: App) -> None:
    app._on_event(Event("message.start", SID, {}))
    app._on_event(Event("message.complete", SID, {"text": "done"}))


class CommandEchoTests(unittest.TestCase):
    def test_a_hermes_command_is_echoed_at_once_and_its_output_lands_under_it(self) -> None:
        app, client = make_app()
        send(app, "/usage")
        self.assertEqual(client.calls, [("slash.exec", {"command": "usage", "session_id": SID})])
        block = last(app)
        self.assertIsInstance(block, CommandBlock)
        self.assertEqual((block.command, block.parts, block.done), ("/usage", [], False))
        answer(app, client, {"output": "Session cost: $0.01"})
        self.assertEqual((block.parts, block.done), ([("Session cost: $0.01", NOTICE_INFO)], True))
        screen = drawn(app)
        self.assertIn("  ❯ /usage", screen)
        self.assertIn("    ⎿  Session cost: $0.01", screen)

    def test_the_title_reply_draws_its_templates_bold_and_keeps_the_title_as_written(self) -> None:
        # Found live: `/title Alpha Work` printed `Session title set: **Alpha Work**`: Hermes' `gateway.title.set_to`
        # template marks the title for a chat.
        for title in ("Alpha Work", "fix __init__ import of *.py"):
            app, client = make_app()
            send(app, f"/title {title}")
            answer(app, client, {"output": f"✏️ Session title set: **{title}**"})
            self.assertIn(f"    ⎿  ✏️ Session title set: {title}", drawn(app))
            (row,) = [row for row in block_rows(last(app), 80, THEME) if "title set" in line_text(row)]
            self.assertEqual([span.text for span in row if span.style.bold], [title])
        app, client = make_app()
        send(app, "/title")
        answer(app, client, {"output": "📌 Session: `abc_1`\nTitle: **beta notes**"})
        self.assertEqual(drawn(app)[1:3], ["    ⎿  📌 Session: abc_1", "       Title: beta notes"])

    def test_a_title_reply_of_no_marked_shape_stays_as_written(self) -> None:
        # Review 2 of #2389: the slash worker's `cli.title.set` (en.yaml:2533) has no marks, and a title refused as in
        # use (hermes_state_titles.py:163) quotes it, so neither may lose a `**` or a backtick.
        # Review 3: the worker's `cli.title.current` (en.yaml:2528) is "Title: {title}", and a title may be `**draft**`.
        for output in ("Session title set: **x** and `y`", "Title 'use `uv` sync' is already in use by session abc",
                       "Session ID: abc\nTitle: **draft**"):
            app, client = make_app()
            send(app, "/title x")
            answer(app, client, {"output": output})
            self.assertIn(f"    ⎿  {output.splitlines()[0]}", drawn(app))
            self.assertIn(output.splitlines()[-1], lines_text(block_rows(last(app), 100, THEME))[-1])
            self.assertFalse(any(span.style.bold for row in block_rows(last(app), 100, THEME) for span in row))
        app, client = make_app()
        send(app, "/title")
        answer(app, client, {"output": "📌 Session: `abc`\nNo title set. Usage: `/title My Session Name`"})
        rows = block_rows(last(app), 100, THEME)
        self.assertEqual(lines_text(rows)[1:], ["    ⎿  📌 Session: abc", "       No title set. Usage: /title My Session Name"])
        self.assertEqual([span.text for row in rows for span in row if span.style == THEME.code],
                         ["abc", "/title My Session Name"])

    def test_any_other_hermes_reply_is_data_and_stays_as_written(self) -> None:
        # Review of #2389: drawing every reply as Markdown ate `__init__`, `*.py`, `2*3*4` and a Windows path's `\\`.
        replies = (
            ("/gitst", " M src/__init__.py\n M tests/__init__.py\n?? docs/*.md"),  # a quick command's `git status`
            ("/context", "[You #1] rename my_var to __my_var__ in src/*.py and tests/*.py\n[Hermes #2] Done: 2*3*4 files"),
            ("/status", "Path: C:\\Users\\me\\.hermes\\sessions\\abc.jsonl"),
            ("/tools", 'ignore: ["*.pyc", "*.log"] and [You #1](draft)'),
        )
        for command, output in replies:
            app, client = make_app()
            send(app, command)
            if command == "/gitst":
                app._on_response(Response(1, None, {"code": 4018, "message": "not a slash.exec command"}))
                answer(app, client, {"type": "exec", "output": output})
            else:
                answer(app, client, {"output": output})
            self.assertEqual(last(app).parts, [(output, NOTICE_INFO)])
            rows = lines_text(block_rows(last(app), 120, THEME))[1:]
            self.assertEqual([row[7:] for row in rows], output.split("\n"), command)
            self.assertFalse(any(span.style.bold for row in block_rows(last(app), 120, THEME) for span in row))

    def test_only_the_title_reply_is_read_for_marks_not_omhs_own_words_under_its_echo(self) -> None:
        mine, reply = "✏️ Session title set: **as** written", "✏️ Session title set: **Alpha**"
        block = CommandBlock("/title Alpha", [(mine, NOTICE_INFO), (reply, OUTPUT_MARKED)])
        rows = block_rows(block, 80, THEME)
        self.assertEqual(lines_text(rows)[1:], [f"    ⎿  {mine}", "       ✏️ Session title set: Alpha"])
        self.assertEqual([span.text for row in rows for span in row if span.style.bold], ["Alpha"])

    def test_long_output_stays_in_the_transcript_and_no_pager_opens(self) -> None:
        app, client = make_app(rows=24, cols=80)
        send(app, "/context")
        long = "\n".join(f"context row {number}" for number in range(40))
        answer(app, client, {"output": long})
        self.assertIsNone(app.pager)
        self.assertEqual(last(app).parts, [(long, NOTICE_INFO)])  # all of it held, for /history
        screen = drawn(app)
        self.assertIn(f"       context row {OUTPUT_PREVIEW_ROWS - 1}", screen)
        self.assertNotIn(f"       context row {OUTPUT_PREVIEW_ROWS}", screen)
        self.assertIn(f"       … +{40 - OUTPUT_PREVIEW_ROWS} rows · ctrl+o shows all", screen)

    def test_a_command_dispatch_owns_answers_under_the_same_echo_and_closes_it_only_then(self) -> None:
        app, client = make_app()
        send(app, "/undo")
        app._on_response(Response(1, None, {"code": 4018, "message": "not a slash.exec command"}))
        self.assertEqual(client.calls[-1], ("command.dispatch", {"name": "undo", "arg": "", "session_id": SID}))
        self.assertFalse(last(app).done)  # its fallback is still out
        answer(app, client, {"type": "exec", "output": "Undid the last turn."})
        self.assertEqual((last(app).command, last(app).parts, last(app).done), ("/undo", [("Undid the last turn.", NOTICE_INFO)], True))

    def test_a_local_commands_notice_is_its_output_and_the_echo_closes_with_the_command(self) -> None:
        app, client = make_app()
        send(app, "/theme nope")
        self.assertEqual(client.calls, [])
        block = last(app)
        self.assertTrue(block.done)
        self.assertEqual(block.command, "/theme nope")
        self.assertEqual(block.parts[0][1], NOTICE_WARN)
        self.assertIn("No theme or launch look named nope", block.parts[0][0])

    def test_help_prints_whole(self) -> None:
        app, _client = make_app(rows=24, cols=200)
        send(app, "/help")
        block = last(app)
        self.assertTrue(block.whole)
        self.assertIsNone(app.pager)
        self.assertGreater(len(block.parts[0][0].split("\n")), OUTPUT_PREVIEW_ROWS)

    def test_output_answered_after_a_prompt_repeats_the_echo(self) -> None:
        app, client = make_app()
        send(app, "/usage")
        send(app, "and now a prompt")
        self.assertIsInstance(last(app), UserBlock)
        app._on_response(Response(1, {"output": "Session cost: $0.01"}, None))
        block = last(app)
        self.assertIsInstance(block, CommandBlock)
        self.assertEqual((block.command, block.parts, block.done), ("/usage", [("Session cost: $0.01", NOTICE_INFO)], True))
        echoes = [entry for entry in app.transcript.blocks if isinstance(entry, CommandBlock)]
        self.assertEqual([entry.command for entry in echoes], ["/usage", "/usage"])

    def test_two_commands_out_at_once_each_print_under_their_own_echo(self) -> None:
        # Hermes' slash.exec runs a CLI worker and can take seconds, so a second command often goes before the first
        # one answers; the answer finds its command through the call that asked, whichever order they come in.
        for order in ((1, 2), (2, 1)):
            with self.subTest(order=order):
                app, client = make_app()
                send(app, "/usage")
                send(app, "/skills list")
                said = {1: "USAGE: 12k tokens today", 2: "SKILLS: omh-plan, omh-review"}
                for call in order:
                    app._on_response(Response(call, {"output": said[call]}, None))
                under = {part: block.command for block in app.transcript.blocks if isinstance(block, CommandBlock)
                         for part, _level in block.parts}
                self.assertEqual(under, {said[1]: "/usage", said[2]: "/skills list"})
                echoes = [block for block in app.transcript.blocks if isinstance(block, CommandBlock)]
                self.assertEqual([block.command for block in echoes], ["/usage", "/skills list"])  # no repeated echo
                self.assertTrue(all(block.done for block in echoes))

    def test_output_answered_after_a_switch_repeats_the_echo_in_the_session_now_live(self) -> None:
        app, client = make_app()
        send(app, "/usage")
        send(app, "/new")
        answer(app, client, {"session_id": "live-2", "stored_session_id": "stored-2", "info": {}})
        app._on_response(Response(1, {"output": "Session cost: $0.01"}, None))
        echoes = [block for block in app.transcript.blocks if isinstance(block, CommandBlock)]
        self.assertEqual([(block.command, block.parts) for block in echoes][-1:],
                         [("/usage", [("Session cost: $0.01", NOTICE_INFO)])])  # not lost in the old session's echo

    def test_a_notice_from_outside_a_command_is_not_its_output(self) -> None:
        app, _client = make_app()
        send(app, "/usage")  # still waiting for Hermes
        app._on_error_event("The gateway reported an error.")  # between turns: a notice of its own
        echo = next(block for block in app.transcript.blocks if isinstance(block, CommandBlock))
        self.assertEqual(echo.parts, [])
        self.assertIsInstance(last(app), NoticeBlock)

    def test_a_prompt_typed_in_plan_mode_is_no_command_and_is_not_echoed(self) -> None:
        app, client = make_app()
        app.plan_mode = True
        send(app, "fix the flaky test")
        self.assertFalse([entry for entry in app.transcript.blocks if isinstance(entry, CommandBlock)])
        self.assertEqual(client.calls[0][0], "slash.exec")

    def test_the_pager_opens_only_when_asked_for(self) -> None:
        app, _client = make_app()
        app.transcript.add_notice("an earlier notice")
        send(app, "/history")
        self.assertIsNotNone(app.pager)
        self.assertEqual(last(app).text, "an earlier notice")  # a pager command prints nothing, so it has no echo

    def test_completion_still_fills_the_composer_without_running_anything(self) -> None:
        app, client = make_app()
        type_text(app, "/usa")
        app._on_input(Key(TAB))
        self.assertEqual(client.calls, [])
        self.assertFalse([entry for entry in app.transcript.blocks if isinstance(entry, (CommandBlock, NoticeBlock))])


class CommandCaseTests(unittest.TestCase):
    """A TUI command typed in any case is the TUI's own, as Hermes matches its own names whatever their case."""

    def test_help_in_capitals_shows_the_tuis_help_under_the_echo_as_typed(self) -> None:
        app, client = make_app(rows=24, cols=200)
        send(app, "/HELP")
        block = last(app)
        self.assertEqual(block.command, "/HELP")
        self.assertIn("OMH TUI commands:", block.parts[0][0])
        self.assertEqual(client.calls, [])

    def test_steer_in_capitals_steers_the_running_turn(self) -> None:
        app, client = make_app(busy=True)
        send(app, "/Steer use the other file")
        self.assertEqual(client.calls, [("session.steer", {"session_id": SID, "text": "use the other file"})])

    def test_a_renamed_command_in_capitals_runs_its_hermes_name(self) -> None:
        app, client = make_app()
        send(app, "/Cost")
        self.assertEqual(client.calls, [("slash.exec", {"command": "usage", "session_id": SID})])

    def test_an_unknown_name_and_a_skill_in_capitals_still_go_to_hermes_as_typed(self) -> None:
        # Unchanged: Hermes lowercases the name itself. A whole skill name typed bare is sent, not completed.
        for line in ("/Foo bar", "/Dag-ulw check the prs", "/Dag-ulw"):
            with self.subTest(line=line):
                app, client = make_app()
                app.catalog = [("/dag-ulw", "Graph work"), ("/dag-ulw-extra", "Another")]
                send(app, line)
                self.assertEqual(client.calls, [("slash.exec", {"command": line[1:], "session_id": SID})])

    def test_enter_on_a_whole_name_typed_in_another_case_sends_the_line(self) -> None:
        # The TUI's reload-skills row sorts above Hermes' /reload. A whole name on the first row, or the highlight on
        # the row that only changes the case of what is typed, sends the line, as it does in lower case.
        for typed in ("/reload", "/Reload"):
            for downs in (0, 1):
                with self.subTest(typed=typed, downs=downs):
                    app, client = make_app()
                    app.catalog = [("/reload", "Hermes: reload config")]
                    type_text(app, typed)
                    self.assertEqual([label for label, _summary in app._menu_rows()][:2], ["/reload-skills", "/reload"])
                    for _ in range(downs):
                        app._on_input(Key(DOWN))
                    app._on_input(Key(ENTER))
                    self.assertEqual(client.calls, [("slash.exec", {"command": typed[1:], "session_id": SID})])


class SkillCommandRowTests(unittest.TestCase):
    """A skill command is one input row, its prompt's, with one dispatch and one prompt sent.

    The owner typed `/dag-ulw <request>` once and saw two identical rows: the
    command's echo, then the prompt the skill sent, which shows Hermes'
    `display`. The prompt's row stays; the echo is taken back.
    """

    def test_one_skill_command_is_one_row_one_dispatch_and_one_prompt(self) -> None:
        app, client = make_app(rows=40)
        run_skill(app, client)
        methods = [method for method, _params in client.calls]
        self.assertEqual(methods, ["slash.exec", "command.dispatch", "prompt.submit"])
        self.assertEqual(client.named("prompt.submit"), [{"session_id": SID, "text": SKILL_TURN["message"]}])
        self.assertEqual(prompt_rows(app), [f"  ❯ {SKILL_LINE}"])
        self.assertEqual([type(block) for block in app.transcript.blocks], [UserBlock])

    def test_the_same_skill_command_sent_twice_is_two_rows_and_two_prompts(self) -> None:
        # Two submissions are two because they were sent twice, whatever their text.
        app, client = make_app(rows=40)
        run_skill(app, client)
        end_turn(app)
        run_skill(app, client)
        self.assertEqual(len(client.named("command.dispatch")), 2)
        self.assertEqual(client.named("prompt.submit"), [{"session_id": SID, "text": SKILL_TURN["message"]}] * 2)
        self.assertEqual(prompt_rows(app), [f"  ❯ {SKILL_LINE}"] * 2)

    def test_the_same_skill_command_sent_during_its_own_turn_waits_and_then_shows_once(self) -> None:
        app, client = make_app(rows=40)
        run_skill(app, client)
        app._on_event(Event("message.start", SID, {}))
        run_skill(app, client)  # the busy mode is queue: the prompt waits behind the turn
        self.assertEqual(len(client.named("prompt.submit")), 1)
        self.assertEqual([line.shown for line in app.queued], [SKILL_LINE])
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertEqual(len(client.named("command.dispatch")), 2)
        self.assertEqual(len(client.named("prompt.submit")), 2)
        first, drained = prompt_rows(app)
        self.assertEqual(first, f"  ❯ {SKILL_LINE}")
        self.assertTrue(drained.startswith(f"  ❯ {SKILL_LINE}") and drained.endswith("from queue"), drained)

    def test_what_the_dispatch_says_goes_under_the_prompt_row_and_repeats_no_echo(self) -> None:
        notice = "⚡ Loading 2 stacked skills: dag-ulw, review"
        stacked = {**SKILL_TURN, "notice": notice, "display": "/dag-ulw /review fix it"}
        app, client = make_app(rows=40)
        run_skill(app, client, "/dag-ulw /review fix it", stacked)
        self.assertEqual(prompt_rows(app), ["  ❯ /dag-ulw /review fix it"])
        self.assertEqual([type(block) for block in app.transcript.blocks], [UserBlock, NoticeBlock])
        self.assertEqual(notices(app), [notice])

    def test_stacked_skills_sent_during_a_running_tool_wait_and_cut_nothing_off(self) -> None:
        notice = "⚡ Loading 2 stacked skills: dag-ulw, review"
        stacked = {**SKILL_TURN, "notice": notice, "display": "/dag-ulw /review fix it"}
        app, client = make_app(rows=40)
        app.turn_pending = True
        app._on_event(Event("message.start", SID, {}))
        app._on_event(Event("tool.start", SID, {"tool_id": "t1", "name": "terminal", "context": "make test"}))
        run_skill(app, client, "/dag-ulw /review fix it", stacked)  # the busy mode is queue
        self.assertEqual(client.named("prompt.submit"), [])
        self.assertEqual([line.shown for line in app.queued], ["/dag-ulw /review fix it"])
        group = app.transcript.blocks[-1]
        self.assertFalse(group.done)  # nothing closed the running call
        self.assertEqual(group.tools[0].status, "running")
        self.assertFalse([block for block in app.transcript.blocks if isinstance(block, (CommandBlock, NoticeBlock))])
        self.assertEqual([line.notice for line in app.queued], [notice])  # it waits with its prompt, not in this turn
        app._on_event(Event("tool.complete", SID, {"tool_id": "t1", "name": "terminal", "result": {"output": "ok"}}))
        app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.assertEqual(len(client.named("prompt.submit")), 1)
        self.assertEqual(notices(app), [notice])
        row, notice_block = app.transcript.blocks[-2:]  # the drained row, then what the dispatch said, under it
        self.assertEqual((type(row), row.text, row.from_queue), (UserBlock, "/dag-ulw /review fix it", True))
        self.assertEqual((type(notice_block), notice_block.text), (NoticeBlock, notice))
        (shown,) = prompt_rows(app)
        self.assertTrue(shown.startswith("  ❯ /dag-ulw /review fix it") and shown.endswith("from queue"), shown)

    def test_two_skill_commands_of_one_line_answered_out_of_order_are_two_rows(self) -> None:
        # Hermes runs slash.exec and command.dispatch on its RPC pool, so the second dispatch can answer first.
        app, client = make_app(rows=40)
        app.turn_pending = True
        app._on_event(Event("message.start", SID, {}))
        app._on_event(Event("tool.start", SID, {"tool_id": "t1", "name": "terminal", "context": "make test"}))
        send(app, SKILL_LINE)
        send(app, SKILL_LINE)
        app._on_response(Response(1, None, SKILL_REFUSAL))
        app._on_response(Response(2, None, SKILL_REFUSAL))
        self.assertEqual([method for method, _params in client.calls[2:]], ["command.dispatch"] * 2)
        app._on_response(Response(4, SKILL_TURN, None))  # the second submission's dispatch
        app._on_response(Response(3, SKILL_TURN, None))
        self.assertFalse([block for block in app.transcript.blocks if isinstance(block, CommandBlock)])
        app._on_event(Event("tool.complete", SID, {"tool_id": "t1", "name": "terminal", "result": {"output": "ok"}}))
        end_turn(app)  # the first queued prompt's turn
        end_turn(app)  # the second's
        self.assertEqual(len(client.named("prompt.submit")), 2)
        self.assertFalse([block for block in app.transcript.blocks if isinstance(block, CommandBlock)])
        self.assertEqual(len(prompt_rows(app)), 2)

    def test_a_refused_prompt_says_so_as_for_a_typed_one_and_repeats_no_echo(self) -> None:
        app, client = make_app(rows=40)
        run_skill(app, client)
        answer(app, client, error={"code": 4090, "message": "another process owns this session"})
        self.assertEqual(prompt_rows(app), [f"  ❯ {SKILL_LINE}"])
        self.assertEqual(notices(app), ["Hermes did not take the prompt: another process owns this session."])
        self.assertFalse([block for block in app.transcript.blocks if isinstance(block, CommandBlock)])

    def test_the_row_is_the_one_a_resumed_session_draws_and_up_gives_back_the_command(self) -> None:
        app, client = make_app(rows=40)
        run_skill(app, client)
        end_turn(app)
        resumed, _client = make_app(rows=40)
        # Hermes' session history shows a skill turn as its invocation (session_history.py), as a rewind redraws it.
        resumed._draw_history([{"role": "user", "text": SKILL_LINE, "display_kind": "skill_invocation"},
                               {"role": "assistant", "text": "done"}])
        self.assertEqual(prompt_rows(app), prompt_rows(resumed))
        app._on_input(Key(UP))
        self.assertEqual(app.composer.text, SKILL_LINE)

    def test_a_plain_prompt_is_still_one_row_and_one_prompt(self) -> None:
        app, client = make_app(rows=40)
        send(app, "fix the flaky test")
        self.assertEqual(client.calls, [("prompt.submit", {"session_id": SID, "text": "fix the flaky test"})])
        self.assertEqual(prompt_rows(app), ["  ❯ fix the flaky test"])

    def test_a_command_that_prints_keeps_its_echo(self) -> None:
        for line in ("/help", "/usage"):
            with self.subTest(command=line):
                app, client = make_app(rows=40, cols=200)
                send(app, line)
                if client.calls:
                    answer(app, client, {"output": "Session cost: $0.01"})
                self.assertEqual(prompt_rows(app), [f"  ❯ {line}"])  # an echo, on the prompt's rail
                self.assertEqual(client.named("prompt.submit"), [])

    def test_a_skill_hermes_names_no_display_for_shows_as_typed(self) -> None:
        app, client = make_app(rows=40)
        run_skill(app, client, turn={key: value for key, value in SKILL_TURN.items() if key != "display"})
        self.assertEqual(prompt_rows(app), [f"  ❯ {SKILL_LINE}"])
        self.assertEqual(client.named("prompt.submit"), [{"session_id": SID, "text": SKILL_TURN["message"]}])

    def test_a_built_in_send_with_no_display_keeps_its_echo_above_what_it_sends(self) -> None:
        # Hermes' own TUI shows the built message for such a send, and so does a resumed session.
        for line, answers, sent in (
            ("/plan fix the flaky test", ({"error": {"code": contract.NOT_MINE, "message": "pending-input command"}},
                                          {"result": {"type": "send", "message": PLAN_PROMPT}}), PLAN_PROMPT),
            ("/retry", ({"result": {"type": "send", "message": "fix the flaky test"}},), "fix the flaky test"),
        ):
            with self.subTest(command=line):
                app, client = make_app(rows=40)
                send(app, line)
                for reply in answers:
                    answer(app, client, reply.get("result"), reply.get("error"))
                self.assertEqual(prompt_rows(app), [f"  ❯ {line}", f"  ❯ {sent.splitlines()[0]}"])  # the echo, the prompt
                self.assertEqual(client.named("prompt.submit"), [{"session_id": SID, "text": sent}])


class DetailsViewTests(unittest.TestCase):
    def test_ctrl_o_opens_the_whole_transcript_with_details_at_its_end(self) -> None:
        from omh.tui.keys import CHAR
        from omh.tui.pager import HistoryPager

        app, client = make_app(rows=12, cols=80)
        for number in range(30):
            app.transcript.add_notice(f"notice {number}")
        app._on_input(Key(CHAR, "o", ctrl=True))
        self.assertIsInstance(app.pager, HistoryPager)
        screen = drawn(app)
        self.assertIn("· notice 29", screen)  # the last page, not the first
        self.assertNotIn("· notice 0", screen)
        self.assertEqual(client.calls, [])

    def test_the_key_a_cut_output_names_is_the_one_that_shows_what_it_cut(self) -> None:
        from omh.tui.gateway import Event
        from omh.tui.keys import CHAR

        for kind in ("tool", "command"):
            with self.subTest(output=kind):
                app, client = make_app(rows=40, cols=80)
                if kind == "tool":
                    printed = "\n".join(f"out {number}" for number in range(1, 7))
                    app._on_event(Event("message.start", SID, {}))
                    app._on_event(Event("tool.start", SID, {"tool_id": "t", "name": "terminal", "context": "seq 6"}))
                    app._on_event(Event("tool.complete", SID, {"tool_id": "t", "name": "terminal",
                                                               "result": {"output": printed}}))
                    hidden, cut = "out 6", "… +3 lines · "
                else:
                    send(app, "/context")
                    answer(app, client, {"output": "\n".join(f"context row {number}" for number in range(40))})
                    hidden, cut = "context row 39", f"… +{40 - OUTPUT_PREVIEW_ROWS} rows · "
                screen = drawn(app)
                row = next(row for row in screen if cut in row)
                self.assertNotIn(hidden, screen)
                key = row.split(cut)[1].split(" ")[0]
                self.assertEqual(key, "ctrl+o")
                app._on_input(Key(CHAR, key.removeprefix("ctrl+"), ctrl=True))
                self.assertIn(hidden, "\n".join(drawn(app)))  # the details view, at its end

    def test_ctrl_o_over_an_open_question_pages_the_question_not_the_transcript(self) -> None:
        from omh.tui.gateway import ServerRequest
        from omh.tui.keys import CHAR
        from omh.tui.pager import HistoryPager

        app, client = make_app()
        app.transcript.add_notice("something to show")  # so a view would have rows to open on
        app._on_server_request(ServerRequest("srq-1", "approval", {"command": "rm -rf ./x"}))
        app._on_input(Key(CHAR, "o", ctrl=True))
        self.assertIs(app.pager, app.question_view)
        self.assertNotIsInstance(app.pager, HistoryPager)
        self.assertIsNotNone(app.slot)
        self.assertEqual(client.answers, [])


class DocumentedOutputTests(unittest.TestCase):
    def test_installation_names_the_rows_the_code_shows(self) -> None:
        from pathlib import Path

        prose = " ".join((Path(__file__).resolve().parents[1] / "docs/INSTALLATION.md").read_text(encoding="utf-8").split())
        self.assertIn(f"a long output shows its first {OUTPUT_PREVIEW_ROWS} rows and a count of the rest", prose)
        self.assertIn("Nothing a command prints opens a pager", prose)


@unittest.skipIf(NO_TERMIOS, "the OMH TUI needs termios")
class SkillCommandReplayTests(AppTestCase):
    def test_a_skill_command_reaches_hermes_once_and_the_terminal_prints_one_row(self) -> None:
        answers = (
            *startup_answers(),
            ("slash.exec", {"error": SKILL_REFUSAL}),
            ("command.dispatch", {"result": SKILL_TURN}),
        )
        run = self.prepare(Scenario("session", spans("session", "startup", "create", "plain_turn"), answers=answers))
        terminal = run.terminal
        terminal.script(
            self.submit(run, SKILL_LINE),
            Step(b"\x04", when=lambda: "later." in terminal.history() and terminal.idle(), label="the reply"),
        )
        self.run_main(run)
        self.assert_clean_run(run)
        self.assertEqual(len(run.calls("slash.exec")), 1)
        self.assertEqual(len(run.calls("command.dispatch")), 1)
        (submitted,) = run.calls("prompt.submit")
        self.assertEqual(submitted["params"]["text"], SKILL_TURN["message"])
        self.assertEqual(terminal.history().count(SKILL_LINE), 1, terminal.history())


if __name__ == "__main__":
    unittest.main()

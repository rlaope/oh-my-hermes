"""An attached image is an `[Image #N]` token in the draft; Hermes holds it only while the prompt it goes with is sent.

The app is driven as `test_tui_modes` drives it: keys go through
`App._on_input` (or the decoder, for the bytes a terminal sends), and the
calls it makes are answered by `FakeHermes`, which keeps a session's staged
images as Hermes' gateway does: a staging appends one, `image.detach` takes
one out by path, and a `prompt.submit` takes everything staged only when its
turn is admitted: COLD, when the test says (`admit`), as Hermes' turn thread
takes it after the agent build (`_admit_prompt_turn`); WARM (`warm`), the
moment Hermes reads the submit, before any call written after it, as an agent
already built races the reader. So a test sees which images each turn really
went with. The composer's own rules for a token are
`test_tui_composer.ImageTokenTests`.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _tui_lines import lines_text
from test_tui_app import info_row_of
from test_tui_modes import SID, RecordingClient, drawn, make_app, notices, type_text
from omh.tui import gateway_contract as contract
from omh.tui.app import (
    EXIT_HINT,
    IMAGE_NOT_SENT_NOTICE,
    IMAGE_WAIT_LINE,
    UNSENT_BACK_NOTICE,
    UNSENT_BACK_RESPAWN,
    UNSENT_BACK_SWITCH,
    App,
    Attachment,
    read_image,
)
from omh.tui.gateway import Event, Response
from omh.tui.keys import BACKSPACE, CHAR, DOWN, ENTER, ESCAPE, LEFT, UP, Key, KeyDecoder, Paste
from omh.tui.theme import DEFAULT_THEME
from omh.tui.transcript import NOTICE_WARN, UserBlock, block_rows

CTRL_V = Key(CHAR, "v", ctrl=True)
PNG = b"\x89PNG\r\n\x1a\n"
# The last private-use plane, where the composer's token characters live: none may leave the TUI.
TOKEN_RANGE = range(0x100000, 0x110000)
ANSWERED = ("clipboard.paste", "image.attach", "image.attach_bytes", "image.detach", "input.detect_drop",
            "prompt.submit")


def ctrl(char: str) -> Key:
    return Key(CHAR, char, ctrl=True)


class FakeHermes:
    """Hermes' staging of images for one session, answering the app's image and prompt calls in order (`pump`)."""

    def __init__(self, app: App, client: RecordingClient, home: Path, warm: bool = False) -> None:
        self.app, self.client, self.home, self.warm = app, client, home, warm
        self.held: list[str] = []
        self.files: dict[str, bytes] = {}  # every image file Hermes wrote, by path, in order
        self.waiting: list[str] = []  # submitted prompts whose turns are not admitted yet
        self.turns: list[tuple[str, list[bytes]]] = []  # each admitted turn's text and the images it took
        self.answered = 0
        self.responded: set[int] = set()

    def write(self, data: bytes) -> str:
        path = str(self.home / f"image_{len(self.files) + 1}.png")
        Path(path).write_bytes(data)
        self.files[path] = data
        return path

    def stage(self, data: bytes, name: str = "") -> dict:
        path = self.write(data)
        self.held.append(path)
        return {"attached": True, "path": path, "name": name or Path(path).name, "width": 4, "height": 3}

    def pump(self, until: int | None = None) -> None:
        """Answer the app's image and prompt calls made since the last pump, the first `until` calls at most; any
        other call stays unanswered (a test answers it with `respond`)."""
        while self.answered < len(self.client.calls) and (until is None or self.answered < until):
            index = self.answered
            self.answered += 1
            method, params = self.client.calls[index]
            if method in ANSWERED:
                self.app._on_response(Response(index + 1, self.answer(method, params), None))
                if method == "prompt.submit" and self.warm:
                    self.admit()

    def answer(self, method: str, params: dict) -> dict:
        if method == "clipboard.paste":
            return self.stage(PNG + b"clip%d" % len(self.files))
        if method == "image.attach":
            return self.stage(PNG + params["path"].encode(), Path(params["path"]).name)
        if method == "input.detect_drop":
            if not params["text"].startswith("/"):
                return {"matched": False}  # no path: the paste is text
            return {"matched": True, "is_image": True, **self.stage(PNG + params["text"].encode())}
        if method == "image.attach_bytes":
            path = self.write(base64.b64decode(params["content_base64"]))
            self.held.append(path)
            return {"attached": True, "path": path}
        if method == "image.detach":
            before = len(self.held)
            self.held = [path for path in self.held if path != params["path"]]
            return {"detached": len(self.held) != before, "count": len(self.held)}
        self.waiting.append(params["text"])  # prompt.submit: the turn takes the images when it is admitted
        return {"status": "streaming"}

    def admit(self) -> None:
        """The oldest waiting turn is admitted: it takes every image staged now, and the app sees `message.start`."""
        text = self.waiting.pop(0)
        taken, self.held = self.held, []
        self.turns.append((text, [self.files[path] for path in taken]))
        self.app._on_event(Event("message.start", SID, {}))
        self.pump()

    def complete(self) -> None:
        self.app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.pump()

    def respond(self, method: str, result: dict | None = None, error: dict | None = None) -> None:
        """Answer the oldest call of `method` no test answered yet."""
        index = next(index for index, (name, _params) in enumerate(self.client.calls)
                     if name == method and index not in self.responded)
        self.responded.add(index)
        self.app._on_response(Response(index + 1, result, error))
        self.pump()


class ImageTestCase(unittest.TestCase):
    def setUp(self, warm: bool = False) -> None:
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.app, self.client = make_app()
        self.hermes = FakeHermes(self.app, self.client, Path(home.name), warm)

    def press(self, *keys: Key | Paste) -> None:
        for key in keys:
            self.app._on_input(key)
        self.hermes.pump()

    def type(self, text: str) -> None:
        type_text(self.app, text)
        self.hermes.pump()

    def paste_image(self) -> bytes:
        """Ctrl+V; the bytes of the clipboard image Hermes saved."""
        self.press(CTRL_V)
        return list(self.hermes.files.values())[-1]

    def shown(self) -> str:
        return self.app.composer.expanded()

    def screen(self) -> str:
        self.app._render()
        return "\n".join(self.app.terminal.screen.lines())  # type: ignore[attr-defined]

    def methods(self, prefix: str = "image.") -> list[str]:
        return [method for method, _params in self.client.calls if method.startswith(prefix)]

    def users(self) -> list[UserBlock]:
        return [block for block in self.app.transcript.blocks if isinstance(block, UserBlock)]


class TokenTests(ImageTestCase):
    def test_a_pasted_image_is_a_token_at_the_caret_its_bytes_kept_and_hermes_holding_nothing(self) -> None:
        self.type("이런느낌으로")
        for _ in range(len("느낌으로")):
            self.press(Key(LEFT))
        data = self.paste_image()
        self.assertEqual(self.shown(), "이런 [Image #1] 느낌으로")
        ((_label, image),) = self.app.composer.images.values()
        self.assertEqual(image.data, data)
        self.assertEqual(self.hermes.held, [])  # let go of at once: only a prompt being sent stages an image
        self.app._render()
        screen = "\n".join(self.app.terminal.screen.lines())  # type: ignore[attr-defined]
        self.assertIn("❯ 이런 [Image #1] 느낌으로", screen)
        self.assertNotIn("📎", screen)

    def test_images_are_numbered_upward_through_the_run_like_claude_codes(self) -> None:
        self.paste_image()
        self.paste_image()
        self.assertEqual(self.shown(), "[Image #1] [Image #2] ")
        self.press(Key(ENTER))
        self.hermes.admit()
        self.hermes.complete()
        self.paste_image()
        self.assertEqual(self.shown(), "[Image #3] ")

    def test_a_resumed_sessions_labels_are_never_given_again(self) -> None:
        self.app._draw_history([{"role": "user", "text": "[Image #7] this one, and [Image #2]"}])
        self.paste_image()
        self.assertEqual(self.shown(), "[Image #8] ")

    def test_every_attach_path_makes_a_token_and_leaves_hermes_holding_nothing(self) -> None:
        for name, start in (
            ("/image", lambda app: app._image("shot.png what is this?")),
            ("Ctrl+V", lambda app: app._on_input(CTRL_V)),
            ("a dropped path", lambda app: app._on_input(Paste("/h/images/shot.png"))),
        ):
            with self.subTest(name):
                self.setUp()
                start(self.app)
                self.hermes.pump()
                self.assertTrue(self.shown().startswith("[Image #1] "), self.shown())
                self.assertEqual(self.hermes.held, [])

    def test_typing_the_label_by_hand_attaches_nothing(self) -> None:
        self.type("[Image #1] what is it")
        self.press(Key(ENTER))
        self.hermes.admit()
        self.assertEqual(self.hermes.turns, [("[Image #1] what is it", [])])
        self.assertEqual(self.methods(), [])


class DeletionTests(ImageTestCase):
    """Whatever takes the token takes its image: no prompt goes with it, since nothing else holds it."""

    def test_a_deleted_image_never_rides_any_prompt(self) -> None:
        cmd_backspace = list(KeyDecoder().feed(b"\x15"))  # what iTerm2 and Ghostty send for Cmd+Backspace
        self.assertEqual(cmd_backspace, [ctrl("u")])
        cases = {
            "Backspace into the token": [Key(BACKSPACE)] * 3,
            "Cmd+Backspace (Ctrl+U)": cmd_backspace,
            "Ctrl+W": [ctrl("w"), ctrl("w")],
            "Ctrl+K from before it": [Key(LEFT), Key(LEFT), Key(LEFT), ctrl("k")],
            "Ctrl+C": [ctrl("c")],
            "Esc Esc": [Key(ESCAPE), Key(ESCAPE)],
        }
        for name, keys in cases.items():
            with self.subTest(name):
                self.setUp()
                self.type("look")
                self.paste_image()
                self.type("x")
                self.press(*keys)
                self.assertNotIn("[Image", self.shown())
                self.type(" and send")
                self.press(Key(ENTER))
                self.hermes.admit()
                ((_text, images),) = self.hermes.turns
                self.assertEqual(images, [])
                self.assertEqual(self.methods("image.attach_bytes"), [])

    def test_undo_brings_the_token_back_and_the_prompt_goes_with_that_image(self) -> None:
        data = self.paste_image()
        self.press(ctrl("u"), ctrl("_"))
        self.assertEqual(self.shown(), "[Image #1] ")
        self.press(Key(ENTER))
        self.hermes.admit()
        self.assertEqual(self.hermes.turns, [("[Image #1] ", [data])])


class SendTests(ImageTestCase):
    def test_the_prompt_keeps_its_labels_goes_with_its_images_and_the_echo_lists_them(self) -> None:
        first = self.paste_image()
        self.type("and ")
        second = self.paste_image()
        self.type("like this")
        self.press(Key(ENTER))
        self.assertEqual(self.hermes.waiting, ["[Image #1] and [Image #2] like this"])
        self.hermes.admit()
        self.assertEqual(self.hermes.turns, [("[Image #1] and [Image #2] like this", [first, second])])
        (user,) = self.users()
        self.assertEqual(user.images, ("[Image #1]", "[Image #2]"))
        rows = lines_text(block_rows(user, 60, DEFAULT_THEME))
        # Under the prompt, behind its painted rail cell: one row for each image.
        self.assertEqual([row.rstrip() for row in rows[-2:]], ["    ⎿  [Image #1]", "    ⎿  [Image #2]"])
        self.assertEqual(self.hermes.held, [])

    def test_the_prompt_waits_for_hermes_to_answer_every_staging_before_it_goes(self) -> None:
        self.paste_image()
        self.app._on_input(Key(ENTER))  # nothing answered yet
        self.assertEqual(self.client.calls[-1][0], "image.attach_bytes")
        self.assertEqual(self.users(), [])  # the echo waits, to list only what Hermes took
        self.hermes.pump()
        self.assertEqual(self.hermes.waiting, ["[Image #1] "])

    def test_an_image_hermes_does_not_take_is_said_and_not_listed_and_the_prompt_still_goes(self) -> None:
        kept = self.paste_image()
        self.paste_image()
        self.app._on_input(Key(ENTER))
        stagings = [index for index, (method, _params) in enumerate(self.client.calls) if method == "image.attach_bytes"]
        self.hermes.answered = len(self.client.calls)  # this test answers the two stagings itself
        path = self.hermes.write(kept)
        self.hermes.held.append(path)
        self.app._on_response(Response(stagings[0] + 1, {"attached": True, "path": path}, None))
        self.app._on_response(Response(stagings[1] + 1, None, {"code": 4016, "message": "unsupported image"}))
        self.hermes.pump()
        self.hermes.admit()
        self.assertEqual(self.hermes.turns, [("[Image #1] [Image #2] ", [kept])])
        self.assertEqual(self.users()[-1].images, ("[Image #1]",))
        self.assertIn(IMAGE_NOT_SENT_NOTICE.format(label="[Image #2]", reason="unsupported image"),
                      notices(self.app, NOTICE_WARN))

    def test_a_prompt_sent_before_the_last_turn_was_admitted_never_lends_it_its_images(self) -> None:
        # Hermes still builds the agent for A: B, sent into the running turn, stages nothing until A is admitted, and
        # nor does a Ctrl+V meanwhile.
        self.app.busy_mode = "steer"
        first = self.paste_image()
        self.type("A")
        self.press(Key(ENTER))
        self.press(CTRL_V)
        self.assertEqual(self.shown(), "")  # its staging waits for A's admission
        self.assertEqual(self.hermes.held, list(self.hermes.files)[-1:])  # A's image alone
        self.hermes.admit()
        self.assertEqual(self.hermes.turns, [("[Image #1] A", [first])])
        second = list(self.hermes.files.values())[-1]
        self.assertEqual(self.shown(), "[Image #2] ")
        self.type("B")
        self.press(Key(ENTER))
        self.hermes.admit()
        self.assertEqual(self.hermes.turns[1], ("[Image #2] B", [second]))

    def test_a_queued_prompt_goes_with_its_images_and_never_with_the_drafts(self) -> None:
        self.app.turn_pending = True  # a turn runs: Enter queues
        first = self.paste_image()
        self.type("first")
        self.press(Key(ENTER))
        (line,) = self.app.queued
        self.assertEqual([image.label for image in line.images], ["[Image #1]"])
        self.paste_image()  # the next draft's
        self.hermes.complete()  # the running turn ends: the queued prompt goes
        self.hermes.admit()
        self.assertEqual(self.hermes.turns, [("[Image #1] first", [first])])
        self.assertEqual(self.shown(), "[Image #2] ")
        self.assertEqual(self.hermes.held, [])

    def test_up_takes_a_queued_prompt_back_with_its_tokens(self) -> None:
        self.app.turn_pending = True
        data = self.paste_image()
        self.type("first")
        self.press(Key(ENTER), Key(UP))
        self.assertEqual(self.shown(), "[Image #1] first")
        self.app.turn_pending = False
        self.press(Key(ENTER))
        self.hermes.admit()
        self.assertEqual(self.hermes.turns, [("[Image #1] first", [data])])

    def test_a_refused_prompt_leaves_hermes_holding_nothing(self) -> None:
        self.paste_image()
        self.app._on_input(Key(ENTER))
        self.hermes.pump(len(self.client.calls))  # the staging is answered, so the prompt goes
        (submit,) = [index for index, (method, _params) in enumerate(self.client.calls) if method == "prompt.submit"]
        self.hermes.answered = len(self.client.calls)
        self.app._on_response(Response(submit + 1, None, {"code": 4009, "message": "busy"}))
        self.hermes.pump()
        self.assertEqual(self.hermes.held, [])
        self.assertEqual(self.methods()[-1], "image.detach")

    def test_a_turn_that_ends_before_hermes_admits_it_leaves_hermes_holding_nothing(self) -> None:
        self.paste_image()
        self.press(Key(ENTER))
        self.app._on_event(Event("error", SID, {"message": "the agent did not build"}))
        self.hermes.pump()
        self.assertEqual(self.hermes.held, [])

    def test_a_new_session_holds_nothing_and_the_next_prompt_stages_from_the_tuis_bytes(self) -> None:
        data = self.paste_image()
        self.app._enter_session({"session_id": SID, "stored_session_id": "stored-2", "info": {}})
        self.hermes.held = []  # whatever the old session staged went with it
        self.assertEqual(self.shown(), "[Image #1] ")
        self.press(Key(ENTER))
        self.hermes.admit()
        self.assertEqual(self.hermes.turns, [("[Image #1] ", [data])])

    def test_a_staging_answered_after_a_new_gateway_sends_nothing(self) -> None:
        self.paste_image()
        self.app._on_input(Key(ENTER))
        self.app.image_epoch += 1  # what `_respawn_gateway` and `_enter_session` do
        self.hermes.pump()
        self.assertEqual(self.hermes.waiting, [])


class GateTests(ImageTestCase):
    """The review's reproductions, with Hermes admitting a turn at once (WARM) and after the agent build (COLD)."""

    def test_a_paste_right_after_enter_never_rides_that_prompt(self) -> None:
        for warm in (True, False):
            with self.subTest(warm=warm):
                self.setUp(warm)
                first = self.paste_image()
                self.type(" first")
                self.app._on_input(Key(ENTER))
                self.app._on_input(CTRL_V)  # before any answer to the staging
                self.hermes.pump()
                if not warm:
                    self.hermes.admit()
                self.assertEqual(self.hermes.turns, [("[Image #1]  first", [first])])
                second = list(self.hermes.files.values())[-1]
                self.assertEqual(self.shown(), "[Image #2] ")
                self.assertEqual(self.hermes.held, [])
                self.hermes.complete()
                self.press(Key(ENTER))
                if not warm:
                    self.hermes.admit()
                self.assertEqual(self.hermes.turns[1], ("[Image #2] ", [second]))

    def test_enter_before_a_pastes_answer_waits_for_it_and_goes_with_that_image(self) -> None:
        # Case D: the person pasted, then sent at once; the image is meant for that prompt, as in Claude Code.
        for name, intake in (("Ctrl+V", CTRL_V), ("a dropped path", Paste("/h/images/drop.png"))):
            for warm in (True, False):
                with self.subTest(name, warm=warm):
                    self.setUp(warm)
                    self.type("describe this")
                    self.app._on_input(intake)
                    self.app._on_input(Key(ENTER))  # the intake is not answered yet: the prompt waits for it
                    self.assertEqual(len(self.client.calls), 1)
                    self.hermes.pump()
                    if not warm:
                        self.hermes.admit()
                    image = list(self.hermes.files.values())[0]
                    self.assertEqual(self.hermes.turns, [("describe this [Image #1]", [image])])
                    self.assertEqual(self.users()[-1].images, ("[Image #1]",))
                    self.assertEqual(self.shown(), "")
                    self.assertEqual(self.hermes.held, [])

    def test_a_prompt_queued_before_a_pastes_answer_goes_with_that_image(self) -> None:
        self.app.turn_pending = True  # a turn runs: Enter queues
        self.type("after this")
        self.app._on_input(CTRL_V)
        self.app._on_input(Key(ENTER))
        self.hermes.pump()
        (line,) = self.app.queued
        self.assertEqual((line.text, [image.label for image in line.images]), ("after this [Image #1]", ["[Image #1]"]))
        self.assertEqual(self.shown(), "")
        self.hermes.complete()
        self.hermes.admit()
        self.assertEqual(self.hermes.turns, [("after this [Image #1]", [list(self.hermes.files.values())[0]])])

    def test_a_submit_held_while_the_turn_ends_goes_once_its_paste_is_answered(self) -> None:
        self.app.turn_pending = True
        self.type("after this")
        self.app._on_input(CTRL_V)
        self.app._on_input(Key(ENTER))  # held: the paste is out
        self.app._on_event(Event("message.complete", SID, {"text": "done"}))  # the turn ends before the answer
        self.assertEqual(self.methods("prompt."), [])
        self.hermes.pump()
        self.hermes.admit()
        self.assertEqual(self.hermes.turns, [("after this [Image #1]", [list(self.hermes.files.values())[0]])])

    def test_esc_gives_back_a_submit_held_for_its_paste_and_the_image_joins_the_draft(self) -> None:
        self.type("describe this")
        self.app._on_input(CTRL_V)
        self.app._on_input(Key(ENTER))
        self.app._on_input(Key(ESCAPE))  # before the paste answers
        self.assertEqual(self.shown(), "describe this")
        self.hermes.pump()
        self.assertEqual(self.shown(), "describe this [Image #1] ")
        self.assertEqual(self.methods("prompt."), [])
        self.assertNotIn(IMAGE_WAIT_LINE, self.screen())

    def test_a_one_line_text_paste_right_before_enter_joins_that_prompt(self) -> None:
        for warm in (True, False):
            with self.subTest(warm=warm):
                self.setUp(warm)
                type_text(self.app, "describe ")
                self.app._on_input(Paste("the second paragraph"))  # offered to detect_drop first: an intake
                self.app._on_input(Key(ENTER))
                self.hermes.pump()
                if not warm:
                    self.hermes.admit()
                self.assertEqual(self.hermes.turns, [("describe the second paragraph", [])])
                self.assertEqual(self.shown(), "")

    def test_a_text_paste_hermes_refuses_to_look_at_still_joins_the_held_prompt(self) -> None:
        type_text(self.app, "describe ")
        self.app._on_input(Paste("the second paragraph"))
        self.app._on_input(Key(ENTER))
        (drop,) = [index for index, (method, _params) in enumerate(self.client.calls) if method == "input.detect_drop"]
        self.hermes.answered = len(self.client.calls)
        self.app._on_response(Response(drop + 1, None, {"code": 5000, "message": "detect failed"}))
        self.hermes.pump()
        self.hermes.admit()
        self.assertEqual(self.hermes.turns, [("describe the second paragraph", [])])

    def test_an_armed_ctrl_c_over_a_new_draft_does_not_exit_past_a_held_submit(self) -> None:
        self.app._on_input(ctrl("c"))  # on the empty composer: arms the exit
        self.assertIsNotNone(self.app.exit_armed_at)
        type_text(self.app, "describe this")
        self.app._on_input(CTRL_V)
        self.app._on_input(Key(ENTER))  # held for its paste
        type_text(self.app, "next")
        self.app._on_input(ctrl("c"))
        self.assertIsNone(self.app.exit_code)
        self.assertEqual(self.shown(), "")  # the draft is cleared, as any Ctrl+C over a draft
        self.hermes.pump()
        self.hermes.admit()
        self.assertEqual([text for text, _files in self.hermes.turns], ["describe this [Image #1]"])

    def test_with_a_submit_held_the_info_line_does_not_name_an_exit_the_press_would_not_make(self) -> None:
        for draft in ("next", ""):
            with self.subTest(draft=draft):
                self.setUp()
                self.app._on_input(ctrl("c"))  # arms the exit
                type_text(self.app, "describe this")
                self.app._on_input(CTRL_V)
                self.app._on_input(Key(ENTER))  # held for its paste
                type_text(self.app, draft)
                self.assertNotIn(EXIT_HINT, info_row_of(drawn(self.app)))
                self.app._on_input(ctrl("c"))  # clears the draft, or gives the held submit back
                self.assertIsNone(self.app.exit_code)

    def test_ctrl_c_with_no_turn_running_gives_a_held_submit_back_and_arms_no_exit(self) -> None:
        type_text(self.app, "describe this")
        self.app._on_input(CTRL_V)
        self.app._on_input(Key(ENTER))
        self.app._on_input(ctrl("c"))
        self.assertEqual(self.shown(), "describe this")
        self.assertIsNone(self.app.exit_armed_at)
        self.hermes.pump()
        self.assertEqual(self.methods("prompt."), [])
        self.assertEqual(self.shown(), "describe this [Image #1] ")

    def test_an_interrupt_gives_a_held_submit_back(self) -> None:
        self.app.transcript.running = True  # a turn runs
        type_text(self.app, "describe this")
        self.app._on_input(CTRL_V)
        self.app._on_input(Key(ENTER))
        self.app._on_input(ctrl("c"))  # interrupts the turn, and the held submit comes back
        self.assertEqual(self.shown(), "describe this")
        self.assertEqual(len(self.methods("session.interrupt")), 1)
        self.hermes.pump()
        self.assertEqual(self.methods("prompt."), [])

    def test_a_session_switch_gives_a_held_submit_back_with_a_notice(self) -> None:
        type_text(self.app, "describe this")
        self.app._on_input(CTRL_V)
        self.app._on_input(Key(ENTER))
        self.app._enter_session({"session_id": SID, "stored_session_id": "stored-2", "info": {}})
        self.assertEqual(self.shown(), "describe this")
        self.assertIn(UNSENT_BACK_NOTICE.format(why=UNSENT_BACK_SWITCH), notices(self.app, NOTICE_WARN))
        self.assertNotIn(IMAGE_WAIT_LINE, self.screen())

    def test_a_second_submit_waits_behind_a_held_one_and_they_go_in_order(self) -> None:
        self.app.turn_pending = True  # a turn runs: both queue, in the order they were sent
        type_text(self.app, "first")
        self.app._on_input(CTRL_V)
        self.app._on_input(Key(ENTER))
        type_text(self.app, "second")  # the paste is still out
        self.app._on_input(Key(ENTER))
        self.hermes.pump()
        self.assertEqual([line.text for line in self.app.queued], ["first [Image #1]", "second"])

    def test_a_submit_held_for_two_pastes_goes_once_both_are_answered_with_both(self) -> None:
        type_text(self.app, "compare")
        self.app._on_input(CTRL_V)
        self.app._on_input(CTRL_V)
        self.app._on_input(Key(ENTER))
        self.hermes.pump()
        self.hermes.admit()
        first, second = list(self.hermes.files.values())[:2]
        self.assertEqual(self.hermes.turns, [("compare [Image #1] [Image #2]", [first, second])])

    def test_a_held_ctrl_enter_whose_paste_brought_no_image_still_steers(self) -> None:
        self.app.transcript.running = True
        type_text(self.app, "look at b")
        self.app._on_input(CTRL_V)
        self.app._on_input(Key(ENTER, ctrl=True))
        (paste,) = [index for index, (method, _params) in enumerate(self.client.calls) if method == "clipboard.paste"]
        self.hermes.answered = len(self.client.calls)
        self.app._on_response(Response(paste + 1, {"attached": False, "message": "No image found in clipboard"}, None))
        self.assertEqual(self.client.calls[-1], ("session.steer", {"session_id": SID, "text": "look at b"}))

    def test_a_prompt_waiting_on_a_paste_says_so_under_the_queue_with_the_time_once_it_is_long(self) -> None:
        now = [100.0]
        self.app.clock = lambda: now[0]
        self.type("describe this")
        self.app._on_input(CTRL_V)
        self.app._on_input(Key(ENTER))
        screen = self.screen()
        self.assertIn(IMAGE_WAIT_LINE, screen)
        self.assertNotIn(f"{IMAGE_WAIT_LINE} ", screen)
        now[0] += 5.0
        self.assertIn(f"{IMAGE_WAIT_LINE} 5s", self.screen())
        self.hermes.pump()
        self.assertNotIn(IMAGE_WAIT_LINE, self.screen())

    def test_a_paste_hermes_never_answers_holds_the_prompt_only_until_it_expires(self) -> None:
        now = [100.0]
        self.app.clock = lambda: now[0]
        self.type("describe this")
        self.app._on_input(CTRL_V)
        self.app._on_input(Key(ENTER))
        self.hermes.answered = len(self.client.calls)  # the paste is never answered
        now[0] += 10_000.0
        self.app._expire_calls()
        self.assertEqual(self.client.calls[-1], ("prompt.submit", {"session_id": SID, "text": "describe this"}))
        self.assertNotIn(IMAGE_WAIT_LINE, self.screen())

    def test_a_staging_hermes_never_answers_is_said_and_the_prompt_goes_without_it(self) -> None:
        now = [100.0]
        self.app.clock = lambda: now[0]
        self.paste_image()
        self.type("x")
        self.app._on_input(Key(ENTER))
        now[0] += 10_000.0
        self.app._expire_calls()  # once crashed the TUI: the expiry handler took the seconds for the image
        self.hermes.answered = len(self.client.calls)
        self.assertIn(IMAGE_NOT_SENT_NOTICE.format(label="[Image #1]", reason="no answer"), notices(self.app, NOTICE_WARN))
        self.assertEqual(self.client.calls[-1][0], "prompt.submit")
        self.assertEqual(self.client.calls[-1][1]["text"], "[Image #1] x")
        self.assertEqual(self.users()[-1].images, ())

    def test_esc_while_a_prompt_stages_takes_it_back_and_sends_nothing(self) -> None:
        self.paste_image()
        self.type("go")
        self.app._on_input(Key(ENTER))
        self.app._on_input(Key(ESCAPE))  # the staging is not answered yet
        self.assertEqual(self.shown(), "[Image #1] go")
        self.assertEqual(len(self.app.composer.images), 1)
        self.assertFalse(self.app._busy())
        self.assertFalse(self.app.interrupting)
        self.hermes.pump()  # the staging is answered now: what Hermes took for it is detached
        self.assertEqual(self.methods("session.interrupt"), [])
        self.assertEqual(self.methods("prompt.submit"), [])
        self.assertEqual(self.hermes.held, [])
        self.press(Key(ENTER))
        self.hermes.admit()
        self.assertEqual(self.hermes.turns, [("[Image #1] go", [list(self.hermes.files.values())[1]])])

    def test_a_turn_hermes_starts_on_its_own_while_a_prompt_stages_does_not_open_the_gate(self) -> None:
        # A wake-up or a notification turn: its `message.start` says nothing about this prompt's images.
        self.paste_image()
        self.app._on_input(Key(ENTER))  # staging out, not answered
        self.app._on_event(Event("message.start", SID, {}))
        self.app._on_input(CTRL_V)
        self.assertNotEqual(self.client.calls[-1][0], "clipboard.paste")

    def test_a_queued_answer_takes_the_images_so_the_next_paste_goes_at_once(self) -> None:
        self.app.busy_mode = "steer"
        self.app.transcript.running = True  # a turn runs: the prompt goes into it, and Hermes queues it
        self.paste_image()
        self.type("also this")
        self.app._on_input(Key(ENTER))
        self.hermes.pump(len(self.client.calls))  # the staging; the submit stays unanswered here
        (submit,) = [index for index, (method, _params) in enumerate(self.client.calls) if method == "prompt.submit"]
        self.hermes.answered = len(self.client.calls)
        self.app._on_response(Response(submit + 1, {"status": "queued"}, None))
        self.app._on_input(CTRL_V)
        self.assertEqual(self.client.calls[-1][0], "clipboard.paste")

    def test_a_turn_never_admitted_and_never_ended_does_not_hold_the_next_prompt(self) -> None:
        self.paste_image()
        self.press(Key(ENTER))  # staged and sent; Hermes never starts the turn
        self.app.turn_pending = False  # the person interrupted it, and nothing Hermes sent ended it
        self.type("next")
        self.press(Key(ENTER))
        self.assertEqual(self.hermes.waiting[-1], "next")
        self.assertEqual(self.hermes.held, [])  # what the first left staged was detached

    def test_a_staging_answered_after_a_session_switch_touches_nothing_in_the_new_session(self) -> None:
        self.paste_image()
        self.type("A")
        self.app._on_input(Key(ENTER))  # A's staging is out, unanswered
        stale = [index for index, (method, _params) in enumerate(self.client.calls) if method == "image.attach_bytes"]
        self.hermes.answered = len(self.client.calls)
        self.app._enter_session({"session_id": SID, "stored_session_id": "stored-2", "info": {}})
        self.app._on_input(ctrl("u"))  # A came back to the draft: clear it, and send B in the new session
        self.paste_image()
        self.type("B")
        self.app._on_input(Key(ENTER))  # B stages now
        before = len(self.client.calls)
        self.app._on_response(Response(stale[0] + 1, {"attached": True, "path": "/old/upload_1.png"}, None))
        self.assertEqual(self.client.calls[before:], [])  # no detach in the new session, and the gate stays closed
        self.app._on_input(CTRL_V)
        self.assertEqual(self.client.calls[before:], [])

    def test_an_answer_to_an_admitted_prompt_never_opens_the_gate_for_the_next_one(self) -> None:
        self.paste_image()
        self.app._on_input(Key(ENTER))
        self.hermes.pump(len(self.client.calls))  # the staging
        (submit,) = [index for index, (method, _params) in enumerate(self.client.calls) if method == "prompt.submit"]
        self.hermes.answered = len(self.client.calls)  # its answer comes late
        self.app._on_event(Event("message.start", SID, {}))
        self.app._on_event(Event("message.complete", SID, {"text": "done"}))
        self.paste_image()
        self.app._on_input(Key(ENTER))  # the next prompt stages, unanswered
        self.hermes.answered = len(self.client.calls)
        self.app._on_response(Response(submit + 1, {"status": "queued"}, None))
        before = len(self.client.calls)
        self.app._on_input(CTRL_V)
        self.assertEqual(self.client.calls[before:], [])  # the staging prompt still holds the gate

    def test_a_turn_that_ends_while_the_next_prompt_stages_leaves_the_gate_closed(self) -> None:
        self.app.busy_mode = "steer"
        self.app.transcript.running = True  # a turn runs: the prompt goes into it
        self.paste_image()
        self.app._on_input(Key(ENTER))  # staging out, unanswered
        self.hermes.answered = len(self.client.calls)
        self.app.transcript.running = False
        self.app._on_event(Event("message.complete", SID, {"text": "done"}))
        before = len(self.client.calls)
        self.app._on_input(CTRL_V)
        self.assertEqual(self.client.calls[before:], [])

    def test_a_session_switch_while_a_prompt_stages_gives_it_back_and_a_paste_goes_in_the_new_one(self) -> None:
        self.paste_image()
        self.type("x")
        self.app._on_input(Key(ENTER))
        self.app._enter_session({"session_id": SID, "stored_session_id": "stored-2", "info": {}})
        self.assertEqual(self.shown(), "[Image #1] x")
        self.assertIn(UNSENT_BACK_NOTICE.format(why=UNSENT_BACK_SWITCH), notices(self.app, NOTICE_WARN))
        self.hermes.pump()
        self.assertEqual(self.methods("prompt.submit"), [])
        self.app._on_input(CTRL_V)
        self.assertEqual(self.client.calls[-1][0], "clipboard.paste")

    def test_an_unreadable_staged_image_makes_no_token_and_is_let_go_of(self) -> None:
        with patch("omh.tui.app.read_image", lambda path: None):
            self.press(CTRL_V)
        self.assertEqual(self.app.composer.images, {})
        self.assertEqual(self.hermes.held, [])
        self.assertTrue(any("could not be read for its token" in said for said in notices(self.app, NOTICE_WARN)))


class RespawnTests(unittest.TestCase):
    """A new gateway holds no image: a prompt that was staging comes back, and the next send stages from the TUI."""

    def test_a_respawn_gives_back_the_prompt_that_was_staging_and_the_next_send_stages_from_the_tuis_bytes(self) -> None:
        from test_tui_respawn import crash, crashing

        app, old, spawner, _now = crashing()
        image = Attachment("/h/images/clip.png", "clip.png", "", "[Image #1]", PNG)
        app.composer.insert_image(image.label, image)
        type_text(app, "x")
        app._on_input(Key(ENTER))
        self.assertEqual(old.calls[-1][0], "image.attach_bytes")
        crash(app, old)
        new = spawner.made[0]
        self.assertEqual(app.composer.expanded(), "[Image #1] x")
        self.assertIn(UNSENT_BACK_NOTICE.format(why=UNSENT_BACK_RESPAWN), notices(app, NOTICE_WARN))
        app._on_input(Key(ENTER))
        (stage,) = new.named("image.attach_bytes")
        self.assertEqual(base64.b64decode(stage["content_base64"]), PNG)


    def test_a_respawn_gives_back_a_submit_held_for_its_paste(self) -> None:
        from test_tui_respawn import crash, crashing

        app, old, spawner, _now = crashing()
        type_text(app, "describe this")
        app._on_input(CTRL_V)
        app._on_input(Key(ENTER))  # held: the paste is out on the old gateway
        crash(app, old)
        self.assertEqual(app.composer.expanded(), "describe this")
        self.assertIn(UNSENT_BACK_NOTICE.format(why=UNSENT_BACK_RESPAWN), notices(app, NOTICE_WARN))
        self.assertEqual(spawner.made[0].named("prompt.submit"), [])

    def test_a_paste_the_old_gateway_never_answered_does_not_hold_a_prompt_on_the_new_one(self) -> None:
        from test_tui_respawn import crash, crashing

        app, old, spawner, _now = crashing()
        app._on_input(CTRL_V)
        self.assertEqual(old.calls[-1][0], "clipboard.paste")  # out, and lost with the old gateway
        crash(app, old)
        type_text(app, "x")
        app._on_input(Key(ENTER))
        self.assertEqual(spawner.made[0].named("prompt.submit"), [{"session_id": app.sid, "text": "x"}])

class KeptTokenTests(ImageTestCase):
    """A line that sends no prompt takes no image: its tokens come back to the draft, and a notice says so."""

    def test_a_shell_line_and_a_printing_command_give_their_tokens_back(self) -> None:
        for name, text, answer in (("!", "!ls ", None), ("/usage", "/usage ", {"output": "12 calls"})):
            with self.subTest(name):
                self.setUp()
                self.type(text)
                data = self.paste_image()
                self.press(Key(ENTER))
                if answer is not None:
                    self.hermes.respond("slash.exec", answer)
                self.assertEqual(self.shown(), "[Image #1] ")
                ((_label, image),) = self.app.composer.images.values()
                self.assertEqual(image.data, data)
                self.assertTrue(any("takes no image: [Image #1] stay in the composer" in said
                                    for said in notices(self.app)), notices(self.app))
                self.assertEqual(self.methods("image.attach_bytes"), [])

    def test_ctrl_enter_with_an_image_is_a_prompt_not_a_steer(self) -> None:
        self.app.turn_pending = True
        self.paste_image()
        self.type("this one")
        self.press(Key(ENTER, ctrl=True))
        self.assertEqual(self.methods("session.steer"), [])
        self.assertEqual([image.label for image in self.app.queued[-1].images], ["[Image #1]"])


    def test_the_send_now_key_leaves_a_queued_prompt_with_images_for_the_turns_end(self) -> None:
        self.app.turn_pending = True
        data = self.paste_image()
        self.type("first")
        self.press(Key(ENTER))
        self.press(Key(ENTER, ctrl=True))  # the send-now key on an empty composer: a steer would drop the image
        self.assertEqual(self.methods("session.steer"), [])
        self.assertEqual(len(self.app.queued), 1)
        self.hermes.complete()
        self.hermes.admit()
        self.assertEqual(self.hermes.turns, [("[Image #1] first", [data])])


class CommandTests(ImageTestCase):
    def test_a_plan_mode_prompt_goes_with_its_images(self) -> None:
        self.app.plan_mode = True
        data = self.paste_image()
        self.type("plan this")
        self.press(Key(ENTER))
        self.assertEqual(self.client.calls[-1], ("slash.exec", {"command": "plan [Image #1] plan this", "session_id": SID}))
        self.hermes.respond("slash.exec", error={"code": contract.NOT_MINE, "message": "pending-input command"})
        self.hermes.respond("command.dispatch", {"type": "send", "message": "Task to plan:\n[Image #1] plan this"})
        self.hermes.admit()
        self.assertEqual(self.hermes.turns, [("Task to plan:\n[Image #1] plan this", [data])])

    def test_two_commands_in_flight_each_send_their_own_images(self) -> None:
        self.type("/skill-a ")
        first = self.paste_image()
        self.press(Key(ENTER))
        self.type("/skill-b ")
        second = self.paste_image()
        self.press(Key(ENTER))
        for _ in range(2):
            self.hermes.respond("slash.exec", error={"code": contract.NOT_MINE, "message": "skill"})
        self.hermes.respond("command.dispatch", {"type": "skill", "message": "A: [Image #1]"})
        self.hermes.admit()
        self.hermes.complete()
        self.hermes.respond("command.dispatch", {"type": "skill", "message": "B: [Image #2]"})
        self.hermes.admit()
        self.assertEqual(self.hermes.turns, [("A: [Image #1]", [first]), ("B: [Image #2]", [second])])


class NoTokenCharacterLeavesTests(ImageTestCase):
    def test_history_browsing_keeps_the_drafts_tokens_and_no_token_character_reaches_any_sink(self) -> None:
        remembered: list[str] = []
        self.app._remember = remembered.append  # type: ignore[method-assign]  # what goes to Hermes' history file
        self.app.composer.on_record = remembered.append
        self.type("old prompt")
        self.press(Key(ENTER))
        self.hermes.admit()
        self.hermes.complete()
        self.type("look ")
        data = self.paste_image()
        self.press(Key(UP))
        self.type("!")
        self.press(Key(DOWN))
        self.assertEqual(self.shown(), "look [Image #1] ")
        self.press(Key(ENTER))
        self.hermes.admit()
        self.hermes.complete()
        self.assertEqual(self.hermes.turns[-1], ("look [Image #1] ", [data]))
        self.type("/usage ")
        self.paste_image()
        self.press(Key(ENTER))
        self.app._on_input(ctrl("c"))
        sinks = [*map(repr, self.client.calls), *remembered, *self.app.composer.history]
        for item in sinks:
            self.assertFalse(any(ord(ch) in TOKEN_RANGE for ch in item), item)


class ReadImageTests(unittest.TestCase):
    """The TUI reads a file Hermes named only as a regular file, without following a link or waiting on a FIFO."""

    def test_only_a_regular_file_within_the_cap_is_read(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            regular = Path(home, "shot.png")
            regular.write_bytes(PNG)
            link = Path(home, "link.png")
            link.symlink_to(regular)
            self.assertEqual(read_image(str(regular)), PNG)
            self.assertIsNone(read_image(str(link)))
            self.assertIsNone(read_image(str(Path(home, "gone.png"))))
            empty = Path(home, "empty.png")
            empty.write_bytes(b"")
            self.assertIsNone(read_image(str(empty)))
            with patch("omh.tui.app.IMAGE_KEEP_BYTES", len(PNG) - 1):
                self.assertIsNone(read_image(str(regular)))

    def test_a_link_is_refused_where_open_cannot_refuse_it(self) -> None:
        # Windows has no O_NOFOLLOW; the link is refused by its own entry before the open.
        with tempfile.TemporaryDirectory() as home:
            regular = Path(home, "shot.png")
            regular.write_bytes(PNG)
            link = Path(home, "link.png")
            link.symlink_to(regular)
            with patch("omh.tui.app.os.O_NOFOLLOW", 0, create=True):
                self.assertEqual(read_image(str(regular)), PNG)
                self.assertIsNone(read_image(str(link)))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "no FIFOs here")
    def test_a_fifo_is_refused_without_waiting_for_a_writer(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            fifo = Path(home, "fifo.png")
            os.mkfifo(fifo)
            self.assertIsNone(read_image(str(fifo)))  # returns at once: no writer is waited for

    def test_a_directory_or_a_fifo_is_never_read(self) -> None:
        opened: list[int] = []
        real = os.fdopen

        def watch(fd: int, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
            opened.append(fd)
            return real(fd, *args, **kwargs)

        with tempfile.TemporaryDirectory() as home, patch("omh.tui.app.os.fdopen", watch):
            self.assertIsNone(read_image(home))
            if hasattr(os, "mkfifo"):
                fifo = Path(home, "fifo.png")
                os.mkfifo(fifo)
                self.assertIsNone(read_image(str(fifo)))
        self.assertEqual(opened, [])  # refused by what fstat said, before any read


class AttachmentShapeTests(ImageTestCase):
    def test_the_label_and_the_bytes_ride_on_the_attachment_the_composer_holds(self) -> None:
        data = self.paste_image()
        ((label, image),) = self.app.composer.images.values()
        self.assertEqual(label, "[Image #1]")
        self.assertIsInstance(image, Attachment)
        self.assertEqual((image.label, image.data), ("[Image #1]", data))


if __name__ == "__main__":
    unittest.main()

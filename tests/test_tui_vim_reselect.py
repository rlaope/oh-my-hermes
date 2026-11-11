"""RS-1–RS-5 and retained character/line gv contracts."""
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from contextlib import ExitStack
from functools import partial

from test_tui_vim_mode import Composer, ESC, CHIP_TEXT, keys, normal
from test_tui_vim_character_visual import snapshot, selected_text, vim_app
from test_tui_modes import SID, type_text, answer
from omh.tui.keys import CHAR, ENTER, ESCAPE, Key, Paste


def geometry(c):
    return c.visual_anchor, c.visual_head, c.visual_line, c.visual_span


def saved(text="abc\ndef", at=2, command="vh"):
    c = normal(text, at)
    keys(c, command)
    expected = geometry(c)
    c.handle(ESC)
    return c, expected


class TestRS(unittest.TestCase):
    def test_restore(self):
        for command in ("vh", "Vkg", "Vk", "vVkhv", "V"):
            c = normal("abc\ndef\nghi", 6)
            keys(c, command)
            c._drop_pending()
            expected = geometry(c)
            c.handle(ESC)
            keys(c, "G0")
            before = snapshot(c)
            keys(c, "999999gv")
            self.assertEqual(geometry(c), expected)
            self.assertTrue(c.visual)
            self.assertEqual(snapshot(c)[:1] + snapshot(c)[2:], before[:1] + before[2:])
            self.assertFalse(c.pending)
        c = normal("abc", 1)
        before = snapshot(c)
        keys(c, "9999gv")
        self.assertEqual(snapshot(c), before)
        self.assertFalse(c.visual)
        keys(c, "gxv")
        self.assertEqual(geometry(c), (1, 1, False, (1, 2)))

    def test_capture(self):
        for end in ("escape", "v", "y"):
            c = normal("abcd", 1)
            keys(c, "vl")
            expected = geometry(c)
            c.handle(ESC) if end == "escape" else keys(c, end)
            keys(c, "hgv")
            self.assertEqual(geometry(c), expected)
        c = normal("abc\n  def", 7)
        keys(c, "Vky")
        self.assertEqual(c.caret, 0)
        keys(c, "gv")
        self.assertEqual(geometry(c), (7, 2, True, (0, 9)))
        for command in ("vld", "vlcX"):
            c = normal("abcd", 1)
            keys(c, command)
            if not c.normal:
                c.handle(ESC)
            keys(c, "gv")
            self.assertFalse(c.visual)
        for command in ("vd", "vc"):
            c = normal("", 0)
            keys(c, command)
            if not c.normal:
                c.handle(ESC)
            keys(c, "gv")
            self.assertTrue(c.visual)
        c, expected = saved()
        old = c._saved_visual
        keys(c, "Vv")
        self.assertEqual(c._saved_visual, old)  # conversions are not exits
        c.handle(ESC)
        keys(c, "gv")
        self.assertNotEqual(geometry(c), expected)

    def test_generation(self):
        for mutate in (
            lambda c: keys(c, "x"), lambda c: keys(c, "rZ"),
            lambda c: c.handle(Paste("Q")), lambda c: c.insert_image("[Image]", object()),
            lambda c: c.replace(0, len(c.text), c.text), lambda c: c.restore("", []),
            lambda c: c._load(c.text), lambda c: c._clear(),
            lambda c: c.set_vim(True), lambda c: c.set_vim(False),
            lambda c: c.handle(Key(ENTER)), lambda c: c._history_back(),
        ):
            c, _ = saved()
            c.history = [c.text]
            old = c._generation
            mutate(c)
            self.assertGreater(c._generation, old)
            self.assertIsNone(c._saved_visual)
        c, _ = saved()
        original = c.text
        keys(c, "ix")
        c.handle(ESC)
        keys(c, "ugv")
        self.assertEqual(c.text, original)
        self.assertFalse(c.visual)
        c, expected = saved()
        old = c._generation
        keys(c, "9999hFZgx")  # navigation, failed find and unsupported follower
        c.handle(Key(CHAR, "z", ctrl=True))  # failed undo
        self.assertEqual(c._generation, old)
        keys(c, "gv")
        self.assertEqual(geometry(c), expected)
        for corrupt in ("generation", "map", "bounds", "negative"):
            c, _ = saved()
            if corrupt == "generation":
                c._generation += 1
            elif corrupt == "map":
                c.pastes["abc"] = "payload"
            else:
                g, a, h, line = c._saved_visual
                c._saved_visual = (g, a, 999 if corrupt == "bounds" else -1, line)
            before = snapshot(c)
            keys(c, "gv")
            self.assertFalse(c.visual)
            self.assertIsNone(c._saved_visual)
            self.assertEqual(snapshot(c), before)
        c = Composer(vim=True)
        c.handle(Paste(CHIP_TEXT))
        c.handle(ESC)
        keys(c, "0vy")
        c.pastes.clear()  # atom map revision changed without changing displayed text
        keys(c, "gv")
        self.assertFalse(c.visual)

    def test_metadata_revision_and_identical_replay(self):
        # In-place mutations and ABA changes cannot resurrect completed ranges.
        for name in ("pastes", "images"):
            for method in ("set", "update", "ior", "delete", "clear", "pop", "popitem", "setdefault"):
                with self.subTest(map=name, method=method):
                    c = normal("abc", 1)
                    mapping = getattr(c, name)
                    payload = "payload" if name == "pastes" else ("[Image]", object())
                    if method in ("delete", "clear", "pop", "popitem"):
                        mapping["unused"] = payload
                    keys(c, "vl")
                    c.handle(ESC)
                    generation = c._generation
                    if method == "set":
                        mapping["unused"] = payload
                        del mapping["unused"]
                    elif method == "update":
                        mapping.update({"unused": payload})
                    elif method == "ior":
                        mapping |= {"unused": payload}
                    elif method == "delete":
                        del mapping["unused"]
                    elif method == "setdefault":
                        mapping.setdefault("unused", payload)
                    else:
                        getattr(mapping, method)("unused") if method == "pop" else getattr(mapping, method)()
                    self.assertGreater(c._generation, generation)
                    self.assertIsNone(c._saved_visual)
                    before = snapshot(c)
                    keys(c, "999999gv")
                    self.assertEqual(snapshot(c), before)
                    self.assertFalse(c.visual)
        c, expected = saved()
        generation = c._generation
        c.pastes.clear()
        c.pastes.update({})
        self.assertEqual(c._generation, generation)  # no-op map calls
        keys(c, "gv")
        self.assertEqual(geometry(c), expected)
        # Detached replay deletes/reinserts the same bytes; live invalidation
        # must not depend on final-value inequality or candidate callbacks.
        c = normal("xbc", 0)
        keys(c, "vc" + "a")
        c.handle(ESC)
        keys(c, "vy")
        generation = c._generation
        keys(c, ".")
        self.assertEqual(c.text, "abc")
        self.assertGreater(c._generation, generation)
        self.assertIsNone(c._saved_visual)
        keys(c, "gv")
        self.assertFalse(c.visual)
        # The compact record retains no draft/metadata/boundary snapshots.
        c, _ = saved("a" * 10000, 5)
        self.assertEqual(len(c._saved_visual), 4)
        self.assertTrue(all(isinstance(value, (int, bool)) for value in c._saved_visual))
        # Native g motions still normalize stale-chip carets on completion.
        for command, endpoint in (("gg", 0), ("ge", 0), ("gE", 0)):
            c, _ = saved()
            c.pastes["abc"] = "payload"
            keys(c, command)
            self.assertEqual(c.caret, endpoint)
            self.assertIn(c.caret, c._atoms()[1])

    def test_cycle(self):
        for selection in ("vh", "Vk"):
            for operator in ("d", "c", "y"):
                direct = normal("abc\ndef\nghi\njkl", 6)
                restored = normal(direct.text, 6)
                keys(direct, selection)
                keys(restored, selection)
                expected = geometry(restored)
                for _ in range(5):
                    restored.handle(ESC)
                    keys(restored, "G0gv")
                    self.assertEqual(geometry(restored), expected)
                keys(restored, "gv")  # unsupported while active
                self.assertEqual(geometry(restored), expected)
                keys(direct, operator)
                keys(restored, operator)
                if operator == "c":
                    for c in (direct, restored):
                        keys(c, "XY")
                        c.handle(Key("left"))
                        c.handle(ESC)
                self.assertEqual(snapshot(direct), snapshot(restored))
                keys(direct, "G2.")
                keys(restored, "G2.")
                self.assertEqual(snapshot(direct), snapshot(restored))
                keys(restored, "gv")
                if operator != "y":
                    self.assertFalse(restored.visual)
        # Actual restored c descriptors inherit bounded admission before any
        # snapshot/token/text allocation, not merely a prerequisite fixture.
        from omh.tui.vim_repeat import Limits, preflight
        for selection in ("vl", "V"):
            c = normal("abcdef\nghij", 0)
            keys(c, selection)
            c.handle(ESC)
            keys(c, "gvc" + "Z" * 257)
            c.handle(ESC)
            c.caret = 0
            before = snapshot(c), c._generation, c._saved_visual, c._paste_count, c._token_count
            keys(c, "9999")
            with ExitStack() as stack:
                stack.enter_context(mock.patch("omh.tui.vim_repeat.preflight",
                    wraps=partial(preflight, limits=Limits(materialized_bytes=256))))
                for method in ("_state", "_new_token", "_set"):
                    stack.enter_context(mock.patch.object(Composer, method,
                        side_effect=AssertionError("allocation before admission: " + method)))
                keys(c, ".")
            self.assertEqual((snapshot(c), c._generation, c._saved_visual,
                              c._paste_count, c._token_count), before)
            self.assertTrue(c.take_bell())
            self.assertFalse(c.take_bell())
        # Terminal insertion motion remains atom-relative after gv, and a
        # counted replay advances from each prior copy's terminal endpoint.
        c = normal("abcdef", 0)
        keys(c, "vl")
        c.handle(ESC)
        keys(c, "gvcXY")
        c.handle(Key("left"))
        c.handle(ESC)
        self.assertEqual((c.text, c.caret), ("XYcdef", 0))
        keys(c, "l2.")
        self.assertEqual((c.text, c.caret), ("XXYf", 1))
        keys(c, "u")
        self.assertEqual((c.text, c.caret), ("XYcdef", 1))
        c = normal("a\nb\nc\nd", 2)
        keys(c, "V")
        c.handle(ESC)
        keys(c, "gvcXY")
        c.handle(Key("left"))
        c.handle(ESC)
        self.assertEqual((c.text, c.caret), ("a\nXY\nc\nd", 2))
        keys(c, "G2.")
        self.assertEqual((c.text, c.caret), ("a\nXY\nc\nXY", 7))
        keys(c, "u")
        self.assertEqual(c.text, "a\nXY\nc\nd")

    def test_restored_replay_limits(self):
        from dataclasses import replace
        from omh.tui.composer import _Register, _RepeatChange, _TOKEN_FIRST, _TOKEN_LAST
        from omh.tui.vim_repeat import Limits, preflight
        for selection in ("vl", "V"):
            c = normal("abcdef\nghij", 0)
            keys(c, selection)
            c.handle(ESC)
            keys(c, "gvcXY")
            c.handle(ESC)
            descriptor = c._repeat_change
            for limits in (Limits(steps=0), Limits(materialized_bytes=0), Limits(atom_visits=0)):
                before = snapshot(c), c._generation, c._paste_count
                with ExitStack() as stack:
                    stack.enter_context(mock.patch("omh.tui.vim_repeat.preflight",
                        wraps=partial(preflight, limits=limits)))
                    for method in ("_state", "_set", "_new_token"):
                        stack.enter_context(mock.patch.object(Composer, method,
                            side_effect=AssertionError("allocation before admission")))
                    keys(c, ".")
                self.assertEqual((snapshot(c), c._generation, c._paste_count), before)
                self.assertTrue(c.take_bell())
            c._repeat_change = replace(descriptor, terminal=99999)
            before = snapshot(c), c._generation
            keys(c, ".")
            self.assertEqual((snapshot(c), c._generation), before)
            self.assertTrue(c.take_bell())
            c._repeat_change = descriptor
            # Restored selection itself is not put: image budgets and free
            # token union remain inherited when the subsequent captured put
            # transaction is attempted while completed geometry is available.
            token = chr(_TOKEN_FIRST)
            payload = ("[Image]", object())
            change = _RepeatChange("P", 1, register=_Register(token, {}, {token: payload}, False))
            c.images = {chr(code): payload for code in range(_TOKEN_FIRST, _TOKEN_LAST + 1)}
            keys(c, selection)
            c.handle(ESC)
            c._repeat_change = change
            before = snapshot(c), c._generation, c._saved_visual
            with mock.patch.object(Composer, "_new_token", side_effect=AssertionError("allocated exhausted token")):
                keys(c, ".")
            self.assertEqual((snapshot(c), c._generation, c._saved_visual), before)
            self.assertTrue(c.take_bell())
            c.images = {}
            c._repeat_change = change
            before = snapshot(c), c._generation
            keys(c, "513.")
            self.assertEqual((snapshot(c), c._generation), before)
            self.assertTrue(c.take_bell())

    def test_viewports(self):
        text = "0123456789abcdefghijKLMNOPQRST\nuvwxyz"
        for width, height, head in ((20, 8, 20), (100, 30, 33)):
            for mode in ("v", "V"):
                c = normal(text, 2)
                c.history = ["NEVER LOAD"]
                c.render(width, height, prompt="> ")
                keys(c, mode + "j")
                self.assertEqual(c.visual_head, head)
                expected = (2, head, mode == "V", (0, 31 if width == 20 else 37)
                            if mode == "V" else (2, head + 1))
                self.assertEqual(geometry(c), expected)
                visible = c.render(width, height, prompt="> ")
                highlighted = ("0123456789abcdefghijKLMNOPQRST␊" if width == 20 else
                               "0123456789abcdefghijKLMNOPQRST␊uvwxyz ") if mode == "V" else (
                               "23456789abcdefghijK" if width == 20 else
                               "23456789abcdefghijKLMNOPQRST␊uvw")
                self.assertEqual(selected_text(visible[0]), highlighted)
                self.assertEqual(visible[1], (1, 4))
                c.handle(ESC)
                keys(c, "gggv")
                self.assertEqual(geometry(c), expected)
                self.assertEqual(c.render(width, height, prompt="> "), visible)
                c.render(100 if width == 20 else 20, height)
                self.assertEqual(geometry(c), expected)
                keys(c, "9999k9999j")
                self.assertEqual(c.text, text)
                self.assertIsNone(c.history_index)

    def test_routing(self):
        for busy in (False, True):
            for escape in (ESC, Key(ESCAPE, alt=True, protocol=True)):
                app, client, clock = vim_app(busy=busy)
                type_text(app, "abvcd")
                app._on_input(ESC)
                type_text(app, "0vl")
                app._on_input(ESC)
                type_text(app, "g")
                app.escape_armed = ("exit", clock.now)
                app._on_input(escape)
                self.assertFalse(app.composer.pending)
                self.assertFalse(app.composer.visual)
                self.assertIsNone(app.escape_armed)
                type_text(app, "fv")
                self.assertEqual(app.composer.caret, 2)
                self.assertFalse(app.composer.visual)
                type_text(app, "gv")
                self.assertEqual(geometry(app.composer), (0, 1, False, (0, 2)))
                app._on_input(Key(ENTER))
                self.assertIsNone(app.composer._saved_visual)
                if busy:
                    self.assertEqual([x.text for x in app.queued], ["abvcd"])
                else:
                    self.assertEqual(client.named("prompt.submit")[-1]["text"], "abvcd")
        for restored in (False, True):
            app, client, _ = vim_app()
            type_text(app, "abc")
            app._on_input(ESC)
            type_text(app, "0vl")
            app._on_input(ESC)
            if restored:
                type_text(app, "gv")
            app._on_input(Key(CHAR, "v", ctrl=True))
            self.assertIsNone(app.composer._saved_visual)
            self.assertFalse(app.composer.visual)
            self.assertEqual(client.calls, [("clipboard.paste", {"session_id": SID})])
        c, _ = saved()
        c.masked = True
        self.assertIsNone(c._saved_visual)
        keys(c, "gv")
        self.assertFalse(c.visual)
        # Existing ownership matrix is inherited, not replaced by gv parsing.
        from test_tui_vim_character_visual import TestCV
        TestCV("test_routing").test_routing()

    def test_restored_app_owners(self):
        from omh.tui.keys import DOWN
        from omh.tui.gateway import ServerRequest
        from test_tui_vim_mode import CLARIFY
        for mode in ("v", "V"):
            for busy, enter in ((False, Key(ENTER)), (True, Key(ENTER)), (True, Key(ENTER, ctrl=True))):
                app, client, _ = vim_app(busy=busy)
                type_text(app, "abc")
                app._on_input(ESC)
                type_text(app, "0" + mode + "l")
                app._on_input(ESC)
                type_text(app, "gv")
                self.assertTrue(app.composer.visual)
                app._on_input(enter)
                self.assertFalse(app.composer.visual)
                self.assertIsNone(app.composer._saved_visual)
                self.assertEqual(app.composer.text, "")
                if busy and not enter.ctrl:
                    self.assertEqual([line.text for line in app.queued], ["abc"])
                    self.assertEqual(client.calls, [])
                else:
                    method = "session.redirect" if busy else "prompt.submit"
                    self.assertEqual(client.named(method)[-1]["text"], "abc")
            app, client, _ = vim_app(environ={"NO_COLOR": "1"})
            type_text(app, "abc")
            app._on_input(ESC)
            type_text(app, "0" + mode + "l")
            app._on_input(ESC)
            type_text(app, "gv")
            app._on_input(Key(CHAR, "v", ctrl=True))
            with tempfile.TemporaryDirectory() as directory:
                image = Path(directory) / "clipboard.png"
                image.write_bytes(b"\x89PNG\r\n\x1a\n")
                answer(app, client, {"attached": True, "path": str(image), "name": image.name})
            self.assertEqual(app.composer.expanded(), "a [Image #1] bc")
            self.assertEqual(len(app.composer.images), 1)
            self.assertEqual(len(client.named("clipboard.paste")), 1)
            self.assertIsNone(app.composer._saved_visual)
            self.assertFalse(app.composer.visual)
        # Front-picker and waiting-slot ownership with an actual saved range.
        app, client, clock = vim_app()
        type_text(app, "abc")
        app._on_input(ESC)
        type_text(app, "0vl")
        app._on_input(ESC)
        type_text(app, "g")
        from omh.tui.session_picker import SessionPicker, SessionRow
        app.picker = SessionPicker([SessionRow(SID, "title", "", 0.0, 1)], current=app.stored_id)
        app.picker.waiting = False
        before = snapshot(app.composer)
        type_text(app, "v")
        self.assertEqual(snapshot(app.composer), before)
        self.assertFalse(app.composer.visual)
        self.assertFalse(app.composer.pending)
        self.assertEqual(app.picker.query, "v")
        self.assertEqual(client.calls, [])
        app.picker = SessionPicker([SessionRow(SID, "title", "", 0.0, 1)],
                                  current=app.stored_id, waiting=True)
        app._on_input(Key(DOWN))
        self.assertFalse(app.picker.waiting)
        self.assertEqual(snapshot(app.composer), before)
        app, client, clock = vim_app()
        type_text(app, "draft")
        app._on_input(ESC)
        type_text(app, "0vl")
        app._on_input(ESC)
        app._on_server_request(ServerRequest("rs-question", "clarify", CLARIFY))
        clock.now += 1
        type_text(app, "gv")
        self.assertEqual(app.composer.text, "gv")
        self.assertFalse(app.composer.visual)
        self.assertIsNone(app.composer._saved_visual)

    def test_docs(self):
        from omh.tui.shortcuts import SHORTCUTS
        doc = (Path(__file__).resolve().parents[1] / "docs/INSTALLATION.md").read_text(encoding="utf-8")
        for phrase in ("gv", "generation", "NORMAL-only", "anchor/head", "9999gv", "paste/image metadata",
                       "undo/redo", "history/draft replacement", "masking", "failed/no-op", "never block visual",
                       "Enter sends unchanged text", "clipboard image"):
            self.assertIn(phrase, dict(SHORTCUTS)["Esc (vim mode)"])
            self.assertIn(phrase, doc)

    @unittest.skipIf(__import__("os").name == "nt", "POSIX PTY only; the OMH TUI does not run on Windows")
    def test_pty(self):
        from _vim_reselect_pty import assert_reselect_pty
        assert_reselect_pty(self)


if __name__ == "__main__":
    unittest.main()

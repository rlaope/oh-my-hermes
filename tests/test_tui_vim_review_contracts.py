"""Permanent real-App/renderer regressions for final-review contracts R1–R4.

Literal outputs protect lifecycle and dispatch seams, not implementation helpers.
The public-prose R5 checks live in test_tui_vim_public_contract.py.
"""
from unittest import TestCase, mock

from test_tui_vim_character_visual import VIEWPORTS, selected_text, vim_app
from test_tui_vim_mode import CHIP_TEXT, CLARIFY, ESC, FAMILY, Composer, keys
from test_tui_modes import SID, type_text
from omh.tui.gateway import ServerRequest
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, TAB, Key, Paste
from omh.tui.session_picker import SessionPicker, SessionRow


UNDO = Key(CHAR, "_", ctrl=True)
REDO = Key(CHAR, "y", ctrl=True)


def active_change(command):
    app, client, clock = vim_app()
    type_text(app, "abcd")
    app._on_input(ESC)
    type_text(app, "0x" + command + "Q")
    return app, client, clock


class TestActiveInsertTraversal(TestCase):
    def test_undo_closes_each_capture_before_typing_escape_and_dot(self):
        for command, final, register in (
            ("i", "bcd", "a"), ("cl", "bcd", "b"),
            ("vc", "bcd", "b"), ("Vc", "bcd", "bcd"),
            ("vvgvc", "bcd", "b"), ("VVgvc", "bcd", "bcd"),
        ):
            with self.subTest(command=command):
                app, client, _ = active_change(command)
                c = app.composer
                prior, saved_register = c._repeat_change, c._register
                self.assertEqual(saved_register.text, register)
                app._on_input(UNDO)
                self.assertIsNone(c._insert_change)
                self.assertEqual(c.text, "bcd")
                self.assertIs(c._repeat_change, prior)
                self.assertIs(c._register, saved_register)
                type_text(app, "R")
                app._on_input(ESC)
                self.assertEqual(c.text, "Rbcd")
                self.assertIs(c._repeat_change, prior)
                self.assertIs(c._register, saved_register)
                type_text(app, ".")
                self.assertEqual(c.text, final)
                self.assertNotIn("Q", c.text)
                self.assertEqual(client.calls, [])

    def test_redo_even_without_a_step_closes_capture_and_preserves_repeat(self):
        for command in ("i", "cl", "vc", "Vc", "vvgvc", "VVgvc"):
            for traverse in ((REDO,), (UNDO, REDO)):
                with self.subTest(command=command, traverse=traverse):
                    app, client, _ = active_change(command)
                    c = app.composer
                    prior, register = c._repeat_change, c._register
                    for event in traverse:
                        app._on_input(event)
                        self.assertIsNone(c._insert_change)
                        self.assertIs(c._repeat_change, prior)
                        self.assertIs(c._register, register)
                    # Remove Q again before fresh typing; dot must not resurrect it.
                    app._on_input(UNDO)
                    self.assertEqual(c.text, "bcd")
                    type_text(app, "R")
                    app._on_input(ESC)
                    self.assertIs(c._repeat_change, prior)
                    type_text(app, ".")
                    self.assertEqual(c.text, "bcd")
                    self.assertNotIn("Q", c.text)
                    self.assertEqual(client.calls, [])


class TestPendingGDispatch(TestCase):
    def pending_app(self, prefix, **options):
        app, client, clock = vim_app(**options)
        type_text(app, "abc def")
        app._on_input(ESC)
        type_text(app, "0" + prefix)
        self.assertTrue(app.composer.pending)
        return app, client, clock

    def test_invalid_modified_followers_never_reach_global_actions(self):
        for prefix in ("g", "2g", "2d3g"):
            for event in (Key(CHAR, "t", ctrl=True), Key(TAB, shift=True),
                          Key(CHAR, "g", ctrl=True), Key(CHAR, "r", ctrl=True),
                          Key(CHAR, "s", ctrl=True), Key(CHAR, "x", alt=True),
                          Key(CHAR, "x", alt=True, protocol=True), Key(DOWN)):
                with self.subTest(prefix=prefix, event=event):
                    app, client, _ = self.pending_app(prefix)
                    before = app.composer.text, app.composer.caret, app.composer._register
                    app._on_input(event)
                    self.assertEqual(client.calls, [])
                    self.assertFalse(app.composer.pending)
                    self.assertEqual((app.composer.text, app.composer.caret, app.composer._register), before)
                    self.assertIsNone(app.pager)
                    self.assertIsNone(app.search)
                    self.assertFalse(app.plan_mode)
                    # Neither count may bleed into the next command.
                    type_text(app, "x")
                    self.assertEqual(app.composer.text, "bc def")

    def test_g_followers_and_find_literals_keep_native_grammar(self):
        for command, caret in (("gg", 0), ("ge", 2), ("gE", 2), ("2gg", 0)):
            app, client, _ = vim_app()
            type_text(app, "abc def")
            app._on_input(ESC)
            type_text(app, command)
            self.assertEqual(app.composer.caret, caret)
            self.assertFalse(app.composer.pending)
            self.assertEqual(client.calls, [])
        app, client, _ = vim_app()
        type_text(app, "abc")
        app._on_input(ESC)
        type_text(app, "0vlvlgv")
        self.assertEqual((app.composer.visual_anchor, app.composer.visual_head), (0, 1))
        self.assertEqual(client.calls, [])
        for target in "gveE":
            app, client, _ = vim_app()
            type_text(app, "agveE")
            app._on_input(ESC)
            type_text(app, "0f" + target)
            self.assertEqual(app.composer.caret, "agveE".index(target))
            self.assertFalse(app.composer.pending)
            self.assertEqual(client.calls, [])

    def test_display_clipboard_enter_escape_picker_and_slot_ownership(self):
        for prefix in ("g", "2g", "2d3g"):
            for char, method in (("o", "_details_view"), ("l", "_redraw"), ("z", "_suspend")):
                app, client, _ = self.pending_app(prefix)
                with mock.patch.object(app, method) as owned:
                    app._on_input(Key(CHAR, char, ctrl=True))
                owned.assert_called_once()
                self.assertFalse(app.composer.pending)
                self.assertEqual(client.calls, [])
            for event in (ESC, Key(ESCAPE, alt=True, protocol=True)):
                app, client, _ = self.pending_app(prefix)
                app._on_input(event)
                self.assertFalse(app.composer.pending)
                self.assertIsNone(app.escape_armed)
                self.assertEqual(client.calls, [])
            app, client, _ = self.pending_app(prefix)
            app._on_input(Key(CHAR, "v", ctrl=True))
            self.assertFalse(app.composer.pending)
            self.assertEqual(client.calls, [("clipboard.paste", {"session_id": SID})])
            app, client, _ = self.pending_app(prefix)
            app._on_input(Key(ENTER))
            self.assertFalse(app.composer.pending)
            # A pending NORMAL command consumes Enter; it never submits a partial grammar.
            self.assertEqual(client.calls, [])
            self.assertEqual(app.composer.text, "abc def")
            app, client, _ = self.pending_app(prefix)
            app._on_input(Paste("Z"))
            self.assertFalse(app.composer.pending)
            self.assertEqual(app.composer.text, "Zabc def")
            self.assertEqual(client.calls, [])
            for waiting in (False, True):
                app, client, _ = self.pending_app(prefix)
                app.picker = SessionPicker([SessionRow(SID, "title", "", 0.0, 1)],
                                          current=app.stored_id, waiting=waiting)
                app._on_input(Key(DOWN) if waiting else Key(CHAR, "e"))
                self.assertFalse(app.composer.pending)
                self.assertFalse(app.picker.waiting)
                if not waiting:
                    self.assertEqual(app.picker.query, "e")
                self.assertEqual(client.calls, [])
            app, client, clock = self.pending_app(prefix)
            app._on_server_request(ServerRequest("g-question", "clarify", CLARIFY))
            clock.now += 1
            type_text(app, "z")
            self.assertFalse(app.composer.vim)
            self.assertEqual(app.composer.text, "z")
            self.assertEqual(client.calls, [])


class TestVisualQueuedSend(TestCase):
    def test_empty_visual_and_restored_sentinels_send_oldest_exactly_once(self):
        for command in ("", "v", "V", "vvgv", "VVgv"):
            for event in (Key(ENTER, ctrl=True), Key(CHAR, "j", ctrl=True)):
                with self.subTest(command=command, event=event):
                    app, client, _ = vim_app(busy=True)
                    type_text(app, "queued prompt")
                    app._on_input(Key(ENTER))
                    self.assertEqual([line.text for line in app.queued], ["queued prompt"])
                    app._on_input(ESC)
                    type_text(app, command)
                    app._on_input(event)
                    self.assertEqual(client.calls, [("session.redirect", {"session_id": SID, "text": "queued prompt"})])
                    self.assertFalse(app.queued)
                    self.assertFalse(app.composer.visual)
                    self.assertFalse(app.composer.pending)
                    app._on_input(event)
                    self.assertEqual(len(client.named("session.redirect")), 1)

    def test_nonempty_visual_steers_draft_and_does_not_drain_queue(self):
        for command in ("v", "V", "vvgv", "VVgv"):
            app, client, _ = vim_app(busy=True)
            type_text(app, "queued prompt")
            app._on_input(Key(ENTER))
            type_text(app, "draft")
            app._on_input(ESC)
            type_text(app, command)
            app._on_input(Key(ENTER, ctrl=True))
            self.assertEqual(client.named("session.redirect"), [{"session_id": SID, "text": "draft"}])
            self.assertEqual([line.text for line in app.queued], ["queued prompt"])
            self.assertFalse(app.composer.visual)

    def test_no_queue_empty_visual_keeps_native_enter_policy(self):
        for busy in (False, True):
            for command in ("v", "V", "vvgv", "VVgv"):
                app, client, _ = vim_app(busy=busy)
                app._on_input(ESC)
                type_text(app, command)
                app._on_input(Key(ENTER, ctrl=True))
                self.assertFalse(app.composer.visual)
                self.assertEqual(client.calls, [])
                self.assertFalse(app.queued)
                self.assertEqual(app.composer.text, "")


class TestFinalLineMarker(TestCase):
    def test_final_visible_cell_uses_atom_endpoints_after_opaque_and_unicode_lines(self):
        for width, height in VIEWPORTS:
            for preceding in ("chip", "image", "unicode", "mixed"):
                for final in ("", "x", "é" + FAMILY + "界"):
                    for restored in (False, True):
                        with self.subTest(size=(width, height), preceding=preceding, final=final, restored=restored):
                            c = Composer(vim=True)
                            if preceding in ("chip", "mixed"):
                                c.handle(Paste(CHIP_TEXT))
                            if preceding in ("image", "mixed"):
                                c.insert_image("[Image #1]", object())
                            if preceding in ("unicode", "mixed"):
                                keys(c, "é" + FAMILY + "界")
                            c.handle(Key(ENTER, shift=True))
                            keys(c, final)
                            c.handle(ESC)
                            keys(c, "GV")
                            if restored:
                                keys(c, "Vgggv")
                            before = c.text, dict(c.pastes), dict(c.images), c._register
                            lines, _ = c.render(width, height, prompt="> ")
                            self.assertEqual(selected_text(lines), final + " ")
                            self.assertEqual((c.text, c.pastes, c.images, c._register), before)
                            keys(c, "y")
                            self.assertEqual(c._register.text, final)
                            self.assertEqual(c.text, before[0])

    def test_preceding_line_selection_does_not_highlight_final_empty_line(self):
        for width, height in VIEWPORTS:
            c = Composer(vim=True)
            c.handle(Paste(CHIP_TEXT))
            c.handle(Key(ENTER, shift=True))
            c.handle(ESC)
            keys(c, "ggV")
            lines, _ = c.render(width, height, prompt="> ")
            self.assertEqual(selected_text(lines), c.text[:-1] + "␊")
            self.assertTrue(c.text.endswith("\n"))

"""Exercise production App input, polling and review without a live gateway."""

import threading
import unittest
import os
from unittest.mock import patch

from test_tui_modes import make_app
from omh.tui import proofread
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, Key
from omh.tui.prompts import PromptSlot

PAYLOAD = {"matches": [{"offset": 3, "length": 8, "message": "Agreement",
                        "replacements": [{"value": "These are"}, {"value": "This is"}]}]}
SAMPLE = "😀 This are a sentence. Café are nice."
ALT_P = Key(CHAR, "p", alt=True)


class AppTests(unittest.TestCase):
    def typo_app(self, text="teh cat", offsets=(0,)):
        app, client = make_app()
        app.composer.replace(0, 0, text)
        payload = {"matches": [{"offset": i, "length": 3, "replacements": [{"value": "the"}]}
                               for i in offsets]}
        app.proofread_worker = proofread.Worker(lambda where, sent: payload)
        return app, client, payload

    def test_pager_takes_foreground_before_result_even_after_return(self):
        for return_to_draft in (False, True):
            with self.subTest(return_to_draft=return_to_draft):
                app, client, payload = self.typo_app()
                gate = threading.Event()
                app.proofread_worker = proofread.Worker(lambda where, sent: (gate.wait(2), payload)[1])
                app._on_input(ALT_P)
                app._on_input(Key(CHAR, "o", ctrl=True))
                self.assertIsNotNone(app.pager)
                self.assertIsNone(app.proofread_job)
                if return_to_draft:
                    app._on_input(Key(ESCAPE))
                    self.assertIsNone(app.pager)
                gate.set()
                app.proofread_worker.wait()
                app._take_proofread()
                self.assertIsNone(app.proofread_review)
                self.assertEqual(app.composer.text, "teh cat")
                self.assertEqual(client.calls, [])
                if not return_to_draft:
                    app._render()
                    pager = app.pager
                    with patch.object(pager, "handle_key", return_value=True) as handle:
                        app._on_input(Key(ENTER))
                        handle.assert_called_once()
                    self.assertEqual(app.composer.text, "teh cat")
                    self.assertEqual(client.calls, [])

    def test_inflight_result_keeps_vim_find_target_and_control(self):
        for timing in ("control", "pending", "completed"):
            with self.subTest(timing=timing):
                app, client, payload = self.typo_app()
                app.composer.vim = True
                app.composer.normal = True
                app._on_input(Key(CHAR, "0"))
                gate = threading.Event()
                app.proofread_worker = proofread.Worker(lambda where, sent: (gate.wait(2), payload)[1])
                try:
                    if timing != "control":
                        app._on_input(ALT_P)
                        self.assertIsNotNone(app.proofread_job)
                    app._on_input(Key(CHAR, "f"))
                    self.assertTrue(app.composer.pending)
                    self.assertEqual(app.composer._prefix, "f")
                    self.assertIsNone(app.proofread_job)
                    if timing == "completed":
                        app._on_input(Key(CHAR, "c"))
                    gate.set()
                    app.proofread_worker.wait()
                    app._take_proofread()
                    self.assertIsNone(app.proofread_review)
                    if timing != "completed":
                        app._on_input(Key(CHAR, "c"))
                    self.assertFalse(app.composer.pending)
                    self.assertEqual(app.composer._prefix, "")
                    self.assertEqual(app.composer.text, "teh cat")
                    app._on_input(Key(CHAR, "i"))
                    app._on_input(Key(CHAR, "X"))
                    self.assertEqual(app.composer.text, "teh Xcat")
                    self.assertEqual(client.calls, [])
                finally:
                    gate.set()
                    app.proofread_worker.wait()

    def test_two_issue_review_undo_closes_and_restores_one_correction(self):
        app, client, _ = self.typo_app("teh teh", (0, 4))
        self.open(app)
        app.proofread_review.armed_until = 0
        app._on_input(Key(ENTER))
        self.assertEqual(app.composer.text, "the teh")
        self.assertIsNotNone(app.proofread_review)
        app._on_input(Key(CHAR, "_", ctrl=True))
        self.assertEqual(app.composer.text, "teh teh")
        self.assertIsNone(app.proofread_review)
        self.assertEqual(client.calls, [])

    def test_foreground_change_after_review_opens_routes_pager_enter(self):
        app, client, _ = self.typo_app()
        self.open(app)
        review = app.proofread_review
        app.proofread_review = None
        app._on_input(Key(CHAR, "o", ctrl=True))
        app.proofread_review = review  # an external owner displaced an already-open overlay
        self.assertIsNotNone(app.pager)
        with patch.object(app.pager, "handle_key", return_value=True) as handle:
            app._on_input(Key(ENTER))
            handle.assert_called_once()
            self.assertIsNone(app.proofread_review)
            self.assertEqual(app.composer.text, "teh cat")
            self.assertEqual(client.calls, [])

    def test_buffered_enter_and_repeats_do_not_submit_but_undo_still_works(self):
        app, client, _ = self.typo_app()
        with patch.object(app, "clock", return_value=100) as clock:
            self.open(app)
            app.proofread_review.armed_until = 0
            app._take_input(b"\r\r")
            self.assertEqual(app.composer.text, "the cat")
            self.assertIsNone(app.proofread_review)
            self.assertEqual(client.calls, [])
            clock.return_value = 100.2
            app._on_input(Key(ENTER))
            clock.return_value = 100.4
            app._on_input(Key(ENTER))  # repeat extends the quiet interval
            self.assertEqual(app.composer.text, "the cat")
            self.assertEqual(client.calls, [])
            app._on_input(Key(CHAR, "_", ctrl=True))
            self.assertEqual(app.composer.text, "teh cat")
            clock.return_value = 101
            app._on_input(Key(ENTER))  # a fresh intentional Enter works after quiet
            self.assertEqual(client.named("prompt.submit")[0]["text"], "teh cat")

    @unittest.skipUnless(os.environ.get("OMH_PROOFREAD_REAL") == "1", "real server opt-in")
    def test_real_http_through_app_accept_and_undo(self):
        app, client = self.app()
        app.environ = dict(app.environ, OMH_PROOFREAD_URL="http://127.0.0.1:18081/v2/check")
        app.proofread_worker = proofread.Worker()
        before = list(client.calls)
        self.open(app)
        self.assertEqual(app.proofread_review.issue.original, "This are")
        app.proofread_review.armed_until = 0
        app._on_input(Key(DOWN))
        app._on_input(Key(ENTER))
        self.assertEqual(app.composer.text, "😀 This is a sentence. Café are nice.")
        app._on_input(Key(CHAR, "_", ctrl=True))
        self.assertEqual(app.composer.text, SAMPLE)
        self.assertEqual(client.calls, before)

    def app(self):
        app, client = make_app()
        app.proofread_worker = proofread.Worker(lambda where, sent: PAYLOAD)
        app.composer.replace(0, 0, SAMPLE)
        return app, client

    def open(self, app):
        app._on_input(ALT_P)
        app.proofread_worker.wait()
        app._take_proofread()
        self.assertIsNotNone(app.proofread_review)

    def test_accept_arming_undo_and_no_submit(self):
        app, client = self.app()
        calls = list(client.calls)
        self.open(app)
        app._on_input(Key(ENTER))  # the late key is swallowed by arming
        self.assertEqual(app.composer.text, SAMPLE)
        app.proofread_review.armed_until = 0
        app._on_input(Key(DOWN))
        app._on_input(Key(ENTER))
        self.assertEqual(app.composer.text, "😀 This is a sentence. Café are nice.")
        self.assertIsNone(app.proofread_review)
        app._on_input(Key(CHAR, "_", ctrl=True))
        self.assertEqual(app.composer.text, SAMPLE)
        self.assertEqual(client.calls, calls)

    def test_skip_cancel_and_render(self):
        app, client = self.app()
        self.open(app)
        self.assertTrue(app._slot_lines(80, 24))
        app.proofread_review.armed_until = 0
        app._on_input(Key(DOWN))
        app._on_input(Key(DOWN))
        app._on_input(Key(ENTER))
        self.assertEqual(app.composer.text, SAMPLE)
        self.open(app)
        app._on_input(Key(ESCAPE))
        self.assertIsNone(app.proofread_review)
        self.assertEqual(app.composer.text, SAMPLE)
        self.assertEqual(client.named("turn.start"), [])

    def test_pending_typing_and_aba_results_rejected(self):
        app, _ = self.app()
        gate = threading.Event()
        app.proofread_worker = proofread.Worker(lambda where, sent: (gate.wait(1), PAYLOAD)[1])
        app._on_input(ALT_P)
        app._on_input(Key(CHAR, "x"))
        self.assertTrue(app.composer.text.endswith("x"))
        app.composer.replace(len(SAMPLE), len(app.composer.text), "")
        gate.set()
        app.proofread_worker.wait()
        app._take_proofread()
        self.assertEqual(app.composer.text, SAMPLE)
        self.assertIsNone(app.proofread_review)

    def test_clarify_field_and_changed_question(self):
        app, client = self.app()
        app.slot = PromptSlot("q1", "clarify", {"question": "What?"}, typing=True)
        app.slot_opened_at = 0
        self.open(app)
        app.proofread_review.armed_until = 0
        app._on_input(Key(DOWN))
        app._on_input(Key(ENTER))
        self.assertIn("This is", app.composer.text)
        self.assertEqual(client.answers, [])
        self.open(app)
        app.slot.question_index += 1
        app._on_input(Key(ENTER))
        self.assertIsNone(app.proofread_review)
        self.assertEqual(client.answers, [])

    def test_masked_and_session_change(self):
        app, _ = self.app()
        app.composer.masked = True
        app._on_input(ALT_P)
        self.assertFalse(app.proofread_worker.pending)
        app.composer.masked = False
        self.open(app)
        app.sid = "other"
        app._on_input(Key(ENTER))
        self.assertIsNone(app.proofread_review)

    def test_vim_pending_and_approval_keep_ownership(self):
        app, _ = self.app()
        app.composer.vim = True
        app.composer.normal = True
        app.composer._prefix = "g"
        app._on_input(ALT_P)
        self.assertFalse(app.proofread_worker.pending)
        app.composer._drop_pending()
        app.slot = PromptSlot("approval", "approval", {})
        app.slot_opened_at = 0
        app._on_input(ALT_P)
        self.assertFalse(app.proofread_worker.pending)

    def test_image_and_paste_metadata_survive_correction_and_undo(self):
        app, _ = self.app()
        app.composer.replace(0, len(app.composer.text), "")
        app.composer.insert_image("picture", object())
        app.composer.replace(len(app.composer.text), len(app.composer.text), " " + SAMPLE)
        from omh.tui.keys import Paste
        app.composer.handle(Paste("private\nprivate\nprivate\nprivate\nprivate"))
        text = app.composer.text
        metadata = (dict(app.composer.images), dict(app.composer.pastes))
        job = proofread.prepare(app.composer, app._proofread_owner(), app.environ)
        self.assertIsInstance(job, proofread.Job)
        self.assertNotIn("private", job.protected.sent)
        self.assertNotIn(next(iter(app.composer.images)), job.protected.sent)
        start = text.index("This are")
        app.composer.replace(start, start + 8, "This is")
        self.assertEqual((dict(app.composer.images), dict(app.composer.pastes)), metadata)
        app.composer.handle(Key(CHAR, "_", ctrl=True))
        self.assertEqual(app.composer.text, text)
        self.assertEqual((dict(app.composer.images), dict(app.composer.pastes)), metadata)

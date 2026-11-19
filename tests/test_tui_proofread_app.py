"""Exercise production App input, polling and review without a live gateway."""

import threading
import time
import unittest
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_tui_modes import make_app
from omh.tui import proofread
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, Key
from omh.tui.prompts import PromptSlot
from omh.tui.composer import Composer
from omh.tui.width import line_width
from omh.tui.style import Style
from omh.tui.theme import DEFAULT_THEME, without_colour

PAYLOAD = {"matches": [{"offset": 3, "length": 8, "message": "Agreement",
                        "replacements": [{"value": "These are"}, {"value": "This is"}]}]}
SAMPLE = "😀 This are a sentence. Café are nice."
ALT_P = Key(CHAR, "p", alt=True)


def line_text(row):
    return "".join(span.text for span in row)


def settle_dictionary(app):
    """Until the dictionary read or save in flight, and a save queued behind it, has landed."""
    task = getattr(app, "proofread_dictionary_task", None)  # a TUI reading the dictionary on its own thread
    for _ in range(4):
        if task is None or not (task.pending or app.proofread_dictionary_save is not None):
            return
        task.wait()
        app._take_proofread()
    raise AssertionError("the dictionary task did not settle")


class AppTests(unittest.TestCase):
    def typo_app(self, text="teh cat", offsets=(0,)):
        app, client = make_app(environ={"OMH_PROOFREAD": "1"})
        app.transcript.add_notice("Prior conversation.")
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

    def test_two_local_corrections_undo_one_at_a_time(self):
        app, client, _ = self.typo_app("teh teh", (0, 4))
        self.open(app)
        app.proofread_review.armed_until = 0
        app._on_input(Key(ENTER))
        self.assertEqual(app.composer.text, "the teh")
        self.assertIsNone(app.proofread_review)
        app.composer.caret = 5
        app._on_input(ALT_P)
        app.proofread_worker.wait()
        app._take_proofread()
        app.proofread_review.armed_until = 0
        app._on_input(Key(ENTER))
        self.assertEqual(app.composer.text, "the the")
        app._on_input(Key(CHAR, "_", ctrl=True))
        self.assertEqual(app.composer.text, "the teh")
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
        app.environ = dict(app.environ, OMH_PROOFREAD_URL="http://127.0.0.1:8081/v2/check")
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
        app, client = make_app(environ={"OMH_PROOFREAD": "1"})
        app.proofread_worker = proofread.Worker(lambda where, sent: PAYLOAD)
        app.composer.replace(0, 0, SAMPLE)
        return app, client

    def open(self, app):
        app.composer.caret = app.composer.text.index("This") if "This" in app.composer.text else 0
        app._on_input(ALT_P)
        app.proofread_worker.wait()
        app._take_proofread()
        settle_dictionary(app)
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

    def test_cancel_and_render(self):
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

    def test_dictionary_picker_saves_and_restores_spelling_without_editing_or_sending(self):
        text = "Blorfle blorfle go"
        payload = {"matches": [
            {"offset": 0, "length": 7, "rule": {"issueType": "misspelling"}, "replacements": []},
            {"offset": 8, "length": 7, "rule": {"issueType": "misspelling"}, "replacements": [{"value": "blowfly"}]},
            {"offset": 16, "length": 2, "rule": {"issueType": "grammar"}, "replacements": [{"value": "goes"}]},
        ]}
        queries = []

        def start(home):
            app, client = make_app(environ={"OMH_HOME": home})
            app.composer.replace(0, 0, text)
            app.proofread_worker = proofread.Worker(lambda _endpoint, draft: (queries.append(draft), payload)[1])
            self.open(app)
            return app, client

        def pick(app, label):
            review = app.proofread_review
            review.armed_until = 0
            self.assertEqual(review.choices().count(label), 1)
            for _ in range(review.choices().index(label)):
                app._on_input(Key(DOWN))
            app._on_input(Key(ENTER))
            self.assertIsNone(app.proofread_review)
            settle_dictionary(app)

        with TemporaryDirectory() as home:
            path = Path(home) / "proofread" / "dictionary.txt"
            app, client = start(home)
            self.assertEqual(app.proofread_review.choices(), ["Add to dictionary", "Cancel"])
            self.assertEqual(app._proofread_marks(), ((0, 7), (8, 15), (16, 18)))
            before = proofread.Snapshot.capture(app.composer, app._proofread_owner())
            app._on_input(Key(ENTER))  # arming cannot save a word, even with Add on the first row
            self.assertFalse(path.exists())
            pick(app, "Cancel")
            self.assertFalse(path.exists())
            self.open(app)
            pick(app, "Add to dictionary")
            self.assertEqual(path.read_bytes(), b"blorfle\n")
            self.assertEqual(app._proofread_marks(), ((16, 18),))
            self.assertTrue(before.matches(app.composer, app._proofread_owner()))
            self.assertEqual(queries, [text])
            self.assertEqual(client.calls, [])

            reopened, second_client = start(home)
            reopened._on_input(Key(ESCAPE))
            reopened.composer.caret = 9
            reopened._on_input(ALT_P)
            settle_dictionary(reopened)
            self.assertEqual(reopened._proofread_marks(), ((16, 18),))
            self.assertEqual(reopened.proofread_review.choices(), ["Remove from dictionary", "Cancel"])
            before = proofread.Snapshot.capture(reopened.composer, reopened._proofread_owner())
            pick(reopened, "Remove from dictionary")
            self.assertEqual(path.read_bytes(), b"")
            self.assertEqual(reopened._proofread_marks(), ((0, 7), (8, 15), (16, 18)))
            self.assertTrue(before.matches(reopened.composer, reopened._proofread_owner()))
            self.assertEqual(queries, [text, text])
            self.assertEqual(second_client.calls, [])

            path.write_bytes(b"not a word\n")
            reopened._on_input(ALT_P)
            settle_dictionary(reopened)
            pick(reopened, "Add to dictionary")
            self.assertEqual(path.read_bytes(), b"not a word\n")
            self.assertEqual(reopened._proofread_marks(), ((0, 7), (8, 15), (16, 18)))
            self.assertEqual(reopened.proofread_status, "Could not update the local dictionary")

    def test_grammar_correction_survives_overlapping_spellings_with_or_without_a_home(self):
        text = "teh cat " + "zz " * 50 + "end"
        spelling = {"rule": {"issueType": "misspelling"}, "replacements": []}
        payload = {"matches": [
            {"offset": 0, "length": 3, **spelling},  # same start as the grammar correction
            {"offset": 4, "length": 3, **spelling},  # inside it
            {"offset": 0, "length": 7, "message": "Grammar", "replacements": [{"value": "the cat"}]},
            *({"offset": 8 + 3 * n, "length": 2, **spelling} for n in range(50)),
            {"offset": 158, "length": 3, "message": "Case", "replacements": [{"value": "End"}]},
        ]}
        for saved in (None, b"", b"teh\n"):
            with self.subTest(saved=saved), TemporaryDirectory() as home:
                if saved is not None:
                    (Path(home) / "proofread").mkdir()
                    (Path(home) / "proofread" / "dictionary.txt").write_bytes(saved)
                app, client = make_app(environ={"OMH_HOME": home} if saved is not None else {})
                app.composer.replace(0, 0, text)
                app.proofread_worker = proofread.Worker(lambda _endpoint, _draft: payload)
                self.open(app)
                marks = app._proofread_marks()
                self.assertIn((0, 7), marks)
                self.assertIn((158, 161), marks)
                review = app.proofread_review
                expected = {None: ["the cat", "Cancel"], b"": ["the cat", "Add to dictionary", "Cancel"],
                            b"teh\n": ["the cat", "Remove from dictionary", "Cancel"]}[saved]
                self.assertEqual(review.choices(), expected)
                if saved == b"teh\n":
                    review.armed_until = 0
                    app._on_input(Key(DOWN))
                    app._on_input(Key(ENTER))
                    settle_dictionary(app)
                    self.assertEqual((Path(home) / "proofread" / "dictionary.txt").read_bytes(), b"")
                    self.assertEqual(app.composer.text, text)
                    self.open(app)
                    app.proofread_review.armed_until = 0
                app.proofread_review.armed_until = 0
                app._on_input(Key(ENTER))
                self.assertTrue(app.composer.text.startswith("the cat "))
                app.composer.caret = len(app.composer.text) - 1
                app._on_input(ALT_P)
                app.proofread_worker.wait()
                app._take_proofread()
                settle_dictionary(app)
                self.assertEqual(app.proofread_review.choices()[0], "End")
                self.assertEqual(client.calls, [])

    def test_dictionary_only_hint_names_the_action(self):
        payload = {"matches": [{"offset": 0, "length": 7, "rule": {"issueType": "misspelling"}, "replacements": []},
                               {"offset": 8, "length": 2, "replacements": [{"value": "goes"}]}]}
        with TemporaryDirectory() as home:
            app, _ = make_app(environ={"OMH_HOME": home})
            app.composer.replace(0, 0, "Blorfle go")
            app.proofread_worker = proofread.Worker(lambda _endpoint, _draft: payload)
            self.open(app)
            app._on_input(Key(ESCAPE))
            hints = {}
            for caret in (3, 9):
                app.composer.caret = caret
                hints[caret] = line_text(app._info_line(120))
            self.assertIn("Alt+P adds word to dictionary", hints[3])
            self.assertIn("Alt+P corrects at cursor", hints[9])

    def test_dictionary_io_never_holds_the_loop_and_other_windows_saves_show(self):
        payload = {"matches": [{"offset": 0, "length": 3, "rule": {"issueType": "misspelling"},
                                "replacements": [{"value": "the"}]}]}
        with TemporaryDirectory() as home:
            path = Path(home) / "proofread" / "dictionary.txt"

            def window():
                app, client = make_app(environ={"OMH_HOME": home})
                app.composer.replace(0, 0, "teh cat")
                app.proofread_worker = proofread.Worker(lambda _endpoint, _draft: payload)
                return app, client

            first, _ = window()
            second, second_client = window()
            self.assertFalse(path.exists())  # starting reads nothing
            self.open(first)
            self.open(second)
            self.assertEqual(second.proofread_review.choices(), ["the", "Add to dictionary", "Cancel"])
            second._on_input(Key(ESCAPE))
            first.proofread_review.armed_until = 0
            first._on_input(Key(DOWN))
            gate, entered = threading.Event(), threading.Event()
            real = proofread.update_dictionary

            def held(*args, **kwargs):
                entered.set()
                gate.wait(5)
                return real(*args, **kwargs)

            with patch.object(proofread, "update_dictionary", held):
                started = time.monotonic()
                first._on_input(Key(ENTER))
                self.assertTrue(entered.wait(2))
                self.assertLess(time.monotonic() - started, 0.1)  # the key returned while the save is held
                first._on_input(Key(CHAR, "x"))  # typing and repainting go on
                first._render()
                self.assertEqual(first.composer.text, "xteh cat")
                gate.set()
                settle_dictionary(first)
            self.assertEqual(path.read_bytes(), b"teh\n")
            self.assertEqual(first.proofread_words, {"teh"})
            second._on_input(ALT_P)
            settle_dictionary(second)
            self.assertEqual(second.proofread_review.choices(), ["Remove from dictionary", "Cancel"])
            self.assertEqual(second_client.calls, [])

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

    def test_automatic_debounce_no_popup_or_cursor_only_request(self):
        app, client, payload = self.typo_app()
        sent = []
        app.proofread_worker = proofread.Worker(lambda where, text: (sent.append(text), payload)[1])
        with patch.object(app, "clock", return_value=10) as clock:
            app._take_proofread()
            self.assertFalse(app.proofread_worker.pending)
            app.composer.caret = 1
            clock.return_value = 10.59
            app._take_proofread()
            self.assertEqual(sent, [])
            clock.return_value = 10.6
            app._take_proofread()
            app.proofread_worker.wait()
            app._take_proofread()
            self.assertEqual(sent, ["teh cat"])
            self.assertEqual(app._proofread_marks(), ((0, 3),))
            self.assertIsNone(app.proofread_review)
            for caret in (0, 1, 3, 7):
                app.composer.caret = caret
                clock.return_value += 1
                app._take_proofread()
            self.assertEqual(sent, ["teh cat"])
            self.assertEqual(client.calls, [])
            app._on_input(Key(CHAR, "x"))
            self.assertEqual(app._proofread_marks(), ())

    def test_empty_protected_and_hidden_drafts_do_not_wake_or_redraw(self):
        for text, masked, hidden in (("", False, False), ("`teh`", False, False),
                                     ("/teh", False, False), ("secret", True, False),
                                     ("teh", False, True), (" " * 3, False, False)):
            with self.subTest(text=text, masked=masked, hidden=hidden):
                app, _, _ = self.typo_app(text)
                app.composer.masked = masked
                if hidden:
                    app.list_selected = "agent"
                app.dirty = False
                with patch.object(app.proofread_worker, "start") as start:
                    app._take_proofread()
                    app._take_proofread()
                    self.assertIsNone(app.proofread_due)
                    self.assertFalse(app.dirty)
                    start.assert_not_called()

    def test_enabled_prose_debounce_shares_aura_deadline_without_redraw(self):
        from omh.tui.app import TICK_SECONDS

        app, _, _ = self.typo_app()
        with patch.object(app, "clock", return_value=10) as clock:
            app.last_render = 10
            app.dirty = False
            app._take_proofread()
            self.assertAlmostEqual(app._read_timeout(), 0.6)
            with patch.object(app, "_aura_live", return_value=True):
                self.assertAlmostEqual(app._read_timeout(), TICK_SECONDS)
            self.assertFalse(app.dirty)
            clock.return_value = 10.6
            with patch.object(app.proofread_worker, "start") as start:
                app._take_proofread()
                start.assert_called_once()
            self.assertFalse(app.dirty)
            self.assertIsNone(app.proofread_due)

    def test_pending_and_ineligible_start_do_not_redraw(self):
        app, _, _ = self.typo_app("`teh`")
        app._sync_proofread()
        app.dirty = False
        app._start_proofread()
        self.assertFalse(app.dirty)
        with patch.object(type(app.proofread_worker), "pending", new_callable=property,
                          fget=lambda _: True):
            app._start_proofread()
            self.assertFalse(app.dirty)

    def test_cursor_local_cached_and_pending_intent(self):
        for caret, expected in ((0, 0), (1, 0), (3, 0), (4, 4), (5, 4), (7, 4), (8, None)):
            with self.subTest(caret=caret):
                app, _, payload = self.typo_app("teh teh away", (0, 4))
                app.composer.caret = caret
                self.assertEqual(self._checked(app), ((0, 3), (4, 7)))
                app._on_input(ALT_P)
                review = app.proofread_review
                self.assertEqual(review.issue.start if review else None, expected)
                if review:
                    self.assertEqual(len(review.issues), 1)
                else:
                    self.assertIn("cursor", app.proofread_status)
        app, _, payload = self.typo_app("teh teh", (0, 4))
        gate = threading.Event()
        app.proofread_worker = proofread.Worker(lambda where, sent: (gate.wait(2), payload)[1])
        app.composer.caret = 0
        app._on_input(ALT_P)
        app.composer.caret = 5
        gate.set()
        app.proofread_worker.wait()
        app._take_proofread()
        self.assertEqual(app.proofread_review.issue.start, 4)

    def _checked(self, app):
        with patch.object(app, "clock", return_value=100) as clock:
            app._take_proofread()
            clock.return_value = 101
            app._take_proofread()
            app.proofread_worker.wait()
            app._take_proofread()
        return app._proofread_marks()

    def test_latest_generation_after_stale_job_and_intent_cancel(self):
        app, _, payload = self.typo_app()
        gate = threading.Event()
        sent = []
        app.proofread_worker = proofread.Worker(
            lambda where, text: (sent.append(text), gate.wait(2), payload)[2])
        with patch.object(app, "clock", return_value=10) as clock:
            app.composer.caret = 1
            app._on_input(ALT_P)
            app._on_input(Key(CHAR, "x"))
            clock.return_value = 11
            app._take_proofread()
            self.assertTrue(app.proofread_worker.pending)
            gate.set()
            app.proofread_worker.wait()
            app._take_proofread()
            app._take_proofread()
            app.proofread_worker.wait()
            app._take_proofread()
            self.assertEqual(sent, ["teh cat", "txeh cat"])
            self.assertIsNone(app.proofread_review)

    def test_automatic_checks_are_opt_in_and_alt_p_still_works(self):
        for value in (None, "0", "", "yes", "true"):
            with self.subTest(OMH_PROOFREAD=value):
                app, client, payload = self.typo_app()
                app.environ = {k: v for k, v in app.environ.items() if k != "OMH_PROOFREAD"}
                if value is not None:
                    app.environ["OMH_PROOFREAD"] = value
                sent = []
                app.proofread_worker = proofread.Worker(lambda where, text: (sent.append(text), payload)[1])
                with patch.object(app, "clock", return_value=10) as clock:
                    app._take_proofread()
                    clock.return_value = 20
                    app._take_proofread()
                    self.assertFalse(app.proofread_worker.pending)
                    self.assertEqual(sent, [])
                    self.assertEqual(app._proofread_marks(), ())
                    app._on_input(ALT_P)
                    app.proofread_worker.wait()
                    app._take_proofread()
                self.assertEqual(sent, ["teh cat"])
                self.assertEqual(client.calls, [])

    def test_auto_opt_out_protected_masked_and_owner(self):
        for text, masked, disabled in (("teh", False, True), ("secret", True, False),
                                       ("`teh`", False, False), ("/teh", False, False),
                                       ("", False, False)):
            with self.subTest(text=text, masked=masked, disabled=disabled):
                app, _, _ = self.typo_app(text)
                app.composer.masked = masked
                if disabled:
                    app.environ = {k: v for k, v in app.environ.items() if k != "OMH_PROOFREAD"}
                sent = []
                app.proofread_worker = proofread.Worker(lambda where, text: sent.append(text))
                self._checked(app)
                self.assertFalse(app.proofread_worker.pending)
                self.assertEqual(sent, [])
        app, _, _ = self.typo_app()
        self._checked(app)
        app._on_input(Key(CHAR, "o", ctrl=True))
        self.assertEqual(app._proofread_marks(), ())
        app._on_input(Key(ESCAPE))
        self.assertEqual(app._proofread_marks(), ())

    def test_unavailable_backoff_manual_retry_and_no_transcript_spam(self):
        app, _, _ = self.typo_app()
        sent = []
        def unavailable(where, text):
            sent.append(text)
            raise proofread.ProofreadError("server down")
        app.proofread_worker = proofread.Worker(unavailable)
        with patch.object(app, "clock", return_value=100) as clock:
            self._checked(app)
            self.assertEqual(len(sent), 1)
            self.assertIn("unavailable", app.proofread_status)
            for _ in range(20):
                app._take_proofread()
            self.assertEqual(len(sent), 1)
            app.composer.caret = 1
            app._on_input(ALT_P)
            app.proofread_worker.wait()
            app._take_proofread()
            self.assertEqual(len(sent), 2)
            clock.return_value = app.proofread_retry
            app._take_proofread()
            app.proofread_worker.wait()
            app._take_proofread()
            self.assertEqual(len(sent), 3)

    def test_diagnostics_preserve_wrapping_caret_chips_glow_and_selection(self):
        composer = Composer()
        composer.replace(0, 0, "😀 teh cat long words")
        composer.visual_anchor, composer.visual_head = 2, 4
        ink = Style(fg="#123456", bold=True)
        for width in (8, 30):
            with self.subTest(width=width):
                plain, caret = composer.render(width, 10, glow=((2, 5),), glow_style=lambda *_: ink)
                marked, marked_caret = composer.render(
                    width, 10, glow=((2, 5),), glow_style=lambda *_: ink, diagnostics=((2, 5),))
                self.assertEqual([line_text(row) for row in marked], [line_text(row) for row in plain])
                self.assertEqual(caret, marked_caret)
                underlined = [span for row in marked for span in row if span.style.underline]
                self.assertEqual("".join(span.text for span in underlined), "teh")
                self.assertTrue(all(span.style.fg == ink.fg and span.style.bold for span in underlined))
                self.assertTrue(any(span.style.reverse for span in underlined))
                self.assertTrue(all(line_width(row) <= width for row in marked))
        composer.visual_anchor = composer.visual_head = None
        composer.insert_image("picture", object())
        chip_style = Style(dim=True)
        rows, _ = composer.render(80, 10, chip_style=chip_style, diagnostics=((0, len(composer.text)),))
        chips = [span for row in rows for span in row if span.style.dim]
        self.assertTrue(chips)
        self.assertFalse(any(span.style.underline for span in chips))
        composer.masked = True
        rows, _ = composer.render(80, 10, diagnostics=((0, len(composer.text)),))
        self.assertFalse(any(span.style.underline for row in rows for span in row))

    def test_actual_clarify_field_underlines_no_color_at_two_widths(self):
        for width in (30, 80):
            with self.subTest(width=width):
                app, client, _ = self.typo_app("😀 teh tail", (3,))  # LanguageTool UTF-16 offset
                app.theme = without_colour(DEFAULT_THEME)
                app.slot = PromptSlot("q1", "clarify", {"questions": [
                    {"qid": "q", "question": "Why?", "choices": ["Yes"]}]}, typing=True, selected=1)
                app.slot_opened_at = 0
                app.composer.caret = 4
                self.assertEqual(self._checked(app), ((2, 5),))
                rows = app._slot_lines(width, 24)
                caret = app.slot.caret
                marked = [span for row in rows for span in row if span.style.underline]
                self.assertTrue(marked)
                self.assertTrue(all("4" in span.style.sgr() for span in marked))
                app.proofread_issues = ()
                plain = app._slot_lines(width, 24)
                self.assertEqual([line_text(row) for row in rows], [line_text(row) for row in plain])
                self.assertEqual(caret, app.slot.caret)
                self.assertEqual(client.answers, [])

    def test_clarify_exact_scroll_boundary_preserves_first_character(self):
        for marks in ((), ((0, 3),), ((7, 10),)):
            with self.subTest(marks=marks):
                slot = PromptSlot("q1", "clarify", {"question": "What?"}, typing=True)
                slot.draft, slot.draft_before = "abcdefghijklmno", "abcdefghi"
                slot.draft_marks = marks
                row, caret = slot._field_row("", 12, DEFAULT_THEME)
                self.assertEqual(line_text(row), "❯ abcdefghi…")
                self.assertEqual(caret, 11)
                expected = "".join(slot.draft[left:min(right, 9)] for left, right in marks)
                self.assertEqual("".join(span.text for span in row if span.style.underline), expected)

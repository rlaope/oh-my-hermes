"""The proofread helper (`src/tui/proofread.py`): protected spans, UTF-16 mapping, a real LanguageTool on loopback,
refusal of anything but loopback, stale answers, and an accepted correction as one Composer edit and one undo."""

from __future__ import annotations

import http.server
import os
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

from omh.tui import proofread
from omh.tui.composer import Composer
from omh.tui.keys import CHAR, DOWN, ENTER, ESCAPE, Key, Paste

SAMPLE = "😀 This are a sentence. Café are nice."
REAL = {"OMH_PROOFREAD_URL": "http://127.0.0.1:18081/v2/check"}
OWNER = ("sid", None)


def real_server_up() -> bool:
    try:
        proofread.post_check(proofread.endpoint(REAL), "Hello.")
        return True
    except proofread.ProofreadError:
        return False


def job_for(text: str, owner: tuple = OWNER, env: dict | None = None) -> tuple[Composer, proofread.Job]:
    composer = Composer()
    composer.replace(0, 0, text)
    job = proofread.prepare(composer, owner, env or REAL)
    assert isinstance(job, proofread.Job), job
    return composer, job


class Fake(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []
    reply: tuple[int, bytes, dict] = (200, b"{}", {})

    def do_POST(self) -> None:
        Fake.hits.append(self.rfile.read(int(self.headers["Content-Length"])).decode())
        status, body, headers = Fake.reply
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.path == "/trickle":
            try:
                for byte in body:
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    time.sleep(0.02)
            except OSError:
                pass
        else:
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass


class Served:
    def __enter__(self) -> dict:
        Fake.hits, Fake.reply = [], (200, b'{"matches": []}', {})
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return {"OMH_PROOFREAD_URL": f"http://127.0.0.1:{self.server.server_port}/v2/check"}

    def __exit__(self, *exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()


class EndpointTests(unittest.TestCase):
    def test_default_and_override(self) -> None:
        self.assertEqual(proofread.endpoint({}).port, 8081)
        self.assertEqual(proofread.endpoint(REAL).port, 18081)
        self.assertEqual(proofread.endpoint({"OMH_PROOFREAD_URL": "http://localhost:9/x"}).host, "127.0.0.1")
        self.assertEqual(proofread.endpoint({}).language, "auto")

    def test_refuses_everything_but_plain_loopback(self) -> None:
        for url in ("https://127.0.0.1:8081/v2/check", "http://example.com:8081/v2/check", "http://10.0.0.5:8081/x",
                    "http://127.0.0.1/v2/check", "http://u:p@127.0.0.1:8081/x", "http://127.0.0.1:8081/x?a=1", "nonsense"):
            with self.assertRaises(proofread.ProofreadError, msg=url):
                proofread.endpoint({"OMH_PROOFREAD_URL": url})
        with self.assertRaises(proofread.ProofreadError):
            proofread.endpoint({"OMH_PROOFREAD_LANGUAGE": "en;rm -rf"})


class ProtectTests(unittest.TestCase):
    def test_outbound_container_indentation_survives_marker_stripping(self) -> None:
        lines = (
            ">     - secret10",
            ">     > secret11",
            "> >     1. secret12",
            "> \t- secret13",
            ">     + secret14",
            ">     * secret15",
            ">  \t- secret16",
            "> >   \t1. secret17",
            "  \t- secret18",
            "> -     - secret19",
            "> 1.     > secret20",
            "> -  \t+ secret21",
            "> 1.  \t* secret22",
        )
        with Served() as env:
            for line in lines:
                with self.subTest(line=line):
                    separator = "> >" if line.startswith("> >") else ">"
                    text = f"prose\n{separator}\n{line}\n{separator}\nafter"
                    composer, job = job_for(text, env=env)
                    proofread.post_check(job.endpoint, job.protected.sent)
                    sent = parse_qs(Fake.hits[-1])["text"][0]
                    self.assertEqual(sent, text.replace(line, " " * len(line)))
                    self.assertEqual(composer.text, text)
                    self.assertEqual(job.original, text)

    def test_outbound_fences_require_real_closers_and_mask_nested_containers(self) -> None:
        cases = (
            "prose\n~~~python\nsecret1\n~~~not-a-close\nsecret2\n~~~\nafter",
            "prose\n~~~python\nsecret1\n> ~~~\nsecret2\n- ~~~\nsecret3\n~~~\nafter",
            "prose\n> > ~~~python\n> > secret1\n> ~~~\n> > secret2\n> > ~~~\nafter",
            "prose\n````python\nsecret1\n```\nsecret2\n```` trailing\nsecret3\n````\nafter",
            "prose\n> ~~~python\n> secret1\n> ~~~not-a-close\n> secret2\n> ~~~\nafter",
            "prose\n- ~~~python\n  secret1\n  ~~~\nafter",
            "prose\n> 1. > - ~~~python\n> > secret1\n> > ~~~\nafter",
            "prose\n> ~~~python\n> secret1",  # unclosed container fence
            "prose\n>\n>     secret5\n>\nafter",
            "prose\n> >\n> >     secret6\n> >\nafter",
            "prose\n>\n> \tsecret7\n>\nafter",
            "prose\n> /secret8\n> > !secret9\nafter",
        )
        with Served() as env:
            for text in cases:
                with self.subTest(text=text):
                    composer, job = job_for(text, env=env)
                    proofread.post_check(job.endpoint, job.protected.sent)
                    sent = parse_qs(Fake.hits[-1])["text"][0]
                    self.assertNotIn("secret", sent)
                    self.assertIn("prose", sent)
                    if text.endswith("after"):
                        self.assertIn("after", sent)
                    self.assertEqual(len(sent.encode("utf-16-le")), len(text.encode("utf-16-le")))
                    self.assertEqual(composer.text, text)

    def test_blanking_keeps_utf16_width_and_offsets(self) -> None:
        guarded = proofread.protect("😀 `x` This", [])
        self.assertEqual(guarded.sent, "😀     This")  # `x` blanked, emoji kept
        self.assertEqual(guarded.units[7], 6)  # UTF-16 offset 7 (emoji is 2 units) is character index 6
        self.assertEqual(guarded.origin[6], 6)
        wide = proofread.protect("a`😀`b", [])
        self.assertEqual(wide.sent, "a    b")  # the protected emoji keeps its two UTF-16 units (+ 2 backticks)
        self.assertEqual(wide.units[5], 5)

    def test_commands_fences_inline_code(self) -> None:
        text = "/model foo bar\n!ls teh\nprose teh\n```\ncode teh\n```\nafter `teh` ok"
        guarded = proofread.protect(text, [])
        self.assertNotIn("model", guarded.sent)
        self.assertNotIn("ls", guarded.sent)
        self.assertNotIn("code", guarded.sent)
        self.assertIn("prose teh", guarded.sent)
        self.assertIn("after", guarded.sent)
        self.assertNotIn("`teh`", guarded.sent)

    def test_only_protected_means_nothing_to_read(self) -> None:
        composer = Composer()
        composer.replace(0, 0, "/help me")
        self.assertEqual(proofread.prepare(composer, OWNER, REAL), proofread.NOTHING_NOTICE)

    def test_paste_chip_never_expanded_and_image_blanked(self) -> None:
        composer = Composer()
        composer.replace(0, 0, "see ")
        composer.handle(Paste("a\nb\nc\nd\nteh teh"))
        composer.replace(len(composer.text), len(composer.text), " wirte")
        job = proofread.prepare(composer, OWNER, REAL)
        self.assertIsInstance(job, proofread.Job)
        self.assertNotIn("teh", job.protected.sent)
        self.assertNotIn("Pasted", job.protected.sent)
        self.assertIn("wirte", job.protected.sent)
        self.assertEqual(len(job.protected.sent), len(composer.text))

    def test_masked_makes_no_request(self) -> None:
        with Served() as env:
            composer = Composer(masked=True)
            composer.text = "secret teh"
            self.assertEqual(proofread.prepare(composer, OWNER, env), proofread.MASKED_NOTICE)
            self.assertEqual(Fake.hits, [])


@unittest.skipUnless(os.environ.get("OMH_PROOFREAD_REAL") == "1" and real_server_up(),
                     "set OMH_PROOFREAD_REAL=1 with LanguageTool on 127.0.0.1:18081")
class RealServerTests(unittest.TestCase):
    def test_real_response_maps_utf16_and_applies_in_one_undoable_edit(self) -> None:
        composer, job = job_for(SAMPLE)
        payload = proofread.post_check(job.endpoint, job.protected.sent)
        first = payload["matches"][0]
        self.assertEqual((first["offset"], first["length"]), (3, 8))  # UTF-16: python index of "This" is 2
        self.assertEqual(SAMPLE.index("This"), 2)
        issues = proofread.issues_from(payload, job)
        issue = issues[0]
        self.assertEqual((issue.start, issue.end, issue.original), (2, 10, "This are"))
        self.assertEqual(issue.replacements[:3], ("These are", "This is", "This was"))
        review = proofread.Review(job.snapshot, issues)
        review.row = 1
        self.assertEqual(review.handle_key(Key(ENTER)), ("accept", "This is"))
        before = composer.text
        composer.replace(issue.start, issue.end, "This is")
        self.assertEqual(composer.text, "😀 This is a sentence. Café are nice.")
        self.assertFalse(job.snapshot.matches(composer, OWNER))
        composer.handle(Key(CHAR, "_", ctrl=True))
        self.assertEqual(composer.text, before)

    def test_worker_polls_real_server(self) -> None:
        _, job = job_for(SAMPLE)
        worker = proofread.Worker()
        self.assertTrue(worker.start(job))
        self.assertFalse(worker.start(job))  # one pending
        worker.wait()
        outcome = worker.take()
        self.assertEqual(outcome.error, "")
        self.assertEqual(outcome.issues[0].original, "This are")
        self.assertIsNone(worker.take())
        self.assertTrue(worker.start(job))
        worker.wait()


class ReviewKeyTests(unittest.TestCase):
    def test_literal_action_labels_are_replacements_and_arming_blocks_enter(self) -> None:
        review = self.review()
        review.issues = [proofread.Issue(0, 3, "teh", "typo", ("Skip", "Cancel"))]
        review.armed_until = 10
        self.assertIsNone(review.handle_key(Key(ENTER), now=9))
        self.assertEqual(review.handle_key(Key(ENTER), now=11), ("accept", "Skip"))
        review.row = 1
        self.assertEqual(review.handle_key(Key(ENTER), now=11), ("accept", "Cancel"))

    def test_conservative_code_exclusions(self) -> None:
        for text in ("    secret code", "\tsecret code", "before `secret\ncode` after",
                     "before `secret code", "before\n~~~\nsecret code"):
            with self.subTest(text=text):
                guarded = proofread.protect(text, [])
                self.assertNotIn("secret", guarded.sent)
        self.assertIn("after", proofread.protect("before `secret\ncode` after", []).sent)

    def review(self) -> proofread.Review:
        _, job = job_for("teh cat")
        issue = proofread.Issue(0, 3, "teh", "typo", ("the", "ten"))
        return proofread.Review(job.snapshot, [issue])

    def test_skip_cancel_and_nothing_else_acts(self) -> None:
        review = self.review()
        self.assertIsNone(review.handle_key(Key(CHAR, "x")))
        self.assertIsNone(review.handle_key(Key(DOWN)))
        self.assertEqual(review.row, 1)
        review.row = 2
        self.assertEqual(review.handle_key(Key(ENTER)), ("skip", ""))
        review.row = 3
        self.assertEqual(review.handle_key(Key(ENTER)), ("cancel", ""))
        self.assertEqual(review.handle_key(Key(ESCAPE)), ("cancel", ""))


class FailureTests(unittest.TestCase):
    def test_trickled_response_obeys_elapsed_deadline_and_worker_recovers(self) -> None:
        with Served() as env, patch.object(proofread, "TIMEOUT_SECONDS", 0.15):
            Fake.reply = (200, b'{"matches": []}' + b" " * 100, {})
            env["OMH_PROOFREAD_URL"] = env["OMH_PROOFREAD_URL"].replace("/v2/check", "/trickle")
            _, job = job_for("teh cat", env=env)
            worker = proofread.Worker()
            started = time.monotonic()
            worker.start(job)
            worker.wait(1)
            outcome = worker.take()
            self.assertIsNotNone(outcome)
            self.assertTrue(outcome.error)
            self.assertLess(time.monotonic() - started, 0.8)
            self.assertFalse(worker.pending)
            self.assertTrue(worker.start(job))
            worker.wait(1)
            self.assertIsNotNone(worker.take())

    def test_unavailable_server(self) -> None:
        _, job = job_for("teh cat", env={"OMH_PROOFREAD_URL": "http://127.0.0.1:1/v2/check"})
        worker = proofread.Worker()
        worker.start(job)
        worker.wait()
        outcome = worker.take()
        self.assertIn("unavailable", outcome.error)
        self.assertEqual(outcome.issues, [])

    def test_redirect_refused_and_not_followed(self) -> None:
        with Served() as env:
            Fake.reply = (302, b"", {"Location": "http://127.0.0.1:1/elsewhere"})
            _, job = job_for("teh cat", env=env)
            with self.assertRaisesRegex(proofread.ProofreadError, "redirect"):
                proofread.post_check(job.endpoint, "teh cat")
            self.assertEqual(len(Fake.hits), 1)

    def test_oversized_reply_and_bad_json(self) -> None:
        with Served() as env:
            Fake.reply = (200, b"x" * (proofread.MAX_RESPONSE_BYTES + 10), {})
            _, job = job_for("teh cat", env=env)
            with self.assertRaisesRegex(proofread.ProofreadError, "too large"):
                proofread.post_check(job.endpoint, "teh cat")
            Fake.reply = (200, b"not json", {})
            with self.assertRaisesRegex(proofread.ProofreadError, "not JSON"):
                proofread.post_check(job.endpoint, "teh cat")

    def test_matches_inside_protected_spans_are_dropped(self) -> None:
        composer, job = job_for("`teh` and teh")
        payload = {"matches": [
            {"offset": 1, "length": 3, "message": "m", "replacements": [{"value": "the"}]},
            {"offset": 10, "length": 3, "message": "m", "replacements": [{"value": "the"}]},
            {"offset": 0, "length": 5, "message": "m", "replacements": [{"value": "the"}]},
        ]}
        issues = proofread.issues_from(payload, job)
        self.assertEqual([(i.start, i.original) for i in issues], [(10, "teh")])


class StaleTests(unittest.TestCase):
    def test_edit_away_and_back_is_stale(self) -> None:
        composer, job = job_for("teh cat")
        self.assertTrue(job.snapshot.matches(composer, OWNER))
        composer.replace(0, 3, "the")
        composer.replace(0, 3, "teh")
        self.assertEqual(composer.text, job.original)
        self.assertFalse(job.snapshot.matches(composer, OWNER))

    def test_typing_session_field_and_object_change_are_stale(self) -> None:
        composer, job = job_for("teh cat")
        self.assertFalse(job.snapshot.matches(composer, ("other", None)))
        self.assertFalse(job.snapshot.matches(composer, ("sid", "question-2")))
        twin = Composer()
        twin.replace(0, 0, "teh cat")
        self.assertFalse(job.snapshot.matches(twin, OWNER))

    def test_paste_metadata_change_with_same_text_is_stale(self) -> None:
        composer, job = job_for("teh cat")
        composer.pastes["[Pasted text #9 +3 lines]"] = "x"
        self.assertFalse(job.snapshot.matches(composer, OWNER))


if __name__ == "__main__":
    unittest.main()

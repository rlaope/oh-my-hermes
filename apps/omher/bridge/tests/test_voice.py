"""Voice (BOUNDARY rule 54): the bridge's one HTTP use. A recording goes to Hermes' own `POST /api/audio/transcribe` and
an answer's text, in parts, to `POST /api/audio/speak`, on the loopback listener of the bot's own gateway, each with a
fresh one-use `native-http` ticket and no `Origin`, through no proxy and following no redirect. A throwaway
`http.server` on loopback stands in for Hermes; no real gateway, ticket or microphone is used."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402

BOT = "demo-bot"
TICKET = "tk-" + "a" * 40
AUDIO = b"\x1aE\xdf\xa3 not really webm, only bytes " * 8
AUDIO_B64 = base64.b64encode(AUDIO).decode("ascii")


class FakeHermes:
    """One loopback HTTP server: records every request (method, path, query, headers, body) and answers with
    `self.reply(path, body)` -> (status, headers, body bytes); `self.delay` seconds before answering."""

    def __init__(self):
        self.seen: list[dict] = []
        self.reply = lambda path, body: (200, {}, b'{"ok": true, "transcript": "hello", "provider": "local"}')
        self.delay = 0.0
        self.trickle = False  # answer one byte every 0.1 s: a server that never quite stops sending
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                url = urlsplit(self.path)
                owner.seen.append({"method": "POST", "path": url.path, "query": parse_qs(url.query),
                                   "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                if owner.delay:
                    time.sleep(owner.delay)
                if owner.trickle:
                    self.send_response(200)
                    self.send_header("Content-Length", "100000")
                    self.end_headers()
                    try:
                        for _ in range(100):
                            self.wfile.write(b" ")
                            self.wfile.flush()
                            time.sleep(0.1)
                    except OSError:
                        pass
                    return
                status, headers, out = owner.reply(url.path, body)
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                try:
                    self.wfile.write(out)
                except OSError:
                    pass

            do_GET = do_POST  # noqa: N815

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.origin = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def answer(status: int, data) -> tuple:
    return status, {}, json.dumps(data).encode("utf-8")


class Request(unittest.TestCase):
    def setUp(self):
        self.hermes = FakeHermes()

    def tearDown(self):
        self.hermes.close()

    def send(self, which="transcribe", body=b'{"x": 1}', origin=None):
        return ob.voice_request(origin or self.hermes.origin, which, BOT, TICKET, body)

    def test_the_request_carries_the_ticket_the_profile_and_the_fixed_path_and_no_origin(self):
        got = self.send(body=b'{"data_url": "data:audio/webm;base64,AAAA"}')
        self.assertEqual(got["transcript"], "hello")
        self.assertEqual(len(self.hermes.seen), 1)
        req = self.hermes.seen[0]
        self.assertEqual((req["method"], req["path"]), ("POST", "/api/audio/transcribe"))
        self.assertEqual(req["query"], {"profile": [BOT]})
        self.assertEqual(req["headers"]["x-hermes-gateway-ticket"], TICKET)
        self.assertNotIn("origin", req["headers"])
        self.assertNotIn("cookie", req["headers"])
        self.assertEqual(req["headers"]["content-type"], "application/json")
        # the Host is the loopback address Hermes' own DNS-rebinding check accepts
        self.assertTrue(req["headers"]["host"].startswith("127.0.0.1:"))
        self.assertEqual(req["body"], b'{"data_url": "data:audio/webm;base64,AAAA"}')
        self.send("speak", b'{"text": "hi"}')
        self.assertEqual(self.hermes.seen[1]["path"], "/api/audio/speak")

    def test_only_the_two_fixed_paths(self):
        self.assertEqual(ob.VOICE_PATHS, {"transcribe": "/api/audio/transcribe", "speak": "/api/audio/speak"})
        for which in ("voice-config", "/api/audio/voice-config", "transcribe-stream", ""):
            with self.assertRaises(KeyError):
                self.send(which)
        self.assertEqual(self.hermes.seen, [])

    def test_a_non_loopback_origin_is_refused_before_any_socket_opens(self):
        opened = []
        real = ob.voice_target
        with mock.patch("http.client.HTTPConnection", lambda *a, **k: opened.append(a) or (_ for _ in ()).throw(AssertionError)):
            for origin in ("http://192.168.1.7:8080", "http://example.com:80", "http://localhost:9119", "https://10.0.0.1:9119",
                           "http://127.0.0.1", "http://127.0.0.1:9119/api", "http://user:pw@127.0.0.1:9119",
                           "http://127.0.0.1:9119?x=1", "ws://127.0.0.1:9119", "http://[::ffff:10.0.0.1]:80", "", None):
                with self.assertRaises(ob.VoiceError) as cm:
                    ob.voice_request(origin, "transcribe", BOT, TICKET, b"{}")
                self.assertEqual(cm.exception.code, "voice_refused", origin)
            # Hermes' discovery accepts an https loopback origin; omher has no TLS client, and says so in its own words
            with self.assertRaises(ob.VoiceError) as cm:
                ob.voice_request("https://127.0.0.1:9119", "transcribe", BOT, TICKET, b"{}")
            self.assertEqual(cm.exception.code, "voice_https")
            self.assertIn("over https", cm.exception.message)
        self.assertEqual(opened, [])
        self.assertEqual(real("http://[::1]:9119"), ("::1", 9119))
        self.assertEqual(real("http://127.0.0.1:9119"), ("127.0.0.1", 9119))

    def test_a_profile_that_is_not_hermes_id_is_never_sent(self):
        for bad in ("../x", "a b", "x&profile=default", "", "Bad"):
            with self.assertRaises(ob.VoiceError):
                ob.voice_request(self.hermes.origin, "transcribe", bad, TICKET, b"{}")
        self.assertEqual(self.hermes.seen, [])

    def test_a_redirect_is_not_followed(self):
        self.hermes.reply = lambda path, body: (302, {"Location": f"{self.hermes.origin}/api/audio/voice-config"}, b"")
        with self.assertRaises(ob.VoiceError) as cm:
            self.send()
        self.assertEqual(cm.exception.code, "voice_failed")
        self.assertIn("redirect", cm.exception.message)
        self.assertEqual([r["path"] for r in self.hermes.seen], ["/api/audio/transcribe"])

    def test_an_environment_proxy_is_never_used(self):
        proxy = FakeHermes()
        try:
            env = {k: proxy.origin for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")}
            with mock.patch.dict(os.environ, {**env, "NO_PROXY": "", "no_proxy": ""}):
                self.assertEqual(self.send()["transcript"], "hello")
            self.assertEqual(proxy.seen, [])
            self.assertEqual(len(self.hermes.seen), 1)
        finally:
            proxy.close()

    def test_the_answer_is_read_up_to_its_cap(self):
        big = json.dumps({"ok": True, "transcript": "x" * 5000}).encode()
        self.hermes.reply = lambda path, body: (200, {}, big)
        with mock.patch.dict(ob.VOICE_ANSWER_MAX, {"transcribe": 1000}):
            with self.assertRaises(ob.VoiceError) as cm:
                self.send()
        self.assertEqual(cm.exception.code, "voice_too_large")
        self.assertEqual(self.send()["transcript"], "x" * 5000)

    def test_a_slow_hermes_is_a_timeout(self):
        self.hermes.delay = 1.0
        with mock.patch.dict(ob.VOICE_TIMEOUT, {"transcribe": 0.2}):
            with self.assertRaises(ob.VoiceError) as cm:
                self.send()
        self.assertEqual(cm.exception.code, "voice_timeout")
        self.assertIn("did not answer", cm.exception.message)

    def test_a_server_that_trickles_is_cut_at_the_deadline_for_the_whole_exchange(self):
        self.hermes.trickle = True
        start = time.monotonic()
        with mock.patch.dict(ob.VOICE_TIMEOUT, {"transcribe": 0.6}):
            with self.assertRaises(ob.VoiceError) as cm:
                self.send()
        self.assertEqual(cm.exception.code, "voice_timeout")
        # each byte comes well within the per-read timeout, yet the whole exchange ends at its deadline, not after 10 s
        self.assertLess(time.monotonic() - start, 3.0)

    def test_a_ticket_never_reaches_an_error_or_a_log(self):
        records: list[logging.LogRecord] = []
        handler = logging.Handler(logging.DEBUG)
        handler.emit = records.append
        logging.getLogger().addHandler(handler)
        bad = "tk-secret\r\nX-Injected: 1"
        try:
            # a ticket that is not of Hermes' shape is never sent
            with self.assertRaises(ob.VoiceError) as cm:
                ob.voice_request(self.hermes.origin, "transcribe", BOT, bad, b"{}")
            self.assertNotIn("tk-secret", cm.exception.message)
            # and should http.client itself refuse a header value, its message (which holds the value) is dropped
            with mock.patch.object(ob, "VOICE_TICKET", ob.re.compile(r"[\s\S]+")):
                with self.assertRaises(ob.VoiceError) as cm:
                    ob.voice_request(self.hermes.origin, "transcribe", BOT, bad, b"{}")
            self.assertEqual(cm.exception.code, "voice_failed")
            self.assertNotIn("tk-secret", cm.exception.message)
        finally:
            logging.getLogger().removeHandler(handler)
        self.assertEqual(self.hermes.seen, [])
        self.assertNotIn("tk-secret", "\n".join(r.getMessage() for r in records))

    def test_nothing_listening_is_not_ready(self):
        origin = self.hermes.origin
        self.hermes.close()
        with self.assertRaises(ob.VoiceError) as cm:
            ob.voice_request(origin, "transcribe", BOT, TICKET, b"{}")
        self.assertEqual(cm.exception.code, "voice_not_ready")
        self.hermes = FakeHermes()

    def test_each_error_keeps_hermes_words_under_its_own_code(self):
        cases = [
            (503, {"error": "gateway_not_ready", "state": "starting"}, "voice_not_ready", "not ready"),
            (400, {"detail": "No STT provider available. Install faster-whisper for free local transcription"}, "voice_no_provider", "faster-whisper"),
            (400, {"detail": "No TTS provider available. Enable Edge TTS with: pip install edge-tts"}, "voice_no_provider", "Edge TTS"),
            (400, {"detail": "STT is disabled in config.yaml (stt.enabled: false)."}, "voice_disabled", "stt.enabled: false"),
            (400, {"detail": "Local STT fallback requires ffmpeg for non-WAV inputs, but ffmpeg was not found"}, "voice_failed", "ffmpeg"),
            (413, {"detail": "Audio recording is too large"}, "voice_too_large", "too large"),
            (500, {"detail": "Transcription failed: boom"}, "voice_failed", "Transcription failed: boom"),
            (401, {"detail": "Unauthorized"}, "voice_refused", "Unauthorized"),
            (403, {"detail": "profile_scope_mismatch"}, "voice_refused", "profile_scope_mismatch"),
            (404, {"detail": "Not Found"}, "voice_unsupported", "Update Hermes"),
            (422, {"detail": [{"loc": ["body"], "msg": "field required"}]}, "voice_failed", "HTTP 422"),
        ]
        for status, data, code, words in cases:
            self.hermes.reply = lambda path, body, s=status, d=data: answer(s, d)
            with self.assertRaises(ob.VoiceError) as cm:
                self.send()
            self.assertEqual(cm.exception.code, code, data)
            self.assertIn(words, cm.exception.message, data)

    def test_hermes_words_are_cleaned_and_clipped(self):
        self.hermes.reply = lambda path, body: answer(500, {"detail": "\x1b[31mTranscription failed:\x1b[0m bad\x07\nline‮" + "y" * 900})
        with self.assertRaises(ob.VoiceError) as cm:
            self.send()
        msg = cm.exception.message
        self.assertTrue(msg.startswith("Transcription failed: bad line"), msg)
        for ch in ("\x1b", "\x07", "\n", "‮"):
            self.assertNotIn(ch, msg)
        self.assertLessEqual(len(msg), ob.VOICE_DETAIL)

    def test_an_answer_that_is_not_hermes_is_refused(self):
        for raw in (b"<html>", b'{"ok": false}', b"[1]", b""):
            self.hermes.reply = lambda path, body, r=raw: (200, {}, r)
            with self.assertRaises(ob.VoiceError) as cm:
                self.send()
            self.assertEqual(cm.exception.code, "voice_failed", raw)


class Ticket(unittest.TestCase):
    """The ticket comes from Hermes' own `mint_ticket(home, endpoint, purpose="native-http")`, for the ready owner its
    own discovery finds; an older Hermes without it fails closed."""

    def modules(self, attach: types.ModuleType, state: str = "ready"):
        runtime = types.ModuleType("hermes_cli.gateway_runtime")
        endpoint = types.SimpleNamespace(api_origin="http://127.0.0.1:9119", profile_id="/h")
        runtime.gateway_profile_home = lambda home: Path(home)
        runtime.discover_gateway_endpoint = lambda home: types.SimpleNamespace(state=state, endpoint=endpoint if state == "ready" else None)
        pkg = types.ModuleType("hermes_cli")
        pkg.gateway_runtime = runtime
        pkg.__path__ = []
        return mock.patch.dict(sys.modules, {"hermes_cli": pkg, "hermes_cli.gateway_runtime": runtime,
                                             "hermes_cli.gateway_runtime_attach": attach,
                                             "hermes_cli.web_routers": types.ModuleType("hermes_cli.web_routers")})

    def attach(self, fn=None) -> types.ModuleType:
        mod = types.ModuleType("hermes_cli.gateway_runtime_attach")
        if fn is not None:
            mod.mint_ticket = fn
        return mod

    def test_one_native_http_ticket_per_request_from_hermes_own_mint(self):
        minted = []

        def mint_ticket(home, endpoint, *, purpose="interactive", scope=None):
            minted.append((home, endpoint.profile_id, purpose, scope))
            return f"t{len(minted)}"
        with self.modules(self.attach(mint_ticket)), mock.patch("importlib.util.find_spec", lambda name: object()):
            self.assertEqual(ob.voice_ticket_for(Path("/h")), ("http://127.0.0.1:9119", "t1"))
            self.assertEqual(ob.voice_ticket_for(Path("/h")), ("http://127.0.0.1:9119", "t2"))
        self.assertEqual(minted, [(Path("/h"), "/h", "native-http", None)] * 2)

    def test_an_older_hermes_without_mint_ticket_fails_closed(self):
        with self.modules(self.attach(None)):
            self.assertIn("Update Hermes", ob.voice_supported())
            with self.assertRaises(ob.VoiceError) as cm:
                ob.voice_ticket_for(Path("/h"))
        self.assertEqual(cm.exception.code, "voice_unsupported")

    def test_a_mint_ticket_without_purpose_fails_closed(self):
        with self.modules(self.attach(lambda home, endpoint: "t")), mock.patch("importlib.util.find_spec", lambda name: object()):
            with self.assertRaises(ob.VoiceError) as cm:
                ob.voice_ticket_for(Path("/h"))
        self.assertEqual(cm.exception.code, "voice_unsupported")

    def test_a_hermes_without_the_audio_routes_fails_closed(self):
        with self.modules(self.attach(lambda home, endpoint, purpose="interactive": "t")), \
                mock.patch("importlib.util.find_spec", lambda name: None):
            self.assertIn("no audio routes", ob.voice_supported())

    def test_a_gateway_that_is_not_ready_gets_no_ticket(self):
        minted = []
        with self.modules(self.attach(lambda home, endpoint, purpose="interactive": minted.append(1) or "t"), state="starting"), \
                mock.patch("importlib.util.find_spec", lambda name: object()):
            with self.assertRaises(ob.VoiceError) as cm:
                ob.voice_ticket_for(Path("/h"))
        self.assertEqual(cm.exception.code, "voice_not_ready")
        self.assertEqual(minted, [])

    def test_a_refused_mint_says_so_without_the_raw_error(self):
        class TicketUnavailable(RuntimeError):
            def __init__(self, reason):
                super().__init__(f"ticket_unavailable: {reason}")
                self.reason = reason

        def refuse(home, endpoint, *, purpose="interactive"):
            raise TicketUnavailable("bootstrap binding rejected")
        with self.modules(self.attach(refuse)), mock.patch("importlib.util.find_spec", lambda name: object()):
            with self.assertRaises(ob.VoiceError) as cm:
                ob.voice_ticket_for(Path("/h"))
        self.assertEqual(cm.exception.code, "voice_refused")
        self.assertIn("bootstrap binding rejected", cm.exception.message)


class Split(unittest.TestCase):
    def test_short_text_is_one_part_and_code_is_left_out(self):
        parts, cut = ob.speak_parts("Here is the fix.\n\n```python\nprint('x')\n```\n\n- first\n- second")
        self.assertEqual(parts, ["Here is the fix.\n\n- first\n- second"])
        self.assertFalse(cut)
        self.assertEqual(ob.speak_parts("```\nonly code\n```"), ([], False))
        self.assertEqual(ob.speak_parts("   \n "), ([], False))

    def test_long_text_splits_at_sentence_ends_under_the_part_size(self):
        sentence = "This sentence is about forty-five chars long. "
        parts, cut = ob.speak_parts(sentence * 100)
        self.assertGreater(len(parts), 1)
        self.assertFalse(cut)
        for p in parts:
            self.assertLessEqual(len(p), ob.SPEAK_PART_MAX)
            self.assertTrue(p.endswith("long."), p[-20:])
        self.assertEqual(" ".join(parts), (sentence * 100).strip())

    def test_cjk_text_without_spaces(self):
        ja = "これは長い答えの一文です。" * 300
        parts, _ = ob.speak_parts(ja)
        self.assertGreater(len(parts), 1)
        for p in parts:
            self.assertLessEqual(len(p), ob.SPEAK_PART_MAX)
            self.assertTrue(p.endswith("。"), p[-5:])
        self.assertEqual("".join(p.replace(" ", "") for p in parts), ja)
        # no sentence end at all: cut at the part's length, nothing lost
        ko = "가" * 4000
        parts, _ = ob.speak_parts(ko)
        self.assertEqual([len(p) for p in parts], [1500, 1500, 1000])
        self.assertEqual("".join(parts), ko)

    def test_one_very_long_sentence_splits_at_spaces(self):
        words = " ".join(f"w{i}" for i in range(2000))
        parts, _ = ob.speak_parts(words)
        self.assertGreater(len(parts), 1)
        for p in parts:
            self.assertLessEqual(len(p), ob.SPEAK_PART_MAX)
        self.assertEqual(" ".join(parts).split(), words.split())

    def test_the_total_is_bounded_at_a_sentence(self):
        text = "Short sentence number one here. " * 2000
        parts, cut = ob.speak_parts(text)
        self.assertTrue(cut)
        total = sum(len(p) for p in parts)
        self.assertLessEqual(total, ob.SPEAK_TEXT_MAX)
        self.assertGreater(total, ob.SPEAK_TEXT_MAX - ob.SPEAK_PART_MAX)
        self.assertTrue(parts[-1].endswith("here."))


class Config(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def read(self, yaml: str) -> dict:
        (self.dir / "config.yaml").write_text(yaml, encoding="utf-8")
        return ob.voice_config(self.dir)

    def test_what_the_config_names_and_where_it_goes(self):
        self.assertEqual(self.read("model: x\n"), {"stt": {"enabled": True, "provider": "", "where": "auto"},
                                                    "tts": {"provider": "edge", "where": "edge"}})
        self.assertEqual(self.read("stt:\n  provider: local\ntts:\n  provider: piper\n"),
                         {"stt": {"enabled": True, "provider": "local", "where": "local"}, "tts": {"provider": "piper", "where": "local"}})
        self.assertEqual(self.read("stt:\n  provider: OpenAI\ntts:\n  provider: elevenlabs\n"),
                         {"stt": {"enabled": True, "provider": "openai", "where": "online"}, "tts": {"provider": "elevenlabs", "where": "online"}})
        self.assertEqual(self.read("stt:\n  enabled: false\n  provider: groq\n")["stt"], {"enabled": False, "provider": "groq", "where": "off"})
        self.assertEqual(self.read("stt:\n  enabled: 'off'\n")["stt"]["enabled"], False)
        self.assertEqual(self.read("stt:\n  use_gateway: true\ntts:\n  use_gateway: 'yes'\n"),
                         {"stt": {"enabled": True, "provider": "nous", "where": "online"}, "tts": {"provider": "nous", "where": "online"}})
        self.assertEqual(self.read("tts:\n  provider: my-command\n")["tts"], {"provider": "my-command", "where": "other"})
        self.assertEqual(self.read("tts:\n  provider: 'a b; c'\n")["tts"], {"provider": "other", "where": "other"})

    def test_no_key_is_read_back(self):
        got = self.read("stt:\n  provider: openai\n  openai:\n    api_key: sk-SECRET\ntts:\n  elevenlabs:\n    api_key: el-SECRET\n")
        self.assertNotIn("SECRET", json.dumps(got))


class Ops(unittest.TestCase):
    """The ops end to end against the fake Hermes: the page's fields in, Hermes' answer out, nothing kept."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.home = self.root / "hermes"
        for path in (self.home / "config.yaml", self.home / "profiles" / BOT / "config.yaml"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("model: x\n", encoding="utf-8")
        self.hermes = FakeHermes()
        self.tickets: list[Path] = []
        self.bridge = ob.Bridge(token="t", hermes_home=self.home, omher_home=self.root / "omher",
                                voice_ticket=lambda home: self.tickets.append(Path(home)) or (self.hermes.origin, TICKET))
        conn = ob.Conn(next(b for b in ob.discover_bots(self.home) if b["name"] == BOT))
        conn.client = object()
        self.bridge.conns[BOT] = conn

    def tearDown(self):
        self.hermes.close()
        self._tmp.cleanup()

    def op(self, name: str, **p):
        return asyncio.run(getattr(self.bridge, f"op_voice_{name}")({"bot": BOT, **p}))

    def refused(self, name: str, code: str, **p) -> ob.BridgeError:
        with self.assertRaises(ob.BridgeError) as cm:
            self.op(name, **p)
        self.assertEqual(cm.exception.code, code, cm.exception.message)
        return cm.exception

    def test_transcribe_sends_hermes_data_url_and_returns_the_transcript(self):
        self.hermes.reply = lambda path, body: answer(200, {"ok": True, "transcript": " 안녕하세요\x1b[2J\x00 ", "provider": "local"})
        got = self.op("transcribe", data_base64=AUDIO_B64, mime="audio/webm;codecs=opus")
        self.assertEqual(got, {"transcript": "안녕하세요", "provider": "local"})
        body = json.loads(self.hermes.seen[0]["body"])
        self.assertEqual(body, {"data_url": f"data:audio/webm;base64,{AUDIO_B64}", "mime_type": "audio/webm"})
        self.assertEqual(self.tickets, [self.home / "profiles" / BOT])
        # silence: Hermes answers 200 with an empty transcript, passed on as it is
        self.hermes.reply = lambda path, body: answer(200, {"ok": True, "transcript": "", "provider": "local"})
        self.assertEqual(self.op("transcribe", data_base64=AUDIO_B64, mime="audio/mp4")["transcript"], "")

    def test_the_page_names_no_address_path_host_or_header(self):
        # whatever else the page puts in the frame is never read: the request is the bridge's own
        self.op("transcribe", data_base64=AUDIO_B64, mime="audio/ogg", url="http://evil.example/", path="/api/audio/voice-config",
                host="evil.example", headers={"Origin": "http://evil.example"}, profile="default", origin="http://x")
        req = self.hermes.seen[0]
        self.assertEqual(req["path"], "/api/audio/transcribe")
        self.assertEqual(req["query"], {"profile": [BOT]})
        self.assertNotIn("origin", req["headers"])

    def test_a_recording_is_checked_before_anything_is_sent(self):
        self.refused("transcribe", "bad_request", data_base64=AUDIO_B64, mime="text/plain")
        self.refused("transcribe", "bad_request", data_base64=AUDIO_B64, mime="application/octet-stream")
        self.refused("transcribe", "bad_request", data_base64="", mime="audio/webm")
        self.refused("transcribe", "bad_request", data_base64="not base64!", mime="audio/webm")
        with mock.patch.object(ob, "VOICE_AUDIO_B64_MAX", 64):
            e = self.refused("transcribe", "voice_too_large", data_base64=AUDIO_B64, mime="audio/webm")
        self.assertIn("25 MB", e.message)
        self.assertEqual((self.hermes.seen, self.tickets), ([], []))

    def test_the_recording_is_checked_and_encoded_off_the_event_loop(self):
        seen: list[bool] = []
        real = ob.VOICE_B64

        class Watch:
            @staticmethod
            def fullmatch(text):
                seen.append(threading.current_thread() is threading.main_thread())
                return real.fullmatch(text)
        dumps = ob.json.dumps

        def watched_dumps(obj, *a, **k):
            if isinstance(obj, dict) and "data_url" in obj:
                seen.append(threading.current_thread() is threading.main_thread())
            return dumps(obj, *a, **k)
        with mock.patch.object(ob, "VOICE_B64", Watch), mock.patch.object(ob.json, "dumps", watched_dumps):
            self.op("transcribe", data_base64=AUDIO_B64, mime="audio/webm")
        self.assertEqual(seen, [False, False])  # both ran in the worker thread, never on the loop's own thread

        # read aloud: the split of the answer's text and the check of Hermes' audio answer run off the loop too
        seen.clear()
        split, audio = ob.speak_parts, ob.SPEAK_DATA_URL

        def watched_split(text):
            seen.append(("split", threading.current_thread() is threading.main_thread()))
            return split(text)

        class WatchAudio:
            @staticmethod
            def fullmatch(text):
                seen.append(("audio", threading.current_thread() is threading.main_thread()))
                return audio.fullmatch(text)
        mp3 = base64.b64encode(b"ID3 fake mp3").decode()
        self.hermes.reply = lambda path, body: answer(200, {"ok": True, "data_url": f"data:audio/mpeg;base64,{mp3}", "provider": "edge"})
        with mock.patch.object(ob, "speak_parts", watched_split), mock.patch.object(ob, "SPEAK_DATA_URL", WatchAudio):
            got = self.op("speak", text="Read this one aloud.")
            self.hermes.reply = lambda path, body: answer(200, {"ok": True, "data_url": "data:text/html;base64,PGI+"})
            self.refused("speak", "voice_failed", text="Read this one aloud.")  # the code is unchanged
        self.assertEqual((got["mime"], got["data_base64"], got["provider"]), ("audio/mpeg", mp3, "edge"))
        self.assertEqual(seen, [("split", False), ("audio", False)] * 2)

    def test_an_offline_bot_and_an_unknown_bot_send_nothing(self):
        self.bridge.conns[BOT].client = None
        self.refused("transcribe", "bot_offline", data_base64=AUDIO_B64, mime="audio/webm")
        self.refused("speak", "bot_offline", text="Hello.")
        with self.assertRaises(ob.BridgeError) as cm:
            asyncio.run(self.bridge.op_voice_speak({"bot": "nobody", "text": "x"}))
        self.assertEqual(cm.exception.code, "unknown_bot")
        self.assertEqual((self.hermes.seen, self.tickets), ([], []))

    def test_hermes_refusal_reaches_the_page_with_its_code(self):
        self.hermes.reply = lambda path, body: answer(400, {"detail": "STT is disabled in config.yaml (stt.enabled: false)."})
        e = self.refused("transcribe", "voice_disabled", data_base64=AUDIO_B64, mime="audio/webm")
        self.assertEqual(e.message, "STT is disabled in config.yaml (stt.enabled: false).")
        self.hermes.reply = lambda path, body: answer(503, {"error": "gateway_not_ready"})
        self.refused("speak", "voice_not_ready", text="Hello.")

    def test_speak_reads_each_part_and_says_how_many(self):
        mp3 = base64.b64encode(b"ID3 fake mp3").decode()
        self.hermes.reply = lambda path, body: answer(200, {"ok": True, "data_url": f"data:audio/mpeg;base64,{mp3}",
                                                            "mime_type": "audio/mpeg", "provider": "edge"})
        text = "First sentence of a long answer. " * 120
        got = self.op("speak", text=text)
        parts, _ = ob.speak_parts(text)
        self.assertEqual(got, {"part": 0, "parts": len(parts), "cut": False, "text_max": ob.SPEAK_TEXT_MAX, "empty": False,
                               "mime": "audio/mpeg", "data_base64": mp3, "provider": "edge"})
        self.assertEqual(json.loads(self.hermes.seen[0]["body"]), {"text": parts[0]})
        self.op("speak", text=text, part=len(parts) - 1)
        self.assertEqual(json.loads(self.hermes.seen[1]["body"]), {"text": parts[-1]})
        self.refused("speak", "bad_request", text=text, part=len(parts))
        self.refused("speak", "bad_request", text=text, part=-1)
        self.refused("speak", "bad_request", text=text, part="1")
        self.refused("speak", "voice_empty", text="```\ncode only\n```")
        with mock.patch.object(ob, "SPEAK_INPUT_MAX", 10):
            self.refused("speak", "voice_too_large", text="x" * 11)

    def test_a_part_hermes_finds_empty_is_skipped_and_audio_that_is_not_audio_refused(self):
        self.hermes.reply = lambda path, body: answer(400, {"detail": "Text is empty after TTS cleanup"})
        self.assertTrue(self.op("speak", text="https://example.com")["empty"])
        self.hermes.reply = lambda path, body: answer(200, {"ok": True, "data_url": "data:text/html;base64,PGI+", "provider": "edge"})
        self.refused("speak", "voice_failed", text="Hello.")

    def test_info_says_what_the_config_names_and_whether_hermes_takes_voice(self):
        (self.home / "profiles" / BOT / "config.yaml").write_text("model: x\nstt:\n  provider: local\n", encoding="utf-8")
        with mock.patch.object(ob, "voice_supported", lambda: ""):
            got = self.op("info")
        self.assertEqual(got, {"supported": True, "line": "", "stt": {"enabled": True, "provider": "local", "where": "local"},
                               "tts": {"provider": "edge", "where": "edge"}, "text_max": ob.SPEAK_TEXT_MAX})
        with mock.patch.object(ob, "voice_supported", lambda: "This Hermes has no audio routes. Update Hermes to use voice."):
            got = self.op("info")
        self.assertEqual((got["supported"], got["line"]), (False, "This Hermes has no audio routes. Update Hermes to use voice."))
        self.assertEqual(self.hermes.seen, [])

    def test_nothing_is_written_to_disk_or_logged(self):
        temp = self.root / "tmp"
        temp.mkdir()
        before = sorted(p for p in self.root.rglob("*"))
        records: list[logging.LogRecord] = []
        handler = logging.Handler(logging.DEBUG)
        handler.emit = records.append
        root = logging.getLogger()
        old = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            with mock.patch.object(tempfile, "tempdir", str(temp)):
                self.op("transcribe", data_base64=AUDIO_B64, mime="audio/webm")
                mp3 = base64.b64encode(b"ID3 secret audio").decode()
                self.hermes.reply = lambda path, body: answer(200, {"ok": True, "data_url": f"data:audio/mpeg;base64,{mp3}", "provider": "edge"})
                self.op("speak", text="A private answer to read.")
                self.hermes.reply = lambda path, body: answer(500, {"detail": "Transcription failed"})
                with self.assertRaises(ob.BridgeError):
                    self.op("transcribe", data_base64=AUDIO_B64, mime="audio/webm")
        finally:
            root.removeHandler(handler)
            root.setLevel(old)
        self.assertEqual(sorted(p for p in self.root.rglob("*")), before)
        logged = "\n".join(r.getMessage() for r in records)
        for needle in (AUDIO_B64[:24], mp3, "private answer", TICKET):
            self.assertNotIn(needle, logged)


class Peer(unittest.TestCase):
    def test_a_bot_on_another_computer_is_refused_with_the_reason(self):
        bridge = ob.Bridge(token="t", hermes_home=Path(tempfile.gettempdir()) / "omher-no-home")
        link = ob.PeerLink("mac", "Mac mini", "demo@host.example", "ws://127.0.0.1:1/?token=" + "0" * 32)
        link.rows = [{"name": "mini"}]
        bridge.peers["mac"] = link
        for op in ("voice.info", "voice.transcribe", "voice.speak"):
            with self.assertRaises(ob.BridgeError) as cm:
                asyncio.run(bridge._peer_op({"op": op, "bot": "mac:mini", "text": "x", "data_base64": AUDIO_B64, "mime": "audio/webm"}))
            self.assertEqual(cm.exception.code, "remote_bot", op)
            self.assertIn("Mac mini's bots run on another one", cm.exception.message)
            self.assertNotIn(op, ob.PEER_FORWARD)


if __name__ == "__main__":
    unittest.main()

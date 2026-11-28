"""A bot's browser steps in chat (BOUNDARY rule 53): `browser_exec` shows the `# label` its code starts with, `browser_cdp`
its method, `browser_dialog` and `browser_vault` their action, and none of them its code, params, typed text or result,
on the main chat, a subagent's step and the Plans session view. The screenshot a `browser_exec` or `computer_use` step
captured is read at its `tool.complete`, only from the bot's cache and browser-harness' tmp folder, as a regular image
file of at most 5 MB reached through no link. Every test uses temp folders and a fake gateway: no real Hermes or browser."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402

SECRET = "hunter2-typed-secret"
# what a model sends: a label, then code with a URL, a selector and the text it types into the page
CODE = f"# Logging in to the shop\nnew_tab('https://shop.example/login')\nfill_input('#password', '{SECRET}')\nclick_at_xy(10, 20)\n"
NO_LABEL = f"new_tab('https://shop.example/login')\nfill_input('#password', '{SECRET}')\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


class Label(unittest.TestCase):
    def test_the_first_line_when_it_is_a_comment(self):
        self.assertEqual(ob.browser_label(CODE), "Logging in to the shop")
        self.assertEqual(ob.browser_label("\n\n   #   Searching Amazon   \nx = 1"), "Searching Amazon")
        self.assertEqual(ob.browser_label("## Reading the cart\r\nprint(1)"), "Reading the cart")

    def test_no_label_is_empty_and_nothing_else_of_the_code_is_read(self):
        self.assertEqual(ob.browser_label(NO_LABEL), "")
        self.assertEqual(ob.browser_label("x = 1\n# a comment on the second line"), "")
        self.assertEqual(ob.browser_label("#!/usr/bin/env python\n# Searching"), "")
        self.assertEqual(ob.browser_label("#"), "")
        self.assertEqual(ob.browser_label(""), "")
        for bad in (None, 7, ["# x"], {"code": "# x"}):
            self.assertEqual(ob.browser_label(bad), "")

    def test_a_long_label_is_clipped_and_cleaned_to_one_line(self):
        got = ob.browser_label("# " + "a" * 100 + "\nx")
        self.assertEqual(len(got), ob.BROWSER_LABEL_MAX)
        self.assertTrue(got.endswith("…"))
        self.assertEqual(ob.browser_label("# Opening\x1b[2J the\x07 page‮\nx"), "Opening the page")
        # a bidi control first leaves no space in front once it is cleaned
        self.assertEqual(ob.browser_label("#‮ Opening the page\nx"), "Opening the page")

    def test_secret_shaped_text_in_a_label_is_masked_as_the_plans_view_masks_it(self):
        key = "sk-ant-api03-" + "A" * 40
        got = ob.browser_label(f"# Log in with {key}\nx")
        self.assertEqual(got, "Log in with ••••")
        self.assertNotIn(key, got)
        self.assertEqual(ob.mask_secrets(f"Log in with {key}"), got)
        self.assertEqual(ob.browser_label("# Sign in, password=hunter2\nx"), "Sign in, password=••••")
        # the same label on every path: the main chat's detail and the session view's input
        self.assertEqual(ob.tool_detail("browser_exec", {"code": f"# Log in with {key}\nx"}, key), "Log in with ••••")
        self.assertEqual(ob.browser_args("browser_exec", {"code": f"# Log in with {key}\nx"}), {"label": "Log in with ••••"})


class StepLines(unittest.TestCase):
    def test_each_tool_line(self):
        self.assertEqual(ob.browser_step("browser_exec", {"code": CODE, "session": "r7k2"}), ("", "Logging in to the shop"))
        self.assertEqual(ob.browser_step("browser_exec", {"code": NO_LABEL}), ("", ""))
        self.assertEqual(ob.browser_step("browser_cdp", {"method": "Input.insertText", "params": {"text": SECRET}}),
                         ("", "Input.insertText"))
        self.assertEqual(ob.browser_step("browser_cdp", {"method": f"Runtime.evaluate('{SECRET}')"}), ("", ""))
        self.assertEqual(ob.browser_step("browser_dialog", {"action": "accept", "prompt_text": SECRET}), ("accept", ""))
        self.assertEqual(ob.browser_step("browser_dialog", {"action": "dismiss"}), ("dismiss", ""))
        self.assertEqual(ob.browser_step("browser_dialog", {"action": SECRET}), ("", ""))
        for action in ("list", "fill", "save_login", "enter_code", "unlock"):
            self.assertEqual(ob.browser_step("browser_vault", {"action": action, "handle": "h_123", "label": "My bank"}), (action, ""))
        self.assertEqual(ob.browser_step("browser_vault", {"action": "export"}), ("", ""))
        for odd in (["fill"], {"a": 1}, 7, None):
            self.assertEqual(ob.browser_step("browser_vault", {"action": odd}), ("", ""))
            self.assertEqual(ob.browser_step("browser_dialog", {"action": odd}), ("", ""))
        self.assertEqual(ob.browser_step("browser_cdp", {"method": ["Page.navigate"]}), ("", ""))
        self.assertEqual(ob.browser_step("browser_exec", "not args"), ("", ""))

    def test_the_detail_is_never_hermes_preview_for_a_browser_tool(self):
        # Hermes' `context` for browser_exec without a label is the code on one line
        self.assertEqual(ob.tool_detail("browser_exec", {"code": CODE}, "Logging in to the shop"), "Logging in to the shop")
        self.assertEqual(ob.tool_detail("browser_exec", {"code": NO_LABEL}, " ".join(NO_LABEL.split())), "")
        self.assertEqual(ob.tool_detail("browser_cdp", {"method": "Page.navigate", "params": {"url": "x"}}, SECRET), "Page.navigate")
        self.assertEqual(ob.tool_detail("browser_dialog", {"action": "accept", "prompt_text": SECRET}, SECRET), "")
        self.assertEqual(ob.tool_detail("browser_vault", {"action": "fill", "handle": "h"}, SECRET), "")
        # an older Hermes: browser_navigate keeps its url; any other old browser tool (browser_type's text) shows nothing
        self.assertEqual(ob.tool_detail("browser_navigate", {"url": "https://example.com"}, "x"), "https://example.com")
        self.assertEqual(ob.tool_detail("browser_type", {"ref": "@e3", "text": SECRET}, SECRET), "")
        self.assertFalse(ob.browser_quiet("browser_navigate"))
        self.assertTrue(all(ob.browser_quiet(t) for t in ob.BROWSER_TOOLS | {"browser_type", "browser_click"}))
        self.assertFalse(ob.browser_quiet("terminal"))


def _bridge_and_sent(profile: Path):
    bridge = ob.Bridge(token="t", hermes_home=Path(tempfile.gettempdir()) / "omher-no-home")
    conn = ob.Conn({"name": "kami", "path": profile, "display_name": "Kami"})
    sent: list[tuple[str, dict]] = []

    async def emit(c, chat, event, **fields):
        sent.append((event, fields))

    async def begin(c, chat=None):
        return None
    bridge._chat_emit = emit
    bridge._begin_turn = begin
    return bridge, conn, sent


class MainChat(unittest.TestCase):
    def test_no_code_params_or_typed_text_reaches_the_page(self):
        bridge, conn, sent = _bridge_and_sent(Path("/nowhere"))
        calls = [("b1", "browser_exec", {"code": CODE}, "Logging in to the shop"),
                 ("b2", "browser_exec", {"code": NO_LABEL}, " ".join(NO_LABEL.split())[:80]),
                 ("b3", "browser_cdp", {"method": "Input.insertText", "params": {"text": SECRET}}, f"Input.insertText {SECRET}"),
                 ("b4", "browser_dialog", {"action": "accept", "prompt_text": SECRET}, SECRET),
                 ("b5", "browser_vault", {"action": "fill", "handle": "h_1", "label": SECRET}, SECRET)]
        for tid, name, args, ctx in calls:
            asyncio.run(bridge._main_event(conn, "tool.start", {}, {"tool_id": tid, "name": name, "context": ctx, "args": args}))
            asyncio.run(bridge._main_event(conn, "tool.complete", {}, {
                "tool_id": tid, "name": name, "args": args, "result": {"output": SECRET, "success": True}}))
        starts = [f for e, f in sent if e == "tool.start"]
        self.assertEqual([(f["name"], f["detail"], f.get("action")) for f in starts],
                         [("browser_exec", "Logging in to the shop", None), ("browser_exec", "", None),
                          ("browser_cdp", "Input.insertText", None), ("browser_dialog", "", "accept"),
                          ("browser_vault", "", "fill")])
        self.assertEqual({e for e, _ in sent}, {"tool.start", "tool.end"})
        self.assertNotIn(SECRET, json.dumps(sent))
        self.assertNotIn("fill_input", json.dumps(sent))


class Subagent(unittest.TestCase):
    def test_a_childs_browser_step_carries_no_preview(self):
        for tool in ("browser_exec", "browser_cdp", "browser_dialog", "browser_vault", "browser_type"):
            for key in ("tool_preview", "text"):
                got = ob.subagent_fields("subagent.tool", {"subagent_id": "s1", "tool_name": tool, key: f"fill_input('#pw', '{SECRET}')"})
                self.assertEqual(got["tool"], tool)
                self.assertNotIn("step", got)
                self.assertNotIn(SECRET, json.dumps(got))
        # the old browser_navigate's preview is its url, kept
        got = ob.subagent_fields("subagent.tool", {"subagent_id": "s1", "tool_name": "browser_navigate", "tool_preview": "https://example.com"})
        self.assertEqual(got["step"], "https://example.com")


class SessionView(unittest.TestCase):
    def test_args_keep_the_label_method_or_action_only(self):
        self.assertEqual(ob.browser_args("browser_exec", json.dumps({"code": CODE, "session": "r7k2", "timeout_s": 30})),
                         {"label": "Logging in to the shop"})
        self.assertEqual(ob.browser_args("browser_exec", json.dumps({"code": NO_LABEL})), {})
        self.assertEqual(ob.browser_args("browser_cdp", {"method": "Network.getCookies", "params": {"urls": ["x"]}}),
                         {"method": "Network.getCookies"})
        self.assertEqual(ob.browser_args("browser_dialog", {"action": "accept", "prompt_text": SECRET}), {"action": "accept"})
        self.assertEqual(ob.browser_args("browser_vault", {"action": "save_login", "label": "My bank", "handle": "h"}),
                         {"action": "save_login"})
        self.assertEqual(ob.browser_args("browser_type", {"text": SECRET}), {})
        self.assertEqual(ob.browser_args("browser_exec", "not json"), {})

    def test_a_recorded_session_shows_no_code_params_typed_text_or_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            prof = Path(tmp) / "profiles" / "kami"
            prof.mkdir(parents=True)
            con = sqlite3.connect(prof / "state.db")
            con.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, parent_session_id TEXT, model TEXT,"
                        " billing_provider TEXT, started_at REAL, ended_at REAL, end_reason TEXT, title TEXT)")
            con.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT,"
                        " content TEXT, tool_calls TEXT, tool_name TEXT, tool_call_id TEXT, timestamp REAL)")
            sid = "20261128_101500_beef01"
            con.execute("INSERT INTO sessions (id, source, started_at, ended_at, title) VALUES (?,?,?,?,?)",
                        (sid, "delegate", 1.0, 2.0, "child"))
            fn = lambda cid, name, args: {"id": cid, "function": {"name": name, "arguments": json.dumps(args)}}  # noqa: E731
            calls = [fn("c1", "browser_exec", {"code": CODE}), fn("c2", "browser_cdp", {"method": "Input.insertText", "params": {"text": SECRET}}),
                     fn("c3", "browser_dialog", {"action": "accept", "prompt_text": SECRET}),
                     fn("c4", "browser_vault", {"action": "save_login", "label": "bank"}),
                     fn("c5", "vision_analyze", {"image_url": "/x.png", "question": "what is it"})]
            # a multimodal browser_exec row as Hermes stores it (its `\x00json:` envelope with the capture as a data URL)
            envelope = "\x00json:" + json.dumps({"_multimodal": True, "text_summary": json.dumps({"output": f"typed {SECRET}"}),
                                                  "content": [{"type": "text", "text": f"typed {SECRET}"},
                                                              {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + "Q" * 6000}}]})
            rows = [("user", "Log in", None, None, None), ("assistant", "", json.dumps(calls), None, None),
                    ("tool", envelope, None, "browser_exec", "c1"),
                    ("tool", json.dumps({"success": True, "result": {"cookie": SECRET}}), None, "browser_cdp", "c2"),
                    ("tool", json.dumps({"success": False, "error": "no dialog", "dialog": {"message": SECRET}}), None, "browser_dialog", "c3"),
                    ("tool", json.dumps({"success": True, "identifier": "me@example.com"}), None, "browser_vault", "c4"),
                    ("tool", "a cat; seen in data:image/png;base64," + "B" * 5000 + " and more", None, "vision_analyze", "c5"),
                    ("assistant", "Done.", None, None, None)]
            for role, content, tc, tname, tcid in rows:
                con.execute("INSERT INTO messages (session_id, role, content, tool_calls, tool_name, tool_call_id, timestamp)"
                            " VALUES (?,?,?,?,?,?,?)", (sid, role, content, tc, tname, tcid, 1.5))
            con.commit()
            con.close()
            got = ob.NodeSessions(homes={"claude": Path(tmp) / "c", "codex": Path(tmp) / "x"}).hermes_read(prof, sid)
        dump = json.dumps(got)
        for leak in (SECRET, "fill_input", "me@example.com", "QQQQ", "BBBB", "base64"):
            self.assertNotIn(leak, dump, leak)
        steps = got["steps"]
        self.assertEqual([st["tool"] for st in steps], ["browser_exec", "browser_cdp", "browser_dialog", "browser_vault", "vision_analyze"])
        self.assertEqual(json.loads(steps[0]["input"]), {"label": "Logging in to the shop"})
        self.assertEqual(json.loads(steps[1]["input"]), {"method": "Input.insertText"})
        self.assertEqual(json.loads(steps[2]["input"]), {"action": "accept"})
        self.assertEqual([st["result"] for st in steps[:4]], ["", "", "", ""])
        # ok / failed stays, read from the result before it was dropped
        self.assertEqual([st["ok"] for st in steps[:4]], [True, True, False, True])
        # another tool's result keeps its text with the image as a marker
        self.assertEqual(steps[4]["result"], "a cat; seen in [image] and more")


def _png(path: Path, body: bytes = PNG) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def _key(profile) -> str:
    """A stand-in for Hermes' hermes_home_key in these tests: one key per profile path."""
    return f"key:{profile}"


def _leaf(profile) -> str:
    return "p-" + hashlib.sha256(_key(profile).encode()).hexdigest()[:12]


class ShotRead(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.profile = self.tmp / "hermes" / "profiles" / "kami"
        self.harness = self.tmp / "bh"
        self._key = mock.patch.object(ob, "_hermes_home_key", _key)
        self._key.start()
        self.roots = ob.shot_roots(self.profile, {"BH_HOME": str(self.harness)})
        self.own = self.harness / "tmp" / _leaf(self.profile)

    def tearDown(self) -> None:
        self._key.stop()
        self._tmp.cleanup()

    def read(self, path) -> dict | None:
        return ob.read_step_shot(str(path), self.roots)

    def test_the_roots_are_the_bots_cache_and_its_own_harness_folder_as_hermes_resolves_it(self):
        self.assertEqual(self.roots, (self.profile / "cache", self.profile / "image_cache", self.own))
        # without Hermes' home key there is no harness folder to read
        with mock.patch.object(ob, "_hermes_home_key", lambda p: None):
            self.assertEqual(ob.shot_roots(self.profile, {}), (self.profile / "cache", self.profile / "image_cache"))
        # a broad BH_TMP_DIR still names only this bot's own folder under it
        self.assertEqual(ob.harness_shot_root(self.profile, {"BH_TMP_DIR": "/"}), Path("/") / _leaf(self.profile))
        self.assertEqual(ob.harness_tmp_root({"BH_TMP_DIR": "/t/x", "BH_HOME": "/ignored"}), Path("/t/x"))
        self.assertEqual(ob.harness_tmp_root({"BROWSER_HARNESS_HOME": "/b"}), Path("/b") / "tmp")
        self.assertEqual(ob.harness_tmp_root({"XDG_CONFIG_HOME": "/xdg"}), Path("/xdg") / "browser-harness" / "tmp")
        self.assertEqual(ob.harness_tmp_root({"HOME": "/home/me"}), Path("/home/me") / ".config" / "browser-harness" / "tmp")
        # no HOME (Windows): the user's home, as Path.home() gives it
        self.assertEqual(ob.harness_tmp_root({}), Path.home() / ".config" / "browser-harness" / "tmp")

    def test_a_capture_under_each_root_is_read_as_its_bytes_say(self):
        for path, body, mime in ((self.profile / "cache" / "images" / "computer_use_ab12.png", PNG, "image/png"),
                                 (self.profile / "cache" / "browser-use" / "workspace" / "t1" / "cart.jpg", JPEG, "image/jpeg"),
                                 (self.own / "shot.png", PNG, "image/png"),
                                 (self.profile / "image_cache" / "computer_use_cd34.png", PNG, "image/png"),
                                 # the name says png, the bytes say jpeg: the bytes win
                                 (self.own / "q.png", JPEG, "image/jpeg")):
            got = self.read(_png(path, body))
            self.assertEqual(got, {"mime": mime, "data_base64": base64.b64encode(body).decode("ascii")}, path)

    def test_outside_the_roots_is_not_read(self):
        for path in (self.tmp / "elsewhere" / "shot.png", self.profile / "shot.png", self.profile / "cachex" / "a.png",
                     self.tmp / "hermes" / "cache" / "images" / "other_profile.png",
                     # another bot's harness folder, and the harness tmp folder itself
                     self.harness / "tmp" / _leaf(self.tmp / "hermes" / "profiles" / "friren") / "shot.png",
                     self.harness / "tmp" / "shot.png"):
            self.assertIsNone(self.read(_png(path)), path)
        # a `..` that climbs out, a relative path, nothing
        _png(self.tmp / "secret.png")
        self.assertIsNone(self.read(f"{self.profile}/cache/../../../../secret.png"))
        self.assertIsNone(self.read("cache/images/a.png"))
        for bad in ("", None, 7, "\x00/x.png"):
            self.assertIsNone(ob.read_step_shot(bad, self.roots))

    def test_missing_a_folder_too_large_or_not_an_image_is_not_read(self):
        self.assertIsNone(self.read(self.profile / "cache" / "images" / "gone.png"))
        folder = self.profile / "cache" / "images" / "dir.png"
        folder.mkdir(parents=True)
        self.assertIsNone(self.read(folder))
        big = _png(self.profile / "cache" / "images" / "big.png", PNG + b"\x00" * ob.SHOT_MAX)
        self.assertIsNone(self.read(big))
        exact = _png(self.profile / "cache" / "images" / "exact.png", PNG + b"\x00" * (ob.SHOT_MAX - len(PNG)))
        self.assertEqual(self.read(exact)["mime"], "image/png")
        for name, body in (("page.png", b"<html>secret</html>"), ("x.png", b"GIF8"), ("y.webp", b"RIFF\x00\x00\x00\x00WEBQ"),
                           ("z.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>")):
            self.assertIsNone(self.read(_png(self.profile / "cache" / "images" / name, body)), name)
        self.assertEqual(ob.shot_mime(b"GIF89a\x01\x00"), "image/gif")
        self.assertEqual(ob.shot_mime(b"RIFF\x10\x00\x00\x00WEBPVP8 "), "image/webp")

    @unittest.skipIf(os.name == "nt", "creating symlinks needs a privilege on Windows")
    def test_never_through_a_symbolic_link(self):
        outside = _png(self.tmp / "outside" / "secret.png")
        inside = _png(self.profile / "cache" / "images" / "real.png")
        # the file itself a link: to a file outside, and to a file inside
        link = self.profile / "cache" / "images" / "link.png"
        os.symlink(outside, link)
        self.assertIsNone(self.read(link))
        link2 = self.profile / "cache" / "images" / "link2.png"
        os.symlink(inside, link2)
        self.assertIsNone(self.read(link2))
        # a folder between the root and the file a link: outside, and back inside
        os.symlink(self.tmp / "outside", self.profile / "cache" / "out")
        self.assertIsNone(self.read(self.profile / "cache" / "out" / "secret.png"))
        os.symlink(self.profile / "cache" / "images", self.profile / "cache" / "again")
        self.assertIsNone(self.read(self.profile / "cache" / "again" / "real.png"))
        # the root itself behind a link (a Hermes home moved elsewhere) still reads, by either spelling
        moved = self.tmp / "moved"
        _png(moved / "cache" / "images" / "m.png")
        os.symlink(moved, self.tmp / "home-link")
        roots = ob.shot_roots(self.tmp / "home-link", {"BH_HOME": str(self.harness)})
        self.assertEqual(ob.read_step_shot(str(self.tmp / "home-link" / "cache" / "images" / "m.png"), roots)["mime"], "image/png")
        self.assertEqual(ob.read_step_shot(str(moved / "cache" / "images" / "m.png"), roots)["mime"], "image/png")
        # but a capture folder that is itself a link is not a root to read through
        other = self.tmp / "other-profile"
        _png(other / "cache" / "images" / "o.png")
        (self.tmp / "linked").mkdir()
        os.symlink(other / "cache", self.tmp / "linked" / "cache")
        roots = ob.shot_roots(self.tmp / "linked", {"BH_HOME": str(self.harness)})
        self.assertIsNone(ob.read_step_shot(str(self.tmp / "linked" / "cache" / "images" / "o.png"), roots))

    def test_a_root_that_is_the_disk_the_home_or_above_it_is_never_read(self):
        shot = _png(self.tmp / "anywhere" / "a.png")
        self.assertIsNone(ob.read_step_shot(str(shot), (Path(os.path.abspath(os.sep)),)))
        self.assertTrue(ob._shot_root_too_wide(os.path.abspath(os.sep)))
        home = self.tmp / "home" / "me"
        inside = _png(home / "work" / "a.png")
        with mock.patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
            self.assertIsNone(ob.read_step_shot(str(inside), (home,)))
            self.assertIsNone(ob.read_step_shot(str(inside), (home.parent,)))
            self.assertEqual(ob.read_step_shot(str(inside), (home / "work",))["mime"], "image/png")

    def test_lstat_and_fstat_agree_on_this_system(self):
        # read_step_shot compares the check's lstat with the open file's fstat: on a system where the two disagree for
        # one file every screenshot would be refused. No skip: this must hold on every system the bridge runs on.
        path = _png(self.tmp / "agree" / "a.png")
        before = os.lstat(path)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
        fd = os.open(path, flags)
        try:
            after = os.fstat(fd)
        finally:
            os.close(fd)
        self.assertEqual((after.st_dev, after.st_ino), (before.st_dev, before.st_ino))
        self.assertEqual(after.st_nlink, 1)

    def test_a_real_png_under_a_temp_root_is_shown(self):
        # a decodable 2x2 PNG (not only its signature), read through the whole check on every system
        raw = b"".join(b"\x00" + b"\x10\x20\x30" * 2 for _ in range(2))

        def chunk(kind: bytes, data: bytes) -> bytes:
            return len(data).to_bytes(4, "big") + kind + data + (zlib.crc32(kind + data) & 0xFFFFFFFF).to_bytes(4, "big")
        png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", (2).to_bytes(4, "big") * 2 + b"\x08\x02\x00\x00\x00")
               + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
        path = _png(self.profile / "cache" / "images" / "computer_use_real.png", png)
        self.assertEqual(self.read(path), {"mime": "image/png", "data_base64": base64.b64encode(png).decode("ascii")})

    def test_the_file_opened_must_be_the_file_checked(self):
        # a folder swapped for a link (or the file replaced) between the check and the open: another inode is refused
        shot = _png(self.own / "shot.png")
        real = ob._shot_file

        def swap(path, roots):
            found = real(path, roots)
            other = _png(self.tmp / "swap.png")
            os.replace(other, shot)
            return found
        with mock.patch.object(ob, "_shot_file", swap):
            self.assertIsNone(self.read(shot))
        self.assertEqual(self.read(shot)["mime"], "image/png")

    def test_a_hard_link_to_another_file_is_not_read(self):
        outside = _png(self.tmp / "outside" / "secret.png")
        linked = self.profile / "cache" / "images" / "hard.png"
        linked.parent.mkdir(parents=True)
        try:
            os.link(outside, linked)
        except (OSError, NotImplementedError) as e:
            self.skipTest(f"this temp folder cannot hold a hard link: {e}")
        self.assertIsNone(self.read(linked))
        os.unlink(outside)  # the same file with one name again
        self.assertEqual(self.read(linked)["mime"], "image/png")

    def test_the_folder_name_matches_hermes_own_when_hermes_is_here(self):
        # Hermes' own namespace_harness_dirs and hermes_home_key, run in a child interpreter so its modules stay there
        root = ob.DEFAULT_HERMES_ROOT
        if not (root / "hermes_constants.py").is_file() or not (root / "tools" / "browser_harness_dirs.py").is_file():
            self.skipTest("no Hermes Agent checkout on this computer to compare with")
        script = ("import sys; sys.path.insert(0, sys.argv[1])\n"
                  "from hermes_constants import hermes_home_key\n"
                  "from tools.browser_harness_dirs import namespace_harness_dirs\n"
                  "env = {'BH_TMP_DIR': sys.argv[3], 'BH_RUNTIME_DIR': sys.argv[4]}\n"
                  "key = hermes_home_key(sys.argv[2])\n"
                  "namespace_harness_dirs(env, key)\n"
                  "print(key); print(env['BH_TMP_DIR'])\n")
        self.profile.mkdir(parents=True)
        out = subprocess.run([sys.executable, "-I", "-c", script, str(root), str(self.profile), str(self.tmp / "t"),
                              str(self.tmp / "r")], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            self.skipTest(f"Hermes' modules did not import here: {out.stderr.strip()[-200:]}")
        key, folder = out.stdout.strip().splitlines()
        # the bridge asks the same hermes_home_key (it imports it from the checkout on its path); the folder under it
        # must be the one Hermes' own namespace_harness_dirs gives the browser
        with mock.patch.object(ob, "_hermes_home_key", lambda p: key):
            self.assertEqual(str(ob.harness_shot_root(self.profile, {"BH_TMP_DIR": str(self.tmp / "t")})), folder)
        unpatched = self._key.temp_original  # the bridge's own, under this class's stand-in
        self.assertIn("from hermes_constants import hermes_home_key", inspect.getsource(unpatched))
        self.assertIn("return hermes_home_key(profile_dir)", inspect.getsource(unpatched))

    @unittest.skipIf(os.name == "nt", "a named pipe is a POSIX file")
    def test_a_pipe_is_not_opened(self):
        fifo = self.profile / "cache" / "images" / "pipe.png"
        fifo.parent.mkdir(parents=True)
        os.mkfifo(fifo)
        self.assertIsNone(self.read(fifo))


class ShotEvent(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.profile = self.tmp / "profiles" / "kami"
        self.bridge, self.conn, self.sent = _bridge_and_sent(self.profile)
        self._env = {k: os.environ.get(k) for k in ("BH_HOME", "BH_TMP_DIR")}
        os.environ["BH_HOME"] = str(self.tmp / "bh")
        os.environ.pop("BH_TMP_DIR", None)
        self._key = mock.patch.object(ob, "_hermes_home_key", _key)
        self._key.start()

    def tearDown(self) -> None:
        self._key.stop()
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def complete(self, tool: str, image_path, **over) -> None:
        asyncio.run(self.bridge._main_event(self.conn, "tool.complete", {}, {
            "tool_id": "t1", "name": tool, "args": {"code": CODE}, "result": {"output": SECRET},
            **({"image_path": image_path} if image_path is not None else {}), **over}))

    def test_the_default_capture_is_read_at_its_event_before_the_next_overwrites_it(self):
        shot = _png(self.tmp / "bh" / "tmp" / _leaf(self.profile) / "shot.png", PNG + b"first")
        self.complete("browser_exec", str(shot))
        shot.write_bytes(PNG + b"second")  # the next capture
        self.assertEqual([e for e, _ in self.sent], ["tool.end", "tool.shot"])
        self.assertEqual(self.sent[1][1], {"tool_id": "t1", "mime": "image/png",
                                           "data_base64": base64.b64encode(PNG + b"first").decode("ascii")})
        self.assertNotIn(SECRET, json.dumps(self.sent))

    def test_a_computer_capture_too(self):
        shot = _png(self.profile / "cache" / "images" / "computer_use_0f.png")
        self.complete("computer_use", str(shot))
        self.assertEqual([e for e, _ in self.sent], ["tool.end", "tool.shot"])

    def test_no_shot_for_another_tool_an_error_no_path_or_a_path_outside(self):
        inside = str(_png(self.profile / "cache" / "images" / "a.png"))
        self.complete("vision_analyze", inside)       # an image it looked at, not one a step captured
        self.complete("image_generate", inside)
        self.complete("browser_exec", inside, is_error=True)
        self.complete("browser_exec", None)
        self.complete("browser_exec", ["/x.png"])
        self.complete("browser_exec", str(_png(self.tmp / "elsewhere" / "a.png")))
        self.assertEqual({e for e, _ in self.sent}, {"tool.end"})

    def test_a_failure_resolving_the_folders_still_ends_the_step_and_shows_no_shot(self):
        inside = str(_png(self.profile / "cache" / "images" / "a.png"))
        for err in (RuntimeError("Symlink loop from '/x'"), OSError("gone"), ValueError("bad"), ImportError("no hermes")):
            self.sent.clear()

            def boom(_p, err=err):
                raise err
            with mock.patch.object(ob, "_hermes_home_key", boom):
                self.complete("computer_use", inside)
            self.assertEqual(self.sent, [("tool.end", {"tool_id": "t1", "name": "computer_use", "ok": True, "ms": 0})], err)

    def test_the_end_goes_out_before_the_shot_and_the_shot_before_the_turn_ends(self):
        shot = str(_png(self.profile / "cache" / "images" / "a.png"))
        self.complete("computer_use", shot)
        asyncio.run(self.bridge._main_event(self.conn, "message.complete", {}, {"text": "Done.", "status": "complete"}))
        self.assertEqual([e for e, _ in self.sent][:3], ["tool.end", "tool.shot", "message"])

    def test_the_path_comes_from_the_event_only(self):
        # the result and the args may name a file; only `image_path` is read
        inside = str(_png(self.profile / "cache" / "images" / "a.png"))
        asyncio.run(self.bridge._main_event(self.conn, "tool.complete", {}, {
            "tool_id": "t1", "name": "browser_exec", "args": {"code": CODE, "image_path": inside},
            "result": {"screenshot_path": inside, "meta": {"screenshot_path": inside}}}))
        self.assertEqual([e for e, _ in self.sent], ["tool.end"])


class PeerShot(unittest.TestCase):
    def test_a_peers_capture_is_checked_again_here(self):
        good = base64.b64encode(PNG).decode("ascii")
        self.assertEqual(ob.peer_shot({"tool_id": "t1", "mime": "image/gif", "data_base64": good, "extra": SECRET}),
                         {"tool_id": "t1", "mime": "image/png", "data_base64": good})
        self.assertEqual(ob.peer_shot({"tool_id": "t1", "data_base64": good, "session": "th1"})["session"], "th1")
        too_big = base64.b64encode(PNG + b"\x00" * ob.SHOT_MAX).decode("ascii")
        for bad in ({"tool_id": "t1", "data_base64": too_big}, {"tool_id": "t1", "data_base64": base64.b64encode(b"<html>").decode()},
                    {"tool_id": "t1", "data_base64": "not base64!"}, {"tool_id": "", "data_base64": good},
                    {"tool_id": "t1", "data_base64": 7}):
            self.assertIsNone(ob.peer_shot(bad))


if __name__ == "__main__":
    unittest.main()

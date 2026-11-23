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
    base = {"platform": "discord", "status": "failed", "attention": True, "since": "2026-11-23T09:00:00Z",
            "logged": "2026-11-23T09:30:00Z", "reason_kind": "discord_privileged_intents",
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
        self.assertEqual(ob.OMH_READS, {"platforms": ("hermes", "platforms")})
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
                self.assertIsNone(ob.omh_path(which=lambda name: "bin/omh", environ={}))
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
            self.assertIsNone(ob.run_omh_read(str(script), Path(tmp), "platforms", timeout=0.5))
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


if __name__ == "__main__":
    unittest.main()

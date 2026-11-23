"""Add bot › Create and its template gallery (BOUNDARY rule 43): one fixed `hermes -p default profile create <name>`
through the shared Hermes runner, the name checked against Hermes' own rule and the disk first, the outcome read from
the folder Hermes made; and one fixed `omh profile bot-templates --json` read for the gallery. Every test uses a temp
Hermes home and fake runners: no real profile, no real `hermes`, no real `omh`."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import omher_bridge as ob  # noqa: E402


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class Argv(unittest.TestCase):
    def test_the_one_argv_names_the_main_profile_and_the_new_name_as_one_element(self):
        self.assertEqual(ob.profile_create_argv("/h/hermes", "pr-bot"), ["/h/hermes", "-p", "default", "profile", "create", "pr-bot"])

    def test_hermes_own_rule_refuses_every_other_name(self):
        # hermes_cli/profiles.py validate_profile_name: PROFILE_ID_RE, not a reserved name, never `default`
        for name in ("PR-Bot", "a b", "x;y", "../x", "-p", "--clone-all", "_x", "", "a" * 65, "pr.bot", "봇", None, 7,
                     "hermes", "default", "test", "tmp", "root", "sudo"):
            with self.assertRaises(ValueError, msg=name):
                ob.profile_create_argv("/h/hermes", name)
        self.assertEqual(ob.profile_create_argv("h", "a" * 64)[-1], "a" * 64)
        self.assertEqual(ob.profile_create_argv("h", "9to5_bot")[-1], "9to5_bot")

    def test_the_shared_runner_runs_it_like_rule_41s_runs(self):
        seen: dict = {}

        class Proc:
            pid = 4343

            def __init__(self, argv, **kw):
                seen.update(argv=argv, **kw)
                kw["stdout"].write(b"Profile 'pr-bot' created\n")

            def wait(self, timeout=None):
                seen["timeout"] = timeout
                return 0

        env = {"_HERMES_GATEWAY": "1", "HERMES_TUI_GATEWAY_URL": "ws://127.0.0.1:1/x"}
        with mock.patch.object(ob.subprocess, "Popen", Proc), mock.patch.dict(os.environ, env):
            code, out = ob.run_hermes_profile_create("/h/hermes", "pr-bot", Path("/home/h"), 120.0)
        self.assertEqual((code, out), (0, "Profile 'pr-bot' created\n"))
        self.assertEqual(seen["argv"], ["/h/hermes", "-p", "default", "profile", "create", "pr-bot"])
        self.assertIs(seen["stdin"], subprocess.DEVNULL)
        self.assertNotIn("shell", seen)
        self.assertEqual(seen["timeout"], 120.0)
        self.assertEqual(seen["env"]["HERMES_HOME"], "/home/h")
        # a gateway's marker or a TUI gateway address would make Hermes act through a gateway, not here
        self.assertNotIn("_HERMES_GATEWAY", seen["env"])
        self.assertNotIn("HERMES_TUI_GATEWAY_URL", seen["env"])
        if os.name == "nt":
            self.assertEqual(seen["creationflags"] & 0x00000200, 0x00000200)
        else:
            self.assertIs(seen["start_new_session"], True)

    def test_a_bad_name_never_reaches_the_runner(self):
        with mock.patch.object(ob.subprocess, "Popen", side_effect=AssertionError("ran")):
            with self.assertRaises(ValueError):
                ob.run_hermes_profile_create("/h/hermes", "x;rm -rf ~", Path("/h"), 1.0)


class Create(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name) / "hermes"
        write(self.home / "config.yaml", "model: x\n")
        write(self.home / "profiles" / "old-bot" / "config.yaml", "model: x\n")
        self.bridge = ob.Bridge(token="t", hermes_home=self.home)
        self.runs: list[tuple] = []
        self.effect = self.make

        def fake(hermes, name, home, timeout):
            self.runs.append((hermes, name, Path(home), timeout))
            return self.effect(name)

        self._run = mock.patch.object(ob, "run_hermes_profile_create", fake)
        self._path = mock.patch.object(ob, "hermes_path", lambda *a, **k: "/stub/hermes")
        self._run.start()
        self._path.start()

    def tearDown(self) -> None:
        self._path.stop()
        self._run.stop()
        self._tmp.cleanup()

    def make(self, name: str):
        write(self.home / "profiles" / name / "config.yaml", "model: x\n")
        write(self.home / "profiles" / name / "SOUL.md", "You are Hermes.\n")
        return 0, f"\nProfile '{name}' created at {self.home / 'profiles' / name}\n"

    def op(self, **p):
        return asyncio.run(self.bridge.op_bots_create(p))

    def refused(self, code: str, **p) -> str:
        with self.assertRaises(ob.BridgeError) as cm:
            self.op(**p)
        self.assertEqual(cm.exception.code, code, cm.exception.message)
        return cm.exception.message

    def test_create_runs_the_one_argv_and_reads_the_folder_back(self):
        self.assertEqual(self.op(name="pr-bot"), {"outcome": "ok", "bot": "pr-bot"})
        self.assertEqual(self.runs, [("/stub/hermes", "pr-bot", self.home, ob.PROFILE_CREATE_TIMEOUT)])
        self.assertIn("pr-bot", [b["name"] for b in ob.discover_bots(self.home)])

    def test_exit_zero_without_the_folder_is_a_failure_in_hermes_words(self):
        self.effect = lambda name: (0, "  ⚠ Skills could not be seeded.\nnothing else\n")
        got = self.op(name="pr-bot")
        self.assertEqual(got["outcome"], "failed")
        self.assertIn("Skills could not be seeded", got["line"])

    def test_a_refused_create_shows_hermes_error_line(self):
        self.effect = lambda name: (1, "Error: Cannot create profile 'pr-bot': a running gateway still owns it\n")
        self.assertEqual(self.op(name="pr-bot"), {"outcome": "failed",
                                                  "line": "Error: Cannot create profile 'pr-bot': a running gateway still owns it"})

    def test_a_run_past_its_time_says_so(self):
        self.effect = lambda name: (None, "")
        got = self.op(name="pr-bot")
        self.assertEqual(got, {"outcome": "failed", "line": f"Hermes did not finish in {int(ob.PROFILE_CREATE_TIMEOUT)} seconds."})

    def test_a_name_hermes_refuses_or_one_on_disk_runs_nothing(self):
        for bad in ("PR-Bot", "a b", "-p", "x;y", "", None, 7, ["x"], "a" * 65):
            self.refused("bad_request", name=bad)
        for reserved in ("default", "hermes", "root", "sudo", "test", "tmp"):
            self.assertIn("keeps for itself", self.refused("bad_request", name=reserved))
        self.assertIn("already", self.refused("exists", name="old-bot"))
        # a folder Hermes does not list as a profile (no config) and a stray file are refused too, as Hermes refuses
        (self.home / "profiles" / "shell").mkdir(parents=True)
        write(self.home / "profiles" / "stray", "x")
        self.refused("exists", name="shell")
        self.refused("exists", name="stray")
        if os.name != "nt":
            os.symlink(self.home / "profiles" / "old-bot", self.home / "profiles" / "linked")
            self.refused("exists", name="linked")
        self.assertEqual(self.runs, [])

    def test_success_is_a_real_folder_with_its_config(self):
        profiles = self.home / "profiles"
        self.assertTrue(ob.new_profile_made(self.home, "old-bot"))
        self.assertFalse(ob.new_profile_made(self.home, "nobody"))
        (profiles / "shell").mkdir()
        self.assertFalse(ob.new_profile_made(self.home, "shell"))         # no config.yaml: not a bot omher lists
        write(profiles / "stray", "x")
        self.assertFalse(ob.new_profile_made(self.home, "stray"))
        if os.name != "nt":                                                # a link to another bot is not the new one
            os.symlink(profiles / "old-bot", profiles / "linked")
            self.assertFalse(ob.new_profile_made(self.home, "linked"))

    def test_without_hermes_nothing_runs(self):
        with mock.patch.object(ob, "hermes_path", lambda *a, **k: None):
            self.assertEqual(self.op(name="pr-bot"), {"outcome": "failed", "line": "Hermes is not on this computer."})
        self.assertEqual(self.runs, [])

    def test_one_create_at_a_time(self):
        self.bridge._creating = True
        self.refused("busy", name="pr-bot")
        self.assertEqual(self.runs, [])


class Templates(unittest.TestCase):
    CATALOG = {
        "schema_version": "bot_template_catalog/v1",
        "templates": [
            {"id": "pr-review", "title": "PR reviewer", "summary": "Reviews pull requests.",
             "skills": ["code-review", "github-event-ops", "Bad Skill"],
             "schedules": [{"job_name": "pr-review-review-queue", "title": "Weekday review queue", "prompt": "secret"}],
             "webhooks": [{"title": "Pull request events"}], "apps": [{"name": "sentry", "need": "optional"}, {"name": "-x"}],
             "persona_seed": "## Bot template: PR reviewer\n\nYou review pull requests.",
             "apply_message": "/omh-bot-template Apply the bot template `pr-review` to this bot."},
            {"id": "../evil", "title": "x"},
            "not a row",
        ],
    }

    def run_omh(self, code=0, stdout=b"", exc=None):
        seen: dict = {}

        def fake(argv, **kw):
            seen.update(argv=argv, **kw)
            if exc:
                raise exc
            return subprocess.CompletedProcess(argv, code, stdout, b"")

        with mock.patch.object(ob.subprocess, "run", fake):
            got = ob.read_bot_templates("/u/bin/omh", 5.0)
        return got, seen

    def test_one_fixed_read_and_only_what_the_gallery_shows(self):
        got, seen = self.run_omh(stdout=json.dumps(self.CATALOG).encode())
        self.assertEqual(seen["argv"], ["/u/bin/omh", "profile", "bot-templates", "--json"])
        self.assertIs(seen["stdin"], subprocess.DEVNULL)
        self.assertNotIn("shell", seen)
        self.assertEqual(seen["timeout"], 5.0)
        self.assertEqual(got["omh"], "ok")
        self.assertEqual(got["templates"], [{
            "id": "pr-review", "title": "PR reviewer", "summary": "Reviews pull requests.",
            "skills": ["code-review", "github-event-ops"],
            "schedules": [{"name": "pr-review-review-queue", "title": "Weekday review queue"}],
            "webhooks": ["Pull request events"], "apps": [{"name": "sentry", "need": "optional"}],
        }])
        # no prompt, persona or message text from omh reaches the page
        self.assertNotIn("secret", json.dumps(got))
        self.assertNotIn("apply_message", json.dumps(got))

    def test_missing_old_and_failed_omh(self):
        self.assertEqual(ob.read_bot_templates(None), {"omh": "missing", "templates": []})
        # an omh from before bot templates: argparse refuses the command (exit 2)
        self.assertEqual(self.run_omh(code=2)[0], {"omh": "old", "templates": []})
        self.assertEqual(self.run_omh(stdout=b"not json")[0]["omh"], "old")
        self.assertEqual(self.run_omh(stdout=json.dumps({"schema_version": "x/v9"}).encode())[0]["omh"], "old")
        got = self.run_omh(exc=subprocess.TimeoutExpired("omh", 5.0))[0]
        self.assertEqual((got["omh"], got["templates"]), ("failed", []))
        self.assertIn("did not answer", got["line"])
        self.assertEqual(self.run_omh(exc=FileNotFoundError(2, "No such file"))[0]["omh"], "failed")

    def test_omh_is_found_on_path_or_where_its_installer_puts_it(self):
        self.assertEqual(ob.omh_path(which=lambda n: "/opt/omh"), "/opt/omh")
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertIsNone(ob.omh_path(which=lambda n: None, environ={"HOME": tmp, "USERPROFILE": tmp}))
            if os.name == "nt":
                launcher = write(home / ".local" / "bin" / "omh.cmd", "@echo off\n")
            else:
                launcher = write(home / ".local" / "bin" / "omh", "#!/bin/sh\n")
                launcher.chmod(0o755)
            self.assertEqual(ob.omh_path(which=lambda n: None, environ={"HOME": tmp, "USERPROFILE": tmp}), str(launcher))

    def test_the_op_reads_through_omh_path(self):
        bridge = ob.Bridge(token="t", hermes_home=Path(tempfile.gettempdir()))
        with mock.patch.object(ob, "omh_path", lambda *a, **k: None):
            self.assertEqual(asyncio.run(bridge.op_bots_templates({})), {"omh": "missing", "templates": []})


if __name__ == "__main__":
    unittest.main()

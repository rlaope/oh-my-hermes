"""Add bot › Create and its template gallery (BOUNDARY rule 44): one fixed `hermes -p default profile create <name>
--no-alias` through the shared Hermes runner, the name checked against Hermes' own rule and the disk first, the outcome
read from the folder Hermes made; and one more entry in rule 43's `OMH_READS` table for the gallery. Every test uses a temp
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
        self.assertEqual(ob.profile_create_argv("/h/hermes", "pr-bot"), ["/h/hermes", "-p", "default", "profile", "create", "pr-bot", "--no-alias"])

    def test_hermes_own_rule_refuses_every_other_name(self):
        # hermes_cli/profiles.py validate_profile_name: PROFILE_ID_RE, not a reserved name, never `default`
        for name in ("PR-Bot", "a b", "x;y", "../x", "-p", "--clone-all", "_x", "", "a" * 65, "pr.bot", "봇", None, 7,
                     "hermes", "default", "test", "tmp", "root", "sudo", "omh-tui"):
            with self.assertRaises(ValueError, msg=name):
                ob.profile_create_argv("/h/hermes", name)
        self.assertEqual(ob.profile_create_argv("h", "a" * 64)[-2], "a" * 64)
        self.assertEqual(ob.profile_create_argv("h", "9to5_bot")[-2], "9to5_bot")

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
        self.assertEqual(seen["argv"], ["/h/hermes", "-p", "default", "profile", "create", "pr-bot", "--no-alias"])
        self.assertIs(seen["stdin"], subprocess.DEVNULL)
        self.assertNotIn("shell", seen)
        self.assertEqual(seen["timeout"], 120.0)
        # str(Path(...)): Windows writes the separator as `\\` (the same fix #3152 made in test_apps)
        self.assertEqual(seen["env"]["HERMES_HOME"], str(Path("/home/h")))
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
        self.assertEqual(self.op(name="pr-bot"), {"outcome": "ok", "bot": "pr-bot", "notes": [], "incomplete": False})
        self.assertEqual(self.runs, [("/stub/hermes", "pr-bot", self.home, ob.PROFILE_CREATE_TIMEOUT)])
        self.assertIn("pr-bot", [b["name"] for b in ob.discover_bots(self.home)])

    def test_hermes_warnings_on_a_finished_create_are_shown_and_a_failed_setup_holds_the_template(self):
        def warned(name, lines):
            self.make(name)
            return 0, f"\nProfile '{name}' created at /h/{name}\n" + "".join(f"\u26a0 {ln}\n" for ln in lines)
        # an informational note: shown, the template goes ahead
        self.effect = lambda name: warned(name, ["subscription logins not carried over (nous): the profile uses the default profile's",
                                                 "A newer Hermes is available: run `hermes update`"])
        got = self.op(name="note-bot")
        self.assertEqual((got["outcome"], got["incomplete"]), ("ok", False))
        self.assertEqual(got["notes"], ["\u26a0 subscription logins not carried over (nous): the profile uses the default profile's"])
        # skills not seeded, keys not copied, model not set: shown, and the page holds the template
        for line in ("Skills could not be seeded. Run `x update` to retry.", "launch credentials: permission denied",
                     "bundled skills: timed out", "model inherit: no model"):
            with self.subTest(line=line):
                name = "w" + str(abs(hash(line)) % 10000)
                self.effect = lambda n, line=line: warned(n, [line])
                got = self.op(name=name)
                self.assertEqual((got["outcome"], got["incomplete"]), ("ok", True))
                self.assertEqual(got["notes"], [f"\u26a0 {line}"])

    def test_a_create_is_confirmed_only_by_hermes_own_finish(self):
        # exit 0 and the folder, but no `Profile '<name>' created at` line: Hermes did not say it finished
        def quiet(name):
            write(self.home / "profiles" / name / "config.yaml", "model: x\n")
            return 0, ""
        self.effect = quiet
        got = self.op(name="quiet-bot")
        self.assertEqual(got["outcome"], "unconfirmed")
        self.assertNotIn("bot", got)
        self.assertIn("could not confirm that Hermes finished making quiet-bot", got["line"])
        self.assertIn("It may have left profiles/quiet-bot.", got["line"])
        self.assertIn("`hermes profile list`", got["line"])

    def test_a_folder_hermes_left_half_set_up_is_unconfirmed_and_sends_nothing(self):
        # stopped or failed after the folder was published (Hermes copies keys, model and skills after that)
        for code, said in ((None, ""), (1, "Error: skill seeding failed\n")):
            with self.subTest(code=code):
                name = f"half{1 if code else 0}"

                def half(n, code=code, said=said):
                    write(self.home / "profiles" / n / "config.yaml", "model: x\n")
                    return code, said
                self.effect = half
                got = self.op(name=name)
                self.assertEqual(got["outcome"], "unconfirmed")
                self.assertNotIn("bot", got)
                self.assertIn(f"It may have left profiles/{name}.", got["line"])

    def test_a_staging_leftover_is_named(self):
        def cut(name):
            (self.home / "profiles" / f".{name}.staging-4242").mkdir(parents=True)
            return 1, "Error: interrupted\n"
        self.effect = cut
        got = self.op(name="cut-bot")
        self.assertEqual(got["outcome"], "unconfirmed")
        self.assertIn("It may have left profiles/.cut-bot.staging-4242.", got["line"])

    def test_a_stopped_run_with_nothing_on_disk_says_the_gateway_may_still_be_making_it(self):
        self.effect = lambda name: (None, "")
        got = self.op(name="pr-bot")
        self.assertEqual(got["outcome"], "unconfirmed")
        self.assertIn("It may still be making pr-bot through the running gateway.", got["line"])
        self.assertIn("`hermes profile list`", got["line"])
        # Hermes' own 300 s for a create through the gateway (profile_provision_gateway.py CREATE_RPC_TIMEOUT), plus 30
        self.assertEqual(ob.PROFILE_CREATE_TIMEOUT, 330.0)

    def test_exit_zero_without_the_folder_is_a_failure_in_hermes_words(self):
        self.effect = lambda name: (0, "  ⚠ Skills could not be seeded.\nnothing else\n")
        got = self.op(name="pr-bot")
        self.assertEqual(got["outcome"], "failed")
        self.assertIn("Skills could not be seeded", got["line"])

    def test_a_refused_create_shows_hermes_error_line(self):
        self.effect = lambda name: (1, "Error: Cannot create profile 'pr-bot': a running gateway still owns it\n")
        self.assertEqual(self.op(name="pr-bot"), {"outcome": "failed",
                                                  "line": "Error: Cannot create profile 'pr-bot': a running gateway still owns it"})

    def test_a_name_hermes_refuses_or_one_on_disk_runs_nothing(self):
        for bad in ("PR-Bot", "a b", "-p", "x;y", "", None, 7, ["x"], "a" * 65):
            self.refused("bad_request", name=bad)
        for reserved in ("default", "hermes", "root", "sudo", "test", "tmp"):
            self.assertIn("keeps for itself", self.refused("bad_request", name=reserved))
        self.assertIn("oh-my-hermes' own TUI profile", self.refused("bad_request", name="omh-tui"))
        self.assertEqual(self.refused("exists", name="old-bot"), "A folder named old-bot is already under Hermes' profiles.")
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
            {"id": "pr-review", "title": "PR\x1b[31m reviewer", "summary": "Reviews pull requests.",
             "skills": ["code-review", "github-event-ops", "Bad Skill", "code-review", "code-review"],
             "schedules": [{"job_name": "pr-review-review-queue", "title": "Weekday review queue", "prompt": "secret"},
                           {"job_name": "../x", "title": "bad"}],
             "webhooks": [{"title": "Pull request events"}], "apps": [{"name": "sentry", "need": "optional"}, {"name": "-x"}],
             "persona_seed": "## Bot template: PR reviewer\n\nYou review pull requests.",
             "apply_message": "/omh-bot-template Apply the bot template `pr-review` to this bot."},
            {"id": "../evil", "title": "x"},
            "not a row",
        ],
    }

    def test_one_more_fixed_entry_in_rule_43s_table(self):
        home = Path("/h") / ".hermes"
        self.assertEqual(ob.OMH_READS["bot_templates"], ("profile", "bot-templates", "--json"))
        self.assertEqual(ob.omh_read_argv("/x/omh", home, "bot_templates"),
                         ["/x/omh", "--hermes-home", str(home), "profile", "bot-templates", "--json"])

    def test_only_what_the_gallery_shows_is_kept(self):
        rows = ob.bot_template_rows(json.dumps(self.CATALOG))
        self.assertEqual(rows, [{
            "id": "pr-review", "title": "PR reviewer", "summary": "Reviews pull requests.",
            "skills": ["code-review", "github-event-ops"],
            "schedules": [{"name": "pr-review-review-queue", "title": "Weekday review queue"}],
            "webhooks": ["Pull request events"], "apps": [{"name": "sentry", "need": "optional"}],
        }])
        # no prompt, persona or message text from omh reaches the page
        self.assertNotIn("secret", json.dumps(rows))
        self.assertNotIn("apply_message", json.dumps(rows))

    def test_anything_but_the_catalog_is_no_answer(self):
        for out in (None, "", "not json", json.dumps({"schema_version": "x/v9", "templates": []}),
                    json.dumps({"schema_version": "bot_template_catalog/v1"}), "x" * (ob.OMH_READ_OUTPUT_MAX + 1)):
            self.assertIsNone(ob.bot_template_rows(out), str(out)[:40])

    def bridge(self):
        return ob.Bridge(token="t", hermes_home=Path(tempfile.gettempdir()))

    def test_the_op_reads_through_rule_43s_runner(self):
        seen = []

        def read(omh, home, key, timeout=None):
            seen.append((omh, key))
            return json.dumps(self.CATALOG)

        with mock.patch.object(ob, "omh_path", lambda *a, **k: "/u/bin/omh"), mock.patch.object(ob, "run_omh_read", read):
            got = asyncio.run(self.bridge().op_bots_templates({}))
        self.assertEqual(seen, [("/u/bin/omh", "bot_templates")])
        self.assertEqual((got["omh"], [t["id"] for t in got["templates"]]), ("ok", ["pr-review"]))

    def test_missing_and_unavailable_omh(self):
        with mock.patch.object(ob, "omh_path", lambda *a, **k: None):
            self.assertEqual(asyncio.run(self.bridge().op_bots_templates({})), {"omh": "missing", "templates": []})
        # an omh from before bot templates exits non-zero (argparse), which run_omh_read answers as None
        with mock.patch.object(ob, "omh_path", lambda *a, **k: "/u/bin/omh"), \
                mock.patch.object(ob, "run_omh_read", lambda *a, **k: None):
            self.assertEqual(asyncio.run(self.bridge().op_bots_templates({})), {"omh": "unavailable", "templates": []})


if __name__ == "__main__":
    unittest.main()

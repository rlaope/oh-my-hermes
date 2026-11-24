"""`omh apply --profile <name>`: OMH's skills in one bot profile made after install, and nowhere else.

A Hermes profile created after `omh setup` has no OMH skills until the next
`omh update`, which also updates OMH and touches every home. The narrow
command runs the update's own per-profile pass (`_sync_hermes_profile`) for
the one profile it names, refuses every name `omh update` would not reach,
and leaves the main home and every other profile byte-identical.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from _cli_harness import run_cli
from omh.commands import setup as _setup_module
from omh.install.skill_registration import hermes_profile_dirs, named_hermes_profile


def _tree(root: Path) -> dict[str, bytes]:
    """Every file under `root` by its relative POSIX path, for byte-identity checks."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


class ApplyProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # A space in every path: the command and Hermes both read these homes through `Path`.
        self.root = Path(self._tmp.name) / "my homes"
        self.omh_home = self.root / ".omh"
        self.hermes_home = self.root / "Hermes Home"
        patcher = mock.patch.object(
            _setup_module,
            "_command_package_self_update_plan",
            return_value={"should_update": False, "reason": "test fixture"},
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _base(self) -> list[str]:
        return ["--omh-home", str(self.omh_home), "--hermes-home", str(self.hermes_home)]

    def _setup(self) -> None:
        status, _stdout, stderr = run_cli(self._base() + ["setup", "--json"], output_json=False)
        self.assertEqual((status, stderr), (0, ""))

    def _profile(self, name: str) -> Path:
        profile = self.hermes_home / "profiles" / name
        profile.mkdir(parents=True, exist_ok=True)
        # What `hermes profile create` leaves before OMH ever sees it: a config and a persona.
        (profile / "config.yaml").write_text("model:\n  default: demo-model\n", encoding="utf-8")
        (profile / "SOUL.md").write_text("Profile identity\n", encoding="utf-8")
        return profile

    def _apply(self, *argv: str) -> tuple[int, dict[str, object], str]:
        status, stdout, stderr = run_cli(self._base() + ["apply", *argv, "--json"], output_json=False)
        return status, json.loads(stdout), stderr

    def _skills_dir(self) -> str:
        return (self.omh_home / "skills").resolve().as_posix()

    def test_registers_one_profile_and_leaves_every_other_home_byte_identical(self) -> None:
        self._setup()
        bot = self._profile("demo-bot")
        other = self._profile("other-bot")
        before_other = _tree(other)
        before_primary = (self.hermes_home / "config.yaml").read_bytes()

        status, payload, stderr = self._apply("--profile", "demo-bot")

        self.assertEqual((status, stderr), (0, ""))
        self.assertEqual(payload["profile"], "demo-bot")
        self.assertEqual(payload["status"], "bootstrapped")
        self.assertEqual(payload["registration"], "added")
        self.assertFalse(payload["dry_run"])
        self.assertEqual(Path(str(payload["hermes_home"])).resolve(), bot.resolve())
        self.assertTrue((bot / "plugins" / "omh").is_dir())
        self.assertIn(self._skills_dir(), (bot / "config.yaml").read_text(encoding="utf-8"))
        # The persona Hermes wrote is the profile's, not OMH's.
        self.assertEqual((bot / "SOUL.md").read_text(encoding="utf-8"), "Profile identity\n")
        self.assertEqual(_tree(other), before_other)
        self.assertEqual((self.hermes_home / "config.yaml").read_bytes(), before_primary)

    def test_a_second_run_changes_nothing(self) -> None:
        self._setup()
        bot = self._profile("demo-bot")
        first, _payload, _stderr = self._apply("--profile", "demo-bot")
        self.assertEqual(first, 0)
        after_first = _tree(bot)

        status, payload, stderr = self._apply("--profile", "demo-bot")

        self.assertEqual((status, stderr), (0, ""))
        self.assertEqual((payload["status"], payload["registration"]), ("refreshed", "unchanged"))
        self.assertEqual(_tree(bot), after_first)

    def test_the_same_pass_omh_update_runs_for_each_profile(self) -> None:
        self._setup()
        self._profile("demo-bot")
        calls: list[str] = []
        real = _setup_module._sync_hermes_profile

        def spy(args, primary, name, profile_dir):
            calls.append(name)
            return real(args, primary, name, profile_dir)

        with mock.patch.object(_setup_module, "_sync_hermes_profile", side_effect=spy):
            status, _payload, _stderr = self._apply("--profile", "demo-bot")
        self.assertEqual((status, calls), (0, ["demo-bot"]))

    def test_dry_run_writes_nothing(self) -> None:
        self._setup()
        bot = self._profile("demo-bot")
        before = _tree(bot)

        status, payload, stderr = self._apply("--profile", "demo-bot", "--dry-run")

        self.assertEqual((status, stderr), (0, ""))
        self.assertTrue(payload["dry_run"])
        self.assertIsNone(payload["gateway_restart_hint"])
        self.assertEqual(_tree(bot), before)
        self.assertFalse((bot / "plugins").exists())

    def test_refuses_names_omh_update_does_not_reach(self) -> None:
        self._setup()
        self._profile("omh-tui")
        self._profile("root")
        self._profile("gone-bot")
        (self.hermes_home / "profiles" / ".deleted").mkdir()
        (self.hermes_home / "profiles" / ".deleted" / "gone-bot").write_text("", encoding="utf-8")
        (self.hermes_home / "profiles" / "shell-bot").mkdir()
        before = _tree(self.hermes_home)
        cases = {
            "no-such-bot": "no Hermes profile named `no-such-bot`",
            "Demo-Bot": "is not a Hermes profile name",
            "-bot": "is not a Hermes profile name",
            "a" * 65: "is not a Hermes profile name",
            "../demo-bot": "is not a Hermes profile name",
            "default": "is the main Hermes home",
            "root": "a name Hermes reserves",
            "omh-tui": "oh-my-hermes' own TUI profile",
            "gone-bot": "is deleted",
            "shell-bot": "is not a Hermes profile: it holds none of",
        }
        for name, reason in cases.items():
            with self.subTest(name=name):
                status, payload, stderr = self._apply(f"--profile={name}")
                self.assertEqual((status, stderr), (2, ""))
                self.assertEqual((payload["profile"], payload["status"]), (name, "refused"))
                self.assertIn(reason, str(payload["reason"]))
        self.assertEqual(_tree(self.hermes_home), before)

    def test_human_refusal_goes_to_stderr(self) -> None:
        self._setup()
        status, stdout, stderr = run_cli(self._base() + ["apply", "--profile", "no-such-bot"], output_json=False)
        self.assertEqual((status, stdout), (2, ""))
        self.assertIn("omh: no Hermes profile named `no-such-bot`", stderr)

    def test_refuses_before_omh_skills_are_installed(self) -> None:
        bot = self._profile("demo-bot")
        before = _tree(bot)

        status, payload, _stderr = self._apply("--profile", "demo-bot")

        self.assertEqual((status, payload["status"]), (2, "refused"))
        self.assertIn("run `omh setup` first", str(payload["reason"]))
        self.assertEqual(_tree(bot), before)

    def test_a_deliberately_unregistered_profile_stays_unregistered(self) -> None:
        self._setup()
        bot = self._profile("demo-bot")
        (bot / "plugins" / "omh").mkdir(parents=True)
        before = (bot / "config.yaml").read_bytes()

        status, payload, _stderr = self._apply("--profile", "demo-bot")

        self.assertEqual((status, payload["status"]), (1, "unregistered_kept"))
        self.assertEqual((bot / "config.yaml").read_bytes(), before)

    def test_human_output_says_what_hermes_reads_without_a_restart(self) -> None:
        self._setup()
        self._profile("demo-bot")
        status, stdout, stderr = run_cli(self._base() + ["apply", "--profile", "demo-bot"], output_json=False)
        self.assertEqual((status, stderr), (0, ""))
        self.assertIn("Bot profile demo-bot: set up", stdout)
        self.assertIn("Hermes reads the new skills on its next skill lookup, without a restart", stdout)


class NamedHermesProfileTests(unittest.TestCase):
    def test_resolves_exactly_the_profiles_omh_update_lists(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "Hermes Home"
            for name in ("demo-bot", "omh-tui"):
                profile = home / "profiles" / name
                profile.mkdir(parents=True)
                (profile / "config.yaml").write_text("{}\n", encoding="utf-8")
            listed = dict(hermes_profile_dirs(home))
            self.assertEqual(sorted(listed), ["demo-bot"])
            self.assertEqual(named_hermes_profile(home, "demo-bot"), (listed["demo-bot"], ""))
            profile_dir, reason = named_hermes_profile(home, "omh-tui")
            self.assertIsNone(profile_dir)
            self.assertIn("own TUI profile", reason)
            # The refusal names the folder through `Path`, whatever the separator.
            _none, missing = named_hermes_profile(home, "no-such-bot")
            self.assertIn(str(home / "profiles"), missing)


if __name__ == "__main__":
    unittest.main()

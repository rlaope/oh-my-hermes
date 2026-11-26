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

        def spy(args, primary, name, profile_dir, **kwargs):
            calls.append(name)
            return real(args, primary, name, profile_dir, **kwargs)

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

    def _break_config(self, bot: Path) -> None:
        # A shape OMH's config editor refuses: the registration would raise.
        (bot / "config.yaml").write_text("skills:\n  external_dirs: not-a-list\n", encoding="utf-8")

    def _repair_config(self, bot: Path) -> None:
        (bot / "config.yaml").write_text("model:\n  default: demo-model\n", encoding="utf-8")

    def _update(self) -> dict[str, object]:
        status, stdout, _stderr = run_cli(self._base() + ["update", "--json", "--no-restart-gateway"], output_json=False)
        payload = json.loads(stdout)
        return {"exit": status, **{row["profile"]: row for row in payload["hermes_profiles"]}}

    def test_a_config_omh_cannot_edit_fails_before_anything_is_written_and_a_repair_registers(self) -> None:
        self._setup()
        bot = self._profile("demo-bot")
        self._break_config(bot)
        before = _tree(bot)

        status, payload, _stderr = self._apply("--profile", "demo-bot")

        self.assertEqual((status, payload["status"]), (1, "failed"))
        self.assertIn("external_dirs", str(payload["error"]))
        self.assertEqual(_tree(bot), before)
        # a rerun before the repair still fails; it is never read as the opt-out
        status, payload, _stderr = self._apply("--profile", "demo-bot")
        self.assertEqual((status, payload["status"]), (1, "failed"))
        self._repair_config(bot)
        status, payload, _stderr = self._apply("--profile", "demo-bot")
        self.assertEqual((status, payload["status"]), (0, "bootstrapped"))
        self.assertIn(self._skills_dir(), (bot / "config.yaml").read_text(encoding="utf-8"))

    def test_omh_update_fails_the_same_profile_without_writing_it_and_registers_it_after_the_repair(self) -> None:
        self._setup()
        bot = self._profile("demo-bot")
        self._break_config(bot)
        before = _tree(bot)

        rows = self._update()

        self.assertEqual(rows["demo-bot"]["status"], "failed")
        self.assertEqual(_tree(bot), before)
        self._repair_config(bot)
        self.assertEqual(self._update()["demo-bot"]["status"], "bootstrapped")
        self.assertIn(self._skills_dir(), (bot / "config.yaml").read_text(encoding="utf-8"))

    def test_a_write_that_fails_after_the_bundle_went_in_takes_the_bundle_back(self) -> None:
        self._setup()
        bot = self._profile("demo-bot")
        real = _setup_module._apply_result

        def fail_for_real(args, **kwargs):
            if not args.dry_run:
                raise _setup_module.OmhError("config.yaml changed under the write")
            return real(args, **kwargs)

        with mock.patch.object(_setup_module, "_apply_result", side_effect=fail_for_real):
            status, payload, _stderr = self._apply("--profile", "demo-bot")
        self.assertEqual((status, payload["status"], payload["plugin_bundle_rolled_back"]), (1, "failed", True))
        self.assertFalse((bot / "plugins" / "omh").exists())
        status, payload, _stderr = self._apply("--profile", "demo-bot")
        self.assertEqual((status, payload["status"]), (0, "bootstrapped"))

    def test_a_deliberate_opt_out_stays_unregistered_through_both_commands(self) -> None:
        self._setup()
        bot = self._profile("demo-bot")
        (bot / "plugins" / "omh").mkdir(parents=True)
        before = (bot / "config.yaml").read_bytes()
        self.assertEqual(self._apply("--profile", "demo-bot")[1]["status"], "unregistered_kept")
        self.assertEqual(self._update()["demo-bot"]["status"], "unregistered_kept")
        self.assertEqual((bot / "config.yaml").read_bytes(), before)

    def test_json_shapes(self) -> None:
        """The keys each outcome prints with --json, as docs/INSTALLATION.md lists them."""
        self._setup()
        bot = self._profile("demo-bot")
        row = {"profile", "status", "hermes_home", "dry_run", "gateway_restart_hint"}
        registered = row | {"registration", "registered_dir", "retired_external_dirs", "display_release"}
        _s, dry, _e = self._apply("--profile", "demo-bot", "--dry-run")
        self.assertLessEqual(registered, set(dry))
        self.assertEqual((dry["status"], dry["dry_run"]), ("bootstrapped", True))
        _s, done, _e = self._apply("--profile", "demo-bot")
        self.assertLessEqual(registered, set(done))
        _s, refused, _e = self._apply("--profile", "no-such-bot")
        self.assertEqual(set(refused), {"profile", "status", "reason", "dry_run"})
        self._profile("broken-bot")
        self._break_config(self.hermes_home / "profiles" / "broken-bot")
        _s, failed, _e = self._apply("--profile", "broken-bot")
        self.assertEqual(failed["status"], "failed")
        self.assertLessEqual(row | {"error"}, set(failed))
        (self.hermes_home / "profiles" / "kept-bot" / "plugins" / "omh").mkdir(parents=True)
        (self.hermes_home / "profiles" / "kept-bot" / "SOUL.md").write_text("x\n", encoding="utf-8")
        _s, kept, _e = self._apply("--profile", "kept-bot")
        self.assertEqual(kept["status"], "unregistered_kept")
        self.assertLessEqual(row | {"registration", "display_release"}, set(kept))
        self.assertTrue(bot.is_dir())

    def test_a_profile_gone_before_the_write_is_not_recreated(self) -> None:
        self._setup()
        bot = self._profile("demo-bot")
        real = _setup_module._profile_clone

        def vanish(args, primary, profile_dir):
            for path in sorted(profile_dir.rglob("*"), reverse=True):
                path.unlink() if path.is_file() else path.rmdir()
            return real(args, primary, profile_dir)

        with mock.patch.object(_setup_module, "_profile_clone", side_effect=vanish):
            status, payload, _stderr = self._apply("--profile", "demo-bot")
        self.assertEqual((status, payload["status"]), (2, "refused"))
        self.assertIn("is no longer a Hermes profile", str(payload["reason"]))
        self.assertEqual(list(bot.rglob("*")), [])

    def test_a_profile_swapped_for_a_link_before_the_write_is_refused(self) -> None:
        self._setup()
        bot = self._profile("demo-bot")
        real = _setup_module._profile_clone
        moved = self.hermes_home / "profiles" / "real-bot"

        def swap(args, primary, profile_dir):
            profile_dir.rename(moved)
            try:
                profile_dir.symlink_to(moved, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            return real(args, primary, profile_dir)

        with mock.patch.object(_setup_module, "_profile_clone", side_effect=swap):
            status, payload, _stderr = self._apply("--profile", "demo-bot")
        self.assertEqual((status, payload["status"]), (2, "refused"))
        self.assertIn("is a link to", str(payload["reason"]))
        self.assertFalse((moved / "plugins").exists())
        self.assertTrue(bot.is_symlink())

    @unittest.skipUnless(hasattr(Path, "symlink_to"), "needs symlinks")
    def test_refuses_a_profile_that_is_a_link(self) -> None:
        self._setup()
        target = self._profile("demo-bot")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "SOUL.md").write_text("Profile identity\n", encoding="utf-8")
        try:
            (self.hermes_home / "profiles" / "link-bot").symlink_to(target, target_is_directory=True)
            (self.hermes_home / "profiles" / "out-bot").symlink_to(outside, target_is_directory=True)
        except OSError as exc:  # Windows without the symlink privilege
            self.skipTest(f"symlinks unavailable: {exc}")
        before = (_tree(target), _tree(outside))
        for name in ("link-bot", "out-bot"):
            with self.subTest(name=name):
                status, payload, _stderr = self._apply("--profile", name)
                self.assertEqual((status, payload["status"]), (2, "refused"))
                self.assertIn("is a link to", str(payload["reason"]))
        self.assertEqual((_tree(target), _tree(outside)), before)

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

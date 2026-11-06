"""`omh update` names the commit it moved between, and `--channel main` names preview.

The staged transaction's own records (`identity_change` in its result) are
covered beside the rest of the transaction in `test_staged_self_update.py`.
These cases cover what the person sees: the human line in every language
table, the `--json` result, the exit code, the channel alias, and the refusal
a package-manager install gives instead of recording a main build it cannot
install.
"""

from __future__ import annotations

from argparse import Namespace
import contextlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from omh.commands import setup as setup_commands
from omh.commands.language import LANGUAGE_CODES, MESSAGES
from omh.commands.main import build_parser
from omh.core.errors import OmhError

OLD = "1" * 40
NEW = "2" * 40


def _identity(version: str, commit: str = "", ref: str = "main") -> dict[str, str]:
    return {"version": version, "ref": ref if commit else "", "commit_sha": commit}


def _change(status: str, previous: dict[str, str], current: dict[str, str]) -> dict[str, object]:
    return {
        "schema_version": "update_identity_change/v1",
        "status": status,
        "previous": previous,
        "current": current,
        "version_changed": previous["version"] != current["version"],
    }


def _ok_result(change: dict[str, object]) -> dict[str, object]:
    return {
        "ok": True,
        "phase": "cleanup",
        "activation": {"status": "ok"},
        "rollback": {"performed": False},
        "cleanup": {"collected": []},
        "identity_change": change,
    }


class IdentityChangeLineTests(unittest.TestCase):
    def test_each_status_reads_as_what_moved(self) -> None:
        cases = (
            (
                _change("changed", _identity("4.0.6", OLD), _identity("4.0.6", NEW)),
                f"oh-my-hermes 4.0.6 main@{OLD[:8]} → main@{NEW[:8]}",
            ),
            (
                _change("changed", _identity("4.0.5", OLD), _identity("4.0.6", NEW)),
                f"oh-my-hermes 4.0.5 main@{OLD[:8]} → 4.0.6 main@{NEW[:8]}",
            ),
            (
                _change("unchanged", _identity("4.0.6", NEW), _identity("4.0.6", NEW)),
                f"oh-my-hermes 4.0.6: already at main@{NEW[:8]}",
            ),
            (
                _change("previous_unrecorded", _identity("4.0.5"), _identity("4.0.5", NEW)),
                f"oh-my-hermes 4.0.5 → 4.0.5 main@{NEW[:8]}",
            ),
            (
                _change("previous_unrecorded", _identity(""), _identity("4.0.6", NEW)),
                f"oh-my-hermes not recorded → 4.0.6 main@{NEW[:8]}",
            ),
            (
                _change("version_changed", _identity("4.0.5"), _identity("4.0.6")),
                "oh-my-hermes 4.0.5 → 4.0.6",
            ),
            (
                _change("unrecorded", _identity("4.0.6"), _identity("4.0.6")),
                "oh-my-hermes 4.0.6 (commit not recorded)",
            ),
        )
        for change, expected in cases:
            with self.subTest(status=change["status"], expected=expected):
                self.assertEqual(setup_commands._identity_change_line(change, language="en"), expected)

    def test_a_commit_without_a_ref_is_named_by_its_commit_alone(self) -> None:
        change = _change("changed", _identity("4.0.6", OLD, ref=""), _identity("4.0.6", NEW, ref=""))
        self.assertEqual(
            setup_commands._identity_change_line(change, language="en"),
            f"oh-my-hermes 4.0.6 {OLD[:8]} → {NEW[:8]}",
        )

    def test_every_language_table_carries_the_identity_rows(self) -> None:
        unchanged = _change("unchanged", _identity("4.0.6", NEW), _identity("4.0.6", NEW))
        unrecorded = _change("unrecorded", _identity("4.0.6"), _identity("4.0.6"))
        for language in LANGUAGE_CODES:
            with self.subTest(language=language):
                for key in ("update_identity_current", "update_identity_unrecorded", "update_identity_not_recorded"):
                    self.assertIn(key, MESSAGES[language])
                current = setup_commands._identity_change_line(unchanged, language=language)
                self.assertIn(f"main@{NEW[:8]}", current)
                self.assertIn("4.0.6", current)
                self.assertIn("4.0.6", setup_commands._identity_change_line(unrecorded, language=language))
        self.assertEqual(
            setup_commands._identity_change_line(unchanged, language="ko"),
            f"oh-my-hermes 4.0.6: 이미 main@{NEW[:8]} 상태입니다",
        )


class UpdateOutputTests(unittest.TestCase):
    def _update(self, result: dict[str, object], *, json_output: bool) -> tuple[int, str]:
        output = io.StringIO()
        with (
            patch("omh.commands.setup._command_package_self_update_plan", return_value={"should_update": True, "method": "installer"}),
            patch("omh.install.self_update.run_installer_self_update", return_value=result),
            contextlib.redirect_stdout(output),
        ):
            status = setup_commands.cmd_update(Namespace(json=json_output, language="en"))
        return status, output.getvalue()

    def test_human_update_names_the_commit_move_even_when_the_version_held(self) -> None:
        change = _change("changed", _identity("4.0.6", OLD), _identity("4.0.6", NEW))
        status, printed = self._update(_ok_result(change), json_output=False)
        self.assertEqual(status, 0)
        lines = printed.splitlines()
        complete = lines.index("OMH update complete: command and workflow pack activated together.")
        self.assertEqual(lines[complete + 1], f"  oh-my-hermes 4.0.6 main@{OLD[:8]} → main@{NEW[:8]}")

    def test_json_update_carries_the_identity_change(self) -> None:
        change = _change("unchanged", _identity("4.0.6", NEW), _identity("4.0.6", NEW))
        status, printed = self._update(_ok_result(change), json_output=True)
        self.assertEqual(status, 0)
        payload = json.loads(printed)
        self.assertEqual(payload["identity_change"], change)
        self.assertNotIn("already at", printed)

    def test_a_stopped_update_prints_no_identity_line_and_exits_nonzero(self) -> None:
        stopped = {"ok": False, "phase": "post_activation", "post_activation": {"status": "failed", "reason": "boom"}, "rollback": {"performed": True, "restored": "g1"}}
        status, printed = self._update(stopped, json_output=False)
        self.assertEqual(status, 1)
        self.assertNotIn("oh-my-hermes", printed)
        self.assertNotIn("already at", printed)

    def test_an_update_without_a_change_record_prints_the_old_summary_only(self) -> None:
        result = _ok_result({})
        result.pop("identity_change")
        status, printed = self._update(result, json_output=False)
        self.assertEqual(status, 0)
        self.assertEqual(printed.strip(), "OMH update complete: command and workflow pack activated together.")


class ProfileOnlyFailureExitCodeTests(unittest.TestCase):
    """A bot profile failing gets its own nonzero code, so a staged update keeps the generation."""

    def _update(self, failed_rows: list[dict[str, object]], *, agent_skills_error: bool = False) -> tuple[int, dict]:
        from _cli_harness import run_cli

        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            argv = ["--omh-home", str(root / "omh"), "--hermes-home", str(root / "hermes"), "update", "--json"]
            agent_skills = patch(
                "omh.install.agent_skills_projection.refresh_installed_agent_skills",
                side_effect=OSError("agent skills unwritable") if agent_skills_error else None,
                return_value={"refreshed_files": 0},
            )
            with (
                patch.dict(os.environ, {setup_commands.SELF_UPDATE_SKIP_ENV: "1"}),
                patch("omh.install.agent_skills_projection.agent_skills_user_home", return_value=root / "user"),
                agent_skills,
                patch.object(setup_commands, "_sync_hermes_profiles", return_value=failed_rows),
                patch.object(setup_commands, "_refresh_installed_menubar_app", return_value=None),
            ):
                status, stdout, _stderr = run_cli(argv)
        return status, json.loads(stdout)

    def test_only_bot_profiles_failing_exits_with_the_profile_repair_code(self) -> None:
        rows = [{"profile": "dapbench", "status": "failed", "error": "PluginPackError: plugins/omh exists without an OMH plugin manifest"}]
        status, payload = self._update(rows)
        self.assertEqual(status, setup_commands.PROFILE_REPAIR_EXIT_CODE)
        self.assertEqual(payload["exit_code"], setup_commands.PROFILE_REPAIR_EXIT_CODE)
        self.assertEqual(payload["status"], "partial")
        self.assertEqual([row["phase"] for row in payload["failures"]], ["profile_sync"])

    def test_a_failure_in_this_home_still_exits_1(self) -> None:
        rows = [{"profile": "dapbench", "status": "failed", "error": "boom"}]
        status, payload = self._update(rows, agent_skills_error=True)
        self.assertEqual(status, 1)
        self.assertEqual(sorted(row["phase"] for row in payload["failures"]), ["agent_skills", "profile_sync"])

    def test_a_clean_update_exits_0(self) -> None:
        status, payload = self._update([])
        self.assertEqual((status, payload["exit_code"], payload["status"]), (0, 0, "ok"))


class StagedUpdateRecoveryDoctorTests(unittest.TestCase):
    def _check(self, state: object | None):
        from omh.maintenance import doctor

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "self-update.json"
            if state is not None:
                path.write_text(state if isinstance(state, str) else json.dumps(state), encoding="utf-8")
            with (
                patch.object(doctor, "managed_command_self_update_state_path", return_value=path),
                patch.object(doctor.sys, "prefix", str(Path(temporary) / "generations" / "g1" / "venv")),
            ):
                return doctor._staged_update_recovery_check()

    def test_a_doctor_running_outside_the_managed_root_reads_no_marker(self) -> None:
        from omh.maintenance import doctor

        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "managed" / "self-update.json"
            path.parent.mkdir()
            path.write_text(json.dumps({"activation_in_progress": {"previous": "/g1", "candidate": "/g2", "restore_required": True}}), encoding="utf-8")
            with (
                patch.object(doctor, "managed_command_self_update_state_path", return_value=path),
                patch.object(doctor.sys, "prefix", str(Path(temporary) / "checkout" / ".venv")),
            ):
                check = doctor._staged_update_recovery_check()
        self.assertTrue(check.ok)
        self.assertFalse(check.observed)

    def test_an_open_restore_marker_names_the_blocked_updates_and_the_step(self) -> None:
        check = self._check({
            "activation_in_progress": {
                "candidate": "/root/generations/20261104090113899212-edfca25300",
                "previous": "/root/generations/20261104024458671554-edfca25300",
                "phase": "post_switch",
                "restore_required": True,
            }
        })
        self.assertFalse(check.ok)
        self.assertEqual(check.severity, "warning")
        self.assertIn("could not restore generation 20261104024458671554-edfca25300", check.message)
        self.assertIn("installs nothing new until it succeeds", check.message)
        self.assertIn("finishes the restore before staging", check.next_action)
        self.assertIn("plugins/omh points at a deleted path", check.remediation)

    def test_other_states(self) -> None:
        interrupted = self._check({"activation_in_progress": {"candidate": "/r/generations/g2", "previous": "/r/generations/g1", "phase": "post_switch"}})
        self.assertFalse(interrupted.ok)
        self.assertIn("interrupted while activating generation g2", interrupted.message)
        self.assertTrue(self._check({"activation_in_progress": None}).ok)
        absent = self._check(None)
        self.assertTrue(absent.ok)
        self.assertFalse(absent.observed)
        self.assertFalse(self._check("not json").ok)


class ChannelAliasTests(unittest.TestCase):
    def test_main_is_parsed_as_the_preview_channel(self) -> None:
        for argv in (["update", "--channel", "main"], ["update", "--channel=main"], ["setup", "--channel", "main"]):
            with self.subTest(argv=argv):
                self.assertEqual(build_parser().parse_args(argv).channel, "preview")
        self.assertEqual(build_parser().parse_args(["update", "--channel", "stable"]).channel, "stable")

    def test_an_unknown_channel_is_still_refused(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as exited:
            build_parser().parse_args(["update", "--channel", "nightly"])
        self.assertEqual(exited.exception.code, 2)
        self.assertIn("invalid choice", stderr.getvalue())

    def test_the_installer_plan_for_main_is_the_preview_archive(self) -> None:
        args = Namespace(
            command_package_updated=False,
            dry_run=False,
            from_skills_dir=None,
            source=None,
            channel=build_parser().parse_args(["update", "--channel", "main"]).channel,
            version="",
            package_url="",
            source_ref="",
        )
        with (
            patch.dict(os.environ, {setup_commands.COMMAND_PACKAGE_MANAGER_ENV: "", setup_commands.SELF_UPDATE_SKIP_ENV: ""}),
            patch.object(setup_commands, "_command_package_update_guidance", return_value=("installer", "curl")),
            patch.object(setup_commands, "_managed_command_runtime", return_value={"managed": True, "python": "python", "venv_dir": "venv"}),
        ):
            plan = setup_commands._command_package_self_update_plan(args)
        self.assertEqual(plan["method"], "installer")
        self.assertEqual(plan["release"].channel, "preview")
        self.assertEqual(plan["release"].package_url, "https://github.com/rlaope/oh-my-hermes/archive/refs/heads/main.zip")


class InstalledChannelSelfUpdateTests(unittest.TestCase):
    """A plain `omh update` keeps the channel the installer recorded instead of jumping to main."""

    STABLE_WHEEL = {
        "url": "https://github.com/rlaope/oh-my-hermes/releases/download/v4.0.5/oh_my_hermes-4.0.5-py3-none-any.whl",
        "archive_info": {},
    }
    MAIN_ARCHIVE = {"url": "https://github.com/rlaope/oh-my-hermes/archive/refs/heads/main.zip", "archive_info": {}}

    def _plan(self, record: dict[str, object] | None, *, latest: str | Exception = "9.9.9", dry_run: bool = False, **flags: str) -> dict[str, object]:
        args = Namespace(
            command_package_updated=False,
            dry_run=dry_run,
            from_skills_dir=None,
            source=None,
            channel=flags.get("channel"),
            version=flags.get("version", ""),
            package_url="",
            source_ref="",
        )
        fetch = patch("omh.tui.update_notice.fetch_latest", side_effect=latest if isinstance(latest, Exception) else None, return_value=latest)
        with (
            patch.dict(os.environ, {setup_commands.COMMAND_PACKAGE_MANAGER_ENV: "", setup_commands.SELF_UPDATE_SKIP_ENV: ""}),
            patch.object(setup_commands, "_command_package_update_guidance", return_value=("installer", "curl")),
            patch.object(setup_commands, "_managed_command_runtime", return_value={"managed": True, "python": "python", "venv_dir": "venv"}),
            patch.object(setup_commands, "_installed_direct_url", return_value=record),
            fetch as fetched,
        ):
            plan = setup_commands._command_package_self_update_plan(args)
        plan["fetched"] = fetched.called
        return plan

    def test_a_stable_install_moves_to_the_newest_release_wheel(self) -> None:
        plan = self._plan(self.STABLE_WHEEL)
        self.assertTrue(plan["should_update"])
        self.assertEqual(plan["release"].channel, "stable")
        self.assertEqual(
            plan["release"].package_url,
            "https://github.com/rlaope/oh-my-hermes/releases/download/v9.9.9/oh_my_hermes-9.9.9-py3-none-any.whl",
        )

    def test_a_stable_install_already_on_the_newest_release_is_left_alone(self) -> None:
        plan = self._plan(self.STABLE_WHEEL, latest=setup_commands.__version__)
        self.assertFalse(plan["should_update"])
        self.assertIn("already on the newest stable release", plan["reason"])

    def test_an_unreadable_newest_release_skips_the_command_package_instead_of_taking_main(self) -> None:
        plan = self._plan(self.STABLE_WHEEL, latest=OSError("offline"))
        self.assertFalse(plan["should_update"])
        self.assertIn("could not read the newest stable release", plan["reason"])
        self.assertNotIn("release", plan)

    def test_a_prerelease_newest_version_is_not_installed_as_stable(self) -> None:
        plan = self._plan(self.STABLE_WHEEL, latest="9.9.9-beta.1")
        self.assertFalse(plan["should_update"])
        self.assertIn("not a stable version", plan["reason"])

    def test_an_install_newer_than_npm_latest_is_not_downgraded(self) -> None:
        # The release workflow creates the GitHub release before `npm publish`, so npm's
        # `latest` can trail a stable install made from the new release's wheel.
        current = tuple(int(part) for part in setup_commands.__version__.split("."))
        older = ".".join(map(str, current[:-1] + (current[-1] - 1,))) if current[-1] else "0.0.1"
        for latest in (older, "0.0.1"):
            with self.subTest(latest=latest):
                plan = self._plan(self.STABLE_WHEEL, latest=latest)
                self.assertFalse(plan["should_update"])
                self.assertNotIn("release", plan)
                self.assertIn("is newer than the newest published release", plan["reason"])

    def test_a_numerically_newer_release_is_taken_even_when_it_sorts_lower_as_text(self) -> None:
        major, minor, _patch = setup_commands.__version__.split(".")
        latest = f"{major}.{minor}.{int(_patch) + 10}"
        plan = self._plan(self.STABLE_WHEEL, latest=latest)
        self.assertTrue(plan["should_update"])
        self.assertEqual(plan["release"].version, latest)

    def test_an_http_client_failure_skips_the_command_package_instead_of_raising(self) -> None:
        import http.client

        for error in (http.client.IncompleteRead(b'{"ver'), http.client.BadStatusLine("garbled")):
            with self.subTest(error=type(error).__name__):
                plan = self._plan(self.STABLE_WHEEL, latest=error)
                self.assertFalse(plan["should_update"])
                self.assertNotIn("release", plan)
                self.assertIn("could not read the newest stable release", plan["reason"])

    def test_a_main_install_and_an_unrecorded_install_keep_tracking_main(self) -> None:
        for record in (self.MAIN_ARCHIVE, None):
            with self.subTest(record=record):
                plan = self._plan(record)
                self.assertEqual(plan["release"].channel, "preview")
                self.assertFalse(plan["fetched"])

    def test_an_explicit_channel_still_wins_over_the_installed_record(self) -> None:
        plan = self._plan(self.STABLE_WHEEL, channel="preview")
        self.assertEqual(plan["release"].channel, "preview")
        self.assertFalse(plan["fetched"])

    def test_a_dry_run_plans_the_same_update_a_real_run_would_make(self) -> None:
        plan = self._plan(self.STABLE_WHEEL, dry_run=True)
        self.assertTrue(plan["should_update"])
        self.assertEqual(setup_commands._self_update_target_label(plan), "v9.9.9")


class DryRunCommandPackageCardTests(unittest.TestCase):
    def test_a_dry_run_reports_the_update_a_real_run_would_make(self) -> None:
        status = setup_commands._command_package_status_for_install(
            operation="update", source="builtin", dry_run=True, would_update_to="v9.9.9"
        )
        self.assertEqual(status["status"], "would_update")
        self.assertFalse(status["updated"])
        self.assertEqual(status["would_update_to"], "v9.9.9")
        for language in LANGUAGE_CODES:
            with self.subTest(language=language):
                self.assertIn("{target}", MESSAGES[language]["update_card_command_would_update"])

    def test_a_dry_run_with_nothing_to_update_still_says_unchanged(self) -> None:
        status = setup_commands._command_package_status_for_install(operation="update", source="builtin", dry_run=True)
        self.assertEqual(status["status"], "would_remain_unchanged")
        self.assertNotIn("would_update_to", status)

    def test_cmd_update_dry_run_does_not_run_the_planned_self_update(self) -> None:
        args = build_parser().parse_args(["update", "--dry-run"])
        plan = {"should_update": True, "method": "installer", "release": setup_commands.package_url_for("stable", "9.9.9")}
        with (
            patch.object(setup_commands, "_command_package_self_update_plan", return_value=plan),
            patch.object(setup_commands, "_run_command_package_self_update") as run,
            patch.object(setup_commands, "cmd_install", return_value=1),
        ):
            setup_commands.cmd_update(args)
        run.assert_not_called()
        self.assertEqual(args.command_package_would_update, "v9.9.9")


class PackageManagerMainRefusalTests(unittest.TestCase):
    def test_an_npm_install_refuses_to_claim_it_tracks_main(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            package_root = root / "oh-my-hermes"
            entrypoint = package_root / "bin" / "omh.js"
            entrypoint.parent.mkdir(parents=True)
            entrypoint.write_text("export {};\n", encoding="utf-8")
            (package_root / "package.json").write_text(
                json.dumps({"name": "oh-my-hermes", "version": setup_commands.__version__, "bin": {"omh": "bin/omh.js"}}),
                encoding="utf-8",
            )
            runtime = root / "node"
            runtime.touch()
            manager = root / "npm"
            manager.touch()
            env = {
                setup_commands.COMMAND_PACKAGE_MANAGER_ENV: "npm",
                setup_commands.COMMAND_PACKAGE_ROOT_ENV: str(package_root),
                setup_commands.COMMAND_PACKAGE_RUNTIME_ENV: str(runtime),
                setup_commands.COMMAND_PACKAGE_ENTRYPOINT_ENV: str(entrypoint),
                setup_commands.SELF_UPDATE_SKIP_ENV: "",
            }
            for channel, refused in (("preview", True), (None, False)):
                args = Namespace(
                    command_package_updated=False,
                    dry_run=False,
                    from_skills_dir=None,
                    source=None,
                    channel=channel,
                    version="",
                    package_url="",
                    source_ref="",
                )
                with (
                    self.subTest(channel=channel),
                    patch.dict(os.environ, env),
                    patch.object(setup_commands.shutil, "which", return_value=str(manager)),
                ):
                    if refused:
                        with self.assertRaisesRegex(OmhError, "npm installs follow published releases and cannot track main"):
                            setup_commands._command_package_self_update_plan(args)
                    else:
                        plan = setup_commands._command_package_self_update_plan(args)
                        self.assertEqual(plan["method"], "package_manager")


if __name__ == "__main__":
    unittest.main()

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

from __future__ import annotations

import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.cli import main


def run_cli(args: list[str]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        status = main(args)
    return status, stdout.getvalue(), stderr.getvalue()


class CliTests(unittest.TestCase):
    def test_install_apply_doctor_and_list(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "install"])[0], 0)
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "apply"])[0], 0)
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "list"])[0], 0)
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "doctor"])[0], 0)

            manifest = json.loads((omh_home / "manifest.json").read_text(encoding="utf-8"))
            names = {skill["name"] for skill in manifest["skills"]}
            self.assertIn("oh-my-hermes", names)
            self.assertIn("ralph", names)
            self.assertIn("ultragoal", names)
            self.assertIn(str(omh_home / "skills"), (hermes_home / "config.yaml").read_text(encoding="utf-8"))

            _, doctor_stdout, _ = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "doctor"])
            doctor = json.loads(doctor_stdout)
            checks = {check["name"]: check for check in doctor["checks"]}
            self.assertTrue(checks["runtime_context"]["ok"])
            self.assertIn("--hermes-home", checks["runtime_context"]["message"])
            self.assertTrue(checks["manifest_skills_dir"]["ok"])
            self.assertTrue(checks["local_modifications"]["ok"])

    def test_install_is_idempotent_and_detects_local_modifications(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            hermes_home = root / ".hermes"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "install"])[0], 0)
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "install"])[0], 0)
            skill_file = omh_home / "skills" / "ralph" / "SKILL.md"
            skill_file.write_text(skill_file.read_text(encoding="utf-8") + "\nlocal edit\n", encoding="utf-8")

            status, _, stderr = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "install"])
            self.assertEqual(status, 2)
            self.assertIn("local modifications detected", stderr)

            doctor_status, doctor_stdout, _ = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "doctor"])
            self.assertEqual(doctor_status, 1)
            checks = {check["name"]: check for check in json.loads(doctor_stdout)["checks"]}
            self.assertFalse(checks["local_modifications"]["ok"])
            self.assertIn("ralph/SKILL.md", checks["local_modifications"]["message"])
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(hermes_home), "install", "--force"])[0], 0)

    def test_doctor_reports_wrong_runtime_home(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            installed_hermes_home = root / ".hermes-installed"
            other_hermes_home = root / ".hermes-other"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(installed_hermes_home), "install"])[0], 0)
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "--hermes-home", str(installed_hermes_home), "apply"])[0], 0)

            status, stdout, _ = run_cli(["--omh-home", str(omh_home), "--hermes-home", str(other_hermes_home), "doctor"])

            self.assertEqual(status, 1)
            checks = {check["name"]: check for check in json.loads(stdout)["checks"]}
            self.assertFalse(checks["runtime_context"]["ok"])
            self.assertIn("matching the Hermes or bot runtime", checks["runtime_context"]["message"])

    def test_convert_from_local_skill_fixture(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "local-skills" / "ralph"
            source.mkdir(parents=True)
            source.joinpath("SKILL.md").write_text(
                "---\nname: ralph\ndescription: Upstream Ralph\n---\n# Ralph\nUse durable goal tools.\n",
                encoding="utf-8",
            )
            omh_home = root / ".omh"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "convert", "--from-skills-dir", str(root / "local-skills")])[0], 0)
            converted = (omh_home / "skills" / "ralph" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("Hermes Compatibility Contract", converted)

    def test_mocked_source_install_update(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "release-archive" / "team"
            source.mkdir(parents=True)
            source.joinpath("SKILL.md").write_text(
                "---\nname: team\ndescription: Upstream Team\n---\n# Team\n",
                encoding="utf-8",
            )
            omh_home = root / ".omh"

            self.assertEqual(run_cli(["--omh-home", str(omh_home), "install", "--source", str(root / "release-archive")])[0], 0)
            first_manifest = json.loads((omh_home / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(first_manifest["source"], str((root / "release-archive").resolve()))

            source.joinpath("SKILL.md").write_text(
                "---\nname: team\ndescription: Upstream Team\n---\n# Team\nUpdated.\n",
                encoding="utf-8",
            )
            self.assertEqual(run_cli(["--omh-home", str(omh_home), "update", "--source", str(root / "release-archive")])[0], 0)
            updated = (omh_home / "skills" / "team" / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("Updated.", updated)


if __name__ == "__main__":
    unittest.main()

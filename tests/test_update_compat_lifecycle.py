"""Behavior regressions for audited config, recovery, and profile boundaries."""
from __future__ import annotations

from pathlib import Path
from argparse import Namespace
import json
import subprocess
import sys
from unittest.mock import patch
from tempfile import TemporaryDirectory
import unittest

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.install.config_adapter import _normalize, ensure_external_dir, external_dirs, remove_external_dir, update_config  # noqa: E402


from omh.install import self_update as su, self_update_state as st  # noqa: E402
from omh.install.skill_registration import hermes_profile_dirs  # noqa: E402
from omh.install.self_update_platform import remove_directory_link  # noqa: E402


class ConfigCompatibilityTests(unittest.TestCase):
    def test_empty_flow_mapping_registers_as_valid_block_mapping(self):
        for original in ("{}\n", "# config\n{} # empty mapping\n", "---\n{}\n...\n"):
            with self.subTest(original=original):
                change = ensure_external_dir(original, "/managed")
                self.assertTrue(change.changed)
                self.assertNotIn("{}", change.text)
                self.assertEqual(external_dirs(change.text), ["/managed"])
                for line in original.splitlines():
                    if "#" in line:
                        self.assertIn(line[line.index("#"):], change.text)
                self.assertFalse(ensure_external_dir(change.text, "/managed").changed)
                removed = remove_external_dir(change.text, "/managed")
                self.assertTrue(removed.changed)
                self.assertEqual(external_dirs(removed.text), [])
                self.assertFalse(remove_external_dir(original, "/managed").changed)

    def test_single_document_markers_registration_round_trip(self):
        envelopes = (
            ("---\n", ""),
            ("# my config\n--- # start\n", ""),
            ("%YAML 1.1\n---\n", ""),
            ("%YAML 1.2\n---\n", ""),
            ("%TAG !e! tag:example.com,2026:\n---\n", ""),
            ("", "... # end\n# after document\n"),
            ("%YAML 1.1\n%TAG !e! tag:example.com,2026:\n--- # start\n", "... # end\n"),
        )
        for prefix, suffix in envelopes:
            for skills in ("", "skills: # preferences\n  external_dirs: [/existing] # dirs\n"):
                with self.subTest(prefix=prefix, suffix=suffix, skills=skills), TemporaryDirectory() as temporary:
                    config = Path(temporary) / "config.yaml"
                    original = prefix + skills + "model: x\n" + suffix
                    config.write_text(original, encoding="utf-8")
                    change = update_config(config, lambda text: ensure_external_dir(text, "/managed"))
                    self.assertTrue(change.written)
                    expected = (["/existing"] if skills else []) + ["/managed"]
                    self.assertEqual(external_dirs(change.text), expected)
                    self.assertEqual(change.text.count("    - /managed\n"), 1)
                    self.assertTrue(change.text.startswith(prefix))
                    self.assertTrue(change.text.endswith(suffix))
                    if suffix:
                        self.assertLess(change.text.index("    - /managed"), change.text.index("..."))
                    self.assertEqual(ensure_external_dir(change.text, "/managed").text, change.text)
                    self.assertFalse(ensure_external_dir(change.text, "/managed").changed)
                    removed = update_config(config, lambda text: remove_external_dir(text, "/managed"))
                    self.assertTrue(removed.written)
                    self.assertEqual(external_dirs(removed.text), expected[:-1])
                    self.assertTrue(removed.text.startswith(prefix))
                    self.assertTrue(removed.text.endswith(suffix))
                    self.assertIn("model: x\n", removed.text)

    def test_document_streams_and_non_mapping_roots_refuse_without_writing(self):
        cases = (
            ("---\nmodel: x\n---\nmodel: y\n", "multi-document"),
            ("model: x\n---\nmodel: y\n", "multi-document"),
            ("---\nmodel: x\n...\n---\nmodel: y\n", "multi-document"),
            ("---\n- item\n", "non-mapping"),
            ("---\nscalar\n...\n", "non-mapping"),
        )
        for original, reason in cases:
            with self.subTest(original=original), TemporaryDirectory() as temporary:
                config = Path(temporary) / "config.yaml"
                config.write_bytes(original.encode("utf-8"))
                with self.assertRaisesRegex(ValueError, reason):
                    update_config(config, lambda text: ensure_external_dir(text, "/managed"))
                self.assertEqual(config.read_bytes(), original.encode("utf-8"))
                # Nothing to take out is answered before the refusal, so uninstall never fails on it (#3075).
                self.assertFalse(update_config(config, lambda text: remove_external_dir(text, "/managed")).written)
                self.assertEqual(config.read_bytes(), original.encode("utf-8"))

    def test_flow_child_under_skills_refuses_without_writing(self):
        for header in ("skills:", "skills: # preferences"):
            for child in ("{external_dirs: [/existing]}", "[/existing, /other]"):
                with self.subTest(header=header, child=child), TemporaryDirectory() as temporary:
                    config = Path(temporary) / "config.yaml"
                    original = f"{header}\n# keep note\n  {child}\nmodel: x\n"
                    config.write_bytes(original.encode("utf-8"))
                    with self.assertRaisesRegex(ValueError, "flow.*skills|skills.*flow"):
                        update_config(config, lambda text: ensure_external_dir(text, "/managed"))
                    self.assertEqual(config.read_bytes(), original.encode("utf-8"))
                    with self.assertRaisesRegex(ValueError, "flow.*skills|skills.*flow"):
                        remove_external_dir(original, "/existing")

    def test_commented_skills_public_apply_preserves_existing_preferences(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "hermes"
            home.mkdir()
            config = home / "config.yaml"
            before = ("skills: # my skill preferences\n  external_dirs:\n"
                      "    - /existing-skills\n  create_dir: /my-skills\n  ledger: false\n")
            config.write_text(before, encoding="utf-8")
            code, stdout, stderr = run_cli(["--hermes-home", str(home), "--omh-home", str(root / "omh"),
                                           "apply", "--json"])
            self.assertEqual(code, 0, (stdout, stderr))
            after = config.read_text(encoding="utf-8")
            self.assertEqual(sum(line.startswith("skills:") for line in after.splitlines()), 1, after)
            self.assertIn("skills: # my skill preferences", after)
            self.assertIn("  create_dir: /my-skills\n  ledger: false", after)
            self.assertEqual(external_dirs(after), ["/existing-skills", _normalize((root / "omh" / "skills").resolve())])
    def test_standalone_comment_does_not_hide_an_existing_external_dirs_key(self):
        original = "skills: # preferences\n# directories follow\n  external_dirs:\n    - /existing\n"
        change = ensure_external_dir(original, "/managed")
        self.assertEqual(change.text.count("  external_dirs:"), 1)
        self.assertEqual(external_dirs(change.text), ["/existing", "/managed"])

    def test_commented_external_list_round_trip_preserves_user_entry(self):
        for header in ("  external_dirs: # directories", "  external_dirs: [/existing] # directories"):
            with self.subTest(header=header):
                original = "skills: # preferences\n" + header + "\n"
                if "[/existing]" not in header:
                    original += "    - /existing\n"
                original += "# keep this note\n  ledger: false\n"
                change = ensure_external_dir(original, "/managed")
                self.assertEqual(external_dirs(change.text), ["/existing", "/managed"])
                self.assertIn("# directories", change.text)
                self.assertIn("# keep this note", change.text)
                self.assertEqual(external_dirs(remove_external_dir(change.text, "/managed").text), ["/existing"])
                self.assertFalse(ensure_external_dir(change.text, "/managed").changed)

    def test_unrelated_yaml_syntax_does_not_block_skills_registration(self):
        elsewhere = (
            'aliases:\n  "fast/model": glm-5.3\n',
            '"model": x\n',
            "defaults: &defaults\n  retries: 1\n",
            "defaults: &defaults\n  retries: 1\nplugins:\n  <<: *defaults\n",
        )
        for prefix in ("", "skills: # preferences\n  external_dirs:\n    - /existing\n"):
            for suffix in elsewhere:
                with self.subTest(prefix=prefix, suffix=suffix):
                    original = prefix + suffix
                    change = ensure_external_dir(original, "/managed")
                    self.assertTrue(change.changed)
                    self.assertIn(suffix, change.text)
                    expected = (["/existing"] if prefix else []) + ["/managed"]
                    self.assertEqual(external_dirs(change.text), expected)
                    self.assertFalse(ensure_external_dir(change.text, "/managed").changed)
                    removed = remove_external_dir(change.text, "/managed")
                    self.assertTrue(removed.changed)
                    self.assertIn(suffix, removed.text)
                    self.assertEqual(external_dirs(removed.text), expected[:-1])

    def test_bom_registration_round_trip_preserves_existing_entries(self):
        for body in (
            "skills:\n  external_dirs:\n    - /existing\nmodel: x\n",
            "skills: # preferences\n  external_dirs: [/existing] # dirs\nmodel: x\n",
            "model: x\nskills:\n  external_dirs:\n    - /existing\n",
            "model: x\n",
        ):
            with self.subTest(body=body), TemporaryDirectory() as temporary:
                config = Path(temporary) / "config.yaml"
                original = "\ufeff" + body
                config.write_text(original, encoding="utf-8")
                change = update_config(config, lambda text: ensure_external_dir(text, "/managed"))
                self.assertTrue(change.written)
                self.assertTrue(config.read_bytes().startswith(b"\xef\xbb\xbf"))
                self.assertEqual(change.text.count("\ufeff"), 1)
                self.assertEqual(sum(line.startswith("skills:") for line in change.text.removeprefix("\ufeff").splitlines()), 1)
                expected = (["/existing"] if "external_dirs:" in body else []) + ["/managed"]
                self.assertEqual(external_dirs(change.text), expected)
                again = ensure_external_dir(change.text, "/managed")
                self.assertFalse(again.changed)
                self.assertEqual(again.text, change.text)
                removed = update_config(config, lambda text: remove_external_dir(text, "/managed"))
                self.assertTrue(removed.written)
                self.assertTrue(config.read_bytes().startswith(b"\xef\xbb\xbf"))
                self.assertEqual(external_dirs(removed.text), expected[:-1])
                self.assertIn("model: x\n", removed.text)

    def test_uneditable_yaml_refuses_instead_of_shadowing_keys(self):
        for original in (
            "'skills':\n  external_dirs: []\n",
            '"skills": # note\n  external_dirs: []\n',
            "skills: {external_dirs: [/existing]}\n",
            "skills: &prefs\n  external_dirs: []\n",
            "skills:\n  'external_dirs': []\n",
            "skills:\n  external_dirs: []\nskills: # duplicate\n  ledger: false\n",
            "skills:\n  external_dirs: []\n  external_dirs: [/other]\n",
            "skills:\n  external_dirs: /not-a-list\n",
        ):
            with self.subTest(original=original), self.assertRaises(ValueError):
                ensure_external_dir(original, "/managed")


class RecoveryCompatibilityTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.old = self.root / "generations" / "old"
        self.candidate = self.root / "generations" / "candidate"
        for generation in (self.old, self.candidate):
            (generation / "venv" / "bin").mkdir(parents=True)
            (generation / "skills").mkdir()
        self.shared = self.root / "shared-resource"
        self.shared.write_text("known-good", encoding="utf-8")
        from test_staged_self_update import StagedSelfUpdateTests
        self.platform = StagedSelfUpdateTests._platform()
        st.switch_current(self.root, self.old, platform=self.platform)
        self.state = {"schema_version": st.STATE_SCHEMA_VERSION, "active": st.generation_entry(self.old),
                      "previous_known_good": None, "migration": {"status": "completed"},
                      "activation_in_progress": None, "retained_generations": ["old"]}
        st.record_pointer(self.state, self.root, self.old)
        st.save_state(self.root, self.state)
        self.calls = []

    def runner(self, restore_ok=False):
        def run(command, **kwargs):
            restoring = kwargs["env"].get(su.ROLLBACK_RESTORE_ENV) == "1"
            self.calls.append(restoring)
            value = "known-good" if restoring and restore_ok else "partial-candidate"
            code = 0 if restoring and restore_ok else 1
            program = (f"from pathlib import Path; import sys; Path({str(self.shared)!r}).write_text({value!r}, "
                       f"encoding='utf-8'); sys.stderr.write('injected reentry refusal'); sys.exit({code})")
            return subprocess.run([sys.executable, "-c", program], text=True, capture_output=True, timeout=10)
        return run

    def activate(self, restore_ok=False):
        with patch.object(sys, "argv", ["omh", "update", "--json"]):
            return su._activate(self.root, self.state, self.candidate, Namespace(json=True),
                                self.runner(restore_ok), self.platform, su._result(self.candidate))

    def test_restore_marker_does_not_bypass_current_pointer_validation(self):
        st.mark_activation(self.state, self.candidate, self.old)
        self.state["activation_in_progress"]["restore_required"] = True
        remove_directory_link(self.root / "current")
        outside = self.root / "outside"
        outside.mkdir()
        self.platform.create_directory_link(self.root, self.root / "current", outside)
        from omh.core.errors import OmhError
        with self.assertRaises(OmhError):
            st.interrupted_activation(self.root, self.state, platform=self.platform)
        self.assertTrue(self.candidate.is_dir())

    def test_interrupted_activation_failed_restore_is_retried_until_healthy(self):
        st.mark_activation(self.state, self.candidate, self.old)
        st.switch_current(self.root, self.candidate, platform=self.platform)
        st.mark_switched(self.state)
        st.save_state(self.root, self.state)
        with patch.object(sys, "argv", ["omh", "update", "--json"]):
            result = su._recover_interrupted(self.root, self.state, (self.candidate, self.old),
                                            Namespace(json=True), self.runner(), self.platform,
                                            su._result(self.candidate))
        self.assertEqual(result["rollback"]["restored"], "")
        self.assertEqual(result["recovery"]["status"], "required")
        loaded = st.load_state(self.root, self.root / "legacy")
        self.assertEqual(st.interrupted_activation(self.root, loaded, platform=self.platform),
                         (self.candidate, self.old))
        self.assertTrue(self.candidate.is_dir())
        self.calls.clear()
        args = Namespace(json=True, hermes_home=str(self.root / "hermes"), omh_home=str(self.root / "omh"))
        with patch.object(sys, "argv", ["omh", "update", "--json"]):
            result = su.run_installer_self_update(args, {"venv_dir": str(self.root / "legacy")},
                                                 runner=self.runner(True), platform=self.platform)
        self.assertEqual(self.calls, [True], "pending restore must not retry candidate activation")
        self.assertEqual(result["rollback"]["restored"], "old")
        self.assertIsNone(st.load_state(self.root, self.root / "legacy")["activation_in_progress"])
        self.assertFalse(self.candidate.exists())
        self.assertEqual(self.shared.read_text(encoding="utf-8"), "known-good")

    def test_healthy_restore_clears_marker_and_disposes_rejected_candidate(self):
        result = self.activate(restore_ok=True)
        self.assertEqual(result["rollback"]["restored"], "old")
        self.assertIsNone(st.load_state(self.root, self.root / "legacy")["activation_in_progress"])
        self.assertFalse(self.candidate.exists())
        self.assertEqual(self.shared.read_text(encoding="utf-8"), "known-good")

    def test_failed_restore_keeps_marker_anchor_and_truthful_failure(self):
        result = self.activate()
        persisted = st.load_state(self.root, self.root / "legacy")
        self.assertIsInstance(persisted["activation_in_progress"], dict)
        self.assertTrue(persisted["activation_in_progress"]["restore_required"])
        self.assertTrue(self.candidate.is_dir())
        self.assertEqual(result["rollback"]["restored"], "")
        self.assertEqual(result["rollback"]["status"], "failed")
        self.assertIn("refusal", result["rollback"]["reason"])
        self.assertEqual(result["recovery"]["status"], "required")
        self.assertEqual(self.calls, [False, True])
        self.assertEqual(self.shared.read_text(encoding="utf-8"), "partial-candidate")
        self.assertEqual((self.root / "current").resolve(), self.old)


class ProfileCompatibilityTests(unittest.TestCase):
    def test_identity_markers_include_link_claims_but_exclude_tombstones(self):
        with TemporaryDirectory() as temporary:
            home = Path(temporary)
            profiles = home / "profiles"
            expected = []
            for index, marker in enumerate(("config.yaml", ".env", "SOUL.md", "profile.yaml", "auth.json", "state.db")):
                name = f"bot-{index}"
                target = profiles / name
                target.mkdir(parents=True)
                (target / marker).touch()
                expected.append(name)
            dangling = profiles / "dangling"
            dangling.mkdir()
            (dangling / "config.yaml").symlink_to(home / "missing-config")
            expected.append("dangling")
            for name in ("deleted", ".hidden"):
                target = profiles / name
                target.mkdir()
                (target / "config.yaml").touch()
            (profiles / ".deleted").mkdir()
            (profiles / ".deleted" / "deleted").touch()
            self.assertEqual([name for name, path in hermes_profile_dirs(home)], expected)

    def test_sync_ignores_log_cache_shells_but_bootstraps_existing_profile(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "hermes"
            ghost = home / "profiles" / "old-log-shell"
            (ghost / "logs").mkdir(parents=True)
            (ghost / "cache").mkdir()
            good = home / "profiles" / "bot"
            good.mkdir()
            (good / "SOUL.md").write_text("profile identity\n", encoding="utf-8")
            code, stdout, stderr = run_cli(["--hermes-home", str(home), "--omh-home", str(root / "omh"),
                                           "update", "--core", "--json"])
            self.assertEqual(code, 0, (stdout, stderr))
            rows = json.loads(stdout)["hermes_profiles"]
            self.assertEqual([row["profile"] for row in rows], ["bot"])
            self.assertEqual(sorted(path.name for path in ghost.iterdir()), ["cache", "logs"])
            self.assertTrue((good / "config.yaml").is_file())
            self.assertTrue((home / "config.yaml").is_file(), "primary/default home remains supported")


if __name__ == "__main__":
    unittest.main()

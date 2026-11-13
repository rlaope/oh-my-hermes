"""Dependency-free contracts plus explicitly enabled real-native integration."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import math
import os
import platform
import subprocess
import sys
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
from pathlib import Path
import tempfile
import unittest
from _module_patch import patch_modules
from _toolkit_path_guard import (POSIX_ONLY, assert_alias_does_not_exempt_links_below,
                                 assert_only_system_aliases_trusted, assert_unsearchable_directory_is_refused)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src/skills/molecular_docking_toolkit/scripts/dock.py"
ATOM = "ATOM      1  C1  LIG L   1      15.822  54.641  12.322  1.00  0.00     0.038 A \n"


def load_helper():
    spec = importlib.util.spec_from_file_location("docking_prerequisites", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrerequisiteTests(unittest.TestCase):
    def test_validated_inputs_are_not_a_docking_result(self):
        self.assertTrue(SCRIPT.is_file(), "missing prerequisite implementation")
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receptor = root / "receptor.pdbqt"
            ligand = root / "ligand.pdbqt"
            receptor.write_text(ATOM)
            ligand.write_text("ROOT\n" + ATOM + "ENDROOT\nTORSDOF 0\n")
            output = root / "preflight"
            code = helper.main([
                "--receptor", str(receptor), "--ligand", str(ligand),
                "--center", "15.190", "53.903", "16.917",
                "--box-size", "20", "20", "20", "--output-dir", str(output),
                "--validate-only",
            ])
            self.assertEqual(code, 0)
            manifest = json.loads((output / "preflight.json").read_text())
            self.assertEqual(manifest["execution_status"], "not_observed")
            self.assertEqual(manifest["status"], "prerequisites_validated")
            self.assertEqual(manifest["backend"], "standalone-autodock-vina-python")
            self.assertFalse(manifest["tooluniverse_execution"])
            self.assertNotIn("scores", manifest)
            self.assertEqual(sorted(p.name for p in output.iterdir()), ["preflight.json"])

    def test_torsdof_must_be_final_structural_record(self):
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ligand.pdbqt"
            path.write_text("ROOT\n" + ATOM + "ENDROOT\nTORSDOF 0\nBRANCH 1 2\n")
            with self.assertRaises(ValueError):
                helper.read_pdbqt(path, "ligand")
            path.write_text("ROOT\n" + ATOM + "ENDROOT\nTORSDOF 0\n" + ATOM.replace("    1  C1", "    2  C1"))
            with self.assertRaisesRegex(ValueError, "TORSDOF"):
                helper.read_pdbqt(path, "ligand")

    def test_default_execution_fails_closed_without_vina(self):
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receptor, ligand = self.inputs(root)
            output = root / "not-created"
            with patch_modules({"vina": None}), contextlib.redirect_stderr(io.StringIO()) as stderr:
                code = helper.main(self.argv(receptor, ligand, output))
            self.assertEqual(code, 3)
            self.assertIn("optional Vina dependency", stderr.getvalue())
            self.assertFalse(output.exists())
            self.assertNotIn("vina", sys.modules)

    @staticmethod
    def inputs(root):
        receptor, ligand = root / "receptor.pdbqt", root / "ligand.pdbqt"
        receptor.write_text(ATOM)
        ligand.write_text("ROOT\n" + ATOM + "ENDROOT\nTORSDOF 0\n")
        return receptor, ligand

    @staticmethod
    def argv(receptor, ligand, output):
        return ["--receptor", str(receptor), "--ligand", str(ligand),
                "--center", "15.190", "53.903", "16.917", "--box-size", "20", "20", "20",
                "--output-dir", str(output)]

    def test_resource_and_nonfinite_settings_refuse_before_writes(self):
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receptor, ligand = self.inputs(root)
            base = self.argv(receptor, ligand, root / "absent")
            for field, values in {
                "cpu": (0, 3), "seed": (0, 2147483648),
                "exhaustiveness": (0, 5), "n_poses": (0, 6),
                "host_timeout_seconds": (0, 181),
                "center": ([float("nan"), 0, 0], [float("inf"), 0, 0], [100001, 0, 0]),
                "box_size": ([0, 20, 20], [25, 20, 20], [float("nan"), 20, 20]),
            }.items():
                for value in values:
                    with self.subTest(field=field, value=value):
                        args = helper.parser().parse_args(base)
                        # Mutate argument data, not dynamically assigned test methods.
                        vars(args)[field] = value
                        with self.assertRaises(ValueError):
                            helper.validate(args)
            self.assertFalse((root / "absent").exists())

    def test_malformed_formats_and_atom_caps(self):
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receptor, ligand = self.inputs(root)
            bad_ligands = (
                ATOM, "ROOT\nENDROOT\nTORSDOF 0\n", "ROOT\n" + ATOM,
                "ROOT\n" + ATOM + "ENDROOT\nTORSDOF 17\n",
                "ROOT\n" + ATOM + ATOM + "ENDROOT\nTORSDOF 0\n",
                "MODEL 1\nROOT\n" + ATOM + "ENDROOT\nTORSDOF 0\nENDMDL\n",
                "ROOT\n" + ATOM[:30] + "     nan" + ATOM[38:] + "ENDROOT\nTORSDOF 0\n",
                "ROOT\n" + ATOM.replace("0.038 A", "0.038 Q") + "ENDROOT\nTORSDOF 0\n",
                "ROOT\n" + ATOM + "ENDROOT\nBRANCH 1 2\nENDBRANCH 2 1\nTORSDOF 1\n",
                "ROOT\n" + ATOM + "ENDROOT\nTORSDOF 0\n\x00",
            )
            for content in bad_ligands:
                with self.subTest(content=content[:40]):
                    ligand.write_text(content)
                    with self.assertRaises(ValueError):
                        helper.read_pdbqt(ligand, "ligand")
            for role, path in (("ligand", ligand), ("receptor", receptor)):
                with self.subTest(role=role):
                    records = "".join(ATOM[:6] + f"{i:5d}" + ATOM[11:] for i in range(1, helper.MAX_ATOMS[role] + 2))
                    path.write_text(("ROOT\n" if role == "ligand" else "") + records + ("ENDROOT\nTORSDOF 0\n" if role == "ligand" else ""))
                    with self.assertRaisesRegex(ValueError, "atom cap"):
                        helper.read_pdbqt(path, role)
            receptor.write_bytes(b"X" * (helper.MAX_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "byte cap"):
                helper.read_pdbqt(receptor, "receptor")
            receptor.write_text("BEGIN_RES\n" + ATOM + "END_RES\n")
            with self.assertRaisesRegex(ValueError, "unsupported"):
                helper.read_pdbqt(receptor, "receptor")

    def test_path_refusals_preserve_existing_files(self):
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receptor, ligand = self.inputs(root)
            missing = root / "missing.pdbqt"
            wrong = root / "wrong.pdb"
            wrong.write_text(ATOM)
            link = root / "link.pdbqt"
            link.symlink_to(receptor)
            parent_link = root / "parent-link"
            parent_link.symlink_to(root, target_is_directory=True)
            for path in (missing, wrong, link, parent_link / "receptor.pdbqt"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    helper.read_pdbqt(path, "receptor")
            output = root / "existing"
            output.mkdir()
            sentinel = output / "preflight.json"
            sentinel.write_text("unchanged")
            original = receptor.read_bytes(), ligand.read_bytes()
            for selected_output in (output, root / "missing-parent" / "child", parent_link / "new"):
                with self.subTest(output=selected_output):
                    with contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(helper.main(self.argv(receptor, ligand, selected_output) + ["--validate-only"]), 2)
            self.assertEqual(sentinel.read_text(), "unchanged")
            self.assertEqual((receptor.read_bytes(), ligand.read_bytes()), original)

    def test_receptor_and_ligand_must_be_different_files_however_spelled(self):
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receptor, ligand = self.inputs(root)
            (root / "sub").mkdir()
            hard_link = root / "hard-link.pdbqt"
            os.link(receptor, hard_link)
            for same in (receptor, root / "sub" / ".." / receptor.name, hard_link):
                stderr = io.StringIO()
                with self.subTest(ligand=same), contextlib.redirect_stderr(stderr):
                    self.assertEqual(helper.main(self.argv(receptor, same, root / "refused") + ["--validate-only"]), 2)
                    self.assertIn("receptor and ligand must be different files", stderr.getvalue())
            # A ligand symlinked to the receptor is refused as a symlink: `checked_path` reads both before `same_file`.
            link = root / "link.pdbqt"
            link.symlink_to(receptor)
            stderr = io.StringIO()
            with self.subTest(ligand=link), contextlib.redirect_stderr(stderr):
                self.assertEqual(helper.main(self.argv(receptor, link, root / "refused") + ["--validate-only"]), 2)
                self.assertIn("symlink paths are not accepted", stderr.getvalue())
            self.assertFalse((root / "refused").exists())
            missing = root / "missing.pdbqt"
            self.assertTrue(helper.same_file(missing, root / "sub" / ".." / missing.name))
            self.assertFalse(helper.same_file(missing, receptor))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(helper.main(self.argv(receptor, ligand, root / "validated") + ["--validate-only"]), 0)

    def test_only_macos_system_aliases_are_trusted(self):
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            assert_only_system_aliases_trusted(self, helper.checked_path, helper.system_alias, Path(directory),
                                               "symlink paths")

    @POSIX_ONLY
    def test_a_trusted_alias_does_not_exempt_a_link_below_it(self):
        assert_alias_does_not_exempt_links_below(self, load_helper().checked_path, "symlink paths")

    def test_an_unsearchable_directory_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            assert_unsearchable_directory_is_refused(self, load_helper().checked_path, Path(directory))

    def test_malformed_engine_pose_refuses_without_success_manifest(self):
        # Corrupted backend output fixture only: never evidence of native execution.
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receptor, ligand = self.inputs(root)
            output = root / "failed"
            engine = MagicMock()
            engine.energies.return_value.tolist.return_value = [[0.0] * 5]
            engine.write_poses.side_effect = lambda path, **kwargs: Path(path).write_text(
                "MODEL 1\nREMARK VINA RESULT:\n" + ATOM + "ENDMDL\n")
            backend = SimpleNamespace(Vina=MagicMock(return_value=engine), __version__="corruption-fixture")
            with patch_modules({"vina": backend}), contextlib.redirect_stderr(io.StringIO()) as stderr:
                code = helper.main(self.argv(receptor, ligand, output))
            self.assertEqual(code, 2)
            self.assertIn("saved pose", stderr.getvalue())
            self.assertFalse((output / "manifest.json").exists())
            engine.dock.assert_called_once()
            engine.optimize.assert_not_called()

    def test_engine_nonfinite_energies_refuse_before_pose_write(self):
        helper = load_helper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receptor, ligand = self.inputs(root)
            for energies in ([], [[float("nan")] * 5], [[float("inf")] * 5], [[0.0]]):
                with self.subTest(energies=energies):
                    engine = MagicMock()
                    engine.energies.return_value.tolist.return_value = energies
                    backend = SimpleNamespace(Vina=MagicMock(return_value=engine))
                    args = helper.parser().parse_args(self.argv(receptor, ligand, root / "new"))
                    r, l, output = helper.validate(args)
                    with self.assertRaisesRegex(ValueError, "energies"):
                        helper.run_docking(backend, args, r, l, output)
                    engine.write_poses.assert_not_called()
                    self.assertFalse(output.exists())

    def test_cli_help_and_invalid_arguments_need_no_optional_dependency(self):
        for args, expected in ((["--help"], 0), ([], 2)):
            with self.subTest(args=args):
                run = subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True, timeout=10)
                self.assertEqual(run.returncode, expected)
                self.assertNotIn("Traceback", run.stderr)
                if args:
                    self.assertIn("--validate-only", run.stdout)
                    self.assertIn("NO docking execution", run.stdout)


class PoseValidationTests(unittest.TestCase):
    """Synthetic corrupt-backend refusal, never evidence of native execution."""

    SECOND_ATOM = ATOM[:6] + "    2" + ATOM[11:12] + " C2 " + ATOM[16:]
    SCORE = "REMARK VINA RESULT: -1.000 0.000 0.000\n"

    @classmethod
    def model(cls, number=1, atoms=None, score=None):
        if atoms is None:
            atoms = ATOM + cls.SECOND_ATOM
        if score is None:
            score = cls.SCORE
        return f"MODEL {number}\n{score}ROOT\n{atoms}ENDROOT\nTORSDOF 0\nENDMDL\n"

    def run_pose(self, content, energies=None, accepted=False):
        helper = load_helper()
        if energies is None:
            energies = [[-1.0, 0.0, 0.0, 0.0, 0.0]] * 2
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receptor, ligand = PrerequisiteTests.inputs(root)
            ligand.write_text("ROOT\n" + ATOM + self.SECOND_ATOM + "ENDROOT\nTORSDOF 0\n")
            output = root / "result"
            engine = MagicMock()
            engine.energies.return_value.tolist.return_value = energies
            engine.info.return_value = {}
            engine.write_poses.side_effect = lambda path, **kwargs: Path(path).write_text(content)
            backend = SimpleNamespace(Vina=MagicMock(return_value=engine), __version__="pose-validation-fixture")
            argv = PrerequisiteTests.argv(receptor, ligand, output) + ["--n-poses", "2"]
            with patch_modules({"vina": backend}), contextlib.redirect_stderr(io.StringIO()) as stderr:
                code = helper.main(argv)
            self.assertEqual(code, 0 if accepted else 2, stderr.getvalue())
            self.assertEqual((output / "manifest.json").exists(), accepted)
            self.assertEqual((output / "scores.json").exists(), accepted)
            if accepted:
                scores = json.loads((output / "scores.json").read_text())
                self.assertEqual(scores["pose_totals"], [row[0] for row in energies])
            engine.dock.assert_called_once()
            engine.optimize.assert_not_called()

    def test_every_output_coordinate_is_finite_fixed_column(self):
        for model_number in (1, 2):
            for offset in (30, 38, 46):
                for value in ("nan", "inf", "-inf", "invalid", ""):
                    with self.subTest(model=model_number, coordinate=offset, value=value):
                        bad_atom = self.SECOND_ATOM[:offset] + f"{value:>8}" + self.SECOND_ATOM[offset + 8:]
                        models = [self.model(1), self.model(2)]
                        models[model_number - 1] = self.model(model_number, ATOM + bad_atom)
                        self.run_pose("".join(models))

    def test_every_model_has_atoms(self):
        self.run_pose(self.model(1) + self.model(2, atoms=""))

    def test_exactly_one_score_is_required_inside_each_model(self):
        cases = {
            "missing_second": self.model(1) + self.model(2, score=""),
            "duplicate_first_missing_second": self.model(1, score=self.SCORE * 2) + self.model(2, score=""),
            "before_first": self.SCORE + self.model(1, score="") + self.model(2),
            "between_models": self.model(1) + self.SCORE + self.model(2, score=""),
            "after_last": self.model(1) + self.model(2, score="") + self.SCORE,
            "duplicate_second": self.model(1) + self.model(2, score=self.SCORE * 2),
        }
        for name, content in cases.items():
            with self.subTest(case=name):
                self.run_pose(content)

    def test_malformed_additional_score_records_are_not_ignored(self):
        for malformed in (
            "REMARK VINA RESULT -1 0 0\n",
            "REMARK VINA RESULT:-1 0 0\n",
        ):
            with self.subTest(score=malformed):
                self.run_pose(self.model(1) + self.model(2, score=self.SCORE + malformed))

    def test_all_score_fields_must_be_valid_finite_numbers(self):
        for score in (
            "REMARK VINA RESULT:\n", "REMARK VINA RESULT: -1 0\n",
            "REMARK VINA RESULT: -1 0 0 extra\n", "REMARK VINA RESULT: nan 0 0\n",
            "REMARK VINA RESULT: -1 nan 0\n", "REMARK VINA RESULT: -1 0 inf\n",
            "REMARK VINA RESULT: -1 bad 0\n", "REMARK VINA RESULT: -1 -1 0\n",
        ):
            with self.subTest(score=score):
                self.run_pose(self.model(1) + self.model(2, score=score))

    def test_models_are_balanced_nonnested_sequential_records(self):
        first, second = self.model(1), self.model(2)
        cases = {
            "nested": first.replace("ENDMDL\n", "") + second + "ENDMDL\n",
            "end_before_model": "ENDMDL\n" + first + second.removesuffix("ENDMDL\n"),
            "unclosed": first + second.removesuffix("ENDMDL\n"),
            "extra_end": first + second + "ENDMDL\n",
            "duplicate_id": first + self.model(1),
            "invalid_id": first + second.replace("MODEL 2", "MODEL nope"),
            "model_extra_field": first + second.replace("MODEL 2", "MODEL 2 extra"),
            "end_extra_field": first + second.replace("ENDMDL", "ENDMDL extra"),
            "atom_outside": ATOM + first + second,
        }
        for name, content in cases.items():
            with self.subTest(case=name):
                self.run_pose(content)

    def test_model_atom_identities_and_counts_match_ligand(self):
        extra_atom = self.SECOND_ATOM[:6] + "    3" + self.SECOND_ATOM[11:]
        for name, atoms in {
            "missing_atom": ATOM,
            "extra_atom": ATOM + self.SECOND_ATOM + extra_atom,
            "duplicate_id": ATOM + ATOM,
            "wrong_id_same_count": ATOM + extra_atom,
            "wrong_name": ATOM + self.SECOND_ATOM.replace(" C2 ", " X2 "),
            "wrong_residue": ATOM + self.SECOND_ATOM.replace("LIG", "BAD"),
            "wrong_type": ATOM + self.SECOND_ATOM.replace("0.038 A", "0.038 C"),
            "wrong_charge": ATOM + self.SECOND_ATOM.replace("0.038 A", "0.039 A"),
            "truncated_record": ATOM + self.SECOND_ATOM[:54] + "\n",
        }.items():
            with self.subTest(case=name):
                self.run_pose(self.model(1) + self.model(2, atoms=atoms))

    def test_scores_match_backend_rows_in_model_order_with_absolute_tolerance(self):
        for name, energies, second_score in (
            ("wrong_second", [[-1.0] * 5, [-2.0] * 5], self.SCORE),
            ("wrong_count", [[-1.0] * 5], self.SCORE),
            ("relative_tolerance_not_allowed", [[-1.0] * 5, [-1000000.0] * 5],
             "REMARK VINA RESULT: -1000000.0015 0 0\n"),
        ):
            with self.subTest(case=name):
                self.run_pose(self.model(1) + self.model(2, score=second_score), energies)

    def test_valid_multiple_models_and_fewer_than_requested_are_retained(self):
        self.run_pose(self.model(1) + self.model(2), accepted=True)
        self.run_pose(self.model(1), energies=[[-1.0] * 5], accepted=True)
        self.run_pose(self.model(1) + self.model(2, atoms=self.SECOND_ATOM + ATOM), accepted=True)
        self.run_pose(self.model(1) + self.model(2, score="REMARK VINA RESULT: -2.000 0 0\n"),
                      energies=[[-1.0] * 5, [-2.0] * 5], accepted=True)


@unittest.skipUnless(os.environ.get("VINA_TEST_INPUT_DIR"), "explicit optional native Vina integration")
class NativeDockingTests(unittest.TestCase):
    def test_real_dock_outputs_engine_poses_scores_and_replay(self):
        inputs = Path(os.environ["VINA_TEST_INPUT_DIR"])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "native"
            argv = PrerequisiteTests.argv(inputs / "1iep_receptor.pdbqt", inputs / "1iep_ligand.pdbqt", output)
            run = subprocess.run([sys.executable, "-I", str(SCRIPT), *argv], capture_output=True, text=True, timeout=180)
            self.assertEqual(run.returncode, 0, run.stderr)
            manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(manifest["execution_status"], "observed")
            self.assertFalse(manifest["tooluniverse_execution"])
            self.assertEqual(manifest["backend_version"], "1.2.7")
            self.assertEqual(manifest["platform"], platform.platform())
            self.assertEqual(manifest["settings"]["seed"], 20261022)
            self.assertEqual(manifest["settings"]["cpu"], 1)
            self.assertIn("--output-dir", manifest["replay_argv"])
            scores = json.loads((output / "scores.json").read_text())
            self.assertEqual(scores["units"], "kcal/mol")
            self.assertTrue(all(math.isfinite(n) for row in scores["energies"] for n in row))
            pose = (output / "poses.pdbqt").read_text()
            self.assertIn("ENDMDL", pose)
            self.assertIn("ATOM", pose)
            pose_score = float(next(line.split()[3] for line in pose.splitlines() if line.startswith("REMARK VINA RESULT:")))
            self.assertAlmostEqual(pose_score, scores["energies"][0][0], places=3)
            for name, record in manifest["outputs"].items():
                self.assertEqual(record["sha256"], hashlib.sha256((output / name).read_bytes()).hexdigest())
            # Same command cannot overwrite even an existing successful result.
            before = (output / "poses.pdbqt").read_bytes()
            repeat = subprocess.run([sys.executable, "-I", str(SCRIPT), *argv], capture_output=True, text=True, timeout=10)
            self.assertEqual(repeat.returncode, 2)
            self.assertEqual((output / "poses.pdbqt").read_bytes(), before)


class DefinitionTests(unittest.TestCase):
    def test_definition_and_closed_support_exports_are_honest(self):
        from omh.skills import molecular_docking_skill as skill
        self.assertEqual(skill.DEFINITION.name, "molecular-docking")
        self.assertIs(skill.molecular_docking_definition(), skill.DEFINITION)
        self.assertEqual(skill.DEFINITION.artifact_contracts, ())
        self.assertTrue(skill.DEFINITION.progressive_disclosure)
        self.assertIn("actual docking", skill.DEFINITION.handoff_policy)
        self.assertIn("standalone Vina", skill.DEFINITION.description)
        self.assertEqual(len(skill.TOOLKIT_RESOURCES), len(set(skill.TOOLKIT_RESOURCES)))
        templates = skill.molecular_docking_support_templates()
        self.assertEqual({t.relative_path for t in templates}, {"toolkit/" + p for p in skill.TOOLKIT_RESOURCES})
        self.assertTrue(all(t.skill_name == "molecular-docking" for t in templates))
        manifest = json.loads(next(t.content for t in templates if t.relative_path.endswith("upstream-manifest.json")))
        self.assertEqual(manifest["runtime_status"], "observed_native_smoke")
        for template in templates:
            relative = template.relative_path.removeprefix("toolkit/")
            if relative != "upstream-manifest.json":
                self.assertEqual(manifest["files"][relative]["local_sha256"], hashlib.sha256(template.content.encode()).hexdigest())
        references = skill.molecular_docking_reference_templates()
        self.assertEqual([r.relative_path for r in references], ["references/execution-and-qa.md"])
        input_refs = set(skill.DEFINITION.required_inputs)
        output_refs = set(skill.DEFINITION.expected_outputs)
        check_ids = {c.check_id for c in skill.DEFINITION.procedure_checks}
        for step in skill.DEFINITION.procedure_steps:
            self.assertLessEqual(set(step.input_refs), input_refs)
            self.assertLessEqual(set(step.output_refs), output_refs)
            self.assertLessEqual(set(step.check_ids), check_ids)

    def test_support_rejects_hash_and_inventory_tampering(self):
        from omh.skills import molecular_docking_skill as skill
        texts = skill._resource_texts()
        tampered = dict(texts, **{"scripts/dock.py": texts["scripts/dock.py"] + "# tampered\n"})
        with patch.object(skill, "_resource_texts", return_value=tampered), self.assertRaises(ValueError):
            skill.molecular_docking_support_templates()
        manifest = json.loads(texts["upstream-manifest.json"])
        manifest["files"]["../foreign.py"] = {}
        with patch.object(skill, "_resource_texts", return_value=dict(texts, **{"upstream-manifest.json": json.dumps(manifest)})), self.assertRaises(ValueError):
            skill.molecular_docking_support_templates()

    def test_factories_never_import_helper_or_optional_science(self):
        import builtins
        from omh.skills import molecular_docking_skill as skill
        original = builtins.__import__
        def guarded(name, *args, **kwargs):
            self.assertNotIn(name.split(".")[0], ("vina", "numpy", "tooluniverse", "subprocess", "socket"))
            self.assertNotIn("molecular_docking_toolkit", name)
            return original(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=guarded):
            skill.molecular_docking_definition()
            skill.molecular_docking_reference_templates()
            skill.molecular_docking_support_templates()
        toolkit = SCRIPT.parents[1]
        actual = {p.relative_to(toolkit).as_posix() for p in toolkit.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
        self.assertEqual(actual, set(skill.TOOLKIT_RESOURCES))


if __name__ == "__main__":
    unittest.main()

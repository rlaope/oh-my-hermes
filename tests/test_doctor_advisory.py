from __future__ import annotations

import argparse
import io
import json
import os
import tempfile
import dataclasses
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from omh.maintenance import advisory
from omh.maintenance.advisory import (
    AdviceEntry,
    APPROX_TOKENS_PER_SKILL,
    CONTRACT,
    MEMORY_STALE_AFTER_DAYS,
    check_auxiliary_routing_unset,
    check_hermes_memory_staleness,
    check_installed_skill_context_weight,
    check_legacy_plan_artifacts,
    check_orphaned_project_scope_store,
    check_soul_missing_or_starter,
    check_workflow_engine_reach,
    run_config_advisories,
)
from omh.maintenance.doctor import Check, doctor_ok, recommended_next_action, run_doctor, run_doctor_advisories
from omh.commands import setup as setup_commands
from omh.installer import install_skill_pack
from omh.manifest import read_manifest, write_manifest
from omh.paths import resolve_paths
from omh.skill_pack import CORE_PROFILE_SKILLS
from omh.skills.catalog import omh_skill_install_path, ulw_inventory_payload

ADVISORY_CHECK_IDS = {
    "model_routing_readiness",
    "auxiliary_routing_unset",
    "soul_missing_or_starter",
    "hermes_memory_staleness",
    "legacy_plan_artifacts",
    "orphaned_project_scope_store",
    "installed_skill_context_weight",
    "workflow_engine_reach",
}

ALL_AUTO_AUXILIARY = """version: 1
auxiliary:
  vision:
    provider: auto
    model:
  compression:
    provider: auto
    model:
  web_extract:
    provider: auto
    model:
  approval_scoring:
    provider: auto
    model:
  skills_hub_lookup:
    provider: auto
    model:
  mcp_routing:
    provider: auto
    model:
  triage_specifier:
    provider: auto
    model:
  kanban_decomposer:
    provider: auto
    model:
  profile_describer:
    provider: auto
    model:
  curator:
    provider: auto
    model:
  title:
    provider: auto
    model:
"""

ONE_PINNED_AUXILIARY = ALL_AUTO_AUXILIARY.replace(
    "  vision:\n    provider: auto\n    model:\n",
    "  vision:\n    provider: openai\n    model: gpt-4o\n",
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class AuxiliaryRoutingTests(unittest.TestCase):
    def _home(self, config_text: str | None) -> Path:
        home = Path(tempfile.mkdtemp())
        if config_text is not None:
            _write(home / "config.yaml", config_text)
        return home

    def test_all_auto_is_advice(self) -> None:
        entry = check_auxiliary_routing_unset(self._home(ALL_AUTO_AUXILIARY))
        self.assertEqual(entry.status, "advice")
        self.assertTrue(entry.read_only)
        self.assertIn("11 observed", entry.observed)

    def test_one_pinned_model_is_ok(self) -> None:
        entry = check_auxiliary_routing_unset(self._home(ONE_PINNED_AUXILIARY))
        self.assertEqual(entry.status, "ok")

    def test_missing_config_is_unobserved(self) -> None:
        entry = check_auxiliary_routing_unset(self._home(None))
        self.assertEqual(entry.status, "unobserved")

    def test_inline_scalar_is_unobserved(self) -> None:
        entry = check_auxiliary_routing_unset(self._home("auxiliary: something\n"))
        self.assertEqual(entry.status, "unobserved")

    def test_list_shape_is_unobserved(self) -> None:
        entry = check_auxiliary_routing_unset(self._home("auxiliary:\n  - a\n  - b\n"))
        self.assertEqual(entry.status, "unobserved")

    def test_truncated_block_is_unobserved(self) -> None:
        entry = check_auxiliary_routing_unset(self._home("auxiliary:\n  vision:\n"))
        self.assertEqual(entry.status, "unobserved")

    def test_tab_indentation_is_unobserved(self) -> None:
        entry = check_auxiliary_routing_unset(self._home("auxiliary:\n\tvision:\n\t\tprovider: auto\n"))
        self.assertEqual(entry.status, "unobserved")

    def test_never_raises_on_garbage(self) -> None:
        for text in (":::\n", "auxiliary:\n   \tmixed\n", "\x00\x01auxiliary:\n", ""):
            with self.subTest(text=text):
                entry = check_auxiliary_routing_unset(self._home(text))
                self.assertIn(entry.status, {"advice", "ok", "unobserved"})


class SoulTests(unittest.TestCase):
    def _home(self, soul: str | None) -> Path:
        home = Path(tempfile.mkdtemp())
        if soul is not None:
            _write(home / "SOUL.md", soul)
        return home

    def test_missing_soul_is_advice(self) -> None:
        self.assertEqual(check_soul_missing_or_starter(self._home(None)).status, "advice")

    def test_empty_soul_is_advice(self) -> None:
        self.assertEqual(check_soul_missing_or_starter(self._home("   \n")).status, "advice")

    def test_starter_soul_is_advice(self) -> None:
        starter = "# SOUL\n\nTODO: define your agent's soul here (placeholder).\n"
        self.assertEqual(check_soul_missing_or_starter(self._home(starter)).status, "advice")

    def test_custom_soul_is_ok(self) -> None:
        custom = (
            "# Ada\n\nAda is a meticulous release engineer who prizes reproducible "
            "builds, writes terse changelogs, distrusts flaky tests, and always "
            "double-checks the rollback plan before shipping anything to prod.\n"
        )
        self.assertEqual(check_soul_missing_or_starter(self._home(custom)).status, "ok")


class MemoryTests(unittest.TestCase):
    def _home(self) -> Path:
        return Path(tempfile.mkdtemp())

    def test_missing_memories_is_unobserved(self) -> None:
        self.assertEqual(check_hermes_memory_staleness(self._home()).status, "unobserved")

    def test_fresh_memory_is_ok(self) -> None:
        home = self._home()
        _write(home / "memories" / "MEMORY.md", "recent notes")
        self.assertEqual(check_hermes_memory_staleness(home).status, "ok")

    def test_stale_memory_is_advice(self) -> None:
        home = self._home()
        memory = home / "memories" / "MEMORY.md"
        _write(memory, "old notes")
        old = advisory._now_seconds() - (MEMORY_STALE_AFTER_DAYS + 5) * 86400
        os.utime(memory, (old, old))
        self.assertEqual(check_hermes_memory_staleness(home).status, "advice")


class LegacyPlanArtifactTests(unittest.TestCase):
    """Plans written by the pre-relocation writer are unread; say so out loud.

    Nothing reads `~/.hermes/plans` any more. Staying silent about files that
    are already on disk is how a user concludes their plans vanished.
    """

    def _home(self) -> Path:
        return Path(tempfile.mkdtemp())

    def test_no_legacy_directories_is_ok(self) -> None:
        self.assertEqual(check_legacy_plan_artifacts(self._home()).status, "ok")

    def test_an_empty_legacy_directory_is_ok(self) -> None:
        home = self._home()
        (home / "plans").mkdir(parents=True)
        self.assertEqual(check_legacy_plan_artifacts(home).status, "ok")

    def test_leftover_plans_are_reported_with_a_count(self) -> None:
        home = self._home()
        _write(home / "plans" / "2026-01-01T000000Z-old-plan-abc123.md", "# old\n")
        _write(home / "plans" / "2026-01-02T000000Z-other-plan-def456.md", "# old\n")
        entry = check_legacy_plan_artifacts(home)
        self.assertEqual(entry.status, "advice")
        self.assertIn("2 file(s) in plans", entry.observed)

    def test_blocked_plan_context_is_counted_too(self) -> None:
        home = self._home()
        _write(home / "context" / "2026-01-01T000000Z-old-context-abc123.md", "# old\n")
        entry = check_legacy_plan_artifacts(home)
        self.assertEqual(entry.status, "advice")
        self.assertIn("1 file(s) in context", entry.observed)

    def test_the_remedy_never_offers_to_move_or_delete_them(self) -> None:
        home = self._home()
        _write(home / "plans" / "old.md", "# old\n")
        entry = check_legacy_plan_artifacts(home)
        # OMH reports on Hermes' home and does not write to it.
        self.assertIn("OMH will not touch them", entry.remediation)
        self.assertTrue(entry.read_only)
        self.assertTrue((home / "plans" / "old.md").exists())


class OrphanedProjectScopeStoreTests(unittest.TestCase):
    """`--scope project` moved its anchor to the repository root in #676.

    A store installed from a subdirectory before that is now unreachable. This
    check is the exact inverse of the change, so it must fire for that case and
    stay quiet for every other shape.
    """

    def _repo(self, root: Path) -> Path:
        (root / ".git").mkdir(parents=True)
        return root

    def test_a_store_below_the_root_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(Path(tmp).resolve())
            nested = root / "nested" / "deep"
            _write(nested / ".omh" / "manifest.json", "{}")
            entry = check_orphaned_project_scope_store(cwd=nested)
            self.assertEqual(entry.status, "advice")
            self.assertIn(str(nested), entry.observed)

    def test_a_store_at_the_root_is_not_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(Path(tmp).resolve())
            _write(root / ".omh" / "manifest.json", "{}")
            # The root store is the supported location, not an orphan.
            self.assertEqual(check_orphaned_project_scope_store(cwd=root).status, "ok")

    def test_a_subdirectory_without_a_store_is_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(Path(tmp).resolve())
            nested = root / "nested"
            nested.mkdir()
            self.assertEqual(check_orphaned_project_scope_store(cwd=nested).status, "ok")

    def test_an_omh_directory_without_a_manifest_is_not_an_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(Path(tmp).resolve())
            nested = root / "nested"
            # A plans/codegraph store is not a `--scope project` install, and
            # reporting one would fire on every repository that records a plan.
            _write(nested / ".omh" / "plans" / "some-plan.md", "# plan\n")
            self.assertEqual(check_orphaned_project_scope_store(cwd=nested).status, "ok")

    def test_outside_a_repository_there_is_nothing_to_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp).resolve()
            with mock.patch("omh.maintenance.advisory.find_project_root", return_value=None):
                self.assertEqual(check_orphaned_project_scope_store(cwd=plain).status, "ok")

    def test_the_remedy_never_offers_to_move_the_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(Path(tmp).resolve())
            nested = root / "nested"
            manifest = nested / ".omh" / "manifest.json"
            _write(manifest, "{}")
            entry = check_orphaned_project_scope_store(cwd=nested)
            self.assertIn("OMH will not move it", entry.remediation)
            self.assertTrue(entry.read_only)
            self.assertTrue(manifest.exists())


class SkillWeightTests(unittest.TestCase):
    def _skills_dir(self, count: int) -> Path:
        skills_dir = Path(tempfile.mkdtemp()) / "skills"
        skills_dir.mkdir(parents=True)
        for i in range(count):
            _write(skills_dir / f"skill_{i}" / "SKILL.md", f"# skill {i}\n")
        # Decoys that must not be counted.
        (skills_dir / "not_a_skill").mkdir()
        _write(skills_dir / "not_a_skill" / "README.md", "no skill file")
        return skills_dir

    def test_skill_weight_math(self) -> None:
        skills_dir = self._skills_dir(3)
        entry = check_installed_skill_context_weight(
            Path(tempfile.mkdtemp()), skills_dirs=[skills_dir]
        )
        self.assertEqual(entry.status, "advice")
        self.assertIn("3 installed OMH skill(s)", entry.observed)
        self.assertIn(f"{3 * APPROX_TOKENS_PER_SKILL} tokens", entry.observed)

    def test_config_derived_skill_count(self) -> None:
        skills_dir = self._skills_dir(2)
        home = Path(tempfile.mkdtemp())
        _write(
            home / "config.yaml",
            f"skills:\n  external_dirs:\n    - {skills_dir}\n",
        )
        entry = check_installed_skill_context_weight(home)
        self.assertEqual(entry.status, "advice")
        self.assertIn("2 installed OMH skill(s)", entry.observed)

    def test_no_skill_dir_is_unobserved(self) -> None:
        entry = check_installed_skill_context_weight(Path(tempfile.mkdtemp()))
        self.assertEqual(entry.status, "unobserved")


class ContractShapeTests(unittest.TestCase):
    def test_contract_and_entry_shape(self) -> None:
        report = run_config_advisories(Path(tempfile.mkdtemp()))
        self.assertEqual(report.contract, CONTRACT)
        self.assertEqual(CONTRACT, "hermes_config_advice/v1")
        data = report.to_dict()
        self.assertEqual(data["contract"], CONTRACT)
        self.assertEqual(len(data["entries"]), len(ADVISORY_CHECK_IDS))
        for entry in data["entries"]:
            self.assertEqual(
                set(entry.keys()),
                {"check_id", "status", "read_only", "remediation", "evidence_boundary", "observed"},
            )
            self.assertTrue(entry["read_only"])
            self.assertIn(entry["status"], {"advice", "ok", "unobserved"})
        self.assertEqual(
            {entry["check_id"] for entry in data["entries"]}, ADVISORY_CHECK_IDS
        )


class GoldenStringTests(unittest.TestCase):
    def _all_remediation(self) -> str:
        report = run_config_advisories(Path(tempfile.mkdtemp()))
        return "\n".join(entry.remediation for entry in report.entries)

    def test_verified_commands_present(self) -> None:
        text = self._all_remediation()
        self.assertIn("hermes skills config", text)
        self.assertIn("hermes skills opt-out", text)
        self.assertIn("threshold_pct 10", text)

    def test_forbidden_disable_command_absent(self) -> None:
        report = run_config_advisories(Path(tempfile.mkdtemp()))
        for entry in report.entries:
            self.assertNotIn("hermes skills disable", entry.remediation)
            self.assertNotIn("hermes skills disable", entry.observed)
            self.assertNotIn("hermes skills disable", entry.evidence_boundary)

    def test_auxiliary_facts_present(self) -> None:
        entry = check_auxiliary_routing_unset(Path(tempfile.mkdtemp()))
        for slot in ("vision", "compression", "curator", "title"):
            self.assertIn(slot, entry.remediation)
        self.assertIn("11", entry.remediation)

    def test_soul_and_memory_boundary_copy(self) -> None:
        report = run_config_advisories(Path(tempfile.mkdtemp()))
        by_id = {entry.check_id: entry for entry in report.entries}
        self.assertIn("system-prompt slot #1", by_id["soul_missing_or_starter"].remediation)
        self.assertIn(
            "OMH reports only and cannot change Hermes memory",
            by_id["hermes_memory_staleness"].remediation,
        )


class MembershipGuardrailTests(unittest.TestCase):
    def _all_firing_home(self) -> tuple[Path, Path]:
        root = Path(tempfile.mkdtemp())
        omh_home = root / ".omh"
        hermes_home = root / ".hermes"
        skills_dir = omh_home / "skills"
        _write(skills_dir / "alpha" / "SKILL.md", "# alpha\n")
        _write(skills_dir / "beta" / "SKILL.md", "# beta\n")
        _write(
            hermes_home / "config.yaml",
            ALL_AUTO_AUXILIARY + f"skills:\n  external_dirs:\n    - {skills_dir}\n",
        )
        # SOUL intentionally missing -> advice.
        memory = hermes_home / "memories" / "MEMORY.md"
        _write(memory, "stale memory")
        old = advisory._now_seconds() - (MEMORY_STALE_AFTER_DAYS + 5) * 86400
        os.utime(memory, (old, old))
        return omh_home, hermes_home

    def test_all_advisories_fire_and_stay_out_of_checks(self) -> None:
        omh_home, hermes_home = self._all_firing_home()
        paths = resolve_paths(omh_home, hermes_home)

        report = run_doctor_advisories(paths)
        statuses = {entry.check_id: entry.status for entry in report.entries}
        self.assertEqual(
            statuses,
            {
                "model_routing_readiness": "advice",
                "auxiliary_routing_unset": "advice",
                "soul_missing_or_starter": "advice",
                "hermes_memory_staleness": "advice",
                # The fixture home has no leftover ~/.hermes/plans, so this one
                # reports ok rather than advice; the firing case is covered in
                # LegacyPlanArtifactTests.
                "legacy_plan_artifacts": "ok",
                # No subdirectory store below a repository root in the fixture home.
                "orphaned_project_scope_store": "ok",
                "installed_skill_context_weight": "advice",
                # The fixture home has no install manifest, so reach cannot be
                # measured; the firing case is covered in
                # WorkflowEngineReachTests.
                "workflow_engine_reach": "unobserved",
            },
        )

        checks = run_doctor(paths)
        # Membership guardrail: no advisory objects leak into the doctor check list.
        for check in checks:
            self.assertIsInstance(check, Check)
            self.assertNotIsInstance(check, AdviceEntry)
        self.assertTrue(ADVISORY_CHECK_IDS.isdisjoint({check.name for check in checks}))

        # doctor_ok() and recommended_next_action() operate only on Checks.
        ok_with = doctor_ok(checks)
        self.assertEqual(ok_with, doctor_ok([c for c in checks]))
        self.assertIsInstance(recommended_next_action(checks), str)


class WorkflowEngineReachTests(unittest.TestCase):
    """#1635: a core install cannot reach the ULW workflow engines, and now says so.

    `install_skill_pack` ADDS only what the recorded profile names and
    otherwise refreshes what is on disk, so on a core install a full-only skill
    is in neither set and no number of `omh update` runs will ever add one.
    That rule is deliberate and stays. What was missing is the consequence: a
    user invokes a workflow engine, finds nothing, and no surface names the
    command that would install it.

    The advisory lane is the home for it because core is a legitimate,
    deliberately recommended profile -- a fact with a consequence, not a health
    failure -- so it must not move the doctor status or exit code, which
    `ExitCodeParityTests` already pins for the lane as a whole.
    """

    def _engines(self) -> list[dict]:
        return list(ulw_inventory_payload()["canonical_engines"])

    def _entry(self, paths):
        return check_workflow_engine_reach(paths.hermes_home, omh_home=paths.omh_home)

    def test_no_workflow_engine_is_in_the_core_profile(self) -> None:
        """The premise, computed: this is why the entry has to exist at all."""
        core = set(CORE_PROFILE_SKILLS)
        reachable = sorted(
            str(engine["canonical"]) for engine in self._engines() if str(engine["canonical"]) in core
        )
        self.assertEqual(reachable, [])

    def test_a_core_install_is_told_what_it_cannot_reach_and_which_command_adds_it(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="core")

            entry = self._entry(paths)
            self.assertEqual(entry.status, "advice")
            for engine in self._engines():
                self.assertIn(str(engine["display_name"]), entry.observed)
            self.assertIn("core", entry.observed)
            self.assertIn("omh update --full", entry.remediation)

            # The reason this needs saying rather than merely recording: the
            # update the operator would reach for adds none of them.
            install_skill_pack(paths, profile="core")
            self.assertEqual(self._entry(paths).observed, entry.observed)

    def test_a_full_install_is_not_told_to_run_full(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="full")

            entry = self._entry(paths)
            self.assertEqual(entry.status, "ok")
            self.assertNotIn("--full", entry.remediation)

    def test_an_install_holding_every_engine_is_silent_whatever_it_recorded(self) -> None:
        """Derived from what is absent, never from the profile label.

        A `full` install whose manifest was later rewritten to `core` is the
        real `retained_exception` state -- installs never delete -- and it has
        every engine, so there is nothing to say.
        """
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="full")
            manifest = read_manifest(paths.manifest_path)
            manifest["skill_profile"] = "core"
            write_manifest(paths.manifest_path, manifest)

            entry = self._entry(paths)
            self.assertEqual(entry.status, "ok")
            self.assertIn("core", entry.observed)

    def test_an_engine_present_on_a_core_install_is_not_named(self) -> None:
        """The per-engine half: `ultrawork` is the engine the reports named."""
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            install_skill_pack(paths, profile="core")
            present = next(
                engine for engine in self._engines() if str(engine["canonical"]) == "ultrawork"
            )
            _write(
                paths.skills_dir / omh_skill_install_path(str(present["canonical"])) / "SKILL.md",
                "# placed by hand\n",
            )

            entry = self._entry(paths)
            self.assertEqual(entry.status, "advice")
            self.assertNotIn(str(present["display_name"]), entry.observed)
            for engine in self._engines():
                if str(engine["canonical"]) == str(present["canonical"]):
                    continue
                self.assertIn(str(engine["display_name"]), entry.observed)

    def test_a_home_with_no_install_is_unobserved_rather_than_advice(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            self.assertEqual(self._entry(paths).status, "unobserved")


class NoWriteTests(unittest.TestCase):
    def test_zero_writes_to_hermes_home(self) -> None:
        home = Path(tempfile.mkdtemp())
        _write(home / "config.yaml", ALL_AUTO_AUXILIARY)
        _write(home / "SOUL.md", "# real soul with substantive persona content here.\n" * 5)
        _write(home / "memories" / "MEMORY.md", "memory")
        _write(home / "memories" / "USER.md", "user")

        before = {
            str(p): (p.stat().st_mtime_ns, p.stat().st_size)
            for p in home.rglob("*")
            if p.is_file()
        }
        run_config_advisories(home)
        after = {
            str(p): (p.stat().st_mtime_ns, p.stat().st_size)
            for p in home.rglob("*")
            if p.is_file()
        }
        self.assertEqual(before, after)


class ExitCodeParityTests(unittest.TestCase):
    def _args(self, omh_home: Path, hermes_home: Path, *, json: bool) -> argparse.Namespace:
        return argparse.Namespace(
            omh_home=str(omh_home),
            hermes_home=str(hermes_home),
            scope=None,
            json=json,
            language="en",
        )

    def test_exit_code_matches_doctor_ok_regardless_of_advice(self) -> None:
        root = Path(tempfile.mkdtemp())
        omh_home = root / ".omh"
        hermes_home = root / ".hermes"
        _write(hermes_home / "config.yaml", ALL_AUTO_AUXILIARY)  # triggers advice

        paths = resolve_paths(omh_home, hermes_home)
        expected = 0 if doctor_ok(run_doctor(paths)) else 1

        args = self._args(omh_home, hermes_home, json=True)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = setup_commands.cmd_doctor(args)
        self.assertEqual(code, expected)

        # The advice section renders but does not change ok / exit code.
        payload = setup_commands._doctor_result(args)
        self.assertEqual(payload["ok"], doctor_ok(run_doctor(paths)))
        self.assertEqual(payload["advisories"]["contract"], CONTRACT)

    def test_advisory_only_model_gap_keeps_doctor_exit_zero(self) -> None:
        root = Path(tempfile.mkdtemp())
        omh_home = root / ".omh"
        hermes_home = root / ".hermes"
        args = self._args(omh_home, hermes_home, json=True)
        with mock.patch(
            "omh.commands.setup.run_doctor",
            return_value=[Check("base", True, "healthy")],
        ):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                code = setup_commands.cmd_doctor(args)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        model_advice = next(
            entry
            for entry in payload["advisories"]["entries"]
            if entry["check_id"] == "model_routing_readiness"
        )
        self.assertEqual(model_advice["status"], "advice")

    def test_advice_section_renders_in_text_output(self) -> None:
        root = Path(tempfile.mkdtemp())
        omh_home = root / ".omh"
        hermes_home = root / ".hermes"
        _write(hermes_home / "config.yaml", ALL_AUTO_AUXILIARY)

        args = self._args(omh_home, hermes_home, json=False)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            setup_commands.cmd_doctor(args)
        output = buffer.getvalue()
        self.assertIn("Advice", output)
        self.assertIn("auxiliary_routing_unset", output)


class PlacementTests(unittest.TestCase):
    def test_config_adapter_has_no_auxiliary_symbol(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "install"
            / "config_adapter.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("auxiliary", source.lower())


if __name__ == "__main__":
    unittest.main()


class RegistrationThroughCurrentPointerTests(unittest.TestCase):
    def test_doctor_accepts_a_pack_registered_under_the_current_pointer(self) -> None:
        # The staged-update layout: config.yaml names `current/skills`, the
        # command running doctor resolves its own generation.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            generation = root / "generations" / "g1"
            (generation / "skills").mkdir(parents=True)
            os.symlink(generation, root / "current", target_is_directory=True)
            hermes_home = root / ".hermes"
            hermes_home.mkdir()
            (hermes_home / "config.yaml").write_text(
                f"skills:\n  external_dirs:\n    - {(root / 'current' / 'skills').as_posix()}\n", encoding="utf-8"
            )
            paths = dataclasses.replace(
                resolve_paths(root / ".omh", hermes_home), managed_skills_dir=generation / "skills"
            )
            by_name = {check.name: check for check in run_doctor(paths)}
            self.assertTrue(by_name["external_dir"].ok, by_name["external_dir"].message)
            self.assertTrue(by_name["runtime_context"].ok, by_name["runtime_context"].message)

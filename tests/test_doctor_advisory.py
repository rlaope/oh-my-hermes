from __future__ import annotations

import argparse
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from omh.maintenance import advisory
from omh.maintenance.advisory import (
    AdviceEntry,
    APPROX_TOKENS_PER_SKILL,
    CONTRACT,
    MEMORY_STALE_AFTER_DAYS,
    check_auxiliary_routing_unset,
    check_hermes_memory_staleness,
    check_installed_skill_context_weight,
    check_soul_missing_or_starter,
    run_config_advisories,
)
from omh.maintenance.doctor import Check, doctor_ok, recommended_next_action, run_doctor, run_doctor_advisories
from omh.commands import setup as setup_commands
from omh.paths import resolve_paths

ADVISORY_CHECK_IDS = {
    "auxiliary_routing_unset",
    "soul_missing_or_starter",
    "hermes_memory_staleness",
    "installed_skill_context_weight",
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
        self.assertEqual(len(data["entries"]), 4)
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

    def test_all_four_fire_and_stay_out_of_checks(self) -> None:
        omh_home, hermes_home = self._all_firing_home()
        paths = resolve_paths(omh_home, hermes_home)

        report = run_doctor_advisories(paths)
        statuses = {entry.check_id: entry.status for entry in report.entries}
        self.assertEqual(
            statuses,
            {
                "auxiliary_routing_unset": "advice",
                "soul_missing_or_starter": "advice",
                "hermes_memory_staleness": "advice",
                "installed_skill_context_weight": "advice",
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

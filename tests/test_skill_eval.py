"""`omh skill-eval` and the `omh-skill-eval` skill: offline command, situation-first card, guarded routing."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from _local_package import load_local_package

load_local_package()

from omh.commands.main import build_parser  # noqa: E402
from omh.routing.localization import normalized_phrase  # noqa: E402
from omh.routing.policy import everyday_sense_phrase_unanchored  # noqa: E402
from omh.routing.skill_eval_cues import skill_eval_korean_match  # noqa: E402
from omh.skills.catalog import builtin_definitions  # noqa: E402
from omh.skills.packaging import builtin_skill_reference_templates, builtin_skill_templates  # noqa: E402

SKILL = "skill-eval"
REFERENCE_PATH = "references/with-without-eval.md"
SIBLINGS = ("skill-health", "skill-scout", "agent-evaluation", "doctor")


def _definition(name: str):
    return next(definition for definition in builtin_definitions() if definition.name == name)


def _reference() -> str:
    return next(
        template.content
        for template in builtin_skill_reference_templates()
        if template.skill_name == SKILL and template.relative_path == REFERENCE_PATH
    )


def _write_skill(folder: Path, name: str, description: str) -> Path:
    path = folder / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n", encoding="utf-8")
    return path


def _run(*argv: str) -> tuple[int, str]:
    args = build_parser().parse_args(["skill-eval", *argv])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = args.func(args)
    return code, out.getvalue()


class SkillEvalCommandTests(unittest.TestCase):
    def test_one_skill_prints_a_row_per_host_and_a_count_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = _write_skill(Path(tmp) / ".claude" / "skills", "pdf-tables", "Use when a PDF table must be read.")
            code, out = _run(str(skill), "--host", "hermes,claude-code")
        lines = out.splitlines()
        self.assertEqual(code, 0)
        self.assertTrue(lines[1].startswith("❌ hermes not_loaded — HERMES_ROOT"), lines[1])
        self.assertEqual(lines[2], "✅ claude-code loads")
        self.assertEqual(lines[-1], "2 hosts: 1 not_loaded, 0 degraded")

    def test_strict_exits_one_on_a_not_loaded_row_and_json_writes_the_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = _write_skill(Path(tmp) / ".claude" / "skills", "pdf-tables", "Use when a PDF table must be read.")
            target = Path(tmp) / "out.json"
            code, _ = _run(str(skill), "--host", "hermes", "--strict", "--json", str(target))
            payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(code, 1)
        self.assertEqual(payload["schema"], "omh_skill_eval/v1")
        self.assertEqual(payload["summary"]["not_loaded"], 1)

    def test_a_folder_without_skill_md_is_read_as_a_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pack"
            for name in ("alpha", "beta"):
                _write_skill(root, name, f"Use when {name} work comes up.")
            code, out = _run(str(root), "--host", "hermes")
        self.assertEqual(code, 0)
        self.assertIn("(catalog)", out.splitlines()[0])
        self.assertIn("roots: not checked; pass --install-root", out)
        self.assertTrue(out.splitlines()[-1].startswith("2 skills: 0 not_loaded and 0 degraded host rows"))

    def test_an_unknown_host_or_a_missing_folder_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill = _write_skill(Path(tmp), "alpha", "Use when alpha work comes up.")
            self.assertEqual(_run(str(skill), "--host", "nope")[0], 2)
            self.assertEqual(_run(str(Path(tmp) / "missing"))[0], 2)


class SkillEvalCatalogTests(unittest.TestCase):
    def test_the_situation_clause_fits_the_hermes_listing(self) -> None:
        situation = _definition(SKILL).description.split(":", 1)[0] + ":"
        self.assertLessEqual(len(situation), 51)

    def test_the_lift_reference_is_cost_zero_by_default_and_paired(self) -> None:
        text = _reference()
        for phrase in ("delegate_task", "cost 0", "approved that spend", "same prompt and model", "not measured"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)
        body = next(t.content for t in builtin_skill_templates() if t.name == SKILL)
        self.assertIn(REFERENCE_PATH, body)
        self.assertIn("omh skill-eval", body)

    def test_each_sibling_is_named_once_in_do_not_use_when(self) -> None:
        lines = _definition(SKILL).do_not_use_when
        for other in SIBLINGS:
            with self.subTest(other=other):
                self.assertEqual(len([line for line in lines if f"`{other}`" in line]), 1)


class SkillEvalRoutingGuardTests(unittest.TestCase):
    def test_a_persons_skill_is_kept_off_and_an_agent_skill_is_not(self) -> None:
        for message, unanchored in (
            ("is my skill any good at chess", True),
            ("my tennis skill evaluation", True),
            ("is my skill any good", False),
            ("check skill compatibility for codex", False),
        ):
            with self.subTest(message=message):
                self.assertEqual(everyday_sense_phrase_unanchored(SKILL, normalized_phrase(message)), unanchored)

    def test_korean_phrases_count_alone_or_beside_an_anchor(self) -> None:
        for message, matched in (
            ("스킬 평가해줘", True),
            ("스킬 호환성 확인해줘", True),
            ("내 스킬 괜찮은지 점검해줘", True),
            ("직원 스킬 평가 기준 만들어줘", False),
            ("영업 스킬 평가표", False),
        ):
            with self.subTest(message=message):
                self.assertEqual(skill_eval_korean_match(normalized_phrase(message)), matched)


if __name__ == "__main__":
    unittest.main()

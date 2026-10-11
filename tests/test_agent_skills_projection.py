"""Portable projection contracts; Hermes digests captured before target support."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest



def _shadow_problems(definitions) -> list[str]:
    """Every override whose recorded shadow digest no longer matches its section (#1786)."""
    from omh.skills.catalog import omh_skill_display_name

    problems: list[str] = []
    for definition in definitions:
        name = omh_skill_display_name(definition.name)
        recorded = definition.portable_override_shadows
        for section in sorted(definition.portable_overrides.keys() | recorded.keys()):
            if section not in definition.portable_overrides:
                problems.append(f"{name}::{section}: portable_override_shadows entry without an override; drop it")
                continue
            actual = hashlib.sha256(json.dumps(getattr(definition, section, None), ensure_ascii=False).encode()).hexdigest()
            if recorded.get(section) != actual:
                problems.append(
                    f"{name}::{section}: shadowed section changed; re-read the override, "
                    f"then update portable_override_shadows[{section!r}] to {actual}"
                )
    return problems


class AgentSkillsProjectionTests(unittest.TestCase):
    def test_ulw_work_projection_has_no_hermes_framing(self):
        from omh.skills.render import agent_skill_templates
        templates = {t.name: t.content for t in agent_skill_templates()}
        self.assertIn("ulw-work", templates)
        self.assertIn("omh-frontend", templates)
        for name, content in templates.items():
            for token in ("Hermes-native", "omh hermes", "Wrapper Backend", "skills.external_dirs"):
                self.assertNotIn(token.lower(), content.lower(), name)

    def test_research_blocked_source_recovery_names_hermes_skill_only_on_hermes(self):
        """#1527: a 403/429/paywall/WAF source tries one recovery before the gap.

        Hermes bundles `blocked-page-recovery`; no other host does, so the
        portable body keeps the rule and drops the skill name.
        """
        from omh.skills.render import agent_skill_templates, builtin_skill_templates
        hermes = {t.name: t.content for t in builtin_skill_templates()}["research"]
        portable = {t.name: t.content for t in agent_skill_templates()}["ulw-research"]
        rule = (
            "If a source fails with HTTP 403, HTTP 429, a paywall, or a WAF or bot wall, "
            "load Hermes' `blocked-page-recovery` skill once for that source when it is available"
        )
        self.assertIn(rule, hermes)
        self.assertIn("never as the live page", hermes)
        self.assertIn("name the retrieval gap with that reason", hermes)
        self.assertNotIn("blocked-page-recovery", portable)
        self.assertIn(
            "If a source fails with HTTP 403, HTTP 429, a paywall, or a WAF or bot wall, "
            "use the host's blocked-page recovery capability once for that source",
            portable,
        )
        self.assertIn("never as the live page", portable)
        self.assertIn("name the retrieval gap with that reason", portable)
        for name, content in {t.name: t.content for t in agent_skill_templates()}.items():
            self.assertNotIn("blocked-page-recovery", content, name)

    def test_requires_omh_cli_skills_carry_compatibility_frontmatter(self):
        from omh.skills.catalog_portable import PORTABILITY_REQUIRES_OMH_CLI, skill_portability
        from omh.skills.render import agent_skill_templates
        required = []
        for template in agent_skill_templates():
            frontmatter = template.content.split("---", 2)[1]
            if skill_portability(template.name) == PORTABILITY_REQUIRES_OMH_CLI:
                required.append(template.name)
                self.assertIn("\ncompatibility:", frontmatter)
            else:
                self.assertNotIn("\ncompatibility:", frontmatter)
        self.assertIn("ulw-loop", required)

    def test_omh_docs_is_projected_with_cli_compatibility(self):
        from omh.skills.catalog_portable import PORTABILITY_REQUIRES_OMH_CLI, skill_portability
        from omh.skills.render import agent_skill_templates
        templates = {template.name: template.content for template in agent_skill_templates()}
        self.assertIn("omh-docs", templates)
        self.assertEqual(skill_portability("omh-docs"), PORTABILITY_REQUIRES_OMH_CLI)
        self.assertEqual(skill_portability("product-docs"), PORTABILITY_REQUIRES_OMH_CLI)
        self.assertIn("\ncompatibility:", templates["omh-docs"].split("---", 2)[1])

    def test_hermes_only_skills_absent_from_projection(self):
        from omh.skills.catalog_portable import PORTABILITY_HERMES_ONLY, portable_skill_names, skill_portability
        from omh.skills.render import agent_skill_templates
        names = tuple(t.name for t in agent_skill_templates())
        self.assertEqual(names, portable_skill_names())
        for name in ("ulw-maestro", "omh-routing", "omh-doctor", "unknown-future-skill"):
            self.assertNotIn(name, names)
            self.assertEqual(skill_portability(name), PORTABILITY_HERMES_ONLY)

    def test_hermes_projection_byte_stable(self):
        """The only gate that sees a skill BODY change, so it has to name the body.

        `docs ... --check` cannot do this job: those are drift gates, and an
        intended body edit moves the source and the generated file together,
        so there is no drift to find. This pin is what fires instead -- and
        its bare dict compare used to report 124 keys in two different orders
        (producer here, sorted in the fixture), so the elided preview lined up
        two unrelated skills and read as though everything had moved. The
        names below are the whole point: a body change is usually deliberate,
        and what the author needs is confirmation that exactly the skill they
        edited moved and nothing else did.
        """
        from omh.skills.render import builtin_skill_templates
        expected = json.loads((Path(__file__).parent / "fixtures/agent_skills_hermes_digests.json").read_text())
        actual = {t.name: hashlib.sha256(t.content.encode()).hexdigest() for t in builtin_skill_templates()}
        moved = sorted(name for name in actual.keys() & expected.keys() if actual[name] != expected[name])
        added = sorted(actual.keys() - expected.keys())
        removed = sorted(expected.keys() - actual.keys())
        self.assertEqual(
            (moved, added, removed),
            ([], [], []),
            "skill body digests changed: moved="
            f"{moved or 'none'} added={added or 'none'} removed={removed or 'none'}. "
            "If that is the change you meant, re-derive the fixture with "
            "json.dumps(..., indent=2, sort_keys=True) and commit it with the body edit.",
        )
        self.assertEqual(actual, expected)

    def test_the_digest_fixture_stays_in_sorted_order(self):
        """Sorted keys are what keeps one moved digest a one-line diff.

        The assertion above compares dicts, so key order cannot fail it: a
        re-derive in producer order rewrites all 125 lines, buries the one
        that moved, and still passes. Producer order is catalog insertion
        order, so it also re-shuffles whenever a skill is added. This says
        the order out loud, because the convention was otherwise held only
        by whoever regenerated the file knowing about it.
        """
        path = Path(__file__).parent / "fixtures/agent_skills_hermes_digests.json"
        keys = list(json.loads(path.read_text()))
        self.assertEqual(
            keys,
            sorted(keys),
            "re-derive the fixture with json.dumps(..., indent=2, sort_keys=True)",
        )

    def test_every_portable_override_replaces_a_section_the_portable_body_renders(self):
        """An override lives on the definition it shadows, so it cannot name a missing skill.

        It can still name a section by a string that stops matching: a renamed
        definition field, or a field the portable body never renders. The
        first dies in `_target_definition` on an `AttributeError` that names
        only the field; the second is applied and silently dropped. Checking
        the key against the definition's fields before rendering, then each
        replacement line against the rendered body, names the skill and the
        section for both.
        """
        from dataclasses import fields
        from omh.skills.catalog import installable_skill_definitions, omh_skill_display_name
        from omh.skills.catalog_types import SkillDefinition
        from omh.skills.render import agent_skill_template
        from omh.skills.catalog_portable import portable_skill_names

        sections = {field.name for field in fields(SkillDefinition)} - {"portable_overrides"}
        overridden = [d for d in installable_skill_definitions() if d.portable_overrides]
        self.assertTrue(overridden, "no definition carries portable_overrides; the check below would be vacuous")
        portable = set(portable_skill_names())
        problems = []
        for definition in overridden:
            name = omh_skill_display_name(definition.name)
            unknown = sorted(set(definition.portable_overrides) - sections)
            problems.extend(f"{name}::{section} (not a SkillDefinition field)" for section in unknown)
            if unknown:
                continue
            if name not in portable:
                problems.append(f"{name} (overrides a skill with no Agent Skills projection)")
                continue
            body = agent_skill_template(definition).content
            problems.extend(
                f"{name}::{section} (replacement line absent from the portable body)"
                for section, lines in definition.portable_overrides.items()
                if any(line not in body for line in lines)
            )
        self.assertEqual(
            problems,
            [],
            "portable_overrides entries that do not replace a rendered section. Point the key at "
            "the field that replaced it, or drop the entry.",
        )

    def test_hermes_reference_lines_name_unshipped_references_and_drop_from_portable(self):
        # A line marked Hermes-only is dropped from the portable body, so the
        # mark is only honest while its reference really stays out of that
        # target; the line itself stays in the Hermes body.
        from omh.skills.catalog import installable_skill_definitions
        from omh.skills.catalog_portable import PORTABLE_REFERENCE_PATHS
        from omh.skills.catalog_types import HermesReferenceLine
        from omh.skills.render import agent_skill_template, builtin_skill_templates

        hermes = {t.name: t.content for t in builtin_skill_templates()}
        marked = [
            (definition, line)
            for definition in installable_skill_definitions()
            for line in definition.quality_bar
            if isinstance(line, HermesReferenceLine)
        ]
        self.assertTrue(marked, "no HermesReferenceLine in the catalog; the check below would be vacuous")
        for definition, line in marked:
            with self.subTest(skill=definition.name, reference=line.reference):
                self.assertNotIn(f"{definition.name}/{line.reference}", PORTABLE_REFERENCE_PATHS)
                self.assertIn(str(line), hermes[definition.name])
                self.assertNotIn(str(line), agent_skill_template(definition).content)

    def test_a_hermes_reference_line_outside_quality_bar_is_refused(self):
        # The portable projection filters quality_bar only, so the same line in
        # another section would ship a pointer to a missing reference.
        from dataclasses import replace

        from omh.skills.catalog import installable_skill_definitions
        from omh.skills.catalog_types import HermesReferenceLine
        from omh.skills.render import agent_skill_template

        definition = next(d for d in installable_skill_definitions() if d.name == "agent-debug")
        line = HermesReferenceLine("Load `references/session-forensics.md` first.", "references/session-forensics.md")
        misplaced = replace(definition, final_checklist=(*definition.final_checklist, line))
        with self.assertRaisesRegex(ValueError, r"agent-debug: HermesReferenceLine is honoured only in quality_bar, found in \['final_checklist'\]"):
            agent_skill_template(misplaced)

    def test_every_portable_override_pins_the_section_it_shadows(self):
        """The #1786 gate, recorded beside the override it protects.

        An override REPLACES its catalog section, so a line added to that
        section never reaches agent-skills/<skill>/SKILL.md, and
        `docs agent-skills --check` agrees with the override by construction.
        The digest is sha256 of the section's JSON form, so a scalar and a
        one-element tuple never collide.
        """
        from omh.skills.catalog import installable_skill_definitions

        self.assertEqual(_shadow_problems(installable_skill_definitions()), [], "portable_override_shadows out of date (#1786)")

    def test_a_changed_shadowed_section_is_named_alone(self):
        # The guard's precision is part of the contract: one section edited
        # upstream names exactly that skill::section, and nothing else, so the
        # fix is one literal away rather than a hunt.
        from dataclasses import replace

        from omh.skills.catalog import installable_skill_definitions, omh_skill_display_name

        definitions = list(installable_skill_definitions())
        victim = next(d for d in definitions if "quality_bar" in d.portable_overrides)
        mutated = replace(victim, quality_bar=(*victim.quality_bar, "a line added upstream"))
        problems = _shadow_problems([mutated if d is victim else d for d in definitions])
        self.assertEqual(len(problems), 1, problems)
        self.assertTrue(problems[0].startswith(f"{omh_skill_display_name(victim.name)}::quality_bar: shadowed section changed"), problems[0])
        self.assertIn("update portable_override_shadows['quality_bar'] to ", problems[0])

    def test_user_scope_mirror_has_shared_manifest_and_drift(self):
        from omh.install.agent_skills_projection import install_agent_skills, agent_skills_status, MANIFEST_NAME
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / ".agents/skills"
            mirror = Path(tmp) / ".claude/skills"
            install_agent_skills(target, mirror=mirror)
            manifest = json.loads((target / MANIFEST_NAME).read_text())
            self.assertEqual(manifest["target_dirs"], [str(target), str(mirror)])
            self.assertEqual((target / MANIFEST_NAME).read_bytes(), (mirror / MANIFEST_NAME).read_bytes())
            self.assertFalse((mirror / "ulw-work/SKILL.md").is_symlink())
            self.assertEqual((target / "ulw-work/SKILL.md").read_bytes(), (mirror / "ulw-work/SKILL.md").read_bytes())
            (mirror / "ulw-work/SKILL.md").write_bytes(b"local mirror edit")
            status = agent_skills_status(target, mirror=mirror)
            self.assertEqual(status["drift"], "locally_modified")
            self.assertTrue(status["locally_modified"])
            self.assertEqual(install_agent_skills(target, mirror=mirror)["drift"], "clean")

    def test_agent_descriptions_are_bounded_without_changing_hermes(self):
        from dataclasses import replace
        from omh.skills.catalog import installable_skill_definitions
        from omh.skills.render import agent_skill_templates, agent_frontmatter_description, frontmatter_description
        for template in agent_skill_templates():
            line = next(line for line in template.content.splitlines() if line.startswith("description: "))
            description = json.loads(line.removeprefix("description: "))
            self.assertGreaterEqual(len(description), 1)
            self.assertLessEqual(len(description), 1024)
        # The router deliberately emits no trigger tail; exercise an ordinary skill.
        definition = replace(installable_skill_definitions()[1], description="x" * 990, triggers=("long trigger phrase",))
        self.assertLessEqual(len(agent_frontmatter_description(definition)), 1024)
        self.assertGreater(len(frontmatter_description(definition)), 1024)
        with self.assertRaises(ValueError):
            agent_frontmatter_description(replace(definition, description="x" * 1025))

    def test_install_manifest_detects_local_modification(self):
        from omh.install.agent_skills_projection import install_agent_skills, agent_skills_status, MANIFEST_NAME
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / ".agents/skills"
            status = install_agent_skills(target)
            self.assertEqual(status["projection"], "fresh")
            manifest = json.loads((target / MANIFEST_NAME).read_text())
            self.assertEqual(manifest["schema_version"], "omh_agent_skills_projection/v1")
            path = target / "ulw-work/SKILL.md"
            path.write_bytes(path.read_bytes() + b"\nlocal edit\n")
            status = agent_skills_status(target)
            self.assertEqual(status["drift"], "locally_modified")
            self.assertIn("ulw-work/SKILL.md", status["locally_modified"])
            self.assertTrue(status["next_action"])
            status = install_agent_skills(target)
            self.assertEqual(status["projection"], "fresh")
            self.assertEqual(status["drift"], "clean")

    def test_hermes_source_discovery_does_not_mix_agent_projections(self):
        from omh.converter import discover_skill_files, convert_references_from_dir
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)
            for directory in ("skills", "agent-skills", ".agents/skills"):
                skill = source / directory / "omh-frontend/SKILL.md"
                reference = skill.parent / "references/example.md"
                reference.parent.mkdir(parents=True)
                skill.write_text("---\nname: omh-frontend\n---\n" + directory)
                reference.write_text(directory)
            self.assertEqual(discover_skill_files(source), [source / "skills/omh-frontend/SKILL.md"])
            self.assertEqual([ref.content for ref in convert_references_from_dir(source)], ["skills"])
            # An explicit import root still means exactly what the operator named.
            self.assertEqual(discover_skill_files(source / "agent-skills"), [source / "agent-skills/omh-frontend/SKILL.md"])

    def test_repo_scope_ignores_ambient_git_target_and_bounds_the_probe(self):
        from contextlib import chdir
        import os
        import subprocess
        from unittest.mock import patch
        from omh.install.agent_skills_projection import agent_skills_targets
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            repo, foreign = root / "repo", root / "foreign"
            for path in (repo, foreign):
                subprocess.run(["git", "init", "-q", str(path)], check=True, capture_output=True)
            with chdir(repo), patch.dict(os.environ, {"GIT_DIR": str(foreign / ".git"), "GIT_WORK_TREE": str(foreign)}):
                self.assertEqual(agent_skills_targets("repo"), (repo / ".agents/skills", repo / ".claude/skills"))
            with patch("omh.install.agent_skills_projection.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 10)) as runner:
                with self.assertRaisesRegex(ValueError, "timed out"):
                    agent_skills_targets("repo")
                self.assertEqual(runner.call_args.kwargs["timeout"], 10)

    def test_repo_scope_installs_and_repairs_claude_mirror(self):
        from contextlib import chdir
        import subprocess
        from _cli_harness import run_cli
        from omh.install.agent_skills_projection import MANIFEST_NAME, agent_skill_files, install_agent_skills
        from omh.converter import discover_skill_files
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
            target, mirror = repo / ".agents/skills", repo / ".claude/skills"
            # Upgrade an existing single-root v1 installation without losing files.
            install_agent_skills(target)
            with chdir(repo):
                command = ["install", "--target", "agents", "--scope", "repo", "--json"]
                status, output, error = run_cli(command)
                self.assertEqual(status, 0, error)
                self.assertEqual(json.loads(output)["target_dirs"], [str(target), str(mirror)])
                self.assertEqual(json.loads(output)["projection"], "fresh")
                manifest = json.loads((target / MANIFEST_NAME).read_text())
                self.assertEqual(manifest["schema_version"], "omh_agent_skills_projection/v1")
                self.assertEqual((target / MANIFEST_NAME).read_bytes(), (mirror / MANIFEST_NAME).read_bytes())
                for relative, content in agent_skill_files().items():
                    self.assertEqual((mirror / relative).read_bytes(), content.encode("utf-8"))
                    self.assertFalse((mirror / relative).is_symlink())
                    self.assertEqual(manifest["files"][relative], hashlib.sha256(content.encode("utf-8")).hexdigest())
                changed = mirror / "ulw-work/SKILL.md"
                changed.write_bytes(b"local repo mirror edit")
                status, output, _ = run_cli(command + ["--status"])
                self.assertEqual(status, 0)
                self.assertEqual(json.loads(output)["drift"], "locally_modified")
                self.assertIn("mirror:ulw-work/SKILL.md", json.loads(output)["locally_modified"])
                self.assertEqual(changed.read_bytes(), b"local repo mirror edit")
                status, output, _ = run_cli(command)
                self.assertEqual(status, 0)
                self.assertEqual(json.loads(output)["projection"], "fresh")
                self.assertEqual(json.loads(output)["drift"], "clean")
                (mirror / MANIFEST_NAME).unlink()
                self.assertEqual(json.loads(run_cli(command + ["--status"])[1])["projection"], "missing")
                self.assertEqual(run_cli(command)[0], 0)
            # Neither generated copy may contaminate an implicit Hermes import.
            self.assertEqual(discover_skill_files(repo), [])
            self.assertEqual(len(discover_skill_files(mirror)), len(list(mirror.glob("*/SKILL.md"))))

    def test_manifest_owned_claude_mirror_is_not_an_implicit_hermes_source(self):
        from omh.install.agent_skills_projection import install_agent_skills
        from omh.converter import discover_skill_files
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            target, mirror = repo / ".agents/skills", repo / ".claude/skills"
            install_agent_skills(target, mirror=mirror)
            self.assertEqual(discover_skill_files(repo), [])
            self.assertTrue(discover_skill_files(mirror))

    def test_unowned_claude_skills_survive_manifest_owned_path_exclusion(self):
        from omh.install.agent_skills_projection import install_agent_skills
        from omh.converter import discover_skill_files, convert_from_dir, convert_skill, convert_references_from_dir
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            mirror = repo / ".claude/skills"
            install_agent_skills(repo / ".agents/skills", mirror=mirror)
            custom = mirror / "custom-skill/SKILL.md"
            nested = mirror / "omh-frontend/custom-child/SKILL.md"
            raw = "---\nname: custom-skill\n---\ncustom-input\n"
            nested_raw = "---\nname: custom-child\n---\nnested-input\n"
            for path, content in ((custom, raw), (nested, nested_raw)):
                path.parent.mkdir(parents=True)
                path.write_text(content, encoding="utf-8")
            reference = custom.parent / "references/user.md"
            reference.parent.mkdir()
            reference.write_text("custom-reference\n", encoding="utf-8")
            # Ownership is per path, not an entire mirror or owned parent directory.
            self.assertEqual(discover_skill_files(repo), sorted([custom, nested]))
            expected = {convert_skill(raw, "custom-skill"), convert_skill(nested_raw, "custom-child")}
            self.assertEqual(set(convert_from_dir(repo)), expected)
            references = convert_references_from_dir(repo)
            self.assertEqual([(r.skill_name, r.relative_path) for r in references], [("custom-skill", "references/user.md")])
            self.assertEqual(references[0].content, reference.read_text())
            # Modified generated files are still manifest-owned, not user sources.
            (mirror / "ulw-work/SKILL.md").write_bytes(b"modified managed file")
            self.assertEqual(discover_skill_files(repo), sorted([custom, nested]))

    def test_projection_references_resolve_and_shipped_bytes_match(self):
        import re
        from omh.install.agent_skills_projection import agent_skill_files
        root = Path(__file__).resolve().parents[1] / "agent-skills"
        files = agent_skill_files()
        self.assertEqual({p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}, set(files))
        for relative, content in files.items():
            self.assertEqual((root / relative).read_bytes(), content.encode("utf-8"), relative)
            for ref in re.findall(r"`((?:omh-[\w-]+/|ulw-[\w-]+/)?references/[\w./-]+)`", content):
                key = ref if ref.startswith(("omh-", "ulw-")) else relative.split("/")[0] + "/" + ref
                self.assertIn(key, files, relative)
            for token in ("Hermes-native", "omh hermes", "Wrapper Backend", "skills.external_dirs"):
                self.assertNotIn(token.lower(), content.lower(), relative)

    def test_manifest_revision_and_mirror_loss_are_not_fresh(self):
        from omh.install.agent_skills_projection import install_agent_skills, agent_skills_status, MANIFEST_NAME
        with tempfile.TemporaryDirectory() as tmp:
            target, mirror = Path(tmp) / ".agents/skills", Path(tmp) / ".claude/skills"
            install_agent_skills(target, mirror=mirror)
            path = target / MANIFEST_NAME
            manifest = json.loads(path.read_text())
            manifest["catalog_revision"] = "old-revision"
            path.write_text(json.dumps(manifest))
            status = agent_skills_status(target, mirror=mirror)
            self.assertEqual(status["projection"], "stale")
            self.assertEqual(status["drift"], "clean")
            (mirror / MANIFEST_NAME).unlink()
            self.assertEqual(agent_skills_status(target, mirror=mirror)["projection"], "missing")

    def test_manifest_traversal_and_symlink_destinations_fail_before_writes(self):
        from omh.install.agent_skills_projection import install_agent_skills, MANIFEST_NAME
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target, mirror = root / ".agents/skills", root / ".claude/skills"
            install_agent_skills(target)
            manifest_path = target / MANIFEST_NAME
            original = manifest_path.read_bytes()
            manifest = json.loads(original)
            manifest["files"]["../../outside"] = "a" * 64
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                install_agent_skills(target, mirror=mirror)
            self.assertFalse(mirror.exists())
            manifest_path.write_bytes(original)
            outside = root / "outside"
            outside.mkdir()
            mirror.parent.mkdir()
            mirror.symlink_to(outside, target_is_directory=True)
            before = {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}
            with self.assertRaisesRegex(ValueError, "symlink"):
                install_agent_skills(target, mirror=mirror)
            self.assertEqual(list(outside.iterdir()), [])
            self.assertEqual(before, {p: p.read_bytes() for p in target.rglob("*") if p.is_file()})

    def test_unowned_collisions_refused_and_unrelated_skills_preserved(self):
        from omh.install.agent_skills_projection import install_agent_skills
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / ".agents/skills"
            collision = target / "ulw-work/SKILL.md"
            collision.parent.mkdir(parents=True)
            collision.write_bytes(b"not installed by OMH")
            with self.assertRaisesRegex(ValueError, "unowned"):
                install_agent_skills(target)
            self.assertEqual(collision.read_bytes(), b"not installed by OMH")
            collision.unlink()
            foreign = target / "foreign/SKILL.md"
            foreign.parent.mkdir()
            foreign.write_bytes(b"foreign skill")
            install_agent_skills(target)
            self.assertEqual(foreign.read_bytes(), b"foreign skill")

    def test_retired_manifest_files_removed_without_removing_foreign_files(self):
        from omh.install.agent_skills_projection import install_agent_skills, MANIFEST_NAME
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / ".agents/skills"
            install_agent_skills(target)
            retired = target / "retired/SKILL.md"
            retired.parent.mkdir()
            retired.write_bytes(b"old generated skill")
            foreign = retired.parent / "notes.txt"
            foreign.write_bytes(b"user notes")
            path = target / MANIFEST_NAME
            manifest = json.loads(path.read_text())
            manifest["files"]["retired/SKILL.md"] = hashlib.sha256(retired.read_bytes()).hexdigest()
            path.write_text(json.dumps(manifest))
            self.assertEqual(install_agent_skills(target)["projection"], "fresh")
            self.assertFalse(retired.exists())
            self.assertEqual(foreign.read_bytes(), b"user notes")

    def test_byte_gate_detects_missing_extra_stale_and_crlf(self):
        from _cli_harness import run_cli
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pack"
            command = ["docs", "agent-skills", "--output", str(root)]
            self.assertEqual(run_cli(command)[0], 0)
            self.assertEqual(run_cli(command + ["--check"])[0], 0)
            (root / "ulw-work/SKILL.md").unlink()
            (root / "extra.txt").write_bytes(b"extra")
            changed = root / "omh-frontend/SKILL.md"
            changed.write_bytes(changed.read_bytes().replace(b"\n", b"\r\n"))
            status, output, _ = run_cli(command + ["--check"])
            payload = json.loads(output)
            self.assertEqual(status, 1)
            self.assertEqual(payload["missing"], ["ulw-work/SKILL.md"])
            self.assertEqual(payload["extra"], ["extra.txt"])
            self.assertEqual(payload["stale"], ["omh-frontend/SKILL.md"])

    def test_cli_scopes_use_git_root_and_home_and_status_is_read_only(self):
        from contextlib import chdir
        import os
        import subprocess
        from unittest.mock import patch
        from _cli_harness import run_cli
        from omh.skills.catalog_portable import portable_skill_names
        from omh.install.agent_skills_projection import MANIFEST_NAME
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            home, repo = root / "home", root / "repo"
            home.mkdir()
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
            nested = repo / "nested"
            nested.mkdir()
            with chdir(nested), patch.dict(os.environ, {"HOME": str(home), "USERPROFILE": str(home)}):
                command = ["install", "--target", "agents", "--scope", "repo", "--json"]
                status, output, error = run_cli(command + ["--status"])
                self.assertEqual(status, 0, error)
                self.assertEqual(json.loads(output)["projection"], "missing")
                self.assertFalse((repo / ".agents").exists())
                self.assertEqual(run_cli(command + ["--dry-run"])[0], 0)
                self.assertFalse((repo / ".agents").exists())
                self.assertEqual(run_cli(command)[0], 0)
                self.assertEqual({p.name for p in (repo / ".agents/skills").iterdir() if p.is_dir()}, set(portable_skill_names()))
                self.assertFalse((nested / ".agents").exists())
                self.assertEqual((repo / ".agents/skills" / MANIFEST_NAME).read_bytes(), (repo / ".claude/skills" / MANIFEST_NAME).read_bytes())
                user = ["install", "--target", "agents", "--scope", "user", "--json"]
                self.assertEqual(run_cli(user)[0], 0)
                self.assertEqual((home / ".agents/skills" / MANIFEST_NAME).read_bytes(), (home / ".claude/skills" / MANIFEST_NAME).read_bytes())
                self.assertFalse((home / ".hermes").exists())
                self.assertFalse((home / ".omh").exists())
            with chdir(home):
                self.assertNotEqual(run_cli(command)[0], 0)
                self.assertNotEqual(run_cli(["install", "--target", "agents", "--json"])[0], 0)


if __name__ == "__main__":
    unittest.main()

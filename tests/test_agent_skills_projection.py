"""Portable projection contracts; Hermes digests captured before target support."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest



# The distribution's own name, which is also the router's canonical name.
_DISTRIBUTION_NAME = "oh-my-hermes"
# Read in any case, since a catalog bullet often opens with its verb ("Route
# setup questions to doctor."); the skill names after it stay case-sensitive.
_REFERENCE_VERBS = r"(?i:(?:route|routes|routed|routing|hand|hands|handed|send|sends|sent|go|goes)\b[^.;\n`]{0,60}?\bto|use|uses|load|loads)"


def _unshipped_portable_skills() -> dict[str, str]:
    """Canonical name -> label for each skill the Hermes projection ships and the portable one does not.

    Both sides come from the producers, so a skill that starts or stops
    shipping on either side moves this map without anyone editing a list.
    """
    from omh.skills.catalog import omh_skill_display_name
    from omh.skills.render import agent_skill_templates, builtin_skill_templates

    portable = {template.name for template in agent_skill_templates()}
    return {
        template.name: omh_skill_display_name(template.name)
        for template in builtin_skill_templates()
        if omh_skill_display_name(template.name) not in portable
    }


def _skill_references(text: str, skills: dict[str, str]) -> list[tuple[int, str, str]]:
    """Each `(line, canonical name, matched text)` where `text` names one of `skills` as a skill.

    A label (`omh-doctor`) and a backticked canonical name (`` `doctor` ``)
    always name the skill, and so does a bare hyphenated canonical name
    (`research-department`), which no sentence uses as an ordinary word. A
    one-word canonical name and the distribution name count only right after a
    route, hand, send, use, or load verb, read in any case, so "a doctor", "the
    always-loaded skill body" and "pip install oh-my-hermes" never match.
    """
    def alternatives(names):
        return "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True)) or r"(?!)"

    by_label = {label: name for name, label in skills.items()}
    hyphenated = [name for name in skills if "-" in name and name != _DISTRIBUTION_NAME]
    words = [name for name in skills if name not in hyphenated]
    patterns = (
        (re.compile(rf"(?<![\w-])({alternatives(by_label)})(?![\w-])"), by_label),
        (re.compile(rf"`({alternatives(skills)})`"), None),
        (re.compile(rf"(?<![\w/.`-])({alternatives(hyphenated)})(?![\w-])"), None),
        (re.compile(rf"\b{_REFERENCE_VERBS}\s+({alternatives(words)})(?![\w-])"), None),
    )
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        for pattern, names in patterns:
            for match in pattern.finditer(line):
                name = match.group(1)
                found.append((number, names[name] if names else name, match.group(0)))
    return found


def _unshipped_skill_mentions(files, unshipped: dict[str, str]) -> list[str]:
    """Every `<path>:<line>: <matched text>` where a file names a skill in `unshipped`."""
    return [
        f"{path}:{number}: {matched}"
        for path, content in files
        for number, _name, matched in _skill_references(content, unshipped)
    ]


# Each `portable_overrides` section that leaves out a skill only the Hermes
# projection ships, and those skills by canonical name: the record of why the
# override exists, which its shadow digest does not keep. The rewrite test
# fails naming the override once one of them ships portably.
_OVERRIDES_AROUND_UNSHIPPED_SKILLS = {
    "ulw-loop::do_not_use_when": ("automation-blueprint",),
    "ulw-plan::quality_bar": ("dag-ulw",),
    "ulw-work::quality_bar": ("maestro",),
    "ulw-qa::quality_bar": ("todo-checklist",),
    "omh-source-finder::use_when": ("research-department",),
    "omh-research-brief::description": ("research-department",),
    "omh-model-finetuning::why_this_exists": ("model-optimization", "workflow-learning"),
    "omh-spend-gate::why_this_exists": ("browser-operator",),
    "omh-memory-new::description": ("memory-sync",),
    "omh-external-connector-readiness::description": ("executor-runtime-readiness",),
    "omh-toolbelt-readiness::description": ("executor-runtime-readiness",),
}


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

    def test_hermes_only_is_exactly_skills_absent_from_the_committed_pack(self):
        # docs/AGENT-SKILLS.md states this rule instead of listing names, which
        # went stale; the two committed trees and the producer must agree.
        from omh.skills.catalog_portable import PORTABILITY_HERMES_ONLY, skill_portability
        root = Path(__file__).resolve().parents[1]
        hermes = {p.name for p in (root / "skills").iterdir() if (p / "SKILL.md").is_file()}
        pack = {p.name for p in (root / "agent-skills").iterdir() if (p / "SKILL.md").is_file()}
        self.assertLessEqual(pack, hermes)
        for name in sorted(hermes):
            with self.subTest(skill=name):
                self.assertEqual(skill_portability(name) == PORTABILITY_HERMES_ONLY, name not in pack)
        doc = (root / "docs/AGENT-SKILLS.md").read_text(encoding="utf-8")
        section = doc.split("### Hermes-only boundary\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn("`skill_portability()` in `src/skills/catalog_portable.py`", section)
        self.assertNotIn("| --- |", section)

    def test_portable_files_name_no_skill_the_portable_projection_does_not_ship(self):
        """A portable host is never told to load a skill it does not have.

        A Do Not Use When line that hands its request only to such skills keeps
        the request and loses the pointer in `_target_definition`; any other
        sentence naming one is rewritten through a `PortableLine`,
        `portable_overrides`, or `PORTABLE_REFERENCE_REWRITES`. This reads
        every body and reference the projection ships, by label and by
        canonical name (see `_skill_references`), and names each by path and
        line.
        """
        from omh.skills.render import agent_skill_reference_templates, agent_skill_templates

        self.maxDiff = None
        unshipped = _unshipped_portable_skills()
        self.assertTrue(unshipped, "every Hermes skill ships portably; the gate below would read nothing")
        files = [
            *((f"{template.name}/SKILL.md", template.content) for template in agent_skill_templates()),
            *(
                (f"{template.skill_name}/{template.relative_path}", template.content)
                for template in agent_skill_reference_templates()
            ),
        ]
        self.assertEqual(
            _unshipped_skill_mentions(files, unshipped),
            [],
            "a portable body or reference names a skill only the Hermes projection ships: rewrite the line "
            "through a PortableLine, portable_overrides, or PORTABLE_REFERENCE_REWRITES",
        )

    def test_the_gate_names_planted_references_and_a_pure_pointer_keeps_its_request(self):
        # The gate's precision is part of the contract. Every planted
        # reference form is named once by line, an ordinary use of a word that
        # is also a skill name is not, and a Do Not Use When line that hands its
        # request only to an unshipped skill keeps the request.
        from dataclasses import replace

        from omh.skills.catalog import installable_skill_definitions, omh_skill_display_name
        from omh.skills.render import agent_skill_template

        unshipped = _unshipped_portable_skills()
        self.assertTrue(unshipped)
        portable = [
            d for d in installable_skill_definitions()
            if omh_skill_display_name(d.name) not in unshipped.values()
        ]
        host = next(d for d in portable if not {"do_not_use_when", "final_checklist"} & set(d.portable_overrides))
        shipped_sibling = next(d.name for d in portable if d.name != host.name)
        hyphenated = sorted(name for name in unshipped if "-" in name and name != _DISTRIBUTION_NAME)[0]
        words = sorted(name for name in unshipped if "-" not in name)
        planted = [
            f"Check the page with `{unshipped[hyphenated]}` first.",
            f"Record it as `{hyphenated}` input.",
            f"Hand the result to {hyphenated} afterwards.",
        ]
        ordinary = [f"A {hyphenated.replace('-', ' ')} note is prose."]
        if words:
            # A catalog bullet often opens with its verb, so the verb is read
            # in any case; the skill name is not.
            planted += [
                f"If it is about setup, route to {words[0]}.",
                f"Route setup questions to {words[0]}.",
                f"Use {words[0]} for install health.",
                f"Hand it off to {words[0]}.",
                f"Load {words[0]} to edit the catalog.",
            ]
            ordinary += [f"A {words[0]} visit is no request.", f"The always-loaded {words[0]} body is prose."]
        if _DISTRIBUTION_NAME in unshipped:
            ordinary.append(f"Install with pip install {_DISTRIBUTION_NAME}.")
        content = agent_skill_template(replace(
            host,
            final_checklist=(*host.final_checklist, *planted, *ordinary),
            do_not_use_when=(
                *host.do_not_use_when,
                f"The ask is a planted chore; use `{hyphenated}`.",
                f"The ask is a mixed chore; use `{hyphenated}` or `{shipped_sibling}`.",
            ),
        )).content
        mentions = _unshipped_skill_mentions([("planted/SKILL.md", content)], unshipped)
        self.assertEqual(len(mentions), len(planted) + 1, mentions)
        self.assertIn("- The ask is a planted chore.\n", content)
        self.assertNotIn("planted chore; use", content)
        self.assertIn(
            f"- The ask is a mixed chore; use `{unshipped[hyphenated]}` or `{omh_skill_display_name(shipped_sibling)}`.\n",
            content,
        )
        for line in ordinary:
            self.assertIn(f"- {line}\n", content)
        self.assertEqual(_skill_references("omh-skill-health omh-skill-scout", {"skill": "omh-skill"}), [])

    def test_a_portable_rewrite_is_reread_once_a_skill_it_leaves_out_ships(self):
        """A rewrite exists because a skill is missing from the portable projection.

        A `PortableLine` or `PORTABLE_REFERENCE_REWRITES` pair exists for that
        reason alone, so every skill its Hermes text names and its portable
        text does not must still be missing. A `portable_overrides` section can
        exist for other reasons too, so the skills it was written around are
        recorded in `_OVERRIDES_AROUND_UNSHIPPED_SKILLS`. Either way, a skill
        that starts shipping portably fails here, naming each rewrite to re-read.
        """
        from dataclasses import fields

        from omh.skills.catalog import installable_skill_definitions, omh_skill_display_name
        from omh.skills.catalog_portable import PORTABLE_REFERENCE_REWRITES, portable_skill_names
        from omh.skills.catalog_types import PortableLine

        definitions = installable_skill_definitions()
        every_skill = {d.name: omh_skill_display_name(d.name) for d in definitions}
        shipped = set(portable_skill_names())
        unshipped = {name for name, label in every_skill.items() if label not in shipped}

        def left_out(hermes: str, portable: str) -> set[str]:
            return (
                {name for _, name, _ in _skill_references(hermes, every_skill)}
                - {name for _, name, _ in _skill_references(portable, every_skill)}
            )

        problems = []
        rewrites = [(path, hermes, portable) for path, pairs in PORTABLE_REFERENCE_REWRITES.items() for hermes, portable in pairs]
        overrides = {}
        for definition in definitions:
            label = every_skill[definition.name]
            if label not in shipped:
                continue
            for field in fields(definition):
                value = getattr(definition, field.name)
                if isinstance(value, tuple):
                    rewrites += [(f"{label}::{field.name}", str(line), line.portable) for line in value if isinstance(line, PortableLine)]
            for section, lines in definition.portable_overrides.items():
                hermes = getattr(definition, section)
                overrides[f"{label}::{section}"] = left_out("\n".join(hermes) if isinstance(hermes, tuple) else hermes, "\n".join(lines))
        self.assertTrue(any("::" in where for where, _, _ in rewrites), "no PortableLine in the catalog; half of this check is vacuous")
        for where, hermes, portable in rewrites:
            problems += [
                f"{where} leaves out `{every_skill[name]}`, which the portable projection ships; re-read the rewrite"
                for name in sorted(left_out(hermes, portable) - unshipped)
            ]
        for where in sorted(overrides.keys() | _OVERRIDES_AROUND_UNSHIPPED_SKILLS.keys()):
            recorded = set(_OVERRIDES_AROUND_UNSHIPPED_SKILLS.get(where, ()))
            problems += [
                f"{where} was written around `{every_skill.get(name, name)}`, which the portable projection now ships; re-read the override"
                for name in sorted(recorded - unshipped)
            ]
            actual = overrides.get(where, set()) & unshipped
            if actual != recorded & unshipped:
                problems.append(f"{where} leaves out {sorted(actual)}; record exactly those in _OVERRIDES_AROUND_UNSHIPPED_SKILLS")
        self.assertEqual(problems, [])

    def test_a_portable_rewrite_that_no_longer_applies_fails_the_render(self):
        from dataclasses import replace

        from omh.skills.catalog import installable_skill_definitions
        from omh.skills.catalog_portable import PORTABLE_REFERENCE_PATHS, PORTABLE_REFERENCE_REWRITES
        from omh.skills.catalog_types import PortableLine
        from omh.skills.render import SkillReferenceTemplate, agent_skill_template, portable_reference_templates

        self.assertTrue(PORTABLE_REFERENCE_REWRITES)
        self.assertLessEqual(set(PORTABLE_REFERENCE_REWRITES), PORTABLE_REFERENCE_PATHS)
        skill, _, relative = next(iter(PORTABLE_REFERENCE_REWRITES)).partition("/")
        with self.assertRaisesRegex(ValueError, "no longer occurs exactly once"):
            portable_reference_templates([SkillReferenceTemplate(skill, relative, "moved text\n")])
        definition = next(d for d in installable_skill_definitions() if d.name == "spend-gate")
        with self.assertRaisesRegex(ValueError, "PortableLine is honoured in list fields"):
            agent_skill_template(replace(definition, why_this_exists=PortableLine("a", "b")))

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
        from omh.skills.render import agent_skill_template, translate_sibling_mentions
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
            # Every rendered line names its siblings under loadable labels
            # (`translate_sibling_mentions`), so that is the line to find.
            problems.extend(
                f"{name}::{section} (replacement line absent from the portable body)"
                for section, lines in definition.portable_overrides.items()
                if any(
                    translate_sibling_mentions(line, owner=definition.name) not in body
                    for line in lines
                )
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
                self.assertEqual(json.loads(run_cli(command + ["--status"])[1])["projection"], "fresh")
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
        from omh.install.agent_skills_projection import MANIFEST_NAME, agent_skill_files
        root = Path(__file__).resolve().parents[1] / "agent-skills"
        files = agent_skill_files()
        self.assertEqual({p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}, {*files, MANIFEST_NAME})
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
            self.assertEqual(agent_skills_status(target, mirror=mirror)["projection"], "stale")

    def test_status_reports_primary_when_mirror_manifest_absent(self):
        from unittest.mock import patch
        from omh.install.agent_skills_projection import install_agent_skills, agent_skills_status, MANIFEST_NAME
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            target, mirror = home / ".agents/skills", home / ".claude/skills"
            with patch.object(Path, "home", return_value=home):
                empty = agent_skills_status(target, mirror=mirror)
                self.assertEqual((empty["primary"], empty["mirror"], empty["projection"]),
                                 ("missing", "missing", "missing"))
                install_agent_skills(target)
                status = agent_skills_status(target, mirror=mirror)
                self.assertEqual((status["primary"], status["mirror"], status["projection"]),
                                 ("fresh", "missing", "fresh"))
                self.assertIn("mirror copy", status["warnings"][0])
                self.assertIn("omh install --target agents --scope user", status["warnings"][0])
                self.assertFalse(mirror.exists())
                self.assertEqual(agent_skills_status(target)["mirror"], "none")
                path = target / MANIFEST_NAME
                manifest = json.loads(path.read_text())
                manifest["catalog_revision"] = "old-revision"
                path.write_text(json.dumps(manifest))
                status = agent_skills_status(target, mirror=mirror)
                self.assertEqual((status["primary"], status["mirror"], status["projection"]),
                                 ("stale", "missing", "stale"))

    def test_status_stale_mirror_still_stale(self):
        from omh.install.agent_skills_projection import install_agent_skills, agent_skills_status, MANIFEST_NAME
        with tempfile.TemporaryDirectory() as tmp:
            target, mirror = Path(tmp) / ".agents/skills", Path(tmp) / ".claude/skills"
            install_agent_skills(target, mirror=mirror)
            path = mirror / MANIFEST_NAME
            manifest = json.loads(path.read_text())
            manifest["catalog_revision"] = "old-revision"
            path.write_text(json.dumps(manifest))
            status = agent_skills_status(target, mirror=mirror)
            self.assertEqual((status["primary"], status["mirror"], status["projection"]),
                             ("fresh", "stale", "stale"))

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

    def test_cli_ancestor_fixture_leaves_cold_import_tempfile_aliases_unmocked(self):
        import os
        import subprocess
        import sys
        from textwrap import dedent

        # A fresh interpreter matters: collection can import the lazy CLI command
        # tree before the fixture and hide a captured process-global mock.
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(root / "src"), str(root / "tests"))))
        probe = dedent("""\
            import importlib
            from pathlib import Path
            import sys
            import tempfile
            import unittest

            real_constructor = tempfile.TemporaryDirectory
            consumers = ("omh.quality.working_tree_fingerprint", "omh.coding.fanout_dispatch")
            for name in consumers:
                assert name not in sys.modules, f"probe must start cold: {name}"
            suite = unittest.TestLoader().loadTestsFromName(
                "test_agent_skills_projection.AgentSkillsProjectionTests."
                "test_cli_scope_fixture_cannot_discover_an_ancestor_repository"
            )
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            assert result.wasSuccessful(), "ancestor fixture failed"
            assert result.testsRun == 1
            assert tempfile.TemporaryDirectory is real_constructor
            for name in consumers:
                constructor = importlib.import_module(name).TemporaryDirectory
                assert constructor is real_constructor, f"{name} retained a mocked TemporaryDirectory"
                with constructor(prefix="omh-fixture-isolation-") as directory:
                    assert Path(directory).is_dir(), name
        """)
        result = subprocess.run(
            [sys.executable, "-c", probe], cwd=root, env=env,
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_cli_scope_fixture_cannot_discover_an_ancestor_repository(self):
        import subprocess
        from _cli_harness import run_cli

        self.assertTrue(callable(run_cli))
        with tempfile.TemporaryDirectory() as tmp:
            ancestor = Path(tmp).resolve()
            subprocess.run(["git", "init", "-q", str(ancestor)], check=True, capture_output=True)
            self._assert_cli_scopes_use_git_root_and_home_and_status_is_read_only(temporary_parent=ancestor)
            self.assertFalse((ancestor / ".agents").exists())
            self.assertFalse((ancestor / ".claude").exists())

    def test_cli_scopes_use_git_root_and_home_and_status_is_read_only(self):
        self._assert_cli_scopes_use_git_root_and_home_and_status_is_read_only()

    def _assert_cli_scopes_use_git_root_and_home_and_status_is_read_only(self, *, temporary_parent=None):
        from contextlib import chdir
        import os
        import subprocess
        from unittest.mock import patch
        from _cli_harness import run_cli
        from omh.skills.catalog_portable import portable_skill_names
        from omh.install.agent_skills_projection import MANIFEST_NAME
        with tempfile.TemporaryDirectory(dir=temporary_parent) as tmp:
            root = Path(tmp).resolve()
            home, repo = root / "home", root / "repo"
            # A filesystem barrier survives installer stripping of GIT_* env vars.
            # Keep the sibling real repo discoverable, but never inherit an ancestor.
            (root / ".git").write_text(f"gitdir: {root / 'nonexistent-git-barrier'}\n")
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

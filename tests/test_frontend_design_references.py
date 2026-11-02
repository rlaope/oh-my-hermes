"""The design-reference lane of `frontend` and the routing that reaches it.

Copy-paste component registries hand a project someone else's source, and the
gaps ship with it: marquee duplicates read four times by a screen reader, a
hover-only pause, a split-text effect with no reduced-motion branch. Charts
themed by config literals drift at the first theme change. These tests pin the
clauses that make an adoption or a chart theme reviewable, the extensions to
the design-system contract and taste foundations, and the phrase triggers -
including that the everyday words inside them do not widen the skill.
"""

from __future__ import annotations

from pathlib import Path
import unittest

from omh.skill_pack import builtin_skill_templates
from omh.skills.catalog import builtin_definitions
from omh.skills.catalog_portable import PORTABLE_REFERENCE_PATHS
from omh.skills.catalog_types import omh_skill_display_name
from omh.skills.packaging import builtin_skill_reference_templates
from omh.skills.render import frontend_design_reference_templates
from omh.wrapper.contract import build_chat_interaction_payload

REPO_ROOT = Path(__file__).resolve().parents[1]
ADOPTION = ("frontend", "references/component-registry-adoption.md")
CHARTS = ("frontend", "references/chart-styling.md")
CONTRACT = ("frontend", "references/design-system-contract.md")
TASTE = ("frontend", "references/taste-foundations.md")


def _unwrapped(content: str) -> str:
    """Soft line wraps collapsed, for phrase assertions that span lines."""
    return " ".join(content.split())


def _packaged(key: tuple[str, str]) -> str:
    for template in builtin_skill_reference_templates():
        if (template.skill_name, template.relative_path) == key:
            return _unwrapped(template.content)
    raise AssertionError(f"{key} is not packaged")


def _body() -> str:
    for template in builtin_skill_templates():
        if template.name == "frontend":
            return _unwrapped(template.content)
    raise AssertionError("missing skill frontend")


def _route(message: str) -> dict:
    return build_chat_interaction_payload(message, source="discord")["route"]


class RegistryTests(unittest.TestCase):
    def test_the_producer_emits_both_references(self) -> None:
        produced = {(t.skill_name, t.relative_path) for t in frontend_design_reference_templates()}
        # forms-and-input.md shares this producer; tests/test_frontend_build_contracts.py pins it.
        self.assertEqual(produced, {ADOPTION, CHARTS, ("frontend", "references/forms-and-input.md")})

    def test_both_are_packaged_generated_and_portable(self) -> None:
        packaged = {(t.skill_name, t.relative_path): t.content for t in builtin_skill_reference_templates()}
        for key in (ADOPTION, CHARTS):
            with self.subTest(reference=key[1]):
                self.assertIn(key, packaged)
                self.assertIn(f"{key[0]}/{key[1]}", PORTABLE_REFERENCE_PATHS)
                path = REPO_ROOT / "skills" / omh_skill_display_name(key[0]) / key[1]
                self.assertTrue(path.exists(), path)
                self.assertEqual(path.read_text(encoding="utf-8"), packaged[key])

    def test_the_always_loaded_body_points_at_both(self) -> None:
        body = _body()
        self.assertIn("references/component-registry-adoption.md", body)
        self.assertIn("references/chart-styling.md", body)
        self.assertIn("a marquee gets a pause reachable by keyboard and touch", body)


class ComponentRegistryAdoptionTests(unittest.TestCase):
    def test_copied_source_is_the_projects_to_fix(self) -> None:
        content = _packaged(ADOPTION)
        self.assertIn("from that moment the project owns it", content)
        self.assertIn("Every gap ships with the file.", content)
        self.assertIn("Updates are a merge, not an upgrade.", content)

    def test_the_checklist_names_every_item(self) -> None:
        content = _packaged(ADOPTION)
        for item in (
            "License, observed at the source.",
            "What it pulls in.",
            "A reduced-motion branch.",
            "ARIA.",
            "Keyboard and touch.",
            "Token mapping.",
            "Performance cost.",
        ):
            with self.subTest(item=item):
                self.assertIn(item, content)

    def test_an_unread_license_is_not_asserted(self) -> None:
        # The Commons Clause condition is the reason a sibling's MIT badge is
        # not evidence; the record must say "check" where it did not read.
        content = _packaged(ADOPTION)
        self.assertIn("Commons Clause", content)
        self.assertIn("not an OSI license", content)
        self.assertIn("license: check before adopting", content)

    def test_layers_and_effect_budget(self) -> None:
        content = _packaged(ADOPTION)
        self.assertIn("a headless primitive (Radix, Base UI, Headless UI)", content)
        self.assertIn("At most one hero effect per view.", content)
        self.assertIn("Heavy effects belong to marketing surfaces, not app UI.", content)
        self.assertIn("meets contrast at its worst-case background", content)

    def test_split_text_contract(self) -> None:
        content = _packaged(ADOPTION)
        for clause in (
            'per-character or per-word spans are `aria-hidden="true"`',
            "`aria-label` on the container, or visually-hidden text",
            "Wait for `document.fonts.ready` before splitting.",
            "revert the split and kill the scroll triggers",
            "Do not char-split long text.",
            "Under reduced motion, show the final state immediately",
            "a 50ms stagger, a 1.25s duration, `power3.out` easing",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, content)

    def test_marquee_contract(self) -> None:
        content = _packaged(ADOPTION)
        for clause in (
            "The duplicates are `aria-hidden`.",
            "A pause control reachable by keyboard and touch, not only hover.",
            "WCAG 2.2.2 (Pause, Stop, Hide)",
            "longer than five seconds",
            "Reduced motion stops it.",
            "Speed and gap are CSS variables",
            "Slow enough to read.",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, content)

    def test_motion_profiles_are_defined_once(self) -> None:
        content = _packaged(ADOPTION)
        self.assertIn("stagger, duration, easing, and travel distance", content)
        self.assertIn("**Calm**", content)
        self.assertIn("**Energetic**", content)
        self.assertIn("A component picks a profile; it does not invent numbers.", content)

    def test_the_source_record_is_dated_and_not_a_dependency(self) -> None:
        content = _packaged(ADOPTION)
        self.assertIn("Reviewed on 2026-10-07", content)
        self.assertIn("No component source, demo copy, or brand material is reproduced", content)
        self.assertIn("OMH does not install, vendor, pin, or fetch any of this at runtime", content)


class ChartStylingTests(unittest.TestCase):
    def test_categorical_and_sequential_are_separate(self) -> None:
        content = _packaged(CHARTS)
        self.assertIn("`chart-1` .. `chart-N`", content)
        self.assertIn("Keep the two sets apart", content)
        self.assertIn("a categorical hue used as a magnitude step implies an order", content)

    def test_role_tokens_and_mode_palette(self) -> None:
        content = _packaged(CHARTS)
        self.assertIn("grid, crosshair, axis label, muted label, marker, and tooltip", content)
        self.assertIn("Treat the palette as a function of the color mode", content)

    def test_color_mapping_is_a_named_choice(self) -> None:
        content = _packaged(CHARTS)
        for mapping in ("**Piecewise**", "**Continuous**", "**Ordinal**", "`unknownColor`"):
            with self.subTest(mapping=mapping):
                self.assertIn(mapping, content)

    def test_axis_text_goes_through_the_label_style_api_not_css(self) -> None:
        content = _packaged(CHARTS)
        self.assertIn("Axis text goes through the library, not CSS", content)
        self.assertIn("`tickLabelStyle` and `labelStyle`", content)
        self.assertIn("never through a CSS override", content)

    def test_states_and_slot_exhaustion(self) -> None:
        content = _packaged(CHARTS)
        for state in ("**Loading**", "**No data**", "**Error**"):
            with self.subTest(state=state):
                self.assertIn(state, content)
        self.assertIn("do not generate more hues", content)
        self.assertIn("use direct labels", content)

    def test_the_data_viz_palette_rows_are_linked_not_restated(self) -> None:
        content = _packaged(CHARTS)
        self.assertIn("omh design data --kind palette --context data-viz", content)
        self.assertIn("this reference does not restate them", content)


class ContractAndTasteExtensionTests(unittest.TestCase):
    def test_the_color_section_carries_semantic_pairs(self) -> None:
        content = _packaged(CONTRACT)
        self.assertIn("`X` and `X-foreground`", content)
        self.assertIn("`X` and `X-content`", content)
        self.assertIn("The focus ring is its own token", content)
        self.assertIn("Do not write `dark:` variants on semantic colors", content)
        self.assertIn("A single `--radius` drives the radius scale", content)

    def test_neobrutalism_is_a_rule_set(self) -> None:
        content = _packaged(TASTE)
        self.assertIn("Style presets are rule sets, not adjectives", content)
        self.assertIn("a flat offset with zero blur", content)
        self.assertIn("The offset value is NOT published by the reference library", content)
        self.assertIn("No gradients, no glass, no blur anywhere.", content)
        self.assertIn("The active state presses into its shadow", content)
        self.assertIn("A dark-mode border strategy", content)

    def test_mood_directions_and_footer_anatomy(self) -> None:
        content = _packaged(TASTE)
        self.assertIn("over a `DESIGN.md` that carries the palette", content)
        self.assertIn("## Footer anatomy", content)
        self.assertIn("the wordmark with a one-line positioning statement", content)
        self.assertIn("On mobile the link columns collapse", content)


class RoutingTests(unittest.TestCase):
    def test_the_phrases_are_triggers(self) -> None:
        frontend = next(d for d in builtin_definitions() if d.name == "frontend")
        for phrase in (
            "chart styling",
            "footer design",
            "neobrutalism style",
            "logo marquee",
            "split text animation",
            "shadcn",
            "차트 스타일",
            "푸터 디자인",
            "네오브루탈리즘",
            "로고 마키",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, frontend.triggers)

    def test_design_requests_dispatch_frontend(self) -> None:
        for message in (
            "Style the dashboard charts so axis, grid and tooltip match our theme.",
            "Design a better footer for the marketing site.",
            "Make the site neobrutalism style.",
            "Add split text animation to the hero heading.",
            "네오브루탈리즘 스타일로 바꿔줘.",
            "차트 스타일 우리 디자인 시스템에 맞춰줘.",
        ):
            with self.subTest(message=message):
                route = _route(message)
                self.assertEqual((route["action"], route["selected_skill"]), ("dispatch", "frontend"))

    def test_everyday_senses_do_not_name_frontend(self) -> None:
        for message in (
            "Chart a course for the migration.",
            "The footer of the email says unsubscribe.",
            "The sales chart in the board deck has the wrong numbers.",
            "Split text into sentences before tokenizing.",
            "The chart theme for the quarter is cost cutting.",
            "A marquee signing joined the team this week.",
        ):
            with self.subTest(message=message):
                route = _route(message)
                self.assertNotEqual(route["action"], "dispatch")
                self.assertNotEqual(route["candidate_skill"], "frontend")
                self.assertNotIn("frontend", [row["skill"] for row in route.get("recommendations") or []][:1])


if __name__ == "__main__":
    unittest.main()

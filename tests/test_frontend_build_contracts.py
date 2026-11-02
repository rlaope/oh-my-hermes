"""The build-time data and input contracts of `frontend` and `frontend-refactor`.

The visual half of `frontend` was strong and the engineering middle was empty.
A settings page built from it got `useState` plus a fetch in an effect, an
optimistic write with no rollback, errors shown on the first keystroke, a
double submit, and a chat composer whose Enter sent half-composed Hangul: the
state rules lived only in `frontend-refactor`, and nothing in OMH said
anything about IME composition. A refactor that only checked tests could
shift the page while staying green.

These tests pin the clauses that close those gaps, and that every reference a
body now names is loaded from that body with the condition for reading it.
"""

from __future__ import annotations

from pathlib import Path
import unittest

from omh.skill_pack import builtin_skill_templates
from omh.skills.catalog_portable import PORTABLE_REFERENCE_PATHS
from omh.skills.catalog_types import omh_skill_display_name
from omh.skills.packaging import builtin_skill_reference_templates

REPO_ROOT = Path(__file__).resolve().parents[1]
FORMS = ("frontend", "references/forms-and-input.md")
TASTE = ("frontend", "references/taste-foundations.md")
PASSES = ("frontend-refactor", "references/refactor-passes.md")
STATE = ("frontend-refactor", "references/state-discipline.md")


def _unwrapped(content: str) -> str:
    """Soft line wraps collapsed, for phrase assertions that span lines."""
    return " ".join(content.split())


def _packaged(key: tuple[str, str]) -> str:
    for template in builtin_skill_reference_templates():
        if (template.skill_name, template.relative_path) == key:
            return _unwrapped(template.content)
    raise AssertionError(f"{key} is not packaged")


def _body(name: str) -> str:
    for template in builtin_skill_templates():
        if template.name == name:
            return _unwrapped(template.content)
    raise AssertionError(f"missing skill {name}")


class ServerStateTests(unittest.TestCase):
    def test_the_build_body_loads_the_state_ladder_when_data_is_remote(self) -> None:
        body = _body("frontend")
        self.assertIn(
            "When the surface reads or writes remote data, load the frontend-refactor skill's "
            "`omh-frontend-refactor/references/state-discipline.md` (sections 1 and 4-6)",
            body,
        )
        self.assertIn("an optimistic write ships with its rollback", body)

    def test_the_pointer_names_sections_that_exist(self) -> None:
        state = _packaged(STATE)
        for heading in (
            "## 1. Make impossible states unrepresentable",
            "## 4. Effects synchronize with the outside",
            "## 5. Server state is not UI state",
            "## 6. The optimistic-update contract",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, state)

    def test_the_route_state_matrix_has_the_rows_a_form_page_has(self) -> None:
        body = _body("frontend")
        for row in ("submitting", "submit-failed", "optimistic-pending", "stale/refetching", "conflict (409)"):
            with self.subTest(row=row):
                self.assertIn(row, body)


class FormsAndInputTests(unittest.TestCase):
    def test_packaged_generated_and_portable(self) -> None:
        packaged = {(t.skill_name, t.relative_path): t.content for t in builtin_skill_reference_templates()}
        self.assertIn(FORMS, packaged)
        self.assertIn(f"{FORMS[0]}/{FORMS[1]}", PORTABLE_REFERENCE_PATHS)
        for tree in ("skills", "agent-skills"):
            with self.subTest(tree=tree):
                path = REPO_ROOT / tree / omh_skill_display_name(FORMS[0]) / FORMS[1]
                self.assertTrue(path.exists(), path)
                self.assertEqual(path.read_text(encoding="utf-8"), packaged[FORMS])

    def test_the_body_loads_it_with_its_condition(self) -> None:
        body = _body("frontend")
        self.assertIn(
            "When the surface has a form, a text composer, or a dialog, load `references/forms-and-input.md`",
            body,
        )

    def test_enter_to_send_waits_for_ime_composition(self) -> None:
        content = _packaged(FORMS)
        self.assertIn("when the key event reports `isComposing`, the Enter belongs to the IME", content)
        # The Safari ordering is why the flag alone is not enough.
        self.assertIn("`event.isComposing || event.keyCode === 229`", content)
        # The timing fallback is only correct with event timestamps compared in absolute value.
        self.assertIn("record `event.timeStamp` of the last `compositionend`", content)
        self.assertIn("within about 50 ms of it in absolute value", content)
        self.assertIn("a clock read inside the handler (`Date.now()`, `performance.now()`) drifts", content)
        self.assertIn("A single-line input inside a `<form>` needs no handler", content)
        self.assertIn("Run the composition check before any Enter branch, modified or not", content)
        self.assertIn("A visible submit button always remains", content)
        self.assertIn("typing Korean or Japanese with a real IME", content)

    def test_errors_wait_for_a_committed_value_and_server_errors_land_on_fields(self) -> None:
        content = _packaged(FORMS)
        self.assertIn("Validate when the user commits a value (blur) or submits", content)
        self.assertIn("`aria-invalid` turns on at the same moment the visual error appears", content)
        self.assertIn("Map each field path in the error response onto its field", content)
        self.assertIn("A failed submit keeps everything the user typed", content)
        self.assertIn("use one announcement channel, not two", content)
        self.assertIn("(`tabindex=\"-1\"`, not a live region)", content)
        self.assertIn("Help text and the error message are linked with `aria-describedby`", content)
        self.assertIn("Add `aria-errormessage` only on top of `aria-invalid=\"true\"`", content)
        self.assertIn("Never overwrite silently", content)

    def test_one_submit_in_flight_and_dialog_focus(self) -> None:
        content = _packaged(FORMS)
        self.assertIn("The guard lives in the form's `submit` handler, not on the button's click", content)
        self.assertIn("idempotency key created once per user intent and reused on retry", content)
        self.assertIn("on close focus returns to the control that opened it", content)
        self.assertIn("Under the HTML close-watcher rules (shipped in Chromium; check other engines)", content)
        self.assertIn("can be prevented only once per user activation", content)
        self.assertIn("`closedby=\"none\"`", content)
        # closedby="none" turns Escape off; keyboard users must keep it.
        self.assertIn("handle Escape yourself (keydown on the dialog) so it runs the same check", content)

    def test_undetectable_behavior_is_an_enhancement_not_a_detected_fallback(self) -> None:
        content = _packaged(FORMS)
        self.assertIn("cannot be feature-detected: `@supports` and `CSS.supports()` answer true everywhere", content)
        self.assertIn("Ship it as a progressive enhancement and say which browsers get it", content)
        self.assertIn("use the project's scroll lock", content)
        self.assertIn("A behavior that cannot be detected (the backdrop scroll above) cannot take that path", content)
        self.assertIn("A placeholder is an example value, never the label", content)

    def test_every_skill_reference_it_names_exists(self) -> None:
        content = _packaged(FORMS)
        packaged = {(t.skill_name, t.relative_path) for t in builtin_skill_reference_templates()}
        self.assertIn("`omh-backend/references/service-contract.md`", content)
        self.assertIn(("backend", "references/service-contract.md"), packaged)
        self.assertIn("`omh-frontend-refactor/references/state-discipline.md`, section 6", content)
        self.assertIn("section `Interface copy`", content)
        self.assertIn("## Interface copy", _packaged(TASTE))


class BrowserSupportTests(unittest.TestCase):
    def test_the_target_is_a_required_input_with_a_default(self) -> None:
        body = _body("frontend")
        self.assertIn(
            "browser-support target (default: Baseline Widely available, in every core browser for 30+ months)",
            body,
        )
        self.assertIn(
            "a feature newer than the target (by default, anything only Baseline Newly available) needs feature "
            "detection plus a fallback, or a deliberate target change",
            body,
        )
        self.assertIn("`omh-agent-instructions` owns that file", body)


class InterfaceCopyTests(unittest.TestCase):
    def test_copy_rules_live_in_the_always_loaded_taste_reference(self) -> None:
        taste = _packaged(TASTE)
        self.assertIn("Name things the way the reader already does", taste)
        self.assertIn("One action keeps one verb everywhere it shows up", taste)
        self.assertIn("An error message gives the cause, then the way out", taste)
        self.assertIn("An empty list carries the control that fills it", taste)
        self.assertIn("Load `references/taste-foundations.md`", _body("frontend"))


class ComponentInterfaceTests(unittest.TestCase):
    def test_the_inventory_records_interfaces_and_the_deletion_test(self) -> None:
        body = _body("frontend")
        self.assertIn("each primitive's interface: props, events, slots, and the invariants a caller must know", body)
        self.assertIn("a wrapper earns a row only when deleting it would push its complexity into its callers", body)

    def test_decomposition_inlines_only_what_the_deletion_test_clears(self) -> None:
        passes = _packaged(PASSES)
        self.assertIn("Premature means the deletion test passes", passes)
        self.assertIn("stays, whatever its caller count", passes)


class RefactorVisualParityTests(unittest.TestCase):
    def test_structural_changes_need_a_before_and_after_capture(self) -> None:
        passes = _packaged(PASSES)
        self.assertIn("Green tests do not prove the render is unchanged", passes)
        self.assertIn(
            "capture the affected component before and after apply at one viewport and compare the two",
            passes,
        )
        self.assertIn("`omh-frontend/references/screenshot-loop.md`", passes)
        self.assertIn("needs a before/after capture at one viewport", _body("frontend-refactor"))


class OwnWordingTests(unittest.TestCase):
    def test_upstream_examples_are_not_reused(self) -> None:
        # Reconstruction, not paraphrase: the upstream guides' own examples stay out.
        taste = _packaged(TASTE)
        for phrase in ("webhook", "Published", "invitation", "interface's voice"):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, taste)
        self.assertNotIn("user@gm", _packaged(FORMS))


if __name__ == "__main__":
    unittest.main()

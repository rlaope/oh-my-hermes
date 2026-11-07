"""A capability family turned off is not routed to, offered, or hinted.

`omh capability-policy disable <family>` writes the family into
`<omh_home>/setup-profile.json`. These tests write that file with the CLI's own
writer in an isolated home and pin four things: a request for the family's
work neither dispatches nor offers it and the answer names the family and the
command that turns it back on; the per-turn route hint and the skill-candidate
line leave its skills out; a home with nothing turned off routes the whole
routing-precision corpus exactly as a call without a home does; and every
corpus route that names none of the turned-off skills is unchanged, so a
sibling family routes as before.

The routing-precision corpus carries no home state, so these are unit tests
over it rather than corpus cases.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest

from omh.capabilities.families import capability_family_projection
from omh.capabilities.toggles import (
    build_capability_policy,
    disabled_family_workflows,
    toggleable_family_ids,
    write_capability_policy,
)
from omh.paths import OmhPaths
from omh.plugin_bundle.omh import capability_off, skill_shortlist
from omh.plugin_bundle.omh.hooks import llm_hooks
from omh.plugin_bundle.omh.installed_skills import reset_installed_skill_cache
from omh.plugin_bundle.omh.tools import recommend_tool
from omh.quality.routing_precision import ROUTING_INTERVENTION_CASES, ROUTING_PRECISION_CASES
from omh.routing.chat import public_chat_route_payload, recommend_route_summary
from omh.skills.catalog import CORE_SKILLS, installable_skill_names, omh_skill_display_name
from omh.wrapper.contract import build_chat_interaction_payload

FAMILY = "learn_and_gather"
SIBLING = "retain_knowledge"
EXPLICIT = "/omh-web-research compare redis and valkey"
# A high-confidence clarify whose candidate, and whole shortlist, is in FAMILY.
PARAPHRASED = "research the latest vector database benchmarks and cite sources"
# Ranks `omh-lifecycle-growth` (FAMILY) first on the skill-candidate line.
CANDIDATE_MESSAGE = (
    "Activation fell after we changed the signup flow and new users churn in their first week. "
    "Where does retention break?"
)
_SELECTED = re.compile(r"selected=([A-Za-z0-9_-]+)")


def _paths(root: Path) -> OmhPaths:
    return OmhPaths(omh_home=root / "omh", hermes_home=root / "hermes")


def _home(root: Path, *families: str) -> OmhPaths:
    paths = _paths(root)
    paths.omh_home.mkdir(parents=True, exist_ok=True)
    write_capability_policy(paths, families)
    return paths


def _offered_skills(route: dict[str, object]) -> set[str]:
    """Every skill a route dispatches to, asks about, or lists."""
    names = {str(route.get("selected_skill") or ""), str(route.get("candidate_skill") or "")}
    names |= {str(row.get("skill") or "") for row in route.get("recommendations", []) if isinstance(row, dict)}
    handoff = route.get("candidate_handoff")
    if isinstance(handoff, dict):
        names |= {str(row.get("skill") or "") for row in handoff.get("candidates", []) if isinstance(row, dict)}
    plan = route.get("workflow_route_plan")
    if isinstance(plan, dict):
        names |= {str(step.get("skill") or "") for step in plan.get("steps", []) if isinstance(step, dict)}
    return names - {""}


def _corpus_messages() -> list[str]:
    return [case.message for case in (*ROUTING_PRECISION_CASES, *ROUTING_INTERVENTION_CASES)]


class PolicyReadTests(unittest.TestCase):
    def test_the_bundle_core_set_is_the_catalog_core_set(self) -> None:
        self.assertEqual(capability_off.CORE_SKILLS, frozenset(CORE_SKILLS))

    def test_each_family_turns_off_exactly_the_workflows_the_cli_reports(self) -> None:
        with TemporaryDirectory() as tmp:
            for family_id in toggleable_family_ids():
                paths = _home(Path(tmp) / family_id, family_id)
                expected = disabled_family_workflows(build_capability_policy([family_id]))
                read = capability_off.disabled_skill_families(paths.omh_home)
                installable = set(installable_skill_names())
                self.assertEqual(sorted(name for name in read if name in installable), list(expected), family_id)
                # Beyond the skills, only the coding family's conceptual
                # surfaces, which no install holds and the hint may name.
                self.assertLessEqual(
                    {name for name in read if name not in installable},
                    {"dynamic-workflow", "request-to-handoff", "executor selection", "coding runtime handoff"},
                )
                self.assertEqual(set(read.values()), {family_id})

    def test_the_sidecar_lists_every_installable_skill_under_its_family(self) -> None:
        projection = capability_family_projection()
        members = {
            workflow: str(family["id"])
            for family in projection["families"]
            for workflow in family["primary_workflows"]
        }
        mapping = projection["workflow_to_family"]
        self.assertEqual(
            {name: members.get(name) for name in installable_skill_names()},
            {name: mapping.get(name) for name in installable_skill_names()},
        )

    def test_no_policy_a_malformed_profile_or_an_unknown_family_turns_nothing_off(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertEqual(capability_off.disabled_skill_families(home), {})
            (home / "setup-profile.json").write_text("{not json", encoding="utf-8")
            self.assertEqual(capability_off.disabled_skill_families(home), {})
            (home / "setup-profile.json").write_text(
                json.dumps({"capability_policy": {"disabled_families": ["no_such_family"]}}), encoding="utf-8"
            )
            self.assertEqual(capability_off.disabled_skill_families(home), {})
            self.assertEqual(capability_off.disabled_skill_families(None), {})

    def test_two_homes_in_one_process_each_read_their_own_policy(self) -> None:
        # A profile-scoped OMH home is another file; nothing is carried across.
        with TemporaryDirectory() as tmp:
            off = _home(Path(tmp) / "off", FAMILY)
            on = _home(Path(tmp) / "on")
            self.assertIn("web-research", capability_off.disabled_skill_families(off.omh_home))
            self.assertEqual(capability_off.disabled_skill_families(on.omh_home), {})
            write_capability_policy(off, [])
            self.assertEqual(capability_off.disabled_skill_families(off.omh_home), {})


class RouterTests(unittest.TestCase):
    def test_an_explicit_request_is_answered_with_the_family_off_not_routed_elsewhere(self) -> None:
        self.assertEqual(public_chat_route_payload(EXPLICIT)["action"], "dispatch")
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), FAMILY)
            disabled = capability_off.disabled_skill_families(paths.omh_home)
            for message in (EXPLICIT, PARAPHRASED):
                route = public_chat_route_payload(message, disabled_skills=disabled)
                self.assertEqual(route["action"], "clarify", message)
                self.assertEqual(route["reason_code"], "capability_family_disabled", message)
                self.assertEqual(_offered_skills(route), {"oh-my-hermes"}, message)
                self.assertNotIn("candidate_handoff", route)
                self.assertNotIn("route_question", route)
                record = route["capability_family_off"]
                self.assertEqual(record["family"], FAMILY)
                self.assertEqual(record["enable_command"], f"omh capability-policy enable {FAMILY}")
                self.assertIn("Learn and gather", route["clarification"])
                self.assertNotIn("``", route["routing_instruction"])

    def test_the_chat_reply_names_the_family_and_the_command_that_turns_it_on(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), FAMILY)
            interaction = build_chat_interaction_payload(EXPLICIT, source="discord", paths=paths)
        response = interaction["chat_response"]
        self.assertEqual(response["kind"], "capability_family_off")
        self.assertIn("Learn and gather capability family is turned off", response["headline"])
        self.assertIn(f"omh capability-policy enable {FAMILY}", response["body"])
        self.assertEqual(
            [action["payload"] for action in response["actions"]],
            [{"command": f"omh capability-policy enable {FAMILY}"}],
        )
        self.assertNotIn("handoff", interaction)
        self.assertEqual(interaction["route"]["action"], "clarify")

    def test_turning_the_family_back_on_restores_the_route(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), FAMILY)
            write_capability_policy(paths, [])
            on = capability_off.disabled_skill_families(paths.omh_home)
            interaction = build_chat_interaction_payload(EXPLICIT, source="discord", paths=paths)
        self.assertEqual(public_chat_route_payload(EXPLICIT, disabled_skills=on), public_chat_route_payload(EXPLICIT))
        self.assertEqual(interaction["route"]["selected_skill"], "web-research")
        self.assertEqual(interaction["route"]["action"], "dispatch")

    def test_the_recommend_summary_carries_the_off_record(self) -> None:
        with TemporaryDirectory() as tmp:
            disabled = capability_off.disabled_skill_families(_home(Path(tmp), FAMILY).omh_home)
        summary = recommend_route_summary(EXPLICIT, disabled_skills=disabled)
        self.assertEqual(summary["action"], "clarify")
        self.assertEqual(summary["capability_family_off"]["family"], FAMILY)
        self.assertNotIn("capability_family_off", recommend_route_summary(EXPLICIT))


class CorpusTests(unittest.TestCase):
    """Over every routing-precision and intervention message, at the route the chat surfaces build on."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.plain = {message: public_chat_route_payload(message, source="discord") for message in _corpus_messages()}

    def test_a_home_with_nothing_off_routes_the_corpus_as_no_home_does(self) -> None:
        with TemporaryDirectory() as tmp:
            nothing_off = capability_off.disabled_skill_families(_home(Path(tmp)).omh_home)
        self.assertEqual(nothing_off, {})
        moved = [
            message
            for message, route in self.plain.items()
            if public_chat_route_payload(message, source="discord", disabled_skills=nothing_off) != route
        ]
        self.assertEqual(moved, [])

    def test_a_family_off_moves_only_the_routes_that_offered_it_and_never_offers_it(self) -> None:
        with TemporaryDirectory() as tmp:
            disabled = capability_off.disabled_skill_families(_home(Path(tmp), FAMILY).omh_home)
        off = set(disabled)
        touched = 0
        for message, plain in self.plain.items():
            route = public_chat_route_payload(message, source="discord", disabled_skills=disabled)
            self.assertEqual(_offered_skills(route) & off, set(), message)
            mentioned = _offered_skills(plain) | {
                skill for skill in off if f"`{skill}`" in f"{plain.get('clarification')}{plain.get('routing_prompt')}"
            }
            if mentioned & off:
                touched += 1
            else:
                # A sibling family's request, and every request that never
                # offered this family, routes byte for byte as before.
                self.assertEqual(route, plain, message)
        self.assertGreater(touched, 0)


class PreLlmCallTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_installed_skill_cache()
        skill_shortlist.reset_candidate_line_state()
        self.addCleanup(reset_installed_skill_cache)
        self.addCleanup(skill_shortlist.reset_candidate_line_state)

    def _context(self, paths: OmhPaths, message: str, session: str) -> str:
        skill_shortlist.reset_candidate_line_state()
        result = llm_hooks.pre_llm_call(
            user_message=message,
            session_id=session,
            omh_home=str(paths.omh_home),
            hermes_home=str(paths.hermes_home),
            is_first_turn=False,
        )
        return str((result or {}).get("context", ""))

    def test_a_turned_off_family_is_named_off_and_neither_hinted_nor_listed(self) -> None:
        with TemporaryDirectory() as tmp:
            bare = _paths(Path(tmp) / "bare")
            paths = _home(Path(tmp) / "off", FAMILY)

            self.assertIn("selected=ulw-research", self._context(bare, PARAPHRASED, "s-bare"))
            self.assertIn("omh-lifecycle-growth", self._context(bare, CANDIDATE_MESSAGE, "s-bare-c"))

            route = self._context(paths, PARAPHRASED, "s-route")
            candidates = self._context(paths, CANDIDATE_MESSAGE, "s-candidates")
            disabled = capability_off.disabled_skill_families(paths.omh_home)

        off_names = set(disabled) | {omh_skill_display_name(name) for name in disabled}
        self.assertIn("[OMH Capability Off]", route)
        self.assertIn(f"omh capability-policy enable {FAMILY}", route)
        self.assertEqual(set(_SELECTED.findall(route)) & off_names, set())
        self.assertNotIn("Skills that may fit this request", route)
        self.assertNotIn("omh-lifecycle-growth", candidates)
        self.assertIn("Skills that may fit this request", candidates)

    def test_nothing_off_and_a_sibling_off_render_what_a_home_without_policy_renders(self) -> None:
        with TemporaryDirectory() as tmp:
            bare = _paths(Path(tmp) / "bare")
            nothing_off = _home(Path(tmp) / "none")
            sibling_off = _home(Path(tmp) / "sibling", SIBLING)
            for index, message in enumerate((PARAPHRASED, CANDIDATE_MESSAGE, EXPLICIT)):
                expected = self._context(bare, message, f"s-{index}")
                self.assertEqual(self._context(nothing_off, message, f"s-{index}"), expected, message)
                self.assertEqual(self._context(sibling_off, message, f"s-{index}"), expected, message)


class RecommendToolTests(unittest.TestCase):
    def test_the_recommend_tool_lists_no_turned_off_skill(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), FAMILY)
            disabled = capability_off.disabled_skill_families(paths.omh_home)
            payload = json.loads(
                recommend_tool.omh_recommend_handler({"message": PARAPHRASED, "omh_home": str(paths.omh_home)})
            )
        self.assertEqual([row["skill"] for row in payload["recommendations"] if row["skill"] in disabled], [])
        self.assertEqual(payload["route"]["capability_family_off"]["family"], FAMILY)


if __name__ == "__main__":
    unittest.main()

"""A capability family turned off is not routed to, offered, or hinted.

`omh capability-policy disable <family>` writes the family into
`<omh_home>/setup-profile.json`. These tests write that file with the CLI's own
writer in an isolated home and pin five things: a request for the family's
work neither dispatches nor offers it, and one the router would have
dispatched (or that names the skill) is answered with the family and the
command that turns it back on; the per-turn route hint and the skill-candidate
line leave its skills out, and the turn's "off" block fires exactly where the
router's verdict does, never on a negative control; a home with nothing turned
off routes the whole routing-precision corpus exactly as a call without a home
does; and every corpus route that names none of the turned-off skills is
unchanged, so a sibling family routes as before.

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
from omh.mcp.bridge import _call_tool as mcp_call_tool
from omh.capabilities.toggles import (
    build_capability_policy,
    disabled_family_workflows,
    toggleable_family_ids,
    write_capability_policy,
)
from omh.paths import OmhPaths
from omh.plugin_bundle.omh import capability_off, skill_shortlist
from omh.plugin_bundle.omh.awareness import capability_family_verdict, capability_off_hint_context
from omh.plugin_bundle.omh.hooks import llm_hooks
from omh.plugin_bundle.omh.installed_skills import reset_installed_skill_cache
from omh.plugin_bundle.omh.tools import recommend_tool
from omh.plugin_bundle.omh.tools.route_answer_tool import _verify_digest
from omh.quality.routing_precision import ROUTING_INTERVENTION_CASES, ROUTING_PRECISION_CASES
from omh.routing.chat import public_chat_route_payload, recommend_route_summary, route_chat_message
from omh.routing.route_plan import public_workflow_identifier
from omh.skills.catalog import CORE_SKILLS, installable_skill_names, omh_skill_display_name
from omh.wrapper.contract import build_chat_interaction_payload
from omh.wrapper.localized_copy import CAPABILITY_NOTE_SENTENCES, ChatCopy, card_copy_voice_violations
from omh.wrapper.route_hints import build_chat_route_hint_payload

FAMILY = "learn_and_gather"
SIBLING = "retain_knowledge"
EXPLICIT = "/omh-web-research compare redis and valkey"
# A plain request the router dispatches to `ai-job-search` (FAMILY).
NATURAL = "Help with my job search for library coordinator roles in Boston."
# A high-confidence clarify whose candidate, and whole shortlist, is in FAMILY:
# the router is asking, so it asks an open question that notes the family.
PARAPHRASED = "research the latest vector database benchmarks and cite sources"
# Clarifies whose best match is in FAMILY; the re-review measured each handed
# to an unrelated skill (`ultraperf`, `ops-review`, `content-operator`,
# `ai-slop-cleaner`) when the next row was promoted.
REVIEWED_CLARIFIES = (
    "find recent papers on diffusion model distillation and summarize them",
    "우리 앱 경쟁사 분석 정리해줘",
)
# Negative controls the review measured the old hint block refusing.
NEGATIVE_CONTROLS = (
    ("operate_and_observe", "Explain what a cron job does."),
    ("plan_and_decide", "plan looks good, go ahead"),
    (FAMILY, 'Explain the phrase "our recruiting team runs a job search campaign".'),
    (FAMILY, "Draft a tweet about the HellaSwag results our paper reported"),
)
# A shortlist that loses `web-research` (FAMILY) but keeps its own candidate,
# so its route question is rebuilt with FAMILY off (review: digest mismatch).
QUESTION_MESSAGE = "set up web search"
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


def _spellings(disabled: dict[str, str]) -> set[str]:
    """Every name a route may carry for a turned-off skill: catalog, display and public."""
    return set(disabled) | {omh_skill_display_name(name) for name in disabled} | {
        public_workflow_identifier(name) for name in disabled
    }


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
            self.assertEqual(public_chat_route_payload(NATURAL)["selected_skill"], "ai-job-search")
            for message in (EXPLICIT, NATURAL):
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

    def test_a_clarify_on_a_turned_off_skill_asks_openly_and_notes_the_family(self) -> None:
        plain = public_chat_route_payload(PARAPHRASED)
        self.assertEqual((plain["action"], plain["confidence"], plain["explicit"]), ("clarify", "high", False))
        with TemporaryDirectory() as tmp:
            disabled = capability_off.disabled_skill_families(_home(Path(tmp), FAMILY).omh_home)
        for message in (PARAPHRASED, *REVIEWED_CLARIFIES):
            self.assertIn(public_chat_route_payload(message)["candidate_skill"], disabled, message)
            route = public_chat_route_payload(message, disabled_skills=disabled)
            # Not refused, and no stand-in from another family.
            self.assertNotIn("capability_family_off", route, message)
            self.assertEqual(route["action"], "clarify", message)
            self.assertEqual(route["reason_code"], "no_enabled_candidate", message)
            self.assertEqual(_offered_skills(route), {"oh-my-hermes"}, message)
            self.assertEqual(route["capability_family_note"]["family"], FAMILY, message)
            self.assertIn(f"omh capability-policy enable {FAMILY}", route["clarification"], message)
            self.assertNotIn("``", route["routing_instruction"])

    def test_the_note_reaches_the_reply_in_every_language(self) -> None:
        command = f"omh capability-policy enable {FAMILY}"
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), FAMILY)
            for message in REVIEWED_CLARIFIES:
                response = build_chat_interaction_payload(message, source="discord", paths=paths)["chat_response"]
                self.assertEqual(response["state"]["capability_family_note"]["enable_command"], command, message)
                # The visible body names the command once, in the body's language.
                self.assertEqual(response["body"].count(command), 1, message)
            korean = build_chat_interaction_payload(REVIEWED_CLARIFIES[1], source="discord", paths=paths)
        self.assertIn("기능 묶음이 꺼져 있습니다", korean["chat_response"]["body"])

    def test_the_family_sentences_pass_the_card_voice_gate(self) -> None:
        table = {"capability_note": {locale: ChatCopy(headline="", body=text) for locale, text in CAPABILITY_NOTE_SENTENCES.items()}}
        self.assertEqual(card_copy_voice_violations(table), ())

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
        off = _spellings(disabled)
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

    def test_the_turn_verdict_and_the_route_agree_on_every_message(self) -> None:
        # "off" (the turn's block) and "note" (the turn withholds its hint and
        # candidate line) are read from the same router pass `omh_interact` uses.
        with TemporaryDirectory() as tmp:
            disabled = capability_off.disabled_skill_families(_home(Path(tmp), FAMILY).omh_home)
        disagree = []
        verdicts = {"off": 0, "note": 0}
        for message in self.plain:
            route = public_chat_route_payload(message, disabled_skills=disabled)
            routed = (
                "off" if "capability_family_off" in route else "note" if "capability_family_note" in route else ""
            )
            turn = str(capability_family_verdict(message, disabled).get("verdict") or "")
            if turn != routed or bool(capability_off_hint_context(message, disabled)) != (routed == "off"):
                disagree.append(message)
            if routed:
                verdicts[routed] += 1
        self.assertEqual(disagree, [])
        self.assertGreater(verdicts["off"], 0)
        self.assertGreater(verdicts["note"], 0)

    def test_a_request_whose_best_match_is_off_is_never_offered_another_family(self) -> None:
        # Every intervention request the plain router dispatches to, or asks
        # about, a skill of the family turned off: answered "off", or asked
        # openly with the enable command named, never handed to a stand-in.
        checked = 0
        for family_id in toggleable_family_ids():
            disabled = capability_off.skill_families_for((family_id,))
            command = f"omh capability-policy enable {family_id}"
            for case in ROUTING_INTERVENTION_CASES:
                plain = self.plain[case.message]
                if plain["action"] not in {"clarify", "dispatch"}:
                    continue
                pick = plain["selected_skill"] if plain["action"] == "dispatch" else plain["candidate_skill"]
                if pick not in disabled:
                    continue
                checked += 1
                route = public_chat_route_payload(case.message, source="discord", disabled_skills=disabled)
                self.assertEqual(_offered_skills(route), {"oh-my-hermes"}, (family_id, case.id))
                record = route.get("capability_family_off") or route.get("capability_family_note")
                self.assertIsInstance(record, dict, (family_id, case.id))
                self.assertEqual(record["enable_command"], command, (family_id, case.id))
                if "capability_family_note" in route:
                    self.assertIn(command, route["clarification"], (family_id, case.id))
        self.assertGreater(checked, 0)

    def test_no_negative_control_is_answered_off_whichever_family_is_off(self) -> None:
        for family_id in toggleable_family_ids():
            disabled = capability_off.skill_families_for((family_id,))
            refused = [
                case.id for case in ROUTING_PRECISION_CASES if capability_off_hint_context(case.message, disabled)
            ]
            self.assertEqual(refused, [], family_id)


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

            asked = self._context(paths, NATURAL, "s-natural")
            route = self._context(paths, PARAPHRASED, "s-route")
            candidates = self._context(paths, CANDIDATE_MESSAGE, "s-candidates")
            disabled = capability_off.disabled_skill_families(paths.omh_home)

        off_names = _spellings(disabled)
        # The router dispatched it: the turn says the family is off, and
        # neither hints nor lists anything in its place.
        self.assertIn("[OMH Capability Off]", asked)
        self.assertIn(f"omh capability-policy enable {FAMILY}", asked)
        self.assertNotIn("selected=", asked)
        self.assertNotIn("Skills that may fit this request", asked)
        # The router only asked: the family is dropped, with no "off" block.
        self.assertNotIn("[OMH Capability Off]", route)
        self.assertEqual(set(_SELECTED.findall(route)) & off_names, set())
        self.assertNotIn("omh-lifecycle-growth", candidates)
        self.assertIn("Skills that may fit this request", candidates)

    def test_an_open_question_withholds_the_hint_and_the_candidate_line(self) -> None:
        # Every intervention request the router asks openly about because its
        # best match is off, for each family: the turn names no other skill
        # (the third review measured 53 of 140 that did) and adds no block.
        checked = 0
        with TemporaryDirectory() as tmp:
            for family_id in toggleable_family_ids():
                paths = _home(Path(tmp) / family_id, family_id)
                disabled = capability_off.disabled_skill_families(paths.omh_home)
                for case in ROUTING_INTERVENTION_CASES:
                    if "capability_family_note" not in public_chat_route_payload(case.message, disabled_skills=disabled):
                        continue
                    checked += 1
                    skill_shortlist.reset_candidate_line_state()
                    result = llm_hooks.pre_llm_call(
                        user_message=case.message,
                        session_id=f"note-{family_id}-{case.id}",
                        omh_home=str(paths.omh_home),
                        hermes_home=str(paths.hermes_home),
                        is_first_turn=True,
                    )
                    context = str((result or {}).get("context", ""))
                    self.assertEqual(_SELECTED.findall(context), [], (family_id, case.id))
                    self.assertNotIn("Skills that may fit this request", context, (family_id, case.id))
                    self.assertNotIn("[OMH Capability Off]", context, (family_id, case.id))
        self.assertGreater(checked, 0)

    def test_negative_controls_get_no_off_block_on_any_turn(self) -> None:
        with TemporaryDirectory() as tmp:
            for index, (family_id, message) in enumerate(NEGATIVE_CONTROLS):
                paths = _home(Path(tmp) / str(index), family_id)
                for first in (True, False):
                    skill_shortlist.reset_candidate_line_state()
                    result = llm_hooks.pre_llm_call(
                        user_message=message,
                        session_id=f"neg-{index}-{first}",
                        omh_home=str(paths.omh_home),
                        hermes_home=str(paths.hermes_home),
                        is_first_turn=first,
                    )
                    self.assertNotIn("[OMH Capability Off]", str((result or {}).get("context", "")), message)

    def test_an_unreadable_policy_is_reported_as_a_degradation(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            paths.omh_home.mkdir(parents=True)
            paths.setup_profile_path.write_text("{not json", encoding="utf-8")
            result = llm_hooks.pre_llm_call(
                user_message=NATURAL,
                session_id="s-bad-policy",
                omh_home=str(paths.omh_home),
                hermes_home=str(paths.hermes_home),
                is_first_turn=False,
            )
        components = (result or {}).get("omh_degradation", {}).get("components", [])
        self.assertIn("capability_policy_read", [row.get("component") for row in components])

    def test_nothing_off_and_a_sibling_off_render_what_a_home_without_policy_renders(self) -> None:
        with TemporaryDirectory() as tmp:
            bare = _paths(Path(tmp) / "bare")
            nothing_off = _home(Path(tmp) / "none")
            sibling_off = _home(Path(tmp) / "sibling", SIBLING)
            for index, message in enumerate((PARAPHRASED, CANDIDATE_MESSAGE, EXPLICIT, NATURAL)):
                expected = self._context(bare, message, f"s-{index}")
                self.assertEqual(self._context(nothing_off, message, f"s-{index}"), expected, message)
                self.assertEqual(self._context(sibling_off, message, f"s-{index}"), expected, message)


class OtherSurfaceTests(unittest.TestCase):
    def test_a_route_question_built_with_the_family_off_verifies(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), FAMILY)
            disabled = capability_off.disabled_skill_families(paths.omh_home)
            question = route_chat_message(QUESTION_MESSAGE, disabled_skills=disabled)["route_question"]
            plain = route_chat_message(QUESTION_MESSAGE)["route_question"]
            self.assertNotEqual(question["question_digest"], plain["question_digest"])
            verified = _verify_digest(
                {
                    "message": QUESTION_MESSAGE,
                    "question_digest": question["question_digest"],
                    "omh_home": str(paths.omh_home),
                }
            )
        self.assertEqual(verified[:3], (True, "matched", False))

    def test_the_mcp_recommend_tool_lists_no_turned_off_skill(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), FAMILY)
            disabled = capability_off.disabled_skill_families(paths.omh_home)
            result = mcp_call_tool(paths, "omh_recommend", {"message": EXPLICIT})
        payload = result["payload"]
        self.assertEqual([row["skill"] for row in payload["recommendations"] if row["skill"] in disabled], [])
        self.assertEqual(payload["route"]["capability_family_off"]["family"], FAMILY)

    def test_the_route_hint_command_neither_hints_nor_routes_the_family(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), FAMILY)
            disabled = capability_off.disabled_skill_families(paths.omh_home)
            asked = build_chat_route_hint_payload(NATURAL, paths=paths)
            hinted = build_chat_route_hint_payload(PARAPHRASED, paths=paths)
            bare = build_chat_route_hint_payload(PARAPHRASED)
        self.assertEqual(asked["route_hint"]["status"], "no_hint")
        self.assertEqual(asked["route_decision"]["action"], "clarify")
        self.assertIn("ulw-research", [hint["workflow"] for hint in bare["route_hint"]["hints"]])
        workflows = {hint["workflow"] for hint in hinted["route_hint"].get("hints", [])}
        self.assertEqual(workflows & _spellings(disabled), set())


class RecommendToolTests(unittest.TestCase):
    def test_the_recommend_tool_lists_no_turned_off_skill(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _home(Path(tmp), FAMILY)
            disabled = capability_off.disabled_skill_families(paths.omh_home)
            payload = json.loads(
                recommend_tool.omh_recommend_handler({"message": NATURAL, "omh_home": str(paths.omh_home)})
            )
        self.assertEqual([row["skill"] for row in payload["recommendations"] if row["skill"] in disabled], [])
        self.assertEqual(payload["route"]["capability_family_off"]["family"], FAMILY)


if __name__ == "__main__":
    unittest.main()

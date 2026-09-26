"""The route hint honours user trigger language packs (#1535).

A pack under `<omh-home>/routing/trigger-packs/<lang>.json` merges at the
scoring layer, so `omh recommend` and `route_decision` resolved a packed-language
message while the hint rail -- the surface a chat user actually sees -- stayed
silent, and one payload reported `no_hint` beside a high-confidence dispatch.

Every case here installs a pack for a language OMH ships no pack for, so a
positive result can only have come from the user pack.
"""

from __future__ import annotations

from contextlib import contextmanager
from inspect import signature
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from omh.ingress import CHAT_SOURCES
from omh.plugin_bundle.omh import awareness
from omh.routing import chat as routing_chat
from omh.routing import recommend as routing_recommend
from omh.wrapper.route_hints import build_chat_route_hint_payload
from _module_patch import patch_modules


# One phrase, in a language with no shipped pack, so nothing in the catalog or
# the hint rule table can match it by accident.
PACK_PHRASE = "hacer una revision de codigo"
PACK_SKILL = "code-review"
# A sentence in the same language that names no pack phrase. It is the negative
# control: adding a pack must not turn its language into a routing signal.
UNRELATED_SPANISH = "hoy hace buen tiempo en la playa"

_PACK_DOCUMENT = {
    "schema_version": "trigger_language_pack/v1",
    "language": "es",
    "skills": {PACK_SKILL: [PACK_PHRASE]},
}

# A phrase carrying no routing signal of its own, so whichever skill a pack
# points it at is the only reason the router can reach that skill.
NEUTRAL_PACK_PHRASE = "asunto especial de prueba"


def _pack_for(skill: str, phrase: str = NEUTRAL_PACK_PHRASE) -> dict[str, object]:
    return {
        "schema_version": "trigger_language_pack/v1",
        "language": "es",
        "skills": {skill: [phrase]},
    }


def _clear_pack_and_route_caches() -> None:
    """Drop every cache that could carry one OMH home's packs into another."""
    routing_recommend._trigger_pack_packs.cache_clear()
    routing_recommend._user_trigger_pack_phrases.cache_clear()
    routing_recommend._normalized_user_trigger_pack_phrases.cache_clear()
    routing_recommend._pack_trigger_token_holdback.cache_clear()
    routing_recommend._prepared_routable_definitions.cache_clear()
    routing_recommend._recommend_skills_cached.cache_clear()
    routing_chat._route_chat_message_cached.cache_clear()
    awareness._awareness_route_hint_cached.cache_clear()


@contextmanager
def _omh_home(pack: dict[str, object] | None):
    """Run the body against a temp OMH home, with or without a user pack."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp).resolve() / ".omh"
        if pack is not None:
            directory = root / "routing" / "trigger-packs"
            directory.mkdir(parents=True)
            (directory / f"{pack['language']}.json").write_text(
                json.dumps(pack), encoding="utf-8"
            )
        else:
            root.mkdir(parents=True)
        with patch.dict(os.environ, {"OMH_HOME": str(root)}):
            _clear_pack_and_route_caches()
            try:
                yield root
            finally:
                _clear_pack_and_route_caches()


class RouteHintTriggerPackTests(TestCase):
    def test_user_pack_phrase_hints_the_workflow_the_router_dispatches(self) -> None:
        with _omh_home(_PACK_DOCUMENT):
            payload = build_chat_route_hint_payload(PACK_PHRASE)

        route_hint = payload["route_hint"]
        decision = payload["route_decision"]
        self.assertEqual(route_hint["status"], "hinted")
        self.assertEqual(decision["action"], "dispatch")
        self.assertEqual(decision["selected_skill"], PACK_SKILL)
        # Compared through the public-name projection, never string to string:
        # hints pass through `_route_hint_with_public_workflow_names`, so for a
        # workflow whose two names differ the raw comparison would be red for a
        # correct hint -- and for `code-review`, where they coincide, it would
        # be green for an incorrect one. `test_pack_hint_follows_the_router_for_a_renamed_workflow`
        # is the case that separates them.
        self.assertEqual(
            route_hint["primary_workflow"],
            awareness._public_workflow_name(str(decision["selected_skill"])),
        )
        hints = route_hint["hints"]
        self.assertEqual([hint["id"] for hint in hints], ["user_trigger_pack"])
        self.assertEqual(hints[0]["matched_cues"], [PACK_PHRASE])

    def test_hint_and_route_decision_agree_for_every_chat_source(self) -> None:
        # The bug was one payload disagreeing with itself, so the contract is
        # pinned per source rather than for the default alone.
        with _omh_home(_PACK_DOCUMENT):
            for source in sorted(CHAT_SOURCES):
                with self.subTest(source=source):
                    payload = build_chat_route_hint_payload(PACK_PHRASE, source=source)
                    hinted = payload["route_hint"]["status"] == "hinted"
                    dispatches = payload["route_decision"]["action"] == "dispatch"
                    self.assertEqual(hinted, dispatches)

    def test_unrelated_sentence_in_the_packed_language_stays_no_hint(self) -> None:
        with _omh_home(_PACK_DOCUMENT):
            payload = build_chat_route_hint_payload(UNRELATED_SPANISH)

        self.assertEqual(payload["route_hint"]["status"], "no_hint")
        self.assertEqual(payload["route_hint"]["hints"], [])
        self.assertNotEqual(payload["route_decision"]["action"], "dispatch")

    def test_same_message_without_a_user_pack_keeps_todays_silence(self) -> None:
        # The shipped-language surface must not move: with no pack installed the
        # packed phrase is ordinary prose and the rail says so.
        with _omh_home(None):
            payload = build_chat_route_hint_payload(PACK_PHRASE)

        self.assertEqual(payload["route_hint"]["status"], "no_hint")
        self.assertEqual(payload["route_hint"]["hints"], [])

    def test_shipped_cue_message_is_unchanged_by_an_installed_pack(self) -> None:
        message = "do a code review"
        with _omh_home(None):
            without_pack = build_chat_route_hint_payload(message)
        with _omh_home(_PACK_DOCUMENT):
            with_pack = build_chat_route_hint_payload(message)

        self.assertEqual(without_pack["route_hint"], with_pack["route_hint"])

    def test_pack_hint_stores_no_text_beyond_the_pack_phrase(self) -> None:
        # The payload is deliberately text-free: lengths, a hash, cue labels
        # from a trigger table, and workflow names. A pack phrase is a trigger
        # table entry like any shipped cue; the rest of the sentence is the
        # person's prompt and must appear nowhere.
        private_words = ("acme", "staging", "hotfix")
        message = f"{PACK_PHRASE} en el repositorio acme de staging antes del hotfix"
        with _omh_home(_PACK_DOCUMENT):
            payload = build_chat_route_hint_payload(message)

        self.assertEqual(payload["route_hint"]["status"], "hinted")
        serialized = json.dumps(payload, ensure_ascii=False).casefold()
        for word in private_words:
            with self.subTest(word=word):
                self.assertNotIn(word, serialized)
        self.assertIn("matched cue labels", payload["privacy"]["stored_fields"])
        self.assertFalse(payload["privacy"]["raw_prompt_stored"])
        self.assertFalse(payload["privacy"]["raw_prompt_echoed"])

    def test_pack_hint_follows_the_router_for_a_renamed_workflow(self) -> None:
        # `ultrawork` is emitted publicly as `ulw-work`, so this pins the hint
        # against the router's selection through the projection rather than
        # against its spelling. It is also a workflow with no `_ROUTE_HINT_RULES`
        # entry, so it exercises the rule-less branch of the hint builder.
        with _omh_home(_pack_for("ultrawork")):
            payload = build_chat_route_hint_payload(NEUTRAL_PACK_PHRASE)

        decision = payload["route_decision"]
        self.assertEqual(decision["selected_skill"], "ultrawork")
        self.assertEqual(payload["route_hint"]["primary_workflow"], "ulw-work")
        self.assertEqual(
            payload["route_hint"]["primary_workflow"],
            awareness._public_workflow_name(str(decision["selected_skill"])),
        )

    def test_rule_less_workflow_still_gets_a_lane_and_a_next_action(self) -> None:
        # 25 routable skills have no `_ROUTE_HINT_RULES` entry, so the branch
        # that builds a hint without one is live rather than defensive. The lane
        # comes from the workflow's context card; the next action is the generic
        # one, because no rule exists to supply a specific one.
        for skill, lane in (("rust", "coding_handoff"), ("wiki", "retained_knowledge")):
            with self.subTest(skill=skill):
                with _omh_home(_pack_for(skill)):
                    payload = build_chat_route_hint_payload(NEUTRAL_PACK_PHRASE)

                self.assertEqual(payload["route_decision"]["selected_skill"], skill)
                hints = payload["route_hint"]["hints"]
                self.assertEqual([hint["id"] for hint in hints], ["user_trigger_pack"])
                self.assertEqual(hints[0]["lane"], lane)
                self.assertEqual(hints[0]["next_action"], "dispatch_to_workflow")
                self.assertEqual(hints[0]["fallback_action"], "open_picker_or_clarify")

    def test_pack_phrase_is_not_reported_as_the_cue_when_it_did_not_decide(self) -> None:
        # The pack phrase is present, but the English clause is what the router
        # weighed. The hint must still name the workflow the router picked, and
        # must not claim the pack phrase is why.
        message = f"{NEUTRAL_PACK_PHRASE} use the wiki skill"
        with _omh_home(_pack_for(PACK_SKILL)):
            payload = build_chat_route_hint_payload(message)

        self.assertEqual(payload["route_decision"]["selected_skill"], "wiki")
        self.assertEqual(payload["route_hint"]["primary_workflow"], "wiki")
        hint = payload["route_hint"]["hints"][0]
        self.assertEqual(hint["matched_cues"], ["user_trigger_pack"])
        self.assertNotIn(NEUTRAL_PACK_PHRASE, hint["reason"])
        self.assertIn("recognises part of this message", hint["reason"])

    def test_hint_silently_degrades_when_the_router_cannot_be_imported(self) -> None:
        # The bundle must run in a host with no installed `omh` package. A
        # `None` entry in `sys.modules` makes the deferred import raise the same
        # ImportError such a host raises, without unloading the router for the
        # rest of the process.
        with _omh_home(_PACK_DOCUMENT):
            with patch_modules({"omh.routing.chat": None}):
                self.assertEqual(awareness._user_trigger_pack_route_decision(PACK_PHRASE), {})
                awareness._awareness_route_hint_cached.cache_clear()
                degraded = awareness.awareness_route_hint(PACK_PHRASE)
            awareness._awareness_route_hint_cached.cache_clear()
            restored = awareness.awareness_route_hint(PACK_PHRASE)

        self.assertEqual(degraded["status"], "no_hint")
        self.assertEqual(degraded["hints"], [])
        self.assertEqual(restored["status"], "hinted")

    def test_bridge_survives_importing_the_cli_first(self) -> None:
        # `routing.chat` is the router and the router's import graph reaches the
        # plugin bundle, so a module-level import of the router inside the
        # bundle binds `None` whenever the CLI is imported first -- and fails
        # silently, because that looks exactly like a standalone plugin host.
        # This is the shape the CLI actually runs, so it is measured, not
        # reasoned about. `-P` keeps the repo-root shim off the path.
        with _omh_home(_PACK_DOCUMENT) as root:
            script = (
                "import omh.cli\n"
                "from omh.wrapper.route_hints import build_chat_route_hint_payload\n"
                f"payload = build_chat_route_hint_payload({PACK_PHRASE!r})\n"
                "print(payload['route_hint']['status'], payload['route_decision']['action'])\n"
            )
            completed = subprocess.run(
                [sys.executable, "-P", "-c", script],
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, "OMH_HOME": str(root)},
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "hinted dispatch")


class UserTriggerPackRouteDecisionTests(TestCase):
    def test_phrase_match_reports_the_pack_skill_and_the_authored_phrase(self) -> None:
        with _omh_home(_PACK_DOCUMENT):
            self.assertEqual(
                routing_recommend.user_trigger_pack_phrase_match(PACK_PHRASE),
                (PACK_SKILL, PACK_PHRASE),
            )
            self.assertEqual(
                routing_recommend.user_trigger_pack_phrase_match(UNRELATED_SPANISH),
                ("", ""),
            )

    def test_phrase_match_is_empty_without_user_packs(self) -> None:
        with _omh_home(None):
            self.assertEqual(
                routing_recommend.user_trigger_pack_phrase_match(PACK_PHRASE), ("", "")
            )

    def test_bridge_reports_the_routers_own_decision(self) -> None:
        with _omh_home(_PACK_DOCUMENT):
            decision = routing_chat.user_trigger_pack_route_hint(PACK_PHRASE)
            route = routing_chat.route_chat_message(PACK_PHRASE, limit=1)["route_decision"]

        self.assertEqual(decision["workflow"], route["selected_skill"])
        self.assertEqual(decision["matched_phrase"], PACK_PHRASE)
        self.assertEqual(route["action"], "dispatch")

    def test_bridge_is_empty_for_a_message_no_user_pack_names(self) -> None:
        with _omh_home(_PACK_DOCUMENT):
            self.assertEqual(routing_chat.user_trigger_pack_route_hint(UNRELATED_SPANISH), {})

    def test_bridge_drops_the_phrase_when_another_skill_wins(self) -> None:
        with _omh_home(_pack_for(PACK_SKILL)):
            decision = routing_chat.user_trigger_pack_route_hint(
                f"{NEUTRAL_PACK_PHRASE} use the wiki skill"
            )

        self.assertEqual(decision["workflow"], "wiki")
        self.assertEqual(decision["matched_phrase"], "")

    def test_command_pack_phrases_match_on_a_word_boundary(self) -> None:
        # `_prepare_definition` sorts `/omh` into `command_trigger_phrases` and
        # scores it with a word-boundary pattern, so the gate must not use plain
        # containment: `abre /omh. ahora` contains the phrase and scores no pack
        # trigger for the skill.
        with _omh_home(_pack_for(PACK_SKILL, phrase="/omh")):
            self.assertEqual(
                routing_recommend.user_trigger_pack_phrase_match("usa /omh para esto"),
                (PACK_SKILL, "/omh"),
            )
            self.assertEqual(
                routing_recommend.user_trigger_pack_phrase_match("abre /omh. ahora"),
                ("", ""),
            )

    def test_bridge_takes_no_chat_source_parameter(self) -> None:
        # The bundle has no source to pass -- neither `awareness_route_hint` nor
        # `llm_hooks.pre_llm_call` carries one -- so a defaulted `source` here
        # would answer for `generic` while the wrapper's `route_decision` was
        # computed for the real source. If source becomes decision-relevant,
        # thread it through the rail rather than restoring the default.
        parameters = signature(routing_chat.user_trigger_pack_route_hint).parameters
        self.assertEqual(list(parameters), ["message"])

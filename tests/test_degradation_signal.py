"""Distinguishability proofs for the four `#637 treatment` broad-exception sites.

Each of the four sites used to relabel a delegated-call failure as a normal
result. `tests/test_broad_exception_policy.py` records the verdict; this module
proves it against behaviour: per site, genuine absence and call failure must
produce payloads a caller can tell apart.

Harness rule: both awareness `lru_cache`s are cleared in `setUp` and every case
uses a unique message. Without both, a failure case can be served a payload
cached by a healthy case and pass for the wrong reason.
"""

from __future__ import annotations

import json
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh import awareness as awareness_module
from omh.plugin_bundle.omh.awareness import awareness_route_hint
from omh.plugin_bundle.omh.context_brief import build_context_brief
from omh.plugin_bundle.omh.degradation import (
    COMPONENT_CATALOG_QUESTION_CLASSIFIER,
    COMPONENT_LOCALIZED_ROUTING_TEXT,
    COMPONENT_LOOP_ROUTE_HINT_ASSESSMENT,
    COMPONENT_RUNTIME_STATUS_READ,
    DEGRADATION_CHAT_NOTE,
    MAX_DEGRADATION_COMPONENTS,
    OMH_DEGRADATION_SCHEMA_VERSION,
    UNKNOWN_COMPONENT,
    degradation_chat_note,
    degradation_component,
    degradation_payload,
    safe_error_type,
)
from omh.plugin_bundle.omh.hooks import llm_hooks as llm_hooks_module
from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call
from omh.wrapper import contract as contract_module
from omh.wrapper.contract import build_chat_interaction_payload
from omh.wrapper.route_hints import build_chat_route_hint_payload

# `AGENTS.md` evidence-boundary phrasing, carried verbatim into every degraded
# surface. A degradation marker observes a local call failure and nothing more.
CLAIM_BOUNDARY_PHRASE = "not execution, review, CI, merge-readiness, or merge evidence"

LOCALE_BOOM = "locale-boom"
LOOP_BOOM = "loop-boom"
CATALOG_BOOM = "catalog-boom"
STATUS_BOOM = "status-boom"


def component_labels(block: object) -> list[str]:
    """Return the component labels of a degradation block, or []."""
    if not isinstance(block, dict):
        return []
    return [str(row["component"]) for row in block.get("components", [])]


def nested_degradation_blocks(payload: object) -> list[dict]:
    """Return every nested `degradation` block reachable inside `payload`."""
    found: list[dict] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "degradation" and isinstance(value, dict):
                found.append(value)
            else:
                found.extend(nested_degradation_blocks(value))
    elif isinstance(payload, list):
        for item in payload:
            found.extend(nested_degradation_blocks(item))
    return found


class DegradationSignalTestCase(unittest.TestCase):
    def setUp(self) -> None:
        awareness_module._awareness_context_matches_message_cached.cache_clear()
        awareness_module._awareness_route_hint_cached.cache_clear()

    def locale_failure(self) -> mock._patch:
        return mock.patch.object(
            awareness_module,
            "_prepare_routing_text",
            mock.Mock(side_effect=RuntimeError(LOCALE_BOOM)),
        )

    def locale_absent(self) -> mock._patch:
        return mock.patch.object(awareness_module, "_prepare_routing_text", None)

    def loop_failure(self) -> mock._patch:
        return mock.patch.object(
            awareness_module,
            "_assess_loopability",
            mock.Mock(side_effect=RuntimeError(LOOP_BOOM)),
        )

    def loop_absent(self) -> mock._patch:
        return mock.patch.object(awareness_module, "_assess_loopability", None)

    def catalog_failure(self) -> mock._patch:
        return mock.patch(
            "omh.routing.catalog_questions.is_skill_catalog_question",
            side_effect=RuntimeError(CATALOG_BOOM),
        )

    def catalog_absent(self) -> mock._patch:
        return mock.patch.dict(sys.modules, {"omh.routing.catalog_questions": None})

    def status_failure(self) -> mock._patch:
        return mock.patch.object(
            llm_hooks_module, "read_omh_activity", side_effect=RuntimeError(STATUS_BOOM)
        )

    def call_pre_llm(self, message: str, **kwargs: object) -> dict | None:
        with TemporaryDirectory() as temp_dir:
            return pre_llm_call(
                omh_home=temp_dir,
                hermes_home=temp_dir,
                user_message=message,
                is_first_turn=False,
                **kwargs,
            )

    def assert_block_is_well_formed(self, block: dict) -> None:
        self.assertEqual(block["schema_version"], OMH_DEGRADATION_SCHEMA_VERSION)
        self.assertTrue(block["degraded"])
        self.assertFalse(block["privacy"]["error_message_stored"])
        self.assertFalse(block["privacy"]["raw_prompt_stored"])
        self.assertFalse(block["privacy"]["raw_prompt_echoed"])
        self.assertIn(CLAIM_BOUNDARY_PHRASE, block["claim_boundary"])


class SiteDistinguishabilityTests(DegradationSignalTestCase):
    def test_site_1_localized_routing_text_absence_differs_from_call_failure(self) -> None:
        message = "show token cost latency run history for this site-one automation loop"

        with self.locale_absent():
            absent = awareness_route_hint(message)
        self.setUp()
        with self.locale_failure():
            failed = awareness_route_hint(message)

        # Genuine absence: a standalone host without the locale pack looks
        # exactly like it does today.
        self.assertNotIn("degradation", absent)
        # Call failure: same routing answer, but now classified and surfaced.
        self.assertEqual(failed["primary_workflow"], absent["primary_workflow"])
        block = failed["degradation"]
        self.assertEqual(component_labels(block), [COMPONENT_LOCALIZED_ROUTING_TEXT])
        self.assertEqual(block["components"][0]["error_type"], "RuntimeError")
        self.assert_block_is_well_formed(block)

        serialized = json.dumps(failed, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(LOCALE_BOOM, serialized)
        self.assertNotIn(message, serialized)

    def test_site_2_loop_assessment_absence_differs_from_call_failure(self) -> None:
        message = "/loop fix the flaky site-two integration test"

        with self.loop_absent():
            absent = awareness_route_hint(message)
        self.setUp()
        with self.loop_failure():
            failed = awareness_route_hint(message)

        self.assertNotIn("degradation", absent)
        self.assertEqual(failed["primary_workflow"], "ulw-loop")
        self.assertEqual(failed["primary_next_action"], absent["primary_next_action"])
        block = failed["degradation"]
        self.assertEqual(component_labels(block), [COMPONENT_LOOP_ROUTE_HINT_ASSESSMENT])
        self.assertEqual(block["components"][0]["error_type"], "RuntimeError")
        self.assert_block_is_well_formed(block)

        serialized = json.dumps(failed, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(LOOP_BOOM, serialized)
        self.assertNotIn(message, serialized)

    def test_site_3_catalog_classifier_import_absence_emits_nothing(self) -> None:
        message = "what workflows are available in omh for site three"

        with self.catalog_absent():
            absent = build_context_brief(message)

        # Principle 2: a host where the package is genuinely absent produces
        # the same output as today. The import guard emits no degradation.
        self.assertNotIn("degradation", absent)
        self.assertIn("catalog_question", absent)

    def test_site_3_catalog_classifier_call_failure_is_surfaced(self) -> None:
        message = "what workflows are available in omh for site three call failure"

        with self.catalog_failure():
            failed = build_context_brief(message)

        self.assertIn("catalog_question", failed)
        block = failed["degradation"]
        self.assertEqual(component_labels(block), [COMPONENT_CATALOG_QUESTION_CLASSIFIER])
        self.assertEqual(block["components"][0]["error_type"], "RuntimeError")
        self.assert_block_is_well_formed(block)

        serialized = json.dumps(failed, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(CATALOG_BOOM, serialized)
        self.assertNotIn(message, serialized)

    def test_site_3_call_failure_on_a_non_catalog_message_is_visible(self) -> None:
        # The sharpest consequence: today this failure produces no key at all,
        # so it is completely invisible. The classifier answered "no" either
        # way, and only the degradation block tells the two apart.
        message = "tell me a short joke about site-three penguins"

        healthy = build_context_brief(message)
        self.setUp()
        with self.catalog_failure():
            failed = build_context_brief(message)

        self.assertNotIn("catalog_question", healthy)
        self.assertNotIn("degradation", healthy)
        self.assertNotIn("catalog_question", failed)
        self.assertEqual(component_labels(failed["degradation"]), [COMPONENT_CATALOG_QUESTION_CLASSIFIER])

    def test_site_4_runtime_status_read_absence_differs_from_call_failure(self) -> None:
        # Genuine absence: a real empty runtime home has nothing to report.
        healthy = self.call_pre_llm("tell me a short joke about site-four otters")
        self.assertIsNone(healthy)

        self.setUp()
        with self.status_failure():
            failed = self.call_pre_llm("tell me a short joke about site-four badgers")

        self.assertIsNotNone(failed)
        assert failed is not None
        block = failed["omh_degradation"]
        self.assertEqual(component_labels(block), [COMPONENT_RUNTIME_STATUS_READ])
        self.assertEqual(block["components"][0]["error_type"], "RuntimeError")
        self.assert_block_is_well_formed(block)
        # PM-1: no status panel is implied. The status block stays gated on the
        # runtime fields, which are still absent.
        self.assertNotIn("runs", failed)
        self.assertNotIn("[OMH] Native bridge status context.", failed["context"])

        serialized = json.dumps(failed, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(STATUS_BOOM, serialized)


class PreLlmCallDegradationTests(DegradationSignalTestCase):
    def test_happy_path_carries_no_degradation_key_anywhere(self) -> None:
        payload = self.call_pre_llm("show token cost latency run history for this healthy automation loop")

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertNotIn("omh_degradation", payload)
        self.assertNotIn("[OMH Degraded]", payload["context"])
        self.assertNotIn("degradation", json.dumps(payload, sort_keys=True))

    def test_empty_and_whitespace_messages_do_not_raise(self) -> None:
        # Pins the tuple conversion of the empty/whitespace guard inside
        # `_awareness_context_matches_message_cached`. A bare `False` there
        # makes the `[0]` accessor raise `TypeError: 'bool' object is not
        # subscriptable`, and this call site in `pre_llm_call` has no enclosing
        # try/except, so the exception would escape into the Hermes host.
        for message in ("", "   "):
            with self.subTest(message=message):
                self.setUp()
                try:
                    payload = self.call_pre_llm(message)
                except TypeError as exc:  # pragma: no cover - the regression itself
                    self.fail(f"pre_llm_call raised TypeError on an empty message: {exc}")
                self.assertIsNone(payload)

    def test_site_1_failure_flips_a_non_matching_message_from_none_to_a_payload(self) -> None:
        # The B1 headline case. Today this message produces `None`; with the
        # locale-pack call failing, the failure is the only thing in the
        # payload, and it reaches the top level with no nested block at all.
        message = "raconte-moi une blague vraiment courte s'il te plait"

        healthy = self.call_pre_llm(message)
        self.assertIsNone(healthy)

        self.setUp()
        with self.locale_failure():
            failed = self.call_pre_llm(message)

        self.assertIsNotNone(failed)
        assert failed is not None
        self.assertEqual(component_labels(failed["omh_degradation"]), [COMPONENT_LOCALIZED_ROUTING_TEXT])
        # `awareness_route_hint` was never called on this turn, so there is no
        # nested producer. This is why the invariant is containment, not equality.
        self.assertNotIn("omh_context_brief", failed)
        self.assertEqual(nested_degradation_blocks(failed), [])

    def test_suppressed_awareness_stays_none_even_when_site_1_fails(self) -> None:
        with self.locale_failure():
            payload = self.call_pre_llm(
                "raconte-moi une autre blague courte", include_omh_awareness=False
            )

        self.assertIsNone(payload)

    def test_degraded_context_line_is_bounded_and_last_on_an_otherwise_normal_turn(self) -> None:
        # PM-4: site 1 fails on a message that *does* match awareness, so the
        # payload is non-`None` for the pre-existing reason and the model
        # simply receives one extra line.
        message = "이 자동화 루프의 토큰 비용 기록을 보여줘"

        with self.locale_failure():
            payload = self.call_pre_llm(message)

        self.assertIsNotNone(payload)
        assert payload is not None
        context = payload["context"]
        parts = context.split("\n\n")
        self.assertEqual(context.count("[OMH Degraded]"), 1)
        self.assertTrue(parts[-1].startswith("[OMH Degraded] components="))
        self.assertIn(COMPONENT_LOCALIZED_ROUTING_TEXT, parts[-1])
        self.assertIn(CLAIM_BOUNDARY_PHRASE, parts[-1])
        # Component labels only; error types stay in the structured payload.
        self.assertNotIn("RuntimeError", parts[-1])
        self.assertNotIn(LOCALE_BOOM, parts[-1])
        self.assertNotIn(message, parts[-1])
        # The awareness primer is still present, so the payload did not appear
        # only because of the degradation.
        self.assertIn("omh_context_brief", payload)

    def test_two_sites_degrading_in_one_request_are_both_reported(self) -> None:
        message = "raconte-moi une blague courte sur deux pannes"

        with self.locale_failure(), self.status_failure():
            payload = self.call_pre_llm(message)

        self.assertIsNotNone(payload)
        assert payload is not None
        block = payload["omh_degradation"]
        self.assertEqual(
            component_labels(block),
            sorted([COMPONENT_LOCALIZED_ROUTING_TEXT, COMPONENT_RUNTIME_STATUS_READ]),
        )
        self.assertEqual(block["component_count"], 2)
        self.assertFalse(block["components_truncated"])

    def test_runtime_status_read_is_top_level_only(self) -> None:
        # Case (b) for the containment invariant: this component has no nested
        # producer by construction, so equality is unsatisfiable.
        message = "show token cost latency run history for this top-level-only loop"

        with self.status_failure():
            payload = self.call_pre_llm(message)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertIn(COMPONENT_RUNTIME_STATUS_READ, component_labels(payload["omh_degradation"]))
        for block in nested_degradation_blocks(payload):
            self.assertNotIn(COMPONENT_RUNTIME_STATUS_READ, component_labels(block))


class MultiLevelMergeTests(DegradationSignalTestCase):
    MATCHING_MESSAGE = "이 자동화 루프의 토큰 비용과 지연 기록을 보여줘"

    def test_nested_route_hint_block_is_non_empty_on_a_matching_message(self) -> None:
        # Non-vacuity, asserted first and at its specific nesting level. This
        # is the only assertion that proves the route-hint producer was wired;
        # without it the containment check below is satisfied by an entirely
        # unimplemented change.
        with self.locale_failure():
            payload = self.call_pre_llm(self.MATCHING_MESSAGE)

        self.assertIsNotNone(payload)
        assert payload is not None
        nested = payload["omh_context_brief"]["route_hint"]["degradation"]
        self.assertIn(COMPONENT_LOCALIZED_ROUTING_TEXT, component_labels(nested))
        self.assertTrue(component_labels(nested))

        brief_level = payload["omh_context_brief"]["degradation"]
        self.assertIn(COMPONENT_LOCALIZED_ROUTING_TEXT, component_labels(brief_level))

        top_level = payload["omh_degradation"]
        self.assertIn(COMPONENT_LOCALIZED_ROUTING_TEXT, component_labels(top_level))

    def test_every_nested_block_is_contained_in_the_top_level_union(self) -> None:
        # Containment, never equality: the top level is a union superset, and
        # the converse does not hold.
        with self.locale_failure(), self.status_failure():
            payload = self.call_pre_llm(self.MATCHING_MESSAGE + " 두 번째")

        self.assertIsNotNone(payload)
        assert payload is not None
        top = set(component_labels(payload["omh_degradation"]))
        blocks = nested_degradation_blocks(payload)
        self.assertTrue(blocks, "Expected at least one nested degradation block.")
        for block in blocks:
            labels = set(component_labels(block))
            self.assertTrue(labels, "A nested degradation block must not be empty.")
            self.assertLessEqual(labels, top)

    def test_the_nested_route_hint_block_is_not_stripped_when_embedded(self) -> None:
        # `omh_route_hint/v1` must stay byte-identical read standalone or
        # embedded inside `omh_context_brief/v1`.
        message = "show token cost latency run history for this embedded loop"

        with self.locale_failure():
            standalone = awareness_route_hint(message)
        self.setUp()
        with self.locale_failure():
            brief = build_context_brief(message)

        self.assertEqual(
            json.dumps(brief["route_hint"]["degradation"], sort_keys=True),
            json.dumps(standalone["degradation"], sort_keys=True),
        )

    def test_repeated_identical_calls_produce_byte_equal_degraded_payloads(self) -> None:
        # Cache-hit determinism: the assertion an ambient collector would fail.
        message = "show token cost latency run history for this deterministic loop"

        with self.locale_failure():
            first = self.call_pre_llm(message)
            second = self.call_pre_llm(message)

        self.assertIsNotNone(first)
        assert first is not None and second is not None
        self.assertEqual(
            json.dumps(first["omh_degradation"], sort_keys=True),
            json.dumps(second["omh_degradation"], sort_keys=True),
        )
        self.assertEqual(
            json.dumps(first["omh_context_brief"]["route_hint"]["degradation"], sort_keys=True),
            json.dumps(second["omh_context_brief"]["route_hint"]["degradation"], sort_keys=True),
        )

    def test_cached_degradation_block_survives_caller_mutation(self) -> None:
        # `_copy_awareness_route_hint_payload` avoids generic deepcopy, so the
        # nested block needs its own branch or a caller poisons the cache.
        message = "show token cost latency run history for this poisoned loop"

        with self.locale_failure():
            first = awareness_route_hint(message)
            first["degradation"]["degraded"] = "mutated"
            first["degradation"]["components"][0]["component"] = "mutated"
            first["degradation"]["privacy"]["mode"] = "mutated"

            second = awareness_route_hint(message)

        self.assertTrue(second["degradation"]["degraded"])
        self.assertEqual(component_labels(second["degradation"]), [COMPONENT_LOCALIZED_ROUTING_TEXT])
        self.assertEqual(second["degradation"]["privacy"]["mode"], "metadata_only")


class WrapperSurfaceDegradationTests(DegradationSignalTestCase):
    """The Discord/Slack-facing surfaces must show the signal, not swallow it.

    `_response_for_hint` rebuilds `omh_route_hint/v1` from an explicit key
    whitelist, so a key added upstream is dropped unless it is listed. These
    cases pin both directions: healthy renders exactly as before, degraded
    renders a reader-actionable line plus the structured block.
    """

    ROUTE_HINT_MESSAGE = "Users report a wrapper-surface checkout bug"
    INTRO_MESSAGE = "Explain OMH to me"

    def setUp(self) -> None:
        super().setUp()
        contract_module._build_chat_interaction_payload_cached.cache_clear()

    def test_a_healthy_route_hint_renders_exactly_todays_key_set_and_text(self) -> None:
        payload = build_chat_route_hint_payload(self.ROUTE_HINT_MESSAGE, source="discord")

        state_route_hint = payload["chat_response"]["state"]["route_hint"]
        # Non-emptiness first: without it every assertion below passes on an
        # empty payload and proves nothing.
        self.assertTrue(state_route_hint)
        self.assertTrue(payload["chat_response"]["body"].strip())
        self.assertEqual(state_route_hint["primary_workflow"], "feedback-triage")

        self.assertNotIn("degradation", payload["route_hint"])
        self.assertNotIn("degradation", state_route_hint)
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(DEGRADATION_CHAT_NOTE, serialized)
        self.assertNotIn("omh_degradation/v1", serialized)

    def test_a_degraded_route_hint_renders_the_note_and_the_whitelisted_block(self) -> None:
        with self.locale_failure():
            payload = build_chat_route_hint_payload(self.ROUTE_HINT_MESSAGE, source="discord")

        response = payload["chat_response"]
        block = payload["route_hint"]["degradation"]
        self.assertEqual(component_labels(block), [COMPONENT_LOCALIZED_ROUTING_TEXT])
        self.assert_block_is_well_formed(block)

        # The whitelist rebuild must carry the block through unchanged.
        self.assertEqual(
            json.dumps(response["state"]["route_hint"]["degradation"], sort_keys=True),
            json.dumps(block, sort_keys=True),
        )
        # The routing answer itself is unchanged; only the signal is added.
        self.assertEqual(response["state"]["route_hint"]["primary_workflow"], "feedback-triage")

        body = response["body"]
        self.assertTrue(body.strip())
        self.assertIn(DEGRADATION_CHAT_NOTE, body)
        self.assertTrue(body.endswith(DEGRADATION_CHAT_NOTE))
        self.assertIn(DEGRADATION_CHAT_NOTE, response["messenger_rendering"]["body_text"])

    def test_a_degraded_route_hint_renders_the_note_once_in_the_messenger_safe_body(self) -> None:
        """The note survives the render-profile transform on an opted-in generic surface.

        The route-hint messenger body is now profile-resolved, so the note is
        appended before the safe-body transform runs. It must land in the safe
        text exactly once: neither dropped by the transform nor re-appended
        after it.
        """
        message = "Users report a wrapper-surface messenger rendering bug"

        with self.locale_failure():
            payload = build_chat_route_hint_payload(
                message,
                source="generic",
                source_metadata={"render_profile": "limited_markdown"},
            )

        rendering = payload["chat_response"]["messenger_rendering"]
        self.assertEqual(rendering["render_profile"], "limited_markdown")
        body_text = rendering["body_text"]
        self.assertTrue(body_text.strip())
        self.assertEqual(body_text.count(DEGRADATION_CHAT_NOTE), 1)
        self.assertTrue(body_text.endswith(DEGRADATION_CHAT_NOTE))
        self.assertEqual(rendering["fallback_body_text"].count(DEGRADATION_CHAT_NOTE), 1)
        block_text = "\n".join(str(block.get("text", "")) for block in rendering["body_blocks"])
        self.assertTrue(block_text.strip())
        self.assertEqual(block_text.count(DEGRADATION_CHAT_NOTE), 1)

        serialized = json.dumps(rendering, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(message, serialized)
        self.assertNotIn(LOCALE_BOOM, serialized)
        self.assertNotIn(COMPONENT_LOCALIZED_ROUTING_TEXT, serialized)

    def test_a_degraded_route_hint_never_renders_request_or_exception_message_text(self) -> None:
        with self.locale_failure():
            payload = build_chat_route_hint_payload(self.ROUTE_HINT_MESSAGE, source="discord")

        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self.assertIn(DEGRADATION_CHAT_NOTE, serialized)
        self.assertNotIn(self.ROUTE_HINT_MESSAGE, serialized)
        self.assertNotIn(LOCALE_BOOM, serialized)
        # Component labels are engineer-facing, so they stay in the structured
        # block and never reach the rendered chat text.
        self.assertNotIn(COMPONENT_LOCALIZED_ROUTING_TEXT, payload["chat_response"]["body"])

    def test_a_healthy_context_brief_interaction_renders_exactly_todays_text(self) -> None:
        payload = build_chat_interaction_payload(self.INTRO_MESSAGE, source="discord")

        response = payload["chat_response"]
        self.assertEqual(response["kind"], "context_brief")
        brief = response["state"]["context_brief"]
        self.assertTrue(brief)
        self.assertTrue(response["body"].strip())

        self.assertNotIn("degradation", brief)
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(DEGRADATION_CHAT_NOTE, serialized)
        self.assertNotIn("omh_degradation/v1", serialized)

    def test_a_degraded_context_brief_interaction_renders_the_note_and_the_block(self) -> None:
        with self.locale_failure():
            payload = build_chat_interaction_payload(self.INTRO_MESSAGE, source="discord")

        response = payload["chat_response"]
        self.assertEqual(response["kind"], "context_brief")
        block = response["state"]["context_brief"]["degradation"]
        self.assertEqual(component_labels(block), [COMPONENT_LOCALIZED_ROUTING_TEXT])
        self.assert_block_is_well_formed(block)

        body = response["body"]
        self.assertTrue(body.strip())
        self.assertIn(DEGRADATION_CHAT_NOTE, body)
        # Placed before the boundary line, so the reader sees the caveat and
        # the evidence boundary in the same block of text.
        self.assertLess(body.index(DEGRADATION_CHAT_NOTE), body.index("Boundary:"))

        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(LOCALE_BOOM, serialized)
        self.assertNotIn(COMPONENT_LOCALIZED_ROUTING_TEXT, body)

    def test_the_chat_note_is_empty_for_every_non_degraded_input(self) -> None:
        for value in ({}, None, "", [], {"degraded": False}, {"components": []}):
            with self.subTest(repr(value)):
                self.assertEqual(degradation_chat_note(value), "")
        self.assertEqual(
            degradation_chat_note(degradation_payload([(COMPONENT_LOCALIZED_ROUTING_TEXT, "RuntimeError")])),
            DEGRADATION_CHAT_NOTE,
        )


class DegradationPayloadUnitTests(unittest.TestCase):
    def test_empty_input_produces_no_block(self) -> None:
        self.assertEqual(degradation_payload([]), {})

    def test_identical_pairs_are_deduped(self) -> None:
        block = degradation_payload(
            [
                (COMPONENT_LOCALIZED_ROUTING_TEXT, "RuntimeError"),
                (COMPONENT_LOCALIZED_ROUTING_TEXT, "RuntimeError"),
            ]
        )

        self.assertEqual(block["component_count"], 1)
        self.assertEqual(len(block["components"]), 1)

    def test_distinct_error_types_on_one_component_are_kept(self) -> None:
        block = degradation_payload(
            [
                (COMPONENT_LOCALIZED_ROUTING_TEXT, "ValueError"),
                (COMPONENT_LOCALIZED_ROUTING_TEXT, "RuntimeError"),
            ]
        )

        self.assertEqual(block["component_count"], 2)
        self.assertEqual(
            [row["error_type"] for row in block["components"]],
            ["RuntimeError", "ValueError"],
        )

    def test_ordering_is_deterministic_regardless_of_input_order(self) -> None:
        pairs = [
            (COMPONENT_RUNTIME_STATUS_READ, "OSError"),
            (COMPONENT_CATALOG_QUESTION_CLASSIFIER, "RuntimeError"),
            (COMPONENT_LOCALIZED_ROUTING_TEXT, "ValueError"),
        ]

        forward = degradation_payload(pairs)
        backward = degradation_payload(list(reversed(pairs)))

        self.assertEqual(
            json.dumps(forward, sort_keys=True), json.dumps(backward, sort_keys=True)
        )
        self.assertEqual(
            component_labels(forward),
            [
                COMPONENT_CATALOG_QUESTION_CLASSIFIER,
                COMPONENT_LOCALIZED_ROUTING_TEXT,
                COMPONENT_RUNTIME_STATUS_READ,
            ],
        )

    def test_the_cap_truncates_the_tail_and_reports_the_pre_cap_total(self) -> None:
        pairs = [
            (component, f"Error{index}")
            for index in range(3)
            for component in (
                COMPONENT_LOCALIZED_ROUTING_TEXT,
                COMPONENT_LOOP_ROUTE_HINT_ASSESSMENT,
                COMPONENT_CATALOG_QUESTION_CLASSIFIER,
                COMPONENT_RUNTIME_STATUS_READ,
            )
        ]

        block = degradation_payload(pairs)

        self.assertEqual(block["component_count"], 12)
        self.assertEqual(len(block["components"]), MAX_DEGRADATION_COMPONENTS)
        self.assertTrue(block["components_truncated"])

    def test_an_out_of_set_label_is_coerced_without_raising(self) -> None:
        row = degradation_component("typo_component", "RuntimeError")
        self.assertEqual(row["component"], UNKNOWN_COMPONENT)

        block = degradation_payload([("typo_component", "RuntimeError")])
        self.assertEqual(component_labels(block), [UNKNOWN_COMPONENT])

    def test_safe_error_type_is_bounded_and_falls_back(self) -> None:
        self.assertEqual(safe_error_type(""), "Exception")
        self.assertEqual(safe_error_type(None), "Exception")
        self.assertEqual(safe_error_type("RuntimeError"), "RuntimeError")
        # Whitespace, colons, and punctuation are stripped, so an exception
        # *message* accidentally passed here cannot survive as readable text.
        self.assertEqual(safe_error_type("Runtime Error: secret token 123!"), "RuntimeErrorsecrettoken123")
        self.assertEqual(len(safe_error_type("E" * 200)), 80)


if __name__ == "__main__":
    unittest.main()

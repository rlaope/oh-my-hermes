"""Shadow, decline, refuse and replay for the route question (#1817).

Four contracts, each pinned from both sides:

- the mode is read from OMH config, carried with where it came from, and an
  unreadable mode is `unknown`, never the default;
- in `shadow` -- the default -- every negative-control payload is byte for
  byte the payload built with the mode seam patched out;
- the decline predicate and the `invalid_answer` verdict each accept what they
  should and refuse what they should;
- one report joins recorded answers to recorded routes and every rate in it is
  a well-formed reported rate.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.paths import resolve_paths  # noqa: E402
from omh.plugin_bundle.omh.route_answer_consistency import (  # noqa: E402
    INVALID_ANSWER_ARGMAX,
    INVALID_ANSWER_COVERAGE,
    INVALID_ANSWER_MASS,
    invalid_answer_reasons,
)
from omh.plugin_bundle.omh.route_answer_store import build_route_answer_record, write_route_answer  # noqa: E402
from omh.plugin_bundle.omh.route_question_mode import (  # noqa: E402
    read_route_question_mode,
    route_question_config_path,
)
from omh.plugin_bundle.omh.tools.route_answer_tool import omh_route_answer_handler  # noqa: E402
from omh.quality.reported_rate import reported_rate_shape_errors  # noqa: E402
from omh.quality.route_question_shadow_report import (  # noqa: E402
    DECLARED_TURN_SHAPE,
    JOIN_RULES,
    ROUTE_QUESTION_OBSERVED_EVENT,
    build_route_question_shadow_report,
    format_route_question_shadow_report,
)
from omh.wrapper.sessions import ROUTE_QUESTION_OBSERVED_EVENT as SESSION_EVENT  # noqa: E402
from omh.quality.routing_precision import (  # noqa: E402
    ROUTE_QUESTION_ASKED,
    ROUTING_INTERVENTION_CASES,
    ROUTING_PRECISION_CASES,
)
from omh.quality.routing_question_corpus import (  # noqa: E402
    INTERVENTION_CORPUS,
    NEGATIVE_CONTROL_CORPUS,
    ROUTING_QUESTION_ANSWERS_SCHEMA_VERSION,
    answer_records_from_rows,
    build_routing_question_corpus,
    score_routing_question_answers,
)
from omh.routing.chat import route_chat_message, route_question_decline_reason  # noqa: E402
from omh.routing.route_question import ROUTE_QUESTION_DECLINE_REASONS, message_digest  # noqa: E402
from omh.wrapper.contract import build_chat_interaction_payload  # noqa: E402
from omh.wrapper.route_hints import build_chat_route_hint_payload  # noqa: E402

UNDECIDABLE_MESSAGE = "почему сборка падает на main"


def _write_mode(omh_home: Path, content: str) -> None:
    path = route_question_config_path(omh_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


class RouteQuestionModeReaderTests(unittest.TestCase):
    def _read(self, content: str | None) -> dict[str, str]:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            if content is not None:
                _write_mode(home, content)
            return read_route_question_mode(home)

    def test_an_absent_file_is_the_documented_default_and_says_so(self) -> None:
        self.assertEqual(self._read(None), {"mode": "shadow", "mode_source": "default"})

    def test_a_configured_mode_is_read_from_the_omh_config(self) -> None:
        self.assertEqual(self._read('{"mode": "off"}'), {"mode": "off", "mode_source": "omh_config"})
        self.assertEqual(self._read('{"mode": "shadow"}'), {"mode": "shadow", "mode_source": "omh_config"})

    def test_a_file_that_cannot_be_understood_is_unknown_never_the_default(self) -> None:
        for content, error in (
            ("{not json", "not_json"),
            ('["off"]', "not_an_object"),
            ("{}", "missing_mode"),
            ('{"mode": "OFF"}', "unsupported_value"),
            ('{"mode": true}', "unsupported_value"),
            ('{"mode": "on"}', "on_not_available"),
            ('{"mode": "off", "pad": "' + "x" * 5000 + '"}', "too_large"),
        ):
            with self.subTest(content=content[:30]):
                self.assertEqual(
                    self._read(content),
                    {"mode": "unknown", "mode_source": "omh_config", "mode_error": error},
                )

    def test_a_config_path_that_is_not_a_readable_file_is_unknown(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            route_question_config_path(home).mkdir(parents=True)
            reading = read_route_question_mode(home)
        self.assertEqual(reading["mode"], "unknown")
        self.assertEqual(reading["mode_error"], "unreadable")


def _seam_removed():
    """Patch the mode seam out: no config is read and no mode is applied."""
    reader = patch(
        "omh.wrapper.contract.read_route_question_mode",
        return_value={"mode": "shadow", "mode_source": "not_read"},
    )
    applier = patch("omh.wrapper.contract.apply_route_question_mode", side_effect=lambda route, mode: route)
    return reader, applier


class ShadowPayloadIsTheRoutersPayloadTests(unittest.TestCase):
    """`shadow` changes nothing: a difference check against the mode seam removed.

    For every negative-control case, the payload under the default mode, an
    explicit `shadow` and an unreadable config is compared, as the bytes the
    `omh_interact` tool emits (`json.dumps(..., sort_keys=True)`), with the
    payload built while the mode seam -- reading the config and applying the
    mode -- is patched out. That pins "shadow does not move the payload"
    without freezing what the router produces: a routing change elsewhere
    moves both sides together.
    """

    @staticmethod
    def _emitted(payload: object) -> str:
        return json.dumps(payload, sort_keys=True)

    def _payloads(self, config: str | None, *, seam: bool) -> dict[str, str]:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            if config is not None:
                _write_mode(root / "omh", config)
            paths = resolve_paths(omh_home=root / "omh", hermes_home=root / "hermes")

            def build() -> dict[str, str]:
                return {
                    case.id: self._emitted(build_chat_interaction_payload(case.message, source="discord", paths=paths))
                    for case in ROUTING_PRECISION_CASES
                }

            if seam:
                return build()
            reader, applier = _seam_removed()
            with reader, applier as applied:
                payloads = build()
            self.assertTrue(applied.called)
            return payloads

    def test_default_shadow_and_unreadable_equal_the_seam_removed_for_every_negative_control(self) -> None:
        baseline = self._payloads(None, seam=False)
        self.assertEqual(len(baseline), len(ROUTING_PRECISION_CASES))
        self.assertTrue(any('"route_question"' in emitted for emitted in baseline.values()))
        for config in (None, '{"mode": "shadow"}', "{not json"):
            with self.subTest(config=config):
                moved = sorted(
                    case_id
                    for case_id, emitted in self._payloads(config, seam=True).items()
                    if emitted != baseline[case_id]
                )
                self.assertEqual(moved, [])

    def test_recording_a_shadow_question_does_not_change_the_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(omh_home=root / "omh", hermes_home=root / "hermes")
            recorded = 0
            for case in ROUTING_PRECISION_CASES:
                with self.subTest(case=case.id):
                    baseline = build_chat_interaction_payload(case.message, source="discord", paths=paths)
                    observations: list[dict[str, object]] = []
                    observed = build_chat_interaction_payload(
                        case.message, source="discord", paths=paths, _route_question_sink=observations
                    )
                    self.assertEqual(self._emitted(observed), self._emitted(baseline))
                    self.assertEqual(len(observations), int("route_question" in baseline["route"]))
                    recorded += len(observations)
            self.assertGreater(recorded, 0)

    def test_off_records_the_question_before_withholding_it(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(omh_home=root / "omh", hermes_home=root / "hermes")
            shadow = build_chat_interaction_payload(UNDECIDABLE_MESSAGE, source="discord", paths=paths)
            self.assertIn("route_question", shadow["route"])
            _write_mode(root / "omh", '{"mode": "off"}')
            observations: list[dict[str, object]] = []
            off = build_chat_interaction_payload(
                UNDECIDABLE_MESSAGE, source="discord", paths=paths, _route_question_sink=observations
            )
        self.assertNotIn("route_question", off["route"])
        self.assertEqual(len(observations), 1)
        observation = observations[0]
        self.assertEqual(observation["route_question"]["mode"], "off")
        self.assertEqual(observation["route_question"]["mode_source"], "omh_config")
        self.assertTrue(observation["route_question"]["built"])
        self.assertFalse(observation["route_question"]["asked"])
        self.assertEqual(observation["message_sha256"], message_digest(UNDECIDABLE_MESSAGE))
        shadow["route"].pop("route_question")
        self.assertEqual(self._emitted(off), self._emitted(shadow))

    def test_the_tool_emits_the_same_bytes_in_shadow_and_without_the_seam(self) -> None:
        from omh.plugin_bundle.omh.tools.chat_tool import omh_interact_handler

        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            env = {"OMH_HOME": str(root / ".omh"), "HERMES_HOME": str(root / ".hermes")}
            messages = [case.message for case in ROUTING_PRECISION_CASES[::10]]

            def emit() -> list[str]:
                with patch.dict(os.environ, env):
                    return [
                        omh_interact_handler({"message": message, "source": "discord", "record_session": False})
                        for message in messages
                    ]

            shadow = emit()
            reader, applier = _seam_removed()
            with reader, applier:
                removed = emit()
        self.assertEqual(shadow, removed)
        self.assertTrue(any('"route_question"' in text for text in shadow))

    def test_off_withholds_the_question_and_changes_nothing_else(self) -> None:
        """The negative half, over every negative control: `off` moves the payload only by the question."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_mode(root / "omh", '{"mode": "off"}')
            off_paths = resolve_paths(omh_home=root / "omh", hermes_home=root / "hermes")
            shadow_paths = resolve_paths(omh_home=root / "other", hermes_home=root / "hermes")
            asked = 0
            for case in ROUTING_PRECISION_CASES:
                off = build_chat_interaction_payload(case.message, source="discord", paths=off_paths)
                shadow = build_chat_interaction_payload(case.message, source="discord", paths=shadow_paths)
                self.assertNotIn("route_question", off["route"])
                if "route_question" in shadow["route"]:
                    asked += 1
                    shadow["route"].pop("route_question")
                self.assertEqual(self._emitted(off), self._emitted(shadow), case.id)
        self.assertGreater(asked, 0)

    def test_unknown_keeps_the_question_on_the_route_hint(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_mode(root / "omh", "{not json")
            paths = resolve_paths(omh_home=root / "omh", hermes_home=root / "hermes")
            hint = build_chat_route_hint_payload(UNDECIDABLE_MESSAGE, source="discord", paths=paths)
        self.assertIsInstance(hint["route_question"], dict)

    def test_off_withholds_the_question_on_the_route_hint_too(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_mode(root / "omh", '{"mode": "off"}')
            paths = resolve_paths(omh_home=root / "omh", hermes_home=root / "hermes")
            hint = build_chat_route_hint_payload(UNDECIDABLE_MESSAGE, source="discord", paths=paths)
            unset = build_chat_route_hint_payload(UNDECIDABLE_MESSAGE, source="discord", paths=None)
        self.assertIsNone(hint["route_question"])
        self.assertEqual(hint["route_question_answerers"], [])
        self.assertIsInstance(unset["route_question"], dict)


class DeclinePredicateTests(unittest.TestCase):
    def _reason(self, message: str) -> str:
        return route_question_decline_reason(route_chat_message(message, source="discord"), message)

    def test_each_reason_fires_on_its_own_shape(self) -> None:
        self.assertEqual(self._reason("thanks, got it"), "acknowledgement")
        self.assertEqual(self._reason("lgtm"), "one_word_reply")
        self.assertEqual(self._reason("Apologize for being late."), "no_candidate")
        self.assertEqual(self._reason("please run doctor"), "single_candidate")

    def test_a_question_with_something_to_decide_is_kept(self) -> None:
        for message in (
            "remember to close the file handle in the finally block",
            "review my patch for the export feature",
            # One word is not nothing to decide: a one-word workflow request
            # routes to several candidates, and only a listed approval word
            # (`lgtm` above) is a reply.
            "refactor",
            "deploy",
            "debug",
            "review",
            "migrate",
            "optimize",
            # One "word" by whitespace, a whole sentence in fact: a script
            # without spaces is not a one-word reply.
            "移行を説明する長い文書を書いて",
        ):
            with self.subTest(message=message):
                self.assertEqual(self._reason(message), "")

    def test_a_route_without_a_question_has_nothing_to_decline(self) -> None:
        route = route_chat_message("run omh doctor", source="discord")
        self.assertNotIn("route_question", route)
        self.assertEqual(route_question_decline_reason(route, "run omh doctor"), "")

    def test_both_shipped_corpora_pin_the_predicate_in_both_directions(self) -> None:
        for corpus in (ROUTING_PRECISION_CASES, ROUTING_INTERVENTION_CASES):
            expectations = {case.expected_route_question for case in corpus if case.expected_route_question}
            with self.subTest(corpus=type(corpus[0]).__name__):
                self.assertIn(ROUTE_QUESTION_ASKED, expectations)
                self.assertTrue(expectations & set(ROUTE_QUESTION_DECLINE_REASONS))
        # Every decline reason is pinned by at least one shipped case.
        pinned = {
            case.expected_route_question
            for corpus in (ROUTING_PRECISION_CASES, ROUTING_INTERVENTION_CASES)
            for case in corpus
        }
        self.assertLessEqual(set(ROUTE_QUESTION_DECLINE_REASONS), pinned)

    def test_the_corpus_verdict_reads_the_predicate(self) -> None:
        """A case's own row fails when the predicate disagrees with it."""
        from omh.quality.routing_precision import _evaluate_intervention_case, _evaluate_precision_case

        declined = next(case for case in ROUTING_PRECISION_CASES if case.id == "route-question-declines-one-word-reply")
        kept = next(case for case in ROUTING_INTERVENTION_CASES if case.id == "route-question-keeps-multi-candidate-clarify")
        self.assertTrue(_evaluate_precision_case(declined, source="discord")["passed"])
        self.assertTrue(_evaluate_intervention_case(kept, source="discord")["passed"])
        with patch("omh.quality.routing_precision.route_question_decline_reason", return_value=""):
            row = _evaluate_precision_case(declined, source="discord")
        self.assertFalse(row["passed"])
        self.assertIn("expected route question one_word_reply, observed asked", row["issues"])
        with patch("omh.quality.routing_precision.route_question_decline_reason", return_value="single_candidate"):
            self.assertFalse(_evaluate_intervention_case(kept, source="discord")["passed"])


class InvalidAnswerTests(unittest.TestCase):
    def test_each_contradiction_is_named(self) -> None:
        options = ["plan", "code-review", "none"]
        self.assertEqual(
            invalid_answer_reasons("plan", {"plan": 0.7, "none": 0.3}, options=options),
            (INVALID_ANSWER_COVERAGE,),
        )
        self.assertEqual(
            invalid_answer_reasons("plan", {"plan": 0.7, "code-review": 0.2, "none": 0.2}, options=options),
            (INVALID_ANSWER_MASS,),
        )
        self.assertEqual(
            invalid_answer_reasons("none", {"plan": 0.6, "code-review": 0.1, "none": 0.3}, options=options),
            (INVALID_ANSWER_ARGMAX,),
        )
        self.assertEqual(
            invalid_answer_reasons("code-review", {"plan": 0.7, "none": 0.2}, options=options),
            (INVALID_ANSWER_COVERAGE, INVALID_ANSWER_MASS, INVALID_ANSWER_ARGMAX),
        )

    def test_a_consistent_answer_or_no_distribution_is_not_invalid(self) -> None:
        options = ["plan", "code-review", "none"]
        self.assertEqual(invalid_answer_reasons("plan", {"plan": 0.6, "code-review": 0.3, "none": 0.1}, options=options), ())
        # Rounded percentages and a tie at the top are not contradictions.
        self.assertEqual(invalid_answer_reasons("plan", {"plan": 0.335, "code-review": 0.335, "none": 0.335}), ())
        self.assertEqual(invalid_answer_reasons("plan", None, options=options), ())
        # Without the question's options coverage cannot be judged.
        self.assertEqual(invalid_answer_reasons("plan", {"plan": 0.7, "none": 0.3}), ())

    def test_the_mass_tolerance_sits_between_rounding_and_a_real_miss(self) -> None:
        self.assertEqual(invalid_answer_reasons("plan", {"plan": 0.605, "none": 0.4}), ())
        self.assertEqual(invalid_answer_reasons("plan", {"plan": 0.62, "none": 0.4}), (INVALID_ANSWER_MASS,))
        self.assertEqual(invalid_answer_reasons("plan", {"plan": 0.58, "none": 0.4}), (INVALID_ANSWER_MASS,))

    def test_accepted_says_whether_coverage_was_checked(self) -> None:
        common = {"question_digest": "ab" * 32, "answered_by": "main_model", "route_choice": "plan"}
        unchecked = build_route_answer_record(**common, choice_probabilities={"plan": 0.7, "none": 0.3})
        checked = build_route_answer_record(
            **common, choice_probabilities={"plan": 0.7, "none": 0.3}, question_options=["plan", "none"]
        )
        nothing_to_check = build_route_answer_record(**common)
        self.assertEqual((unchecked["answer_verdict"], unchecked["coverage_checked"]), ("accepted", False))
        self.assertEqual((checked["answer_verdict"], checked["coverage_checked"]), ("accepted", True))
        self.assertTrue(nothing_to_check["coverage_checked"])

    def test_the_store_records_the_verdict_and_the_mode(self) -> None:
        record = build_route_answer_record(
            question_digest="ab" * 32,
            answered_by="main_model",
            route_choice="none",
            choice_probabilities={"plan": 0.9, "none": 0.1},
            mode_reading={"mode": "shadow", "mode_source": "default"},
        )
        self.assertEqual(record["answer_verdict"], "invalid_answer")
        self.assertEqual(record["invalid_answer_reasons"], ["argmax"])
        self.assertEqual((record["mode"], record["mode_source"]), ("shadow", "default"))
        accepted = build_route_answer_record(question_digest="ab" * 32, answered_by="main_model", route_choice="none")
        self.assertEqual(accepted["answer_verdict"], "accepted")
        self.assertNotIn("invalid_answer_reasons", accepted)
        # A caller that read no config does not get a default.
        self.assertEqual((accepted["mode"], accepted["mode_source"]), ("unknown", "not_read"))


class RouteAnswerToolModeAndVerdictTests(unittest.TestCase):
    def _call(self, root: Path, arguments: dict[str, object]) -> dict[str, object]:
        with patch.dict(os.environ, {"OMH_HOME": str(root / ".omh"), "HERMES_HOME": str(root / ".hermes")}):
            return json.loads(omh_route_answer_handler(dict(arguments), session_id="session-1"))

    def _question(self) -> dict[str, object]:
        return route_chat_message(UNDECIDABLE_MESSAGE, source="hermes")["route_question"]

    def test_every_record_carries_the_mode_read_from_the_home_it_lands_in(self) -> None:
        question = self._question()
        for config, expected in (
            (None, {"mode": "shadow", "mode_source": "default"}),
            ('{"mode": "off"}', {"mode": "off", "mode_source": "omh_config"}),
            ("{broken", {"mode": "unknown", "mode_source": "omh_config", "mode_error": "not_json"}),
        ):
            with self.subTest(config=config), TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                if config is not None:
                    _write_mode(root / ".omh", config)
                payload = self._call(
                    root,
                    {"question_digest": question["question_digest"], "answered_by": "main_model", "route_choice": "none"},
                )
                self.assertEqual(payload["status"], "recorded")
                record = payload["record"]
                self.assertEqual(
                    {key: record[key] for key in ("mode", "mode_source", "mode_error") if key in record},
                    expected,
                )

    def test_a_mode_argument_from_the_caller_is_not_read(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            payload = self._call(
                root,
                {
                    "question_digest": self._question()["question_digest"],
                    "answered_by": "main_model",
                    "route_choice": "none",
                    "mode": "off",
                    "mode_source": "omh_config",
                },
            )
        self.assertEqual((payload["record"]["mode"], payload["record"]["mode_source"]), ("shadow", "default"))

    def test_a_self_contradicting_answer_is_refused_as_no_opinion_and_counted(self) -> None:
        question = self._question()
        options = sorted(question["questions"]["route_choice"]["options"])
        skill = next(option for option in options if option != "none")
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            payload = self._call(
                root,
                {
                    "question_digest": question["question_digest"],
                    "answered_by": "main_model",
                    "route_choice": skill,
                    # Only two of the offered options: coverage, verified
                    # against the question the message re-derives.
                    "choice_probabilities": {skill: 0.8, "none": 0.2},
                    "message": UNDECIDABLE_MESSAGE,
                    "source": "hermes",
                },
            )
            written = list((root / ".omh" / "runtime" / "route-questions").glob("*.json"))
        self.assertEqual(payload["status"], "invalid_answer")
        self.assertIn("continue the turn", payload["error"])
        self.assertEqual(payload["record"]["invalid_answer_reasons"], ["coverage"])
        self.assertEqual(len(written), 1)


class ScorerInvalidAnswerTests(unittest.TestCase):
    """The same verdict on the offline scorer, over both shipped corpora."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = build_routing_question_corpus(source="discord")

    def _item(self, corpus: str) -> dict[str, object]:
        return next(
            item
            for item in self.corpus["items"]
            if item["corpus"] == corpus and len(item["question"]["questions"]["route_choice"]["options"]) >= 3
        )

    def _row(self, item: dict[str, object], choice: str, probabilities: dict[str, float]) -> dict[str, object]:
        return {
            "schema_version": ROUTING_QUESTION_ANSWERS_SCHEMA_VERSION,
            "arm": "probe",
            "case_id": item["case_id"],
            "answers": {"route_choice": {"choice": choice, "probabilities": probabilities}},
        }

    def test_an_invalid_answer_is_no_opinion_in_both_corpora(self) -> None:
        for corpus in (NEGATIVE_CONTROL_CORPUS, INTERVENTION_CORPUS):
            with self.subTest(corpus=corpus):
                item = self._item(corpus)
                options = sorted(item["question"]["questions"]["route_choice"]["options"])
                even = {option: 1 / len(options) for option in options}
                valid = self._row(item, options[0], even)
                invalid = self._row(item, options[0], {options[0]: 0.9})
                for rows, expected_invalid, expected_answered in (([valid], 0, 1), ([invalid], 1, 0)):
                    score = score_routing_question_answers(self.corpus, answer_records_from_rows(rows))
                    arm = score["arms"]["probe"]
                    self.assertEqual(arm["invalid_answer"], expected_invalid)
                    self.assertEqual(arm["answered"], expected_answered)
                    self.assertEqual(len(score["invalid_answers"]), expected_invalid)
                    for field in ("invalid_answer_rate", "overroute_rate", "missed_rate", "workflow_accuracy"):
                        self.assertEqual(reported_rate_shape_errors(arm[field]), ())
                    self.assertIn("invalid_answer", arm["overroute_rate"]["excluded"])


class ShadowReportTests(unittest.TestCase):
    def _record_route(self, base: list[str], message: str) -> None:
        status, _, stderr = run_cli(base + ["chat", "route", "--source", "discord", "--record", message])
        self.assertEqual(status, 0, stderr)

    def _answer(self, root: Path, message: str, arguments: dict[str, object]) -> dict[str, object]:
        question = route_chat_message(message, source="discord")["route_question"]
        with patch.dict(os.environ, {"OMH_HOME": str(root / ".omh"), "HERMES_HOME": str(root / ".hermes")}):
            return json.loads(
                omh_route_answer_handler(
                    {"question_digest": question["question_digest"], "message": message, "source": "discord", **arguments},
                    session_id="session-report",
                )
            )

    def test_the_report_joins_answers_to_recorded_routes_and_every_rate_is_well_formed(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            kept = "review my patch for the export feature"
            declined = "please run doctor"
            self._record_route(base, kept)
            self._record_route(base, declined)
            self._record_route(base, "run omh doctor")
            deterministic = route_chat_message(kept, source="discord")
            self.assertEqual(
                self._answer(root, kept, {"answered_by": "main_model", "route_choice": deterministic["candidate_skill"], "fits": {deterministic["candidate_skill"]: 0.6}})["status"],
                "recorded",
            )
            self.assertEqual(
                self._answer(root, declined, {"answered_by": "main_model", "route_choice": "none", "choice_probabilities": {"doctor": 0.9, "none": 0.1}})["status"],
                "invalid_answer",
            )
            status, stdout, stderr = run_cli(
                base + ["chat", "route-questions", "report", "--since", "", "--model", "gpt-6-astra", "--json"]
            )
            self.assertEqual(status, 0, stderr)
            report = json.loads(stdout)
            status, text, stderr = run_cli(base + ["chat", "route-questions", "report", "--since", ""], output_json=False)
            self.assertEqual(status, 0, stderr)

        self.assertEqual(report["routes"]["recorded_routes"], 3)
        self.assertEqual(report["routes"]["built"], 2)
        self.assertEqual(report["routes"]["mode"], {"shadow": 3})
        self.assertEqual(report["routes"]["decline_reason"], {"single_candidate": 1})
        self.assertEqual(report["answers"]["mode"], {"shadow": 2})
        rates = report["rates"]
        for name in ("decline_rate", "invalid_answer_rate", "agreement_rate"):
            self.assertEqual(reported_rate_shape_errors(rates[name]), (), name)
        self.assertEqual((rates["decline_rate"]["numerator"], rates["decline_rate"]["denominator"]), (1, 2))
        self.assertEqual((rates["invalid_answer_rate"]["numerator"], rates["invalid_answer_rate"]["denominator"]), (1, 2))
        self.assertEqual((rates["agreement_rate"]["numerator"], rates["agreement_rate"]["denominator"]), (1, 1))
        cost = report["cost"]
        self.assertTrue(cost["estimate"])
        self.assertEqual(cost["turn_shape"], DECLARED_TURN_SHAPE)
        self.assertFalse(cost["turn_shape"]["observed_by_omh"])
        self.assertEqual(cost["per_turn_usd"], round((192_000 * 10.0 + 5_600 * 50.0) / 1_000_000, 6))
        self.assertEqual(cost["turns_in_window"], 3)
        self.assertIn("declared from kerpopule/hermes-jev-skills", text)
        self.assertIn("not priced (no_model_named)", text)
        self.assertEqual(report["routes"]["by_lane"], {"route_record": 3, "wrapper_session": 0})
        self.assertEqual(report["join_rules"], list(JOIN_RULES))
        self.assertIn("Join rule: The join ignores the route's source surface", text)
        self.assertIn("one request routed twice counts twice", " ".join(report["join_rules"]))

    def test_a_live_interaction_turn_is_a_route_the_report_joins(self) -> None:
        """The live lane: `omh_interact` with its default session recording."""
        from omh.plugin_bundle.omh.tools.chat_tool import omh_interact_handler

        kept = "review my patch for the export feature"
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            env = {"OMH_HOME": str(root / ".omh"), "HERMES_HOME": str(root / ".hermes")}
            with patch.dict(os.environ, env):
                interaction = json.loads(omh_interact_handler({"message": kept, "source": "discord"}))
                decided = json.loads(omh_interact_handler({"message": "run omh doctor", "source": "discord"}))
            self.assertIn("route_question", interaction["route"])
            self.assertNotIn("route_question", decided["route"])
            candidate = interaction["route"]["candidate_skill"]
            self.assertEqual(
                self._answer(root, kept, {"answered_by": "main_model", "route_choice": candidate, "fits": {candidate: 0.6}})["status"],
                "recorded",
            )
            status, stdout, stderr = run_cli(
                ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes"),
                 "chat", "route-questions", "report", "--since", "", "--json"]
            )
            self.assertEqual(status, 0, stderr)
            report = json.loads(stdout)
            events = [
                json.loads(line)
                for path in (root / ".omh" / "runtime" / "wrapper_sessions").glob("*/events.jsonl")
                for line in path.read_text(encoding="utf-8").splitlines()
            ]
        self.assertEqual(ROUTE_QUESTION_OBSERVED_EVENT, SESSION_EVENT)
        observed = [event for event in events if event["event"] == SESSION_EVENT]
        # One line for the undecidable turn, none for the decided one, and no text.
        self.assertEqual(len(observed), 1)
        data = observed[0]["data"]
        self.assertEqual(data["message_sha256"], message_digest(kept))
        self.assertEqual(data["route_question"]["mode"], "shadow")
        self.assertTrue(data["route_question"]["built"])
        self.assertNotIn(kept, json.dumps(observed))
        self.assertEqual(report["routes"]["by_lane"], {"route_record": 0, "wrapper_session": 1})
        self.assertEqual(report["answers"]["joined"], 1)
        self.assertEqual((report["rates"]["agreement_rate"]["numerator"], report["rates"]["agreement_rate"]["denominator"]), (1, 1))

    def test_the_newest_route_for_a_request_wins_the_join(self) -> None:
        digest = message_digest("some request")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, stamp, action, candidate in (
                ("a", "2026-09-01T00:00:00Z", "fallback", ""),
                ("b", "2026-09-02T00:00:00Z", "clarify", "code-review"),
            ):
                (root / "runs" / name).mkdir(parents=True)
                (root / "runs" / name / "routing.json").write_text(
                    json.dumps({
                        "route_decision": {"schema_version": "route_decision/v1"},
                        "updated_at": stamp,
                        "message_sha256": digest,
                        "action": action,
                        "selected_skill": "oh-my-hermes",
                        "candidate_skill": candidate,
                    }),
                    encoding="utf-8",
                    newline="\n",
                )
            record = build_route_answer_record(
                question_digest="ab" * 32,
                answered_by="main_model",
                route_choice="code-review",
                fits={"code-review": 0.6},
                message_sha256=digest,
            )
            write_route_answer(root / "omh", record)
            report = build_route_question_shadow_report(
                root / "omh" / "runtime" / "route-questions", root / "runs", since=""
            )
        self.assertEqual(report["rates"]["agreement_rate"]["numerator"], 1)
        self.assertEqual(report["rates"]["agreement_rate"]["denominator"], 1)

    def test_an_answer_whose_coverage_was_not_checked_is_excluded_from_agreement(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            kept = "review my patch for the export feature"
            self._record_route(base, kept)
            question = route_chat_message(kept, source="discord")["route_question"]
            options = sorted(question["questions"]["route_choice"]["options"])
            with patch.dict(os.environ, {"OMH_HOME": str(root / ".omh"), "HERMES_HOME": str(root / ".hermes")}):
                # No `message`: the options cannot be re-derived, so coverage is unchecked.
                payload = json.loads(omh_route_answer_handler(
                    {
                        "question_digest": question["question_digest"],
                        "answered_by": "main_model",
                        "route_choice": options[0],
                        "choice_probabilities": {options[0]: 1.0},
                        "message_sha256": message_digest(kept),
                    },
                    session_id="session-report",
                ))
            report = build_route_question_shadow_report(
                root / ".omh" / "runtime" / "route-questions", root / ".omh" / "runtime" / "runs", since=""
            )
        self.assertEqual((payload["status"], payload["record"]["coverage_checked"]), ("recorded", False))
        self.assertEqual(report["answers"]["coverage_unchecked"], 1)
        self.assertEqual(report["rates"]["agreement_rate"]["denominator"], 0)
        self.assertIn("coverage_unchecked", report["rates"]["agreement_rate"]["excluded"])

    def test_an_empty_window_reports_unmeasured_rates_not_zero(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = build_route_question_shadow_report(root / "answers", root / "runs", since="")
        for rate in report["rates"].values():
            self.assertEqual(reported_rate_shape_errors(rate), ())
            self.assertIsNone(rate["percent"])
        self.assertIsNone(report["cost"]["per_turn_usd"])
        self.assertEqual(report["cost"]["basis"], "no_model_named")
        self.assertIn("unmeasured", format_route_question_shadow_report(report))

    def test_an_answer_with_no_recorded_route_is_unjoined_not_agreeing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self._answer(root, UNDECIDABLE_MESSAGE, {"answered_by": "main_model", "route_choice": "none"})
            report = build_route_question_shadow_report(
                root / ".omh" / "runtime" / "route-questions", root / ".omh" / "runtime" / "runs", since=""
            )
        self.assertEqual(report["answers"]["unjoined"], 1)
        self.assertEqual(report["rates"]["agreement_rate"]["denominator"], 0)
        self.assertIsNone(report["rates"]["agreement_rate"]["percent"])

    def test_off_is_recorded_as_built_but_not_asked(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _write_mode(root / ".omh", '{"mode": "off"}')
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            status, stdout, stderr = run_cli(
                base + ["chat", "route", "--source", "discord", "--record", "--json", UNDECIDABLE_MESSAGE]
            )
            self.assertEqual(status, 0, stderr)
            payload = json.loads(stdout)
            (routing_path,) = (root / ".omh" / "runtime" / "runs").glob("*/routing.json")
            routing = json.loads(routing_path.read_text(encoding="utf-8"))
        self.assertNotIn("route_question", payload["route"])
        self.assertEqual(routing["route_question"]["mode"], "off")
        self.assertTrue(routing["route_question"]["built"])
        self.assertFalse(routing["route_question"]["asked"])
        self.assertEqual(routing["message_sha256"], message_digest(UNDECIDABLE_MESSAGE))


if __name__ == "__main__":
    unittest.main()

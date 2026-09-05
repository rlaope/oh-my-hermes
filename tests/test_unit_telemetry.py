from __future__ import annotations

import json
import unittest

from _local_package import load_local_package

load_local_package()
from omh.coding.unit_telemetry import (  # noqa: E402
    UNIT_TELEMETRY_CLAIM_BOUNDARY,
    UNIT_TELEMETRY_SCHEMA_VERSION,
    UNIT_TELEMETRY_SOURCES,
    UNIT_TELEMETRY_VALUE_KEYS,
    parse_unit_telemetry,
)

CODEX_TOKEN_COUNT_EVENT = {
    "id": "7",
    "msg": {
        "type": "token_count",
        "info": {
            "total_token_usage": {
                "input_tokens": 4200,
                "cached_input_tokens": 3100,
                "output_tokens": 850,
                "reasoning_output_tokens": 640,
                "total_tokens": 5050,
            },
            "last_token_usage": {"input_tokens": 11, "output_tokens": 22, "total_tokens": 33},
            "model_context_window": 272000,
        },
    },
}
CODEX_SESSION_CONFIGURED_EVENT = {
    "id": "0",
    "msg": {"type": "session_configured", "session_id": "0199f0aa-1b2c-4d5e-8f90-abcdef123456", "model": "gpt-5.6-sol"},
}
CLAUDE_RESULT_EVENT = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "duration_ms": 41230,
    "num_turns": 6,
    "result": "Added the parser and its tests.",
    "session_id": "5f0c1d2e-3a4b-4c5d-9e6f-7a8b9c0d1e2f",
    "usage": {
        "input_tokens": 912,
        "cache_creation_input_tokens": 15400,
        "cache_read_input_tokens": 88300,
        "output_tokens": 2734,
    },
}


def jsonl(*events: object) -> str:
    return "\n".join(json.dumps(event) for event in events) + "\n"


class UnitTelemetryPayloadShapeTests(unittest.TestCase):
    def test_every_payload_carries_schema_version_claim_boundary_and_declared_source(self) -> None:
        payloads = [
            parse_unit_telemetry("codex", jsonl(CODEX_SESSION_CONFIGURED_EVENT, CODEX_TOKEN_COUNT_EVENT)),
            parse_unit_telemetry("claude-code", jsonl(CLAUDE_RESULT_EVENT)),
            parse_unit_telemetry("omo-runtime", "anything at all"),
            parse_unit_telemetry("codex", ""),
        ]
        for payload in payloads:
            with self.subTest(owner=payload["owner"], source=payload["source"]):
                self.assertEqual(payload["schema_version"], UNIT_TELEMETRY_SCHEMA_VERSION)
                self.assertEqual(payload["claim_boundary"], UNIT_TELEMETRY_CLAIM_BOUNDARY)
                self.assertIn(payload["source"], UNIT_TELEMETRY_SOURCES)
                self.assertIsInstance(payload["parsed"], bool)

    def test_parsed_flag_and_named_source_are_equivalent(self) -> None:
        cases = (
            ("codex", jsonl(CODEX_TOKEN_COUNT_EVENT)),
            ("codex", ""),
            ("codex", "no json here at all\n"),
            ("claude-code", jsonl(CLAUDE_RESULT_EVENT)),
            ("claude-code", "{"),
            ("omo-runtime", jsonl(CLAUDE_RESULT_EVENT)),
        )
        for owner, stdout_text in cases:
            with self.subTest(owner=owner, stdout_text=stdout_text[:24]):
                payload = parse_unit_telemetry(owner, stdout_text)
                self.assertEqual(payload["parsed"], payload["source"] != "none")

    def test_payload_never_carries_a_value_key_it_did_not_observe(self) -> None:
        payload = parse_unit_telemetry("omo-runtime", jsonl(CODEX_TOKEN_COUNT_EVENT))
        for key in UNIT_TELEMETRY_VALUE_KEYS:
            self.assertNotIn(key, payload)


class CodexOwnerTests(unittest.TestCase):
    def test_codex_token_count_and_session_configured_events_are_read(self) -> None:
        payload = parse_unit_telemetry("codex", jsonl(CODEX_SESSION_CONFIGURED_EVENT, CODEX_TOKEN_COUNT_EVENT))

        self.assertTrue(payload["parsed"])
        self.assertEqual(payload["source"], "codex_json")
        self.assertEqual(payload["tokens_total"], 5050)
        self.assertEqual(payload["input_tokens"], 4200)
        self.assertEqual(payload["output_tokens"], 850)
        self.assertEqual(payload["session_ref"], "0199f0aa-1b2c-4d5e-8f90-abcdef123456")

    def test_per_turn_usage_is_never_mistaken_for_the_run_total(self) -> None:
        payload = parse_unit_telemetry("codex", jsonl(CODEX_TOKEN_COUNT_EVENT))

        self.assertEqual(payload["tokens_total"], 5050)
        self.assertNotEqual(payload["tokens_total"], 33)

    def test_codex_turn_completed_usage_and_thread_started_id_are_read(self) -> None:
        stream = jsonl(
            {"type": "thread.started", "thread_id": "thr_abc123"},
            {"type": "item.completed", "item": {"type": "assistant_message", "text": "done"}},
            {"type": "turn.completed", "usage": {"input_tokens": 120, "output_tokens": 45, "total_tokens": 165}},
        )
        payload = parse_unit_telemetry("codex", stream)

        self.assertTrue(payload["parsed"])
        self.assertEqual(payload["source"], "codex_json")
        self.assertEqual(payload["input_tokens"], 120)
        self.assertEqual(payload["output_tokens"], 45)
        self.assertEqual(payload["tokens_total"], 165)
        self.assertEqual(payload["session_ref"], "thr_abc123")

    def test_last_token_reading_supersedes_earlier_ones_as_a_whole_group(self) -> None:
        stream = jsonl(
            {"msg": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}}},
            {"msg": {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 90, "output_tokens": 40}}}},
        )
        payload = parse_unit_telemetry("codex", stream)

        self.assertEqual(payload["input_tokens"], 90)
        self.assertEqual(payload["output_tokens"], 40)
        # The superseding reading carried no total, so no stale total survives
        # and none is derived from the parts.
        self.assertNotIn("tokens_total", payload)


class ClaudeCodeOwnerTests(unittest.TestCase):
    def test_claude_result_object_yields_usage_and_session(self) -> None:
        payload = parse_unit_telemetry("claude-code", jsonl(CLAUDE_RESULT_EVENT))

        self.assertTrue(payload["parsed"])
        self.assertEqual(payload["source"], "claude_json")
        self.assertEqual(payload["input_tokens"], 912)
        self.assertEqual(payload["output_tokens"], 2734)
        self.assertEqual(payload["session_ref"], "5f0c1d2e-3a4b-4c5d-9e6f-7a8b9c0d1e2f")

    def test_claude_reports_no_total_so_none_is_invented_from_the_parts(self) -> None:
        payload = parse_unit_telemetry("claude-code", jsonl(CLAUDE_RESULT_EVENT))

        self.assertNotIn("tokens_total", payload)
        self.assertNotEqual(payload.get("tokens_total"), 912 + 2734)

    def test_pretty_printed_single_document_is_read_when_no_line_parses(self) -> None:
        payload = parse_unit_telemetry("claude-code", json.dumps(CLAUDE_RESULT_EVENT, indent=2))

        self.assertTrue(payload["parsed"])
        self.assertEqual(payload["input_tokens"], 912)
        self.assertEqual(payload["session_ref"], "5f0c1d2e-3a4b-4c5d-9e6f-7a8b9c0d1e2f")

    def test_claude_stream_json_takes_the_session_from_the_init_event(self) -> None:
        stream = jsonl(
            {"type": "system", "subtype": "init", "session_id": "sess_init_1", "tools": ["Bash", "Edit"]},
            {"type": "assistant", "message": {"role": "assistant", "content": "working"}},
            {"type": "result", "subtype": "success", "usage": {"input_tokens": 7, "output_tokens": 3}},
        )
        payload = parse_unit_telemetry("claude-code", stream)

        self.assertEqual(payload["session_ref"], "sess_init_1")
        self.assertEqual(payload["input_tokens"], 7)
        self.assertEqual(payload["output_tokens"], 3)

    def test_claude_result_total_cost_usd_is_read_as_the_reported_cost(self) -> None:
        event = {**CLAUDE_RESULT_EVENT, "total_cost_usd": 0.4213}
        payload = parse_unit_telemetry("claude-code", jsonl(event))

        self.assertEqual(payload["cost_usd"], 0.4213)

    def test_claude_result_without_total_cost_usd_reports_no_cost(self) -> None:
        payload = parse_unit_telemetry("claude-code", jsonl(CLAUDE_RESULT_EVENT))

        self.assertNotIn("cost_usd", payload)

    def test_negative_or_non_numeric_reported_cost_is_rejected(self) -> None:
        for bad_cost in (-0.5, "0.42", True):
            with self.subTest(bad_cost=bad_cost):
                event = {**CLAUDE_RESULT_EVENT, "total_cost_usd": bad_cost}
                payload = parse_unit_telemetry("claude-code", jsonl(event))
                self.assertNotIn("cost_usd", payload)


class CodexCostTests(unittest.TestCase):
    def test_codex_never_reports_a_cost_because_none_is_estimated_from_tokens(self) -> None:
        payload = parse_unit_telemetry("codex", jsonl(CODEX_SESSION_CONFIGURED_EVENT, CODEX_TOKEN_COUNT_EVENT))

        self.assertNotIn("cost_usd", payload)


class UnstructuredOwnerTests(unittest.TestCase):
    def test_owners_without_a_structured_surface_report_honest_absence(self) -> None:
        stdout_text = jsonl(CLAUDE_RESULT_EVENT, CODEX_TOKEN_COUNT_EVENT)
        for owner in ("omo-runtime", "pi", "senpi", "opencode", "hermes", "omx-runtime", "omc-runtime", "generic", ""):
            with self.subTest(owner=owner):
                payload = parse_unit_telemetry(owner, stdout_text)
                self.assertFalse(payload["parsed"])
                self.assertEqual(payload["source"], "none")
                self.assertEqual(payload["owner"], owner)
                for key in UNIT_TELEMETRY_VALUE_KEYS:
                    self.assertNotIn(key, payload)


class PartialAndMissingObservationTests(unittest.TestCase):
    def test_usage_without_a_session_reports_only_the_counts(self) -> None:
        payload = parse_unit_telemetry("codex", jsonl({"type": "turn.completed", "usage": {"input_tokens": 8, "output_tokens": 2}}))

        self.assertTrue(payload["parsed"])
        self.assertEqual(payload["input_tokens"], 8)
        self.assertEqual(payload["output_tokens"], 2)
        self.assertNotIn("session_ref", payload)
        self.assertNotIn("tokens_total", payload)

    def test_session_without_usage_reports_only_the_session(self) -> None:
        payload = parse_unit_telemetry("codex", jsonl(CODEX_SESSION_CONFIGURED_EVENT))

        self.assertTrue(payload["parsed"])
        self.assertEqual(payload["session_ref"], "0199f0aa-1b2c-4d5e-8f90-abcdef123456")
        for key in ("tokens_total", "input_tokens", "output_tokens"):
            self.assertNotIn(key, payload)

    def test_absent_count_is_an_absent_key_and_never_a_zero(self) -> None:
        payload = parse_unit_telemetry("codex", jsonl(CODEX_SESSION_CONFIGURED_EVENT))

        for key in ("tokens_total", "input_tokens", "output_tokens"):
            with self.subTest(key=key):
                self.assertNotIn(key, payload)
                self.assertIsNone(payload.get(key))
                self.assertNotEqual(payload.get(key), 0)

    def test_a_reported_zero_is_kept_because_it_is_an_observation(self) -> None:
        payload = parse_unit_telemetry("codex", jsonl({"type": "turn.completed", "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}}))

        self.assertTrue(payload["parsed"])
        self.assertEqual(payload["tokens_total"], 0)
        self.assertEqual(payload["input_tokens"], 0)
        self.assertEqual(payload["output_tokens"], 0)


class MalformedStreamTests(unittest.TestCase):
    def test_empty_stdout_parses_to_absence(self) -> None:
        for stdout_text in ("", "\n", "   \n\t\n"):
            with self.subTest(stdout_text=repr(stdout_text)):
                payload = parse_unit_telemetry("codex", stdout_text)
                self.assertFalse(payload["parsed"])
                self.assertEqual(payload["source"], "none")

    def test_stream_truncated_mid_line_does_not_raise_and_reports_absence(self) -> None:
        truncated = json.dumps(CODEX_TOKEN_COUNT_EVENT)[:120]
        payload = parse_unit_telemetry("codex", truncated)

        self.assertFalse(payload["parsed"])
        self.assertEqual(payload["source"], "none")

    def test_complete_event_before_a_truncated_tail_is_still_read(self) -> None:
        stdout_text = json.dumps(CODEX_TOKEN_COUNT_EVENT) + "\n" + json.dumps(CODEX_SESSION_CONFIGURED_EVENT)[:40]
        payload = parse_unit_telemetry("codex", stdout_text)

        self.assertTrue(payload["parsed"])
        self.assertEqual(payload["tokens_total"], 5050)
        self.assertNotIn("session_ref", payload)

    def test_non_json_noise_interleaved_with_a_valid_event_is_ignored(self) -> None:
        stdout_text = "\n".join(
            [
                "warning: could not read ~/.codexrc",
                "[2026-08-03T09:11:02Z] spawning worker",
                json.dumps(CODEX_SESSION_CONFIGURED_EVENT),
                "not json { at all",
                "]}{[",
                json.dumps(CODEX_TOKEN_COUNT_EVENT),
                "done.",
            ]
        )
        payload = parse_unit_telemetry("codex", stdout_text)

        self.assertTrue(payload["parsed"])
        self.assertEqual(payload["tokens_total"], 5050)
        self.assertEqual(payload["session_ref"], "0199f0aa-1b2c-4d5e-8f90-abcdef123456")

    def test_pathological_input_never_raises(self) -> None:
        cases = (
            "{" * 5000,
            "[" * 5000 + "]" * 5000,
            json.dumps({"usage": {"input_tokens": "many"}}),
            json.dumps([CLAUDE_RESULT_EVENT]),
            json.dumps("just a json string"),
            "\x00\x01\x02 binary garbage \xff",
            "{}\n" * 5000,
            "x" * 300000,
            json.dumps({"usage": {"input_tokens": 1}}) + "\n" + "y" * 300000,
        )
        for owner in ("codex", "claude-code", "omo-runtime"):
            for stdout_text in cases:
                with self.subTest(owner=owner, stdout_text=stdout_text[:20]):
                    payload = parse_unit_telemetry(owner, stdout_text)
                    self.assertIn(payload["source"], UNIT_TELEMETRY_SOURCES)

    def test_a_long_but_sane_result_line_still_yields_its_counts(self) -> None:
        padded = {**CLAUDE_RESULT_EVENT, "result": "z" * 200000}
        payload = parse_unit_telemetry("claude-code", json.dumps(padded) + "\n")

        self.assertTrue(payload["parsed"])
        self.assertEqual(payload["input_tokens"], 912)

    def test_line_and_document_beyond_the_work_caps_are_skipped(self) -> None:
        padded = {**CLAUDE_RESULT_EVENT, "result": "z" * 2500000}
        payload = parse_unit_telemetry("claude-code", json.dumps(padded) + "\n")

        self.assertFalse(payload["parsed"])
        self.assertEqual(payload["source"], "none")


class ValueValidationTests(unittest.TestCase):
    def test_non_integer_and_negative_counts_are_rejected(self) -> None:
        cases = (
            {"input_tokens": "912", "output_tokens": 2734},
            {"input_tokens": 91.5, "output_tokens": 2734},
            {"input_tokens": True, "output_tokens": 2734},
            {"input_tokens": None, "output_tokens": 2734},
            {"input_tokens": -1, "output_tokens": 2734},
        )
        for usage in cases:
            with self.subTest(usage=usage):
                payload = parse_unit_telemetry("claude-code", jsonl({"type": "result", "usage": usage}))
                self.assertNotIn("input_tokens", payload)
                self.assertEqual(payload["output_tokens"], 2734)

    def test_free_text_under_a_session_key_is_not_recorded_as_an_identifier(self) -> None:
        cases = (
            "resuming session for the auth refactor",
            "  ",
            "sess\nid",
            "sess\tid",
            "s" * 500,
            "",
        )
        for value in cases:
            with self.subTest(value=value[:24]):
                payload = parse_unit_telemetry("claude-code", jsonl({"type": "result", "session_id": value}))
                self.assertNotIn("session_ref", payload)

    def test_owner_label_is_normalized_for_lookup_but_echoed_as_given(self) -> None:
        payload = parse_unit_telemetry("  Claude_Code  ", jsonl(CLAUDE_RESULT_EVENT))

        self.assertEqual(payload["owner"], "Claude_Code")
        self.assertEqual(payload["source"], "claude_json")
        self.assertEqual(payload["input_tokens"], 912)


class PurityTests(unittest.TestCase):
    def test_parsing_is_deterministic_for_a_given_input(self) -> None:
        stdout_text = jsonl(CODEX_SESSION_CONFIGURED_EVENT, CODEX_TOKEN_COUNT_EVENT)
        first = parse_unit_telemetry("codex", stdout_text)
        second = parse_unit_telemetry("codex", stdout_text)

        self.assertEqual(first, second)
        self.assertEqual(list(first), list(second))

    def test_module_source_touches_no_disk_clock_environment_or_network(self) -> None:
        from omh.coding import unit_telemetry

        self.assertIn("Boundaries, in order of importance:", unit_telemetry.__doc__ or "")
        source = _module_source()
        for banned in ("open(", "Path(", "utc_now", "datetime", "urllib", "socket", "subprocess", "os.environ", "getenv"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, source)


def _module_source() -> str:
    from pathlib import Path

    from omh.coding import unit_telemetry

    return Path(str(unit_telemetry.__file__)).read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()

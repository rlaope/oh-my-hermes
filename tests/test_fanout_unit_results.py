"""Gate for the `fanout_unit_result/v1` typed unit-result contract.

The schema exists because an executor's exit code says nothing about what the
unit verified. A unit result is a *reported* shape: validating it proves the
payload's structure, never the truth of its claims. Provenance therefore rides
on every check row (`reported_by` / `observed_by` / `observation_source`) and
the validator refuses a row that promotes an executor report into a
dispatcher observation without naming the observation's source.
"""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.fanout_unit_results import (  # noqa: E402
    FANOUT_UNIT_RESULT_CHECK_STATUSES,
    FANOUT_UNIT_RESULT_PROCESS_STATUSES,
    FANOUT_UNIT_RESULT_SCHEMA_VERSION,
    validate_check_rows,
    validate_unit_result,
)


VALID_PAYLOAD: dict[str, object] = {
    "schema_version": "fanout_unit_result/v1",
    "unit_id": "core",
    "run_id": "run-20260813-150208",
    "fanout_id": "fanout-0123456789ab",
    "base_sha": "0123456789abcdef0123456789abcdef01234567",
    "head_sha": "89abcdef",
    "process_status": "process_succeeded",
    "changed_paths": ["src/auth/session.py", "tests/test_auth_session.py"],
    "checks": [
        {
            "command": "PYTHONPATH=tests uv run python -m unittest tests/test_auth_session.py",
            "status": "passed",
            "evidence_ref": "runs/run-20260813-150208/unit-core/stdout.txt",
            "reported_by": "executor",
            "observed_by": None,
            "observation_source": None,
        },
        {
            "command": "uv run python -m compileall -q src",
            "status": "skipped",
            "evidence_ref": None,
            "reported_by": "dispatcher",
            "observed_by": "dispatcher",
            "observation_source": "journal:unit_result_validated:core",
        },
    ],
    "findings": ["session cookie rotation left untested upstream"],
}


def _payload(**overrides: object) -> dict[str, object]:
    """A deep-enough copy of VALID_PAYLOAD with top-level fields replaced."""
    payload: dict[str, object] = {
        key: ([dict(row) for row in value] if key == "checks" else value)
        for key, value in VALID_PAYLOAD.items()
    }
    payload.update(overrides)
    return payload


def _payload_with_check(**check_overrides: object) -> dict[str, object]:
    """VALID_PAYLOAD carrying a single check row with the given overrides."""
    row = dict(VALID_PAYLOAD["checks"][0])  # type: ignore[index]
    row.update(check_overrides)
    return _payload(checks=[row])


class FanoutUnitResultTests(unittest.TestCase):
    def test_valid_payload_normalizes(self) -> None:
        result = validate_unit_result(VALID_PAYLOAD)

        self.assertEqual(result["schema_version"], FANOUT_UNIT_RESULT_SCHEMA_VERSION)
        self.assertEqual(result["unit_id"], "core")
        self.assertEqual(result["run_id"], "run-20260813-150208")
        self.assertEqual(result["fanout_id"], "fanout-0123456789ab")
        self.assertEqual(result["base_sha"], "0123456789abcdef0123456789abcdef01234567")
        self.assertEqual(result["head_sha"], "89abcdef")
        self.assertEqual(result["process_status"], "process_succeeded")
        self.assertEqual(result["changed_paths"], ["src/auth/session.py", "tests/test_auth_session.py"])
        self.assertEqual(len(result["checks"]), 2)
        self.assertEqual(result["checks"][0]["reported_by"], "executor")
        self.assertIsNone(result["checks"][0]["observed_by"])
        self.assertIsNone(result["checks"][0]["observation_source"])
        self.assertEqual(result["checks"][1]["observed_by"], "dispatcher")
        self.assertEqual(result["findings"], ["session cookie rotation left untested upstream"])
        self.assertNotIn("schema_error", result)

    def test_validation_does_not_mutate_input(self) -> None:
        before = repr(VALID_PAYLOAD)
        result = validate_unit_result(VALID_PAYLOAD)
        result["checks"][0]["status"] = "failed"
        result["changed_paths"].append("src/mutated.py")

        self.assertEqual(repr(VALID_PAYLOAD), before)

    def test_rejects_unknown_process_status(self) -> None:
        with self.assertRaises(ValueError) as caught:
            validate_unit_result(_payload(process_status="merge_ready"))

        self.assertIn("process_status", str(caught.exception))

    def test_accepts_every_declared_process_status(self) -> None:
        self.assertEqual(FANOUT_UNIT_RESULT_PROCESS_STATUSES, ("process_succeeded", "process_failed"))
        for status in FANOUT_UNIT_RESULT_PROCESS_STATUSES:
            with self.subTest(status=status):
                self.assertEqual(validate_unit_result(_payload(process_status=status))["process_status"], status)

    def test_rejects_non_dict_payload(self) -> None:
        for payload in ([], "fanout_unit_result/v1", None, 7):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError) as caught:
                    validate_unit_result(payload)  # type: ignore[arg-type]
                self.assertIn("payload", str(caught.exception))

    def test_rejects_missing_schema_version(self) -> None:
        payload = _payload()
        del payload["schema_version"]

        with self.assertRaises(ValueError) as caught:
            validate_unit_result(payload)

        self.assertIn("schema_version", str(caught.exception))

    def test_rejects_each_missing_required_key(self) -> None:
        """Verify all 9 required top-level keys are enforced.

        Loop over schema_version, unit_id, run_id, fanout_id, base_sha,
        head_sha, process_status, changed_paths, checks. For each, deepcopy
        VALID_PAYLOAD, delete the key, and assert validate_unit_result
        raises ValueError naming that exact key.
        """
        required_keys = (
            "schema_version",
            "unit_id",
            "run_id",
            "fanout_id",
            "base_sha",
            "head_sha",
            "process_status",
            "changed_paths",
            "checks",
        )
        for key in required_keys:
            with self.subTest(key=key):
                payload = _payload()
                del payload[key]
                with self.assertRaises(ValueError) as caught:
                    validate_unit_result(payload)
                self.assertIn(key, str(caught.exception))

    def test_rejects_wrong_schema_version(self) -> None:
        with self.assertRaises(ValueError) as caught:
            validate_unit_result(_payload(schema_version="fanout_unit_result/v2"))

        message = str(caught.exception)
        self.assertIn("schema_version", message)
        self.assertIn(FANOUT_UNIT_RESULT_SCHEMA_VERSION, message)

    def test_rejects_bad_unit_id(self) -> None:
        for unit_id in ("", "Core", "core/../etc", 12, None):
            with self.subTest(unit_id=unit_id):
                with self.assertRaises(ValueError) as caught:
                    validate_unit_result(_payload(unit_id=unit_id))
                self.assertIn("unit_id", str(caught.exception))

    def test_rejects_blank_or_non_string_run_id(self) -> None:
        for run_id in ("", "   ", 3, None):
            with self.subTest(run_id=run_id):
                with self.assertRaises(ValueError) as caught:
                    validate_unit_result(_payload(run_id=run_id))
                self.assertIn("run_id", str(caught.exception))

    def test_rejects_bad_fanout_id(self) -> None:
        for fanout_id in ("fanout-xyz", "0123456789ab", "", None):
            with self.subTest(fanout_id=fanout_id):
                with self.assertRaises(ValueError) as caught:
                    validate_unit_result(_payload(fanout_id=fanout_id))
                self.assertIn("fanout_id", str(caught.exception))

    def test_rejects_non_hex_shas(self) -> None:
        for field in ("base_sha", "head_sha"):
            for value in ("zzzz", "abc", "0" * 41, "", None, 12345678):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(ValueError) as caught:
                        validate_unit_result(_payload(**{field: value}))
                    self.assertIn(field, str(caught.exception))

    def test_rejects_absolute_and_escaping_changed_paths(self) -> None:
        for changed_paths in (
            ["/etc/passwd"],
            ["../outside.py"],
            ["src/../../outside.py"],
            ["src/auth/session.py", ""],
            "src/auth/session.py",
            [7],
        ):
            with self.subTest(changed_paths=changed_paths):
                with self.assertRaises(ValueError) as caught:
                    validate_unit_result(_payload(changed_paths=changed_paths))
                self.assertIn("changed_paths", str(caught.exception))

    def test_accepts_empty_changed_paths(self) -> None:
        self.assertEqual(validate_unit_result(_payload(changed_paths=[]))["changed_paths"], [])

    def test_rejects_non_list_checks(self) -> None:
        for checks in ({"command": "pytest"}, "pytest", None):
            with self.subTest(checks=checks):
                with self.assertRaises(ValueError) as caught:
                    validate_unit_result(_payload(checks=checks))
                self.assertIn("checks", str(caught.exception))

    def test_rejects_check_row_that_is_not_an_object(self) -> None:
        with self.assertRaises(ValueError) as caught:
            validate_unit_result(_payload(checks=["passed"]))

        self.assertIn("checks", str(caught.exception))

    def test_rejects_blank_check_command(self) -> None:
        with self.assertRaises(ValueError) as caught:
            validate_unit_result(_payload_with_check(command="   "))

        self.assertIn("command", str(caught.exception))

    def test_rejects_unknown_check_status(self) -> None:
        self.assertEqual(FANOUT_UNIT_RESULT_CHECK_STATUSES, ("passed", "failed", "skipped"))
        with self.assertRaises(ValueError) as caught:
            validate_unit_result(_payload_with_check(status="green"))

        self.assertIn("status", str(caught.exception))

    def test_rejects_unknown_reported_by(self) -> None:
        with self.assertRaises(ValueError) as caught:
            validate_unit_result(_payload_with_check(reported_by="reviewer"))

        self.assertIn("reported_by", str(caught.exception))

    def test_rejects_non_dispatcher_observed_by(self) -> None:
        with self.assertRaises(ValueError) as caught:
            validate_unit_result(
                _payload_with_check(observed_by="executor", observation_source="journal:unit_spawned:core")
            )

        self.assertIn("observed_by", str(caught.exception))

    def test_executor_reported_row_cannot_claim_dispatcher_observation_without_source(self) -> None:
        with self.assertRaises(ValueError) as caught:
            validate_unit_result(
                _payload_with_check(reported_by="executor", observed_by="dispatcher", observation_source=None)
            )

        self.assertIn("observation_source", str(caught.exception))

    def test_executor_reported_row_may_be_dispatcher_observed_with_a_source(self) -> None:
        result = validate_unit_result(
            _payload_with_check(
                reported_by="executor",
                observed_by="dispatcher",
                observation_source="journal:unit_verification_observed:core",
            )
        )

        row = result["checks"][0]
        self.assertEqual(row["reported_by"], "executor")
        self.assertEqual(row["observed_by"], "dispatcher")
        self.assertEqual(row["observation_source"], "journal:unit_verification_observed:core")

    def test_rejects_observation_source_without_observed_by(self) -> None:
        with self.assertRaises(ValueError) as caught:
            validate_unit_result(
                _payload_with_check(observed_by=None, observation_source="journal:unit_result_validated:core")
            )

        self.assertIn("observation_source", str(caught.exception))

    def test_rejects_non_string_evidence_ref(self) -> None:
        with self.assertRaises(ValueError) as caught:
            validate_unit_result(_payload_with_check(evidence_ref=17))

        self.assertIn("evidence_ref", str(caught.exception))

    def test_check_row_optional_provenance_keys_default_to_null(self) -> None:
        result = validate_unit_result(
            _payload(
                checks=[
                    {
                        "command": "uv run python -m compileall -q src",
                        "status": "passed",
                        "reported_by": "executor",
                    }
                ]
            )
        )

        row = result["checks"][0]
        self.assertIsNone(row["evidence_ref"])
        self.assertIsNone(row["observed_by"])
        self.assertIsNone(row["observation_source"])

    def test_rejects_missing_reported_by(self) -> None:
        with self.assertRaises(ValueError) as caught:
            validate_unit_result(
                _payload(checks=[{"command": "uv run python -m compileall -q src", "status": "passed"}])
            )

        self.assertIn("reported_by", str(caught.exception))

    def test_findings_are_optional_and_must_be_strings(self) -> None:
        without = _payload()
        del without["findings"]
        self.assertEqual(validate_unit_result(without)["findings"], [])

        with self.assertRaises(ValueError) as caught:
            validate_unit_result(_payload(findings=["ok", 3]))
        self.assertIn("findings", str(caught.exception))

        with self.assertRaises(ValueError) as caught:
            validate_unit_result(_payload(findings="one finding"))
        self.assertIn("findings", str(caught.exception))

    def test_schema_error_is_optional_and_must_be_a_string(self) -> None:
        result = validate_unit_result(_payload(schema_error="upstream reported a partial write"))
        self.assertEqual(result["schema_error"], "upstream reported a partial write")

        with self.assertRaises(ValueError) as caught:
            validate_unit_result(_payload(schema_error=["bad"]))
        self.assertIn("schema_error", str(caught.exception))

    def test_unknown_keys_are_accepted_and_preserved(self) -> None:
        result = validate_unit_result(
            _payload(
                executor_note="written by a newer executor",
                checks=[{**dict(VALID_PAYLOAD["checks"][0]), "duration_ms": 1234}],  # type: ignore[index]
            )
        )

        self.assertEqual(result["executor_note"], "written by a newer executor")
        self.assertEqual(result["checks"][0]["duration_ms"], 1234)


class CheckRowValidatorTests(unittest.TestCase):
    """The rows the dispatcher writes go through the same gate as the payload's."""

    def _dispatcher_row(self, **overrides: object) -> dict[str, object]:
        row = {
            "command": "python -m unittest",
            "status": "passed",
            "evidence_ref": "journal:dispatch_verification:fanout-0123456789ab-core",
            "reported_by": "dispatcher",
            "observed_by": "dispatcher",
            "observation_source": "dispatch_verification",
        }
        row.update(overrides)
        return row

    def test_dispatcher_observed_rows_validate(self) -> None:
        rows = validate_check_rows([self._dispatcher_row(), self._dispatcher_row(status="failed")])

        self.assertEqual([row["status"] for row in rows], ["passed", "failed"])
        self.assertEqual(rows[0]["observation_source"], "dispatch_verification")

    def test_a_dispatcher_row_still_has_to_name_its_observation_source(self) -> None:
        with self.assertRaises(ValueError) as caught:
            validate_check_rows([self._dispatcher_row(observation_source=None)])

        self.assertIn("observation_source", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

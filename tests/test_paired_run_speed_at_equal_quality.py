"""Wall-clock time per paired-run cell and the speed-at-equal-quality verdict.

Elapsed seconds come only from the Hermes-child dispatcher's monotonic clock,
are signed into the receipt, ride the decision rows as
``receipt_elapsed_seconds``, and feed a verdict that may claim speed only when
no task regressed from a baseline PASS to a variant FAIL.
"""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import textwrap
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.hermes_child_dispatch import (  # noqa: E402
    CancellationToken,
    HermesChildObservation,
    HermesChildRequest,
    dispatch_hermes_child,
)
from omh.coding.hermes_child_receipts import (  # noqa: E402
    ReceiptVerificationError,
    load_hermes_child_receipt,
    write_signed_observation,
)
from omh.coding.routing_observation import (  # noqa: E402
    authenticate_child_observation,
    build_routing_observation,
    render_routing_status_rows,
)
from omh.quality.paired_run_aggregation import speed_at_equal_quality  # noqa: E402
from omh.quality.paired_run_decision import (  # noqa: E402
    SCHEMA_VERSION,
    build_paired_run_decision,
    parse_paired_run_decision,
)
from omh.quality.paired_run_decision_store import (  # noqa: E402
    PairedRunStoreError,
    append_paired_run_decision,
    latest_paired_run_decision,
)
from omh.quality.paired_run_model import (  # noqa: E402
    ArmRole,
    ArmSpec,
    BehaviorVerdict,
    InfrastructureStatus,
    PairedRunRequest,
    PairedRunValidationError,
    QualityGate,
    RecordedResult,
    RunResultInput,
    SpeedVerdict,
    TaskSpec,
)
from omh.quality.paired_run_provenance import receipt_provenance_errors  # noqa: E402
from omh.quality.paired_run_validation_helpers import _BANNED_NAMES  # noqa: E402
from omh.quality.reported_rate import reported_rate_shape_errors  # noqa: E402
from paired_run_support import paired_evaluation_binding, write_observed_receipt  # noqa: E402

_PASS = BehaviorVerdict.PASS
_FAIL = BehaviorVerdict.FAIL
_OBSERVED = InfrastructureStatus.OBSERVED
_REF = "hermes-child:run:" + "0" * 64


def _row(
    task_id: str,
    arm: ArmRole,
    verdict: BehaviorVerdict,
    elapsed: float | None,
    status: InfrastructureStatus = _OBSERVED,
) -> RecordedResult:
    """A decision row as the parser yields it; receipts are not re-read here."""
    if status is InfrastructureStatus.NOT_OBSERVED:
        return RecordedResult(task_id, arm, status, BehaviorVerdict.NOT_OBSERVED, None, None, None, None, None)
    receipt_status = "completed" if status is _OBSERVED else "failed"
    return RecordedResult(
        task_id, arm, status, verdict if status is _OBSERVED else BehaviorVerdict.NOT_OBSERVED,
        _REF, "run", "2026-08-27T00:00:00Z", receipt_status, elapsed,
    )


def _task(
    task_id: str,
    baseline: tuple[BehaviorVerdict, float | None],
    variant: tuple[BehaviorVerdict, float | None],
) -> tuple[RecordedResult, RecordedResult]:
    return (
        _row(task_id, ArmRole.BASELINE, *baseline),
        _row(task_id, ArmRole.VARIANT, *variant),
    )


class SpeedVerdictRulesTests(unittest.TestCase):
    def test_variant_faster_when_quality_held_and_both_arms_passed(self) -> None:
        speed = speed_at_equal_quality((
            *_task("t1", (_PASS, 10.0), (_PASS, 6.0)),
            *_task("t2", (_PASS, 20.0), (_PASS, 21.0)),
            *_task("t3", (_PASS, 4.0), (_PASS, 2.0)),
        ))
        self.assertIs(speed.quality_gate, QualityGate.HELD)
        self.assertIs(speed.verdict, SpeedVerdict.VARIANT_FASTER)
        self.assertEqual(speed.timed_task_count, 3)
        self.assertEqual((speed.baseline_total_seconds, speed.variant_total_seconds), (34.0, 29.0))
        self.assertEqual((speed.baseline_median_seconds, speed.variant_median_seconds), (10.0, 6.0))
        rate = speed.variant_faster_rate.to_payload()
        self.assertEqual(reported_rate_shape_errors(rate), ())
        self.assertEqual((rate["numerator"], rate["denominator"]), (2, 3))
        self.assertEqual(rate["denominator_of"], "timed_task")
        self.assertIn("one_arm_failed", rate["excluded"])

    def test_variant_slower_and_no_difference_are_reported_as_such(self) -> None:
        slower = speed_at_equal_quality(_task("t1", (_PASS, 3.0), (_PASS, 5.0)))
        same = speed_at_equal_quality(_task("t1", (_PASS, 3.0), (_PASS, 3.0)))
        self.assertIs(slower.verdict, SpeedVerdict.VARIANT_SLOWER)
        self.assertIs(same.verdict, SpeedVerdict.NO_DIFFERENCE)
        self.assertEqual(same.variant_faster_rate.numerator, 0)

    def test_quality_regression_blocks_any_speed_claim_even_when_variant_is_faster(self) -> None:
        speed = speed_at_equal_quality((
            *_task("fast", (_PASS, 100.0), (_PASS, 1.0)),
            *_task("broke", (_PASS, 10.0), (_FAIL, 1.0)),
        ))
        self.assertIs(speed.quality_gate, QualityGate.REGRESSED)
        self.assertEqual(speed.regressed_task_count, 1)
        self.assertIs(speed.verdict, SpeedVerdict.QUALITY_REGRESSED)
        record = speed.to_record()
        for field in (
            "baseline_total_seconds", "variant_total_seconds",
            "baseline_median_seconds", "variant_median_seconds", "variant_faster_rate",
        ):
            self.assertIsNone(record[field], field)

    def test_variant_improvement_alone_does_not_regress_the_gate(self) -> None:
        speed = speed_at_equal_quality((
            *_task("t1", (_PASS, 9.0), (_PASS, 3.0)),
            *_task("t2", (_FAIL, 5.0), (_PASS, 4.0)),
        ))
        self.assertIs(speed.quality_gate, QualityGate.HELD)
        self.assertIs(speed.verdict, SpeedVerdict.VARIANT_FASTER)
        self.assertEqual(speed.timed_task_count, 1)

    def test_one_arm_failed_tasks_are_excluded_from_timing(self) -> None:
        speed = speed_at_equal_quality((
            *_task("timed", (_PASS, 10.0), (_PASS, 8.0)),
            # The variant fixed a task the baseline failed, very slowly; timing
            # it would flip the verdict, so it must stay out.
            *_task("fixed", (_FAIL, 1.0), (_PASS, 500.0)),
        ))
        self.assertIs(speed.verdict, SpeedVerdict.VARIANT_FASTER)
        self.assertEqual(speed.timed_task_count, 1)
        self.assertEqual(dict(speed.excluded)["one_arm_failed"], 1)
        self.assertEqual((speed.baseline_total_seconds, speed.variant_total_seconds), (10.0, 8.0))

    def test_both_failed_infra_error_and_not_observed_are_named_exclusions(self) -> None:
        speed = speed_at_equal_quality((
            *_task("timed", (_PASS, 2.0), (_PASS, 1.0)),
            *_task("both", (_FAIL, 1.0), (_FAIL, 9.0)),
            _row("infra", ArmRole.BASELINE, _PASS, 3.0),
            _row("infra", ArmRole.VARIANT, _PASS, 3.0, InfrastructureStatus.INFRA_ERROR),
            _row("unrun", ArmRole.BASELINE, _PASS, None, InfrastructureStatus.NOT_OBSERVED),
            _row("unrun", ArmRole.VARIANT, _PASS, None, InfrastructureStatus.NOT_OBSERVED),
        ))
        self.assertEqual(
            dict(speed.excluded),
            {"one_arm_failed": 0, "both_failed": 1, "missing_elapsed": 0, "infra_error": 1, "not_observed": 1},
        )
        self.assertEqual(speed.timed_task_count, 1)

    def test_missing_elapsed_is_unmeasured_never_zero_seconds(self) -> None:
        speed = speed_at_equal_quality(_task("t1", (_PASS, None), (_PASS, 5.0)))
        self.assertIs(speed.quality_gate, QualityGate.HELD)
        self.assertIs(speed.verdict, SpeedVerdict.UNMEASURED)
        self.assertEqual(speed.timed_task_count, 0)
        self.assertEqual(dict(speed.excluded)["missing_elapsed"], 1)
        self.assertIsNone(speed.baseline_total_seconds)
        self.assertIsNone(speed.variant_faster_rate)

    def test_partially_timed_tasks_count_only_the_timed_ones(self) -> None:
        speed = speed_at_equal_quality((
            *_task("timed", (_PASS, 4.0), (_PASS, 6.0)),
            *_task("untimed", (_PASS, None), (_PASS, None)),
        ))
        self.assertIs(speed.verdict, SpeedVerdict.VARIANT_SLOWER)
        self.assertEqual((speed.timed_task_count, dict(speed.excluded)["missing_elapsed"]), (1, 1))

    def test_empty_or_unobserved_matrix_is_unmeasured_with_null_fields(self) -> None:
        for rows in ((), (_row("t", ArmRole.BASELINE, _PASS, None, InfrastructureStatus.NOT_OBSERVED),)):
            with self.subTest(rows=len(rows)):
                speed = speed_at_equal_quality(rows)
                self.assertIs(speed.quality_gate, QualityGate.UNMEASURED)
                self.assertIs(speed.verdict, SpeedVerdict.UNMEASURED)
                record = speed.to_record()
                self.assertIsNone(record["baseline_total_seconds"])
                self.assertIsNone(record["variant_median_seconds"])
                self.assertIsNone(record["variant_faster_rate"])

    def test_field_names_avoid_the_banned_decision_vocabulary(self) -> None:
        record = speed_at_equal_quality(_task("t1", (_PASS, 1.0), (_PASS, 1.0))).to_record()
        names = [*record, *record["excluded"], "receipt_elapsed_seconds", "speed_at_equal_quality"]
        for name in names:
            self.assertFalse(any(banned in name for banned in _BANNED_NAMES), name)


_FAKE_HERMES = """
import sys
import time

prompt = sys.stdin.read()
if "sleep" in prompt:
    time.sleep(0.3)
print("done")
sys.exit(1 if "fail" in prompt else 0)
"""


class DispatchElapsedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory(prefix="omh-paired-speed-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.hermes = self.root / "hermes.py"
        self.hermes.write_text(f"#!{sys.executable}\n" + textwrap.dedent(_FAKE_HERMES).lstrip(), encoding="utf-8")
        self.hermes.chmod(0o755)
        self.omh_home = self.root / ".omh"
        self.omh_home.mkdir()

    def _dispatch(
        self,
        prompt: str,
        cancellation: CancellationToken | None = None,
    ) -> list[HermesChildObservation]:
        events: list[HermesChildObservation] = []
        dispatch_hermes_child(
            HermesChildRequest(
                prompt=prompt, model="fake/model", provider="fake-provider", reasoning="low",
                parent_run_id="parent-1", run_id="child-1", timeout_seconds=5.0,
                termination_grace_seconds=0.2, hermes=str(self.hermes), cwd=self.root,
            ),
            dispatch_policy="ask_before_dispatch",
            confirmed=True,
            cancellation=cancellation,
            observe=events.append,
        )
        return events

    def _sign(self, terminal: HermesChildObservation, **extra: object) -> Path:
        run_dir = self.omh_home / "coding" / "hermes-child" / "child-1"
        run_dir.mkdir(parents=True, exist_ok=True)
        payload = build_routing_observation(
            route={"selected_model": "fake-provider/fake/model", "selected_reasoning_effort": "low",
                   "role": "agent_maintainer", "executor_profile": "hermes_child", "chain": []},
            child_dispatch=authenticate_child_observation({"status": terminal.status, "run_id": "child-1"}),
            run_id="child-1",
        )
        payload.update(extra)
        write_signed_observation(run_dir, payload, terminal)
        return run_dir

    def test_terminal_events_carry_spawn_to_exit_seconds_and_earlier_events_do_not(self) -> None:
        events = self._dispatch("sleep then finish")
        self.assertEqual([item.status for item in events], ["prepared", "running", "completed"])
        self.assertIsNone(events[0].elapsed_seconds)
        self.assertIsNone(events[1].elapsed_seconds)
        self.assertGreaterEqual(events[2].elapsed_seconds, 0.3)
        failed = self._dispatch("fail fast")[-1]
        self.assertEqual(failed.status, "failed")
        self.assertIsInstance(failed.elapsed_seconds, float)

    def test_cancelled_before_spawn_has_no_elapsed_time(self) -> None:
        token = CancellationToken()
        token.cancel()
        events = self._dispatch("never runs", token)
        self.assertEqual(events[-1].status, "cancelled")
        self.assertIsNone(events[-1].elapsed_seconds)

    def test_elapsed_is_signed_into_the_receipt_and_a_caller_value_is_overwritten(self) -> None:
        terminal = self._dispatch("sleep then finish")[-1]
        run_dir = self._sign(terminal, elapsed_seconds=999.0)
        stored = json.loads((run_dir / "observation.json").read_text(encoding="utf-8"))
        self.assertEqual(stored["elapsed_seconds"], round(terminal.elapsed_seconds, 3))
        receipt = load_hermes_child_receipt(self.omh_home, "child-1")
        self.assertEqual(receipt.elapsed_seconds, round(terminal.elapsed_seconds, 3))
        self.assertTrue(any(line.startswith("METRICS") and "elapsed" in line for line in render_routing_status_rows(stored)))

    def test_tampered_elapsed_fails_receipt_verification(self) -> None:
        terminal = self._dispatch("sleep then finish")[-1]
        run_dir = self._sign(terminal)
        path = run_dir / "observation.json"
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored["elapsed_seconds"] = 0.001
        path.write_text(json.dumps(stored), encoding="utf-8")
        with self.assertRaises(ReceiptVerificationError):
            load_hermes_child_receipt(self.omh_home, "child-1")

    def test_prepared_observation_stays_null_and_refuses_a_caller_elapsed(self) -> None:
        run_dir = self.omh_home / "coding" / "hermes-child" / "child-1"
        run_dir.mkdir(parents=True)
        prepared = build_routing_observation(run_id="child-1")
        signed = write_signed_observation(run_dir, prepared)
        self.assertIsNone(signed["elapsed_seconds"])
        with self.assertRaises(ReceiptVerificationError):
            write_signed_observation(run_dir, {**prepared, "elapsed_seconds": 4.0})


def _decision_request(
    home: Path,
    rows: tuple[tuple[str, BehaviorVerdict, float | None, BehaviorVerdict, float | None], ...],
    decision_id: str = "speed-1",
    supersedes: str | None = None,
) -> PairedRunRequest:
    arms = {
        ArmRole.BASELINE: ArmSpec("base", "hermes", "model-a", ()),
        ArmRole.VARIANT: ArmSpec("omh", "hermes", "model-a", ("skill-a",)),
    }
    tasks = tuple(TaskSpec(task_id, f"criteria-{task_id}", "a" * 64) for task_id, *_ in rows)
    results: list[RunResultInput] = []
    for task_id, base_verdict, base_seconds, variant_verdict, variant_seconds in rows:
        for role, verdict, seconds in (
            (ArmRole.BASELINE, base_verdict, base_seconds),
            (ArmRole.VARIANT, variant_verdict, variant_seconds),
        ):
            run_id = f"{decision_id}-{task_id}-{role.value}"
            arm = arms[role]
            write_observed_receipt(
                home, run_id, elapsed_seconds=seconds,
                evaluation_binding=paired_evaluation_binding(
                    task_id=task_id, criteria_ref=f"criteria-{task_id}", input_digest="a" * 64,
                    arm=role.value, executor="hermes", model=arm.model,
                    exposed_skills=arm.exposed_skills, execution_revision="rev-1",
                ),
            )
            results.append(RunResultInput(
                task_id, role, _OBSERVED, verdict, load_hermes_child_receipt(home, run_id),
            ))
    return PairedRunRequest(
        decision_id, supersedes, arms[ArmRole.BASELINE], arms[ArmRole.VARIANT], tasks,
        len(results), 900, "rev-1", "2026-08-27T00:01:00Z", tuple(results),
    )


def _as_v1(document: str) -> str:
    """Rewrite a built v2 decision into the exact shape v1 history holds."""
    record = json.loads(document)
    record["schema_version"] = "paired_run_decision/v1"
    for row in record["results"]:
        del row["receipt_elapsed_seconds"]
    del record["aggregate"]["speed_at_equal_quality"]
    return json.dumps(record, sort_keys=True)


class DecisionSpeedContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory(prefix="omh-paired-speed-decision-")
        self.addCleanup(self.temp.cleanup)
        self.home = (Path(self.temp.name) / ".omh").resolve()

    def test_built_decision_is_v2_and_carries_signed_row_elapsed_and_verdict(self) -> None:
        decision = build_paired_run_decision(
            _decision_request(self.home, (("t1", _PASS, 12.5, _PASS, 7.25),)), self.home,
        )
        self.assertEqual(SCHEMA_VERSION, "paired_run_decision/v2")
        record = json.loads(decision.to_json())
        self.assertEqual(record["schema_version"], "paired_run_decision/v2")
        self.assertEqual(
            sorted(row["receipt_elapsed_seconds"] for row in record["results"]), [7.25, 12.5],
        )
        speed = record["aggregate"]["speed_at_equal_quality"]
        self.assertEqual((speed["quality_gate"], speed["verdict"]), ("held", "variant_faster"))
        reparsed = parse_paired_run_decision(decision.to_json(), self.home)
        self.assertIs(reparsed.aggregate.speed_at_equal_quality.verdict, SpeedVerdict.VARIANT_FASTER)

    def test_hand_edited_row_elapsed_fails_receipt_provenance(self) -> None:
        # The edited row belongs to a one-arm-failed task, so the aggregate
        # stays consistent and only receipt re-verification can catch it.
        decision = build_paired_run_decision(
            _decision_request(self.home, (
                ("t1", _PASS, 5.0, _PASS, 4.0),
                ("t2", _FAIL, 3.0, _PASS, 2.0),
            )),
            self.home,
        )
        record = json.loads(decision.to_json())
        for row in record["results"]:
            if row["task_id"] == "t2" and row["arm"] == "variant":
                row["receipt_elapsed_seconds"] = 0.5
        with self.assertRaises(PairedRunValidationError) as raised:
            parse_paired_run_decision(json.dumps(record), self.home)
        self.assertIn("receipt provenance does not match persisted observation", raised.exception.errors)
        forged = replace(decision, results=tuple(
            replace(row, receipt_elapsed_seconds=None) for row in decision.results
        ))
        self.assertEqual(
            receipt_provenance_errors(forged, self.home),
            ("receipt provenance does not match persisted observation",),
        )

    def test_hand_edited_verdict_or_total_fails_the_aggregate_recompute(self) -> None:
        decision = build_paired_run_decision(
            _decision_request(self.home, (("t1", _PASS, 5.0, _FAIL, 1.0),)), self.home,
        )
        record = json.loads(decision.to_json())
        self.assertEqual(record["aggregate"]["speed_at_equal_quality"]["verdict"], "quality_regressed")
        for field, value in (("verdict", "variant_faster"), ("variant_total_seconds", 1.0)):
            with self.subTest(field=field):
                edited = json.loads(decision.to_json())
                edited["aggregate"]["speed_at_equal_quality"][field] = value
                with self.assertRaises(PairedRunValidationError) as raised:
                    parse_paired_run_decision(json.dumps(edited), self.home)
                self.assertIn("aggregate does not match results", raised.exception.errors)

    def test_v2_rows_require_the_elapsed_key_and_reject_negative_seconds(self) -> None:
        decision = build_paired_run_decision(
            _decision_request(self.home, (("t1", _PASS, 5.0, _PASS, 4.0),)), self.home,
        )
        missing = json.loads(decision.to_json())
        del missing["results"][0]["receipt_elapsed_seconds"]
        negative = json.loads(decision.to_json())
        negative["results"][0]["receipt_elapsed_seconds"] = -1
        for label, record in (("missing", missing), ("negative", negative)):
            with self.subTest(label=label), self.assertRaises(PairedRunValidationError):
                parse_paired_run_decision(json.dumps(record), self.home)

    def test_v1_document_still_parses_and_reads_as_unmeasured(self) -> None:
        decision = build_paired_run_decision(
            _decision_request(self.home, (("t1", _PASS, 5.0, _PASS, 4.0),)), self.home,
        )
        parsed = parse_paired_run_decision(_as_v1(decision.to_json()), self.home)
        self.assertEqual(parsed.schema_version, "paired_run_decision/v1")
        self.assertIsNone(parsed.results[0].receipt_elapsed_seconds)
        self.assertIs(parsed.aggregate.speed_at_equal_quality.verdict, SpeedVerdict.UNMEASURED)
        round_trip = json.loads(parsed.to_json())
        self.assertNotIn("speed_at_equal_quality", round_trip["aggregate"])
        self.assertNotIn("receipt_elapsed_seconds", round_trip["results"][0])
        with_speed = json.loads(_as_v1(decision.to_json()))
        with_speed["aggregate"]["speed_at_equal_quality"] = json.loads(decision.to_json())["aggregate"]["speed_at_equal_quality"]
        with self.assertRaises(PairedRunValidationError):
            parse_paired_run_decision(json.dumps(with_speed), self.home)

    def test_store_with_v1_history_accepts_a_v2_successor_but_never_the_reverse(self) -> None:
        rows = (("t1", _PASS, 5.0, _PASS, 4.0),)
        store = Path(self.temp.name) / "store" / "decisions.jsonl"
        store.parent.mkdir()
        # A successor keeps every observed row's receipt, so all three
        # decisions share one set of signed receipts.
        request = _decision_request(self.home, rows, "d1")
        first = build_paired_run_decision(request, self.home)
        store.write_text(_as_v1(first.to_json()) + "\n", encoding="utf-8")
        store.chmod(0o600)
        second = build_paired_run_decision(
            replace(request, decision_id="d2", supersedes_decision_ref="d1"), self.home,
        )
        append_paired_run_decision(store, second, self.home)
        latest = latest_paired_run_decision(store, "d1", self.home)
        self.assertEqual((latest.decision_id, latest.schema_version), ("d2", "paired_run_decision/v2"))
        third = build_paired_run_decision(
            replace(request, decision_id="d3", supersedes_decision_ref="d2"), self.home,
        )
        downgraded = parse_paired_run_decision(_as_v1(third.to_json()), self.home)
        with self.assertRaises(PairedRunStoreError) as raised:
            append_paired_run_decision(store, downgraded, self.home)
        self.assertIn("downgrade the schema version", raised.exception.reason)


class StandardLibraryShadowingTests(unittest.TestCase):
    """The aggregation module must import under a shadowed `statistics`.

    The documentation-claim probe imports the CLI (and so this module) in a
    spawned child that inherits the parent's sys.path. Benchmark tests put
    `benchmarks/live-model-tools/v1/lib` there, whose `statistics.py` has no
    `median`; a stdlib import made the release-readiness gate flaky in CI.
    """

    def test_module_imports_when_a_path_entry_shadows_statistics(self) -> None:
        import subprocess

        tests_dir = Path(__file__).resolve().parent
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "statistics.py").write_text("MEAN = None\n", encoding="utf-8")
            script = textwrap.dedent(f"""
                import sys
                sys.path[:0] = [{tmp!r}, {str(tests_dir)!r}]
                import statistics
                assert not hasattr(statistics, "median"), statistics.__file__
                from _local_package import load_local_package
                load_local_package()
                from omh.quality.paired_run_aggregation import _median
                print(_median([3.0, 1.0, 2.0]), _median([4.0, 1.0, 2.0, 3.0]))
            """)
            completed = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, check=False, timeout=120,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.split(), ["2.0", "2.5"])

    def test_median_rejects_an_empty_sequence(self) -> None:
        from omh.quality.paired_run_aggregation import _median

        with self.assertRaises(ValueError):
            _median([])


if __name__ == "__main__":
    unittest.main()

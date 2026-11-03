from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.goal_ledger import (  # noqa: E402
    cancel_goal_ledger,
    create_goal_ledger,
    fail_goal_ledger,
    record_goal_blocker,
    record_goal_checkpoint,
)
from omh.goal_loop import (  # noqa: E402
    LOOP_NO_PROGRESS_TICK_CAP,
    LOOP_STOP_LADDER_SCHEMA,
    LOOP_STOP_REASONS,
    assess_loop_stop_ladder,
    create_loop_cycle,
    goal_ledger_entry_count,
    observe_loop_queue_item,
    read_loop_cycle,
    run_loop_once_result,
    tick_loop_runtime,
    validate_loop_cycle,
    validate_loop_stop_ladder,
)
from omh.paths import resolve_paths  # noqa: E402
from omh.system.local_store import atomic_write_json, utc_now  # noqa: E402


def _paths(tmp: str) -> object:
    return resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")


def _cycle(paths, **overrides):
    kwargs = {
        "goal_summary": "Keep the loop stop ladder honest about why it stopped",
        "goal_reframe": "Prepare bounded loop slices and stop with a named reason when a signal says so.",
        "success_criteria": ["Every stop carries a reason code"],
        "permission_profile": "handoff_only",
    }
    kwargs.update(overrides)
    return create_loop_cycle(paths, **kwargs)


def _seed_limit_signal(paths, profile: str, *, observed_at: str) -> None:
    atomic_write_json(
        paths.executor_limit_signals_path,
        {
            "schema_version": "executor_limit_signals/v1",
            "profiles": {
                profile: {
                    "last_limit_shaped_at": observed_at,
                    "run_ref": "run-1",
                    "unit_id": "unit-1",
                    "pattern_label": "http_429",
                }
            },
        },
        private=True,
    )


def _seed_codex_login(home: Path) -> None:
    auth = home / ".codex" / "auth.json"
    auth.parent.mkdir(parents=True, exist_ok=True)
    auth.write_text(json.dumps({"tokens": "redacted"}), encoding="utf-8")


def _advance_to_handoff_phase(paths, loop_id: str, home: Path) -> None:
    """Tick and observe until the next planned action is `executor_dispatch`.

    Phases advance on observed queue evidence, so reaching the dispatch phase
    means walking interview -> plan -> research -> handoff the same way the
    loop does in production.
    """
    for index in range(3):
        item = tick_loop_runtime(paths, loop_id, home=home)["runtime"]["queue"][-1]
        observe_loop_queue_item(
            paths, loop_id, str(item["queue_id"]), evidence_refs=[f"wrapper:phase-observation:{index}"]
        )


class StopLadderOrderingTests(unittest.TestCase):
    def test_ladder_reason_codes_are_the_declared_order(self) -> None:
        self.assertEqual(
            LOOP_STOP_REASONS,
            ("explicit_cancel", "rate_limit_signal", "auth_failure_signal", "no_progress_cap"),
        )

    def test_cancel_outranks_a_rate_limit_that_is_also_present(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            goal = create_goal_ledger(paths, "Cancelled objective", ["Criterion"])
            cancel_goal_ledger(paths, goal["goal_id"], reason="operator stopped this")
            cycle = _cycle(paths, allowed_executors=["codex"], linked_goal_id=goal["goal_id"])
            _seed_limit_signal(paths, "codex", observed_at=utc_now())

            stopped = tick_loop_runtime(paths, cycle["loop_id"])

        ladder = stopped["runtime"]["stop_ladder"]
        self.assertTrue(ladder["stop"])
        self.assertEqual(ladder["stop_reason"], "explicit_cancel")
        self.assertEqual(ladder["stop_rung"], 1)
        self.assertEqual(ladder["rungs"][0]["state"], "fired")
        # The rate-limit rung was real, but a higher rung already answered:
        # recording it as `clear` would claim a check that never ran.
        self.assertEqual(ladder["rungs"][1]["state"], "not_evaluated")
        self.assertEqual(ladder["rungs"][2]["state"], "not_evaluated")
        self.assertEqual(ladder["rungs"][3]["state"], "not_evaluated")
        self.assertEqual(stopped["runtime"]["heartbeat_count"], 0)
        self.assertEqual(stopped["runtime"]["queue"], [])
        self.assertEqual(stopped["next_action"], "show_loop_status")
        self.assertEqual(validate_loop_stop_ladder(ladder), [])
        self.assertEqual(validate_loop_cycle(stopped), {"ok": True, "errors": []})


class StopLadderRungTests(unittest.TestCase):
    def test_cancelled_linked_goal_stops_the_tick(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            goal = create_goal_ledger(paths, "Cancelled objective", ["Criterion"])
            cancel_goal_ledger(paths, goal["goal_id"], reason="operator stopped this")
            cycle = _cycle(paths, linked_goal_id=goal["goal_id"])

            stopped = tick_loop_runtime(paths, cycle["loop_id"])

        self.assertEqual(stopped["runtime"]["last_stop_reason"], "explicit_cancel")
        self.assertEqual(stopped["runtime"]["queue"], [])
        self.assertIn("cancelled", stopped["runtime"]["stop_ladder"]["detail"])

    def test_a_conclusively_failed_linked_goal_also_stops_the_tick(self) -> None:
        # #H: `fail_goal_ledger`'s negative-conclusive verdict makes the ledger
        # refuse every mutation exactly like `cancelled` does, so the loop must
        # not proceed into a doomed write -- but the stop `detail` must name
        # the failure distinctly from an operator's explicit cancel.
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            goal = create_goal_ledger(paths, "Objective that turns out infeasible", ["Criterion"])
            fail_goal_ledger(
                paths, goal["goal_id"], "Criteria are infeasible as specified.",
                reason_code="infeasible_as_specified",
            )
            cycle = _cycle(paths, linked_goal_id=goal["goal_id"])

            stopped = tick_loop_runtime(paths, cycle["loop_id"])

        self.assertEqual(stopped["runtime"]["last_stop_reason"], "explicit_cancel")
        self.assertEqual(stopped["runtime"]["queue"], [])
        detail = stopped["runtime"]["stop_ladder"]["detail"]
        self.assertIn("failed conclusively", detail)
        self.assertNotIn("cancelled", detail)

    def test_fresh_rate_limit_signal_stops_the_tick(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths, allowed_executors=["codex"])
            _seed_limit_signal(paths, "codex", observed_at=utc_now())

            stopped = tick_loop_runtime(paths, cycle["loop_id"])

        ladder = stopped["runtime"]["stop_ladder"]
        self.assertEqual(ladder["stop_reason"], "rate_limit_signal")
        self.assertEqual(ladder["stop_rung"], 2)
        self.assertEqual(ladder["executor_profile"], "codex")
        self.assertIn("http_429", ladder["detail"])
        self.assertEqual(stopped["next_action"], "wait_for_executor_limit_reset")
        self.assertEqual(stopped["runtime"]["heartbeat_count"], 0)

    def test_missing_login_marker_stops_a_tick_that_would_dispatch(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            home = Path(tmp) / "home"
            home.mkdir()
            cycle = _cycle(paths, permission_profile="full_loop", allowed_executors=["codex"])
            _advance_to_handoff_phase(paths, cycle["loop_id"], home)

            stopped = tick_loop_runtime(paths, cycle["loop_id"], home=home)

        ladder = stopped["runtime"]["stop_ladder"]
        self.assertEqual(ladder["planned_action"], "executor_dispatch")
        self.assertEqual(ladder["stop_reason"], "auth_failure_signal")
        self.assertEqual(ladder["stop_rung"], 3)
        self.assertEqual(stopped["next_action"], "confirm_executor_login_or_retarget")
        # The stop names the marker for what it is and claims nothing about
        # the provider, which is the whole reason the rung is allowed to fire.
        self.assertIn("no provider rejected anything here", ladder["detail"])
        self.assertEqual(stopped["runtime"]["heartbeat_count"], 3)

    def test_no_progress_cap_stops_and_records_a_stuck_marker(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            goal = create_goal_ledger(paths, "Objective with no recorded progress", ["Criterion"])
            cycle = _cycle(paths, linked_goal_id=goal["goal_id"])

            first = tick_loop_runtime(paths, cycle["loop_id"])
            second = tick_loop_runtime(paths, cycle["loop_id"])

        self.assertEqual(first["runtime"]["no_progress_ticks"], 1)
        self.assertEqual(first["runtime"]["last_stop_reason"], "none")
        ladder = second["runtime"]["stop_ladder"]
        self.assertEqual(ladder["stop_reason"], "no_progress_cap")
        self.assertEqual(ladder["stop_rung"], 4)
        self.assertEqual(ladder["no_progress_ticks"], LOOP_NO_PROGRESS_TICK_CAP)
        marker = second["runtime"]["stuck_marker"]
        self.assertEqual(marker["reason"], "no_progress_cap")
        self.assertEqual(marker["no_progress_ticks"], LOOP_NO_PROGRESS_TICK_CAP)
        self.assertEqual(marker["next_action"], "replan_stuck_loop_once")
        self.assertIn("not a completion", marker["claim_boundary"])
        self.assertEqual(len(second["runtime"]["queue"]), 1)
        self.assertEqual(second["runtime"]["heartbeat_count"], 1)

    def test_recording_the_stuck_blocker_clears_the_no_progress_stop(self) -> None:
        # The stop's own next_action is the way out of it: a blocker is a
        # ledger record, so writing one is progress by the cap's own measure.
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            goal = create_goal_ledger(paths, "Objective that gets unstuck", ["Criterion"])
            cycle = _cycle(paths, linked_goal_id=goal["goal_id"])

            tick_loop_runtime(paths, cycle["loop_id"])
            replanned = tick_loop_runtime(paths, cycle["loop_id"])
            tick_loop_runtime(paths, cycle["loop_id"])
            stopped = tick_loop_runtime(paths, cycle["loop_id"])
            record_goal_blocker(paths, goal["goal_id"], "Loop stalled without recorded progress")
            resumed = tick_loop_runtime(paths, cycle["loop_id"])

        self.assertEqual(replanned["next_action"], "replan_stuck_loop_once")
        self.assertEqual(stopped["next_action"], "record_goal_blocker_for_stuck_loop")
        self.assertEqual(stopped["runtime"]["stop_ladder"]["stop_reason"], "no_progress_cap")
        self.assertFalse(resumed["runtime"]["stop_ladder"]["stop"])
        self.assertEqual(resumed["runtime"]["no_progress_ticks"], 0)
        self.assertEqual(resumed["runtime"]["last_stop_reason"], "none")
        self.assertNotIn("stuck_marker", resumed["runtime"])
        self.assertEqual(len(resumed["runtime"]["queue"]), 3)


class StrictSecurityPostureStopLadderTests(unittest.TestCase):
    """`OMH_SECURITY=strict` fires the no-progress rung after one stalled
    tick instead of two (`security_posture.POSTURE_MAPPING`, key
    `loop_no_progress_cap`); `default` (unset) is unchanged.
    """

    def test_strict_posture_stops_on_the_first_stalled_tick(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            goal = create_goal_ledger(paths, "Objective with no recorded progress", ["Criterion"])
            cycle = _cycle(paths, linked_goal_id=goal["goal_id"])

            with patch.dict(os.environ, {"OMH_SECURITY": "strict"}):
                first = tick_loop_runtime(paths, cycle["loop_id"])

        ladder = first["runtime"]["stop_ladder"]
        self.assertEqual(ladder["stop_reason"], "no_progress_cap")
        self.assertEqual(ladder["no_progress_cap"], 1)
        self.assertEqual(ladder["no_progress_ticks"], 1)

    def test_default_posture_still_needs_two_stalled_ticks(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            goal = create_goal_ledger(paths, "Objective with no recorded progress", ["Criterion"])
            cycle = _cycle(paths, linked_goal_id=goal["goal_id"])

            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("OMH_SECURITY", None)
                first = tick_loop_runtime(paths, cycle["loop_id"])
                second = tick_loop_runtime(paths, cycle["loop_id"])

        self.assertFalse(first["runtime"]["stop_ladder"]["stop"])
        self.assertEqual(first["runtime"]["stop_ladder"]["no_progress_cap"], LOOP_NO_PROGRESS_TICK_CAP)
        self.assertEqual(second["runtime"]["stop_ladder"]["stop_reason"], "no_progress_cap")

    def test_an_unrecognized_posture_value_is_rejected_loudly(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths)
            with patch.dict(os.environ, {"OMH_SECURITY": "paranoid"}):
                with self.assertRaises(ValueError) as ctx:
                    tick_loop_runtime(paths, cycle["loop_id"])
        self.assertIn("OMH_SECURITY", str(ctx.exception))


class StopLadderNegativeTests(unittest.TestCase):
    def test_healthy_signals_let_the_loop_advance(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            goal = create_goal_ledger(paths, "Healthy objective", ["Criterion"])
            cycle = _cycle(paths, allowed_executors=["codex"], linked_goal_id=goal["goal_id"])

            ticked = tick_loop_runtime(paths, cycle["loop_id"])

        ladder = ticked["runtime"]["stop_ladder"]
        self.assertFalse(ladder["stop"])
        self.assertEqual(ladder["stop_reason"], "none")
        self.assertEqual(ladder["stop_rung"], 0)
        self.assertEqual(ladder["next_action"], "")
        self.assertEqual([rung["state"] for rung in ladder["rungs"]], ["clear", "clear", "not_applicable", "clear"])
        self.assertEqual(ticked["runtime"]["heartbeat_count"], 1)
        self.assertEqual(len(ticked["runtime"]["queue"]), 1)
        self.assertNotIn("stuck_marker", ticked["runtime"])

    def test_one_no_progress_tick_below_the_cap_still_advances(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            goal = create_goal_ledger(paths, "Objective under the cap", ["Criterion"])
            cycle = _cycle(paths, linked_goal_id=goal["goal_id"])

            ticked = tick_loop_runtime(paths, cycle["loop_id"])

        self.assertFalse(ticked["runtime"]["stop_ladder"]["stop"])
        self.assertEqual(ticked["runtime"]["no_progress_ticks"], 1)
        self.assertLess(ticked["runtime"]["no_progress_ticks"], LOOP_NO_PROGRESS_TICK_CAP)
        self.assertEqual(len(ticked["runtime"]["queue"]), 1)

    def test_a_new_ledger_record_resets_the_no_progress_count(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            goal = create_goal_ledger(paths, "Objective that records progress", ["Criterion"])
            cycle = _cycle(paths, linked_goal_id=goal["goal_id"])

            first = tick_loop_runtime(paths, cycle["loop_id"])
            record_goal_checkpoint(paths, goal["goal_id"], "Recorded one real step", status="in_progress")
            second = tick_loop_runtime(paths, cycle["loop_id"])
            third = tick_loop_runtime(paths, cycle["loop_id"])

        self.assertEqual(first["runtime"]["no_progress_ticks"], 1)
        self.assertEqual(second["runtime"]["no_progress_ticks"], 0)
        self.assertEqual(second["runtime"]["ledger_entry_count"], 1)
        self.assertEqual(len(second["runtime"]["queue"]), 2)
        # The count restarts rather than resuming: the cap measures consecutive
        # ticks since the last record, not ticks since the loop began.
        self.assertEqual(third["runtime"]["no_progress_ticks"], 1)
        self.assertEqual(len(third["runtime"]["queue"]), 3)

    def test_a_stale_limit_signal_does_not_stop_the_loop(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths, allowed_executors=["codex"])
            _seed_limit_signal(paths, "codex", observed_at="2020-01-01T00:00:00Z")

            ticked = tick_loop_runtime(paths, cycle["loop_id"])

        ladder = ticked["runtime"]["stop_ladder"]
        self.assertFalse(ladder["stop"])
        self.assertEqual(ladder["rungs"][1]["state"], "clear")
        self.assertIn("stale", ladder["rungs"][1]["detail"])
        self.assertEqual(len(ticked["runtime"]["queue"]), 1)

    def test_an_absent_login_marker_does_not_stop_a_tick_that_never_dispatches(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            home = Path(tmp) / "home"
            home.mkdir()
            cycle = _cycle(paths, permission_profile="full_loop", allowed_executors=["codex"])

            ticked = tick_loop_runtime(paths, cycle["loop_id"], home=home)

        ladder = ticked["runtime"]["stop_ladder"]
        self.assertFalse(ladder["stop"])
        self.assertEqual(ladder["planned_action"], "planning")
        self.assertEqual(ladder["rungs"][2]["state"], "not_applicable")
        self.assertEqual(len(ticked["runtime"]["queue"]), 1)

    def test_a_present_login_marker_lets_a_dispatch_tick_advance(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            home = Path(tmp) / "home"
            home.mkdir()
            _seed_codex_login(home)
            cycle = _cycle(paths, permission_profile="full_loop", allowed_executors=["codex"])
            _advance_to_handoff_phase(paths, cycle["loop_id"], home)

            ticked = tick_loop_runtime(paths, cycle["loop_id"], home=home)

        ladder = ticked["runtime"]["stop_ladder"]
        self.assertEqual(ladder["planned_action"], "executor_dispatch")
        self.assertFalse(ladder["stop"])
        self.assertEqual(ladder["rungs"][2]["state"], "clear")
        self.assertEqual(ticked["runtime"]["heartbeat_count"], 4)

    def test_an_unlinked_loop_never_fires_the_ledger_keyed_rungs(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths)

            ticks = [tick_loop_runtime(paths, cycle["loop_id"]) for _ in range(4)]

        for ticked in ticks:
            ladder = ticked["runtime"]["stop_ladder"]
            self.assertFalse(ladder["stop"])
            self.assertEqual(ladder["rungs"][0]["state"], "not_applicable")
            self.assertEqual(ladder["rungs"][3]["state"], "not_applicable")
        self.assertEqual(ticks[-1]["runtime"]["heartbeat_count"], 4)


class StopLadderContractTests(unittest.TestCase):
    def test_ledger_entry_count_counts_written_records_only(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            goal = create_goal_ledger(paths, "Counted objective", ["First", "Second"])
            self.assertEqual(goal_ledger_entry_count(goal), 0)
            goal = record_goal_checkpoint(paths, goal["goal_id"], "One step", status="in_progress")

        self.assertEqual(goal_ledger_entry_count(goal), 1)
        self.assertEqual(goal_ledger_entry_count(None), 0)

    def test_assessment_is_pure_over_handed_in_signals(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths, allowed_executors=["codex"])

        ladder = assess_loop_stop_ladder(
            cycle,
            planned_action="executor_dispatch",
            goal_linked=True,
            goal_status="active",
            ledger_entry_count=0,
            limit_signal={"stale": True, "pattern_label": "rate_limit"},
            auth_signal={"login_marker": "absent"},
        )

        self.assertEqual(ladder["schema_version"], LOOP_STOP_LADDER_SCHEMA)
        self.assertEqual(ladder["stop_reason"], "auth_failure_signal")
        self.assertEqual(ladder["rungs"][1]["state"], "clear")
        self.assertEqual(validate_loop_stop_ladder(ladder), [])

    def test_validator_rejects_a_disagreeing_stop_flag_and_short_ladder(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths)

        ladder = assess_loop_stop_ladder(cycle, planned_action="planning")
        disagreeing = {**ladder, "stop": True}
        short = {**ladder, "rungs": ladder["rungs"][:2]}
        renamed = {
            **ladder,
            "rungs": [{**ladder["rungs"][0], "reason": "made_up"}, *ladder["rungs"][1:]],
        }

        self.assertEqual(validate_loop_stop_ladder(ladder), [])
        self.assertIn("stop_ladder.stop must agree with stop_reason", validate_loop_stop_ladder(disagreeing))
        self.assertIn("stop_ladder.rungs must hold 4 entries", validate_loop_stop_ladder(short))
        self.assertIn("stop_ladder.rungs[0].reason must be explicit_cancel", validate_loop_stop_ladder(renamed))
        self.assertEqual(validate_loop_stop_ladder("not a ladder"), ["stop_ladder must be an object"])

    def test_a_stored_stop_survives_a_read_and_stays_valid(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths, allowed_executors=["codex"])
            _seed_limit_signal(paths, "codex", observed_at=utc_now())
            tick_loop_runtime(paths, cycle["loop_id"])

            stored = read_loop_cycle(paths, cycle["loop_id"])

        self.assertEqual(stored["runtime"]["stop_ladder"]["stop_reason"], "rate_limit_signal")
        self.assertEqual(validate_loop_cycle(stored), {"ok": True, "errors": []})


class StopLadderRunOnceTests(unittest.TestCase):
    def test_run_once_reports_the_stop_rung_instead_of_an_empty_tick(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths, allowed_executors=["codex"])
            _seed_limit_signal(paths, "codex", observed_at=utc_now())

            result = run_loop_once_result(paths, cycle["loop_id"])["run_once"]

        self.assertEqual(result["outcome"], "stopped_by_ladder")
        self.assertEqual(result["stop_reason"], "rate_limit_signal")
        self.assertFalse(result["advanced"])
        self.assertEqual(result["created_queue_count"], 0)

    def test_run_once_still_reports_a_created_tick_when_no_rung_fires(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            cycle = _cycle(paths, allowed_executors=["codex"])

            result = run_loop_once_result(paths, cycle["loop_id"])["run_once"]

        self.assertEqual(result["outcome"], "created_tick")
        self.assertEqual(result["stop_reason"], "none")
        self.assertTrue(result["advanced"])


if __name__ == "__main__":
    unittest.main()

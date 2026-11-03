from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from omh.goal_ledger import cancel_goal_ledger, create_goal_ledger, record_goal_checkpoint  # noqa: E402
from omh.goal_loop import (  # noqa: E402
    build_loop_status_card,
    create_loop_cycle,
    loop_cycle_path,
    read_loop_cycle,
    tick_loop_runtime,
    validate_loop_cycle,
    validate_loop_stop_ladder,
)
from omh.paths import resolve_paths  # noqa: E402


def _linked_cycle(tmp: str):
    paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
    goal = create_goal_ledger(paths, "Keep goal-ledger progress moving", ["Recorded progress"])
    cycle = create_loop_cycle(
        paths,
        goal_summary="Keep goal-ledger progress moving",
        goal_reframe="Choose another approach when the recorded work stalls.",
        success_criteria=["Recorded progress"],
        linked_goal_id=goal["goal_id"],
        permission_profile="handoff_only",
    )
    return paths, goal, cycle


class LoopReplanTests(unittest.TestCase):
    def test_first_stall_stops_to_replan_without_queueing_and_resets_the_window(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, _, cycle = _linked_cycle(tmp)
            first = tick_loop_runtime(paths, cycle["loop_id"])
            stopped = tick_loop_runtime(paths, cycle["loop_id"])

        runtime = stopped["runtime"]
        ladder = runtime["stop_ladder"]
        self.assertTrue(ladder["stop"])
        self.assertEqual(ladder["stop_reason"], "no_progress_cap")
        self.assertEqual(ladder["stop_rung"], 4)
        self.assertEqual(ladder["next_action"], "replan_stuck_loop_once")
        self.assertEqual(stopped["next_action"], "replan_stuck_loop_once")
        self.assertEqual(runtime["stuck_marker"]["next_action"], "replan_stuck_loop_once")
        self.assertIn("re-plan once", ladder["detail"].lower())
        self.assertIn("goal ledger", ladder["detail"])
        self.assertIn("recorded failures", ladder["detail"])
        self.assertIn("continue", ladder["detail"])
        self.assertEqual(runtime["replans"], 1)
        self.assertEqual(runtime["no_progress_ticks"], 0)
        # The ladder and marker retain the evidence that stopped this tick.
        self.assertEqual(ladder["no_progress_ticks"], 2)
        self.assertEqual(runtime["stuck_marker"]["no_progress_ticks"], 2)
        self.assertEqual(runtime["queue"], first["runtime"]["queue"])
        self.assertEqual(runtime["heartbeat_count"], first["runtime"]["heartbeat_count"])
        self.assertEqual(validate_loop_stop_ladder(ladder), [])
        self.assertEqual(validate_loop_cycle(stopped), {"ok": True, "errors": []})

    def test_second_stall_gets_a_full_window_then_requires_a_blocker(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, _, cycle = _linked_cycle(tmp)
            loop_id = cycle["loop_id"]
            tick_loop_runtime(paths, loop_id)
            replanned = tick_loop_runtime(paths, loop_id)
            resumed = tick_loop_runtime(paths, loop_id)
            stopped = tick_loop_runtime(paths, loop_id)
            stopped_again = tick_loop_runtime(paths, loop_id)

        self.assertFalse(resumed["runtime"]["stop_ladder"]["stop"])
        self.assertEqual(resumed["runtime"]["no_progress_ticks"], 1)
        self.assertEqual(resumed["runtime"]["replans"], 1)
        self.assertEqual(len(resumed["runtime"]["queue"]), len(replanned["runtime"]["queue"]) + 1)
        self.assertNotIn("stuck_marker", resumed["runtime"])
        for result in (stopped, stopped_again):
            self.assertEqual(result["next_action"], "record_goal_blocker_for_stuck_loop")
            self.assertEqual(result["runtime"]["stop_ladder"]["next_action"], result["next_action"])
            self.assertEqual(result["runtime"]["stuck_marker"]["next_action"], result["next_action"])
            self.assertEqual(result["runtime"]["replans"], 1)
            self.assertEqual(result["runtime"]["queue"], resumed["runtime"]["queue"])
        self.assertEqual(stopped["runtime"]["no_progress_ticks"], 2)
        self.assertNotIn("Re-plan once", stopped["runtime"]["stop_ladder"]["detail"])

    def test_progress_rearms_the_replan_for_the_next_stall(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, goal, cycle = _linked_cycle(tmp)
            loop_id = cycle["loop_id"]
            tick_loop_runtime(paths, loop_id)
            tick_loop_runtime(paths, loop_id)
            record_goal_checkpoint(paths, goal["goal_id"], "A different approach worked", status="in_progress")
            progressed = tick_loop_runtime(paths, loop_id)
            tick_loop_runtime(paths, loop_id)
            stalled = tick_loop_runtime(paths, loop_id)

        self.assertEqual(progressed["runtime"]["replans"], 0)
        self.assertEqual(progressed["runtime"]["no_progress_ticks"], 0)
        self.assertFalse(progressed["runtime"]["stop_ladder"]["stop"])
        self.assertEqual(stalled["next_action"], "replan_stuck_loop_once")
        self.assertEqual(stalled["runtime"]["replans"], 1)
        self.assertEqual(stalled["runtime"]["no_progress_ticks"], 0)

    def test_strict_posture_replans_once_then_blocks_on_the_next_stalled_tick(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, _, cycle = _linked_cycle(tmp)
            with patch.dict(os.environ, {"OMH_SECURITY": "strict"}):
                first = tick_loop_runtime(paths, cycle["loop_id"])
                second = tick_loop_runtime(paths, cycle["loop_id"])

        self.assertEqual(first["next_action"], "replan_stuck_loop_once")
        self.assertEqual(first["runtime"]["no_progress_ticks"], 0)
        self.assertEqual(first["runtime"]["replans"], 1)
        self.assertEqual(first["runtime"]["stop_ladder"]["no_progress_cap"], 1)
        self.assertEqual(second["next_action"], "record_goal_blocker_for_stuck_loop")
        self.assertEqual(second["runtime"]["replans"], 1)
        self.assertEqual(second["runtime"]["no_progress_ticks"], 1)
        self.assertEqual(first["runtime"]["queue"], [])
        self.assertEqual(second["runtime"]["queue"], [])
        self.assertEqual(second["runtime"]["heartbeat_count"], 0)

    def test_legacy_cycle_without_replans_reads_as_zero_and_can_replan(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, _, cycle = _linked_cycle(tmp)
            path = loop_cycle_path(paths, cycle["loop_id"])
            stored = json.loads(path.read_text(encoding="utf-8"))
            stored["runtime"].pop("replans", None)
            path.write_text(json.dumps(stored), encoding="utf-8")
            read = read_loop_cycle(paths, cycle["loop_id"])
            card = build_loop_status_card(paths, cycle["loop_id"])
            tick_loop_runtime(paths, cycle["loop_id"])
            stopped = tick_loop_runtime(paths, cycle["loop_id"])

        self.assertEqual(read["runtime"]["replans"], 0)
        self.assertEqual(card["runtime_summary"]["replans"], 0)
        self.assertEqual(stopped["next_action"], "replan_stuck_loop_once")

    def test_legacy_cycle_without_runtime_remains_readable(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, _, cycle = _linked_cycle(tmp)
            path = loop_cycle_path(paths, cycle["loop_id"])
            stored = json.loads(path.read_text(encoding="utf-8"))
            stored.pop("runtime")
            path.write_text(json.dumps(stored), encoding="utf-8")
            read = read_loop_cycle(paths, cycle["loop_id"])

        self.assertEqual(read["loop_id"], cycle["loop_id"])
        self.assertEqual(validate_loop_cycle(read), {"ok": True, "errors": []})

    def test_replans_must_be_a_non_negative_integer(self) -> None:
        with TemporaryDirectory() as tmp:
            _, _, cycle = _linked_cycle(tmp)
        self.assertEqual(cycle["runtime"]["replans"], 0)
        for value in (-1, True, "1", 1.5):
            with self.subTest(value=value):
                invalid = {**cycle, "runtime": {**cycle["runtime"], "replans": value}}
                self.assertIn("runtime.replans must be a non-negative integer", validate_loop_cycle(invalid)["errors"])

    def test_progress_resets_replans_even_when_a_higher_rung_stops_the_tick(self) -> None:
        with TemporaryDirectory() as tmp:
            paths, goal, cycle = _linked_cycle(tmp)
            loop_id = cycle["loop_id"]
            tick_loop_runtime(paths, loop_id)
            tick_loop_runtime(paths, loop_id)
            record_goal_checkpoint(paths, goal["goal_id"], "Recorded before cancellation", status="in_progress")
            cancel_goal_ledger(paths, goal["goal_id"], reason="operator stopped this")
            stopped = tick_loop_runtime(paths, loop_id)

        self.assertEqual(stopped["runtime"]["replans"], 0)
        self.assertEqual(stopped["runtime"]["stop_ladder"]["stop_reason"], "explicit_cancel")
        self.assertEqual(stopped["next_action"], "show_loop_status")


if __name__ == "__main__":
    unittest.main()

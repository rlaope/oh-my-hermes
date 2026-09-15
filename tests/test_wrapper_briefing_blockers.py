"""A stopped run must not read as an early one.

`progress[].state` cannot answer "did this stop or has it merely not started":
`_state` returns `blocked` for an unmet prerequisite and `_runtime_event_state`
returns the same word for a runtime failure. These drive real failure,
cancellation and block signals through the briefing and assert the two facts
stay apart in the payload and in the lines a reader sees.
"""

from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.wrapper.briefing import (  # noqa: E402
    _STEP_RUNTIME_EVENTS,
    BLOCKER_EXECUTOR_SESSION,
    build_coding_briefing,
    chat_response_briefing,
)


def _briefing(
    *,
    runtime_observation: dict[str, object] | None = None,
    executor_status: dict[str, object] | None = None,
) -> dict[str, object]:
    return build_coding_briefing(
        {"session_id": "sess", "status": "runtime_handoff_prepared", "selected_executor_profile": "codex"},
        runtime_status={"run_id": "run"},
        executor_status=executor_status or {"selected_executor_profile": "codex"},
        runtime_observation=runtime_observation or {},
    )


class BlockerSeparationTests(unittest.TestCase):
    def test_every_step_with_a_runtime_event_reports_a_failure_as_a_blocker(self) -> None:
        """Each pair in `_STEP_RUNTIME_EVENTS` must actually carry a failure through.

        A step that gains an event in `_progress_steps` without gaining one here
        would report no blocker for a run that stopped on it, which is the exact
        silence this module exists to prevent.
        """
        for step_id, event_type in _STEP_RUNTIME_EVENTS:
            with self.subTest(step=step_id):
                briefing = _briefing(runtime_observation={"failed_events": [event_type]})
                self.assertEqual(
                    briefing["blockers"],
                    [{"id": step_id, "kind": "failed", "event": event_type}],
                )

    def test_a_cancelled_step_is_a_blocker_and_not_a_pending_gap_alone(self) -> None:
        briefing = _briefing(runtime_observation={"cancelled_events": ["ci"]})
        self.assertEqual(briefing["blockers"], [{"id": "ci", "kind": "cancelled", "event": "ci"}])

    def test_a_blocked_step_is_reported_as_blocked_not_failed(self) -> None:
        briefing = _briefing(runtime_observation={"blocked_events": ["review"]})
        self.assertEqual(briefing["blockers"], [{"id": "review", "kind": "blocked", "event": "review"}])

    def test_cancellation_wins_over_failure_for_the_same_event(self) -> None:
        """The state it is in now, not the one it passed through."""
        briefing = _briefing(runtime_observation={"failed_events": ["ci"], "cancelled_events": ["ci"]})
        self.assertEqual([blocker["kind"] for blocker in briefing["blockers"]], ["cancelled"])

    def test_an_executor_session_error_is_a_blocker(self) -> None:
        briefing = _briefing(executor_status={"selected_executor_profile": "codex", "executor_session_error": "auth failed"})
        self.assertIn(
            {"id": BLOCKER_EXECUTOR_SESSION, "kind": "failed", "event": "executor_session"},
            briefing["blockers"],
        )

    def test_a_run_that_merely_has_not_started_reports_no_blocker(self) -> None:
        """The negative control: nine steps are unreached and none of them stopped."""
        briefing = _briefing()
        self.assertEqual(briefing["blockers"], [])
        self.assertTrue(briefing["pending_gaps"], "expected unreached steps to still be reported")


class BlockerLineTests(unittest.TestCase):
    def test_the_stopped_line_precedes_the_not_reached_line(self) -> None:
        briefing = _briefing(runtime_observation={"failed_events": ["ci"]})
        lines = briefing["user_facing_lines"]
        stopped = [index for index, line in enumerate(lines) if line.startswith("Stopped:")]
        not_reached = [index for index, line in enumerate(lines) if line.startswith("Not reached yet:")]
        self.assertTrue(stopped, f"no stopped line in {lines}")
        self.assertTrue(not_reached, f"no not-reached line in {lines}")
        self.assertLess(stopped[0], not_reached[0])

    def test_a_stopped_step_is_not_repeated_as_not_reached(self) -> None:
        briefing = _briefing(runtime_observation={"failed_events": ["ci"]})
        not_reached = [line for line in briefing["user_facing_lines"] if line.startswith("Not reached yet:")]
        self.assertEqual(len(not_reached), 1)
        # The rendered word, not the step id: after the vocabulary change the id
        # never appears, so asserting on `ci` would pass without proving the
        # stopped step was excluded.
        self.assertNotIn("CI", not_reached[0].split(": ", 1)[1].split(", "))

    def test_the_narrative_leads_with_the_stop(self) -> None:
        briefing = _briefing(runtime_observation={"failed_events": ["ci"]})
        self.assertIn("stopped at CI (failed)", briefing["narrative"])

    def test_a_clean_run_keeps_the_waiting_narrative(self) -> None:
        self.assertIn("still waiting on", _briefing()["narrative"])

    def test_the_chat_projection_carries_blockers(self) -> None:
        briefing = _briefing(runtime_observation={"failed_events": ["ci"]})
        projected = chat_response_briefing(briefing)
        self.assertEqual(projected["blockers"], briefing["blockers"])

    def test_the_chat_projection_copies_rather_than_aliases(self) -> None:
        briefing = _briefing(runtime_observation={"failed_events": ["ci"]})
        projected = chat_response_briefing(briefing)
        projected["blockers"][0]["kind"] = "mutated"
        self.assertEqual(briefing["blockers"][0]["kind"], "failed")


if __name__ == "__main__":
    unittest.main()

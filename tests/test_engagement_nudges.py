"""Behaviour-triggered nudges toward a declared plan and a routed lane.

The defect: OMH engaged only when the user's message already carried OMH
vocabulary, so an ordinary "fix the auth module" session did real work and
never got a plan. Every earlier surface read the user's WORDS; this one reads
the model's tool calls, and nothing in the user's message is consulted at any
point.

Each trigger ships its negative case beside its positive one, because both
directions fail badly: too quiet is the defect, and too loud is a standing
instruction the model learns to skip.

`reset_nudge_budget` and `reset_engagement_declines` are module-global state.
They are cleared in `setUp` rather than at the end of each test because the
shard planner reorders tests run to run, so a leak surfaces as a CI-only
failure in whichever test ran next.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh import engagement_nudges as nudges
from omh.plugin_bundle.omh.engagement_nudges import (
    DELEGATION_NUDGE_DIRECT_READ_THRESHOLD,
    ENGAGEMENT_NUDGE_KEY,
    MAX_ENGAGEMENT_NUDGES,
    PLAN_NUDGE_FILE_MUTATION_THRESHOLD,
    annotate_engagement_nudge,
    engagement_nudge_declines,
    reset_engagement_declines,
)
from omh.plugin_bundle.omh.hooks.nudge_budget import (
    DURABLE_ENGAGEMENT_FIELDS,
    MAX_TRACKED_SESSIONS,
    engagement_nudge_store_path,
    reset_nudge_budget,
)
from omh.plugin_bundle.omh.hooks import session_hooks
from omh.plugin_bundle.omh.hooks.result_transforms import transform_tool_result
from omh.plugin_bundle.omh.hooks.session_hooks import subagent_start
from omh.plugin_bundle.omh.todo_store import build_todo_record, write_todo


class EngagementNudgeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        reset_nudge_budget()
        reset_engagement_declines()
        self.addCleanup(reset_nudge_budget)
        self.addCleanup(reset_engagement_declines)
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = str(Path(self._tmp.name) / "omh")

    def fire(
        self,
        tool: str,
        session: str,
        times: int = 1,
        result: str = "ok",
        *,
        same_args: bool = False,
    ) -> list[str | None]:
        """`times` calls, with DIFFERENT arguments unless asked otherwise.

        The delegation threshold counts distinct `(tool, argument digest)`
        pairs, so "five direct reads" has to mean five different ones or the
        helper is asserting the loop case by accident. `same_args=True` is
        the loop, and it has its own cases.
        """
        return [
            annotate_engagement_nudge(
                tool_name=tool,
                result=result,
                args={"path": "same.py" if same_args else f"file-{index}.py"},
                session_id=session,
                omh_home=self.home,
                hermes_home=self.home,
            )
            for index in range(times)
        ]

    def nudged(
        self, tool: str, session: str, times: int = 1, *, same_args: bool = False
    ) -> list[bool]:
        return [
            value is not None
            for value in self.fire(tool, session, times, same_args=same_args)
        ]

    def declare_plan(self, session: str, states: tuple[str, ...] = ("active",)) -> None:
        write_todo(
            Path(self.home),
            build_todo_record(
                "plan",
                [{"text": f"task {index}", "state": state, "phase": "P"} for index, state in enumerate(states)],
                source="test",
                session_ref=session,
            ),
        )


class PlanNudgeTests(EngagementNudgeTestCase):
    """Fires on observed file mutations, never on anything the user typed."""

    def test_it_fires_once_the_session_has_changed_files_past_the_threshold(self) -> None:
        fired = self.nudged("write_file", "s1", PLAN_NUDGE_FILE_MUTATION_THRESHOLD)
        self.assertEqual(fired[-1], True)
        text = self.fire("write_file", "s1")[0] or ""
        self.assertIn("[OMH plan todo]", text)
        self.assertIn("omh_todo", text)
        self.assertIn("declarations, never execution evidence", text)

    def test_a_session_one_call_under_the_threshold_is_not_nudged(self) -> None:
        # The pinned negative for the threshold itself. Two mutations is an
        # edit and its test; a checklist there is overhead, not help.
        fired = self.nudged("write_file", "s1", PLAN_NUDGE_FILE_MUTATION_THRESHOLD - 1)
        self.assertEqual(fired, [False] * (PLAN_NUDGE_FILE_MUTATION_THRESHOLD - 1))
        self.assertEqual(engagement_nudge_declines().get("below_work_threshold"), len(fired))

    def test_a_trivial_one_tool_session_is_not_nudged(self) -> None:
        self.assertEqual(self.nudged("write_file", "s1"), [False])

    def test_a_session_that_already_declared_a_plan_is_never_nudged(self) -> None:
        self.declare_plan("s1")
        fired = self.nudged("write_file", "s1", PLAN_NUDGE_FILE_MUTATION_THRESHOLD + 3)
        self.assertNotIn(True, fired)

    def test_a_finished_plan_still_counts_as_declared(self) -> None:
        """The reason the latch reads `plan_is_declared`, not `plan_is_established`.

        A completed plan projects as `all_done`, which is not `established`.
        Reading the narrower predicate would ask for a second plan the moment
        the first one finished.
        """
        self.declare_plan("s1", states=("done",))
        fired = self.nudged("write_file", "s1", PLAN_NUDGE_FILE_MUTATION_THRESHOLD + 3)
        self.assertNotIn(True, fired)

    def test_the_budget_is_spent_and_then_it_stops(self) -> None:
        fired = self.nudged("write_file", "s1", PLAN_NUDGE_FILE_MUTATION_THRESHOLD + MAX_ENGAGEMENT_NUDGES + 2)
        self.assertEqual(fired.count(True), MAX_ENGAGEMENT_NUDGES)
        self.assertEqual(fired[-1], False)
        self.assertGreater(engagement_nudge_declines().get("plan_budget_spent", 0), 0)

    def test_a_tool_that_reads_or_runs_is_not_work_for_this_purpose(self) -> None:
        """`terminal` and `execute_code` are deliberately outside the set.

        A session that only ran tests has done nothing a checklist tracks, and
        both of those are mostly that.
        """
        for tool in ("terminal", "execute_code", "omh_status"):
            with self.subTest(tool=tool):
                self.assertNotIn(True, self.nudged(tool, f"s-{tool}", 8))


class DelegationNudgeTests(EngagementNudgeTestCase):
    """opencode's own case: direct search work where a lane would do."""

    def test_it_fires_once_direct_search_work_passes_the_threshold(self) -> None:
        fired = self.nudged("read_file", "s1", DELEGATION_NUDGE_DIRECT_READ_THRESHOLD)
        self.assertEqual(fired[-1], True)
        text = self.fire("read_file", "s1")[0] or ""
        self.assertIn("[OMH delegation]", text)
        self.assertIn("omh_delegate_route", text)
        self.assertIn("delegate_task", text)

    def test_a_session_one_call_under_the_threshold_is_not_nudged(self) -> None:
        fired = self.nudged("search_files", "s1", DELEGATION_NUDGE_DIRECT_READ_THRESHOLD - 1)
        self.assertEqual(fired, [False] * (DELEGATION_NUDGE_DIRECT_READ_THRESHOLD - 1))

    def test_routing_a_lane_latches_it_off_for_the_rest_of_the_session(self) -> None:
        for router in ("delegate_task", "omh_delegate_route"):
            with self.subTest(router=router):
                reset_nudge_budget()
                self.assertEqual(self.fire(router, "s1")[0], None)
                fired = self.nudged("read_file", "s1", DELEGATION_NUDGE_DIRECT_READ_THRESHOLD + 3)
                self.assertNotIn(True, fired)

    def test_the_budget_is_spent_and_then_it_stops(self) -> None:
        fired = self.nudged(
            "web_search", "s1", DELEGATION_NUDGE_DIRECT_READ_THRESHOLD + MAX_ENGAGEMENT_NUDGES + 2
        )
        self.assertEqual(fired.count(True), MAX_ENGAGEMENT_NUDGES)
        self.assertGreater(engagement_nudge_declines().get("delegation_budget_spent", 0), 0)


class DelegatedLaneIsNotNudgedTests(EngagementNudgeTestCase):
    """The orchestrator scoping opencode gets from an agent name.

    The Hermes tool-result seam carries no agent identity and a delegated child
    runs under its own session id, so `subagent_start` is where this comes
    from.
    """

    def test_a_child_session_the_host_reported_is_never_nudged(self) -> None:
        subagent_start(parent_session_id="s1", child_session_id="child-1", child_role="explore")
        fired = self.nudged("write_file", "child-1", PLAN_NUDGE_FILE_MUTATION_THRESHOLD + 3)
        self.assertNotIn(True, fired)
        self.assertGreater(
            engagement_nudge_declines().get("delegated_session", 0),
            0,
            f"tally was {engagement_nudge_declines()}",
        )

    def test_the_parent_that_spawned_it_is_still_nudged(self) -> None:
        subagent_start(parent_session_id="s1", child_session_id="child-1")
        self.assertIn(True, self.nudged("write_file", "s1", PLAN_NUDGE_FILE_MUTATION_THRESHOLD))

    def test_the_observer_records_the_child_and_returns_nothing(self) -> None:
        self.assertIsNone(subagent_start(parent_session_id="s1", child_session_id="child-1"))

    def test_a_malformed_subagent_event_does_not_raise(self) -> None:
        # The host wraps this call in its own quiet block, so a raise here
        # would stop the recording invisibly rather than loudly.
        self.assertIsNone(subagent_start())
        self.assertIsNone(subagent_start(child_session_id=None))
        self.assertIsNone(subagent_start(child_session_id=object()))

    def test_a_swallowed_observer_failure_leaves_a_positive_record(self) -> None:
        """An absence is not a trace.

        Without this, the only evidence that the observer broke is a
        `delegated_session` decline that never happens -- and if the same
        failure keeps the nudge path away from that session, the two cancel
        and nothing is left to read. The report is widened, not the `except`.
        """
        with patch.object(session_hooks, "note_delegated_session", side_effect=RuntimeError("boom")):
            self.assertIsNone(subagent_start(parent_session_id="s1", child_session_id="child-1"))

        # The whole tally, not just the count. This guard fails two ways -- the
        # handler never recorded, or it recorded under a different key because
        # something upstream of `note_delegated_session` raised first -- and
        # only the first means the production path is missing. `None != 1`
        # reads identically for both, and reading it as the second cost an hour
        # once already.
        self.assertEqual(
            engagement_nudge_declines().get("observer_error:RuntimeError"),
            1,
            f"tally was {engagement_nudge_declines()}",
        )


class NudgeCannotRaiseTests(EngagementNudgeTestCase):
    """Hermes swallows and debug-logs anything this seam raises."""

    def test_a_failing_plan_read_is_recorded_rather_than_raised(self) -> None:
        def boom(*_args, **_kwargs):
            raise RuntimeError("todo read exploded")

        with patch.object(nudges, "_plan_declared", boom):
            fired = self.nudged("write_file", "s1", PLAN_NUDGE_FILE_MUTATION_THRESHOLD)

        self.assertNotIn(True, fired)
        self.assertEqual(
            engagement_nudge_declines().get("error:RuntimeError"),
            1,
            f"tally was {engagement_nudge_declines()}",
        )

    def test_every_decline_leaves_a_reason_behind(self) -> None:
        _ = self.nudged("write_file", "s1")
        _ = self.nudged("omh_status", "s1")
        _ = self.nudged("write_file", "", 4)
        self.assertEqual(
            set(engagement_nudge_declines()),
            {"below_work_threshold", "tool_not_watched", "no_session_id"},
        )

    def test_a_session_with_no_id_can_never_reach_a_threshold(self) -> None:
        self.assertNotIn(True, self.nudged("write_file", "", 20))


class NudgeRidesTheToolResultTests(EngagementNudgeTestCase):
    """In-band, and without breaking a host result that is JSON."""

    def test_a_json_object_result_keeps_parsing_and_gains_a_key(self) -> None:
        payload = json.dumps({"ok": True, "path": "a.py"})
        for _ in range(PLAN_NUDGE_FILE_MUTATION_THRESHOLD - 1):
            _ = self.fire("write_file", "s1", result=payload)
        carried = self.fire("write_file", "s1", result=payload)[0]

        self.assertIsNotNone(carried)
        assert carried is not None
        parsed = json.loads(carried)
        self.assertEqual(parsed["ok"], True)
        self.assertEqual(parsed["path"], "a.py")
        self.assertIn("[OMH plan todo]", parsed[ENGAGEMENT_NUDGE_KEY])

    def test_a_plain_text_result_is_appended_to(self) -> None:
        for _ in range(PLAN_NUDGE_FILE_MUTATION_THRESHOLD - 1):
            _ = self.fire("write_file", "s1", result="wrote a.py")
        carried = self.fire("write_file", "s1", result="wrote a.py")[0] or ""

        self.assertTrue(carried.startswith("wrote a.py"))
        self.assertIn("[OMH plan todo]", carried)

    def test_a_json_value_that_is_not_an_object_is_declined_not_guessed_at(self) -> None:
        fired = self.nudged("write_file", "s1", PLAN_NUDGE_FILE_MUTATION_THRESHOLD + 1)
        self.assertEqual(fired.count(True), 2)  # plain "ok" results carry fine

        reset_nudge_budget()
        reset_engagement_declines()
        carried = [
            annotate_engagement_nudge(
                tool_name="write_file",
                result="[1, 2, 3]",
                session_id="s2",
                omh_home=self.home,
                hermes_home=self.home,
            )
            for _ in range(PLAN_NUDGE_FILE_MUTATION_THRESHOLD + 1)
        ]
        self.assertEqual(carried, [None] * len(carried))
        self.assertGreater(engagement_nudge_declines().get("result_not_carryable", 0), 0)

    def test_the_registered_transform_chains_the_nudge(self) -> None:
        """The seam the host actually calls, not the module in isolation."""
        for _ in range(PLAN_NUDGE_FILE_MUTATION_THRESHOLD - 1):
            _ = transform_tool_result(
                tool_name="write_file", result="wrote a.py", session_id="s1",
                omh_home=self.home, hermes_home=self.home,
            )
        carried = transform_tool_result(
            tool_name="write_file", result="wrote a.py", session_id="s1",
            omh_home=self.home, hermes_home=self.home,
        )
        self.assertIsNotNone(carried)
        self.assertIn("[OMH plan todo]", str(carried))

    def test_an_unwatched_tool_still_passes_through_the_transform_untouched(self) -> None:
        self.assertIsNone(
            transform_tool_result(
                tool_name="omh_status", result="plain", session_id="s1",
                omh_home=self.home, hermes_home=self.home,
            )
        )


class NudgeCostTests(EngagementNudgeTestCase):
    """The worst case a session can be charged, stated as a test.

    The first-turn primer is 897 characters once per session; this is a
    per-tool-call surface, so its bound has to be shown rather than argued.
    """

    def test_the_worst_case_per_session_is_bounded_and_small(self) -> None:
        plan_text = nudges.PLAN_NUDGE_TEXT.format(count=PLAN_NUDGE_FILE_MUTATION_THRESHOLD)
        delegation_text = nudges.DELEGATION_NUDGE_TEXT.format(
            count=DELEGATION_NUDGE_DIRECT_READ_THRESHOLD
        )
        worst_case = (len(plan_text) + len(delegation_text)) * MAX_ENGAGEMENT_NUDGES

        self.assertLess(len(plan_text), 500)
        self.assertLess(len(delegation_text), 500)
        # Both nudges, both spent, is under 1.6k characters for a whole
        # session -- roughly two first-turn primers. Raised from 1500 when the
        # delegation nudge stopped saying "keep working while it runs", a
        # claim that is wrong about both tools it names; saying what each one
        # really does costs about 70 characters more than the claim did.
        self.assertLess(worst_case, 1600)

    def test_the_delegation_nudge_says_what_each_tool_does(self) -> None:
        # The measured host behaviour, pinned as text because that is all this
        # surface can affect. `omh_delegate_route` writes `delegation.*` keys
        # for the NEXT dispatch and runs nothing; `delegate_task` spawns the
        # subagent, and `run_agent._dispatch_delegate_task` backgrounds every
        # top-level model call, so "keep working while it runs" rewarded a
        # choice the model does not have and contradicted the host's own
        # "Never wait or poll".
        text = nudges.DELEGATION_NUDGE_TEXT.format(count=5)

        self.assertIn("omh_delegate_route picks the model for the next dispatch", text)
        self.assertIn("delegate_task spawns the subagent", text)
        self.assertIn("Never wait or poll", text)
        self.assertNotIn("keep working while it runs", text)
        # And it must not tell the model to pass a parameter the host does not
        # advertise: the schema-level `background` is unadvertised and ignored
        # (`tools/delegate_tool.py`, "DEPRECATED, ignored ... do not re-add").
        self.assertNotIn("background", text)

    def test_a_session_cannot_be_charged_more_than_the_budget(self) -> None:
        plan = self.fire("write_file", "s1", times=40)
        delegation = self.fire("read_file", "s1", times=40)
        charged = sum(len(value) for value in plan + delegation if value)
        # Each carried result repeats the tool result itself ("ok"), so the
        # bound is counted on the nudges delivered, not on the strings.
        self.assertEqual(len([v for v in plan if v]), MAX_ENGAGEMENT_NUDGES)
        self.assertEqual(len([v for v in delegation if v]), MAX_ENGAGEMENT_NUDGES)
        self.assertLess(charged, 2000)


class DistinctSearchTests(EngagementNudgeTestCase):
    """Five different greps and one grep five times are not the same event.

    #1701. The counter this replaced counted CALLS, so a loop read as a
    search pass and spent the budget meant for one. Measured: session
    `20260919_140745_db409e` issued 203 `search_files` calls, the large
    majority identical; the nudge fired twice, said "delegate this", and was
    silent for the remaining ~180 calls.
    """

    def test_five_identical_searches_do_not_fire_it(self) -> None:
        fired = self.nudged(
            "search_files", "s1", DELEGATION_NUDGE_DIRECT_READ_THRESHOLD, same_args=True
        )

        self.assertNotIn(True, fired)
        self.assertEqual(
            engagement_nudge_declines().get("below_read_threshold"),
            DELEGATION_NUDGE_DIRECT_READ_THRESHOLD,
        )

    def test_five_different_searches_still_fire_it(self) -> None:
        fired = self.nudged("search_files", "s1", DELEGATION_NUDGE_DIRECT_READ_THRESHOLD)

        self.assertEqual(fired[-1], True)

    def test_four_different_searches_still_do_not(self) -> None:
        # The pinned negative for the threshold, unmoved by the change of
        # what it counts.
        fired = self.nudged("search_files", "s1", DELEGATION_NUDGE_DIRECT_READ_THRESHOLD - 1)

        self.assertEqual(fired, [False] * (DELEGATION_NUDGE_DIRECT_READ_THRESHOLD - 1))

    def test_a_long_loop_does_not_consume_the_budget_a_search_pass_needs(self) -> None:
        """The whole complaint, as one sequence.

        A hundred identical searches, and then the session does what the
        nudge exists for. The budget has to still be there.
        """
        self.assertNotIn(True, self.nudged("search_files", "s1", 100, same_args=True))

        fired = self.nudged(
            "search_files", "s1", DELEGATION_NUDGE_DIRECT_READ_THRESHOLD + MAX_ENGAGEMENT_NUDGES
        )

        self.assertEqual(fired.count(True), MAX_ENGAGEMENT_NUDGES)

    def test_the_same_arguments_in_a_different_order_are_the_same_call(self) -> None:
        # Not a second hashing path: `tool_args_digest` canonicalizes, and
        # this is the property that says the nudge is using it rather than
        # something of its own.
        for _ in range(DELEGATION_NUDGE_DIRECT_READ_THRESHOLD):
            _ = annotate_engagement_nudge(
                tool_name="search_files",
                result="ok",
                args={"pattern": "def x", "path": "src"},
                session_id="s1",
                omh_home=self.home,
                hermes_home=self.home,
            )
            _ = annotate_engagement_nudge(
                tool_name="search_files",
                result="ok",
                args={"path": "src", "pattern": "def x"},
                session_id="s1",
                omh_home=self.home,
                hermes_home=self.home,
            )

        self.assertEqual(engagement_nudge_declines().get("below_read_threshold"), 10)

    def test_two_tools_with_the_same_arguments_are_two_distinct_reads(self) -> None:
        """The key is `(tool, digest)`, and the tool half has to carry weight.

        Reading a path and searching it are different work even when the
        arguments coincide. Driven to the threshold on that difference alone:
        all four watched tools on one path is four distinct reads, and a
        fifth call on a different path is the fifth. Keyed on the digest
        alone the same sequence is two, and does not fire -- which is what
        makes this a guard rather than a restatement.
        """
        fired = []
        for tool in sorted(nudges.DIRECT_READ_TOOLS):
            fired.append(
                annotate_engagement_nudge(
                    tool_name=tool, result="ok", args={"path": "same.py"},
                    session_id="s1", omh_home=self.home, hermes_home=self.home,
                )
                is not None
            )
        self.assertNotIn(True, fired)
        self.assertEqual(len(nudges.DIRECT_READ_TOOLS), DELEGATION_NUDGE_DIRECT_READ_THRESHOLD - 1)

        last = annotate_engagement_nudge(
            tool_name="read_file", result="ok", args={"path": "other.py"},
            session_id="s1", omh_home=self.home, hermes_home=self.home,
        )

        self.assertIsNotNone(last)
        self.assertIn("5 different search/read calls", str(last))

    def test_the_digest_is_the_repeat_guards_own(self) -> None:
        """One canonicalization of a call's arguments in this bundle.

        A second one here would be a second answer to "is this the same
        call", and the guard and the nudge would disagree the first time
        either changed.
        """
        from omh.plugin_bundle.omh import tool_bursts

        self.assertIs(nudges.tool_args_digest, tool_bursts.tool_args_digest)


class NudgeBudgetSurvivesARestartTests(EngagementNudgeTestCase):
    """`MAX_ENGAGEMENT_NUDGES` is per session; the map is per process.

    Measured 2026-09-19: session `20260919_140745_db409e` received four
    delegation nudges against a budget of two, in a 2+2 split bracketing a
    mid-session `omh update`, which restarts the plugin host. `8da9b8`
    received three. A budget that a restart refills is not a budget.
    """

    def _spend(self, session: str, start: int, count: int) -> list[bool]:
        return [
            annotate_engagement_nudge(
                tool_name="search_files",
                result="ok",
                args={"path": f"file-{index}.py"},
                session_id=session,
                omh_home=self.home,
                hermes_home=self.home,
            )
            is not None
            for index in range(start, start + count)
        ]

    def test_a_restart_does_not_hand_the_session_a_second_budget(self) -> None:
        first = self._spend("s1", 0, DELEGATION_NUDGE_DIRECT_READ_THRESHOLD + 4)
        self.assertEqual(first.count(True), MAX_ENGAGEMENT_NUDGES)

        # The restart: a fresh plugin host has empty module state and the
        # same OMH home on disk.
        reset_nudge_budget()

        after = self._spend("s1", 100, DELEGATION_NUDGE_DIRECT_READ_THRESHOLD + 4)

        self.assertNotIn(True, after)
        self.assertGreater(engagement_nudge_declines().get("delegation_budget_spent", 0), 0)

    def test_the_plan_budget_and_both_latches_survive_it_too(self) -> None:
        plan = self.nudged("write_file", "s1", PLAN_NUDGE_FILE_MUTATION_THRESHOLD + 4)
        self.assertEqual(plan.count(True), MAX_ENGAGEMENT_NUDGES)

        reset_nudge_budget()

        self.assertNotIn(
            True, self.nudged("write_file", "s1", PLAN_NUDGE_FILE_MUTATION_THRESHOLD + 4)
        )

    def test_routing_a_lane_stays_latched_across_a_restart(self) -> None:
        self.assertIsNone(self.fire("omh_delegate_route", "s1")[0])

        reset_nudge_budget()

        fired = self.nudged("search_files", "s1", DELEGATION_NUDGE_DIRECT_READ_THRESHOLD + 3)
        self.assertNotIn(True, fired)
        self.assertGreater(engagement_nudge_declines().get("lane_already_routed", 0), 0)

    def test_another_session_in_the_same_home_keeps_its_own_budget(self) -> None:
        self.assertEqual(
            self._spend("s1", 0, DELEGATION_NUDGE_DIRECT_READ_THRESHOLD + 4).count(True),
            MAX_ENGAGEMENT_NUDGES,
        )

        reset_nudge_budget()

        self.assertEqual(
            self._spend("s2", 0, DELEGATION_NUDGE_DIRECT_READ_THRESHOLD + 4).count(True),
            MAX_ENGAGEMENT_NUDGES,
        )

    def test_an_unreadable_store_restores_the_budget_rather_than_silencing_it(self) -> None:
        """Which way a broken file fails, stated rather than discovered.

        The alternative is a home whose store cannot be read disabling the
        nudge forever, which is the same direction `_plan_declared` already
        rejected for the same reason.
        """
        self.assertEqual(
            self._spend("s1", 0, DELEGATION_NUDGE_DIRECT_READ_THRESHOLD + 4).count(True),
            MAX_ENGAGEMENT_NUDGES,
        )
        engagement_nudge_store_path(self.home).write_text("{ truncated", encoding="utf-8")

        reset_nudge_budget()

        self.assertEqual(
            self._spend("s1", 100, DELEGATION_NUDGE_DIRECT_READ_THRESHOLD + 4).count(True),
            MAX_ENGAGEMENT_NUDGES,
        )

    def test_the_store_holds_counters_and_no_call_text(self) -> None:
        sentinel = "ZZNUDGEARGSENTINELZZ"
        for index in range(DELEGATION_NUDGE_DIRECT_READ_THRESHOLD + 2):
            _ = annotate_engagement_nudge(
                tool_name="search_files",
                result=f"{sentinel}-result",
                args={"pattern": sentinel, "path": f"src/{index}"},
                session_id="s1",
                omh_home=self.home,
                hermes_home=self.home,
            )

        written = engagement_nudge_store_path(self.home).read_text(encoding="utf-8")
        stored = json.loads(written)

        self.assertNotIn(sentinel, written)
        self.assertNotIn("search_files", written)
        self.assertEqual(stored["privacy"], "metadata_only")
        self.assertEqual(
            set(stored["sessions"]["s1"]) - {"ts"},
            {"plan_nudges", "delegation_nudges", "plan_declared", "lane_routed"},
        )
        self.assertEqual(stored["sessions"]["s1"]["delegation_nudges"], MAX_ENGAGEMENT_NUDGES)

    def test_an_evicted_session_does_not_get_its_budget_back(self) -> None:
        """Eviction must fail toward fewer nudges, not toward more.

        The process map is bounded at `MAX_TRACKED_SESSIONS`, and a spent
        budget that vanished with the row would be a second budget for a
        session that is still running -- the same defect the restart case
        above fixes, reached by a different door. The store outlives the
        row, so the reload answers.
        """
        self.assertEqual(
            self._spend("s1", 0, DELEGATION_NUDGE_DIRECT_READ_THRESHOLD + 4).count(True),
            MAX_ENGAGEMENT_NUDGES,
        )

        for index in range(MAX_TRACKED_SESSIONS + 1):
            _ = self._spend(f"filler-{index}", 0, 1)

        after = self._spend("s1", 100, DELEGATION_NUDGE_DIRECT_READ_THRESHOLD + 4)

        self.assertNotIn(True, after)

    def test_the_durable_field_names_are_the_ones_the_nudges_write(self) -> None:
        # Two spellings of one string in two files is a drift that shows up
        # only as a budget that quietly stopped persisting.
        self.assertEqual(
            DURABLE_ENGAGEMENT_FIELDS,
            {nudges._PLAN_NUDGES, nudges._DELEGATION_NUDGES, nudges._PLAN_LATCH, nudges._DELEGATION_LATCH},
        )
        self.assertNotIn(nudges._DIRECT_READS, DURABLE_ENGAGEMENT_FIELDS)
        self.assertNotIn(nudges._MUTATIONS, DURABLE_ENGAGEMENT_FIELDS)


if __name__ == "__main__":
    unittest.main()

"""Contracts for the repeated-tool-call circuit breaker at pre_tool_call.

The motivating session, measured: 20260919_140745_db409e, 409 tool calls,
203 of them `search_files`. The host's own guard refused 185 and the model
issued the identical call again every time; the same session then repeated
one `read_file` region 100+ times against the host's second guard. So the
loop is tool-agnostic, and a refusal message is something this model
demonstrably ignores.

Hence two stages, and these tests pin both: a `block` whose message the
model may ignore, and then an `approve`, which the host routes to the
human-approval gate instead of back to the model. Everything outside the
narrow positive case -- same session, a repeating cycle of at most four
calls whose arguments AND results repeat, this call one of that cycle's
own, recent, at a stage -- must allow. #1674 is what an over-broad
pre_tool_call veto costs, so the allow side is pinned harder than the
intervene side.

The same session alternated two `terminal` commands to the end of its
turn, which the consecutive-streak form of this guard could not see at
all (#1719), and it could not tell that loop from a status poll, which
has the same shape in its arguments and a different one in its results
(#1706). Those two are the subject of everything below the original
cases: `CycleAwareRepeatGuardTest`, `ResultAwareRepeatGuardTest` and
`UnattendedLaneTest` drive whole calls through the registered
`pre_tool_call` and `post_tool_call`, because the result digest only
exists on the second one and a test that called the module helpers
directly would be checking a path the host never takes.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from omh.plugin_bundle.omh.hooks.nudge_budget import note_delegated_session, reset_nudge_budget
from omh.plugin_bundle.omh.hooks.session_attendance import (
    SINGLE_QUERY_SESSION_ENV,
    UNATTENDED_APPROVAL_PLATFORMS,
    escalation_can_reach_a_person,
    note_session_platform,
    reset_session_attendance,
)
from omh.plugin_bundle.omh.hooks.tool_hooks import post_tool_call, pre_tool_call
from omh.plugin_bundle.omh.tool_bursts import (
    IDLE_REPEAT_HISTORY,
    MAX_DIGEST_INPUT_BYTES,
    MAX_INTERCEPTED_COUNT,
    MAX_REPEAT_HISTORY,
    MAX_RESULT_DIGEST_INPUT_BYTES,
    REPEAT_CALL_APPROVAL_THRESHOLD,
    REPEAT_CALL_BLOCK_THRESHOLD,
    REPEAT_CALL_ESCALATION_ATTEMPTS,
    REPEAT_CYCLE_MAX_PERIOD,
    REPEAT_STREAK_WINDOW_SECONDS,
    _required_laps,
    is_poller_tool,
    record_repeat_refusal,
    record_tool_call,
    repeat_call_directive,
    repeat_call_rule_key,
    repeat_call_streak,
    repeat_cycle_rule_key,
    tool_args_digest,
    tool_bursts_path,
    tool_call_projection,
    tool_result_digest,
)

# The arguments from the observed burn, used verbatim so the fixture keeps
# naming the failure it came from.
BURN_PATTERN = "def render_skill|def render_all|def write_skill|def sync_skills|def generate"
BURN_ARGS = {"pattern": BURN_PATTERN, "path": "src"}
NOW = 1_787_040_000.0


class RepeatCallBreakerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)

    def _call(self, tool="search_files", args=None, session="session-a"):
        return pre_tool_call(
            tool_name=tool,
            tool_input=BURN_ARGS if args is None else args,
            session_id=session,
            omh_home=str(self.home),
        )

    def _run_to_threshold(self, **kwargs):
        for index in range(REPEAT_CALL_BLOCK_THRESHOLD):
            self.assertIsNone(self._call(**kwargs), f"call {index + 1} must proceed")

    def _run_to_escalation(self, **kwargs):
        """Leave the streak one call short of the approval stage.

        Every refusal in between must be a block: ignoring a block is what
        earns the escalation, so a test that skipped them would be
        checking a stage nothing had reached.
        """
        self._run_to_threshold(**kwargs)
        for index in range(REPEAT_CALL_APPROVAL_THRESHOLD - REPEAT_CALL_BLOCK_THRESHOLD):
            directive = self._call(**kwargs)
            self.assertEqual(directive["action"], "block", f"refusal {index + 1} is stage one")

    def _ledger(self):
        return json.loads(tool_bursts_path(str(self.home)).read_text(encoding="utf-8"))

    def _streak(self, session="session-a"):
        # Attended, because these cases are about detection rather than
        # attendance; the withheld lane has its own class.
        return repeat_call_streak(str(self.home), session_id=session, escalation_allowed=True)

    def test_the_call_after_the_threshold_is_refused_and_names_the_alternative(self):
        self._run_to_threshold()

        blocked = self._call()

        self.assertEqual(blocked["action"], "block")
        message = str(blocked["message"])
        # The count is what actually ran: an intercepted call never
        # dispatches, so it is counted apart from the calls that did.
        self.assertIn(f"issued {REPEAT_CALL_BLOCK_THRESHOLD} times in a row", message)
        self.assertIn("search_files", message)
        # The observed failure was a model repeating a search instead of
        # switching tactic, so the refusal has to say what to do instead --
        # both ways, because the guard cannot tell a loop from a poll.
        self.assertIn("read the file directly", message.lower())
        self.assertIn("list what it does define", message)
        self.assertIn("do other work between checks", message)
        self.assertIn("A blocked call did not run", message)
        # Two sentences this message must never contain. The host's
        # refusal said "You already have this information", false in the
        # measured case because the pattern named functions that do not
        # exist. And OMH digests ARGUMENTS, never results, so any claim
        # about what came back is unmeasured -- and wrong for a poll.
        self.assertNotIn("already have this information", message)
        self.assertNotIn("same result", message)
        self.assertNotIn("cannot return anything different", message)
        self.assertIn("compares arguments, not results", message)
        # Still refused on the next attempt, and still reporting the number
        # of calls that reached the tool rather than the number attempted.
        again = self._call()
        self.assertEqual(again["action"], "block")
        self.assertIn(f"issued {REPEAT_CALL_BLOCK_THRESHOLD} times in a row", str(again["message"]))

    def test_the_second_stage_escalates_to_the_human_approval_gate(self):
        self._run_to_escalation()

        escalated = self._call()

        self.assertEqual(escalated["action"], "approve")
        self.assertEqual(
            escalated["rule_key"],
            f"omh_repeat:search_files:{tool_args_digest(BURN_ARGS)}",
        )
        message = str(escalated["message"])
        self.assertTrue(message)
        # Written for a person: which tool, how far it has gone, how many
        # times OMH already intervened, and what each answer does.
        self.assertIn("search_files", message)
        refusals = REPEAT_CALL_APPROVAL_THRESHOLD - REPEAT_CALL_BLOCK_THRESHOLD
        self.assertIn(f"{REPEAT_CALL_APPROVAL_THRESHOLD} times in a row", message)
        # Reworded, and the reason is a defect this sentence carried: an
        # allowed escalation runs the call WITHOUT `record_tool_call`
        # firing, so `ran` freezes at the threshold while the loop keeps
        # going. "The first 8 reached the tool" then told the person
        # reading the second card 8 when the truth was 13. The count is
        # still reported, as what OMH saw, with the gap named.
        self.assertIn(f"saw the first {REPEAT_CALL_BLOCK_THRESHOLD} reach the tool", message)
        self.assertIn(f"more than {REPEAT_CALL_BLOCK_THRESHOLD} may have run", message)
        self.assertIn(f"refused or escalated the {refusals}", message)
        self.assertIn("Denying ends the repetition", message)
        # The person deciding whether to allow a poll is exactly who must
        # not be told the result is unchanged, which OMH never measured.
        self.assertNotIn("same result", message)
        self.assertIn("cannot say whether the result is changing", message)
        # And it stays escalated, at one stable rule key, so a person who
        # answered "always" is not re-prompted by a key that changed.
        self.assertEqual(self._call()["rule_key"], escalated["rule_key"])

    def test_the_second_stage_is_not_reached_before_the_blocks_are_ignored(self):
        self._run_to_threshold()

        # One short of the escalation: every one of these is stage one.
        for _ in range(REPEAT_CALL_APPROVAL_THRESHOLD - REPEAT_CALL_BLOCK_THRESHOLD - 1):
            self.assertEqual(self._call()["action"], "block")

        self.assertEqual(self._call()["action"], "block")
        self.assertEqual(self._call()["action"], "approve")

    def test_no_argument_text_reaches_the_approval_prompt_or_its_rule_key(self):
        marker = "OMH-APPROVAL-ARGUMENT-CANARY"
        args = {"pattern": f"{marker}|{BURN_PATTERN}", "path": f"/private/{marker}"}
        self._run_to_escalation(args=args)

        escalated = self._call(args=args)

        self.assertEqual(escalated["action"], "approve")
        for field in ("message", "rule_key"):
            self.assertNotIn(marker, str(escalated[field]))
            self.assertNotIn(BURN_PATTERN, str(escalated[field]))
            self.assertNotIn("/private/", str(escalated[field]))
        self.assertIn(tool_args_digest(args), escalated["rule_key"])

    def test_a_different_call_between_the_stages_returns_to_the_start(self):
        self._run_to_escalation()
        self.assertEqual(self._call()["action"], "approve")

        self.assertIsNone(self._call(tool="read_file"))

        # Back to allowing, not back to stage one: both counters cleared.
        self.assertIsNone(self._call())
        streak = repeat_call_streak(str(self.home), session_id="session-a", escalation_allowed=True)
        self.assertEqual(streak["stage"], "watching")
        self.assertEqual(streak["intercepted"], 0)
        self.assertEqual(streak["consecutive"], 1)

    def test_the_staleness_window_clears_both_counters(self):
        digest = tool_args_digest(BURN_ARGS)
        for _ in range(REPEAT_CALL_BLOCK_THRESHOLD):
            record_tool_call(
                "search_files",
                omh_home=str(self.home),
                now=NOW,
                args_digest=digest,
                session_id="session-a",
            )
        for _ in range(REPEAT_CALL_APPROVAL_THRESHOLD - REPEAT_CALL_BLOCK_THRESHOLD):
            record_repeat_refusal(
                tool_name="search_files",
                args_digest=digest,
                session_id="session-a",
                omh_home=str(self.home),
                now=NOW,
            )
        self.assertEqual(
            repeat_call_directive(
                tool_name="search_files",
                args_digest=digest,
                session_id="session-a",
                omh_home=str(self.home),
                now=NOW,
            )["action"],
            "approve",
        )

        stale = NOW + REPEAT_STREAK_WINDOW_SECONDS + 1

        self.assertIsNone(
            repeat_call_directive(
                tool_name="search_files",
                args_digest=digest,
                session_id="session-a",
                omh_home=str(self.home),
                now=stale,
            )
        )
        self.assertEqual(
            repeat_call_streak(
                str(self.home), session_id="session-a", now=stale, escalation_allowed=True
            )["status"],
            "idle",
        )

    def test_two_sessions_do_not_add_up_at_the_approval_stage_either(self):
        self._run_to_escalation(session="session-a")
        # session-b has made this call once and must be nowhere near a
        # stage, however far session-a has gone with the identical call.
        self.assertIsNone(self._call(session="session-b"))

        self.assertEqual(self._call(session="session-a")["action"], "approve")
        self.assertIsNone(self._call(session="session-b"))

    def test_the_streak_reader_exposes_the_consecutive_count(self):
        self.assertEqual(
            repeat_call_streak(str(self.home), session_id="session-a", escalation_allowed=True)["status"],
            "idle",
        )
        self._run_to_threshold()
        self._call()

        streak = repeat_call_streak(str(self.home), session_id="session-a", escalation_allowed=True)

        self.assertEqual(streak["status"], "observed")
        self.assertEqual(streak["tool"], "search_files")
        self.assertEqual(streak["args_digest"], tool_args_digest(BURN_ARGS))
        self.assertEqual(streak["ran"], REPEAT_CALL_BLOCK_THRESHOLD)
        self.assertEqual(streak["intercepted"], 1)
        self.assertEqual(streak["consecutive"], REPEAT_CALL_BLOCK_THRESHOLD + 1)
        self.assertEqual(streak["stage"], "blocking")
        self.assertEqual(streak["period"], 1)
        self.assertEqual(streak["laps"], REPEAT_CALL_BLOCK_THRESHOLD)
        # No post_tool_call fired for these calls, so no result was
        # compared and the reader says so. A surface must read this field
        # before it renders anything about results.
        self.assertFalse(streak["results_compared"])
        # Changed with #1706, deliberately. The boundary used to say the
        # record was "never evidence of what any call returned", which
        # stopped being true the moment a result digest landed beside the
        # argument one. It now separates the two claims the record does
        # support -- that a call repeated, and that two returns matched
        # inside the digest bound -- from the one it still cannot make,
        # which is what came back.
        self.assertIn("compared by result digest", streak["claim_boundary"])
        self.assertIn("never evidence of WHAT any call returned", streak["claim_boundary"])
        # A reader for another session sees nothing of this one.
        self.assertEqual(
            repeat_call_streak(str(self.home), session_id="session-b", escalation_allowed=True)["status"],
            "idle",
        )

    def test_repeats_below_the_threshold_proceed(self):
        for _ in range(REPEAT_CALL_BLOCK_THRESHOLD - 1):
            self._call()

        self.assertIsNone(self._call())

    def test_a_different_digest_between_repeats_resets_the_count(self):
        self._run_to_threshold()

        self.assertIsNone(self._call(args={"pattern": BURN_PATTERN, "path": "tests"}))
        # Back to the original arguments: the run restarted, so this is
        # the first call of a new one, not the ninth of the old one.
        self.assertIsNone(self._call())
        # The assertion moved from a stored `count` to the derived lap
        # count, because the row no longer holds a counter: #1719 replaced
        # it with the bounded call history the cycle detector reads, and
        # the count a reader wants is now a property of that history.
        self.assertEqual(self._streak()["laps"], 1)

    def test_a_different_tool_between_repeats_resets_the_count(self):
        self._run_to_threshold()

        self.assertIsNone(self._call(tool="read_file"))
        self.assertIsNone(self._call())
        self.assertEqual(self._streak()["laps"], 1)

    def test_one_different_call_does_not_make_the_resumed_streak_a_cycle(self):
        """A,...,A,B,A,A,... starts over; it does not resume and it is not a cycle.

        Worth pinning because the host's detector would see a period-k
        cycle in a long enough alternation and this looks adjacent to one.
        It is not: after the single B the tail is A,A, two laps of period
        1, so the new run needs its own eight. The B was work that
        happened, and treating it as noise would let a model buy a fresh
        call budget by padding the loop with one real call -- the exact
        move the cycle detector exists to refuse when it is REPEATED.
        """
        self._run_to_threshold()
        self.assertIsNone(self._call(tool="read_file"))

        for index in range(REPEAT_CALL_BLOCK_THRESHOLD):
            self.assertIsNone(self._call(), f"call {index + 1} of the new run must proceed")

        self.assertEqual(self._call()["action"], "block")

    def test_two_sessions_making_the_same_call_do_not_add_up(self):
        # Interleaved, so an unkeyed counter would see one session making
        # 2x threshold identical calls in a row and refuse long before the
        # end of this loop.
        for _ in range(REPEAT_CALL_BLOCK_THRESHOLD):
            self.assertIsNone(self._call(session="session-a"))
            self.assertIsNone(self._call(session="session-b"))

        # Each session counted its own calls, and each is now at the
        # threshold on its own.
        self.assertEqual(self._call(session="session-a")["action"], "block")
        self.assertEqual(self._call(session="session-b")["action"], "block")

    def test_closing_each_call_does_not_disarm_the_guard(self):
        # post_tool_call rewrites the same ledger. A writer that dropped the
        # streak key would leave the guard permanently at one on any host
        # that pairs its tool calls, which is every current one.
        for index in range(REPEAT_CALL_BLOCK_THRESHOLD):
            self.assertIsNone(
                pre_tool_call(
                    tool_name="search_files",
                    tool_input=BURN_ARGS,
                    session_id="session-a",
                    omh_home=str(self.home),
                    tool_call_id=f"call-{index}",
                )
            )
            post_tool_call(tool_call_id=f"call-{index}", omh_home=str(self.home))

        self.assertEqual(self._call()["action"], "block")

    def test_a_missing_session_id_degrades_to_allow(self):
        for _ in range(REPEAT_CALL_BLOCK_THRESHOLD * 2):
            self.assertIsNone(self._call(session=""))

        self.assertEqual(self._ledger()["repeat_streaks"], {})

    def test_arguments_that_cannot_be_canonicalized_degrade_to_allow(self):
        circular: dict[str, object] = {"pattern": BURN_PATTERN}
        circular["self"] = circular

        self.assertEqual(tool_args_digest(circular), "")
        for _ in range(REPEAT_CALL_BLOCK_THRESHOLD * 2):
            self.assertIsNone(self._call(args=circular))

        self.assertEqual(self._ledger()["repeat_streaks"], {})

    def test_an_unreadable_ledger_degrades_to_allow(self):
        self._run_to_threshold()
        self.assertEqual(self._call()["action"], "block")

        tool_bursts_path(str(self.home)).write_text("{not json", encoding="utf-8")

        self.assertIsNone(self._call())

    def test_calls_that_aged_out_are_dropped_even_when_the_row_is_alive(self):
        """The row's own stamp is not enough; each call carries its own.

        A row stays alive as long as SOMETHING happens in it, so without a
        per-call window a session that made eight identical calls and then
        came back five minutes later would meet a refusal it earned in a
        turn that is over -- and a slow poll, identical arguments and an
        identical answer minutes apart, would read as one loop. The gate
        reads the window per entry so the calls it counts are the calls
        that were actually back to back.
        """
        digest = tool_args_digest(BURN_ARGS)
        for index in range(REPEAT_CALL_BLOCK_THRESHOLD):
            record_tool_call(
                "search_files",
                omh_home=str(self.home),
                now=NOW + index,
                args_digest=digest,
                session_id="session-a",
            )
        last_call = NOW + REPEAT_CALL_BLOCK_THRESHOLD - 1

        # One second inside the row-level window, so the row itself is not
        # what refuses: all but the last two calls have aged past it.
        gate = last_call + REPEAT_STREAK_WINDOW_SECONDS - 1

        self.assertIsNone(
            repeat_call_directive(
                tool_name="search_files",
                args_digest=digest,
                session_id="session-a",
                omh_home=str(self.home),
                now=gate,
            )
        )
        self.assertEqual(
            repeat_call_streak(
                str(self.home), session_id="session-a", now=gate, escalation_allowed=True
            )["laps"],
            2,
        )

    def test_a_streak_older_than_the_window_is_not_a_loop(self):
        digest = tool_args_digest(BURN_ARGS)
        for _ in range(REPEAT_CALL_BLOCK_THRESHOLD):
            record_tool_call(
                "search_files",
                omh_home=str(self.home),
                now=NOW,
                args_digest=digest,
                session_id="session-a",
            )

        self.assertIsNotNone(
            repeat_call_directive(
                tool_name="search_files",
                args_digest=digest,
                session_id="session-a",
                omh_home=str(self.home),
                now=NOW + REPEAT_STREAK_WINDOW_SECONDS,
            )
        )
        self.assertIsNone(
            repeat_call_directive(
                tool_name="search_files",
                args_digest=digest,
                session_id="session-a",
                omh_home=str(self.home),
                now=NOW + REPEAT_STREAK_WINDOW_SECONDS + 1,
            )
        )


class CycleAndResultHarness(unittest.TestCase):
    """Drives whole tool calls through the two registered hooks.

    `pre_tool_call` then `post_tool_call`, with a real result, because the
    result digest only exists on the second one and a test that called the
    module helpers directly would be checking a path the host never takes.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        # Process-global session facts, cleared both ways for the reason
        # `reset_nudge_budget` gives: the shard planner reorders tests, so
        # a map one test populated surfaces as a failure in another.
        reset_session_attendance()
        reset_nudge_budget()
        self.addCleanup(reset_session_attendance)
        self.addCleanup(reset_nudge_budget)
        self._sequence = 0

    def call(self, tool="terminal", *, args=None, result="", session="session-a"):
        """One tool call, gate then close, the way a sequential host runs it."""
        directive, close = self.open_call(tool, args=args, result=result, session=session)
        close()
        return directive

    def open_call(self, tool="terminal", *, args=None, result="", session="session-a"):
        """The gate now, and a callable that closes the call later.

        Split because Hermes does not wait. It dispatches a model turn's
        batched calls through a worker pool (`agent/tool_executor.py`), so
        several calls are open at once and the gate for one of them runs
        while its siblings are still in flight. A harness that always
        closed before the next gate modelled a host that does not exist,
        and that is the whole reason MF1 and MF2 of the #1745 review were
        invisible to 44 passing tests.

        The close is faithful about the other half too: the host fires
        `post_tool_call` for a BLOCKED call as well, with the refusal as
        the result and `status="blocked"`
        (`model_tools.handle_function_call`). So does this.
        """
        self._sequence += 1
        call_id = f"call-{self._sequence}"
        payload = {"command": tool} if args is None else args
        directive = pre_tool_call(
            tool_name=tool,
            tool_input=payload,
            session_id=session,
            omh_home=str(self.home),
            tool_call_id=call_id,
        )
        blocked = directive is not None and directive.get("action") == "block"

        def close():
            post_tool_call(
                tool_name=tool,
                args=payload,
                result=str(directive.get("message")) if blocked else result,
                status="blocked" if blocked else "ok",
                session_id=session,
                omh_home=str(self.home),
                tool_call_id=call_id,
            )

        return directive, close

    def drive_batched(self, plan, *, width, session="session-a"):
        """Run `plan` through a pool of `width`, returning one mark per call.

        `.` allowed, `B` blocked, `A` escalated -- the notation the #1745
        review used, so the ladders asserted here and the ones in the PR
        body are the same strings.

        The ordering is the pool's, and it is the part that matters. A
        worker takes the next call only once the previous one's post has
        fired, so up to `width` allowed calls are open at any moment. A
        BLOCKED call posts inline and immediately, because it did no
        work -- and that is the moment a refusal's digest can land in a
        sibling's waiting slot. A model that closed calls in open order
        instead never reproduces it, which is how the defect survived the
        first round of these tests.
        """
        marks, inflight = [], []
        for tool, args, result in plan:
            while len(inflight) >= width:
                inflight.pop(0)()
            directive, close = self.open_call(tool, args=args, result=result, session=session)
            marks.append(
                "." if directive is None else {"block": "B", "approve": "A"}[directive["action"]]
            )
            if directive is None:
                inflight.append(close)
            else:
                close()
        for close in inflight:
            close()
        return "".join(marks)

    @staticmethod
    def loop_plan(calls, *, tool="terminal", result="no matches"):
        """One call repeated: identical tool, arguments and result."""
        return [(tool, {"command": "grep nothing"}, result)] * calls

    @staticmethod
    def poll_plan(calls, *, tool="terminal"):
        """One call repeated with a different answer every time."""
        return [(tool, {"command": "gh pr checks 1745"}, f"pending {index}") for index in range(calls)]

    def drive_cycle(self, tools, laps, *, session="session-a", result="same"):
        """Run `laps` laps of a cycle, asserting every call was allowed."""
        for lap in range(laps):
            for tool in tools:
                self.assertIsNone(
                    self.call(tool, result=f"{result}-{tool}", session=session),
                    f"lap {lap + 1} call `{tool}` must proceed",
                )

    def streak(self, session="session-a"):
        return repeat_call_streak(str(self.home), session_id=session, escalation_allowed=True)


class CycleAwareRepeatGuardTest(CycleAndResultHarness):
    """#1719: a repeating cycle defeated the consecutive-streak counter.

    The measured session alternated two `terminal` commands -- A returned
    "0", B returned "" -- A, B, A, B, to the end of the turn. Every call
    differed from the one before it, so the streak this guard shipped with
    reset on every call and never reached a stage: armed, and silent,
    through the whole failure.
    """

    def test_an_alternating_pair_reaches_block_and_then_the_human_gate(self):
        # Period 2 needs four laps, which is the same eight calls a
        # period-1 streak gets. The ladder shape is unchanged: block, then
        # the approval gate four ignored blocks later.
        self.drive_cycle(("terminal_a", "terminal_b"), _required_laps(2))

        blocked = self.call("terminal_a")

        self.assertEqual(blocked["action"], "block")
        message = str(blocked["message"])
        self.assertIn("the same cycle of 2 tool calls", message)
        self.assertIn("`terminal_a`, `terminal_b`", message)
        self.assertIn(f"{_required_laps(2)} times in a row", message)
        for _ in range(REPEAT_CALL_ESCALATION_ATTEMPTS - 1):
            self.assertEqual(self.call("terminal_a")["action"], "block")

        escalated = self.call("terminal_a")

        self.assertEqual(escalated["action"], "approve")
        self.assertIn("the same cycle of 2 tool calls", str(escalated["message"]))

    def test_the_other_element_of_a_blocked_cycle_is_blocked_too(self):
        """The measured shape: one tool, two commands, alternating.

        Found by driving the ladder through the registered hooks rather
        than by re-issuing the blocked call, which is what the first pass
        of these tests did. A blocked call never runs, so the cycle's
        phase does not advance; a model that answers the block by issuing
        the OTHER element is one step along the same loop, and a gate
        that compared against "the element the cycle predicts next" read
        that as something new and allowed eight more calls.

        The observed ladder for a period-2 cycle, through
        `pre_tool_call` and `post_tool_call`: calls 1-8 allowed, 9-12
        blocked, 13 escalated -- the same shape a period-1 streak has.
        """
        commands = ({"command": "git status --short"}, {"command": "git diff --stat"})
        for lap in range(_required_laps(2)):
            for index, args in enumerate(commands):
                self.assertIsNone(
                    self.call("terminal", args=args, result=str(index)),
                    f"lap {lap + 1} call {index + 1} must proceed",
                )

        ladder = []
        for index in range(REPEAT_CALL_ESCALATION_ATTEMPTS + 1):
            directive = self.call("terminal", args=commands[index % 2])
            ladder.append(directive["action"])

        self.assertEqual(ladder, ["block"] * REPEAT_CALL_ESCALATION_ATTEMPTS + ["approve"])
        # And a call outside the cycle still clears it, which is the only
        # thing that ever did.
        self.assertIsNone(self.call("read_file", args={"path": "README.md"}))

    def test_a_same_tool_cycle_is_named_by_its_tool_once(self):
        commands = ({"command": "git status --short"}, {"command": "git diff --stat"})
        for _ in range(_required_laps(2)):
            for args in commands:
                self.call("terminal", args=args, result="0")

        message = str(self.call("terminal", args=commands[0])["message"])

        self.assertIn("the same cycle of 2 `terminal` calls", message)
        self.assertNotIn("`terminal`, `terminal`", message)
        # The arguments are what differ between the two, and they are
        # exactly what this message may not print.
        self.assertNotIn("git status", message)
        self.assertNotIn("git diff", message)

    def test_period_three_and_four_cycles_reach_stage_one_too(self):
        for period in (3, REPEAT_CYCLE_MAX_PERIOD):
            with self.subTest(period=period):
                self.setUp()
                tools = tuple(f"tool_{index}" for index in range(period))
                self.drive_cycle(tools, _required_laps(period))

                directive = self.call(tools[0])

                self.assertEqual(directive["action"], "block")
                self.assertIn(f"the same cycle of {period} tool calls", str(directive["message"]))

    def test_a_period_five_cycle_is_past_what_the_host_calls_a_cycle(self):
        """Five is not a cycle here because it is not one to the host either.

        `_STALL_GUARD_MAX_CYCLE_PERIOD` is 4. Two detectors that disagreed
        about what a cycle is would refuse different sequences, and a
        person comparing OMH's refusal with the host's note could not tell
        which of them was wrong.
        """
        tools = tuple(f"tool_{index}" for index in range(REPEAT_CYCLE_MAX_PERIOD + 1))

        self.drive_cycle(tools, 3)

        self.assertIsNone(self.call(tools[0]))

    def test_a_cycle_whose_one_element_keeps_changing_never_blocks(self):
        """One moving part is enough: the lap is not a repeat of the last one.

        The A,B alternation here is byte-identical in its arguments and in
        A's result; only B's output changes. That is a session making
        progress in a loop-shaped way, and the guard has to leave it
        alone.
        """
        for lap in range(REPEAT_CALL_APPROVAL_THRESHOLD * 2):
            self.assertIsNone(self.call("terminal_a", result="0"))
            self.assertIsNone(self.call("terminal_b", result=f"progress {lap}"))

        self.assertEqual(self.streak()["stage"], "watching")

    def test_the_rule_key_is_the_same_for_either_rotation_of_one_cycle(self):
        """A,B,A,B and B,A,B,A are one loop, so they are one allowlist grain.

        A key derived from where detection happened to land would differ
        between the two and re-prompt a person who already answered
        `[a]lways` for this exact loop.
        """
        self.drive_cycle(("terminal_a", "terminal_b"), _required_laps(2), session="session-a")
        self.drive_cycle(("terminal_b", "terminal_a"), _required_laps(2), session="session-b")
        for _ in range(REPEAT_CALL_ESCALATION_ATTEMPTS):
            self.assertEqual(self.call("terminal_a", session="session-a")["action"], "block")
            self.assertEqual(self.call("terminal_b", session="session-b")["action"], "block")

        first = self.call("terminal_a", session="session-a")
        second = self.call("terminal_b", session="session-b")

        self.assertEqual(first["action"], "approve")
        self.assertEqual(second["action"], "approve")
        self.assertEqual(first["rule_key"], second["rule_key"])
        # And it is the cycle's own key, not either element's. The space
        # is load-bearing: `_normalized_name` joins a tool name on
        # whitespace and so can never produce one, which is what keeps a
        # tool literally named `cycle2` out of this namespace.
        self.assertTrue(first["rule_key"].startswith("omh_repeat:cycle 2:"))
        self.assertNotIn(
            " ",
            repeat_call_rule_key("any_tool_name", "0123456789abcdef").split(":", 1)[1],
        )

    def test_the_rotation_canonical_key_is_computed_not_taken_from_position(self):
        elements = [
            {"tool": "terminal_a", "args_digest": "aaaa"},
            {"tool": "terminal_b", "args_digest": "bbbb"},
            {"tool": "terminal_c", "args_digest": "cccc"},
        ]

        keys = {
            repeat_cycle_rule_key(elements[index:] + elements[:index])
            for index in range(len(elements))
        }

        self.assertEqual(len(keys), 1)
        # A different cycle is a different key, so the rotation fold did
        # not collapse everything to one value.
        self.assertNotEqual(
            keys.pop(),
            repeat_cycle_rule_key(elements[:2] + [{"tool": "terminal_d", "args_digest": "dddd"}]),
        )

    def test_two_sessions_running_the_same_cycle_do_not_add_up(self):
        # Interleaved, so a ledger that did not key by session would see
        # one run of twice the laps and refuse in the middle of this loop.
        for _ in range(_required_laps(2)):
            for session in ("session-a", "session-b"):
                self.assertIsNone(self.call("terminal_a", result="0", session=session))
                self.assertIsNone(self.call("terminal_b", result="", session=session))

        self.assertEqual(self.call("terminal_a", session="session-a")["action"], "block")
        self.assertEqual(self.call("terminal_a", session="session-b")["action"], "block")

    def _stored_history(self, session="session-a"):
        ledger = json.loads(tool_bursts_path(str(self.home)).read_text(encoding="utf-8"))
        return ledger["repeat_streaks"][session]["history"]

    def test_a_session_that_is_not_looping_keeps_only_the_idle_history(self):
        """The row shape almost every session in a busy ledger has.

        A period-6 rotation is longer than anything the detector reads, so
        this session is never in a cycle and never needs more than the two
        laps it takes to find one. Pinned because it is where the ledger's
        size comes from: `pre_tool_call` rereads and rewrites this file on
        every allowed call, and 64 idle sessions holding a full history
        each is the difference the trim exists to avoid.
        """
        for index in range(MAX_REPEAT_HISTORY * 3):
            self.call(f"tool_{index % (REPEAT_CYCLE_MAX_PERIOD + 2)}", result=str(index))

        self.assertEqual(len(self._stored_history()), IDLE_REPEAT_HISTORY)

    def test_a_looping_session_keeps_the_laps_the_idle_trim_would_have_cut(self):
        """A live cycle releases the trim, and never passes the hard cap.

        Period 4 is the only period whose engagement needs more than the
        idle window: twelve calls, where a trim to eight would have
        thrown away the first lap and reset the count every time.
        """
        tools = tuple(f"tool_{index}" for index in range(REPEAT_CYCLE_MAX_PERIOD))

        self.drive_cycle(tools, _required_laps(REPEAT_CYCLE_MAX_PERIOD))

        stored = self._stored_history()
        self.assertEqual(len(stored), REPEAT_CYCLE_MAX_PERIOD * _required_laps(REPEAT_CYCLE_MAX_PERIOD))
        self.assertGreater(len(stored), IDLE_REPEAT_HISTORY)
        self.assertLessEqual(len(stored), MAX_REPEAT_HISTORY)

    def test_the_idle_trim_does_not_cost_a_later_cycle_its_laps(self):
        """Eight entries is enough to find any cycle this detector reads.

        Driven through the longest period after a run of unrelated calls,
        because the trim only ever fires while no cycle is live and the
        question is whether what it dropped was reachable.
        """
        for index in range(MAX_REPEAT_HISTORY * 2):
            self.call(f"noise_{index}", result=str(index))
        tools = tuple(f"tool_{index}" for index in range(REPEAT_CYCLE_MAX_PERIOD))

        self.drive_cycle(tools, _required_laps(REPEAT_CYCLE_MAX_PERIOD))

        directive = self.call(tools[0])
        self.assertEqual(directive["action"], "block")
        self.assertEqual(self.streak()["laps"], _required_laps(REPEAT_CYCLE_MAX_PERIOD))

    def test_the_ladder_costs_a_long_cycle_more_calls_but_not_four_times_more(self):
        """What "the 9th identical call" translates to for periods 2 to 4.

        Counting laps alone would give a period-4 cycle 32 calls before
        anyone noticed, four times a period-1 streak's budget, bought by
        padding the loop. The floor on laps is what keeps a coincidental
        alternation from reading as a loop, and it is the whole of the
        extra cost.
        """
        self.assertEqual(
            {period: period * _required_laps(period) for period in range(1, REPEAT_CYCLE_MAX_PERIOD + 1)},
            {1: 8, 2: 8, 3: 9, 4: 12},
        )


class ResultAwareRepeatGuardTest(CycleAndResultHarness):
    """#1706: identical arguments say nothing about whether anything moved."""

    POLL_ARGS = {"command": "gh pr checks 1706"}

    def test_a_poll_whose_result_changes_never_reaches_a_stage(self):
        for index in range(REPEAT_CALL_APPROVAL_THRESHOLD * 4):
            self.assertIsNone(
                self.call(args=self.POLL_ARGS, result=f"pending ({index} checks reported)"),
                f"poll {index + 1} must proceed",
            )

        self.assertEqual(self.streak()["stage"], "watching")
        self.assertEqual(self.streak()["laps"], 1)

    def test_the_same_poll_returning_the_same_answer_does_reach_a_stage(self):
        for _ in range(REPEAT_CALL_BLOCK_THRESHOLD):
            self.assertIsNone(self.call(args=self.POLL_ARGS, result="no checks reported"))

        directive = self.call(args=self.POLL_ARGS, result="no checks reported")

        self.assertEqual(directive["action"], "block")

    def test_the_message_claims_identical_results_only_when_they_were_compared(self):
        for _ in range(REPEAT_CALL_BLOCK_THRESHOLD):
            self.call(args=self.POLL_ARGS, result="no checks reported")

        measured = str(self.call(args=self.POLL_ARGS)["message"])

        self.assertIn("every one returned the same result", measured)
        self.assertNotIn("compares arguments, not results", measured)
        self.assertTrue(self.streak()["results_compared"])

    def test_a_host_that_never_closes_a_call_falls_back_to_arguments_only(self):
        """No post_tool_call, no result digest, and no claim about results.

        This is the shape of a host whose `VALID_HOOKS` predates
        post_tool_call, where `_register_optional_hook` never registers
        it. The guard must still work on arguments -- that is what #1708
        shipped -- and must not say a word about what came back.
        """
        for _ in range(REPEAT_CALL_BLOCK_THRESHOLD):
            self.assertIsNone(
                pre_tool_call(
                    tool_name="search_files",
                    tool_input=BURN_ARGS,
                    session_id="session-a",
                    omh_home=str(self.home),
                )
            )

        directive = pre_tool_call(
            tool_name="search_files",
            tool_input=BURN_ARGS,
            session_id="session-a",
            omh_home=str(self.home),
        )

        self.assertEqual(directive["action"], "block")
        self.assertIn("compares arguments, not results", str(directive["message"]))
        self.assertNotIn("same result", str(directive["message"]))
        self.assertFalse(self.streak()["results_compared"])

    def test_the_result_digest_reads_length_as_well_as_a_bounded_prefix(self):
        body = "x" * MAX_RESULT_DIGEST_INPUT_BYTES

        self.assertEqual(len(tool_result_digest("ok")), 16)
        self.assertEqual(tool_result_digest("ok"), tool_result_digest("ok"))
        self.assertNotEqual(tool_result_digest("ok"), tool_result_digest("no"))
        # Past the cap the prefix stops distinguishing, so the length is
        # what keeps a growing log from reading as unchanged -- the
        # direction that would otherwise block a legitimate poll.
        self.assertNotEqual(tool_result_digest(body + "a"), tool_result_digest(body + "bb"))
        # The limit that remains, stated rather than hidden: same length,
        # differing only past the bound, reads as identical.
        self.assertEqual(tool_result_digest(body + "a"), tool_result_digest(body + "b"))
        # Anything that is not text is unknown, never a guessed digest.
        self.assertEqual(tool_result_digest({"content": "ok"}), "")
        self.assertEqual(tool_result_digest(None), "")


class BatchedDispatchTest(CycleAndResultHarness):
    """What the guard does when the host dispatches a batch concurrently.

    Hermes runs a model turn's batched tool calls through a worker pool
    (`agent/tool_executor.py`), so the gate for one call runs while its
    siblings are in flight, and it fires `post_tool_call` for a blocked
    call as well as an allowed one. The first 44 tests of this file
    modelled neither, and two defects lived in that gap: the guard
    digested its own refusal into a sibling's history entry, and it
    counted a call that had not returned as evidence that nothing had
    changed.

    The ladders below are the notation the #1745 review used, so the
    strings here and the strings in the PR body are the same strings.
    """

    LADDER_WIDTH_1 = "........BBBBAAAAAAAA"

    def test_a_loop_reaches_the_person_at_every_dispatch_width(self):
        """The regression that mattered: at width 2 it never escalated.

        The host posts for a blocked call with OMH's own refusal as the
        result. That digest landed in the oldest history entry still
        waiting -- a SIBLING call that really ran, since the two match on
        tool and arguments -- the cycle chain broke, and the ladder
        restarted. #1708 escalated at call 13 at any width, so the loss
        was a regression and not a new limit.
        """
        observed = {
            width: self.drive_batched(self.loop_plan(20), width=width, session=f"s{width}")
            for width in (1, 2, 8)
        }

        self.assertEqual(observed[1], self.LADDER_WIDTH_1)
        for width in (2, 8):
            with self.subTest(width=width):
                # Later than sequential, because a call in flight is not
                # yet evidence, and that is the stated cost of the fix.
                # Reaching a person at all is the part that is not
                # negotiable.
                self.assertIn("A", observed[width], observed[width])
                self.assertLess(observed[width].index("B"), observed[width].index("A"))

    def test_the_observed_batched_ladders_are_pinned(self):
        """Exact strings, so a change to the ladder has to be read and stated."""
        self.assertEqual(
            {
                width: self.drive_batched(self.loop_plan(24), width=width, session=f"s{width}")
                for width in (1, 2, 8)
            },
            {
                1: "........BBBBAAAAAAAAAAAA",
                2: ".........BBBBAAAAAAAAAAA",
                8: "...............BBBBAAAAA",
            },
        )

    def test_a_batched_poll_is_never_interrupted(self):
        """#1706's criterion, on the dispatch shape that broke it.

        Identical arguments, a different answer every call. Sequentially
        the guard never touched it; eight wide it blocked at call 9,
        because an in-flight sibling has no result and the comparison
        fell back to arguments alone.
        """
        for width in (1, 2, 8):
            with self.subTest(width=width):
                ladder = self.drive_batched(self.poll_plan(24), width=width, session=f"poll{width}")
                self.assertEqual(ladder, "." * 24, ladder)

    def test_a_cycle_with_one_element_that_never_returns_blocks_once(self):
        """The ladder does not climb here, and that is worth pinning either way.

        Period 2 where element A returns and element B never does. The
        blocked call is deliberately not appended, so the recorded
        sequence gains a doubled element, the next call finds no cycle,
        and `_advance_repeat_streak` resets the interception count and
        trims the history. The result is one block and then a fresh
        start, repeating.

        Base never intervened in this shape at all, so the direction is
        an improvement. It is pinned because nothing else distinguishes
        "one block, then reset" from "working", and a future change that
        makes the ladder climb here should have to say so.
        """
        marks, inflight = [], []
        for index in range(24):
            tool = "terminal_a" if index % 2 == 0 else "terminal_b"
            directive, close = self.open_call(tool, result="0")
            marks.append("." if directive is None else {"block": "B", "approve": "A"}[directive["action"]])
            if directive is None and tool == "terminal_a":
                close()          # A returns
            elif directive is not None:
                close()          # a blocked call still posts
            else:
                inflight.append(close)   # B never returns

        ladder = "".join(marks)
        self.assertNotIn("A", ladder, ladder)
        self.assertEqual(ladder.count("B"), 1, ladder)
        for close in inflight:
            close()

    def test_a_blocked_calls_own_refusal_never_becomes_a_history_result(self):
        """The mechanism, isolated from the ladder it broke.

        Driven sequentially so exactly one entry can be waiting, then
        asserted on the stored bytes: the block message's digest must not
        be in the ledger at all.
        """
        plan = self.loop_plan(REPEAT_CALL_BLOCK_THRESHOLD + 1)
        for tool, args, result in plan[:-1]:
            self.assertIsNone(self.call(tool, args=args, result=result))
        tool, args, result = plan[-1]
        directive, close = self.open_call(tool, args=args, result=result)
        self.assertEqual(directive["action"], "block")

        close()

        written = tool_bursts_path(str(self.home)).read_text(encoding="utf-8")
        self.assertNotIn(tool_result_digest(str(directive["message"])), written)
        self.assertIn(tool_result_digest(result), written)
        # And the streak is untouched by the close, so the next call is
        # still refused on the same evidence.
        self.assertEqual(self.streak()["laps"], REPEAT_CALL_BLOCK_THRESHOLD)

    def test_both_tool_hooks_read_the_arguments_the_same_way(self):
        """A caller supplying both spellings must digest one dict, not two.

        `pre_tool_call` preferred `tool_input`, `post_tool_call`
        preferred `args`. Harmless while the host passes only `args` --
        and invisible, because the entry then stays unknown for the
        wrong reason and the guard degrades correctly by accident.
        """
        for index in range(REPEAT_CALL_BLOCK_THRESHOLD):
            self.assertIsNone(
                pre_tool_call(
                    tool_name="terminal",
                    tool_input=BURN_ARGS,
                    args={"command": "something else entirely"},
                    session_id="session-a",
                    omh_home=str(self.home),
                    tool_call_id=f"c{index}",
                )
            )
            post_tool_call(
                tool_name="terminal",
                tool_input=BURN_ARGS,
                args={"command": "something else entirely"},
                result="no matches",
                status="ok",
                session_id="session-a",
                omh_home=str(self.home),
                tool_call_id=f"c{index}",
            )

        # The result landed on the entry the gate created, so the cycle
        # is result-compared rather than argument-only.
        self.assertTrue(self.streak()["results_compared"])
        self.assertEqual(self.streak()["laps"], REPEAT_CALL_BLOCK_THRESHOLD)

    def test_a_host_that_posts_no_result_at_all_keeps_the_argument_guard(self):
        """The fallback exists for this host and no other.

        Nothing in the history has a result, so there is no result
        evidence to prefer, and the ladder is the argument-only one #1708
        shipped -- at any dispatch width.
        """
        for index in range(REPEAT_CALL_BLOCK_THRESHOLD):
            self.assertIsNone(
                pre_tool_call(
                    tool_name="search_files",
                    tool_input=BURN_ARGS,
                    session_id="session-a",
                    omh_home=str(self.home),
                    tool_call_id=f"c{index}",
                )
            )

        directive = pre_tool_call(
            tool_name="search_files",
            tool_input=BURN_ARGS,
            session_id="session-a",
            omh_home=str(self.home),
        )

        self.assertEqual(directive["action"], "block")
        self.assertFalse(self.streak()["results_compared"])


class BlockMessageTest(CycleAndResultHarness):
    """The one text in this module the model acts on."""

    def test_the_block_message_names_the_rule_the_gate_applies(self):
        """It used to tell the model to do the thing the guard now refuses.

        "any different tool call clears the guard" was true while the
        guard watched a single repeated call. Under a cycle the OTHER
        element is a different tool call and is refused, so the model
        would read the refusal, do exactly what it said, and be refused
        again. Pinned on the behaviour as well as the wording: the other
        element is blocked, a call outside the cycle is not.
        """
        commands = ({"command": "git status"}, {"command": "git diff"})
        for _ in range(_required_laps(2)):
            for args in commands:
                self.assertIsNone(self.call("terminal", args=args, result="0"))

        blocked = self.call("terminal", args=commands[0])

        message = str(blocked["message"])
        self.assertIn("any call outside that cycle clears the guard", message)
        self.assertNotIn("different tool call clears", message)
        # The sentence has to match the gate, so assert the gate too.
        self.assertEqual(self.call("terminal", args=commands[1])["action"], "block")
        self.assertIsNone(self.call("read_file", args={"path": "README.md"}))

    def test_the_cycle_rule_key_namespace_cannot_collide_with_a_tool_name(self):
        """F8's separator, under a name a reader looking for it will find.

        It was pinned only by a literal inside a test about rotation.
        `_normalized_name` joins a tool name on whitespace, so a space is
        the one character it can never produce, which is what keeps a
        tool literally named `cycle2` out of the cycle namespace.
        """
        elements = [
            {"tool": "alpha", "args_digest": "1111111111111111"},
            {"tool": "beta", "args_digest": "2222222222222222"},
        ]

        cycle_key = repeat_cycle_rule_key(elements)
        tool_key = repeat_call_rule_key("cycle2", "3333333333333333")

        self.assertIn(" ", cycle_key)
        self.assertNotIn(" ", tool_key)
        self.assertNotEqual(cycle_key.split(":")[1], tool_key.split(":")[1])


class BoundedStateTest(CycleAndResultHarness):
    """Bounds that no other test would notice going away."""

    def test_the_interception_count_is_capped(self):
        """A session that ignores the guard cannot grow a field forever.

        `intercepted` increments on every refusal, in a file the hot path
        rewrites on every call, and nothing else would notice the cap
        going away: past the block stage every rung reads the same, so
        the number stops meaning anything long before it stops growing.
        """
        for _ in range(REPEAT_CALL_BLOCK_THRESHOLD):
            self.assertIsNone(self.call(args=BURN_ARGS, result="no matches"))
        self.assertEqual(self.call(args=BURN_ARGS)["action"], "block")

        # Park the row one short of the ceiling, then refuse once more.
        path = tool_bursts_path(str(self.home))
        ledger = json.loads(path.read_text(encoding="utf-8"))
        ledger["repeat_streaks"]["session-a"]["intercepted"] = MAX_INTERCEPTED_COUNT
        path.write_text(json.dumps(ledger), encoding="utf-8")

        # At the ceiling the ladder is long past stage one, so the next
        # refusal is the escalation; what matters here is the counter.
        self.assertEqual(self.call(args=BURN_ARGS)["action"], "approve")

        stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            stored["repeat_streaks"]["session-a"]["intercepted"], MAX_INTERCEPTED_COUNT
        )

    def test_the_ledger_is_written_without_pretty_printing(self):
        """F6's cheapest win, otherwise unenforced.

        Removing `compact=True` from all three writes left the whole
        suite green, so a later edit could revert it silently. Every
        reader of this file is `json.loads`, so the only thing the flag
        changes is the bytes the hot path parses and rewrites -- which is
        exactly why it needs a gate rather than a comment.
        """
        for _ in range(4):
            self.call(args=BURN_ARGS, result="no matches")

        raw = tool_bursts_path(str(self.home)).read_text(encoding="utf-8")

        self.assertEqual(len(raw.strip().splitlines()), 1, "the ledger is one line")
        self.assertNotIn('": ', raw, "compact separators, no space after a key")
        # Still valid JSON, and still holding what the guard needs.
        self.assertEqual(len(json.loads(raw)["repeat_streaks"]["session-a"]["history"]), 4)


class PollerExemptionTest(CycleAndResultHarness):
    """The tools the host exempts, exempted here by the host's own rule.

    `agent/tool_guardrails.py` names `process_manage` and any tool ending
    `_poll` or `_get_result` as "legitimately re-invoked with identical
    args", and skips a cycle made only of them. Result-awareness covers a
    poll whose output moves; it does not cover the case the host actually
    names, a status poll returning the same line, which is the tool a
    model is told to use while it waits.
    """

    def test_a_status_poll_returning_the_same_line_is_never_refused(self):
        for tool in ("process_manage", "mcp_worker_poll", "job_get_result"):
            with self.subTest(tool=tool):
                self.setUp()
                for index in range(REPEAT_CALL_APPROVAL_THRESHOLD * 2):
                    self.assertIsNone(
                        self.call(tool, args={"action": "status"}, result="running"),
                        f"{tool} check {index + 1} must proceed",
                    )
                self.assertEqual(self.streak()["stage"], "watching")

    def test_a_cycle_that_only_partly_polls_is_still_a_loop(self):
        """The host `continue`s to a longer period rather than returning.

        A cycle of a poller and a real tool is a loop with a poll inside
        it, and exempting it would let one `_poll` call launder any
        repetition.
        """
        for _ in range(_required_laps(2)):
            self.assertIsNone(self.call("process_manage", args={"action": "status"}, result="running"))
            self.assertIsNone(self.call("search_files", args=BURN_ARGS, result=""))

        directive = self.call("process_manage", args={"action": "status"})

        self.assertEqual(directive["action"], "block")

    def test_the_all_poller_skip_continues_to_a_longer_period(self):
        """What `continue` buys over `return None`, measured, not asserted.

        `terminal`, poll, poll: the period-1 tail is an all-poller cycle
        and is skipped, and the mixed period-3 cycle is found at call 10.
        With `return None` the same loop is found at call 11 instead --
        one call, because the next call's own detection picks it up. The
        earlier comment implied the detection would be lost, which is
        not what happens, and this pins the difference that is real.
        """
        plan = [
            (tool, {"a": tool}, "same")
            for _ in range(5)
            for tool in ("terminal", "mcp_x_poll", "mcp_x_poll")
        ]

        ladder = self.drive_batched(plan[:14], width=1)

        self.assertEqual(ladder, ".........BBBBA", ladder)

    def test_the_exemption_is_the_hosts_predicate(self):
        self.assertTrue(is_poller_tool("process_manage"))
        self.assertTrue(is_poller_tool("mcp_anything_poll"))
        self.assertTrue(is_poller_tool("x_get_result"))
        self.assertFalse(is_poller_tool("search_files"))
        self.assertFalse(is_poller_tool("terminal"))
        # Not a substring match: the host anchors on the suffix.
        self.assertFalse(is_poller_tool("poll_the_thing"))


class UnattendedLaneTest(CycleAndResultHarness):
    """Stage two asks a person; these are the lanes where there is none.

    Measured at `tools/approval.py` `_run_approval_gate`: an unattended
    context resolves instantly rather than parking on a card nobody can
    answer, and it resolves two ways. At the `approvals.unattended_mode`
    default of `deny` it returns the HOST's block text, losing OMH's
    advice and closing by telling the reader to set the mode to
    `approve`. At `approve` it returns `_approved()` -- so the escalation
    would RUN the call stage one had been refusing. The second is why
    this gate exists: stage two would be the first rung of the ladder
    that makes a loop worse.

    Which lanes those are is the approval layer's question, not the
    tool-loop guardrail's, and the two sets disagree. These cases pin the
    platform the wrong set got backwards and the ones it withheld from
    needlessly.
    """

    def _run_past_the_escalation_point(self, session):
        for _ in range(REPEAT_CALL_BLOCK_THRESHOLD):
            self.assertIsNone(self.call(args=BURN_ARGS, result="", session=session))
        for _ in range(REPEAT_CALL_ESCALATION_ATTEMPTS + 2):
            directive = self.call(args=BURN_ARGS, result="", session=session)
            self.assertIsNotNone(directive)
            yield directive

    def test_api_server_is_blocked_and_never_escalated(self):
        """The platform the first version of this gate got backwards.

        `api_server` is in `agent/tool_guardrails.py`'s
        `_ATTENDED_PLATFORMS` and also in
        `tools/approval_context.py`'s `_UNATTENDED_APPROVAL_PLATFORMS`
        ("no human can answer a prompt"). Copying the first set made OMH
        escalate on the one surface where the escalation resolves through
        `approvals.unattended_mode` and, at `approve`, runs the looping
        call.
        """
        note_session_platform("session-api", "api_server")
        self.assertFalse(escalation_can_reach_a_person("session-api"))

        actions = {d["action"] for d in self._run_past_the_escalation_point("session-api")}

        self.assertEqual(actions, {"block"})
        # The stage still advanced; only the directive was withheld.
        self.assertEqual(
            repeat_call_streak(
                str(self.home), session_id="session-api", escalation_allowed=True
            )["stage"],
            "approval",
        )

    def test_the_other_programmatic_platforms_are_blocked_too(self):
        for platform in sorted(UNATTENDED_APPROVAL_PLATFORMS):
            with self.subTest(platform=platform):
                self.setUp()
                note_session_platform("s", platform)
                self.assertFalse(escalation_can_reach_a_person("s"))

    def test_a_chat_gateway_reaches_the_person_who_can_answer_there(self):
        """Withheld needlessly by the first version of this gate.

        `_is_gateway_approval_context` is true for a bound platform that
        is neither cron nor programmatic, and `_await_gateway_decision`
        puts the card in front of a real person on that surface.
        """
        note_session_platform("session-chat", "slack")
        self.assertTrue(escalation_can_reach_a_person("session-chat"))

        actions = {d["action"] for d in self._run_past_the_escalation_point("session-chat")}

        self.assertEqual(actions, {"block", "approve"})

    def test_a_delegated_child_is_blocked_and_never_escalated(self):
        note_session_platform("session-child", "tui")
        note_delegated_session("session-child")

        actions = {d["action"] for d in self._run_past_the_escalation_point("session-child")}

        self.assertEqual(actions, {"block"})

    def test_an_attended_platform_still_reaches_the_human_gate(self):
        note_session_platform("session-tui", "tui")

        actions = {d["action"] for d in self._run_past_the_escalation_point("session-tui")}

        self.assertEqual(actions, {"block", "approve"})

    def test_a_single_query_process_is_blocked_and_never_escalated(self):
        """`hermes chat -q` is `platform == "cli"`, so only the marker sees it.

        The host exports this one into the process environment on both
        entry paths (`cli.py`, `hermes_cli/oneshot.py`), and a `-q` run is
        a process dedicated to one turn, so reading it there is sound.
        """
        note_session_platform("session-oneshot", "cli")
        with mock.patch.dict(os.environ, {SINGLE_QUERY_SESSION_ENV: "1"}):
            self.assertFalse(escalation_can_reach_a_person("session-oneshot"))
            actions = {d["action"] for d in self._run_past_the_escalation_point("session-oneshot")}
        self.assertEqual(actions, {"block"})
        # Marker gone, same session: the lane is attended again.
        self.assertTrue(escalation_can_reach_a_person("session-oneshot"))

    def test_cron_is_not_detectable_from_a_plugin_and_reads_as_attended(self):
        """The honest state, pinned so nobody re-adds the read that cannot fire.

        `HERMES_CRON_SESSION` is a ContextVar name and never a process
        variable: the in-process ticker binds it through
        `gateway.session_context`, the detached worker's environment is
        built without it, and the host's own test asserts
        `os.environ.get("HERMES_CRON_SESSION") is None` after a job. A
        plugin cannot read a host ContextVar, so a cron turn is
        indistinguishable from an ordinary one here and escalates.

        An earlier version of this module read that variable and a test
        set it with `mock.patch.dict`, which proved the predicate reads a
        name and not that the host ever writes it. Asserting the variable
        is absent AND the lane still escalates is the claim that can
        actually be checked.
        """
        note_session_platform("session-cron", "telegram")

        self.assertIsNone(os.environ.get("HERMES_CRON_SESSION"))
        self.assertTrue(escalation_can_reach_a_person("session-cron"))
        # Setting it changes nothing, because nothing reads it.
        with mock.patch.dict(os.environ, {"HERMES_CRON_SESSION": "1"}):
            self.assertTrue(escalation_can_reach_a_person("session-cron"))

    def test_a_session_with_no_recorded_platform_still_escalates(self):
        """Unknown is not unattended, and the direction matches the host.

        `_is_gateway_approval_context` answers True for any bound
        platform that is not cron and not one of the three programmatic
        ones, so a surface Hermes adds later has a reader. Refusing to
        escalate on a platform this file has not heard of would disarm
        the one capability this guard has that the host's does not, on
        every such surface.
        """
        self.assertTrue(escalation_can_reach_a_person("session-unknown"))

        actions = {d["action"] for d in self._run_past_the_escalation_point("session-unknown")}

        self.assertIn("approve", actions)

    def test_the_reader_never_renders_a_stage_the_gate_withholds(self):
        """`_repeat_stage`'s docstring claims this, so it has to be true.

        The gate took the attendance answer and the reader did not, so a
        withheld lane blocked while its own projection said `approval` --
        an overclaim in a docstring written by the change that broke it.
        The HUD row in #1687 will read this projection.
        """
        note_session_platform("session-api", "api_server")
        for directive in self._run_past_the_escalation_point("session-api"):
            self.assertEqual(directive["action"], "block")

        allowed = escalation_can_reach_a_person("session-api")

        self.assertFalse(allowed)
        self.assertEqual(
            repeat_call_streak(
                str(self.home), session_id="session-api", escalation_allowed=allowed
            )["stage"],
            "blocking",
        )
        # Passing the attended answer still reports stage two, so this is
        # a threaded predicate and not a reader that stopped reporting an
        # escalation at all.
        self.assertEqual(
            repeat_call_streak(
                str(self.home), session_id="session-api", escalation_allowed=True
            )["stage"],
            "approval",
        )

    def test_the_reader_cannot_be_called_without_the_attendance_answer(self):
        """`_repeat_stage` claims one rule; the signature is what enforces it.

        A default let a caller omit the answer and render `approval` on a
        withheld lane, which is what the first fix for this shipped and
        what its own test then asserted. No default means the
        disagreement cannot be written.
        """
        with self.assertRaises(TypeError):
            repeat_call_streak(str(self.home), session_id="session-a")  # type: ignore[call-arg]


class LedgerPrivacyTest(unittest.TestCase):
    """The ledger may hold a fingerprint of a call, never its text.

    Both halves now: the arguments, and what the call returned. The
    result digest is the newer one and the one worth watching, because a
    tool result is the larger and more sensitive of the two -- a file
    body, a command's output, a page.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)

    def test_no_result_text_reaches_the_written_ledger(self):
        argument_marker = "OMH-REPEAT-GUARD-ARGUMENT-CANARY"
        result_marker = "OMH-REPEAT-GUARD-RESULT-CANARY"
        args = {"pattern": argument_marker, "path": f"/private/{argument_marker}"}
        body = f"{result_marker}\nsecret-looking line\n{'y' * 4096}"

        for index in range(REPEAT_CALL_BLOCK_THRESHOLD + 2):
            call_id = f"call-{index}"
            if pre_tool_call(
                tool_name="terminal",
                tool_input=args,
                session_id="session-a",
                omh_home=str(self.home),
                tool_call_id=call_id,
            ) is None:
                post_tool_call(
                    tool_name="terminal",
                    args=args,
                    result=body,
                    session_id="session-a",
                    omh_home=str(self.home),
                    tool_call_id=call_id,
                )

        # The file's bytes, not the returned object: the question is what
        # landed on disk and would survive the session that wrote it.
        written = tool_bursts_path(str(self.home)).read_bytes()
        self.assertNotIn(argument_marker.encode(), written)
        self.assertNotIn(result_marker.encode(), written)
        self.assertNotIn(b"secret-looking line", written)
        self.assertNotIn(b"/private/", written)
        # Both fingerprints are there, so this is a file that recorded the
        # call in digest form rather than a file that recorded nothing.
        self.assertIn(tool_args_digest(args).encode(), written)
        self.assertIn(tool_result_digest(body).encode(), written)

    def test_no_raw_argument_text_reaches_the_written_ledger(self):
        marker = "OMH-REPEAT-GUARD-ARGUMENT-CANARY"
        args = {"pattern": f"{marker}|{BURN_PATTERN}", "path": f"/private/{marker}/src"}

        for _ in range(REPEAT_CALL_BLOCK_THRESHOLD + 2):
            pre_tool_call(
                tool_name="search_files",
                tool_input=args,
                session_id="session-a",
                omh_home=str(self.home),
            )

        # Asserted against the file's bytes, not the returned object: the
        # question is what landed on disk.
        written = tool_bursts_path(str(self.home)).read_bytes()
        self.assertNotIn(marker.encode(), written)
        self.assertNotIn(BURN_PATTERN.encode(), written)
        self.assertNotIn(b"/private/", written)
        # And the digest is there, so this is a file that recorded the call
        # in fingerprint form rather than a file that recorded nothing.
        self.assertIn(tool_args_digest(args).encode(), written)

    def test_the_digest_is_short_one_way_and_capped_before_hashing(self):
        digest = tool_args_digest(BURN_ARGS)
        self.assertEqual(len(digest), 16)
        self.assertNotIn(BURN_PATTERN, digest)
        self.assertEqual(digest, tool_args_digest(dict(reversed(list(BURN_ARGS.items())))))
        self.assertNotEqual(digest, tool_args_digest({**BURN_ARGS, "path": "tests"}))
        # Past the cap the digest stops changing, which is the documented
        # cost of bounding the hash input.
        body = "x" * MAX_DIGEST_INPUT_BYTES
        self.assertEqual(tool_args_digest(body + "a"), tool_args_digest(body + "b"))
        # An object json cannot serialize still digests, via default=str.
        self.assertTrue(tool_args_digest({"path": Path("src")}))


class RepeatRowProjectionTest(CycleAndResultHarness):
    """What a surface is given about a repeat, and what it is not.

    #1687: the HUD could say "40 calls in flight" and not "the same call
    40 times", and those are opposite situations -- one is progress, the
    other is a loop. This is the projection the row renders from. It rides
    the poll's existing ledger read, so the cases here drive
    `tool_call_projection`, the same single-read call `read_omh_hud`
    makes, rather than a reader of its own.
    """

    def projection(self, session="session-a"):
        return tool_call_projection(str(self.home), session_id=session)["repeat"]

    def loop(self, times, *, session="session-a", args=None):
        for _ in range(times):
            self.call(args=BURN_ARGS if args is None else args, result="", session=session)

    def test_the_same_call_n_times_is_reported_as_n(self):
        self.loop(6)

        row = self.projection()

        self.assertEqual(row["status"], "observed")
        self.assertEqual(row["consecutive"], 6)
        self.assertEqual(row["ran"], 6)
        self.assertEqual(row["period"], 1)
        self.assertFalse(row["cycle"])

    def test_n_different_calls_report_nothing(self):
        """The whole point of the row, stated as its own case.

        Six calls that differ only in their arguments are six calls, and
        the activity block already counts those. A surface must have
        nothing to render here, not a count of one.
        """
        for index in range(6):
            self.call(args={**BURN_ARGS, "path": f"src/{index}"}, result="")

        self.assertEqual(self.projection(), {"status": "idle"})

    def test_a_single_call_is_not_a_repeat(self):
        # The gate's own reader reports `ran: 1` for one call, to keep its
        # numbers continuous with the message it writes. A surface must
        # not turn that into `repeat x1` on every tool call.
        self.call(args=BURN_ARGS, result="")

        self.assertEqual(self.projection(), {"status": "idle"})
        self.assertEqual(
            repeat_call_streak(
                str(self.home), session_id="session-a", escalation_allowed=True
            )["ran"],
            1,
        )

    def test_a_cycle_reports_its_length_rather_than_a_longer_streak(self):
        for _ in range(4):
            self.call(args=BURN_ARGS, result="")
            self.call(args={**BURN_ARGS, "path": "tests"}, result="")

        row = self.projection()

        self.assertEqual(row["period"], 2)
        self.assertEqual(row["laps"], 4)
        self.assertTrue(row["cycle"])
        self.assertEqual(row["consecutive"], 8)

    def test_two_sessions_in_one_omh_home_do_not_add_up(self):
        """The acceptance criterion that keeps the row honest on a gateway.

        One OMH home serves every session on the machine. Two of them
        running the same call is two loops, or two sessions doing ordinary
        work; it is never one session repeating itself sixteen times.
        """
        self.loop(6, session="session-a")
        self.loop(6, session="session-b")

        self.assertEqual(self.projection("session-a")["consecutive"], 6)
        self.assertEqual(self.projection("session-b")["consecutive"], 6)

    def test_a_reader_with_no_session_identity_reports_nothing(self):
        # Not a sum over the file: a reader that cannot say who it is
        # reading for has no repeat to report, the way it has no plan.
        self.loop(6)

        self.assertEqual(self.projection(session="")["status"], "idle")

    def test_a_truncated_ledger_degrades_to_no_row_rather_than_a_wrong_number(self):
        """A torn read must cost the row, never invent one.

        The writer replaces this file atomically, so a half-written one
        should not be observable -- but the reader runs every two seconds
        in a separate process against a file the hot path rewrites on
        every tool call, and "should not" is not a guard. Truncation is
        the shape a partial read takes, and json.loads is where it lands.
        """
        self.loop(6)
        self.assertEqual(self.projection()["consecutive"], 6)

        path = tool_bursts_path(str(self.home))
        raw = path.read_text(encoding="utf-8")
        path.write_text(raw[: len(raw) // 2], encoding="utf-8")

        self.assertEqual(self.projection(), {"status": "idle"})

    def test_the_stage_is_the_one_the_gate_recorded_for_this_lane(self):
        """Two lanes, the same counts, two stages -- the gate's own answer.

        `escalation_can_reach_a_person` reads process-global maps that the
        HUD reader's interpreter does not have: the widget spawns a fresh
        python every two seconds, where the platform map is empty and the
        predicate answers "attended" for everything. So the gate records
        its answer and the projection reads that, which is what makes
        `_repeat_stage`'s claim hold across a process boundary rather than
        only inside one.
        """
        note_session_platform("session-api", "api_server")
        self.assertFalse(escalation_can_reach_a_person("session-api"))
        for session in ("session-cli", "session-api"):
            for _ in range(REPEAT_CALL_BLOCK_THRESHOLD):
                self.assertIsNone(self.call(args=BURN_ARGS, result="", session=session))
            for _ in range(REPEAT_CALL_ESCALATION_ATTEMPTS):
                self.assertEqual(
                    self.call(args=BURN_ARGS, result="", session=session)["action"], "block"
                )

        attended = self.projection("session-cli")
        withheld = self.projection("session-api")

        self.assertEqual(attended["consecutive"], withheld["consecutive"])
        self.assertEqual(attended["stage"], "approval")
        self.assertEqual(withheld["stage"], "blocking")
        self.assertTrue(attended["escalation_recorded"])
        self.assertTrue(withheld["escalation_recorded"])

    def test_a_row_written_without_the_gates_answer_withholds_the_escalation(self):
        """The mutation guard for the threading, stated as behaviour.

        Remove `escalation_allowed=` from `pre_tool_call`'s
        `record_tool_call` and every row lands in this state. The stage
        must then stop at `blocking` -- rendering `approval` where the
        gate would block is the one disagreement this projection exists
        to prevent -- and `escalation_recorded` must say the answer is
        missing rather than leave a reader guessing which it got.
        """
        for _ in range(REPEAT_CALL_BLOCK_THRESHOLD + REPEAT_CALL_ESCALATION_ATTEMPTS):
            record_tool_call(
                "search_files",
                omh_home=str(self.home),
                args_digest=tool_args_digest(BURN_ARGS),
                session_id="session-mute",
            )
        for _ in range(REPEAT_CALL_ESCALATION_ATTEMPTS):
            record_repeat_refusal(
                tool_name="search_files",
                args_digest=tool_args_digest(BURN_ARGS),
                session_id="session-mute",
                omh_home=str(self.home),
            )

        row = self.projection("session-mute")

        self.assertGreaterEqual(row["intercepted"], REPEAT_CALL_ESCALATION_ATTEMPTS)
        self.assertEqual(row["stage"], "blocking")
        self.assertFalse(row["escalation_recorded"])
        # And the same counts WITH an answer do reach the escalation, so
        # the case above is the missing answer and not a missing count.
        self.assertEqual(
            _repeat_stage_of(self.home, "session-mute", escalation_allowed=True), "approval"
        )

    def test_the_row_carries_no_tool_name_and_no_argument_digest(self):
        """#1687's boundary: the row says a call repeated, never what it was.

        Asserted against the projection's keys rather than its values,
        because a field that is not there cannot be rendered by a surface
        that was written later. The gate's own reader keeps both, and
        does so for the message it writes.
        """
        self.loop(6)

        row = self.projection()

        self.assertNotIn("tool", row)
        self.assertNotIn("args_digest", row)
        self.assertNotIn("search_files", json.dumps(row))
        self.assertIn("tool", self._gate_streak())

    def _gate_streak(self):
        return repeat_call_streak(
            str(self.home), session_id="session-a", escalation_allowed=True
        )


def _repeat_stage_of(home, session, *, escalation_allowed):
    return repeat_call_streak(
        str(home), session_id=session, escalation_allowed=escalation_allowed
    )["stage"]


if __name__ == "__main__":
    unittest.main()

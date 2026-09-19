"""Contracts for naming the offset when a refused re-read follows a truncated read.

The measured failure (#1723): a truncated ``read_file`` returned lines 1-1666
of 9,172 and every later refusal told the model the content it already had was
still current. The fixtures here are the verbatim host shapes from the owner's
session ``20260919_140745_db409e``, read out of ``~/.hermes/state.db``, down to
the em dash the BLOCK text carries -- which is why one test asserts the output
is the input string with exactly one key spliced in, rather than a re-parse:
``ensure_ascii=False`` is part of the contract, and a re-parse would agree with
an escaped ``\\u2014``.

Both directions are pinned. Too quiet is the defect; too loud would put a
false claim about what a read covered into a result that was never truncated.

``reset_truncated_read_records`` is module-global state cleared in ``setUp``
rather than at the end of each test, because the shard planner reorders tests
run to run and a leak surfaces as a CI-only failure in whichever test ran next.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh.engagement_nudges import (
    DELEGATION_NUDGE_DIRECT_READ_THRESHOLD,
    ENGAGEMENT_NUDGE_KEY,
    reset_engagement_declines,
)
from omh.plugin_bundle.omh.hooks.nudge_budget import reset_nudge_budget
from omh.plugin_bundle.omh.hooks.result_transforms import transform_tool_result
from omh.plugin_bundle.omh.truncated_read_recovery import (
    MAX_RECORDED_PATH_CHARS,
    MAX_TRACKED_WINDOWS_PER_SESSION,
    MAX_TRACKED_READ_SESSIONS,
    TRUNCATED_READ_RECOVERY_KEY,
    annotate_truncated_read_recovery,
    reset_truncated_read_records,
    truncated_read_window,
)

PATH = "/Users/khope@sionic.ai/Desktop/khope/oh-my-hermes-worktrees/architecture-visualization/src/skills/render.py"
SESSION = "20260919_140745_db409e"

# Verbatim, minus the 100,000 characters of `content`: the non-content fields
# of the truncated read of render.py in the measured session.
TRUNCATED_READ = json.dumps(
    {
        "content": "1|\"\"\"Render a skill definition to its SKILL.md body.\n",
        "total_lines": 9172,
        "file_size": 518335,
        "truncated": True,
        "hint": (
            "Output truncated at the 100,000-char read budget after 1666 line(s) "
            "(showing lines 1-1666 of 9172). Use offset=1667 to continue."
        ),
        "is_binary": False,
        "is_image": False,
        "truncated_by": "bytes",
        "next_offset": 1667,
        "_hint": (
            "This file is large (518,335 bytes). Consider reading only the section "
            "you need with offset and limit to keep context usage efficient."
        ),
    },
    ensure_ascii=False,
)

# Verbatim from the same session. The host at that checkout wrote no
# `guardrail_refusal` key, which is why `already_read` is recognised alone.
BLOCKED_REFUSAL = json.dumps(
    {
        "error": (
            "BLOCKED: You have called read_file on this exact region 3 times and "
            "the file has NOT changed. STOP calling read_file for this path — the "
            "content from your earlier read_file result in this conversation is "
            "still current. Proceed with your task using the information you "
            "already have."
        ),
        "path": PATH,
        "already_read": 3,
    },
    ensure_ascii=False,
)

UNCHANGED_STUB = json.dumps(
    {
        "status": "unchanged",
        "message": (
            "File unchanged since last read. The content from the earlier "
            "read_file result in this conversation is still current — refer to "
            "that instead of re-reading."
        ),
        "path": PATH,
        "dedup": True,
        "content_returned": False,
    },
    ensure_ascii=False,
)

# The same BLOCK body from a host new enough to mark it
# (`agent/tool_result_classification.GUARDRAIL_REFUSAL_KEY`), with the
# `already_read` key removed so the marker is what is being recognised.
GUARDRAIL_REFUSAL = json.dumps(
    {
        "error": "BLOCKED: You have read this exact file region 4 times in a row.",
        "path": PATH,
        "guardrail_refusal": True,
    },
    ensure_ascii=False,
)

# `agent/context_compressor.py` collapses an older read to this one line.
PRUNED_PLACEHOLDER = f"[read_file] read {PATH} from line 1 (650 chars)"

# The same shape for a read that started mid-file: `read_file(path,
# offset=5000)` on render.py, cut by the same 100,000-char budget. Lines
# 1-4999 are in no result at all, which is the case a path-only record got
# wrong.
MID_FILE_TRUNCATED_READ = json.dumps(
    {
        "content": "5000|    return value\n",
        "total_lines": 9172,
        "file_size": 518335,
        "truncated": True,
        "hint": (
            "Output truncated at the 100,000-char read budget after 1600 line(s) "
            "(showing lines 5000-6599 of 9172). Use offset=6600 to continue."
        ),
        "is_binary": False,
        "is_image": False,
        "truncated_by": "bytes",
        "next_offset": 6600,
    },
    ensure_ascii=False,
)

# The continuation the model should have made: a complete read from 1667 on.
CONTINUATION_READ = json.dumps(
    {
        "content": "1667|def workflow_skill():\n",
        "total_lines": 9172,
        "file_size": 518335,
        "truncated": False,
    },
    ensure_ascii=False,
)

# A complete read of a small file: no `truncated`, no `next_offset`.
WHOLE_FILE_READ = json.dumps(
    {"content": "1|x\n", "total_lines": 1, "file_size": 2, "truncated": False},
    ensure_ascii=False,
)


def annotate(result, *, path=PATH, session=SESSION, tool="read_file", **args):
    """One call through the pass, with `path` folded into the call args."""
    call_args = {"path": path, **args} if path is not None else dict(args)
    return annotate_truncated_read_recovery(
        tool_name=tool, args=call_args, result=result, session_id=session
    )


class TruncatedReadRecoveryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        reset_truncated_read_records()
        self.addCleanup(reset_truncated_read_records)

    def assert_every_number_came_from_the_record(
        self, note: str, *, session: str = SESSION, path: str = PATH, offset: int = 1
    ) -> None:
        """Every digit in the note must appear in the recorded window.

        Derived from `truncated_read_window`, never from a literal set. The
        earlier form listed `{"1", "1666", "1667", "9172"}` by hand, and `1`
        is in that set for a reason that had nothing to do with the record --
        so it passed while the note printed a start line the record never
        held. A hand-written expectation cannot catch a fabricated number that
        happens to be the one you wrote down.
        """
        window = truncated_read_window(session, path, offset)
        self.assertIsNotNone(window)
        recorded = {str(value) for value in window}
        found = {word for word in note.replace("-", " ").replace("=", " ").split() if word.isdigit()}
        self.assertTrue(
            found <= recorded, f"numbers in the note that were never recorded: {found - recorded}"
        )


class RecoveryNoteTests(TruncatedReadRecoveryTestCase):
    def test_a_refused_reread_after_a_truncated_read_names_the_offset(self) -> None:
        self.assertIsNone(annotate(TRUNCATED_READ))
        noted = annotate(BLOCKED_REFUSAL)

        self.assertIsNotNone(noted)
        note = json.loads(str(noted))[TRUNCATED_READ_RECOVERY_KEY]
        self.assertIn("lines 1-1666 of 9172", note)
        self.assertIn("offset=1667", note)
        self.assertIn("lines past 1666 were not in that result", note)

    def test_every_other_key_survives_byte_for_byte(self) -> None:
        """The acceptance condition: one key spliced in, nothing else moved.

        Asserted on the STRING, not on a re-parse. The refusal carries an em
        dash, so a pass that dropped `ensure_ascii=False` would still re-parse
        equal while changing every byte after it.
        """
        self.assertIsNone(annotate(TRUNCATED_READ))
        noted = str(annotate(BLOCKED_REFUSAL))

        parsed = json.loads(noted)
        spliced = json.dumps(
            {TRUNCATED_READ_RECOVERY_KEY: parsed[TRUNCATED_READ_RECOVERY_KEY]},
            ensure_ascii=False,
        )
        self.assertEqual(noted, BLOCKED_REFUSAL[:-1] + ", " + spliced[1:])

        del parsed[TRUNCATED_READ_RECOVERY_KEY]
        self.assertEqual(parsed, json.loads(BLOCKED_REFUSAL))

    def test_each_of_the_three_refusal_shapes_is_recognised_by_key(self) -> None:
        for name, refusal in (
            ("already_read", BLOCKED_REFUSAL),
            ("status_unchanged", UNCHANGED_STUB),
            ("guardrail_refusal", GUARDRAIL_REFUSAL),
        ):
            with self.subTest(shape=name):
                reset_truncated_read_records()
                self.assertIsNone(annotate(TRUNCATED_READ))
                noted = annotate(refusal)
                self.assertIsNotNone(noted)
                self.assertIn(
                    TRUNCATED_READ_RECOVERY_KEY, json.loads(str(noted))
                )

    def test_the_note_repeats_for_every_refusal_not_only_the_first(self) -> None:
        """117 refusals were measured; the record is not consumed by one note."""
        self.assertIsNone(annotate(TRUNCATED_READ))
        for _ in range(5):
            self.assertIsNotNone(annotate(BLOCKED_REFUSAL))

    def test_the_note_states_only_numbers_that_were_recorded(self) -> None:
        """No guess at the wanted line: 2318 was in the search result, not here."""
        self.assertIsNone(annotate(TRUNCATED_READ))
        note = json.loads(str(annotate(BLOCKED_REFUSAL)))[TRUNCATED_READ_RECOVERY_KEY]

        self.assertNotIn("2318", note)
        self.assert_every_number_came_from_the_record(note)

    def test_the_note_is_bounded(self) -> None:
        self.assertIsNone(annotate(TRUNCATED_READ))
        note = json.loads(str(annotate(BLOCKED_REFUSAL)))[TRUNCATED_READ_RECOVERY_KEY]
        self.assertLess(len(note), 500)

    def test_the_recorded_window_is_readable(self) -> None:
        self.assertIsNone(annotate(TRUNCATED_READ))
        self.assertEqual(truncated_read_window(SESSION, PATH), (1, 1666, 9172, 1667))
        self.assertIsNone(truncated_read_window(SESSION, "/other.py"))
        self.assertIsNone(truncated_read_window("", PATH))

    def test_a_second_pass_over_its_own_output_declines(self) -> None:
        self.assertIsNone(annotate(TRUNCATED_READ))
        noted = str(annotate(BLOCKED_REFUSAL))
        self.assertIsNone(annotate(noted))


class WindowScopeTests(TruncatedReadRecoveryTestCase):
    """A truncated read describes ONE window and the note may not exceed it."""

    def test_a_mid_file_record_does_not_annotate_a_first_window_refusal(self) -> None:
        """The reviewed defect: the note claimed lines 1-6599 of a 5000-6599 read.

        A read from offset 5000 returned nothing of lines 1-4999, and the
        refusal being annotated is for the first window, which that read says
        nothing about. Recording it under the path alone printed a range no
        read had returned.
        """
        self.assertIsNone(annotate(MID_FILE_TRUNCATED_READ, offset=5000))
        self.assertIsNone(annotate(BLOCKED_REFUSAL))

    def test_a_mid_file_refusal_is_annotated_with_that_window_s_own_numbers(self) -> None:
        self.assertIsNone(annotate(MID_FILE_TRUNCATED_READ, offset=5000))
        noted = annotate(BLOCKED_REFUSAL, offset=5000)

        self.assertIsNotNone(noted)
        note = json.loads(str(noted))[TRUNCATED_READ_RECOVERY_KEY]
        self.assertIn("lines 5000-6599 of 9172", note)
        self.assertIn("offset=6600", note)
        self.assertNotIn("1-6599", note)
        self.assert_every_number_came_from_the_record(note, offset=5000)

    def test_two_windows_of_one_path_are_kept_apart(self) -> None:
        self.assertIsNone(annotate(TRUNCATED_READ))
        self.assertIsNone(annotate(MID_FILE_TRUNCATED_READ, offset=5000))

        self.assertEqual(truncated_read_window(SESSION, PATH, 1), (1, 1666, 9172, 1667))
        self.assertEqual(truncated_read_window(SESSION, PATH, 5000), (5000, 6599, 9172, 6600))
        first = json.loads(str(annotate(BLOCKED_REFUSAL)))[TRUNCATED_READ_RECOVERY_KEY]
        mid = json.loads(str(annotate(BLOCKED_REFUSAL, offset=5000)))[TRUNCATED_READ_RECOVERY_KEY]
        self.assertIn("lines 1-1666", first)
        self.assertIn("lines 5000-6599", mid)

    def test_a_window_that_ended_before_it_began_is_not_recorded(self) -> None:
        backwards = json.dumps(
            {**json.loads(MID_FILE_TRUNCATED_READ), "next_offset": 4000}, ensure_ascii=False
        )
        self.assertIsNone(annotate(backwards, offset=5000))
        self.assertIsNone(truncated_read_window(SESSION, PATH, 5000))
        self.assertIsNone(annotate(BLOCKED_REFUSAL, offset=5000))

    def test_the_note_never_claims_a_line_was_absent_from_every_result(self) -> None:
        """One window is recorded, not the union of a session's reads.

        After the first window was truncated and a later `offset=1667` read
        returned the rest, "lines 1667-9172 have not been returned in any
        result" is simply false. The note is scoped to the read it recorded,
        and this pins the removed sentence by its wording because the wording
        is what overclaimed.
        """
        self.assertIsNone(annotate(TRUNCATED_READ))
        self.assertIsNone(annotate(CONTINUATION_READ, offset=1667))
        note = json.loads(str(annotate(BLOCKED_REFUSAL)))[TRUNCATED_READ_RECOVERY_KEY]

        self.assertIn("were not in that result", note)
        self.assertNotIn("any result", note)
        self.assert_every_number_came_from_the_record(note)


class PassThroughTests(TruncatedReadRecoveryTestCase):
    def test_a_refusal_for_a_path_never_read_truncated_gets_nothing(self) -> None:
        self.assertIsNone(annotate(WHOLE_FILE_READ))
        self.assertIsNone(annotate(BLOCKED_REFUSAL))

    def test_a_refusal_for_a_different_path_gets_nothing(self) -> None:
        self.assertIsNone(annotate(TRUNCATED_READ))
        self.assertIsNone(annotate(BLOCKED_REFUSAL, path="/src/skills/catalog.py"))

    def test_a_different_session_reading_the_same_path_gets_nothing(self) -> None:
        self.assertIsNone(annotate(TRUNCATED_READ))
        self.assertIsNone(annotate(BLOCKED_REFUSAL, session="20260919_999999_other"))

    def test_a_pruned_placeholder_passes_through(self) -> None:
        self.assertIsNone(annotate(TRUNCATED_READ))
        self.assertIsNone(annotate(PRUNED_PLACEHOLDER))

    def test_a_non_json_result_passes_through(self) -> None:
        self.assertIsNone(annotate(TRUNCATED_READ))
        for junk in ("", "{not json", "Error executing tool 'read_file': boom", None, 17):
            with self.subTest(result=junk):
                self.assertIsNone(annotate(junk))

    def test_a_json_value_that_is_not_an_object_passes_through(self) -> None:
        self.assertIsNone(annotate(TRUNCATED_READ))
        self.assertIsNone(annotate("[1, 2, 3]"))
        self.assertIsNone(annotate('"just a string"'))

    def test_another_tool_is_never_touched(self) -> None:
        self.assertIsNone(annotate(TRUNCATED_READ))
        self.assertIsNone(annotate(BLOCKED_REFUSAL, tool="search_files"))
        self.assertIsNone(annotate(BLOCKED_REFUSAL, tool=None))

    def test_a_call_with_no_usable_path_is_neither_recorded_nor_noted(self) -> None:
        self.assertIsNone(annotate(TRUNCATED_READ, path=None))
        self.assertIsNone(annotate(BLOCKED_REFUSAL))
        self.assertIsNone(annotate(TRUNCATED_READ, path=""))
        self.assertIsNone(
            annotate_truncated_read_recovery(
                tool_name="read_file", args="not a dict", result=TRUNCATED_READ,
                session_id=SESSION,
            )
        )

    def test_an_unkeyed_session_shares_no_row(self) -> None:
        self.assertIsNone(annotate(TRUNCATED_READ, session=""))
        self.assertIsNone(annotate(BLOCKED_REFUSAL, session=""))
        self.assertIsNone(annotate(BLOCKED_REFUSAL, session="   "))

    def test_a_result_already_carrying_the_key_is_left_alone(self) -> None:
        self.assertIsNone(annotate(TRUNCATED_READ))
        already = json.dumps(
            {**json.loads(BLOCKED_REFUSAL), TRUNCATED_READ_RECOVERY_KEY: "x"},
            ensure_ascii=False,
        )
        self.assertIsNone(annotate(already))

    def test_a_path_past_the_byte_bound_is_refused_rather_than_truncated(self) -> None:
        """A truncated key would let two long paths collide and print wrong lines."""
        long_path = "/" + "a" * MAX_RECORDED_PATH_CHARS
        self.assertIsNone(annotate(TRUNCATED_READ, path=long_path))
        self.assertIsNone(annotate(BLOCKED_REFUSAL, path=long_path))
        self.assertIsNone(truncated_read_window(SESSION, long_path))


class IncoherentWindowTests(TruncatedReadRecoveryTestCase):
    """A window that cannot describe a real read is recorded as nothing."""

    def window(self, **fields) -> str:
        return json.dumps({**json.loads(TRUNCATED_READ), **fields}, ensure_ascii=False)

    def test_a_window_that_does_not_describe_a_read_is_not_recorded(self) -> None:
        for name, fields in (
            ("truncated_is_a_string", {"truncated": "true"}),
            ("truncated_is_null", {"truncated": None}),
            ("next_offset_is_one", {"next_offset": 1}),
            ("next_offset_is_zero", {"next_offset": 0}),
            ("next_offset_is_a_string", {"next_offset": "1667"}),
            ("next_offset_is_a_bool", {"next_offset": True}),
            ("total_lines_is_zero", {"total_lines": 0}),
            ("total_lines_is_null", {"total_lines": None}),
            ("window_runs_past_the_file", {"next_offset": 9999, "total_lines": 9172}),
        ):
            with self.subTest(case=name):
                reset_truncated_read_records()
                self.assertIsNone(annotate(self.window(**fields)))
                self.assertIsNone(truncated_read_window(SESSION, PATH))
                self.assertIsNone(annotate(BLOCKED_REFUSAL))

    def test_a_window_reaching_the_last_line_is_recorded(self) -> None:
        self.assertIsNone(annotate(self.window(next_offset=9173, total_lines=9172)))
        self.assertEqual(truncated_read_window(SESSION, PATH), (1, 9172, 9172, 9173))


class OffsetGateTests(TruncatedReadRecoveryTestCase):
    """The window a call asked for is derived the host's own way.

    ``read_file`` normalises with ``max(1, int(offset))`` and the tool's
    default on a value ``int()`` refuses
    (``tools/file_operations_common.normalize_read_pagination``), so every
    argument here READ FROM LINE 1 and keys the same window. The gate itself
    is the lookup -- a call whose window was never recorded truncated gets
    nothing, which for these fixtures means any offset but 1.
    """

    def note_for(self, **args) -> str | None:
        reset_truncated_read_records()
        self.assertIsNone(annotate(TRUNCATED_READ))
        return annotate(BLOCKED_REFUSAL, **args)

    def test_a_call_that_read_from_line_one_is_noted(self) -> None:
        for name, args in (
            ("no offset", {}),
            ("offset 1", {"offset": 1}),
            ("offset 0", {"offset": 0}),
            ("negative offset", {"offset": -5}),
            ("offset None", {"offset": None}),
            ("junk offset", {"offset": "somewhere"}),
            ("offset as the string one", {"offset": "1"}),
        ):
            with self.subTest(case=name):
                self.assertIsNotNone(self.note_for(**args))

    def test_a_call_that_asked_for_another_region_gets_nothing(self) -> None:
        for name, args in (
            ("the continuation offset", {"offset": 1667}),
            ("an uncoerced string offset", {"offset": "1667"}),
            ("offset two", {"offset": 2}),
            ("a float offset", {"offset": 2.9}),
        ):
            with self.subTest(case=name):
                self.assertIsNone(self.note_for(**args))

    def test_the_limit_argument_does_not_change_the_gate(self) -> None:
        self.assertIsNotNone(self.note_for(limit=2000))
        self.assertIsNone(self.note_for(offset=1667, limit=2000))


class BoundTests(TruncatedReadRecoveryTestCase):
    """The map is bounded in both dimensions and evicts oldest first.

    The inner bound counts WINDOWS, not paths: two windows of one file are two
    rows, because each records a different read.
    """

    def record(self, *, session: str, path: str) -> None:
        self.assertIsNone(annotate(TRUNCATED_READ, session=session, path=path))

    def test_the_per_session_window_bound_evicts_the_oldest_window(self) -> None:
        paths = [f"/src/f{i}.py" for i in range(MAX_TRACKED_WINDOWS_PER_SESSION + 1)]
        for path in paths:
            self.record(session=SESSION, path=path)

        self.assertIsNone(truncated_read_window(SESSION, paths[0]))
        self.assertIsNone(annotate(BLOCKED_REFUSAL, path=paths[0]))
        for path in paths[1:]:
            self.assertIsNotNone(truncated_read_window(SESSION, path))
            self.assertIsNotNone(annotate(BLOCKED_REFUSAL, path=path))

    def test_re_recording_a_window_refreshes_its_place_in_the_queue(self) -> None:
        paths = [f"/src/f{i}.py" for i in range(MAX_TRACKED_WINDOWS_PER_SESSION)]
        for path in paths:
            self.record(session=SESSION, path=path)
        self.record(session=SESSION, path=paths[0])
        self.record(session=SESSION, path="/src/new.py")

        self.assertIsNotNone(truncated_read_window(SESSION, paths[0]))
        self.assertIsNone(truncated_read_window(SESSION, paths[1]))

    def test_the_session_bound_evicts_the_oldest_session(self) -> None:
        sessions = [f"s{i}" for i in range(MAX_TRACKED_READ_SESSIONS + 1)]
        for session in sessions:
            self.record(session=session, path=PATH)

        self.assertIsNone(truncated_read_window(sessions[0], PATH))
        self.assertIsNone(annotate(BLOCKED_REFUSAL, session=sessions[0]))
        for session in sessions[1:]:
            self.assertIsNotNone(truncated_read_window(session, PATH))

    def test_the_whole_map_is_bounded_by_the_product_of_the_two(self) -> None:
        for s in range(MAX_TRACKED_READ_SESSIONS + 4):
            for p in range(MAX_TRACKED_WINDOWS_PER_SESSION + 4):
                self.record(session=f"s{s}", path=f"/src/f{p}.py")

        live = sum(
            1
            for s in range(MAX_TRACKED_READ_SESSIONS + 4)
            for p in range(MAX_TRACKED_WINDOWS_PER_SESSION + 4)
            if truncated_read_window(f"s{s}", f"/src/f{p}.py") is not None
        )
        self.assertEqual(live, MAX_TRACKED_READ_SESSIONS * MAX_TRACKED_WINDOWS_PER_SESSION)


class ComposedSeamTests(TruncatedReadRecoveryTestCase):
    """Through the registered seam, which is what the host calls."""

    def setUp(self) -> None:
        super().setUp()
        reset_nudge_budget()
        reset_engagement_declines()
        self.addCleanup(reset_nudge_budget)
        self.addCleanup(reset_engagement_declines)
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = str(Path(self._tmp.name) / "omh")

    def seam(self, result: str, **args):
        return transform_tool_result(
            tool_name="read_file",
            args={"path": PATH, **args},
            result=result,
            session_id=SESSION,
            omh_home=self.home,
            hermes_home=self.home,
        )

    def test_the_registered_transform_carries_the_note(self) -> None:
        self.assertIsNone(self.seam(TRUNCATED_READ))
        noted = self.seam(BLOCKED_REFUSAL)
        self.assertIsNotNone(noted)
        self.assertIn(TRUNCATED_READ_RECOVERY_KEY, json.loads(str(noted)))

    def test_an_unwatched_tool_passes_through_the_transform_untouched(self) -> None:
        self.assertIsNone(
            transform_tool_result(
                tool_name="omh_status", args={"path": PATH}, result=BLOCKED_REFUSAL,
                session_id=SESSION, omh_home=self.home, hermes_home=self.home,
            )
        )

    def test_the_engagement_nudge_and_the_note_compose_on_one_result(self) -> None:
        """Both passes watch read_file, so one refusal can carry both keys."""
        self.assertIsNone(self.seam(TRUNCATED_READ))
        # Different paths, because the delegation threshold counts DISTINCT
        # `(tool, argument digest)` pairs: one path read four times is one
        # read to it, and the final call below is on PATH again, which was
        # already counted by the first.
        for index in range(DELEGATION_NUDGE_DIRECT_READ_THRESHOLD - 1):
            _ = self.seam(WHOLE_FILE_READ, path=f"/src/other-{index}.py")

        both = self.seam(BLOCKED_REFUSAL)
        self.assertIsNotNone(both)
        parsed = json.loads(str(both))
        self.assertIn(ENGAGEMENT_NUDGE_KEY, parsed)
        self.assertIn(TRUNCATED_READ_RECOVERY_KEY, parsed)
        self.assertIn("[OMH delegation]", parsed[ENGAGEMENT_NUDGE_KEY])
        self.assertIn("offset=1667", parsed[TRUNCATED_READ_RECOVERY_KEY])
        # The nudge landed first, so the recovery pass parsed the nudged
        # object and added its key beside it rather than over it.
        self.assertEqual(
            list(parsed)[-2:], [ENGAGEMENT_NUDGE_KEY, TRUNCATED_READ_RECOVERY_KEY]
        )
        self.assertEqual(
            {k: v for k, v in parsed.items() if not k.startswith("omh_")},
            json.loads(BLOCKED_REFUSAL),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

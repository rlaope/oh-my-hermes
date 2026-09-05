"""Automatic surfacing of the running-work board in `pre_llm_call`.

Multi-session coding work in flight should be visible to Hermes without the
user asking for it. `read_running_work_board` (a standalone plugin-bundle
reader; it cannot import `omh.*`, see `status_board_reader.py`'s module
docstring) walks the same in-flight markers and dispatch summaries
`omh.coding.status_board` does, and `pre_llm_call` appends a compact block
whenever two or more units are observed running -- a count, never a keyword,
because no fixed phrasing can catch every way a user's message might arrive
while multi-session work is in flight.

Harness rule (matches `tests/test_degradation_signal.py`): both awareness
`lru_cache`s are cleared in `setUp`, and each hook-level test uses a distinct
neutral message so no test's cached match result leaks into another.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import multiprocessing
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _local_package import load_local_package
from _platform_support import requires_fcntl_locks

load_local_package()

from omh.coding.inflight import write_inflight_marker
from omh.plugin_bundle.omh import awareness as awareness_module
from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call
from omh.plugin_bundle.omh.status_board_reader import (
    DEFAULT_LIMIT,
    RUNNING_WORK_BOARD_SCHEMA_VERSION,
    last_running_work_board_fingerprint,
    read_running_work_board,
    record_running_work_board_emission,
    render_running_work_block_text,
    running_work_board_fingerprint,
)
from omh.system.paths import OmhPaths

_FANOUT_ID = "fanout-0123456789ab"


def _paths(root: Path) -> OmhPaths:
    return OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes")


def _record_core_emission_while_plugin_waits(
    home: str,
    lock_held: object,
    plugin_attempting: object,
) -> None:
    from omh.runtime import context_budget

    paths = _paths(Path(home))
    original_locked_json_update = context_budget.locked_json_update

    def coordinated_locked_json_update(path: Path, mutate_fn: object, **kwargs: object) -> dict[str, object]:
        def coordinated_mutation(current: dict[str, object]) -> dict[str, object] | None:
            lock_held.set()
            if not plugin_attempting.wait(10):
                raise AssertionError("plugin did not attempt the shared ledger lock")
            return mutate_fn(current)

        return original_locked_json_update(path, coordinated_mutation, **kwargs)

    context_budget.locked_json_update = coordinated_locked_json_update
    context_budget.record_context_emission(
        paths,
        "run-core",
        surface="runtime_show",
        byte_count=11,
        payload_fingerprint_value="core-latest",
    )


def _record_plugin_emission_after_lock_attempt(home: str, plugin_attempting: object) -> None:
    from omh.plugin_bundle.omh import status_board_reader

    original_lock = status_board_reader._context_budget_ledger_lock
    status_board_reader._CONTEXT_BUDGET_LOCK_TIMEOUT_SECONDS = 10

    @contextmanager
    def coordinated_lock(path: Path):
        plugin_attempting.set()
        with original_lock(path):
            yield

    status_board_reader._context_budget_ledger_lock = coordinated_lock
    status_board_reader.record_running_work_board_emission(
        home,
        byte_count=13,
        fingerprint="plugin-latest",
    )


def _fields(**overrides: str) -> dict[str, str]:
    fields = {
        "owner": "codex",
        "owner_host": "local",
        "model": "gpt-5.6-sol",
        "reasoning_effort": "medium",
        "run_ref": "run-core",
        "worktree": "/tmp/worktrees/core",
        "started_at": "2026-08-03T09:00:00Z",
    }
    fields.update(overrides)
    return fields


class RunningWorkBoardReaderTests(unittest.TestCase):
    def test_no_markers_report_an_empty_board(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            board = read_running_work_board(paths.omh_home)
            self.assertEqual(board["schema_version"], RUNNING_WORK_BOARD_SCHEMA_VERSION)
            self.assertEqual(board["running_count"], 0)
            self.assertEqual(board["unit_count"], 0)
            self.assertEqual(board["units"], [])
            self.assertFalse(board["truncated"])
            self.assertEqual(board["sources"]["fanout_root"], "absent")

    def test_two_running_markers_are_both_reported(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_inflight_marker(paths, _FANOUT_ID, "core", _fields())
            write_inflight_marker(paths, _FANOUT_ID, "docs", _fields(run_ref="run-docs"))
            board = read_running_work_board(paths.omh_home)
            self.assertEqual(board["running_count"], 2)
            self.assertEqual(board["unit_count"], 2)
            self.assertEqual({unit["unit_id"] for unit in board["units"]}, {"core", "docs"})
            for unit in board["units"]:
                self.assertEqual(unit["status"], "running")
                self.assertEqual(unit["model_label"], "gpt-5.6-sol medium")
            self.assertEqual(board["sources"]["fanout_root"], "present")
            # The RENDERED row pins the `runtime (model effort) — status`
            # parenthesized shape, so drift in this plugin-bundle copy of the
            # renderer fails the suite, not just the JSON fields.
            text = render_running_work_block_text(board)
            self.assertIn(f"- {_FANOUT_ID}/core: codex (gpt-5.6-sol medium) — Code · running", text)
            self.assertIn(f"- {_FANOUT_ID}/docs: codex (gpt-5.6-sol medium) — Code · running", text)
            self.assertNotIn(" — (", text)

    def test_more_units_than_the_limit_states_truncation(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            for index in range(DEFAULT_LIMIT + 3):
                write_inflight_marker(paths, _FANOUT_ID, f"unit-{index}", _fields(run_ref=f"run-{index}"))
            board = read_running_work_board(paths.omh_home)
            self.assertEqual(board["running_count"], DEFAULT_LIMIT + 3)
            self.assertEqual(board["unit_count"], DEFAULT_LIMIT + 3)
            self.assertEqual(len(board["units"]), DEFAULT_LIMIT)
            self.assertTrue(board["truncated"])
            self.assertEqual(board["omitted_count"], 3)
            text = render_running_work_block_text(board)
            self.assertIn("3 not shown because of the display limit", text)

    def test_provider_prefixed_model_id_renders_parenthesized_label_intact(self) -> None:
        # A unit routed from a local-inventory catalog carries a
        # provider-prefixed model id ("provider/model_id", see
        # `inventory_model_catalog`); the slash must not break the
        # parenthesized label in the rendered block.
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_inflight_marker(
                paths,
                _FANOUT_ID,
                "omo-core",
                _fields(owner="omo", model="openrouter/qwen-3.5-coder", reasoning_effort="high"),
            )
            board = read_running_work_board(paths.omh_home)
            self.assertEqual(board["units"][0]["model_label"], "openrouter/qwen-3.5-coder high")
            text = render_running_work_block_text(board)
            self.assertIn(f"- {_FANOUT_ID}/omo-core: omo (openrouter/qwen-3.5-coder high) — Code · running", text)
            self.assertNotIn(" — (", text)

    def test_a_malformed_marker_is_skipped_without_raising(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_inflight_marker(paths, _FANOUT_ID, "core", _fields())
            broken_path = paths.omh_home / "coding" / "fanout" / _FANOUT_ID / "inflight" / "broken.json"
            broken_path.write_text("{not json", encoding="utf-8")
            board = read_running_work_board(paths.omh_home)
            self.assertEqual(board["running_count"], 1)
            self.assertEqual(board["unit_count"], 1)
            self.assertEqual(board["sources"]["inflight_markers_unreadable"], 1)

    def test_absent_root_and_unreadable_root_are_distinguishable(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            absent_board = read_running_work_board(paths.omh_home)
            self.assertEqual(absent_board["sources"]["fanout_root"], "absent")

        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            fanout_root = paths.omh_home / "coding" / "fanout"
            fanout_root.parent.mkdir(parents=True, exist_ok=True)
            fanout_root.write_text("a file where the fanout directory belongs", encoding="utf-8")
            unreadable_board = read_running_work_board(paths.omh_home)
            self.assertEqual(unreadable_board["sources"]["fanout_root"], "unreadable")


class RunningWorkBoardSuppressionLedgerTests(unittest.TestCase):
    @requires_fcntl_locks
    def test_mixed_process_writers_preserve_every_bucket_count_and_latest_fingerprint(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = _paths(root)
            from omh.runtime.context_budget import record_context_emission

            record_context_emission(
                paths,
                "unrelated-run",
                surface="fanout_show",
                byte_count=7,
                payload_fingerprint_value="unrelated-latest",
            )
            record_running_work_board_emission(paths.omh_home, byte_count=5, fingerprint="plugin-old")

            context = multiprocessing.get_context("spawn")
            lock_held = context.Event()
            plugin_attempting = context.Event()
            core = context.Process(
                target=_record_core_emission_while_plugin_waits,
                args=(str(root), lock_held, plugin_attempting),
            )
            plugin = context.Process(
                target=_record_plugin_emission_after_lock_attempt,
                args=(str(paths.omh_home), plugin_attempting),
            )

            core.start()
            self.assertTrue(lock_held.wait(20))
            plugin.start()
            for worker in (core, plugin):
                worker.join(20)
                self.assertEqual(worker.exitcode, 0)

            ledger = json.loads((paths.runtime_dir / "context_budget.json").read_text(encoding="utf-8"))
            self.assertEqual(ledger["schema_version"], "omh_run_context_budget/v1")
            unrelated = ledger["runs"]["unrelated-run"]
            self.assertEqual(unrelated["emitted_bytes"], 7)
            self.assertEqual(unrelated["call_count"], 1)
            self.assertEqual(unrelated["surfaces"], {"fanout_show": 1})
            self.assertEqual(unrelated["payload_fingerprints"]["fanout_show"], "unrelated-latest")

            core_entry = ledger["runs"]["run-core"]
            self.assertEqual(core_entry["emitted_bytes"], 11)
            self.assertEqual(core_entry["call_count"], 1)
            self.assertEqual(core_entry["surfaces"], {"runtime_show": 1})
            self.assertEqual(core_entry["payload_fingerprints"]["runtime_show"], "core-latest")

            plugin_entry = ledger["runs"]["__pre_llm_running_work_board__"]
            self.assertEqual(plugin_entry["emitted_bytes"], 18)
            self.assertEqual(plugin_entry["call_count"], 2)
            self.assertEqual(plugin_entry["surfaces"], {"pre_llm_call_running_work_board": 2})
            self.assertEqual(
                plugin_entry["payload_fingerprints"]["pre_llm_call_running_work_board"],
                "plugin-latest",
            )
            self.assertEqual(last_running_work_board_fingerprint(paths.omh_home), "plugin-latest")

    def test_lock_contention_drops_only_the_best_effort_emission(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            record_running_work_board_emission(paths.omh_home, byte_count=5, fingerprint="plugin-old")

            with patch(
                "omh.plugin_bundle.omh.status_board_reader._context_budget_ledger_lock",
                side_effect=TimeoutError("ledger busy"),
            ):
                record_running_work_board_emission(paths.omh_home, byte_count=13, fingerprint="plugin-new")

            self.assertEqual(last_running_work_board_fingerprint(paths.omh_home), "plugin-old")

    def test_fingerprint_changes_when_the_board_changes(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_inflight_marker(paths, _FANOUT_ID, "core", _fields())
            write_inflight_marker(paths, _FANOUT_ID, "docs", _fields(run_ref="run-docs"))
            board = read_running_work_board(paths.omh_home)
            write_inflight_marker(paths, _FANOUT_ID, "tests", _fields(run_ref="run-tests"))
            grown_board = read_running_work_board(paths.omh_home)
            self.assertNotEqual(
                running_work_board_fingerprint(board),
                running_work_board_fingerprint(grown_board),
            )

    def test_a_recorded_emission_is_read_back(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_inflight_marker(paths, _FANOUT_ID, "core", _fields())
            write_inflight_marker(paths, _FANOUT_ID, "docs", _fields(run_ref="run-docs"))
            board = read_running_work_board(paths.omh_home)
            fingerprint = running_work_board_fingerprint(board)
            self.assertEqual(last_running_work_board_fingerprint(paths.omh_home), "")
            record_running_work_board_emission(paths.omh_home, byte_count=120, fingerprint=fingerprint)
            self.assertEqual(last_running_work_board_fingerprint(paths.omh_home), fingerprint)


class PreLlmCallAutoSurfaceTests(unittest.TestCase):
    """Whether `pre_llm_call` surfaces the board on its own, without a keyword match."""

    def setUp(self) -> None:
        awareness_module._awareness_context_matches_message_cached.cache_clear()
        awareness_module._awareness_route_hint_cached.cache_clear()

    def test_no_markers_produce_no_block(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            result = pre_llm_call(
                omh_home=str(paths.omh_home),
                hermes_home=str(paths.hermes_home),
                user_message="tell me a short joke about a lighthouse keeper",
                is_first_turn=False,
            )
            self.assertIsNone(result)

    def test_one_running_unit_stays_below_the_threshold(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_inflight_marker(paths, _FANOUT_ID, "core", _fields())
            result = pre_llm_call(
                omh_home=str(paths.omh_home),
                hermes_home=str(paths.hermes_home),
                user_message="tell me a short joke about a single sleepy cat",
                is_first_turn=False,
            )
            self.assertIsNone(result)

    def test_two_running_units_surface_a_block_with_both_rows(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_inflight_marker(paths, _FANOUT_ID, "core", _fields())
            write_inflight_marker(paths, _FANOUT_ID, "docs", _fields(run_ref="run-docs"))
            result = pre_llm_call(
                omh_home=str(paths.omh_home),
                hermes_home=str(paths.hermes_home),
                user_message="tell me a short joke about two racing snails",
                is_first_turn=False,
            )
            self.assertIsNotNone(result)
            context = str(result["context"])
            self.assertIn("Running coding work: 2 running of 2 observed", context)
            self.assertIn("fanout-0123456789ab/core", context)
            self.assertIn("fanout-0123456789ab/docs", context)

    def test_an_unchanged_board_is_suppressed_on_the_second_call(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = _paths(Path(tmp))
            write_inflight_marker(paths, _FANOUT_ID, "core", _fields())
            write_inflight_marker(paths, _FANOUT_ID, "docs", _fields(run_ref="run-docs"))
            call_kwargs = {
                "omh_home": str(paths.omh_home),
                "hermes_home": str(paths.hermes_home),
                "user_message": "tell me a short joke about a patient turtle",
                "is_first_turn": False,
            }

            first = pre_llm_call(**call_kwargs)
            self.assertIsNotNone(first)
            self.assertIn("Running coding work", str(first["context"]))

            second = pre_llm_call(**call_kwargs)
            self.assertIsNone(second)


if __name__ == "__main__":
    unittest.main()


class AwarenessMarkerCostTests(unittest.TestCase):
    """Every marker is a context cost paid on each message it matches.

    The running-work markers were first written as the bare verb -- `돌고 있어`
    and `what is running` -- and measured 5 false positives on 14 unrelated
    messages: `돌고 있어` is ordinary Korean for "is running" and fired on
    server, test, deploy, and cron chatter, while `what is running` fired on
    "what is running in production right now", a phrasing the ROUTER itself
    blocks. The marker was looser than the route it exists to support.
    """

    # Plausible chat that is NOT about OMH coding units.
    UNRELATED = (
        "is the server still running on port 8080",
        "my docker container is running fine",
        "what is running in production right now",
        "the tests are running slowly",
        "is the deploy still running",
        "while running the migration it crashed",
        "지금 서버 돌고 있어?",
        "테스트 돌고 있어서 기다리는 중",
        "배포 돌고있어",
        "크론 돌고 있어 아마",
        "running low on disk space",
        "i went running this morning",
    )

    RUNNING_WORK_MARKERS = (
        "what is running right now",
        "what's running",
        "whats running",
        "which units are running",
        "running work board",
        "뭐 돌고 있어",
        "뭐가 돌고 있어",
        "뭐 돌고있어",
        "뭐가 돌고있어",
    )

    def _fires_on(self, message: str, markers: tuple[str, ...]) -> bool:
        import unicodedata

        text = unicodedata.normalize("NFKC", message).casefold()
        return any(marker in text for marker in markers)

    def test_no_running_work_marker_fires_on_unrelated_prose(self) -> None:
        from omh.plugin_bundle.omh import awareness

        for message in self.UNRELATED:
            with self.subTest(message=message):
                self.assertFalse(self._fires_on(message, self.RUNNING_WORK_MARKERS))
        # And the markers are actually the ones installed.
        for marker in self.RUNNING_WORK_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, awareness._AWARENESS_MESSAGE_MARKERS)

    def test_every_marker_carries_the_interrogative_not_just_the_verb(self) -> None:
        # `돌고 있어` alone is "is running"; the question word is what makes it
        # a request about OMH units rather than a statement about a server.
        for marker in self.RUNNING_WORK_MARKERS:
            with self.subTest(marker=marker):
                if "돌고" in marker:
                    self.assertTrue(marker.startswith(("뭐 ", "뭐가 ")), marker)

    def test_the_running_work_corpus_still_arms_awareness(self) -> None:
        from omh.plugin_bundle.omh.awareness import awareness_context_matches_message

        for message in ("지금 뭐 돌고 있어", "뭐가 돌고 있어", "what is running right now", "메모리 기능 꺼줘"):
            with self.subTest(message=message):
                self.assertTrue(awareness_context_matches_message(message))

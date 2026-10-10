from __future__ import annotations

import json
import os
import re
import stat
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()
from omh.maintenance.doctor import _awareness_delivery_check
from omh.paths import resolve_paths
from omh.plugin_bundle.omh import awareness_delivery
from omh.plugin_bundle.omh.awareness_delivery import (
    AWARENESS_DELIVERY_SCHEMA_VERSION,
    _awareness_delivery_lock,
    awareness_delivery_path,
    claim_route_guidance_delivery,
    read_awareness_delivery,
    record_awareness_delivery,
)
from omh.plugin_bundle.omh import awareness as awareness_module
from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call
from omh.plugin_bundle.omh.hooks.nudge_budget import reset_nudge_budget
from omh.plugin_bundle.omh.hooks.session_hooks import subagent_start
from omh.skills.catalog_types import ULW_ENGINE_SKILL_NAMES


class AwarenessDeliveryLedgerTests(unittest.TestCase):
    """Whether OMH's awareness hook returned a payload for model input.

    `host_observation` drops a record unless the caller supplies both `host`
    and `session_id`. Hermes does pass `session_id` to `pre_llm_call`, but not
    `host`, so awareness delivery uses its own private metadata ledger rather
    than claiming a native host-observation row. Hermes also swallows hook
    exceptions with a log warning, so the ledger must remain fail-open.
    """

    def test_an_empty_ledger_reads_as_zero(self) -> None:
        with TemporaryDirectory() as tmp:
            record = read_awareness_delivery(tmp)
            self.assertEqual(record["delivery_count"], 0)
            self.assertEqual(record["route_hint_count"], 0)
            self.assertEqual(record["last_delivered_at"], "")
            self.assertFalse(record["unreadable"])

    def test_busy_lock_drops_best_effort_counter_without_waiting(self) -> None:
        with TemporaryDirectory() as tmp:
            with (
                patch(
                    "omh.plugin_bundle.omh.awareness_delivery._acquire_delivery_lock",
                    side_effect=TimeoutError("busy"),
                ) as acquire_lock,
                patch(
                    "omh.plugin_bundle.omh.awareness_delivery._write_delivery_record",
                ) as write_record,
            ):
                result = record_awareness_delivery(
                    delivered=False,
                    route_hint=False,
                    context_chars=0,
                    observed_at="2026-08-12T00:00:00Z",
                    omh_home=tmp,
                )

            self.assertIsNone(result)
            acquire_lock.assert_called_once()
            write_record.assert_not_called()

    def test_a_delivery_is_counted_with_its_size(self) -> None:
        with TemporaryDirectory() as tmp:
            record_awareness_delivery(
                delivered=True, route_hint=True, context_chars=2768,
                observed_at="2026-07-26T04:28:50Z", omh_home=tmp,
            )
            record = read_awareness_delivery(tmp)
            self.assertEqual(record["delivery_count"], 1)
            self.assertEqual(record["route_hint_count"], 1)
            self.assertEqual(record["last_context_chars"], 2768)
            self.assertEqual(record["first_delivered_at"], "2026-07-26T04:28:50Z")
            self.assertEqual(record["schema_version"], AWARENESS_DELIVERY_SCHEMA_VERSION)

    def test_a_turn_with_nothing_to_inject_is_counted_separately(self) -> None:
        """"Ran and had nothing to say" must not look like "never ran"."""
        with TemporaryDirectory() as tmp:
            record_awareness_delivery(
                delivered=False, route_hint=False, context_chars=0,
                observed_at="2026-07-26T04:27:20Z", omh_home=tmp,
            )
            record = read_awareness_delivery(tmp)
            self.assertEqual(record["suppressed_count"], 1)
            self.assertEqual(record["delivery_count"], 0)
            self.assertEqual(record["last_delivered_at"], "")
            self.assertEqual(record["first_attempted_at"], "2026-07-26T04:27:20Z")

    def test_route_hints_are_counted_only_when_present(self) -> None:
        with TemporaryDirectory() as tmp:
            for hint in (False, True, False):
                record_awareness_delivery(
                    delivered=True, route_hint=hint, context_chars=100,
                    observed_at="2026-07-26T04:30:00Z", omh_home=tmp,
                )
            record = read_awareness_delivery(tmp)
            self.assertEqual(record["delivery_count"], 3)
            self.assertEqual(record["route_hint_count"], 1)

    def test_first_delivered_at_is_kept_and_last_moves(self) -> None:
        with TemporaryDirectory() as tmp:
            record_awareness_delivery(
                delivered=True, route_hint=False, context_chars=10,
                observed_at="2026-07-26T01:00:00Z", omh_home=tmp,
            )
            record_awareness_delivery(
                delivered=True, route_hint=False, context_chars=20,
                observed_at="2026-07-26T02:00:00Z", omh_home=tmp,
            )
            record = read_awareness_delivery(tmp)
            self.assertEqual(record["first_delivered_at"], "2026-07-26T01:00:00Z")
            self.assertEqual(record["last_delivered_at"], "2026-07-26T02:00:00Z")

    def test_the_file_has_a_fixed_shape_and_cannot_grow(self) -> None:
        """Counters, not an append-only log.

        A per-turn log on the hottest path is how a journal reached ~4.7k rows
        of test noise. This runs on every LLM call, so its size must not depend
        on how many calls happened.
        """
        with TemporaryDirectory() as tmp:
            for index in range(50):
                record_awareness_delivery(
                    delivered=True, route_hint=True, context_chars=index,
                    observed_at="2026-07-26T04:30:00Z", omh_home=tmp,
                )
            size_after_50 = awareness_delivery_path(tmp).stat().st_size
            for index in range(200):
                record_awareness_delivery(
                    delivered=True, route_hint=True, context_chars=index,
                    observed_at="2026-07-26T04:31:00Z", omh_home=tmp,
                )
            size_after_250 = awareness_delivery_path(tmp).stat().st_size
            self.assertEqual(read_awareness_delivery(tmp)["delivery_count"], 250)
            self.assertLess(abs(size_after_250 - size_after_50), 40)

    def test_no_prompt_text_is_ever_stored(self) -> None:
        with TemporaryDirectory() as tmp:
            record_awareness_delivery(
                delivered=True, route_hint=True, context_chars=2768,
                observed_at="2026-07-26T04:28:50Z", omh_home=tmp,
            )
            written = awareness_delivery_path(tmp).read_text(encoding="utf-8")
            stored = json.loads(written)
            self.assertEqual(
                set(stored),
                {
                    "schema_version", "delivery_count", "route_hint_count", "suppressed_count",
                    "first_attempted_at", "first_delivered_at", "last_delivered_at", "last_context_chars",
                    "accumulated_context_chars", "session_route_fingerprints",
                },
            )
            self.assertNotIn("2768 chars of prompt", written)
            for key in ("context", "user_message", "prompt", "route_hint"):
                self.assertNotIn(key, stored, f"{key} would put model-facing text in a ledger")

    def test_zero_delivery_warns_only_after_seven_days(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record_awareness_delivery(
                delivered=False,
                route_hint=False,
                context_chars=0,
                observed_at="2026-07-01T00:00:00Z",
                omh_home=str(paths.omh_home),
            )

            fresh = _awareness_delivery_check(
                paths,
                now=datetime(2026, 7, 7, 23, 59, 59, tzinfo=UTC),
            )
            aged = _awareness_delivery_check(
                paths,
                now=datetime(2026, 7, 8, 0, 0, 0, tzinfo=UTC),
            )

            self.assertTrue(fresh.ok)
            self.assertEqual(fresh.severity, "ok")
            self.assertFalse(aged.ok)
            self.assertEqual(aged.severity, "warning")
            self.assertIn("restart hermes", aged.next_action.casefold())
            self.assertEqual(aged.remediation, aged.next_action)
            self.assertIn("for at least 7 days", aged.message)
            self.assertIn("hook payload", aged.message)
            self.assertNotIn("reached a model", aged.message)

    def test_a_delivery_or_legacy_record_never_false_ages(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            record_awareness_delivery(
                delivered=True,
                route_hint=True,
                context_chars=12,
                observed_at="2026-07-01T00:00:00Z",
                omh_home=str(paths.omh_home),
            )
            delivered = _awareness_delivery_check(
                paths,
                now=datetime(2026, 8, 1, tzinfo=UTC),
            )
            self.assertTrue(delivered.ok)
            self.assertIn("hook payload", delivered.message)
            self.assertNotIn("reached a model", delivered.message)

            awareness_delivery_path(str(paths.omh_home)).write_text(
                json.dumps(
                    {
                        "schema_version": AWARENESS_DELIVERY_SCHEMA_VERSION,
                        "delivery_count": 0,
                        "route_hint_count": 0,
                        "suppressed_count": 5,
                    }
                ),
                encoding="utf-8",
            )
            legacy = _awareness_delivery_check(
                paths,
                now=datetime(2026, 8, 1, tzinfo=UTC),
            )
            self.assertTrue(legacy.ok)
            self.assertEqual(legacy.severity, "ok")

    @unittest.skipUnless(os.name == "posix", "POSIX mode bits do not exist off POSIX")
    def test_ledger_file_and_directory_are_private(self) -> None:
        with TemporaryDirectory() as tmp:
            record_awareness_delivery(
                delivered=False,
                route_hint=False,
                context_chars=0,
                observed_at="2026-07-01T00:00:00Z",
                omh_home=tmp,
            )
            path = awareness_delivery_path(tmp)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_a_corrupt_ledger_reads_as_unreadable_rather_than_zero(self) -> None:
        """Zero deliveries and an unparseable file mean different things."""
        with TemporaryDirectory() as tmp:
            path = awareness_delivery_path(tmp)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json", encoding="utf-8")
            record = read_awareness_delivery(tmp)
            self.assertTrue(record["unreadable"])
            self.assertEqual(record["delivery_count"], 0)

    def test_semantically_corrupt_ledger_is_unreadable_and_repaired(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            path = awareness_delivery_path(str(paths.omh_home))
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": AWARENESS_DELIVERY_SCHEMA_VERSION,
                        "delivery_count": "many",
                        "route_hint_count": 0,
                        "suppressed_count": 0,
                        "first_attempted_at": [],
                        "last_context_chars": -1,
                    }
                ),
                encoding="utf-8",
            )

            self.assertTrue(read_awareness_delivery(str(paths.omh_home))["unreadable"])
            self.assertEqual(_awareness_delivery_check(paths).severity, "warning")
            repaired = record_awareness_delivery(
                delivered=True,
                route_hint=False,
                context_chars=12,
                observed_at="2026-07-01T00:00:00Z",
                omh_home=str(paths.omh_home),
            )

            self.assertIsNotNone(repaired)
            self.assertEqual(read_awareness_delivery(str(paths.omh_home))["delivery_count"], 1)

    def test_route_claim_hashes_session_identity_and_preserves_route_scope(self) -> None:
        with TemporaryDirectory() as tmp:
            session_id = "raw-session-secret"

            self.assertTrue(
                claim_route_guidance_delivery(
                    session_id=session_id,
                    route_fingerprint="route-a",
                    omh_home=tmp,
                )
            )
            self.assertFalse(
                claim_route_guidance_delivery(
                    session_id=session_id,
                    route_fingerprint="route-a",
                    omh_home=tmp,
                )
            )
            self.assertTrue(
                claim_route_guidance_delivery(
                    session_id=session_id,
                    route_fingerprint="route-b",
                    omh_home=tmp,
                )
            )
            self.assertTrue(
                claim_route_guidance_delivery(
                    session_id="other-session-secret",
                    route_fingerprint="route-a",
                    omh_home=tmp,
                )
            )
            record_awareness_delivery(
                delivered=True,
                route_hint=True,
                context_chars=10,
                observed_at="2026-08-12T00:00:00Z",
                omh_home=tmp,
                session_id="recorded-session-secret",
                route_fingerprint="route-c",
            )

            written = awareness_delivery_path(tmp).read_text(encoding="utf-8")
            fingerprints = read_awareness_delivery(tmp)["session_route_fingerprints"]
            self.assertNotIn(session_id, written)
            self.assertNotIn("other-session-secret", written)
            self.assertNotIn("recorded-session-secret", written)
            self.assertEqual(len(fingerprints), 3)
            self.assertTrue(all(key.startswith("sha256:") and len(key) == 71 for key in fingerprints))

    def test_route_claims_keep_only_64_hashed_session_identifiers(self) -> None:
        with TemporaryDirectory() as tmp:
            for index in range(65):
                self.assertTrue(
                    claim_route_guidance_delivery(
                        session_id=f"session-{index}",
                        route_fingerprint="route-a",
                        omh_home=tmp,
                    )
                )

            fingerprints = read_awareness_delivery(tmp)["session_route_fingerprints"]
            self.assertEqual(len(fingerprints), 64)
            self.assertTrue(all(key.startswith("sha256:") and len(key) == 71 for key in fingerprints))

    def test_same_session_same_route_claim_is_atomic_for_concurrent_calls(self) -> None:
        with TemporaryDirectory() as tmp:
            ready = threading.Barrier(3)
            results: list[bool] = []

            def claim() -> None:
                ready.wait(timeout=1)
                results.append(
                    claim_route_guidance_delivery(
                        session_id="shared-session",
                        route_fingerprint="shared-route",
                        omh_home=tmp,
                    )
                )

            threads = [threading.Thread(target=claim) for _ in range(2)]
            for thread in threads:
                thread.start()
            ready.wait(timeout=1)
            for thread in threads:
                thread.join(timeout=1)
                self.assertFalse(thread.is_alive())

            self.assertEqual(sorted(results), [False, True])

    def test_delivery_lock_serializes_concurrent_writers(self) -> None:
        with TemporaryDirectory() as tmp:
            path = awareness_delivery_path(tmp)
            contender_started = threading.Event()
            contender_acquired = threading.Event()

            def contend() -> None:
                contender_started.set()
                with _awareness_delivery_lock(path):
                    contender_acquired.set()

            with _awareness_delivery_lock(path):
                thread = threading.Thread(target=contend)
                thread.start()
                self.assertTrue(contender_started.wait(timeout=1))
                self.assertFalse(contender_acquired.is_set())
            self.assertTrue(contender_acquired.wait(timeout=1))
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())

    def test_a_write_failure_never_raises(self) -> None:
        """Losing a counter is fine; breaking the hook that feeds the model is not."""
        with TemporaryDirectory() as tmp:
            with patch.object(Path, "mkdir", side_effect=OSError("read-only")):
                self.assertIsNone(
                    record_awareness_delivery(
                        delivered=True, route_hint=True, context_chars=10,
                        observed_at="2026-07-26T04:30:00Z", omh_home=tmp,
                    )
                )


class WindowsRetryTests(unittest.TestCase):
    """The lock's permission calls go through the one jittered backoff.

    Windows denies chmod/touch/replace while another process transiently holds
    the file (WinError 5/32). `local_store` and `memory_store_io` retried; the
    lock every bundle store takes and the delivery ledger's replace did not.
    The ledger replace under a concurrent reader is the denial Windows
    produces; the lock's own calls are wrapped so no call on the store path is
    left unguarded (preventive, not observed on Windows).
    """

    def test_the_lock_takes_its_permission_calls_through_the_backoff(self) -> None:
        calls: list[object] = []

        def recording(operation):
            calls.append(operation)
            operation()

        with TemporaryDirectory() as tmp, patch.object(awareness_delivery, "_with_windows_retry", side_effect=recording):
            with _awareness_delivery_lock(Path(tmp) / "store" / "ledger.json"):
                pass
        # parent chmod, lock touch, lock chmod -- each a call Windows can deny.
        self.assertEqual(len(calls), 3)

    def test_the_ledger_write_takes_replace_and_chmod_through_the_backoff(self) -> None:
        calls: list[object] = []

        def recording(operation):
            calls.append(operation)
            operation()

        with TemporaryDirectory() as tmp, patch.object(awareness_delivery, "_with_windows_retry", side_effect=recording):
            path = Path(tmp) / "ledger.json"
            awareness_delivery._write_delivery_record(path, {"schema_version": "x/v1"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"schema_version": "x/v1"})
        self.assertEqual(len(calls), 2)

    def test_the_backoff_retries_permission_errors_only_on_windows(self) -> None:
        attempts = {"count": 0}

        def flaky() -> None:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise PermissionError("[WinError 32] The process cannot access the file")

        with patch.object(awareness_delivery.os, "name", "nt"), patch.object(awareness_delivery.time, "sleep") as sleep:
            awareness_delivery._with_windows_retry(flaky)
        self.assertEqual((attempts["count"], sleep.call_count), (3, 2))

        attempts["count"] = 0
        with patch.object(awareness_delivery.os, "name", "posix"), patch.object(awareness_delivery.time, "sleep") as sleep:
            with self.assertRaises(PermissionError):
                awareness_delivery._with_windows_retry(flaky)
        self.assertEqual((attempts["count"], sleep.call_count), (1, 0))

    def test_the_backoff_has_one_definition(self) -> None:
        from omh.plugin_bundle.omh import memory_store_io
        from omh.system import local_store

        self.assertIs(memory_store_io._with_windows_retry, awareness_delivery._with_windows_retry)
        self.assertIs(local_store._with_windows_retry, awareness_delivery._with_windows_retry)


class DelegatedChildRouteHintTests(unittest.TestCase):
    """A delegated child's brief is not a request to start an engine (#2049).

    Hermes builds a `delegate_task` child as an in-process agent and runs its
    loop on a worker thread of the parent process, so `subagent_start` has
    registered the child's session before the child's own `pre_llm_call`
    fires. The same brief is routed twice: once on a registered child session,
    once on a session nobody registered.
    """

    def setUp(self) -> None:
        reset_nudge_budget()
        self.addCleanup(reset_nudge_budget)

    def _context(self, brief: str, *, delegated: bool) -> str:
        with TemporaryDirectory() as omh_home, TemporaryDirectory() as hermes_home:
            if delegated:
                subagent_start(
                    parent_session_id="parent-session", child_session_id="child-session",
                    omh_home=omh_home, hermes_home=hermes_home,
                )
            result = pre_llm_call(
                user_message=brief, is_first_turn=True, session_id="child-session",
                platform="subagent", omh_home=omh_home, hermes_home=hermes_home,
            )
        assert result is not None
        return str(result["context"])

    def test_registered_child_gets_no_engine_route_hint_or_context_card(self) -> None:
        for brief in ("$ulw-work fix the build", "ultrawork this refactor until the tests pass"):
            with self.subTest(brief=brief):
                context = self._context(brief, delegated=True)
                self.assertNotIn("selected=ulw-work", context)
                self.assertNotIn("lane=coding_handoff", context)
                self.assertNotIn("next_action=prepare_parallel_delivery", context)

    def test_unregistered_session_keeps_the_engine_route_hint_and_context_card(self) -> None:
        for brief in ("$ulw-work fix the build", "ultrawork this refactor until the tests pass"):
            with self.subTest(brief=brief):
                context = self._context(brief, delegated=False)
                self.assertIn("- selected=ulw-work; lane=coding_handoff", context)
                self.assertIn("next_action=prepare_parallel_delivery", context)

    def _hinted_workflows(self, brief: str, *, delegated: bool) -> set[str]:
        names = awareness_module._canonical_workflow_by_display_name()
        return {
            names.get(display, display)
            for display in re.findall(r"^- selected=([\w-]+);", self._context(brief, delegated=delegated), re.MULTILINE)
        }

    def test_registered_child_keeps_every_hint_but_the_orchestrating_engines(self) -> None:
        # The brief draws an orchestrating-engine hint (`ultrawork`) and a
        # task-engine hint that is right for it (`research`); the child loses
        # exactly the first.
        brief = "ultrawork the upload fix and research the retry library options"
        plain = self._hinted_workflows(brief, delegated=False)
        child = self._hinted_workflows(brief, delegated=True)
        self.assertTrue({"ultrawork", "research"} <= plain, plain)
        self.assertEqual(child, plain - awareness_module._ULW_ORCHESTRATING_ENGINES)
        self.assertIn("research", child)

    def test_every_engine_is_classified_orchestrating_or_task(self) -> None:
        # A new engine fails here until someone decides whether a delegated
        # child may still be pointed at it.
        self.assertLessEqual(awareness_module._ULW_ORCHESTRATING_ENGINES, set(ULW_ENGINE_SKILL_NAMES))
        self.assertEqual(
            set(ULW_ENGINE_SKILL_NAMES) - awareness_module._ULW_ORCHESTRATING_ENGINES,
            {"context", "deep-interview", "research", "ultraperf", "ultraqa"},
        )


if __name__ == "__main__":
    unittest.main()

"""Journal appends must be mutually exclusive on Windows too.

Three append paths guarded on `if fcntl is not None:` with no Windows branch, so
on a Windows host they took no lock at all and concurrent writers could
interleave -- and unlike `local_store.file_lock`, which reports
`enforced: False`, nothing said the guarantee had lapsed. That silence is the
worse half: a lock that is not one still reads as a lock.

These tests pin both halves: the shared helper actually locks, and no module
reintroduces a bare single-backend `fcntl.flock` on an append path.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _platform_support import HAS_FCNTL, HAS_SECURE_DIR_IO

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

# `fcntl.flock` is legitimate in exactly these places:
#   local_store          - the shared two-backend implementation itself
#   awareness_delivery   - vendored into the user's Hermes install, imports
#                          nothing from omh core, so it carries its own copy
#   host_observation     - same standalone plugin boundary; protects host
#                          evidence append + state projection across processes
#   status_board_reader - same standalone plugin boundary; interoperates with
#                          core's context-budget sidecar lock
#   domain_intelligence* - fails closed off POSIX by design, so a single
#                          backend is the contract rather than a gap
#   tui/live_sessions    - the TUI session record is written on the TUI's exit
#                          path (SIGHUP, SIGTERM), which must give up after a
#                          bounded ~2 s non-blocking retry and never raise;
#                          local_store.file_lock waits 10 s and raises. It has
#                          its own msvcrt LK_NBLCK/LK_UNLCK branch for Windows
FCNTL_FLOCK_ALLOWED = {
    "src/system/local_store.py",
    "src/plugin_bundle/omh/awareness_delivery.py",
    "src/plugin_bundle/omh/host_observation.py",
    "src/plugin_bundle/omh/status_board_reader.py",
    "src/workflows/domain_intelligence_bound_store.py",
    "src/workflows/domain_intelligence_store_security.py",
    "src/tui/live_sessions.py",
}


def _code_lines(path: Path) -> list[str]:
    """Source lines with whole-line comments dropped.

    The two receipt modules mention `fcntl.flock` in prose explaining why they
    use `file_lock` instead; a text scan that counted those would flag the
    modules that got this right.
    """
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        lines.append(line)
    return lines


class SharedAppendHelperTests(unittest.TestCase):
    def test_append_reports_an_enforced_os_lock(self) -> None:
        from omh.local_store import append_jsonl_locked

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "journal.jsonl"
            lock = append_jsonl_locked(path, {"b": 2, "a": 1})

            self.assertTrue(lock["locked"])
            self.assertTrue(lock["enforced"], "every host CI runs on has fcntl or msvcrt")
            self.assertIn(lock["mechanism"], {"fcntl", "msvcrt"})

    def test_append_creates_the_parent_and_appends_rather_than_truncating(self) -> None:
        from omh.local_store import append_jsonl_locked

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "journal.jsonl"
            append_jsonl_locked(path, {"n": 1})
            append_jsonl_locked(path, {"n": 2})

            rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(rows, [{"n": 1}, {"n": 2}])

    def test_the_line_is_byte_identical_on_every_platform(self) -> None:
        # Read as bytes on purpose. Sorted keys make the JSON stable, and
        # newline="" keeps the terminator LF -- text mode would write "\r\n"
        # here on Windows and the same record would be different bytes per
        # platform, which is exactly what the repo's managed-write convention
        # exists to prevent.
        from omh.local_store import append_jsonl_locked

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.jsonl"
            append_jsonl_locked(path, {"b": 2, "a": 1})

            self.assertEqual(path.read_bytes(), b'{"a": 1, "b": 2}\n')

    def test_the_lock_sidecar_is_not_mistaken_for_journal_content(self) -> None:
        from omh.local_store import append_jsonl_locked

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.jsonl"
            append_jsonl_locked(path, {"n": 1})

            self.assertEqual(path.read_bytes().count(b"\n"), 1)
            self.assertTrue((path.parent / f".{path.name}.lock").exists())


class NoSingleBackendLockOnAppendPathsTests(unittest.TestCase):
    """Derived from source, so the bug cannot be reintroduced quietly."""

    def test_only_the_sanctioned_modules_take_fcntl_flock_directly(self) -> None:
        offenders = []
        for path in sorted(SRC_ROOT.rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel in FCNTL_FLOCK_ALLOWED:
                continue
            if any("fcntl.flock" in line for line in _code_lines(path)):
                offenders.append(rel)

        self.assertEqual(
            offenders,
            [],
            "take the lock through local_store.file_lock / append_jsonl_locked, "
            "or add the module to FCNTL_FLOCK_ALLOWED with a reason",
        )

    def test_the_three_repaired_append_paths_hold_no_fcntl_reference_at_all(self) -> None:
        for rel in ("src/workflows/memory.py", "src/workflows/observation_journal.py"):
            source = (REPO_ROOT / rel).read_text(encoding="utf-8")
            self.assertNotIn("fcntl", source, f"{rel} should route locking through local_store")

    def test_the_tui_session_record_carries_both_lock_backends(self) -> None:
        # Allowed above only because it has its own Windows branch, bounded like the POSIX one.
        source = (REPO_ROOT / "src/tui/live_sessions.py").read_text(encoding="utf-8")
        for needle in ("import msvcrt", "LK_NBLCK", "LK_UNLCK", "LOCK_NB", "LOCK_WAIT_SECONDS"):
            self.assertIn(needle, source)

    def test_the_vendored_bundle_carries_both_lock_backends(self) -> None:
        # It cannot import local_store, so it has to have its own msvcrt branch.
        source = (REPO_ROOT / "src/plugin_bundle/omh/awareness_delivery.py").read_text(encoding="utf-8")
        self.assertIn("import msvcrt", source)
        self.assertIn("LK_NBLCK", source)
        self.assertIn("LK_UNLCK", source)
        self.assertNotIn("from ..", source, "the bundle is vendored and must stay import-free of omh core")


class AwarenessDeliveryLockTests(unittest.TestCase):
    def test_the_lock_yields_a_real_mechanism_on_this_host(self) -> None:
        from omh.plugin_bundle.omh.awareness_delivery import _awareness_delivery_lock

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "awareness_delivery.json"
            with _awareness_delivery_lock(path) as mechanism:
                self.assertIn(mechanism, {"fcntl", "msvcrt"})

    def test_a_host_with_neither_backend_reports_none_rather_than_pretending(self) -> None:
        from omh.plugin_bundle.omh import awareness_delivery

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "awareness_delivery.json"
            with (
                patch.object(awareness_delivery, "fcntl", None),
                patch.object(awareness_delivery, "msvcrt", None),
            ):
                with awareness_delivery._awareness_delivery_lock(path) as mechanism:
                    # The block still runs: refusing would disable awareness
                    # recording entirely, which protects nobody.
                    self.assertEqual(mechanism, "none")

    def test_recording_still_round_trips_through_the_lock(self) -> None:
        from omh.plugin_bundle.omh.awareness_delivery import (
            read_awareness_delivery,
            record_awareness_delivery,
        )

        with TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / ".omh"
            record_awareness_delivery(
                delivered=True, route_hint=True, context_chars=12, observed_at="2026-01-01T00:00:00Z",
                omh_home=str(omh_home),
            )
            record_awareness_delivery(
                delivered=False, route_hint=False, context_chars=0, observed_at="2026-01-01T00:00:01Z",
                omh_home=str(omh_home),
            )

            current = read_awareness_delivery(str(omh_home))
            self.assertEqual(int(current["delivery_count"]), 1)
            self.assertEqual(int(current["suppressed_count"]), 1)


class DomainIntelligenceCapabilityTests(unittest.TestCase):
    """The Windows user's answer to 'why does this never engage?'"""

    def test_the_verdict_matches_what_this_host_can_actually_do(self) -> None:
        # Not pinned to "available": on Windows the honest answer is "missing",
        # and that is the whole point of the row. The expectation is derived
        # from the same primitives tests/_platform_support.py probes, so this
        # passes on both platforms for the right reason rather than by being
        # skipped on one.
        from omh.maintenance.probe import _domain_intelligence_store_capability

        capability = _domain_intelligence_store_capability()
        expected = "available" if (HAS_SECURE_DIR_IO and HAS_FCNTL) else "missing"

        self.assertEqual(capability.name, "domain_intelligence_store")
        self.assertEqual(capability.status, expected)
        if expected == "missing":
            self.assertIn("unavailable on this host", capability.message)

    def test_a_host_without_fcntl_reports_missing_and_names_the_primitive(self) -> None:
        from omh.maintenance import probe

        with patch.object(probe, "fcntl", None):
            capability = probe._domain_intelligence_store_capability()

        self.assertEqual(capability.status, "missing")
        self.assertIn("fcntl advisory locks", capability.message)
        # Routing is explicitly not implicated: the attachment degrades, the
        # route does not.
        self.assertIn("routing is unaffected", capability.message)

    def test_the_capability_is_reachable_from_the_probe_payload(self) -> None:
        from omh.paths import OmhPaths
        from omh.probe import probe_capabilities

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = probe_capabilities(OmhPaths(omh_home=root / ".omh", hermes_home=root / ".hermes"))

        names = [item["name"] for item in payload["capabilities"]]
        self.assertIn("domain_intelligence_store", names)

    def test_the_capability_status_stays_inside_the_declared_vocabulary(self) -> None:
        from omh.maintenance.probe import PROBE_STATUSES, _domain_intelligence_store_capability

        self.assertIn(_domain_intelligence_store_capability().status, PROBE_STATUSES)


class SanctionedModuleListTests(unittest.TestCase):
    def test_every_allowed_path_exists(self) -> None:
        # A stale allowlist entry would silently re-permit a module that was
        # renamed or deleted.
        for rel in sorted(FCNTL_FLOCK_ALLOWED):
            self.assertTrue((REPO_ROOT / rel).is_file(), f"{rel} is allowlisted but missing")

    def test_every_allowed_path_actually_uses_fcntl_flock(self) -> None:
        for rel in sorted(FCNTL_FLOCK_ALLOWED):
            lines = _code_lines(REPO_ROOT / rel)
            self.assertTrue(
                any("fcntl.flock" in line for line in lines),
                f"{rel} no longer needs its allowlist entry",
            )


if __name__ == "__main__":
    unittest.main()

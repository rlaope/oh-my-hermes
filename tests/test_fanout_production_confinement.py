from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.fanout_dispatch import dispatch_fanout, signal_safe_unit_runner  # noqa: E402
from omh.quality.cross_harness_adapter_backend import trusted_bwrap  # noqa: E402
from _fanout_production_confinement_fixture import (  # noqa: E402
    ProductionConfinementUnavailable,
    git,
    prepare_production_confinement_fixture,
)


def _real_confinement_available() -> bool:
    if sys.platform == "darwin":
        return Path("/usr/bin/sandbox-exec").is_file()
    if not sys.platform.startswith("linux"):
        return False
    snapshot = trusted_bwrap()
    if snapshot is None:
        return False
    completed = subprocess.run(
        (
            str(snapshot.path),
            "--unshare-user",
            "--ro-bind",
            "/",
            "/",
            "--",
            "/bin/true",
        ),
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


_REAL_CONFINEMENT_AVAILABLE = _real_confinement_available()
if os.environ.get("OMH_REQUIRE_BWRAP_E2E") == "1" and (
    not sys.platform.startswith("linux") or not _REAL_CONFINEMENT_AVAILABLE
):
    raise ProductionConfinementUnavailable(
        "the required Linux bwrap production dispatch test cannot run"
    )


class FanoutProductionConfinementTests(unittest.TestCase):
    def test_dedicated_bwrap_job_runs_the_production_dispatch_regression(self) -> None:
        workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn(
            "tests.test_fanout_production_confinement."
            "FanoutProductionConfinementTests."
            "test_dispatch_retries_pinned_shim_and_promotes_private_commit",
            workflow,
        )

    @unittest.skipUnless(
        _REAL_CONFINEMENT_AVAILABLE,
        "requires macOS sandbox-exec or a trusted, working Linux bwrap",
    )
    def test_dispatch_retries_pinned_shim_and_promotes_private_commit(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = prepare_production_confinement_fixture(root)
            delays: list[float] = []

            summary = dispatch_fanout(
                fixture.paths,
                fixture.contract,
                goal_text="confined linked-worktree commit",
                repo_root=fixture.repository,
                base_sha=fixture.base_sha,
                concurrency=1,
                runner=signal_safe_unit_runner,
                readiness=lambda _paths, profile: {"status": "ready", "profile": profile},
                env=fixture.environment,
                max_retries=1,
                rng=lambda: 0.0,
                sleep=delays.append,
            )

            unit = summary["units"][0]
            worktree = root / "repo-fanout-core"
            self.assertEqual(unit["status"], "completed", str(unit))
            self.assertTrue(unit["process_succeeded"])
            self.assertTrue(unit["filesystem_confinement"]["enforced"])
            self.assertEqual(unit["retry"]["attempts"], 2)
            self.assertEqual(delays, [1.5])
            self.assertNotEqual(git(worktree, "rev-parse", "HEAD"), fixture.base_sha)
            self.assertEqual(git(worktree, "status", "--porcelain"), "")
            self.assertFalse(fixture.hook_marker.exists())
            self.assertFalse(fixture.fsmonitor_marker.exists())
            linked_git = Path(
                (worktree / ".git").read_text(encoding="utf-8").strip().removeprefix("gitdir: ")
            )
            self.assertFalse((linked_git / "child-escape").exists())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
from pathlib import Path
import unittest

from _local_package import load_local_package
from _platform_support import requires_posix

load_local_package()
from omh.paths import default_hermes_home, default_omh_home, resolve_paths


REAL_USER_HOME = Path("~").expanduser().resolve()


def _under_real_user_home(path: Path) -> bool:
    return path.expanduser().resolve().is_relative_to(REAL_USER_HOME)


@requires_posix
class HomeIsolationTests(unittest.TestCase):
    """Guard the test process against writing into the developer's real home.

    Before this guard existed, every test that resolved paths without an
    explicit home wrote to ~/.omh and ~/.hermes. The visible damage was
    ~4.7k `plan_artifact_created` events accumulated in the real
    ~/.omh/runtime/journal/events.jsonl across a month of test runs, drowning
    the four events that came from actual use.

    `tests/_local_package.py` redirects OMH_HOME/HERMES_HOME to a per-process
    temp root at import time. These tests fail if that redirect is removed,
    bypassed, or overridden by an exported OMH_HOME.
    """

    def test_home_env_overrides_are_set_for_the_test_process(self) -> None:
        for name in ("OMH_HOME", "HERMES_HOME", "OMH_AGENT_SKILLS_HOME"):
            with self.subTest(env=name):
                value = os.environ.get(name, "")
                self.assertTrue(value, f"{name} must be set by tests/_local_package.py")
                self.assertFalse(
                    _under_real_user_home(Path(value)),
                    f"{name} points inside the real user home: {value}",
                )

    def test_default_homes_stay_out_of_the_real_user_home(self) -> None:
        for label, resolved in (("omh", default_omh_home()), ("hermes", default_hermes_home())):
            with self.subTest(home=label):
                self.assertFalse(
                    _under_real_user_home(resolved),
                    f"default {label} home resolves inside the real user home: {resolved}",
                )

    def test_resolve_paths_without_explicit_homes_stays_isolated(self) -> None:
        paths = resolve_paths()
        for label, resolved in (("omh_home", paths.omh_home), ("hermes_home", paths.hermes_home)):
            with self.subTest(path=label):
                self.assertFalse(
                    _under_real_user_home(resolved),
                    f"{label} resolves inside the real user home: {resolved}",
                )

    def test_runtime_journal_target_is_not_the_real_user_journal(self) -> None:
        journal = resolve_paths().runtime_journal_events_path
        self.assertFalse(
            _under_real_user_home(journal),
            f"test runs would append to the real journal: {journal}",
        )


if __name__ == "__main__":
    unittest.main()

"""The OMH TUI says once, at launch, that Hermes' gateway needs a restart, and why.

The lines are `gateway_notices`' (pinned in `test_hermes_gateway_health`):
read from the root home's gateway files (a shared gateway keeps them there),
and from a profile's own when the TUI runs in one. They are transcript
notices added at startup, so later frames redraw the one notice, never a new
one; nothing is said when the files show nothing.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from test_hermes_gateway_health import INSTALLED_AT, INSTALLED_EPOCH, UNIT, state_record, write_home
from test_tui_launch_card import Launched
from omh.tui.transcript import NOTICE_WARN, NoticeBlock

STORE = "cannot write its session store"
STALE = "started before OMH was updated"


def notices(run: Launched, fragment: str) -> list[NoticeBlock]:
    return [block for block in run.app.transcript.blocks if isinstance(block, NoticeBlock) and fragment in block.text]


class GatewayHealthNoticeTests(unittest.TestCase):
    def setUp(self) -> None:
        top = tempfile.mkdtemp(prefix="omh-gateway-notice-")
        self.addCleanup(shutil.rmtree, top, ignore_errors=True)
        self.root = Path(top) / ".hermes"

    def test_a_gateway_that_needs_a_restart_is_said_once_per_launch(self) -> None:
        write_home(self.root, state=state_record(self.root, "unavailable"), starts=[INSTALLED_EPOCH - 60],
                   installed_at=INSTALLED_AT)
        run = Launched(env={"HERMES_HOME": str(self.root)})
        for _frame in range(5):
            run.everything()
        store, stale = notices(run, STORE), notices(run, STALE)
        self.assertEqual((len(store), len(stale)), (1, 1))
        self.assertEqual({store[0].level, stale[0].level}, {NOTICE_WARN})
        self.assertIn("`hermes gateway restart`", store[0].text)
        run.app._render()
        shown = " ".join(" ".join(run.app.terminal.screen.history()).split())  # type: ignore[attr-defined]
        self.assertEqual(shown.count(STORE), 1)
        self.assertEqual(shown.count(STALE), 1)

    def test_a_profile_launch_reads_the_shared_gateway_in_the_root_home(self) -> None:
        write_home(self.root, state=state_record(self.root, "unavailable"))
        profile = self.root / "profiles" / "kami"
        profile.mkdir(parents=True)
        run = Launched(env={"HERMES_HOME": str(profile)})
        [notice] = notices(run, STORE)
        self.assertTrue(notice.text.startswith("Hermes' gateway cannot write"))
        self.assertIn("`hermes gateway restart`", notice.text)

    def test_a_profiles_own_gateway_names_its_profile_restart(self) -> None:
        profile = self.root / "profiles" / "kami"
        write_home(profile, state=state_record(profile, "unavailable"))
        run = Launched(env={"HERMES_HOME": str(profile)})
        [notice] = notices(run, STORE)
        self.assertIn("Hermes' gateway for profile kami", notice.text)
        self.assertIn("`hermes --profile kami gateway restart`", notice.text)

    def test_a_draining_gateway_is_said_once_instead_of_a_restart(self) -> None:
        write_home(self.root, state=state_record(self.root, "unavailable", gateway_state="draining",
                                                 restart_requested=True, active_work=[UNIT, UNIT]),
                   starts=[INSTALLED_EPOCH - 60], installed_at=INSTALLED_AT)
        run = Launched(env={"HERMES_HOME": str(self.root)})
        for _frame in range(3):
            run.everything()
        [notice] = notices(run, "Hermes' gateway")
        self.assertEqual(notice.level, NOTICE_WARN)
        self.assertIn("is restarting: it waits for 2 running turns", notice.text)
        self.assertIn("`agent.restart_after_turn_timeout`", notice.text)
        self.assertNotIn("hermes gateway restart", notice.text)

    def test_a_healthy_gateway_or_none_says_nothing(self) -> None:
        write_home(self.root, state=state_record(self.root), starts=[INSTALLED_EPOCH + 60], installed_at=INSTALLED_AT)
        for env in ({"HERMES_HOME": str(self.root)}, {"HERMES_HOME": str(self.root.parent / "absent")}, {}):
            with self.subTest(env=env):
                run = Launched(env=env)
                self.assertEqual(notices(run, "Hermes' gateway"), [])


if __name__ == "__main__":
    unittest.main()

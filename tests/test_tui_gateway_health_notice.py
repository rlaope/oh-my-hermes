"""The OMH TUI says once, at launch, what Hermes' gateway needs, and why.

The lines are `gateway_notices`' (pinned in `test_hermes_gateway_health`):
read from the root home's gateway files (a shared gateway keeps them there),
and from a profile's own when the TUI runs in one. They are transcript
notices added once by `startup()`, after a resumed session's history, so
later frames, a gateway respawn and a session switch never say them again;
nothing is said when the files show nothing.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from test_hermes_gateway_health import INSTALLED_AT, REPLACED, STARTED, UNIT, iso, missing_profile, state_record, write_home
from test_tui_launch_card import Launched, StartClient
from test_tui_respawn import ENVIRON, STORED, crash, crashing
from omh.maintenance import hermes_gateway
from omh.tui.gateway import Response
from omh.tui.transcript import NOTICE_WARN, NoticeBlock

STORE = "cannot write a session store it holds"
STALE = "started before OMH was updated"
HISTORY = [{"role": "user", "text": "the question before"}, {"role": "assistant", "text": "the answer before"}]


def notices(app, fragment: str) -> list[NoticeBlock]:
    return [block for block in app.transcript.blocks if isinstance(block, NoticeBlock) and fragment in block.text]


def state(home: Path, status: str = "ok", **overrides: object) -> dict[str, object]:
    """A record stamped now: the TUI reads the wall clock, and a long test run outlasts Hermes' 120 s bound."""
    return state_record(home, status, updated_at=iso(time.time()), **overrides)


class ResumeClient(StartClient):
    def call(self, method: str, params: dict, timeout: float = 30.0) -> dict:
        result = super().call(method, params, timeout)
        if method == "session.resume":
            result["messages"] = HISTORY
        return result


class GatewayHealthNoticeTests(unittest.TestCase):
    def setUp(self) -> None:
        top = tempfile.mkdtemp(prefix="omh-gateway-notice-")
        self.addCleanup(shutil.rmtree, top, ignore_errors=True)
        self.root = Path(top) / ".hermes"

    def failing(self, home: Path, **overrides: object) -> None:
        write_home(home, state=state(home, "unavailable", **overrides), starts=[STARTED], installed_at=INSTALLED_AT,
                   errors=[(time.time() - 5, REPLACED)])

    def test_a_gateway_that_needs_a_restart_is_said_once_per_launch(self) -> None:
        self.failing(self.root)
        run = Launched(env={"HERMES_HOME": str(self.root)})
        for _frame in range(5):
            run.everything()
        store, stale = notices(run.app, STORE), notices(run.app, STALE)
        self.assertEqual((len(store), len(stale)), (1, 1))
        self.assertEqual({store[0].level, stale[0].level}, {NOTICE_WARN})
        self.assertIn("`hermes gateway restart`", store[0].text)
        run.app._render()
        shown = " ".join(" ".join(run.app.terminal.screen.history()).split())  # type: ignore[attr-defined]
        self.assertEqual(shown.count(STORE), 1)
        self.assertEqual(shown.count(STALE), 1)

    def test_todays_deleted_profile_reference_is_named_without_a_restart(self) -> None:
        write_home(self.root, state=state(self.root, "unavailable"), starts=[STARTED],
                   errors=[(STARTED - 30, REPLACED), (time.time() - 60, missing_profile(self.root))])
        run = Launched(env={"HERMES_HOME": str(self.root)})
        [notice] = notices(run.app, "Hermes' gateway")
        self.assertIn("a deleted profile `opti-sol-base` is still referenced", notice.text)
        self.assertNotIn("hermes gateway restart", notice.text)

    def test_a_profile_launch_reads_the_shared_gateway_in_the_root_home(self) -> None:
        self.failing(self.root)
        profile = self.root / "profiles" / "kami"
        profile.mkdir(parents=True)
        run = Launched(env={"HERMES_HOME": str(profile)})
        [notice] = notices(run.app, STORE)
        self.assertTrue(notice.text.startswith("Hermes' gateway cannot write"))
        self.assertIn("`hermes gateway restart`", notice.text)

    def test_a_profiles_own_gateway_names_its_profile_restart(self) -> None:
        profile = self.root / "profiles" / "kami"
        self.failing(profile)
        run = Launched(env={"HERMES_HOME": str(profile)})
        [notice] = notices(run.app, STORE)
        self.assertIn("Hermes' gateway for profile kami", notice.text)
        self.assertIn("`hermes --profile kami gateway restart`", notice.text)

    def test_a_draining_gateway_is_said_once_instead_of_a_restart(self) -> None:
        self.failing(self.root, gateway_state="draining", restart_requested=True, active_work=[UNIT, UNIT])
        run = Launched(env={"HERMES_HOME": str(self.root)})
        for _frame in range(3):
            run.everything()
        [notice] = notices(run.app, "Hermes' gateway")
        self.assertEqual(notice.level, NOTICE_WARN)
        self.assertIn("is restarting: it waits for 2 running turns", notice.text)
        self.assertIn("`agent.restart_after_turn_timeout`", notice.text)
        self.assertNotIn("hermes gateway restart", notice.text)

    def test_a_resumed_launch_says_it_under_the_sessions_history(self) -> None:
        self.failing(self.root)
        with patch("test_tui_launch_card.StartClient", ResumeClient):
            run = Launched(env={"HERMES_HOME": str(self.root), "HERMES_TUI_RESUME": "stored-1"})
        blocks = run.app.transcript.blocks
        [notice] = notices(run.app, STORE)
        self.assertGreater(len(blocks), 2)
        history = [index for index, block in enumerate(blocks) if not isinstance(block, NoticeBlock)]
        self.assertTrue(history, "the resumed history was drawn")
        self.assertGreater(blocks.index(notice), max(history))

    def test_a_respawn_and_a_session_switch_never_say_it_again(self) -> None:
        self.failing(self.root)
        environ = {**ENVIRON, "HERMES_HOME": str(self.root), "HERMES_TUI_RESUME": STORED}
        with patch.object(hermes_gateway, "gateway_notices", wraps=hermes_gateway.gateway_notices) as read:
            app, old, spawner, _now = crashing(environ=environ)
            app.startup()
            self.assertEqual(read.call_count, 1)
            self.assertEqual(len(notices(app, STORE)), 1)
            crash(app, old)
            self.assertIs(app.client, spawner.made[0])
            app._switch_session("stored-2")
            new = spawner.made[0]
            app._on_response(Response(new.first_id + len(new.calls) - 1,
                                      {"session_id": "live-3", "stored_session_id": "stored-2", "info": {"model": "m"},
                                       "messages": []}, None))
            self.assertEqual(app.stored_id, "stored-2")
        self.assertEqual(read.call_count, 1)
        self.assertLessEqual(len(notices(app, STORE)), 1)

    def test_a_healthy_gateway_or_none_says_nothing(self) -> None:
        write_home(self.root, state=state(self.root), starts=[STARTED + 120], installed_at=INSTALLED_AT)
        for env in ({"HERMES_HOME": str(self.root)}, {"HERMES_HOME": str(self.root.parent / "absent")}, {}):
            with self.subTest(env=env):
                run = Launched(env=env)
                self.assertEqual(notices(run.app, "Hermes' gateway"), [])


if __name__ == "__main__":
    unittest.main()

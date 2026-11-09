"""The recall switches: `recall_line`, `recall_mode`, and `memory_mode=off` reaching recall.

Hermes posts ``🧠 OMH — recalled N memories`` on every surface whenever the
provider's `recall_status()` returns a value, and injects whatever
`prefetch()` returns. So the line and the memory are two switches:

- `recall_line` (`all | console | off`, default `console`) gates only
  `recall_status()`, by the `platform` Hermes passed to `initialize`. The
  prefetch text and its receipt are the same either way.
- `recall_mode` (`auto | on_demand | off`, default `auto`) gates per-turn
  recall; `off` also refuses tool recall. Saving is never touched.
- `memory_mode=off` (and a disabled retain_knowledge family) used to leave
  per-turn and tool recall running, because neither passed the policy to the
  selector (#1 in the 2026-11-03 recall audit).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.install.config_adapter import memory_provider_selection, set_plugin_setting  # noqa: E402
from omh.plugin_bundle.omh.memory_dreaming import DEFAULT_TURN_INTERVAL  # noqa: E402
from omh.plugin_bundle.omh.memory_blocks import approve_memory_block, build_memory_block, write_memory_block  # noqa: E402
from omh.plugin_bundle.omh.memory_provider import OmhMemoryProvider  # noqa: E402
from omh.plugin_bundle.omh.memory_recall_settings import (  # noqa: E402
    RECALL_SETTING_UNRECOGNIZED,
    read_recall_line_setting,
    read_recall_mode_setting,
)
from omh.plugin_bundle.omh.memory_session_lens import lens_profile_home, session_lens_path  # noqa: E402
from omh.plugin_bundle.omh.tools.memory_tool import omh_remember_handler  # noqa: E402
from test_memory_messenger import DISCORD_OWNER, SLACK_DM, SLACK_OWNER, TELEGRAM_OWNER, _Messenger  # noqa: E402
from omh.plugin_bundle.omh.memory_dreaming import DREAMING_HANDOFF_SCHEMA_VERSION, consolidation_path  # noqa: E402
from test_memory_origin import add_messages, epoch, make_state_db  # noqa: E402
from test_memory_prefetch_canonical import rendered_ids  # noqa: E402

DISCORD_CHANNEL = "1111111111111111111"
FACT = "The billing service deploys only on Tuesday mornings."
QUESTION = "when does the billing service deploy"
CONSOLE_PLATFORMS = ("cli", "tui", "desktop")
MESSENGER_PLATFORMS = ("slack", "telegram", "discord")


class _Switches(_Messenger):
    def settings(self, **values: str) -> None:
        body = "".join(f"        {key}: {value}\n" for key, value in values.items())
        (self.hermes / "config.yaml").write_text(
            "memory:\n  provider: omh\nplugins:\n  entries:\n    omh:\n      settings:\n" + body, encoding="utf-8", newline="\n"
        )

    def memory_policy(self, setup: dict) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "setup-profile.json").write_text(json.dumps(setup), encoding="utf-8", newline="\n")

    def on(self, platform: str, session_id: str) -> OmhMemoryProvider:
        """A session on `platform` whose lens admits the record `seed` saved for it."""
        if platform == "slack":
            return self.gateway(session_id, "slack", chat_type="dm", chat_id=SLACK_DM, user_id=SLACK_OWNER, thread_id="1760000000.000100")
        if platform == "telegram":
            return self.gateway(session_id, "telegram", chat_type="dm", chat_id=TELEGRAM_OWNER, user_id=TELEGRAM_OWNER)
        if platform == "discord":
            return self.gateway(session_id, "discord", chat_type="group", chat_id=DISCORD_CHANNEL, user_id=DISCORD_OWNER)
        live = OmhMemoryProvider(self.home)
        live.initialize(session_id, platform=platform, hermes_home=str(self.hermes), agent_context="primary", cwd=str(self.workspace))
        self.providers.append(live)
        return live

    def author(self, platform: str) -> str | None:
        return {"slack": SLACK_OWNER, "telegram": TELEGRAM_OWNER, "discord": DISCORD_OWNER}.get(platform)

    def seed(self) -> dict[str, str]:
        """One record each surface's lens admits: the owner's for consoles and DMs, the channel's own for Discord."""
        os.environ["SLACK_ALLOWED_USERS"] = SLACK_OWNER
        os.environ["TELEGRAM_ALLOWED_USERS"] = TELEGRAM_OWNER
        owner = self.owner_capture(FACT)
        channel = self.on("discord", "discord-seed")
        self.turn(channel, 1, "hi", author_id=DISCORD_OWNER)
        discord = str(self.capture("discord-seed", FACT)["record_id"])
        # The seeding session ends as an attended console ends one, so the next session's digest window
        # starts after these saves; without it the digest reports them whenever the clock crosses a second.
        self.console("seed-close").shutdown()
        return {**{platform: owner for platform in (*CONSOLE_PLATFORMS, "slack", "telegram")}, "discord": discord}

    def served(self, platform: str, session_id: str) -> tuple[OmhMemoryProvider, str]:
        live = self.on(platform, session_id)
        return live, self.turn(live, 1, QUESTION, author_id=self.author(platform))


class RecallLineTests(_Switches):
    def test_platform_matrix_under_each_recall_line(self) -> None:
        records = self.seed()
        expected_shown = {
            None: set(CONSOLE_PLATFORMS),  # unset: the default `console`
            "console": set(CONSOLE_PLATFORMS),
            "all": set(CONSOLE_PLATFORMS) | set(MESSENGER_PLATFORMS),
            "off": set(),
            "false": set(),  # a bare `off` that `hermes config set` stored as false
        }
        for value, shown in expected_shown.items():
            if value is None:
                (self.hermes / "config.yaml").unlink(missing_ok=True)
            else:
                self.settings(recall_line=value)
            for platform in (*CONSOLE_PLATFORMS, *MESSENGER_PLATFORMS):
                with self.subTest(recall_line=value, platform=platform):
                    live, pack = self.served(platform, f"{platform}-{value}")
                    self.assertEqual(rendered_ids(pack), [records[platform]], "the memory is served whatever the line does")
                    status = live.recall_status()
                    if platform in shown:
                        assert status is not None
                        self.assertEqual((status.provider_label, status.count), ("OMH", 1))
                    else:
                        self.assertIsNone(status)
                    receipt = live.latest_prefetch_receipt()
                    assert receipt is not None
                    self.assertEqual(receipt["selection"]["selected_record_ids"], [records[platform]], "the receipt still records the serve")

    def test_prefetch_text_is_byte_identical_under_recall_line_off(self) -> None:
        self.seed()
        # The brief has its own switch; off in both runs so only the line differs.
        self.settings(dreaming_mode="off")
        for platform in ("tui", "discord"):
            with self.subTest(platform=platform):
                live = self.on(platform, f"{platform}-same")
                author = self.author(platform)
                self.turn(live, 1, QUESTION, author_id=author)  # spends the once-per-session digest
                # A compaction before each repeat: the conversation no longer
                # holds the record, so the same question serves it again.
                live.on_session_switch(f"{platform}-same", reset=False)
                default = self.turn(live, 2, QUESTION, author_id=author)
                self.settings(dreaming_mode="off", recall_line="off")
                live.on_session_switch(f"{platform}-same", reset=False)
                silenced = self.turn(live, 3, QUESTION, author_id=author)
                self.assertIsNone(live.recall_status())
                self.settings(dreaming_mode="off")
                self.assertIn("<memory_records", default)
                self.assertEqual(silenced, default)

    def test_an_unknown_value_keeps_the_default_and_says_so(self) -> None:
        self.settings(recall_line="discord_only", recall_mode="sometimes")
        line, mode = read_recall_line_setting(self.hermes), read_recall_mode_setting(self.hermes)
        self.assertEqual((line["value"], line["recognized"], line["issue"], line["reason"], line["raw"]),
                         ("console", False, RECALL_SETTING_UNRECOGNIZED, "unknown_value", "discord_only"))
        self.assertEqual((mode["value"], mode["recognized"], mode["raw"]), ("auto", False, "sometimes"))
        self.assertEqual(read_recall_line_setting(self.hermes / "absent"), {"value": "console", "raw": None, "recognized": True})


class RecallModeTests(_Switches):
    def remember(self, session_id: str, **args: object) -> dict:
        return json.loads(omh_remember_handler(args, session_id=session_id, cwd=str(self.workspace)))

    def test_auto_is_todays_per_turn_recall(self) -> None:
        records = self.seed()
        self.settings(recall_mode="auto")
        live, pack = self.served("tui", "tui-auto")
        self.assertEqual(rendered_ids(pack), [records["tui"]])
        self.assertEqual(live.recall_status().count, 1)

    def test_on_demand_serves_nothing_per_turn_but_tool_recall_and_saving_work(self) -> None:
        records = self.seed()
        write_memory_block(self.home, approve_memory_block(build_memory_block("operator", "The operator's always-on note.")))
        self.settings(recall_mode="on_demand")
        for platform in ("tui", "discord"):
            with self.subTest(platform=platform):
                live, pack = self.served(platform, f"{platform}-on-demand")
                self.assertEqual(rendered_ids(pack), [])
                for marker in ("<memory_records", "<memory_blocks", "<memory_block_index", "always-on note"):
                    self.assertNotIn(marker, pack)
                self.assertIsNone(live.recall_status())
                receipt = live.latest_prefetch_receipt()
                assert receipt is not None
                self.assertFalse(receipt["selection"]["recall_enabled"])
                recalled = self.remember(f"{platform}-on-demand", action="recall", query="billing service deploy")
                self.assertEqual(recalled["status"], "found", recalled)
                self.assertEqual([row["record_id"] for row in recalled["records"]], [records[platform]])
        saved = self.remember("tui-on-demand", action="save", summary="The owner reviews invoices on Fridays.")
        self.assertEqual(saved["status"], "remembered", saved)

    def test_off_also_refuses_tool_recall_and_still_saves(self) -> None:
        self.seed()
        self.settings(recall_mode="off")
        live, pack = self.served("tui", "tui-off")
        self.assertEqual(rendered_ids(pack), [])
        self.assertIsNone(live.recall_status())
        recalled = self.remember("tui-off", action="recall", query="billing service deploy")
        self.assertEqual((recalled["status"], recalled["reason"]), ("refused", "recall_disabled"), recalled)
        self.assertNotIn("Tuesday", json.dumps(recalled))
        saved = self.remember("tui-off", action="save", summary="The owner reviews invoices on Fridays.")
        self.assertEqual(saved["status"], "remembered", saved)

    def test_the_save_reminder_points_at_recall_only_where_recall_answers(self) -> None:
        for mode, mentions_recall in (("auto", True), ("on_demand", True), ("off", False)):
            with self.subTest(recall_mode=mode):
                self.settings(recall_mode=mode)
                block = self.on("tui", f"tui-prompt-{mode}").system_prompt_block()
                self.assertIn("call omh_remember save", block, "saving is still asked for")
                self.assertEqual("Use recall later." in block, mentions_recall)
        (self.hermes / "config.yaml").unlink()
        self.assertTrue(self.on("tui", "tui-prompt-default").system_prompt_block().endswith(" Use recall later."), "the default is unchanged")

    def test_recall_mode_does_not_touch_the_consolidation_brief_setting(self) -> None:
        self.settings(recall_mode="off")
        self.assertEqual(read_recall_mode_setting(self.hermes)["value"], "off")
        from omh.plugin_bundle.omh.memory_dreaming import configured_dreaming_mode

        self.assertEqual(configured_dreaming_mode(self.hermes), "reminder")


class ToolRecallProfileHomeTests(_Switches):
    """Tool recall reads `recall_mode` where the provider does: the profile home it was given.

    Before, the tool read the process's `HERMES_HOME`, so a provider bound to
    one profile and a tool reading another disagreed about whether recall was
    off (rev-2534).
    """

    def recall(self, session_id: str) -> dict:
        return json.loads(omh_remember_handler({"action": "recall", "query": "billing service deploy"}, session_id=session_id, cwd=str(self.workspace)))

    def test_tool_recall_follows_the_providers_profile_not_the_process_home(self) -> None:
        records = self.seed()
        launch = self.hermes.parent / "launch-home"
        launch.mkdir()
        for profile_mode, launch_mode in (("off", "auto"), ("auto", "off")):
            with self.subTest(profile=profile_mode, launch=launch_mode):
                self.settings(recall_mode=profile_mode)
                (launch / "config.yaml").write_text(
                    f"plugins:\n  entries:\n    omh:\n      settings:\n        recall_mode: {launch_mode}\n", encoding="utf-8", newline="\n"
                )
                session_id = f"tui-profile-{profile_mode}"
                with patch.dict(os.environ, {"HERMES_HOME": str(launch)}):
                    self.on("tui", session_id)
                    recalled = self.recall(session_id)
                if profile_mode == "off":
                    self.assertEqual((recalled["status"], recalled["reason"]), ("refused", "recall_disabled"), recalled)
                else:
                    self.assertEqual(recalled["status"], "found", recalled)
                    self.assertEqual([row["record_id"] for row in recalled["records"]], [records["tui"]])

    def launch_home(self) -> Path:
        launch = self.hermes.parent / "launch-home"
        launch.mkdir()
        return launch

    def test_demote_reads_the_providers_profile_not_the_process_home(self) -> None:
        # Mutant: `_demote_entry(..., Path(HERMES_HOME))` finds nothing in the launch home.
        entry = "The operator deploys from the release branch every Friday afternoon, never from main."
        (self.hermes / "memories" / "MEMORY.md").write_text(entry, encoding="utf-8", newline="\n")
        launch = self.launch_home()
        with patch.dict(os.environ, {"HERMES_HOME": str(launch)}):
            self.on("tui", "tui-demote-profile")
            demoted = self.tool("demote", "tui-demote-profile", entry_sha256=hashlib.sha256(entry.encode("utf-8")).hexdigest()[:12])
        self.assertEqual(demoted["status"], "demoted", demoted)
        self.assertNotEqual(demoted.get("reason"), "entry_not_found")

    def test_recall_origins_come_from_the_providers_profile_state_db(self) -> None:
        # Mutant: `_attach_origins` back to the process home looks in the launch home's (absent) state.db.
        launch = self.launch_home()
        with patch.dict(os.environ, {"HERMES_HOME": str(launch)}):
            self.on("tui", "tui-origin-profile")
            saved = self.capture("tui-origin-profile", FACT)
            record = json.loads((self.home / "memory" / "records" / f"{saved['record_id']}.json").read_text(encoding="utf-8"))
            self.assertEqual(record["source_ref"], "hermes-session:tui-origin-profile")
            db = self.hermes / "state.db"
            make_state_db(db)
            at = epoch(record["created_at"])
            [before] = add_messages(db, "tui-origin-profile", [("user", at - 0.5)])
            recalled = self.recall("tui-origin-profile")
        self.assertEqual(recalled["status"], "found", recalled)
        self.assertEqual(recalled["records"][0]["origin"], {"session_id": "tui-origin-profile", "around_message_id": before})

    def test_the_consolidation_status_is_the_providers_profiles_not_the_process_homes(self) -> None:
        brief = {
            "schema_version": DREAMING_HANDOFF_SCHEMA_VERSION, "due": True, "trigger": "turn",
            "raised_at": "2026-10-14T00:00:00Z", "reasons": ["profile_brief"], "requested_of_executor": [],
        }
        path = consolidation_path(self.home, self.hermes)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(brief), encoding="utf-8", newline="\n")
        launch = self.launch_home()
        with patch.dict(os.environ, {"HERMES_HOME": str(launch)}):
            self.on("tui", "tui-consolidation-profile")
            status = self.tool("consolidation", "tui-consolidation-profile")
            # No lens: the process home. It holds no brief yet, then one of its own.
            self.assertNotIn("reasons", self.tool("consolidation", "no-such-session"))
            own = consolidation_path(self.home, launch)
            own.parent.mkdir(parents=True, exist_ok=True)
            own.write_text(json.dumps({**brief, "reasons": ["process_brief"]}), encoding="utf-8", newline="\n")
            self.assertEqual(self.tool("consolidation", "no-such-session")["reasons"], ["process_brief"])
            self.assertEqual(self.tool("consolidation", "tui-consolidation-profile")["reasons"], ["profile_brief"])
        self.assertEqual(status["reasons"], ["profile_brief"], status)

    def test_a_profile_home_that_is_not_an_absolute_path_is_not_read(self) -> None:
        self.assertEqual(lens_profile_home({"profile_home": str(self.hermes)}), self.hermes)
        for written in ("relative/hermes-home", "", None, 7, f"{self.hermes}\x00x"):
            with self.subTest(profile_home=written):
                self.assertIsNone(lens_profile_home({"profile_home": written}))
        self.assertIsNone(lens_profile_home({}))

    def test_a_lens_that_names_no_profile_home_keeps_the_process_home(self) -> None:
        self.seed()
        self.on("tui", "tui-old-lens")
        path = session_lens_path(self.home, "tui-old-lens")
        lens = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(lens["profile_home"], str(self.hermes))
        del lens["profile_home"]  # as a provider before this field wrote it
        path.write_text(json.dumps(lens), encoding="utf-8", newline="\n")
        self.settings(recall_mode="off")
        self.assertEqual(self.recall("tui-old-lens")["reason"], "recall_disabled", "HERMES_HOME is this profile in the harness")


class CaptureHintRecallSettingTests(_Switches):
    """A capture hint says a record "recalls" only where a turn is served records unasked (rev-2531)."""

    OLD, NEW = "The staging database runs postgres 16", "The staging database runs postgres 17"

    def hinted(self, session_id: str) -> tuple[str, dict]:
        self.on("tui", session_id)
        held = str(self.capture(session_id, self.OLD)["record_id"])
        result = self.capture(session_id, self.NEW)
        self.assertEqual(result["similar_record_id"], held, result)
        return held, result

    def test_under_auto_the_hint_names_what_recalls(self) -> None:
        held, result = self.hinted("tui-hint-auto")
        self.assertEqual(sorted(result["recalls_now"]), sorted([held, result["record_id"]]))
        self.assertIn(f"{result['record_id']} recalls, {held} recalls.", result["next_action"])

    def test_with_per_turn_recall_off_nothing_is_said_to_recall(self) -> None:
        # The last case puts the process's Hermes home on a profile at `auto`
        # while the provider's profile says `on_demand`: the hint must read
        # the provider's, as tool recall does (`ToolRecallProfileHomeTests`).
        launch = self.hermes.parent / "launch-home"
        launch.mkdir()
        (launch / "config.yaml").write_text(
            "plugins:\n  entries:\n    omh:\n      settings:\n        recall_mode: auto\n", encoding="utf-8", newline="\n"
        )
        for mode, process_home in (("on_demand", self.hermes), ("off", self.hermes), ("on_demand", launch)):
            with self.subTest(recall_mode=mode, process_home=process_home.name):
                self.settings(recall_mode=mode)
                try:
                    with patch.dict(os.environ, {"HERMES_HOME": str(process_home)}):
                        held, result = self.hinted(f"tui-hint-{mode}-{process_home.name}")
                    self.assertEqual(result["recalls_now"], [])
                    self.assertIn("per-turn recall is off for this profile, so neither recalls.", result["next_action"])
                    self.assertNotIn(f"{held} recalls", result["next_action"])
                    self.assertIn(f"record_id='{held}'", result["next_action"], "the correct instruction is unchanged")
                finally:
                    # Each case starts from an empty store, so one failure cannot hint at the next case's records.
                    for path in (self.home / "memory" / "records").glob("*.json"):
                        path.unlink()

    def test_correcting_to_the_held_record_still_works_under_on_demand(self) -> None:
        # The hint's wording follows the setting; whether the held record can
        # stand in for the corrected one does not (`_held_replacement_refusal`).
        self.settings(recall_mode="on_demand")
        held, result = self.hinted("tui-hint-correct")
        corrected = self.tool("correct", "tui-hint-correct", record_id=held, summary=self.NEW)
        self.assertEqual((corrected["status"], corrected["replacement"]), ("corrected", "already_held"), corrected)


class MemoryModeOffTests(_Switches):
    """Audit #1: on main both setups below still served the record and posted the line."""

    def assert_recall_stopped(self, setup: dict, session_id: str) -> None:
        records = self.seed()
        self.memory_policy(setup)
        live, pack = self.served("tui", session_id)
        self.assertNotIn(records["tui"], pack)
        self.assertEqual(rendered_ids(pack), [])
        self.assertIsNone(live.recall_status())
        receipt = live.latest_prefetch_receipt()
        assert receipt is not None
        self.assertEqual(receipt["selection"]["selected_record_ids"], [])
        recalled = json.loads(omh_remember_handler({"action": "recall", "query": "billing service deploy"}, session_id=session_id, cwd=str(self.workspace)))
        self.assertEqual((recalled["status"], recalled["reason"]), ("refused", "recall_disabled"), recalled)

    def test_memory_mode_off_serves_nothing(self) -> None:
        self.assert_recall_stopped({"memory_policy": {"mode": "off", "mode_source": "explicit"}}, "tui-mode-off")

    def test_a_disabled_retain_knowledge_family_serves_nothing(self) -> None:
        self.assert_recall_stopped({"capability_policy": {"disabled_families": ["retain_knowledge"]}}, "tui-family-off")

    def test_an_unreadable_setup_profile_fails_closed_and_is_reported(self) -> None:
        self.seed()
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "setup-profile.json").write_text("[]", encoding="utf-8", newline="\n")
        live, pack = self.served("tui", "tui-broken")
        self.assertEqual(rendered_ids(pack), [])
        receipt = live.latest_prefetch_receipt()
        assert receipt is not None
        self.assertIn("setup-profile.json", receipt["store"]["unreadable"], "a read fault, named as the file that could not be read")
        self.assertEqual(receipt["write_failures_count"], 0, "not a write failure")
        self.assertEqual(live.system_prompt_block(), "")
        recalled = json.loads(omh_remember_handler({"action": "recall", "query": "billing service deploy"}, session_id="tui-broken", cwd=str(self.workspace)))
        self.assertEqual((recalled["status"], recalled["reason"]), ("error", "memory_policy_unreadable"), recalled)
        self.assertIn("nothing was searched", recalled["next_action"])
        self.assertNotIn("update failed", recalled["next_action"])

    def raise_brief(self) -> None:
        """A console session that ends with a turn interval's worth of unconsolidated turns leaves a brief for the next one."""
        earlier = self.on("tui", "tui-earlier")
        for number in range(1, DEFAULT_TURN_INTERVAL + 1):
            self.turn(earlier, number, "hello")
        earlier.shutdown()

    def test_under_memory_mode_off_no_capture_prompt_is_served(self) -> None:
        self.raise_brief()
        control = self.on("tui", "tui-control")
        self.assertIn("<memory_consolidation", self.turn(control, 1, "hello"), "the brief is pending")
        self.assertIn("call omh_remember save", control.system_prompt_block())
        self.memory_policy({"memory_policy": {"mode": "off", "mode_source": "explicit"}})
        live = self.on("tui", "tui-capture-off")
        pack = self.turn(live, 1, "hello")
        self.assertNotIn("<memory_consolidation", pack)
        self.assertEqual(live.system_prompt_block(), "")

    def test_auto_safe_default_still_recalls(self) -> None:
        records = self.seed()
        self.memory_policy({"memory_policy": {"mode": "auto-safe", "mode_source": "explicit"}})
        live, pack = self.served("tui", "tui-auto-safe")
        self.assertEqual(rendered_ids(pack), [records["tui"]])
        self.assertEqual(live.recall_status().count, 1)


class RecallSettingCliTests(_Switches):
    def cli(self, *args: str) -> tuple[int, dict]:
        status, stdout, stderr = run_cli(["--omh-home", str(self.home), "--hermes-home", str(self.hermes), "memory", *args])
        self.assertEqual(stderr, "")
        return status, json.loads(stdout)

    def test_set_and_show_write_only_the_plugin_setting(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        before = "model: x\nmemory:\n  provider: omh\n"
        (self.hermes / "config.yaml").write_text(before, encoding="utf-8", newline="\n")
        status, shown = self.cli("recall-line")
        self.assertEqual((status, shown["value"], shown["changed"], shown["refused"]), (0, "console", False, False))
        status, changed = self.cli("recall-line", "off")
        self.assertEqual((status, changed["value"], changed["changed"], changed["refused"]), (0, "off", True, False))
        status, mode = self.cli("recall-mode", "on_demand")
        self.assertEqual((status, mode["value"], mode["changed"]), (0, "on_demand", True))
        text = (self.hermes / "config.yaml").read_text(encoding="utf-8")
        self.assertTrue(text.startswith(before), text)
        self.assertEqual(memory_provider_selection(text), "omh", "the memory.provider slot is untouched")
        status, again = self.cli("recall-line", "off")
        self.assertEqual((status, again["changed"], again["refused"]), (0, False, False))
        status, back = self.cli("recall-line", "all")
        self.assertEqual((status, back["value"]), (0, "all"))
        self.assertEqual(read_recall_line_setting(self.hermes)["value"], "all")
        status, report = self.cli("status")
        self.assertEqual(status, 0)
        self.assertEqual(report["recall_settings"]["recall_line"]["value"], "all")
        self.assertEqual(report["recall_settings"]["recall_mode"]["value"], "on_demand")

    def test_dry_run_writes_nothing(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        status, payload = self.cli("recall-mode", "off", "--dry-run")
        self.assertEqual((status, payload["value"], payload["changed"], payload["refused"]), (0, "auto", True, False))
        self.assertFalse((self.hermes / "config.yaml").exists())

    def test_a_refused_write_exits_nonzero_and_changes_nothing(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        before = "plugins:\n  entries: {omh: {settings: {}}}\n"
        (self.hermes / "config.yaml").write_text(before, encoding="utf-8", newline="\n")
        status, payload = self.cli("recall-line", "off")
        self.assertEqual((status, payload["refused"], payload["changed"]), (1, True, False))
        self.assertEqual((self.hermes / "config.yaml").read_text(encoding="utf-8"), before)

    def test_an_invalid_value_is_rejected_by_the_parser(self) -> None:
        with self.assertRaises(SystemExit) as raised:
            run_cli(["--omh-home", str(self.home), "--hermes-home", str(self.hermes), "memory", "recall-line", "discord"])
        self.assertEqual(raised.exception.code, 2)
        self.assertFalse((self.hermes / "config.yaml").exists())


class SetPluginSettingTests(_Switches):
    def test_replaces_an_existing_leaf_in_place(self) -> None:
        text = "plugins:\n  entries:\n    omh:\n      settings:\n        omh_home: '/x'\n        recall_line: all\n        dreaming_mode: off\n"
        change = set_plugin_setting(text, "recall_line", "off")
        self.assertTrue(change.changed)
        self.assertEqual(change.text, text.replace("recall_line: all", "recall_line: 'off'"))

    def test_keeps_a_trailing_comment_on_the_rewritten_leaf(self) -> None:
        for written, kept in (
            ("recall_line: all  # chosen 2026-11", "recall_line: 'off'  # chosen 2026-11"),
            ("recall_line: 'all' # quoted", "recall_line: 'off' # quoted"),
            ("recall_line: all", "recall_line: 'off'"),
        ):
            with self.subTest(written=written):
                text = f"plugins:\n  entries:\n    omh:\n      settings:\n        {written}\n"
                change = set_plugin_setting(text, "recall_line", "off")
                self.assertTrue(change.changed, change.message)
                self.assertEqual(change.text, f"plugins:\n  entries:\n    omh:\n      settings:\n        {kept}\n")

    def test_adds_a_missing_leaf_beside_existing_settings(self) -> None:
        text = "plugins:\n  entries:\n    omh:\n      settings:\n        omh_home: '/x'\n"
        change = set_plugin_setting(text, "recall_mode", "on_demand")
        self.assertEqual(change.text, text + "        recall_mode: 'on_demand'\n")


class IndexOnlyPackTests(_Switches):
    """Records that match nothing are withheld and named nowhere in the pack; the switches cover it too."""

    UNRELATED = "what is the weather like"

    def indexed(self, platform: str, session_id: str) -> tuple[OmhMemoryProvider, str]:
        live = self.on(platform, session_id)
        return live, self.turn(live, 1, self.UNRELATED, author_id=self.author(platform))

    def test_auto_serves_nothing_and_posts_no_line_whatever_recall_line_says(self) -> None:
        self.seed()
        for value in (None, "all", "off"):
            if value is None:
                (self.hermes / "config.yaml").unlink(missing_ok=True)
            else:
                self.settings(recall_line=value)
            for platform in ("tui", "discord"):
                with self.subTest(recall_line=value, platform=platform):
                    live, pack = self.indexed(platform, f"{platform}-index-{value}")
                    self.assertEqual(pack, "", "an unmatched turn gets no memory block at all")
                    self.assertIsNone(live.recall_status())

    def asked(self, platform: str, session_id: str) -> tuple[OmhMemoryProvider, str]:
        live = self.on(platform, session_id)
        return live, self.turn(live, 1, QUESTION, author_id=self.author(platform))

    def test_recall_mode_on_demand_and_off_serve_no_record_to_a_matching_turn(self) -> None:
        self.seed()
        for mode in ("auto", "on_demand", "off"):
            self.settings(recall_mode=mode)
            for platform in ("tui", "discord"):
                with self.subTest(recall_mode=mode, platform=platform):
                    live, pack = self.asked(platform, f"{platform}-asked-{mode}")
                    if mode == "auto":
                        # The control: the same turn is served the record.
                        self.assertIn(FACT, pack)
                        if platform == "tui":
                            self.assertIsNotNone(live.recall_status())
                        continue
                    self.assertNotIn("<memory_records", pack)
                    self.assertNotIn(FACT, pack)
                    self.assertIsNone(live.recall_status())

    def test_memory_mode_off_serves_no_record_to_a_matching_turn(self) -> None:
        self.seed()
        for platform in ("tui", "discord"):
            with self.subTest(platform=platform, memory_mode="default"):
                self.assertIn(FACT, self.asked(platform, f"{platform}-asked-mode-default")[1])
        self.memory_policy({"memory_policy": {"mode": "off", "mode_source": "explicit"}})
        for platform in ("tui", "discord"):
            with self.subTest(platform=platform, memory_mode="off"):
                live, pack = self.asked(platform, f"{platform}-asked-mode-off")
                self.assertNotIn(FACT, pack)
                self.assertIsNone(live.recall_status())


class RecallSettingAdvisoryTests(_Switches):
    def test_doctor_names_a_value_that_is_not_read(self) -> None:
        from omh.maintenance.advisory import check_recall_settings

        self.assertEqual(check_recall_settings(self.hermes).status, "unobserved", "no config.yaml at all")
        for settings, status, said in (
            ({}, "ok", "recall_line: unset, console is in force; recall_mode: unset, auto is in force"),
            ({"recall_line": "off", "recall_mode": "on_demand"}, "ok", "recall_line: off, off is in force"),
            ({"recall_line": "discord"}, "advice", "recall_line is 'discord', which is not all, console, off; console is in force"),
            ({"recall_mode": "never"}, "advice", "recall_mode is 'never', which is not auto, on_demand, off; auto is in force"),
        ):
            with self.subTest(settings=settings):
                self.settings(**settings)
                entry = check_recall_settings(self.hermes)
                self.assertEqual((entry.check_id, entry.status), ("recall_setting_unrecognized", status))
                self.assertIn(said, entry.observed)


if __name__ == "__main__":
    import unittest

    unittest.main()

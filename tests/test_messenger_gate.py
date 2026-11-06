"""The messenger chat gate: quiet/mute per thread and skipping messages meant for someone else."""

from __future__ import annotations

import asyncio
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path
from types import SimpleNamespace

from omh.plugin_bundle.omh import messenger_gate as gate
from omh.plugin_bundle.omh.hooks import gateway_hooks
from omh.plugin_bundle.omh.messenger_gate import Message, decide

BOT = "UBOT"
OTHER = "UOTHER"


def msg(text: str, **fields) -> Message:
    fields.setdefault("self_ids", frozenset({BOT}))
    fields.setdefault("self_names", ("루미", "lumi"))
    fields.setdefault("other_names", ("민수", "alex", "田中", "小明"))
    fields.setdefault("raw_text", text)
    return Message(text=text, **fields)


def action(text: str, *, muted: bool = False, mode: str = "on", **fields) -> str:
    return decide(msg(text, **fields), muted=muted, mode=mode).action


class QuietWordTests(unittest.TestCase):
    def test_whole_message_quiet_words_mute_in_a_thread(self) -> None:
        for text in (
            "조용히 해", "조용히해!!", "닥쳐", "그만 끼어들어", "shut up", "Be quiet.", "SHUT UP 🙄",
            "黙って", "静かにして。", "闭嘴", "別說了", "cállate", "tais-toi", "Halt den Mund", "sei still",
            "cala a boca", "замолчи", "im đi", "　黙って　",
        ):
            with self.subTest(text=text):
                self.assertEqual(action(text, in_thread=True), "mute")

    def test_ordinary_single_words_mute_only_when_aimed_at_the_bot(self) -> None:
        for text in ("Silencio", "うるさい", "安静！", "silêncio", "Тихо!", "im lặng", "quiet", "조용히", "빠져", "silence"):
            with self.subTest(text=text):
                self.assertEqual(action(text, in_thread=True), "allow")
                self.assertEqual(action(text, in_thread=True, reply_to_own=True), "mute")

    def test_questions_and_formatted_text_never_mute(self) -> None:
        for text in ("shut up?", "조용히 해？", "~조용히 해~", "`shut up`", "```shut up```"):
            with self.subTest(text=text):
                self.assertNotEqual(action(text, in_thread=True, reply_to_own=True), "mute")

    def test_quiet_aimed_at_the_bot_by_mention_or_name(self) -> None:
        self.assertEqual(action("shut up", raw_text=f"<@{BOT}> shut up"), "mute")
        self.assertEqual(action("루미야 조용히 해"), "mute")
        self.assertEqual(action("조용히 해, 루미야"), "mute")
        self.assertEqual(action("lumi, be quiet"), "mute")
        self.assertEqual(action("be quiet", reply_to_own=True), "mute")

    def test_unaddressed_quiet_outside_a_thread_does_not_mute(self) -> None:
        self.assertEqual(action("조용히 해", in_thread=False), "allow")

    def test_quiet_words_inside_sentences_or_quoted_never_mute(self) -> None:
        for text in (
            "닥치라고 하면 안 닥치던데", "조용히 해줘 민수야", "\"조용히 해\"라고 했어", "> shut up",
            "&gt; 조용히 해", "그만", "이건 그만 하자", "he told me to shut up", "黙れって言っても",
            "别让它闭嘴", "민수야 조용히 해", "\"shut up\"",
        ):
            with self.subTest(text=text):
                self.assertNotEqual(action(text, in_thread=True), "mute")


class MuteTests(unittest.TestCase):
    def test_muted_thread_skips_until_addressed(self) -> None:
        self.assertEqual(decide(msg("이거 어때?", in_thread=True), muted=True).reason, gate.REASON_MUTED)
        self.assertEqual(action("이거 어때?", raw_text=f"<@{BOT}> 이거 어때?", muted=True), "unmute")
        self.assertEqual(action("이거 어때?", reply_to_own=True, muted=True), "unmute")
        self.assertEqual(action("루미야 이거 어때?", muted=True), "unmute")
        self.assertEqual(action("이거 어때?", reply_expected=True, muted=True), "unmute")

    def test_talking_about_the_bot_does_not_unmute(self) -> None:
        self.assertEqual(action("루미가 아까 한 말 봐", muted=True), "skip")
        self.assertEqual(action("lumi said that earlier", muted=True), "skip")

    def test_mute_only_mode_keeps_mutes_but_not_addressee_rules(self) -> None:
        self.assertEqual(action("민수야 해줘", mode="mute_only"), "allow")
        self.assertEqual(action("조용히 해", mode="mute_only", in_thread=True), "mute")


class AddresseeTests(unittest.TestCase):
    def test_r1_leading_mention_of_someone_else(self) -> None:
        decision = decide(msg("@민수 이거 해줘", raw_text=f"<@{OTHER}> 이거 해줘"), muted=False)
        self.assertEqual(decision.reason, gate.REASON_OTHER_MENTION)
        self.assertEqual(action("@민수 해줘", raw_text=f"<@{OTHER}|alex> 해줘"), "skip")
        self.assertEqual(action("해줘", raw_text="<@123456> 해줘", self_ids=frozenset({"999"})), "skip")

    def test_r1_needs_the_bot_id(self) -> None:
        self.assertEqual(action("@민수 해줘", raw_text=f"<@{OTHER}> 해줘", self_ids=frozenset(), other_names=()), "allow")

    def test_r2_calls_by_name_in_several_languages(self) -> None:
        for text in (
            "민수야 이거 봐줘", "이거 봐줘, 민수야", "민수야", "alex, can this wait", "hey alex look at this",
            "please check, alex", "@alex do this", "田中さん、これやって", "小明，帮我看看",
            "帮我看看，小明", "alex ơi, xem cái này",
        ):
            with self.subTest(text=text):
                self.assertEqual(decide(msg(text), muted=False).reason, gate.REASON_OTHER_NAME)

    def test_trailing_cc_mentions_and_the_korean_copula_are_not_calls(self) -> None:
        self.assertEqual(action("summarize this for @x", raw_text=f"summarize this for <@{OTHER}>"), "allow")
        for text in ("범인은 민수야", "그거 민수야", "이거 봐줘 민수야"):
            with self.subTest(text=text):
                self.assertEqual(action(text), "allow")

    def test_r2_veto_self_name_or_second_person(self) -> None:
        for text in (
            "민수가 하고 있는 거 빼고 니가", "너가 한 거뿐만 아니라 민수가 한 것도", "민수야 루미한테 물어봐",
            "alex, can you check", "田中さん、あなたはどう思う", "小明，你看看", "alex, ¿tú qué opinas?",
            "민수야 너는 빠져",
        ):
            with self.subTest(text=text):
                self.assertEqual(action(text), "allow")

    def test_names_mentioned_mid_sentence_are_not_calls(self) -> None:
        for text in (
            "민수가 만든 거 확인해봐", "민수 말대로 했어", "alex said this was fine", "민수아니야",
            "这是小明的代码", "田中さんの資料を見て",
        ):
            with self.subTest(text=text):
                self.assertEqual(action(text), "allow")

    def test_no_names_means_r2_does_nothing(self) -> None:
        self.assertEqual(action("민수야 이거 봐줘", other_names=()), "allow")


class ScopeTests(unittest.TestCase):
    def event(self, text="조용히 해", *, platform="slack", chat_type="group", thread_id="171.1", **extra):
        source = SimpleNamespace(
            platform=SimpleNamespace(value=platform), chat_id="C1", thread_id=thread_id,
            chat_type=chat_type, user_id="U9", profile=None,
        )
        raw = {"text": text, "team": "T1"} if platform == "slack" else SimpleNamespace(content=text, guild=None)
        fields = {"text": text, "source": source, "raw_message": raw, "message_id": "171.2",
                  "reply_to_is_own_message": False, "reply_expected": None, "internal": False}
        fields.update(extra)
        return SimpleNamespace(**fields)

    def run_gate(self, event, gateway=None, home=None):
        home = home or Path(self.enterContext(tempfile.TemporaryDirectory()))
        return gate.gate_event(event, gateway, hermes_home=home / "hermes", omh_home=home / "omh")[0], home

    def test_dms_internal_events_commands_and_other_platforms_pass_untouched(self) -> None:
        for event in (
            self.event(chat_type="dm"), self.event(internal=True), self.event("/stop"),
            self.event(platform="telegram"),
        ):
            with self.subTest(event=event):
                self.assertIsNone(self.run_gate(event)[0])

    def test_mute_is_per_thread_and_cleared_by_a_mention(self) -> None:
        adapter = SimpleNamespace(_team_bot_user_ids={"T1": BOT}, _team_bot_names={"T1": "lumi"})
        gateway = SimpleNamespace(adapters={}, _adapter_for_source=lambda source: adapter)
        result, home = self.run_gate(self.event(), gateway)
        self.assertEqual(result, {"action": "skip", "reason": gate.REASON_QUIET})
        self.assertIsNotNone(self.run_gate(self.event("next?"), gateway, home)[0])
        self.assertIsNone(self.run_gate(self.event("next?", thread_id="999.1"), gateway, home)[0])
        self.assertIsNone(self.run_gate(self.event("next?", raw_message={"text": f"<@{BOT}> next?"}), gateway, home)[0])
        self.assertIsNone(self.run_gate(self.event("next?"), gateway, home)[0])
        skips = gate.read_skips(home / "omh")
        self.assertEqual([s["reason"] for s in skips], [gate.REASON_QUIET, gate.REASON_MUTED])

    def test_discord_parity(self) -> None:
        me = SimpleNamespace(id=42, name="lumi", display_name="lumi", global_name=None, nick=None)
        adapter = SimpleNamespace(_client=SimpleNamespace(user=me))
        gateway = SimpleNamespace(adapters={}, _adapter_for_source=lambda source: adapter)
        quiet = self.event("shut up", platform="discord", chat_type="thread", thread_id=None)
        result, home = self.run_gate(quiet, gateway)
        self.assertEqual(result["reason"], gate.REASON_QUIET)
        other = self.event("<@77> look", platform="discord", chat_type="thread", thread_id=None)
        self.assertEqual(self.run_gate(other, gateway, home)[0]["reason"], gate.REASON_MUTED)
        reply = self.event("look", platform="discord", chat_type="thread", thread_id=None)
        reply.raw_message.reference = SimpleNamespace(resolved=SimpleNamespace(author=SimpleNamespace(id=42)))
        self.assertIsNone(self.run_gate(reply, gateway, home)[0])
        self.assertEqual(self.run_gate(other, gateway, home)[0]["reason"], gate.REASON_OTHER_MENTION)

    def test_config_off_and_names(self) -> None:
        home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (home / "hermes").mkdir()
        config = home / "hermes" / "config.yaml"
        config.write_text("plugins:\n  entries:\n    omh:\n      settings:\n        messenger_gate: off\n", encoding="utf-8")
        self.assertIsNone(self.run_gate(self.event(), home=home)[0])
        config.write_text(
            "plugins:\n  entries:\n    omh:\n      settings:\n        messenger_other_names: 민수, alex\n",
            encoding="utf-8",
        )
        self.assertEqual(gate.read_settings(home / "hermes")["other_names"], ("민수", "alex"))
        self.assertEqual(self.run_gate(self.event("민수야 봐줘"), home=home)[0]["reason"], gate.REASON_OTHER_NAME)


class ReviewFollowUpTests(unittest.TestCase):
    event = ScopeTests.event
    run_gate = ScopeTests.run_gate

    def discord_gateway(self):
        me = SimpleNamespace(id=42, name="lumi", display_name="lumi", global_name=None, nick=None)
        adapter = SimpleNamespace(_client=SimpleNamespace(user=me))
        return SimpleNamespace(_adapter_for_source=lambda source: adapter), me

    def test_discord_self_mention_is_read_from_mentions_when_content_is_stripped(self) -> None:
        gateway, me = self.discord_gateway()
        other = SimpleNamespace(id=77)
        quiet = self.event("shut up", platform="discord", chat_type="group", thread_id=None)
        quiet.raw_message.mentions = [me]
        result, home = self.run_gate(quiet, gateway)
        self.assertEqual(result["reason"], gate.REASON_QUIET)
        both = self.event("<@77> look", platform="discord", chat_type="group", thread_id=None)
        both.raw_message.mentions = [me, other]
        self.assertIsNone(self.run_gate(both, gateway, home)[0])
        self.assertEqual(gate.read_mutes(home / "omh"), {})

    def test_slack_top_level_message_is_not_in_a_thread(self) -> None:
        top = self.event("조용히 해", thread_id="171.2")
        self.assertIsNone(self.run_gate(top)[0])

    def test_unauthorized_sender_changes_nothing(self) -> None:
        gateway = SimpleNamespace(_is_user_authorized_for_source=lambda source: False)
        result, home = self.run_gate(self.event(), gateway)
        self.assertIsNone(result)
        self.assertFalse((home / "omh").exists())

    def test_multiplexed_ingress_reads_the_launch_home_settings(self) -> None:
        home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        launch = home / "launch"
        launch.mkdir()
        (launch / "config.yaml").write_text(
            "plugins:\n  entries:\n    omh:\n      settings:\n"
            f"        omh_home: {home / 'store'}\n        messenger_other_names: [민수, \"alex\"]\n",
            encoding="utf-8",
        )
        constants = SimpleNamespace(get_hermes_home=lambda: str(launch))
        unscoped = gate.runtime_paths.UnattributableSessionError("no scope")
        with unittest.mock.patch.object(gate.runtime_paths, "default_hermes_home", side_effect=unscoped), \
                unittest.mock.patch.dict("sys.modules", {"hermes_constants": constants}):
            result, _ack = gate.gate_event(self.event("민수야 봐줘"), None)
        self.assertEqual(result["reason"], gate.REASON_OTHER_NAME)
        self.assertEqual(len(gate.read_skips(home / "store")), 1)

    def test_reaction_follows_the_adapter_setting_and_a_written_mute(self) -> None:
        async def react(*args):
            return True

        off = SimpleNamespace(_add_reaction=react, _reactions_enabled=lambda: False)
        self.assertIsNone(gate.ack_call(off, self.event(), "slack"))
        on = SimpleNamespace(_add_reaction=react, _team_bot_user_ids={"T1": BOT})
        gateway = SimpleNamespace(_adapter_for_source=lambda source: on)
        home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with unittest.mock.patch.object(gate, "write_mute", return_value=False):
            result, ack = gate.gate_event(self.event(), gateway, hermes_home=home, omh_home=home / "omh")
        self.assertEqual(result["reason"], gate.REASON_QUIET)
        self.assertIsNone(ack)
        event = self.event()
        event.source.scope_id = "T9"
        pending = gate.ack_call(on, event, "slack")
        self.assertTrue(asyncio.run(pending))

    def test_settings_are_cached_by_mtime(self) -> None:
        home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        config = home / "config.yaml"
        config.write_text("plugins:\n  entries:\n    omh:\n      settings:\n        messenger_gate: mute_only\n", encoding="utf-8")
        self.assertEqual(gate.read_settings(home)["mode"], "mute_only")
        with unittest.mock.patch.object(gate.runtime_paths, "plugin_setting_text", side_effect=AssertionError):
            self.assertEqual(gate.read_settings(home)["mode"], "mute_only")
        config.write_text("plugins:\n  entries:\n    omh:\n      settings:\n        messenger_gate: off\n", encoding="utf-8")
        self.assertEqual(gate.read_settings(home)["mode"], "off")


class AckTests(unittest.TestCase):
    def test_reaction_failure_does_not_break_the_skip(self) -> None:
        calls = []

        async def failing(*args):
            calls.append(args)
            raise RuntimeError("slack down")

        adapter = SimpleNamespace(_add_reaction=failing, _team_bot_user_ids={"T1": BOT})
        gateway = SimpleNamespace(_adapter_for_source=lambda source: adapter)
        event = ScopeTests().event()

        async def run():
            with tempfile.TemporaryDirectory() as tmp:
                with unittest.mock.patch.object(gate, "hermes_home_for", return_value=Path(tmp) / "h"), \
                        unittest.mock.patch.object(gate, "omh_home_for", return_value=Path(tmp) / "o"):
                    result = await gateway_hooks.pre_gateway_dispatch(event=event, gateway=gateway, session_store=None)
                return result

        self.assertEqual(asyncio.run(run())["reason"], gate.REASON_QUIET)
        self.assertEqual(calls, [("C1", "171.2", gate.SLACK_ACK_EMOJI, "T1")])

    def test_reaction_raising_synchronously_or_missing_loses_only_the_reaction(self) -> None:
        def broken(*args):
            raise RuntimeError("private API moved")

        self.assertIsNone(gate.ack_call(SimpleNamespace(_add_reaction=broken), SimpleNamespace(), "slack"))
        self.assertIsNone(gate.ack_call(SimpleNamespace(), SimpleNamespace(), "slack"))

    def test_discord_reaction_is_the_saluting_face_on_the_message(self) -> None:
        seen = []
        raw = object()

        async def react(message, emoji):
            seen.append((message, emoji))

        pending = gate.ack_call(SimpleNamespace(_add_reaction=react), SimpleNamespace(raw_message=raw), "discord")
        asyncio.run(pending)
        self.assertEqual(seen, [(raw, "\U0001fae1")])

    def test_hook_fails_open(self) -> None:
        broken = SimpleNamespace(source=SimpleNamespace(platform=property()), text=None)
        with unittest.mock.patch.object(gateway_hooks, "gate_event", side_effect=RuntimeError("boom")):
            self.assertIsNone(asyncio.run(gateway_hooks.pre_gateway_dispatch(event=broken)))


class StateTests(unittest.TestCase):
    def test_concurrent_writers_keep_every_mute_and_bound_the_log(self) -> None:
        home = Path(self.enterContext(tempfile.TemporaryDirectory()))

        def write(n: int) -> None:
            for i in range(30):
                gate.write_mute(home, f"k{n}-{i}", {"muted_ts": i})
                gate.append_skip(home, {"reason": "x", "n": n, "pad": "p" * 1000})

        threads = [threading.Thread(target=write, args=(n,)) for n in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(gate.read_mutes(home)), 240)
        self.assertEqual(len(gate.read_skips(home)), gate.SKIP_LOG_LIMIT)
        self.assertLess(gate.skip_log_path(home).stat().st_size, gate.SKIP_LOG_TRIM_BYTES + 3000)

    def test_mutes_keep_the_newest_within_the_limit(self) -> None:
        home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with unittest.mock.patch.object(gate, "MUTE_LIMIT", 3):
            for i in range(5):
                gate.write_mute(home, f"k{i}", {"muted_ts": float(i)})
        self.assertEqual(sorted(gate.read_mutes(home)), ["k2", "k3", "k4"])

    def test_unreadable_state_reads_empty(self) -> None:
        home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        gate.state_path(home).parent.mkdir(parents=True)
        gate.state_path(home).write_text("{not json", encoding="utf-8")
        self.assertEqual(gate.read_mutes(home), {})


if __name__ == "__main__":
    unittest.main()

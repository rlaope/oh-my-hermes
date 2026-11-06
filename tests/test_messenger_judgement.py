"""Model judgement in a Slack or Discord room where Hermes lets a silence marker stand."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
import unittest
from contextvars import ContextVar
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

from _module_patch import patch_modules
from omh.plugin_bundle.omh import messenger_gate as gate
from omh.plugin_bundle.omh import messenger_judgement as judge
from omh.plugin_bundle.omh.hooks import llm_hooks, result_transforms

BOT = "UBOT"


def _schedule_like_hermes(coro, loop, **_kwargs):
    """`agent.async_utils.safe_schedule_threadsafe`: None and a closed coroutine when the loop is gone."""
    try:
        return asyncio.run_coroutine_threadsafe(coro, loop)
    except RuntimeError:
        coro.close()
        return None


def hermes_modules(*, platform="slack", chat_type="thread", chat_id="C1", thread_id="171.1", profile="", config=None):
    """Stand-ins for Hermes' `gateway.session_context` and `gateway.response_filters`."""
    context = ModuleType("gateway.session_context")
    for name, value in (("_SESSION_PROFILE", profile), ("_SESSION_PLATFORM", platform), ("_SESSION_CHAT_ID", chat_id),
                        ("_SESSION_THREAD_ID", thread_id), ("_SESSION_CHAT_TYPE", chat_type)):
        var = ContextVar(name)
        var.set(value)
        vars(context)[name] = var
    filters = ModuleType("gateway.response_filters")
    filters.is_intentional_silence_response = lambda text: text.strip().upper() in {"[SILENT]", "SILENT", "NO_REPLY"}
    run = ModuleType("gateway.run")
    run._load_gateway_config = lambda path: config if config is not None else {"model": {"default": "m"}}
    package = ModuleType("gateway")
    package.session_context = context
    package.response_filters = filters
    package.run = run
    async_utils = ModuleType("agent.async_utils")
    async_utils.safe_schedule_threadsafe = _schedule_like_hermes
    agent = ModuleType("agent")
    agent.async_utils = async_utils
    return patch_modules({"gateway": package, "gateway.session_context": context, "gateway.response_filters": filters,
                          "gateway.run": run, "agent": agent, "agent.async_utils": async_utils})


def judged_gateway(adapter, *, allow=True, streaming=False, capable=True, loop=None):
    gateway = SimpleNamespace(
        adapters={}, _adapter_for_source=lambda source: adapter,
        config=SimpleNamespace(streaming=SimpleNamespace(globally_enabled=streaming)),
        _gateway_loop=loop,
    )
    if capable:
        gateway._room_allow_silence = lambda source: allow
        gateway._silence_allowed_for_source = lambda *args: True
    return gateway


def event(text, *, chat_type="thread", thread_id="171.1", raw_text=None):
    source = SimpleNamespace(platform=SimpleNamespace(value="slack"), chat_id="C1", thread_id=thread_id,
                             chat_type=chat_type, user_id="U9", profile=None)
    return SimpleNamespace(text=text, source=source, raw_message={"text": raw_text or text, "team": "T1"},
                           message_id="171.2", reply_to_is_own_message=False, reply_expected=None, internal=False)


class Reactions:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def add(self, *args):
        self.calls.append(args)
        return True


class StoreReset(unittest.TestCase):
    def setUp(self) -> None:
        judge._rooms.clear()
        judge._turns.clear()
        self.addCleanup(judge._rooms.clear)
        self.addCleanup(judge._turns.clear)
        hermes = hermes_modules()
        hermes.start()
        self.addCleanup(hermes.stop)
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.reactions = Reactions()
        self.adapter = SimpleNamespace(_team_bot_user_ids={"T1": BOT}, _add_reaction=self.reactions.add)

    def gate(self, message, gateway):
        return gate.gate_event(message, gateway, hermes_home=self.home / "hermes", omh_home=self.home / "omh")


class TokenTests(unittest.TestCase):
    def test_a_whole_reply_token_is_the_marker(self) -> None:
        zero_width, bom = chr(0x200b), chr(0xfeff)
        for text in ("[SHUTUP]", "  [shutup]\n", "*[SHUTUP]*", "[SHUTUP].", "[Shut Up]", "[SHUT_UP]", "`[SHUTUP]`",
                     "```\n[SHUTUP]\n```", "```text\n[SHUTUP]\n```", "~~[SHUTUP]~~", "［SHUTUP］", "[ SHUTUP ]",
                     "\U0001fae1 [SHUTUP]", zero_width + "[SHUTUP]", bom + "[SHUTUP]",
                     "[SHUTUP] okay, going quiet", "[SHUTUP] 넵"):
            with self.subTest(text=text):
                self.assertEqual(judge.reply_marker(text), judge.SHUTUP_TOKEN)
        with hermes_modules():
            for text in ("[SILENT]", "`[SILENT]`", "```\n[SILENT]\n```", "`SILENT`"):
                with self.subTest(text=text):
                    self.assertEqual(judge.reply_marker(text), judge.SILENT_TOKEN)

    def test_anything_else_is_not_a_marker(self) -> None:
        for text in ("Fine [SHUTUP] I'll stop now.", "use `[SHUTUP]` here", "SHUTUP", "shut up", "[SHUTUP", "", None,
                     "[SHUTUP]" + " " * 80 + "x", "one\nI said [SHUTUP] to it\ntwo", "[SHUTUP]\n\nOK", "OK.\n\n[SHUTUP]",
                     "[shutup] okay, going quiet", "[Shut Up] is a 2003 single", "The token is [SILENT]",
                     "x = [SILENT]", "[SILENT] = True", "fine. [SHUTUP]", "okay. [SILENT]", "[SILENT] not for me",
                     "[SILENT] is the marker."):
            with self.subTest(text=text):
                self.assertIsNone(judge.reply_marker(text))

    def test_a_reply_of_only_token_lines_is_a_marker(self) -> None:
        zero_width = chr(0x200b)
        for text, marker in (
            ("[SILENT]\n\n[SHUTUP]", judge.SHUTUP_TOKEN),
            ("[SHUTUP]\n[SHUTUP]", judge.SHUTUP_TOKEN),
            ("[SHUTUP]\n[SILENT]", judge.SHUTUP_TOKEN),
            ("`[SILENT]`\n~~[Shut Up]~~", judge.SHUTUP_TOKEN),
            ("```\n[SILENT]\n[SHUTUP]\n```", judge.SHUTUP_TOKEN),
            ("［SILENT］\r\n［SHUTUP］", judge.SHUTUP_TOKEN),
            (zero_width + "[SILENT]\n" + zero_width + "[SHUTUP]", judge.SHUTUP_TOKEN),
            ("[SILENT]\n[SILENT]", judge.SILENT_TOKEN),
            ("*[SILENT]*\n\n`[silent]`.", judge.SILENT_TOKEN),
        ):
            with self.subTest(text=text):
                self.assertEqual(judge.reply_marker(text), marker)

    def test_lines_that_are_not_all_tokens_are_not_a_marker(self) -> None:
        for text in ("[SILENT]\n\nHere is the answer", "[SHUTUP]\n\nreal answer", "Here is the answer\n\n[SILENT]",
                     "[SILENT]\n" + " " * 80 + "\n[SHUTUP]", "- [SILENT]\n- [SHUTUP]", "* [SHUTUP]\n* [SHUTUP]",
                     "[SILENT]\n```\n[SHUTUP]\n```", "SILENT\nSILENT", "[SILENT]\nSILENT", "[SHUTUP\n[SILENT]"):
            with self.subTest(text=text):
                self.assertIsNone(judge.reply_marker(text))

    def test_instruction_by_mode_and_address(self) -> None:
        on = judge.instruction("on")
        self.assertIn(judge.SHUTUP_TOKEN, on)
        self.assertIn(judge.SILENT_TOKEN, on)
        self.assertNotIn(judge.SILENT_TOKEN, judge.instruction("mute_only"))
        addressed = judge.instruction("on", True)
        self.assertIn(judge.SHUTUP_TOKEN, addressed)
        self.assertNotIn(judge.SILENT_TOKEN, addressed)


class RoomTests(StoreReset):
    def test_judged_room_needs_allow_silence_capability_and_no_streaming(self) -> None:
        self.assertTrue(judge.judged_room(judged_gateway(self.adapter), None, self.home))
        self.assertFalse(judge.judged_room(judged_gateway(self.adapter, allow=None), None, self.home))
        self.assertFalse(judge.judged_room(judged_gateway(self.adapter, allow=False), None, self.home))
        self.assertFalse(judge.judged_room(judged_gateway(self.adapter, streaming=True), None, self.home))
        self.assertFalse(judge.judged_room(judged_gateway(self.adapter, capable=False), None, self.home))
        no_config = judged_gateway(self.adapter)
        no_config.config = None
        self.assertFalse(judge.judged_room(no_config, None, self.home))

        def broken(source):
            raise LookupError("override table")

        failing = judged_gateway(self.adapter)
        failing._room_allow_silence = broken
        self.assertFalse(judge.judged_room(failing, None, self.home))

    def test_codex_app_server_or_an_unreadable_runtime_is_not_judged(self) -> None:
        gateway = judged_gateway(self.adapter)
        for config, judged in (
            ({"model": {"openai_runtime": "codex_app_server", "default": "m"}}, False),
            ({"model": {"openai_runtime": " Codex_App_Server "}}, False),
            ({"model": {"api_mode": "codex_app_server"}}, False),
            ({}, False),
            ({"model": {"provider": "mine"}, "providers": {"mine": {"api_mode": "codex_app_server"}}}, False),
            ({"model": {"provider": "other"}, "providers": {"mine": {"api_mode": "codex_app_server"}}}, True),
            ({"model": {"provider": ["mine"]}, "providers": {"mine": {"api_mode": "codex_app_server"}}}, True),
            ({"model": {"openai_runtime": "auto"}}, True),
            ({"model": "gpt-x"}, True),
            ({"streaming": {"enabled": False}}, True),
        ):
            with self.subTest(config=config), hermes_modules(config=config):
                self.assertEqual(judge.judged_room(gateway, None, self.home), judged)
        self.assertFalse(judge.judged_room(gateway, None, None))
        with patch_modules({"gateway.run": None}):
            self.assertFalse(judge.judged_room(gateway, None, self.home))

    def test_codex_app_server_keeps_the_word_list_gate(self) -> None:
        with hermes_modules(config={"model": {"openai_runtime": "codex_app_server"}}):
            result, ack = self.gate(event("조용히 해"), judged_gateway(self.adapter))
        self.assertEqual(result["reason"], gate.REASON_QUIET)
        self.assertTrue(asyncio.run(ack))
        self.assertEqual(judge._rooms, {})

    def test_judged_room_leaves_quiet_words_and_names_to_the_model(self) -> None:
        result, ack = self.gate(event("조용히 해"), judged_gateway(self.adapter))
        self.assertIsNone(result)
        self.assertIsNone(ack)
        self.assertEqual(gate.read_mutes(self.home / "omh"), {})
        self.assertIn(gate.thread_key("", "slack", "C1", "171.1"), judge._rooms)
        # R1 still skips before a turn, and a muted thread stays skipped.
        result, _ = self.gate(event("look", raw_text="<@UOTHER> look"), judged_gateway(self.adapter))
        self.assertEqual(result["reason"], gate.REASON_OTHER_MENTION)

    def test_rooms_without_allow_silence_keep_the_word_list_gate(self) -> None:
        for gateway in (judged_gateway(self.adapter, allow=None), judged_gateway(self.adapter, streaming=True),
                        judged_gateway(self.adapter, capable=False)):
            with self.subTest(gateway=gateway):
                judge._rooms.clear()
                home = Path(self.enterContext(tempfile.TemporaryDirectory()))
                result, ack = gate.gate_event(event("조용히 해"), gateway, hermes_home=home, omh_home=home / "omh")
                self.assertEqual(result["reason"], gate.REASON_QUIET)
                self.assertTrue(asyncio.run(ack))
                self.assertEqual(judge._rooms, {})

    def test_a_room_noted_on_one_profile_copy_reaches_a_turn_on_another(self) -> None:
        # A multiplexed gateway's ingress runs on the launch profile's copy of the bundle and the
        # turn on the serving profile's, each its own module object under its own name.
        name = "_test_omh_judgement_other_profile_copy"
        spec = importlib.util.spec_from_file_location(name, judge.__file__)
        other = importlib.util.module_from_spec(spec)
        self.addCleanup(sys.modules.pop, name, None)
        sys.modules[name] = other
        spec.loader.exec_module(other)
        self.assertIsNot(other, judge)

        muted: list[float] = []
        judge.note_room("kami/slack/C1/171.1", judge.Room(1.0, "on", muted.append, lambda: None, None))
        self.addCleanup(judge._turns.clear)
        self.assertEqual(other.turn_instruction("t7", "kami/slack/C1/171.1", now=2.0), judge.instruction("on"))
        self.assertEqual(other.judged_reply("t7", "[SHUTUP]", now=3.0), (True, judge.SILENT_TOKEN))
        self.assertEqual(muted, [3.0])

    def test_room_store_is_bounded(self) -> None:
        for n in range(judge.ROOM_LIMIT + 5):
            judge.note_room(f"k{n}", judge.Room(0.0, "on", lambda t: None, lambda: None, None))
        self.assertEqual(len(judge._rooms), judge.ROOM_LIMIT)
        self.assertNotIn("k0", judge._rooms)


class InstructionTests(StoreReset):
    def note(self):
        self.gate(event("anyone?"), judged_gateway(self.adapter))

    def test_instruction_only_for_a_noted_group_room(self) -> None:
        self.note()
        with hermes_modules():
            self.assertEqual(gate.session_room_key(), gate.thread_key("", "slack", "C1", "171.1"))
            payload = llm_hooks._with_room_instruction(
                None, llm_hooks._room_instruction({"turn_id": "t1", "platform": "slack"}))
        self.assertIn(judge.SHUTUP_TOKEN, payload["context"])
        self.assertTrue(payload["context"].startswith(llm_hooks.OMH_CONTEXT_FENCE_OPEN))
        self.assertIn("t1", judge._turns)

    def test_dms_other_platforms_other_threads_and_forks_get_nothing(self) -> None:
        self.note()
        for modules in (hermes_modules(chat_type="dm"), hermes_modules(platform="telegram"),
                        hermes_modules(thread_id="999.1")):
            with self.subTest(modules=modules), modules:
                self.assertEqual(llm_hooks._room_instruction({"turn_id": "t1", "platform": "slack"}), "")
        with hermes_modules():
            self.assertEqual(llm_hooks._room_instruction({"turn_id": "t1", "platform": "slack", "session_id": "s",
                                                          "parent_session_id": "s"}), "")
            self.assertEqual(llm_hooks._room_instruction({"platform": "slack"}), "")
        self.assertEqual(judge._turns, {})
        # Without Hermes' session ContextVars at all.
        with patch_modules({"gateway": None}):
            self.assertEqual(gate.session_room_key(), "")

    def test_a_delegated_child_in_the_parents_context_gets_nothing(self) -> None:
        # The child's copy_context still names the person's thread; its session id is its own.
        self.note()
        with hermes_modules():
            self.assertTrue(gate.session_room_key())
            for child in (
                {"turn_id": "c1", "session_id": "child", "parent_session_id": "parent", "platform": "subagent"},
                {"turn_id": "c1", "session_id": "child", "parent_session_id": "parent", "platform": "slack"},
                {"turn_id": "c1", "session_id": "child", "parent_session_id": "", "platform": "subagent"},
            ):
                with self.subTest(child=child):
                    self.assertEqual(llm_hooks._room_instruction(child), "")
        self.assertEqual(judge._turns, {})
        self.assertEqual(judge.judged_reply("c1", "[SHUTUP]"), (False, None))
        self.assertEqual(gate.read_mutes(self.home / "omh"), {})

    def test_addressed_stays_until_a_turn_takes_it(self) -> None:
        self.gate(event("hey", raw_text=f"<@{BOT}> hey"), judged_gateway(self.adapter))
        self.gate(event("thanks all"), judged_gateway(self.adapter))
        key = gate.thread_key("", "slack", "C1", "171.1")
        self.assertNotIn(judge.SILENT_TOKEN, judge.turn_instruction("t5", key))
        self.assertIn(judge.SILENT_TOKEN, judge.turn_instruction("t6", key))

    def test_a_message_addressed_to_the_bot_is_not_offered_silent(self) -> None:
        self.gate(event("hey", raw_text=f"<@{BOT}> hey"), judged_gateway(self.adapter))
        key = gate.thread_key("", "slack", "C1", "171.1")
        text = judge.turn_instruction("t2", key)
        self.assertIn(judge.SHUTUP_TOKEN, text)
        self.assertNotIn(judge.SILENT_TOKEN, text)

    def test_stale_room_gets_nothing(self) -> None:
        self.note()
        key = gate.thread_key("", "slack", "C1", "171.1")
        self.assertEqual(judge.turn_instruction("t1", key, now=judge._rooms[key].noted + judge.ROOM_TTL_SECONDS + 1), "")

    def test_instruction_rides_inside_the_existing_fence(self) -> None:
        fenced = llm_hooks.fence_omh_context(["[OMH] route hint"])
        merged = llm_hooks._with_room_instruction({"context": fenced}, "NOTE")["context"]
        self.assertEqual(merged, llm_hooks.fence_omh_context(["[OMH] route hint", "NOTE"]))
        plain = llm_hooks._with_room_instruction({"context": "degraded"}, "NOTE")["context"]
        self.assertTrue(plain.startswith("degraded\n\n" + llm_hooks.OMH_CONTEXT_FENCE_OPEN))
        self.assertIsNone(llm_hooks._with_room_instruction(None, ""))

    def test_pre_llm_call_appends_the_instruction(self) -> None:
        self.note()
        with hermes_modules(), mock.patch.object(llm_hooks, "_turn_context", return_value=None):
            payload = llm_hooks.pre_llm_call(session_id="s", turn_id="t1", platform="Slack")
        self.assertIn(judge.ELSEWHERE_LINE, payload["context"])


class ReplyTests(StoreReset):
    def keep_turn(self, turn_id="t1", gateway=None):
        async def ingress():
            self.gate(event("hey"), gateway or judged_gateway(self.adapter, loop=asyncio.get_running_loop()))
            key = gate.thread_key("", "slack", "C1", "171.1")
            self.assertTrue(judge.turn_instruction(turn_id, key))

        return ingress

    def test_shutup_mutes_reacts_and_becomes_silent(self) -> None:
        async def run():
            await self.keep_turn()()
            with hermes_modules():
                verdict = await asyncio.to_thread(result_transforms.transform_llm_output, response_text=" [SHUTUP]\n",
                                                  turn_id="t1", session_id="s", platform="slack")
            for _ in range(5):
                await asyncio.sleep(0)
            return verdict

        self.assertEqual(asyncio.run(run()), judge.SILENT_TOKEN)
        mutes = gate.read_mutes(self.home / "omh")
        self.assertEqual(list(mutes), [gate.thread_key("", "slack", "C1", "171.1")])
        self.assertTrue(next(iter(mutes.values()))["judged"])
        self.assertEqual(self.reactions.calls, [("C1", "171.2", gate.SLACK_ACK_EMOJI, "T1")])
        skips = gate.read_skips(self.home / "omh")
        self.assertEqual([(s["reason"], s["marker"], s["text"]) for s in skips],
                         [(gate.REASON_JUDGED_SILENT, judge.SHUTUP_TOKEN, "hey")])
        # The muted thread is skipped until the bot is addressed.
        result, _ = self.gate(event("and then?"), judged_gateway(self.adapter))
        self.assertEqual(result["reason"], gate.REASON_MUTED)

    def test_own_silent_marker_passes_untouched(self) -> None:
        asyncio.run(self.keep_turn()())
        with hermes_modules():
            self.assertEqual(judge.judged_reply("t1", "[SILENT]"), (True, None))
            self.assertIsNone(result_transforms.transform_llm_output(response_text="NO_REPLY", turn_id="t1"))
        self.assertEqual(gate.read_mutes(self.home / "omh"), {})
        self.assertEqual([s["marker"] for s in gate.read_skips(self.home / "omh")], [judge.SILENT_TOKEN])

    def test_wrapped_silent_comes_back_clean(self) -> None:
        for text in ("`[SILENT]`", "```\n[SILENT]\n```", "~~[SILENT]~~", "`SILENT`"):
            with self.subTest(text=text):
                asyncio.run(self.keep_turn()())
                self.assertEqual(judge.judged_reply("t1", text), (True, judge.SILENT_TOKEN))
        self.assertEqual(gate.read_mutes(self.home / "omh"), {})

    def test_an_acknowledged_shutup_mutes_and_posts_nothing(self) -> None:
        asyncio.run(self.keep_turn()())
        self.assertEqual(judge.judged_reply("t1", "[SHUTUP] okay, going quiet"), (True, judge.SILENT_TOKEN))
        self.assertEqual(len(gate.read_mutes(self.home / "omh")), 1)

    def test_a_token_line_at_a_real_answers_edge_is_removed_with_no_mute(self) -> None:
        answer = "Here is the answer. The deploy failed because the disk is full."
        long_answer = "The deploy failed. " * 70 + "Done."
        for text, delivered in (
            (answer + "\n\n[SILENT]", answer),
            (answer + "\n\n[SHUTUP]", answer),
            (long_answer + "\n\n[SILENT]", long_answer),
            (long_answer + "\n\n[SHUTUP]", long_answer),
            ("[SHUTUP]\n\n" + answer, answer),
            ("Yes, the tests pass. [SHUTUP]", "Yes, the tests pass."),
            ("네, 테스트 통과했어요. [SHUTUP]", "네, 테스트 통과했어요."),
            ("Deployed to prod at 10:30. [SILENT]", "Deployed to prod at 10:30."),
            ("배포 끝났습니다. [SILENT]", "배포 끝났습니다."),
            ("First line.\nDeployed at 10:30. [SILENT]", "First line.\nDeployed at 10:30."),
            ("fine. [SHUTUP]", "fine."),
            ("[SHUTUP]\n\nreal answer", "real answer"),
            ("Done. [SILENT]", "Done."),
            ("끝났습니다. [SHUTUP]", "끝났습니다."),
            ("完了。 [SILENT]", "完了。"),
            ("Done! [SILENT]", "Done!"),
            ("Really? [SILENT]", "Really?"),
            ("Wait… [SILENT]", "Wait…"),  # NFKC reads it as `...`; what is delivered keeps it as written
            ("Done！ [SILENT]", "Done！"),
            ("Really？ [SILENT]", "Really？"),
            ("Done‽ [SILENT]", "Done‽"),
            ("هل انتهى؟ [SILENT]", "هل انتهى؟"),
            ("काम पूरा हुआ। [SILENT]", "काम पूरा हुआ।"),
            ("کام ہو گیا۔ [SILENT]", "کام ہو گیا۔"),
        ):
            with self.subTest(text=text[:40]):
                asyncio.run(self.keep_turn()())
                self.assertEqual(judge.judged_reply("t1", text), (False, delivered))
        self.assertEqual(gate.read_mutes(self.home / "omh"), {})
        self.assertEqual(gate.read_skips(self.home / "omh"), [])
        asyncio.run(self.keep_turn()())
        self.assertEqual(result_transforms.transform_llm_output(response_text=answer + "\n\n[SHUTUP]", turn_id="t1"),
                         answer)

    def test_real_answers_come_out_byte_identical_with_no_mute(self) -> None:
        for text in (
            "The marker Hermes drops is this one:\n\n```\n[SILENT]\n```",
            "To go quiet the bot replies:\n\n```\n[SHUTUP]\n```",
            "I use two markers:\n- [SILENT]\n- [SHUTUP]",
            "The token is:\n`[SILENT]`",
            "The token is:\n\n[SHUTUP]",
            "- first\n- second\n[SILENT]",
            "```\nunclosed\n[SILENT]",
            "[Silent]\nThe film came out in 1927 and ran for two hours.",
            "[Shut Up]\nA 2003 single that charted in several countries.",
            "Silent\n\nThat is the word you wanted.",
            "It is one word.\n\nSilent",
            'if reply == "[SILENT]":',
            'markers = ["[SILENT]", "[SHUTUP]"]',
            "flags[SILENT] = True",
            "value = options[silent]",
            "See [silent](https://example.com/silent-mode) for the details.",
            "exactly `[SILENT]`, and the plugin turns `[SHUTUP]` into it.",
            "Replying with [SILENT] tells Hermes to drop it.",
            "Fine [SHUTUP] I'll stop now.",
            "Use this one: [SHUTUP]",
            "조용히 할 땐 이걸 씁니다: [SHUTUP]",
            "The token is: [SILENT]",
            "Answer: [SILENT]",
            "토큰은 이겁니다: [SILENT]",
            "토큰은 이겁니다：[SILENT]",
            "토큰은 이겁니다： [SILENT]",
            "토큰은 이겁니다：\n\n[SHUTUP]",
            "The token is [SILENT]",
            "- done. [SILENT]",
            "Run this:\nDone. [SHUTUP]",
            "[SILENT] is the marker.",
            "[SILENT] tells Hermes to drop a reply.",
            "[SILENT] 은 마커입니다.",
            "[SILENT] not for me",
            "[SILENT]\nThis token drops a reply.",
            "[SILENT]\n\nHere is the answer",
            "- [SILENT]\n- [SHUTUP]",
            "The marker - [SILENT]",
            "One, [SILENT]",
            "Done; [SILENT]",
            "Done — [SILENT]",
            "Done» [SILENT]",
            "1. [SILENT]",
        ):
            with self.subTest(text=text):
                asyncio.run(self.keep_turn()())
                self.assertEqual(judge.judged_reply("t1", text), (False, None))
                asyncio.run(self.keep_turn()())
                self.assertIsNone(result_transforms.transform_llm_output(response_text=text, turn_id="t1"))
        self.assertEqual(gate.read_mutes(self.home / "omh"), {})
        self.assertEqual(gate.read_skips(self.home / "omh"), [])

    def test_token_lines_and_nothing_else_mute_when_one_is_shutup(self) -> None:
        for text, marker in (("[SILENT]\n\n[SHUTUP]", judge.SHUTUP_TOKEN), ("[SHUTUP]\n[SHUTUP]", judge.SHUTUP_TOKEN),
                             ("[SHUTUP]\n[SILENT]", judge.SHUTUP_TOKEN), ("[SILENT]\n[SILENT]", judge.SILENT_TOKEN)):
            with self.subTest(text=text):
                muted: list[float] = []
                reacted: list[int] = []
                logged: list[str] = []
                judge._turns["t1"] = judge.Room(1.0, "on", lambda tick: muted.append(tick) or True,
                                                lambda: reacted.append(1), object(),
                                                log=lambda said, tick: logged.append(said))
                self.assertEqual(judge.judged_reply("t1", text, now=2.0), (True, judge.SILENT_TOKEN))
                once = marker == judge.SHUTUP_TOKEN
                self.assertEqual((muted, reacted, logged), ([2.0] if once else [], [1] if once else [], [marker]))

    def test_token_lines_reach_the_real_mute_and_the_hook_sends_only_silent(self) -> None:
        asyncio.run(self.keep_turn()())
        self.assertEqual(result_transforms.transform_llm_output(response_text="[SILENT]\n\n[SHUTUP]", turn_id="t1"),
                         judge.SILENT_TOKEN)
        self.assertEqual(len(gate.read_mutes(self.home / "omh")), 1)

    def test_a_round_end_restore_cannot_bring_back_a_marker(self) -> None:
        asyncio.run(self.keep_turn()())
        with mock.patch.object(result_transforms, "restore_round_end_answer", return_value="[SHUTUP]"):
            self.assertEqual(result_transforms.transform_llm_output(response_text="sentinel", turn_id="t1"),
                             judge.SILENT_TOKEN)
        self.assertEqual(len(gate.read_mutes(self.home / "omh")), 1)
        asyncio.run(self.keep_turn()())
        with mock.patch.object(result_transforms, "restore_round_end_answer", return_value="[SILENT]"):
            self.assertEqual(result_transforms.transform_llm_output(response_text="sentinel", turn_id="t1"),
                             judge.SILENT_TOKEN)

    def test_the_turns_age_starts_when_it_is_kept(self) -> None:
        judge.note_room("k", judge.Room(100.0, "on", lambda t: True, lambda: None, None))
        kept_at = 100.0 + judge.ROOM_TTL_SECONDS - 1
        self.assertTrue(judge.turn_instruction("t3", "k", now=kept_at))
        self.assertEqual(judge.judged_reply("t3", "[SHUTUP]", now=kept_at + judge.TURN_TTL_SECONDS - 1),
                         (True, judge.SILENT_TOKEN))

    def test_the_reaction_needs_a_written_mute(self) -> None:
        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        reacted = []
        judge._turns["t4"] = judge.Room(1.0, "on", lambda t: False, lambda: reacted.append(1), loop)
        self.assertEqual(judge.judged_reply("t4", "[SHUTUP]", now=2.0), (True, judge.SILENT_TOKEN))
        self.assertEqual(reacted, [])

    def test_turns_without_the_instruction_or_with_prose_are_not_handled(self) -> None:
        self.assertEqual(judge.judged_reply("never-kept", "[SHUTUP]"), (False, None))
        asyncio.run(self.keep_turn()())
        self.assertEqual(judge.judged_reply("t1", "All done, here is your answer."), (False, None))
        # The turn is used once.
        self.assertEqual(judge.judged_reply("t1", "[SHUTUP]"), (False, None))
        self.assertEqual(gate.read_mutes(self.home / "omh"), {})

    def test_failed_mute_or_reaction_still_never_sends_the_token(self) -> None:
        def boom(_tick):
            raise RuntimeError("disk")

        def boom_react():
            raise KeyError("adapter")

        for room in (judge.Room(0.0, "on", boom, lambda: None, None),
                     judge.Room(0.0, "on", lambda t: True, boom_react, asyncio.new_event_loop())):
            with self.subTest(room=room):
                judge._turns["t9"] = room._replace(noted=1.0)
                self.assertEqual(judge.judged_reply("t9", "[SHUTUP]", now=2.0), (True, judge.SILENT_TOKEN))
                judge._turns["t9"] = room._replace(noted=1.0, log=boom)
                self.assertEqual(judge.judged_reply("t9", "[SHUTUP]", now=2.0), (True, judge.SILENT_TOKEN))
                if room.loop is not None:
                    room.loop.close()

    def test_reaction_needs_a_loop_and_hermes_helper(self) -> None:
        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        # Without Hermes' scheduling helper the coroutine is closed, never left unawaited.
        pending = self.reactions.add("C1")
        with patch_modules({"agent.async_utils": None}):
            self.assertFalse(judge._schedule(lambda: pending, loop))
        self.assertIsNone(pending.cr_frame)
        self.assertFalse(judge._schedule(lambda: None, loop))
        self.assertFalse(judge._schedule(lambda: self.fail("no loop, no call"), None))
        self.assertEqual(self.reactions.calls, [])


if __name__ == "__main__":
    unittest.main()

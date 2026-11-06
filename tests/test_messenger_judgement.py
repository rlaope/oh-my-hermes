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


def hermes_modules(*, platform="slack", chat_type="thread", chat_id="C1", thread_id="171.1", profile=""):
    """Stand-ins for Hermes' `gateway.session_context` and `gateway.response_filters`."""
    context = ModuleType("gateway.session_context")
    for name, value in (("_SESSION_PROFILE", profile), ("_SESSION_PLATFORM", platform), ("_SESSION_CHAT_ID", chat_id),
                        ("_SESSION_THREAD_ID", thread_id), ("_SESSION_CHAT_TYPE", chat_type)):
        var = ContextVar(name)
        var.set(value)
        vars(context)[name] = var
    filters = ModuleType("gateway.response_filters")
    filters.is_intentional_silence_response = lambda text: text.strip().upper() in {"[SILENT]", "NO_REPLY"}
    package = ModuleType("gateway")
    package.session_context = context
    package.response_filters = filters
    async_utils = ModuleType("agent.async_utils")
    async_utils.safe_schedule_threadsafe = lambda coro, loop, **_kw: asyncio.run_coroutine_threadsafe(coro, loop)
    agent = ModuleType("agent")
    agent.async_utils = async_utils
    return patch_modules({"gateway": package, "gateway.session_context": context, "gateway.response_filters": filters,
                          "agent": agent, "agent.async_utils": async_utils})


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
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.reactions = Reactions()
        self.adapter = SimpleNamespace(_team_bot_user_ids={"T1": BOT}, _add_reaction=self.reactions.add)

    def gate(self, message, gateway):
        return gate.gate_event(message, gateway, hermes_home=self.home / "hermes", omh_home=self.home / "omh")


class TokenTests(unittest.TestCase):
    def test_token_variants(self) -> None:
        for text in ("[SHUTUP]", "  [shutup]\n", "*[SHUTUP]*", "[SHUTUP].", "[Shut Up]", "[SHUT_UP]"):
            with self.subTest(text=text):
                self.assertTrue(judge.is_shutup(text))

    def test_a_token_inside_text_or_code_is_not_a_token(self) -> None:
        for text in ("[SHUTUP] okay, going quiet", "fine. [SHUTUP]", "`[SHUTUP]`", "SHUTUP", "shut up",
                     "[SHUTUP", "", None, "[SHUTUP]" + " " * 80 + "x"):
            with self.subTest(text=text):
                self.assertFalse(judge.is_shutup(text))

    def test_instruction_by_mode(self) -> None:
        on = judge.instruction("on")
        self.assertIn(judge.SHUTUP_TOKEN, on)
        self.assertIn(judge.SILENT_TOKEN, on)
        self.assertNotIn(judge.SILENT_TOKEN, judge.instruction("mute_only"))


class RoomTests(StoreReset):
    def test_judged_room_needs_allow_silence_capability_and_no_streaming(self) -> None:
        self.assertTrue(judge.judged_room(judged_gateway(self.adapter), None))
        self.assertFalse(judge.judged_room(judged_gateway(self.adapter, allow=None), None))
        self.assertFalse(judge.judged_room(judged_gateway(self.adapter, allow=False), None))
        self.assertFalse(judge.judged_room(judged_gateway(self.adapter, streaming=True), None))
        self.assertFalse(judge.judged_room(judged_gateway(self.adapter, capable=False), None))
        no_config = judged_gateway(self.adapter)
        no_config.config = None
        self.assertFalse(judge.judged_room(no_config, None))

        def broken(source):
            raise LookupError("override table")

        failing = judged_gateway(self.adapter)
        failing._room_allow_silence = broken
        self.assertFalse(judge.judged_room(failing, None))

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
            payload = llm_hooks._with_room_instruction(None, llm_hooks._room_instruction({"turn_id": "t1"}))
        self.assertIn(judge.SHUTUP_TOKEN, payload["context"])
        self.assertTrue(payload["context"].startswith(llm_hooks.OMH_CONTEXT_FENCE_OPEN))
        self.assertIn("t1", judge._turns)

    def test_dms_other_platforms_other_threads_and_forks_get_nothing(self) -> None:
        self.note()
        for modules in (hermes_modules(chat_type="dm"), hermes_modules(platform="telegram"),
                        hermes_modules(thread_id="999.1")):
            with self.subTest(modules=modules), modules:
                self.assertEqual(llm_hooks._room_instruction({"turn_id": "t1"}), "")
        with hermes_modules():
            self.assertEqual(llm_hooks._room_instruction({"turn_id": "t1", "session_id": "s", "parent_session_id": "s"}), "")
            self.assertEqual(llm_hooks._room_instruction({}), "")
        self.assertEqual(judge._turns, {})
        # Without Hermes' session ContextVars at all.
        self.assertEqual(gate.session_room_key(), "")

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
            payload = llm_hooks.pre_llm_call(session_id="s", turn_id="t1", platform="slack")
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
        # The muted thread is skipped until the bot is addressed.
        result, _ = self.gate(event("and then?"), judged_gateway(self.adapter))
        self.assertEqual(result["reason"], gate.REASON_MUTED)

    def test_own_silent_marker_passes_untouched(self) -> None:
        asyncio.run(self.keep_turn()())
        with hermes_modules():
            self.assertEqual(judge.judged_reply("t1", "[SILENT]"), (True, None))
            self.assertIsNone(result_transforms.transform_llm_output(response_text="NO_REPLY", turn_id="t1"))
        self.assertEqual(gate.read_mutes(self.home / "omh"), {})

    def test_turns_without_the_instruction_or_with_prose_are_not_handled(self) -> None:
        self.assertEqual(judge.judged_reply("never-kept", "[SHUTUP]"), (False, None))
        asyncio.run(self.keep_turn()())
        self.assertEqual(judge.judged_reply("t1", "[SHUTUP] fine, I'll be quiet"), (False, None))
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
                if room.loop is not None:
                    room.loop.close()

    def test_reaction_needs_a_loop_and_hermes_helper(self) -> None:
        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        # Without Hermes' scheduling helper the coroutine is closed, never left unawaited.
        pending = self.reactions.add("C1")
        self.assertFalse(judge._schedule(lambda: pending, loop))
        self.assertIsNone(pending.cr_frame)
        self.assertFalse(judge._schedule(lambda: None, loop))
        self.assertFalse(judge._schedule(lambda: self.fail("no loop, no call"), None))
        self.assertEqual(self.reactions.calls, [])


if __name__ == "__main__":
    unittest.main()

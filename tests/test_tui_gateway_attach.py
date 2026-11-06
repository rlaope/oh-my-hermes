"""The OMH TUI's gateway child on Hermes' interpreter: attach versus stdio, and the canonical-wire translation.

`omh.tui.attach.gateway_attach` runs as a script on Hermes' interpreter. The
pure `Adapter` is tested here frame by frame. The script itself is run the way
`gateway_spawn` runs it, against fake Hermes installs written into a temp dir:
one with the shared-gateway attach API (a fake owner behind a fake
`websockets` client, which records every frame it receives), one with only the
stdio entry, and one whose `hermes_cli` has no attach API. The real
`GatewayClient` drives all three.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
import sys
import textwrap
import threading
import types
import unittest
from unittest.mock import patch

from _module_patch import patch_modules
from _test_temp_root import make_test_tempdir
from five_issue_process_fixture import fixture_system_environment
from omh.tui.attach import gateway_attach as attach
from omh.tui.attach.gateway_attach import TO_CLIENT, TO_OWNER, Adapter, LocalImage
from omh.tui.gateway import GATEWAY_SCRIPT, GatewayClient, GatewayUnavailable, ServerRequest, gateway_spawn

CONTRACT = {
    "sources": ["cli", "tui"],
    "parameters": sorted({"client_env", "cwd", "model", "provider", "request_id", "source", "toolsets", "yolo"}),
}
SID = "local-abc"
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 16
FAST_GRACE = 0.3


def _ids() -> object:
    counter = iter(range(1, 1000))
    return lambda: f"id-{next(counter)}"


def _call(request_id: object, method: str, params: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def _answer(request_id: object, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: object, message: str, detail: str = "") -> dict:
    data = {"reason": message, **({"detail": detail} if detail else {})}
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": 4001, "message": message, "data": data}}


def _event(kind: str, payload: dict, session_id: str = SID, **envelope: object) -> dict:
    return {"jsonrpc": "2.0", "method": "event",
            "params": {"type": kind, "session_id": session_id, "payload": payload, **envelope}}


class FakeFiles:
    """`HermesFiles` without a disk: one image per path it knows."""

    def __init__(self, images: dict[str, LocalImage] | None = None, clipboard: tuple[Path, str] | None = None) -> None:
        self.images = images or {}
        self.pasted = clipboard
        self.cwds: list[str] = []  # the workspace each lookup was read against

    def image(self, raw: str, cwd: str = "") -> LocalImage:
        self.cwds.append(cwd)
        if raw not in self.images:
            raise ValueError(f"image not found: {raw}")
        return self.images[raw]

    def dropped_image(self, text: str, cwd: str = "") -> LocalImage | None:
        self.cwds.append(cwd)
        return self.images.get(text)

    def clipboard(self) -> tuple[Path, str] | None:
        return self.pasted


class AdapterCase(unittest.TestCase):
    def adapter(self, options: dict | None = None, *, tool_progress: str | None = None,
                files: FakeFiles | None = None) -> Adapter:
        adapter = Adapter(options or {}, tool_progress, files=files or FakeFiles(), new_id=_ids())
        [(target, describe)] = adapter.describe()
        self.assertEqual((target, describe["method"]), (TO_OWNER, "runtime.describe"))
        self.assertEqual(adapter.from_owner(_answer(describe["id"], {"session_create": CONTRACT})), [])
        return adapter

    def opened(self, adapter: Adapter, generation: int = 3, **extra: object) -> None:
        """A session the TUI created, with this connection's view of it."""
        [(_, create)] = adapter.from_client(_call(1, "session.create", {"cols": 80}))
        adapter.from_owner(_answer(create["id"], {"session_id": SID, "stored_session_id": SID,
                                                  "subscription_id": "sub-1", "execution_generation": generation,
                                                  "revision": 7, "messages": [], **extra}))

    def own_call(self, actions: list, method: str) -> dict:
        [(target, frame)] = actions
        self.assertEqual((target, frame["method"]), (TO_OWNER, method))
        self.assertTrue(frame["id"].startswith("omh-attach-"), frame["id"])
        return frame


class LaunchPolicyTests(AdapterCase):
    """What the stdio entry read from its own environment rides session.create, as `canonicalGateway.ts` sends it."""

    ENV = {
        "HERMES_MODEL": "gpt-x", "HERMES_TUI_PROVIDER": "openai", "HERMES_CWD": "/launch/dir",
        "HERMES_TUI_TOOLSETS": "web,terminal", "HERMES_TUI_SKILLS": "a, b\na", "HERMES_YOLO_MODE": "1",
        "HERMES_TUI_CLIENT_ENV": json.dumps({"PATH": "/bin"}), "HERMES_TUI_MAX_TURNS": "5", "HERMES_SAFE_MODE": "no",
    }

    def test_launch_options_are_read_as_ink_reads_them(self) -> None:
        self.assertEqual(attach.launch_options(self.ENV), {
            "model": "gpt-x", "provider": "openai", "cwd": "/launch/dir", "toolsets": ["web", "terminal"],
            "skills": ["a", "b"], "client_env": {"PATH": "/bin"}, "max_turns": 5, "yolo": True,
        })
        self.assertEqual(attach.launch_options({"HERMES_TUI_MAX_TURNS": "none"}), {"max_turns": "none"})
        self.assertEqual(attach.launch_options({"HERMES_TUI_CLIENT_ENV": "not json"}), {})
        self.assertEqual(attach.launch_options({}), {})

    def test_session_create_carries_the_launch_policy_and_drops_cols(self) -> None:
        adapter = self.adapter(attach.launch_options(self.ENV) | {"skills": None})
        del adapter.options["skills"], adapter.options["max_turns"]  # outside this contract; refused below
        [(target, create)] = adapter.from_client(_call(1, "session.create", {"cols": 120, "cwd": "/tui/cwd"}))
        self.assertEqual(target, TO_OWNER)
        self.assertEqual(create["id"], 1)
        self.assertEqual(create["params"], {
            "cwd": "/tui/cwd", "model": "gpt-x", "provider": "openai", "toolsets": ["web", "terminal"],
            "client_env": {"PATH": "/bin"}, "yolo": True, "source": "tui", "request_id": "id-1",
        })

    def test_an_option_the_owner_does_not_take_refuses_the_create_as_drift(self) -> None:
        adapter = self.adapter({"skills": ["a"]})
        [(target, refusal)] = adapter.from_client(_call(1, "session.create", {"cols": 80}))
        self.assertEqual(target, TO_CLIENT)
        self.assertEqual(refusal["error"]["code"], attach.PARAM_REJECTED)
        self.assertIn("skills", refusal["error"]["message"])

    def test_client_env_is_dropped_for_an_owner_that_predates_it(self) -> None:
        adapter = Adapter({"client_env": {"PATH": "/bin"}}, new_id=_ids())
        [(_, describe)] = adapter.describe()
        adapter.from_owner(_answer(describe["id"], {"session_create": {"sources": ["tui"],
                                                                       "parameters": ["request_id", "source"]}}))
        [(_, create)] = adapter.from_client(_call(1, "session.create", {"cols": 80}))
        self.assertEqual(create["params"], {"source": "tui", "request_id": "id-1"})

    def test_session_create_waits_for_the_contract(self) -> None:
        adapter = Adapter({}, new_id=_ids())
        [(_, describe)] = adapter.describe()
        self.assertEqual(adapter.from_client(_call(1, "session.create", {"cols": 80})), [])
        [(target, create)] = adapter.from_owner(_answer(describe["id"], {"session_create": CONTRACT}))
        self.assertEqual((target, create["method"], create["id"]), (TO_OWNER, "session.create", 1))

    def test_an_owner_without_a_contract_or_without_tui_sessions_refuses_the_create(self) -> None:
        adapter = Adapter({}, new_id=_ids())
        [(_, describe)] = adapter.describe()
        adapter.from_client(_call(1, "session.create", {}))
        [(target, refusal)] = adapter.from_owner(_error(describe["id"], "unknown method"))
        self.assertEqual(target, TO_CLIENT)
        self.assertEqual(refusal["error"]["code"], attach.REFUSED)
        self.assertIn("unknown method", refusal["error"]["message"])
        adapter = Adapter({}, new_id=_ids())
        [(_, describe)] = adapter.describe()
        adapter.from_owner(_answer(describe["id"], {"session_create": {"sources": ["cli"], "parameters": []}}))
        [(_, refusal)] = adapter.from_client(_call(1, "session.create", {}))
        self.assertIn("no session from a TUI", refusal["error"]["message"])

    def test_tool_progress_is_pinned_before_the_create_is_answered(self) -> None:
        adapter = self.adapter(tool_progress="verbose")
        [(_, create)] = adapter.from_client(_call(1, "session.create", {}))
        pin = self.own_call(adapter.from_owner(_answer(1, {"session_id": SID, "messages": []})), "config.set")
        self.assertEqual(pin["params"], {"key": "verbose", "session_id": SID, "value": "verbose"})
        [(target, answer)] = adapter.from_owner(_answer(pin["id"], {"key": "verbose", "value": "verbose"}))
        self.assertEqual((target, answer["id"], answer["result"]["session_id"]), (TO_CLIENT, 1, SID))

    def test_a_refused_tool_progress_pin_leaves_the_created_session_before_refusing_the_create(self) -> None:
        adapter = self.adapter(tool_progress="verbose")
        adapter.current = "local-before"  # the session the TUI had open, as after a `/new` whose create failed
        adapter.from_client(_call(1, "session.create", {}))
        prompt = {"kind": "approval", "prompt_id": "p1", "execution_generation": 0, "choices": ["once", "deny"]}
        pin = self.own_call(adapter.from_owner(_answer(1, {"session_id": SID, "subscription_id": "sub-1",
                                                           "messages": [], "prompts": [prompt]})), "config.set")
        [(_, cancel), (target, detach), (_, refusal)] = adapter.from_owner(_error(pin["id"], "invalid_params"))
        self.assertEqual(cancel, _event("request.cancel", {"id": "omh-approval-p1", "request_ids": ["omh-approval-p1"]}))
        self.assertEqual((target, detach["method"], detach["params"]), (TO_OWNER, "session.detach", {
            "session_id": SID, "subscription_id": "sub-1", "end_reason": attach.CLOSE_END_REASON}))
        self.assertEqual((refusal["id"], refusal["error"]["code"]), (1, attach.REFUSED))
        self.assertNotIn(SID, adapter.sessions)
        self.assertEqual(adapter.shown, {})
        self.assertEqual(adapter.current, "local-before")  # `shell.exec` never runs in the session just left

    def test_an_unknown_tool_progress_refuses_the_launch(self) -> None:
        self.assertEqual(attach.launch_tool_progress({"HERMES_TUI_TOOL_PROGRESS": " Verbose "}), "verbose")
        self.assertIsNone(attach.launch_tool_progress({}))
        with self.assertRaises(ValueError):
            attach.launch_tool_progress({"HERMES_TUI_TOOL_PROGRESS": "loud"})


class SessionTranslationTests(AdapterCase):
    def test_a_resume_asks_for_display_rows_and_its_answer_shows_them(self) -> None:
        adapter = self.adapter()
        [(_, resume)] = adapter.from_client(_call(2, "session.resume", {"session_id": SID, "cols": 80}))
        self.assertEqual(resume["params"], {"session_id": SID, "display_projection": True})
        stored = [{"role": "user", "content": [{"type": "text", "text": "hi"}, {"type": "input_image"}], "row_id": 4}]
        display = [{"role": "user", "text": "hi"}]
        [(_, answer)] = adapter.from_owner(_answer(2, {"session_id": SID, "messages": stored,
                                                       "display_messages": display, "subscription_id": "sub-9"}))
        self.assertEqual(answer["result"]["messages"], display)
        self.assertEqual(answer["result"]["stored_messages"][0]["text"], "hi\n[image]")
        self.assertNotIn("display_messages", answer["result"])
        self.assertEqual(adapter.sessions[SID].subscription_id, "sub-9")
        [(_, answer)] = self.adapter().from_owner(_answer(2, {"messages": stored}))  # no translation asked: as sent
        self.assertNotIn("stored_messages", answer["result"])

    def test_a_prompt_still_open_at_resume_is_asked_after_the_answer(self) -> None:
        adapter = self.adapter()
        adapter.from_client(_call(2, "session.resume", {"session_id": SID}))
        prompt = {"kind": "approval", "prompt_id": "p1", "execution_generation": 2, "command": "rm -rf x",
                  "description": "delete", "choices": ["once", "deny"]}
        [(_, answer), (target, request)] = adapter.from_owner(
            _answer(2, {"session_id": SID, "messages": [], "prompts": [prompt]}))
        self.assertEqual(answer["id"], 2)
        self.assertEqual((target, request["method"], request["id"]), (TO_CLIENT, "approval", "omh-approval-p1"))

    def test_close_detaches_this_connections_view_and_nothing_without_one(self) -> None:
        adapter = self.adapter()
        self.assertEqual(adapter.from_client(_call(5, "session.close", {"session_id": SID})),
                         [(TO_CLIENT, _answer(5, {}))])
        self.opened(adapter)
        [(_, detach)] = adapter.from_client(_call(6, "session.close", {"session_id": SID}))
        self.assertEqual((detach["method"], detach["params"]), ("session.detach", {
            "session_id": SID, "subscription_id": "sub-1", "end_reason": attach.CLOSE_END_REASON}))
        [(_, answer)] = adapter.from_owner(_answer(6, {"session_id": SID, "subscription_id": "sub-1", "detached": True}))
        self.assertEqual(answer, _answer(6, {}))
        self.assertNotIn(SID, adapter.sessions)

    def test_a_closed_session_withdraws_its_open_prompts(self) -> None:
        # Detached, the owner sends this connection no `.settled` for that session: a prompt left open here would
        # wait behind the next session's, and a decline sent for it would stop that session's turn.
        prompt = {"prompt_id": "p1", "execution_generation": 3, "command": "rm -rf x", "choices": ["once", "deny"]}
        adapter = self.adapter()
        self.opened(adapter)
        adapter.from_owner(_event("approval.request", prompt))
        adapter.from_owner(_event("approval.request", {**prompt, "prompt_id": "q1"}, session_id="local-other"))
        adapter.from_client(_call(6, "session.close", {"session_id": SID}))
        actions = adapter.from_owner(_answer(6, {"session_id": SID, "subscription_id": "sub-1", "detached": True}))
        self.assertEqual(actions, [
            (TO_CLIENT, _event("request.cancel", {"id": "omh-approval-p1", "request_ids": ["omh-approval-p1"]})),
            (TO_CLIENT, _answer(6, {})),
        ])
        self.assertEqual(list(adapter.shown), ["omh-approval-q1"])  # another session's question stays
        # A session this connection holds no view of is left at once, its prompts with it.
        actions = adapter.from_client(_call(7, "session.close", {"session_id": "local-other"}))
        self.assertEqual(actions[0][1]["params"]["type"], "request.cancel")
        self.assertEqual(actions[-1], (TO_CLIENT, _answer(7, {})))
        self.assertEqual(adapter.shown, {})

    def test_a_late_lifecycle_event_of_an_older_generation_is_dropped(self) -> None:
        # Ink's `fenceLifecycleEvent`: an interrupted turn's late `message.complete` must not end the next turn.
        adapter = self.adapter()
        self.opened(adapter, generation=3, authority_epoch=2)
        newer = _event("message.start", {}, execution_generation=4, authority_epoch=2)
        self.assertEqual(adapter.from_owner(newer), [(TO_CLIENT, newer)])
        self.assertEqual(adapter.from_owner(_event("message.complete", {"text": "late"}, execution_generation=3,
                                                   authority_epoch=2)), [])
        self.assertEqual(adapter.from_owner(_event("error", {"message": "x"}, execution_generation=4,
                                                   authority_epoch=1)), [])  # another owner epoch
        current = _event("message.complete", {"text": "done"}, execution_generation=4, authority_epoch=2)
        self.assertEqual(adapter.from_owner(current), [(TO_CLIENT, current)])
        unstamped = _event("error", {"message": "agent build failed"})
        self.assertEqual(adapter.from_owner(unstamped), [(TO_CLIENT, unstamped)])  # a failure that is no turn's
        delta = _event("message.delta", {"text": "x"}, execution_generation=2)
        self.assertEqual(adapter.from_owner(delta), [(TO_CLIENT, delta)])  # only the lifecycle events are fenced
        self.assertEqual(adapter.sessions[SID].generation, 4)  # an older event never moves it back

    def test_a_usage_frame_is_never_fenced(self) -> None:
        # The info line's context gauge reads `session.usage` (`gateway/session_usage.py::usage_frame`: the nested
        # status-bar view beside the session counters). It is no lifecycle event, so even one stamped with an older
        # generation reaches the TUI whole.
        adapter = self.adapter()
        self.opened(adapter, generation=4, authority_epoch=2)
        nested = {"output": 900, "calls": 3, "context_used": 74_000, "context_max": 200_000, "context_percent": 37}
        usage = _event("session.usage", {"usage": nested, "last_prompt_tokens": 74_000, "context_length": 200_000},
                       execution_generation=3, authority_epoch=2)
        self.assertEqual(adapter.from_owner(usage), [(TO_CLIENT, usage)])

    def test_a_prompt_gets_an_input_id(self) -> None:
        adapter = self.adapter()
        self.opened(adapter)
        [(_, submit)] = adapter.from_client(_call(7, "prompt.submit", {"session_id": SID, "text": "hi", "queued": True}))
        self.assertEqual(submit["params"], {"session_id": SID, "text": "hi", "queued": True, "input_id": "id-2"})

    def test_a_steer_carries_the_running_generation_and_is_rejected_without_one(self) -> None:
        # The send-now key's `session.redirect` as much as the fallback `session.steer`: Hermes bf0203a794's owner
        # takes both as `CanonicalCorrectionParams` (`contracts/canonical_sessions.py`), generation required.
        for method in ("session.redirect", "session.steer"):
            with self.subTest(method=method):
                adapter = self.adapter()
                self.assertEqual(adapter.from_client(_call(8, method, {"session_id": SID, "text": "go"})),
                                 [(TO_CLIENT, _answer(8, {"status": "rejected"}))])
                self.opened(adapter, generation=3)
                adapter.from_owner(_event("message.delta", {"text": "x"}, execution_generation=4))
                [(_, steer)] = adapter.from_client(_call(9, method, {"session_id": SID, "text": "go"}))
                self.assertEqual(steer["method"], method)
                self.assertEqual(steer["params"], {"session_id": SID, "text": "go", "execution_generation": 4})

    def test_an_interrupt_carries_the_generation_of_the_turn_it_stops(self) -> None:
        # Hermes bf0203a794 refuses `session.interrupt` without the running generation (`session_authority.py`
        # `interrupt`: `stale_generation`), so a stop sent as the stdio entry takes it never stopped the turn.
        adapter = self.adapter()
        self.opened(adapter, generation=3)
        adapter.from_owner(_event("message.start", {}, execution_generation=4))
        interrupt = self.own_call(adapter.from_client(_call(9, "session.interrupt", {"session_id": SID})),
                                  "session.interrupt")
        self.assertEqual(interrupt["params"], {"session_id": SID, "execution_generation": 4})
        handle = {"ref": {"session_id": SID}, "execution_generation": 4, "execution_state": "running"}
        self.assertEqual(adapter.from_owner(_answer(interrupt["id"], handle)), [(TO_CLIENT, _answer(9, handle))])
        self.assertFalse(adapter.waiting())

    def test_a_stale_interrupt_is_read_afresh_and_sent_once_more(self) -> None:
        adapter = self.adapter()
        self.opened(adapter, generation=3)
        first = self.own_call(adapter.from_client(_call(9, "session.interrupt", {"session_id": SID})),
                              "session.interrupt")
        read = self.own_call(adapter.from_owner(_error(first["id"], "stale_generation")), "session.resume")
        self.assertEqual(read["params"], {"session_id": SID})
        again = self.own_call(adapter.from_owner(_answer(read["id"], {
            "session_id": SID, "subscription_id": "sub-1", "running": True, "execution_generation": 5})),
            "session.interrupt")
        self.assertEqual(again["params"], {"session_id": SID, "execution_generation": 5})
        self.assertEqual(adapter.sessions[SID].generation, 5)
        # Refused a second time, the stop is the TUI's refusal: one retry, never a loop.
        [(target, refusal)] = adapter.from_owner(_error(again["id"], "stale_generation"))
        self.assertEqual((target, refusal["id"], refusal["error"]["message"]), (TO_CLIENT, 9, "stale_generation"))
        self.assertFalse(adapter.waiting())

    def test_an_interrupt_whose_read_finds_no_turn_running_stops_nothing(self) -> None:
        adapter = self.adapter()
        self.opened(adapter, generation=3)
        first = self.own_call(adapter.from_client(_call(9, "session.interrupt", {"session_id": SID})),
                              "session.interrupt")
        read = self.own_call(adapter.from_owner(_error(first["id"], "stale_generation")), "session.resume")
        actions = adapter.from_owner(_answer(read["id"], {"session_id": SID, "running": False,
                                                          "execution_generation": 4}))
        self.assertEqual(actions, [(TO_CLIENT, _answer(9, {"session_id": SID, "execution_generation": 4,
                                                            "running": False}))])
        # Any other refusal is the TUI's at once, and nothing is read.
        other = self.own_call(adapter.from_client(_call(10, "session.interrupt", {"session_id": SID})),
                              "session.interrupt")
        [(target, refusal)] = adapter.from_owner(_error(other["id"], "forbidden"))
        self.assertEqual((target, refusal["id"]), (TO_CLIENT, 10))

    def test_an_interrupt_with_no_generation_known_reads_one_first(self) -> None:
        adapter = self.adapter()
        read = self.own_call(adapter.from_client(_call(9, "session.interrupt", {"session_id": SID})),
                             "session.resume")
        interrupt = self.own_call(adapter.from_owner(_answer(read["id"], {
            "session_id": SID, "subscription_id": "sub-2", "running": True, "execution_generation": 2})),
            "session.interrupt")
        self.assertEqual(interrupt["params"], {"session_id": SID, "execution_generation": 2})
        [(target, refusal)] = adapter.from_owner(_error(interrupt["id"], "stale_generation"))
        self.assertEqual((target, refusal["id"]), (TO_CLIENT, 9))  # the read was its one retry
        unread = self.own_call(adapter.from_client(_call(10, "session.interrupt", {"session_id": "local-gone"})),
                               "session.resume")
        [(target, refusal)] = adapter.from_owner(_error(unread["id"], "not_found"))
        self.assertEqual((target, refusal["id"], refusal["error"]["code"]), (TO_CLIENT, 10, attach.REFUSED))
        self.assertIn("not_found", refusal["error"]["message"])

    def test_shell_exec_runs_in_the_session_last_opened(self) -> None:
        adapter = self.adapter()
        self.opened(adapter)
        [(_, shell)] = adapter.from_client(_call(10, "shell.exec", {"command": "ls"}))
        self.assertEqual(shell["params"], {"command": "ls", "session_id": SID})

    def test_session_list_is_the_live_listing_then_the_stored_one(self) -> None:
        adapter = self.adapter()
        live = self.own_call(adapter.from_client(_call(11, "session.list", {"limit": 3})), "session.list")
        self.assertEqual(live["params"], {"limit": 3})
        stored = self.own_call(adapter.from_owner(_answer(live["id"], {"sessions": [{"id": "a"}, {"id": "b"}]})),
                               "session.list")
        self.assertEqual(stored["params"], {"limit": 3, "scope": "stored"})
        [(_, answer)] = adapter.from_owner(_answer(stored["id"], {"sessions": [{"id": "b"}, {"id": "c"}, {"id": "d"}]}))
        self.assertEqual(answer, _answer(11, {"sessions": [{"id": "a"}, {"id": "b"}, {"id": "c"}]}))

    def test_a_title_lookup_is_one_call_answered_as_the_owner_answers_it(self) -> None:
        # The owner looks a title up over its whole store, and refuses `title` with a `scope` (invalid_params).
        adapter = self.adapter()
        lookup = self.own_call(adapter.from_client(_call(13, "session.list", {"title": "Release notes"})), "session.list")
        self.assertEqual(lookup["params"], {"title": "Release notes"})
        found = {"sessions": [{"id": "a", "resolved_id": "a", "title": "Release notes"}], "scope": "stored"}
        self.assertEqual(adapter.from_owner(_answer(lookup["id"], found)), [(TO_CLIENT, _answer(13, found))])

    def test_other_calls_and_events_pass_through_unchanged(self) -> None:
        adapter = self.adapter()
        frame = _call(12, "commands.catalog", {"session_id": SID})
        self.assertEqual(adapter.from_client(frame), [(TO_OWNER, frame)])
        reply = _answer(12, {"pairs": []})
        self.assertEqual(adapter.from_owner(reply), [(TO_CLIENT, reply)])
        delta = _event("message.delta", {"text": "x"})
        self.assertEqual(adapter.from_owner(delta), [(TO_CLIENT, delta)])
        sudo = {"jsonrpc": "2.0", "id": "srq-1", "method": "sudo", "params": {"session_id": SID}}
        self.assertEqual(adapter.from_owner(sudo), [(TO_CLIENT, sudo)])
        answer = {"jsonrpc": "2.0", "id": "srq-1", "result": {"value": ""}}
        self.assertEqual(adapter.from_client(answer), [(TO_OWNER, answer)])
        self.assertFalse(adapter.waiting())


class RewindTests(AdapterCase):
    """A rewind is the owner's revision-fenced `session.mutate`, at the revision read just before it."""

    def test_a_truncating_prompt_reads_the_revision_rewinds_and_then_submits(self) -> None:
        adapter = self.adapter()
        self.opened(adapter)
        read = self.own_call(adapter.from_client(_call(13, "prompt.submit", {
            "session_id": SID, "text": "again", "truncate_before_row_id": 41, "confirm_truncate": True})),
            "session.resume")
        self.assertEqual(read["params"], {"session_id": SID})
        mutate = self.own_call(adapter.from_owner(_answer(read["id"], {
            "session_id": SID, "subscription_id": "sub-1", "revision": 9, "execution_generation": 5})),
            "session.mutate")
        self.assertEqual(mutate["params"], {
            "session_id": SID, "request_id": "id-3", "expected_revision": 9, "expected_generation": 5,
            "operation": "rewind", "payload": {"target_message_id": 41}})
        submit = self.own_call(adapter.from_owner(_answer(mutate["id"], {"rewound_count": 2})), "prompt.submit")
        self.assertEqual(submit["params"], {"session_id": SID, "text": "again", "input_id": "id-2"})
        receipt = {"ref": {"session_id": SID}, "execution_generation": 6, "status": "started"}
        [(target, answer)] = adapter.from_owner(_answer(submit["id"], receipt))
        self.assertEqual((target, answer), (TO_CLIENT, _answer(13, receipt)))  # answered as the TUI's own call
        self.assertEqual(adapter.sessions[SID].generation, 6)

    def rewind_with_an_image(self) -> tuple[Adapter, dict]:
        """A session with one staged image, and a rewind sent: the revision read, the cut asked for."""
        adapter = self.adapter()
        self.opened(adapter)
        adapter.sessions[SID].images.append({"path": "/hermes/cache/images/upload_1.png", "mime": "image/png"})
        read = self.own_call(adapter.from_client(_call(15, "prompt.submit", {
            "session_id": SID, "text": "x", "truncate_before_row_id": 3, "confirm_truncate": True})), "session.resume")
        mutate = self.own_call(adapter.from_owner(_answer(read["id"], {"revision": 1, "execution_generation": 1})),
                               "session.mutate")
        return adapter, mutate

    def test_a_refused_cut_keeps_the_queued_images_for_the_next_prompt(self) -> None:
        adapter, mutate = self.rewind_with_an_image()
        adapter.from_owner(_error(mutate["id"], "revision_conflict"))
        [(_, submit)] = adapter.from_client(_call(16, "prompt.submit", {"session_id": SID, "text": "again"}))
        self.assertEqual(submit["params"]["attachments"],
                         [{"path": "/hermes/cache/images/upload_1.png", "mime": "image/png"}])

    def test_a_prompt_refused_after_the_cut_says_the_cut_happened_and_keeps_its_images(self) -> None:
        adapter, mutate = self.rewind_with_an_image()
        submit = self.own_call(adapter.from_owner(_answer(mutate["id"], {"rewound_count": 1})), "prompt.submit")
        self.assertEqual(len(submit["params"]["attachments"]), 1)  # the images go with the prompt once the cut holds
        [(target, refusal)] = adapter.from_owner(_error(submit["id"], "session_busy"))
        self.assertEqual((target, refusal["id"]), (TO_CLIENT, 15))
        self.assertEqual(refusal["error"]["data"], {"rewound": True})
        self.assertIn("session_busy", refusal["error"]["message"])
        self.assertEqual(adapter.sessions[SID].images,
                         [{"path": "/hermes/cache/images/upload_1.png", "mime": "image/png"}])

    def test_a_refused_rewind_is_a_refusal_the_tui_keeps_its_session_through(self) -> None:
        adapter = self.adapter()
        self.opened(adapter)
        read = self.own_call(adapter.from_client(_call(14, "prompt.submit", {
            "session_id": SID, "text": "x", "truncate_before_row_id": 3, "confirm_truncate": True})), "session.resume")
        mutate = self.own_call(adapter.from_owner(_answer(read["id"], {"revision": 1, "execution_generation": 1})),
                               "session.mutate")
        [(target, refusal)] = adapter.from_owner(_error(mutate["id"], "invalid_params", "target user message is gone"))
        self.assertEqual((target, refusal["id"]), (TO_CLIENT, 14))
        self.assertEqual(refusal["error"]["code"], attach.REFUSED)
        self.assertNotIn(refusal["error"]["code"], (attach.PARAM_REJECTED, -32601))
        self.assertIn("target user message is gone", refusal["error"]["message"])


class ModelSwitchTests(AdapterCase):
    """`config.set model` is the owner's `session.mutate model` (Ink's `/model` on a shared gateway), answered as the
    stdio entry answers it."""

    def switch(self, value: str = "claude-opus-5-5 --provider claude-proxy --session") -> tuple[Adapter, dict]:
        adapter = self.adapter()
        self.opened(adapter)
        read = self.own_call(adapter.from_client(_call(21, "config.set", {
            "key": "model", "value": value, "session_id": SID})), "session.resume")
        self.assertEqual(read["params"], {"session_id": SID})
        mutate = self.own_call(adapter.from_owner(_answer(read["id"], {
            "session_id": SID, "subscription_id": "sub-1", "revision": 9, "execution_generation": 5})),
            "session.mutate")
        return adapter, mutate

    def test_a_switch_reads_the_revision_and_mutates_the_model_with_its_provider(self) -> None:
        adapter, mutate = self.switch()
        self.assertEqual(mutate["params"], {
            "session_id": SID, "request_id": "id-2", "expected_revision": 9, "expected_generation": 5,
            "operation": "model", "payload": {"model": "claude-opus-5-5", "provider": "claude-proxy"}})
        [(target, answer)] = adapter.from_owner(_answer(mutate["id"], {
            "session_id": SID, "operation": "model", "model": "claude-opus-5-5", "execution_generation": 6}))
        self.assertEqual((target, answer), (TO_CLIENT, _answer(21, {
            "key": "model", "value": "claude-opus-5-5", "scope": "session", "deferred": False})))
        self.assertEqual(adapter.sessions[SID].generation, 6)
        self.assertFalse(adapter.waiting())

    def test_a_pick_while_a_turn_runs_is_deferred_and_a_guarded_one_is_not_made(self) -> None:
        adapter, mutate = self.switch("claude-opus-5-5 --session")
        self.assertEqual(mutate["params"]["payload"], {"model": "claude-opus-5-5"})
        [(_, answer)] = adapter.from_owner(_answer(mutate["id"], {"status": "deferred", "model": "claude-opus-5-5"}))
        self.assertEqual(answer["result"]["deferred"], True)
        adapter, mutate = self.switch()
        [(_, answer)] = adapter.from_owner(_answer(mutate["id"], {
            "status": "confirmation_required", "confirm_required": True, "confirm": "token",
            "confirm_message": "Opus costs 5x.", "target_model": "claude-opus-5-5"}))
        self.assertEqual(answer["result"], {
            "key": "model", "value": "", "confirm_required": True, "confirm_message": "Opus costs 5x."})

    def test_switch_anyway_carries_the_owners_token_once(self) -> None:
        adapter, mutate = self.switch()
        adapter.from_owner(_answer(mutate["id"], {
            "status": "confirmation_required", "confirm_required": True, "confirm": "tok-1", "confirm_message": "x"}))
        value = "claude-opus-5-5 --provider claude-proxy --session"
        read = self.own_call(adapter.from_client(_call(24, "config.set", {
            "key": "model", "value": value, "session_id": SID, "confirm_expensive_model": True})), "session.resume")
        again = self.own_call(adapter.from_owner(_answer(read["id"], {"revision": 9, "execution_generation": 5})),
                              "session.mutate")
        self.assertEqual(again["params"]["payload"],
                         {"model": "claude-opus-5-5", "provider": "claude-proxy", "confirm": "tok-1"})
        read = self.own_call(adapter.from_client(_call(25, "config.set", {
            "key": "model", "value": value, "session_id": SID, "confirm_expensive_model": True})), "session.resume")
        third = self.own_call(adapter.from_owner(_answer(read["id"], {"revision": 9, "execution_generation": 5})),
                              "session.mutate")
        self.assertNotIn("confirm", third["params"]["payload"])  # used once: the owner then asks again

    def test_a_refusal_is_the_owners_own_with_its_reason(self) -> None:
        adapter, mutate = self.switch()
        [(target, refusal)] = adapter.from_owner(_error(mutate["id"], "model_resolution_failed"))
        self.assertEqual((target, refusal["id"]), (TO_CLIENT, 21))
        self.assertEqual(refusal["error"]["data"]["reason"], "model_resolution_failed")

    def test_a_flag_the_owner_does_not_take_is_refused_before_anything_is_sent(self) -> None:
        adapter = self.adapter()
        self.opened(adapter)
        for value in ("x --global", "x --once", "x --refresh", "--provider p", "x --provider"):
            with self.subTest(value=value):
                [(target, refusal)] = adapter.from_client(_call(22, "config.set", {
                    "key": "model", "value": value, "session_id": SID}))
                self.assertEqual((target, refusal["error"]["data"]["reason"]), (TO_CLIENT, "unsupported_model_options"))
        self.assertFalse(adapter.waiting())
        self.assertEqual(attach.model_payload("x --tui-session --reasoning HIGH"), {"model": "x", "reasoning": "high"})

    def test_any_other_config_set_passes_through(self) -> None:
        adapter = self.adapter()
        frame = _call(23, "config.set", {"key": "yolo", "value": "on", "session_id": SID})
        self.assertEqual(adapter.from_client(frame), [(TO_OWNER, frame)])
        self.assertFalse(adapter.waiting())


class SharedPromptTests(AdapterCase):
    """An approval or clarify the owner asks as an event is the server request the stdio entry sent."""

    APPROVAL = {"kind": "approval", "prompt_id": "p7", "execution_generation": 4, "command": "rm -rf /tmp/x",
                "description": "recursive delete", "choices": ["once", "deny", "session", "always"]}

    def test_an_approval_event_is_a_request_and_its_answer_is_approval_respond(self) -> None:
        adapter = self.adapter()
        self.opened(adapter)
        [(target, request)] = adapter.from_owner(_event("approval.request", self.APPROVAL, execution_generation=4))
        self.assertEqual(target, TO_CLIENT)
        self.assertEqual(request, {"jsonrpc": "2.0", "id": "omh-approval-p7", "method": "approval", "params": {
            "session_id": SID, "request_id": "p7", "command": "rm -rf /tmp/x", "description": "recursive delete",
            "choices": ["once", "deny", "session", "always"]}})
        self.assertEqual(adapter.from_owner(_event("approval.request", self.APPROVAL)), [])  # asked once
        respond = self.own_call(adapter.from_client(_answer("omh-approval-p7", {"choice": "deny"})), "approval.respond")
        self.assertEqual(respond["params"], {"session_id": SID, "execution_generation": 4, "prompt_id": "p7",
                                             "choice": "deny"})
        self.assertEqual(adapter.from_owner(_answer(respond["id"], {"status": "resolved"})), [])
        self.assertEqual(adapter.from_owner(_event("approval.settled", {"prompt_id": "p7"})), [])  # already answered

    def test_a_choice_the_owner_does_not_have_is_sent_as_deny(self) -> None:
        adapter = self.adapter()
        adapter.from_owner(_event("approval.request", self.APPROVAL))
        respond = self.own_call(adapter.from_client(_answer("omh-approval-p7", {"choice": "maybe"})), "approval.respond")
        self.assertEqual(respond["params"]["choice"], "deny")

    def test_a_settled_prompt_still_open_is_withdrawn(self) -> None:
        adapter = self.adapter()
        adapter.from_owner(_event("approval.request", self.APPROVAL))
        [(target, cancel)] = adapter.from_owner(_event("approval.settled", {"prompt_id": "p7", "execution_generation": 4}))
        self.assertEqual(target, TO_CLIENT)
        self.assertEqual(cancel, _event("request.cancel", {"id": "omh-approval-p7", "request_ids": ["omh-approval-p7"]}))
        self.assertEqual(adapter.from_client(_answer("omh-approval-p7", {"choice": "once"})),
                         [(TO_OWNER, _answer("omh-approval-p7", {"choice": "once"}))])  # no longer a shared prompt

    def test_a_clarify_event_is_one_question_and_its_answer_or_cancel_is_clarify_respond(self) -> None:
        adapter = self.adapter()
        prompt = {"kind": "clarify", "prompt_id": "c1", "execution_generation": 2, "question": "Which?",
                  "choices": ["a", "b"], "multi_select": False}
        [(_, request)] = adapter.from_owner(_event("clarify.request", prompt))
        self.assertEqual(request["params"], {"session_id": SID, "questions": [
            {"qid": "c1", "question": "Which?", "choices": ["a", "b"], "multi_select": False}]})
        respond = self.own_call(adapter.from_client(_answer("omh-clarify-c1", {"answers": {"c1": "b"}})),
                                "clarify.respond")
        self.assertEqual(respond["params"], {"session_id": SID, "execution_generation": 2, "prompt_id": "c1",
                                             "answer": "b"})
        adapter.from_owner(_event("clarify.request", {**prompt, "prompt_id": "c2"}))
        cancel = self.own_call(adapter.from_client(_answer("omh-clarify-c2", {})), "clarify.respond")
        self.assertEqual(cancel["params"]["answer"], "")  # the owner's skip

    def test_an_answer_the_owner_refuses_is_a_visible_notice(self) -> None:
        adapter = self.adapter()
        adapter.from_owner(_event("approval.request", self.APPROVAL))
        respond = self.own_call(adapter.from_client(_answer("omh-approval-p7", {"choice": "once"})), "approval.respond")
        [(target, notice)] = adapter.from_owner(_error(respond["id"], "stale_generation"))
        self.assertEqual((target, notice["params"]["type"], notice["params"]["session_id"]),
                         (TO_CLIENT, "notification.show", SID))
        self.assertIn("stale_generation", notice["params"]["payload"]["text"])
        self.assertEqual(notice["params"]["payload"]["level"], "error")


class ImageTests(AdapterCase):
    """Images are staged with the owner's `image.attach_bytes` and ride the session's next prompt."""

    IMAGE = LocalImage(Path("/work/shot.png"), "what is this?", PNG, "image/png")

    def stage(self, adapter: Adapter, actions: list, staged: str = "/hermes/cache/images/upload_1.png") -> dict:
        call = self.own_call(actions, "image.attach_bytes")
        self.assertEqual(call["params"], {"session_id": SID, "filename": "shot.png",
                                          "content_base64": base64.b64encode(PNG).decode("ascii")})
        [(target, answer)] = adapter.from_owner(_answer(call["id"], {"attached": True, "path": staged,
                                                                     "mime": "image/png"}))
        self.assertEqual(target, TO_CLIENT)
        return answer

    def test_an_attached_image_is_staged_queued_and_sent_with_the_next_prompt(self) -> None:
        adapter = self.adapter(files=FakeFiles({"shot.png what is this?": self.IMAGE}))
        self.opened(adapter)
        answer = self.stage(adapter, adapter.from_client(_call(20, "image.attach", {
            "session_id": SID, "path": "shot.png what is this?"})))
        self.assertEqual(answer, _answer(20, {"attached": True, "remainder": "what is this?", "text": "what is this?",
                                              "path": "/hermes/cache/images/upload_1.png", "name": "shot.png",
                                              "count": 1}))
        [(_, submit)] = adapter.from_client(_call(21, "prompt.submit", {"session_id": SID, "text": "what is this?"}))
        self.assertEqual(submit["params"]["attachments"],
                         [{"path": "/hermes/cache/images/upload_1.png", "mime": "image/png"}])
        [(_, submit)] = adapter.from_client(_call(22, "prompt.submit", {"session_id": SID, "text": "next"}))
        self.assertNotIn("attachments", submit["params"])  # sent once, with the turn it was queued for

    def test_a_relative_image_path_is_read_against_the_sessions_workspace(self) -> None:
        files = FakeFiles({"shot.png": self.IMAGE})
        adapter = Adapter({}, files=files, new_id=_ids(), cwd="/launch")
        [(_, describe)] = adapter.describe()
        adapter.from_owner(_answer(describe["id"], {"session_create": CONTRACT}))
        adapter.from_client(_call(30, "image.attach", {"session_id": "local-unknown", "path": "shot.png"}))
        self.opened(adapter, info={"cwd": "/work/project"})
        adapter.from_client(_call(31, "image.attach", {"session_id": SID, "path": "shot.png"}))
        self.assertEqual(files.cwds, ["/launch", "/work/project"])

    def test_hermes_path_helper_reads_against_the_workspace_and_leaves_the_environment_as_it_was(self) -> None:
        seen: list[str | None] = []

        def resolve(raw: str) -> Path | None:
            seen.append(os.environ.get("TERMINAL_CWD"))
            return None

        helper = types.ModuleType("hermes_cli.cli_terminal_input")
        helper._resolve_attachment_path = resolve  # type: ignore[attr-defined]
        helper._split_path_input = lambda raw: (raw, "")  # type: ignore[attr-defined]
        modules = {"hermes_cli": types.ModuleType("hermes_cli"), "hermes_cli.cli_terminal_input": helper}
        with patch_modules(modules), patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TERMINAL_CWD", None)
            with self.assertRaises(ValueError):
                attach.HermesFiles().image("shot.png", "/work/project")
            self.assertNotIn("TERMINAL_CWD", os.environ)
        self.assertEqual(seen, ["/work/project", "/work/project"])

    def test_a_detached_image_leaves_the_queue(self) -> None:
        adapter = self.adapter(files=FakeFiles({"shot.png": self.IMAGE}))
        self.opened(adapter)
        self.stage(adapter, adapter.from_client(_call(23, "image.attach", {"session_id": SID, "path": "shot.png"})))
        [(_, answer)] = adapter.from_client(_call(24, "image.detach", {
            "session_id": SID, "path": "/hermes/cache/images/upload_1.png"}))
        self.assertEqual(answer, _answer(24, {"detached": True, "count": 0}))
        [(_, submit)] = adapter.from_client(_call(25, "prompt.submit", {"session_id": SID, "text": "x"}))
        self.assertNotIn("attachments", submit["params"])

    def test_the_bytes_the_tui_keeps_are_staged_queued_and_detached_by_the_path_answered(self) -> None:
        adapter = self.adapter()
        self.opened(adapter)
        sent = {"session_id": SID, "filename": "shot.png", "content_base64": base64.b64encode(PNG).decode("ascii")}
        answer = self.stage(adapter, adapter.from_client(_call(40, "image.attach_bytes", sent)))
        self.assertEqual(answer, _answer(40, {"attached": True, "path": "/hermes/cache/images/upload_1.png",
                                              "name": "shot.png", "count": 1}))
        [(_, submit)] = adapter.from_client(_call(41, "prompt.submit", {"session_id": SID, "text": "x"}))
        self.assertEqual(submit["params"]["attachments"],
                         [{"path": "/hermes/cache/images/upload_1.png", "mime": "image/png"}])
        self.stage(adapter, adapter.from_client(_call(42, "image.attach_bytes", sent)),
                   staged="/hermes/cache/images/upload_2.png")
        [(_, answer)] = adapter.from_client(_call(43, "image.detach", {
            "session_id": SID, "path": "/hermes/cache/images/upload_2.png"}))
        self.assertEqual(answer, _answer(43, {"detached": True, "count": 0}))
        [(_, submit)] = adapter.from_client(_call(44, "prompt.submit", {"session_id": SID, "text": "y"}))
        self.assertNotIn("attachments", submit["params"])

    def test_a_staged_path_with_no_mime_answered_is_typed_by_the_suffix_the_owner_gave_it(self) -> None:
        adapter = self.adapter()
        self.opened(adapter)
        sent = {"session_id": SID, "filename": "photo.jpg", "content_base64": base64.b64encode(PNG).decode("ascii")}
        call = self.own_call(adapter.from_client(_call(48, "image.attach_bytes", sent)), "image.attach_bytes")
        adapter.from_owner(_answer(call["id"], {"attached": True, "path": "/hermes/cache/images/upload_3.jpg"}))
        [(_, submit)] = adapter.from_client(_call(49, "prompt.submit", {"session_id": SID, "text": "x"}))
        self.assertEqual(submit["params"]["attachments"], [{"path": "/hermes/cache/images/upload_3.jpg",
                                                            "mime": "image/jpeg"}])

    def test_empty_bytes_are_refused_and_bytes_the_owner_refuses_say_why(self) -> None:
        adapter = self.adapter()
        self.opened(adapter)
        [(target, refusal)] = adapter.from_client(_call(45, "image.attach_bytes", {
            "session_id": SID, "filename": "x.png", "content_base64": ""}))
        self.assertEqual((target, refusal["error"]["code"]), (TO_CLIENT, attach.NOT_FOUND))
        call = self.own_call(adapter.from_client(_call(46, "image.attach_bytes", {
            "session_id": SID, "filename": "x.png", "content_base64": "bm90IGFuIGltYWdl"})), "image.attach_bytes")
        self.assertEqual(call["params"]["content_base64"], "bm90IGFuIGltYWdl")  # as the TUI sent it
        [(target, refusal)] = adapter.from_owner(_error(call["id"], "unsupported image extension"))
        self.assertEqual((target, refusal["error"]["code"]), (TO_CLIENT, attach.REFUSED))
        [(_, submit)] = adapter.from_client(_call(47, "prompt.submit", {"session_id": SID, "text": "x"}))
        self.assertNotIn("attachments", submit["params"])

    def test_an_image_not_found_is_refused_with_its_reason(self) -> None:
        adapter = self.adapter()
        self.opened(adapter)
        [(target, refusal)] = adapter.from_client(_call(26, "image.attach", {"session_id": SID, "path": "nope.png"}))
        self.assertEqual((target, refusal["error"]["code"]), (TO_CLIENT, attach.NOT_FOUND))
        self.assertIn("nope.png", refusal["error"]["message"])

    def test_a_dropped_image_is_staged_and_any_other_drop_is_no_drop(self) -> None:
        adapter = self.adapter(files=FakeFiles({"/work/shot.png": self.IMAGE}))
        self.opened(adapter)
        answer = self.stage(adapter, adapter.from_client(_call(27, "input.detect_drop", {
            "session_id": SID, "text": "/work/shot.png"})))
        self.assertEqual(answer["result"]["matched"], True)
        self.assertEqual(answer["result"]["is_image"], True)
        self.assertEqual(adapter.from_client(_call(28, "input.detect_drop", {"session_id": SID, "text": "hello"})),
                         [(TO_CLIENT, _answer(28, {"matched": False}))])

    def test_a_pasted_clipboard_image_is_queued_where_hermes_saved_it(self) -> None:
        saved = (Path("/hermes/cache/images/clip_1.png"), "image/png")
        adapter = self.adapter(files=FakeFiles(clipboard=saved))
        self.opened(adapter)
        [(_, answer)] = adapter.from_client(_call(29, "clipboard.paste", {"session_id": SID}))
        # The owner reads the path as a path on its own filesystem (`Path(item['path'])`), so it is the native one.
        self.assertEqual(answer["result"], {"attached": True, "path": str(saved[0]), "name": "clip_1.png", "count": 1})
        [(_, empty)] = self.adapter().from_client(_call(30, "clipboard.paste", {"session_id": SID}))
        self.assertIn("error", empty)  # no view of that session on this connection
        adapter = self.adapter()
        self.opened(adapter)
        [(_, empty)] = adapter.from_client(_call(31, "clipboard.paste", {"session_id": SID}))
        self.assertEqual(empty["result"], {"attached": False, "message": "No image found in clipboard"})

    def test_image_types_are_the_ones_the_owner_admits(self) -> None:
        self.assertEqual(attach.image_mime(PNG), "image/png")
        self.assertEqual(attach.image_mime(b"\xff\xd8\xff\xe0"), "image/jpeg")
        self.assertEqual(attach.image_mime(b"GIF89a.."), "image/gif")
        self.assertEqual(attach.image_mime(b"RIFF\0\0\0\0WEBPVP8 "), "image/webp")
        self.assertIsNone(attach.image_mime(b"BM\0\0"))  # a bitmap: the owner refuses it


SLASH_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tui_gateway" / "canonical_slash_verbs.json"
UNSUPPORTED = {"code": 4001, "message": "unsupported_command", "data": {"reason": "unsupported_command"}}


class SlashVerbTests(AdapterCase):
    """A command the owner's `slash.exec` refuses on a shared gateway (`unsupported_command`) and serves through a verb
    of its own (Ink's way on a shared gateway) is answered through that verb, in `slash.exec`'s shape."""

    def refused(self, adapter: Adapter, command: str) -> dict:
        """`command` sent and the owner's `slash.exec` refusal answered: the child's next frame, with `to_client` set
        when it answers the TUI rather than calling the owner."""
        sent = self.own_call(adapter.from_client(_call(50, "slash.exec", {"command": command, "session_id": SID})),
                             "slash.exec")
        self.assertEqual(sent["params"], {"command": command, "session_id": SID})
        [(target, frame)] = adapter.from_owner({"jsonrpc": "2.0", "id": sent["id"], "error": UNSUPPORTED})
        return frame if target == TO_OWNER else {"to_client": frame}

    def answered(self, adapter: Adapter, frame: dict, result: dict) -> dict:
        [(target, answer)] = adapter.from_owner(_answer(frame["id"], result))
        self.assertEqual((target, answer["id"]), (TO_CLIENT, 50))
        self.assertFalse(adapter.waiting())
        return answer["result"]

    def read(self, adapter: Adapter, frame: dict, rows: list[dict], *, running: bool = False) -> dict:
        """The owner's `session.resume` answered: the child's next frame, as `refused` gives it."""
        self.assertEqual((frame["method"], frame["params"]), ("session.resume", {"session_id": SID}))
        [(target, frame)] = adapter.from_owner(_answer(frame["id"], {
            "session_id": SID, "subscription_id": "sub-1", "revision": 9, "execution_generation": 5,
            "running": running, "messages": rows}))
        return frame if target == TO_OWNER else {"to_client": frame}

    @staticmethod
    def rows(*contents: object) -> list[dict]:
        """A transcript of one turn per content: the person's row, then the reply's."""
        rows: list[dict] = []
        for number, content in enumerate(contents):
            rows += [{"role": "user", "row_id": 10 * number + 1, "content": content},
                     {"role": "assistant", "row_id": 10 * number + 2, "content": "ok"}]
        return rows

    def test_the_recorded_shared_gateway_answers_each_command_as_recorded(self) -> None:
        # Recorded from a real Hermes bf0203a794 (v0.22.5) shared gateway through this child: each owner call the
        # child made is replayed with the owner's own answer. The child must make the same calls with the same
        # parameters (the owner took each one) and give the TUI the same answer.
        fixture = json.loads(SLASH_FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(fixture["fixture"]["hermes"], "bf0203a794 (v0.22.5)")
        for scenario in fixture["scenarios"]:
            with self.subTest(command=scenario["command"]):
                adapter = self.adapter()
                session = scenario["owner"][0]["params"]["session_id"]
                actions = adapter.from_client(_call(60, "slash.exec", {"command": scenario["command"],
                                                                        "session_id": session}))
                for step in scenario["owner"]:
                    [(target, frame)] = actions
                    self.assertEqual(target, TO_OWNER)
                    params = dict(frame["params"])
                    if frame["method"] == "session.mutate":
                        params["request_id"] = "<request_id>"
                    self.assertEqual((frame["method"], params), (step["method"], step["params"]))
                    actions = adapter.from_owner({"jsonrpc": "2.0", "id": frame["id"], **step["reply"]})
                [(target, answer)] = actions
                self.assertEqual((target, answer["id"]), (TO_CLIENT, 60))
                self.assertEqual({key: answer[key] for key in ("result", "error") if key in answer}, scenario["answer"])
                self.assertFalse(adapter.waiting())
        verbs = {attach.SLASH_VERBS.get(scenario["command"].split()[0]) for scenario in fixture["scenarios"]}
        self.assertEqual(set(attach.SLASH_VERBS.values()) - verbs, {"tools"})  # its listing is too long to keep

    def test_any_other_command_goes_as_sent_and_is_not_translated(self) -> None:
        adapter = self.adapter()
        for command in ("status", "usage", "goal ship it", "/compressor", ""):
            with self.subTest(command=command):
                frame = _call(51, "slash.exec", {"command": command, "session_id": SID})
                self.assertEqual(adapter.from_client(frame), [(TO_OWNER, frame)])
                self.assertFalse(adapter.waiting())

    def test_an_owner_that_runs_the_command_itself_answers_it_and_nothing_else_is_sent(self) -> None:
        for reply in ({"result": {"type": "exec", "output": "Compressed."}},
                      {"error": {"code": 4001, "message": "session_busy", "data": {"reason": "session_busy"}}}):
            with self.subTest(reply=reply):
                adapter = self.adapter()
                sent = self.own_call(adapter.from_client(_call(52, "slash.exec", {
                    "command": "Compact", "session_id": SID})), "slash.exec")
                [(target, answer)] = adapter.from_owner({"jsonrpc": "2.0", "id": sent["id"], **reply})
                self.assertEqual((target, answer), (TO_CLIENT, {"jsonrpc": "2.0", "id": 52, **reply}))
                self.assertFalse(adapter.waiting())

    def test_compress_sends_its_argument_raw_and_reports_a_noop_without_a_tick(self) -> None:
        adapter = self.adapter()
        mutate = self.read(adapter, self.refused(adapter, "compact here 3"), [])
        self.assertEqual(mutate["params"], {
            "session_id": SID, "request_id": "id-1", "expected_revision": 9, "expected_generation": 5,
            "operation": "compress", "payload": {"focus": "here 3"}})
        result = self.answered(adapter, mutate, {"status": "noop", "summary": {
            "headline": "No changes from compression: 6 messages", "token_line": "Approx request size: ~9 tokens"}})
        self.assertEqual(result, {"type": "exec", "output":
                                  "No changes from compression: 6 messages\n  Approx request size: ~9 tokens"})
        adapter = self.adapter()
        mutate = self.read(adapter, self.refused(adapter, "compress"), [])
        self.assertEqual(mutate["params"]["payload"], {})

    def test_undo_n_rewinds_to_the_nth_newest_turn_of_yours_and_prefills_it(self) -> None:
        adapter = self.adapter()
        rows = [*self.rows("one", "two", "three"), {"role": "user", "row_id": 40, "content": "[CONTEXT SUMMARY]: x"},
                {"role": "user", "row_id": 41, "content": "shown", "display_kind": "notice"},
                {"role": "user", "row_id": 42, "content": "gone", "archived": True}]
        mutate = self.read(adapter, self.refused(adapter, "undo 2"), rows)
        self.assertEqual((mutate["params"]["operation"], mutate["params"]["payload"]),
                         ("rewind", {"target_message_id": 11}))
        result = self.answered(adapter, mutate, {"rewound_count": 4, "target_message": {"content": "two"}})
        self.assertEqual(result, {"type": "prefill", "message": "two", "notice":
                                  "↶ Undid 2 turns (4 messages). Edit and resubmit, or send a new message."})

    def test_a_turn_back_with_nothing_to_take_or_a_bad_count_edits_nothing(self) -> None:
        image_turn = [{"type": "input_image", "image_url": "data:"}, {"type": "text", "text": "x"}]
        for command, rows, said in (("undo", [], "Nothing to undo"), ("undo x", None, "/undo takes a number"),
                                    ("retry", self.rows(image_turn), "/retry cannot send that turn again")):
            with self.subTest(command=command):
                adapter = self.adapter()
                frame = self.refused(adapter, command)
                if rows is not None:
                    frame = self.read(adapter, frame, rows)
                self.assertIn(said, frame["to_client"]["result"]["output"])
                self.assertFalse(adapter.waiting())

    def test_retry_sends_the_turn_it_took_back_again(self) -> None:
        adapter = self.adapter()
        mutate = self.read(adapter, self.refused(adapter, "retry"), self.rows("one", "two"))
        self.assertEqual(mutate["params"]["payload"], {"target_message_id": 11})
        result = self.answered(adapter, mutate, {"rewound_count": 2, "target_message": {"content": [
            {"type": "input_text", "text": "two"}]}})
        self.assertEqual(result, {"type": "send", "message": "two"})

    def test_retry_text_is_only_what_has_a_text_replay(self) -> None:
        self.assertEqual(attach.retry_text("again"), "again")
        self.assertEqual(attach.retry_text([{"type": "text", "text": "a"}, "b"]), "ab")
        self.assertEqual(attach.retry_text("   "), "")
        for content in ([{"type": "input_image", "image_url": "x"}], [{"type": "text", "text": "a", "cache": 1}], None):
            with self.subTest(content=content):
                self.assertIsNone(attach.retry_text(content))

    def test_branch_names_the_new_session_for_the_tui_to_open(self) -> None:
        adapter = self.adapter()
        mutate = self.read(adapter, self.refused(adapter, "fork side quest"), [])
        self.assertEqual(mutate["params"]["payload"], {"title": "side quest"})
        result = self.answered(adapter, mutate, {"operation": "branch", "branched_session_id": "local-child"})
        self.assertEqual(result["branched_session_id"], "local-child")

    def test_an_idle_stop_stops_the_sessions_processes_and_interrupts_nothing(self) -> None:
        adapter = self.adapter()
        stop = self.read(adapter, self.refused(adapter, "stop"), [])
        self.assertEqual((stop["method"], stop["params"]), ("process.stop", {"session_id": SID}))
        result = self.answered(adapter, stop, {"killed": 1, "delegations": 2})
        self.assertEqual(result["output"], "Stopped 1 background process.\nInterrupted 2 background delegations.")

    def test_a_stop_whose_interrupt_found_the_turn_settled_says_it_interrupted_nothing(self) -> None:
        for reply, said in (({"execution_state": "idle", "execution_generation": 5}, False),
                            ({"execution_state": "running", "execution_generation": 6}, False),
                            ({"execution_state": "running", "execution_generation": 5}, True)):
            with self.subTest(reply=reply):
                adapter = self.adapter()
                interrupt = self.read(adapter, self.refused(adapter, "stop"), [], running=True)
                self.assertEqual((interrupt["method"], interrupt["params"]),
                                 ("session.interrupt", {"session_id": SID, "execution_generation": 5}))
                [(_, stop)] = adapter.from_owner(_answer(interrupt["id"], reply))
                output = self.answered(adapter, stop, {"killed": 0, "delegations": 0})["output"]
                self.assertEqual(output.startswith("Interrupted the running turn."), said)

    def test_a_stop_whose_read_failed_still_stops_the_sessions_processes(self) -> None:
        adapter = self.adapter()
        read = self.refused(adapter, "stop")
        [(target, stop)] = adapter.from_owner({"jsonrpc": "2.0", "id": read["id"],
                                               "error": {"code": 4001, "message": "not_found"}})
        self.assertEqual((target, stop["method"], stop["params"]), (TO_OWNER, "process.stop", {"session_id": SID}))
        self.assertEqual(self.answered(adapter, stop, {"killed": 2})["output"], "Stopped 2 background processes.")

    def test_bg_and_btw_start_a_side_agent_and_bare_say_how(self) -> None:
        for command, method in (("background run the tests", "prompt.background"), ("btw why?", "prompt.btw")):
            with self.subTest(command=command):
                adapter = self.adapter()
                frame = self.refused(adapter, command)
                self.assertEqual((frame["method"], frame["params"]),
                                 (method, {"session_id": SID, "text": command.split(None, 1)[1]}))
                self.assertIn("t_1", self.answered(adapter, frame, {"task_id": "t_1"})["output"])
        adapter = self.adapter()
        usage = self.refused(adapter, "bg")["to_client"]
        self.assertTrue(usage["result"]["output"].startswith("usage: /bg <prompt>"))
        self.assertFalse(adapter.waiting())

    def test_rollback_restore_takes_a_file_or_all_and_reports_what_it_kept(self) -> None:
        for command, params in (("rollback 2 src/app.py", {"hash": "2", "file_path": "src/app.py"}),
                                ("rollback 2 --all", {"hash": "2", "all": True}),
                                # Ink and Hermes: `--all` only widens a whole-tree restore; with a file it is no path.
                                ("rollback 2 src/app.py --all", {"hash": "2", "file_path": "src/app.py"}),
                                ("rollback abc123", {"hash": "abc123"})):
            with self.subTest(command=command):
                adapter = self.adapter()
                frame = self.refused(adapter, command)
                self.assertEqual((frame["method"], frame["params"]),
                                 ("rollback.restore", {"session_id": SID, **params}))
        result = self.answered(adapter, frame, {"success": True, "restored_to": "abc123",
                                                "skipped_user_edits": [f"f{n}" for n in range(7)],
                                                "history_removed": 2})
        self.assertEqual(result["output"].splitlines(), [
            "↶ Restored the workspace: abc123", "Kept your own edits to f0, f1, f2, f3, f4 and 2 more.",
            "The last turn went with it (2 messages)."])
        adapter = self.adapter()
        listed = self.answered(adapter, self.refused(adapter, "rollback ls"), {"enabled": True, "checkpoints": [
            {"hash": "0123456789abcdef", "timestamp": "2026-10-28 09:00", "message": "before edit"}]})
        self.assertEqual(listed["output"].splitlines()[0], "1. 0123456789  2026-10-28 09:00 · before edit")

    def test_reload_mcp_reloads_only_when_confirmed(self) -> None:
        for command, params in (("reload-mcp", {"session_id": SID}),
                                ("reload_mcp now", {"session_id": SID, "confirm": True})):
            with self.subTest(command=command):
                adapter = self.adapter()
                frame = self.refused(adapter, command)
                self.assertEqual((frame["method"], frame["params"]), ("reload.mcp", params))

    def test_tools_lists_this_sessions_tools_and_refuses_a_change_in_words(self) -> None:
        adapter = self.adapter()
        frame = self.refused(adapter, "tools")
        self.assertEqual((frame["method"], frame["params"]), ("tools.show", {"session_id": SID}))
        # The shape of Hermes bf0203a794's `tools.show` (`gateway/session_ancillary.py` show_tools).
        result = self.answered(adapter, frame, {"total": 2, "sections": [
            {"name": "file", "tools": [{"name": "read_file", "description": "Read a file."}]},
            {"name": "empty", "tools": []},
            {"name": "web", "tools": [{"name": "web_search", "description": ""}]}]})
        self.assertEqual(result["output"], "[file]\n  read_file - Read a file.\n[web]\n  web_search\nTotal: 2 tools")
        adapter = self.adapter()
        said = self.refused(adapter, "tools disable web")["to_client"]
        self.assertIn("cannot change this session's tools", said["result"]["output"])
        self.assertFalse(adapter.waiting())

    def test_bare_plugins_lists_what_the_gateway_loaded(self) -> None:
        adapter = self.adapter()
        frame = self.refused(adapter, "plugins")
        self.assertEqual((frame["method"], frame["params"]), ("plugins.list", {}))
        # The shape of Hermes bf0203a794's `plugins.list` (`gateway/session_discovery.py` list_plugins).
        result = self.answered(adapter, frame, {"plugins": [
            {"name": "omh", "key": "omh", "version": "4.0.2", "enabled": True, "tools": 9, "hooks": 1, "commands": 0,
             "error": ""},
            {"name": "disk-cleanup", "key": "disk-cleanup", "version": "2.0.0", "enabled": False, "tools": 0,
             "hooks": 0, "commands": 0, "error": "not enabled"}], "toolsets": [], "portable_mcp_servers": []})
        self.assertEqual(result["output"].splitlines(), [
            "omh 4.0.2 (enabled; 9 tools, 1 hook, 0 commands)",
            "disk-cleanup 2.0.0 (disabled; 0 tools, 0 hooks, 0 commands) — error: not enabled"])

    def test_config_lines_join_nested_keys(self) -> None:
        self.assertEqual(attach.config_lines({"display": {"compact": True, "skin": "x"}, "voice": {}, "n": 1}),
                         ['display.compact: true', 'display.skin: "x"', "voice: {}", "n: 1"])


# ── the script, run as gateway_spawn runs it ──

FAKE_OWNER = '''
"""A fake shared-gateway owner behind a fake `websockets` client; it records what it receives."""
import asyncio, json, os
from pathlib import Path

LOG = Path(os.environ["HERMES_HOME"]) / "owner.jsonl"


def _log(entry):
    with LOG.open("a") as log:
        log.write(json.dumps(entry) + "\\n")


class _Socket:
    subprotocol = "hermes-gateway-v1"
    close_code = None

    def __init__(self):
        self.inbox = asyncio.Queue()
        self.inbox.put_nowait({"jsonrpc": "2.0", "method": "event",
                               "params": {"type": "gateway.ready", "payload": {"skin": {"name": "fake"}}}})

    async def send(self, text):
        frame = json.loads(text)
        _log(frame)
        method, rid, params = frame.get("method"), frame.get("id"), frame.get("params") or {}
        answer = lambda result: self.inbox.put_nowait({"jsonrpc": "2.0", "id": rid, "result": result})
        if method == "runtime.describe":
            answer({"session_create": {"sources": ["tui"], "parameters": ["cwd", "model", "request_id", "source"]}})
        elif method == "client.capabilities":
            answer({"server_requests": ["approval"]})
        elif method == "session.create":
            answer({"session_id": "local-1", "stored_session_id": "local-1", "subscription_id": "sub-1",
                    "execution_generation": 1, "messages": [], "info": {"cwd": params.get("cwd")}})
        elif method == "prompt.submit":
            answer({"admission_id": "a1", "ref": {"profile_id": "p", "session_id": "local-1"},
                    "execution_generation": 2, "status": "started"})
            self.inbox.put_nowait({"jsonrpc": "2.0", "method": "event", "params": {
                "type": "approval.request", "session_id": "local-1", "execution_generation": 2,
                "payload": {"kind": "approval", "prompt_id": "p1", "execution_generation": 2,
                            "command": "rm -rf /tmp/x", "description": "delete", "choices": ["once", "deny"]}}})
        elif method == "approval.respond":
            answer({"status": "resolved"})
        elif method == "session.interrupt" and params.get("execution_generation") != 3:
            # The owner moved on to generation 3 without telling this view: a stop for any other is refused.
            self.inbox.put_nowait({"jsonrpc": "2.0", "id": rid, "error": {
                "code": 4001, "message": "stale_generation", "data": {"reason": "stale_generation"}}})
        elif method == "session.interrupt":
            answer({"ref": {"profile_id": "p", "session_id": "local-1"}, "instance_id": "i", "authority_epoch": 1,
                    "revision": 1, "execution_generation": 3, "execution_state": "running"})
        elif method == "session.resume":
            answer({"session_id": "local-1", "stored_session_id": "local-1", "subscription_id": "sub-1",
                    "execution_generation": 3, "running": True, "messages": [], "info": {}})
        elif method == "session.detach":
            answer({"session_id": "local-1", "subscription_id": "sub-1", "detached": True})

    def __aiter__(self):
        return self

    async def __anext__(self):
        if os.environ.get("FAKE_OWNER_GOES_AWAY"):  # a restart: the owner closes with going-away (1001)
            self.close_code = 1001
            raise StopAsyncIteration
        if os.environ.get("FAKE_OWNER_HANGS_UP"):  # the owner's side ends before it is ready
            raise StopAsyncIteration
        return json.dumps(await self.inbox.get())


class connect:
    def __init__(self, url, **options):
        _log({"connect": url, "subprotocols": options.get("subprotocols"), "proxy": options.get("proxy", "unset"),
              "ping_interval": options.get("ping_interval", "unset")})

    async def __aenter__(self):
        if os.environ.get("FAKE_OWNER_DOWN"):
            raise ConnectionRefusedError(61, "Connect call failed")
        if os.environ.get("FAKE_OWNER_GARBLED"):
            from websockets.exceptions import InvalidMessage
            raise InvalidMessage("did not receive a valid HTTP response")
        if os.environ.get("FAKE_OWNER_REFUSES"):
            from websockets.exceptions import WebSocketException
            raise WebSocketException("server rejected WebSocket connection: HTTP 403")
        return _Socket()

    async def __aexit__(self, *exc):
        return False
'''

FAKE_RUNTIME = '''
import json, os
from pathlib import Path
from types import SimpleNamespace


def ensure_gateway_runtime(home, timeout, idle_exit):
    left = sorted(name for name in ("HERMES_MODEL", "HERMES_CWD", "HERMES_TUI_CLIENT_ENV") if name in os.environ)
    with (Path(os.environ["HERMES_HOME"]) / "owner.jsonl").open("a") as log:
        log.write(json.dumps({"ensure": str(home), "idle_exit": idle_exit, "launch_env_left": left}) + "\\n")
    state, _, reason = os.environ.get("FAKE_RUNTIME_STATE", "ready").partition(":")
    return SimpleNamespace(state=state, reason_code=reason or None, detail=None,
                           endpoint=SimpleNamespace(profile_id="p", instance_id="i", api_origin="http://127.0.0.1:1"))


def attachable(receipt):
    return receipt.state == "ready"


def control_home_for(home, endpoint):
    return home
'''

FAKE_DISCOVERY = '''
import io, json


class _Peer:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def sendall(self, data):
        self.request = json.loads(data)

    def makefile(self, mode):
        import os
        if os.environ.get("FAKE_CONTROL_SILENT"):  # the socket closes without an answer
            return io.BytesIO(b"")
        grant = {"ok": True, "id": 1, "result": {"profile_id": "p", "instance_id": "i", "ticket": "t0k"}}
        return io.BytesIO(json.dumps(grant).encode() + b"\\n")


def connect_private(control, timeout):
    import os
    if os.environ.get("FAKE_CONTROL_REFUSES"):
        raise ConnectionRefusedError(61, "Connection refused")
    if os.environ.get("FAKE_CONTROL_DENIED"):
        raise PermissionError(13, "Permission denied")
    return _Peer()
'''

FAKE_CLIENT = '''
GATEWAY_WS_PROTOCOL = "hermes-gateway-v1"


def gateway_ws_target(endpoint, ticket):
    return endpoint.api_origin.replace("http:", "ws:") + "/api/ws", [GATEWAY_WS_PROTOCOL, "hermes-gateway-ticket." + ticket]
'''

FAKE_STDIO_ENTRY = '''
import json, os, sys
from pathlib import Path


def main():
    log = Path(os.environ["HERMES_HOME"]) / "stdio.jsonl"
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "method": "event",
                                 "params": {"type": "gateway.ready", "payload": {"stdio": True}}}) + "\\n")
    sys.stdout.flush()
    for line in sys.stdin:
        frame = json.loads(line)
        with log.open("a") as out:
            out.write(json.dumps(frame) + "\\n")
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": frame["id"], "result": {"stdio": frame["method"]}}) + "\\n")
        sys.stdout.flush()
    return 7
'''


def _write(root: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")


class ScriptTests(unittest.TestCase):
    """The child `gateway_spawn` names, run on a fake Hermes the way the TUI runs it."""

    def hermes(self, files: dict[str, str], env: dict[str, str] | None = None) -> tuple[Path, dict[str, str]]:
        root = Path(self.enterContext(make_test_tempdir("omh-tui-attach-")))
        home = root / "home"
        home.mkdir()
        _write(root / "src", {"tui_gateway/__init__.py": "", "tui_gateway/entry.py": FAKE_STDIO_ENTRY, **files})
        # Windows' runtime prerequisites (SYSTEMROOT and kin) and nothing else of this process: without SYSTEMROOT a
        # Windows child cannot load Winsock, so `import asyncio` fails (WinError 10106). The TUI itself hands its
        # child the launcher's whole environment (`gateway_spawn`), so this reduction is the fixture's own.
        environ = {**fixture_system_environment(), "HERMES_PYTHON": sys.executable,
                   "HERMES_PYTHON_SRC_ROOT": str(root / "src"), "HERMES_HOME": str(home), "HERMES_CWD": str(root),
                   "PATH": os.environ.get("PATH", ""), **(env or {})}
        return home, environ

    def client(self, environ: dict[str, str]) -> GatewayClient:
        client = GatewayClient(gateway_spawn(environ))
        self.addCleanup(client.close, FAST_GRACE)
        return client

    def test_the_child_is_the_attach_script_run_by_path(self) -> None:
        self.assertTrue(GATEWAY_SCRIPT.is_file())
        self.assertEqual(GATEWAY_SCRIPT.name, "gateway_attach.py")
        # Its directory is on the script's import path: nothing in it may be named like a Hermes module.
        self.assertEqual(sorted(path.name for path in GATEWAY_SCRIPT.parent.glob("*.py")),
                         ["__init__.py", "gateway_attach.py"])

    def test_a_hermes_with_only_the_stdio_entry_runs_it_in_the_child(self) -> None:
        home, environ = self.hermes({})
        client = self.client(environ)
        ready = client.start(ready_timeout=10)
        self.assertEqual(ready.payload, {"stdio": True})
        self.assertEqual(client.call("session.create", {"cols": 80}), {"stdio": "session.create"})
        self.assertEqual(client.call("session.interrupt", {"session_id": "s1"}), {"stdio": "session.interrupt"})
        self.assertEqual(client.close(grace=5), 7)  # the entry's own exit code
        # Over stdio nothing is translated: the stop goes as the TUI sent it, with no generation and no read.
        log = [json.loads(line) for line in (home / "stdio.jsonl").read_text().splitlines()]
        self.assertEqual([frame["params"] for frame in log if frame["method"] in ("session.interrupt", "session.resume")],
                         [{"session_id": "s1"}])

    def test_a_hermes_cli_without_the_attach_api_still_runs_the_stdio_entry(self) -> None:
        _home, environ = self.hermes({"hermes_cli/__init__.py": "", "hermes_cli/gateway_client.py": FAKE_CLIENT,
                                      "hermes_constants.py": "def get_hermes_home(): ..."})
        ready = self.client(environ).start(ready_timeout=10)
        self.assertEqual(ready.payload, {"stdio": True})

    ATTACH_API = {
        "hermes_cli/__init__.py": "",
        "hermes_cli/gateway_client.py": FAKE_CLIENT,
        "hermes_cli/gateway_runtime.py": FAKE_RUNTIME,
        "hermes_cli/gateway_runtime_discovery.py": FAKE_DISCOVERY,
        "hermes_constants.py": "import os\nfrom pathlib import Path\n\ndef get_hermes_home():\n"
                               "    return Path(os.environ['HERMES_HOME'])\n",
        "websockets/__init__.py": "", "websockets/asyncio/__init__.py": "",
        "websockets/asyncio/client.py": FAKE_OWNER,
        "websockets/exceptions.py": "class WebSocketException(Exception):\n    pass\n\n\n"
                                    "class InvalidMessage(WebSocketException):\n    pass\n",
    }

    def test_a_refused_upgrade_ends_with_the_childs_own_line_and_no_traceback(self) -> None:
        _home, environ = self.hermes(self.ATTACH_API, env={"FAKE_OWNER_REFUSES": "1"})
        client = self.client(environ)
        with self.assertRaises(GatewayUnavailable) as raised:
            client.start(ready_timeout=10)
        tail = raised.exception.stderr_tail
        self.assertIn("omh-attach: could not reach Hermes' gateway: server rejected WebSocket connection: HTTP 403",
                      tail)
        self.assertFalse([line for line in tail if "Traceback" in line], tail)

    def test_a_gateway_that_is_not_answering_yet_exits_not_ready_so_the_tui_waits(self) -> None:
        # A restart: Hermes' verdict says starting or draining, or the control socket or the WebSocket refuses.
        for env, said in (
            ({"FAKE_RUNTIME_STATE": "starting:deadline"}, "omh-attach: gateway starting: deadline"),
            ({"FAKE_RUNTIME_STATE": "draining:replaced"}, "omh-attach: gateway draining: replaced"),
            ({"FAKE_RUNTIME_STATE": "inaccessible:control_timeout"}, "omh-attach: gateway inaccessible: control_timeout"),
            ({"FAKE_CONTROL_REFUSES": "1"}, "omh-attach: [Errno 61] Connection refused"),
            ({"FAKE_OWNER_DOWN": "1"}, "omh-attach: could not reach Hermes' gateway: [Errno 61] Connect call failed"),
            ({"FAKE_CONTROL_SILENT": "1"}, "omh-attach: Hermes' gateway closed its control socket without answering"),
            ({"FAKE_OWNER_GOES_AWAY": "1"}, "omh-attach: the connection to Hermes' gateway ended (close code 1001)"),
        ):
            with self.subTest(env=env):
                _home, environ = self.hermes(self.ATTACH_API, env=env)
                with self.assertRaises(GatewayUnavailable) as raised:
                    self.client(environ).start(ready_timeout=10)
                self.assertTrue(raised.exception.not_ready, raised.exception)
                self.assertEqual(raised.exception.returncode, attach.NOT_READY_EXIT)
                self.assertIn(said, raised.exception.stderr_tail)

    def test_a_gateway_that_refuses_this_client_is_not_waited_for(self) -> None:
        # A verdict that will not change by waiting, a refused upgrade and a denied socket stay the child's ordinary
        # failure. So does any other WebSocket client error, a garbled handshake included: telling `InvalidMessage`
        # apart needs a name INVARIANT 2's closed list for this script does not hold.
        for env in ({"FAKE_RUNTIME_STATE": "incompatible:runtime_protocol"}, {"FAKE_OWNER_REFUSES": "1"},
                    {"FAKE_CONTROL_DENIED": "1"}, {"FAKE_OWNER_GARBLED": "1"}):
            with self.subTest(env=env):
                _home, environ = self.hermes(self.ATTACH_API, env=env)
                with self.assertRaises(GatewayUnavailable) as raised:
                    self.client(environ).start(ready_timeout=10)
                self.assertFalse(raised.exception.not_ready)
                self.assertEqual(raised.exception.returncode, 1)

    def test_an_owner_that_hangs_up_while_stdin_is_still_open_ends_the_child_with_its_own_code(self) -> None:
        # The TUI holds the child's stdin open, so the stdin reader is still blocked in its read when the relay ends.
        # Reading through `sys.stdin.buffer` there aborted the child at finalization (-6 on POSIX, #2327).
        _home, environ = self.hermes(self.ATTACH_API, env={"FAKE_OWNER_HANGS_UP": "1"})
        client = self.client(environ)
        with self.assertRaises(GatewayUnavailable) as raised:
            client.start(ready_timeout=10)
        self.assertEqual(str(raised.exception), "the gateway exited with code 1 before gateway.ready")
        tail = raised.exception.stderr_tail
        self.assertIn("omh-attach: the connection to Hermes' gateway ended (close code None)", tail)
        self.assertFalse([line for line in tail if "Fatal Python error" in line], tail)

    def test_the_stdin_reader_delivers_one_line_per_newline_and_a_last_unended_line(self) -> None:
        reading, writing = os.pipe()
        long_line = b'{"text": "' + b"x" * (attach.STDIN_READ_BYTES * 2 + 7) + b'"}'
        sent = b'{"a": 1}\n\n' + long_line + b'\n{"last": true}'  # more than a pipe holds: written as it is read

        def write() -> None:
            with open(writing, "wb") as stream:
                stream.write(sent)

        writer = threading.Thread(target=write, daemon=True)
        writer.start()

        async def lines() -> list[bytes | None]:
            queue: asyncio.Queue[bytes | None] = asyncio.Queue()
            with patch.object(sys, "stdin", types.SimpleNamespace(fileno=lambda: reading)):
                attach._start_stdin_reader(asyncio.get_running_loop(), queue)
            read = [await asyncio.wait_for(queue.get(), 10)]
            while read[-1] is not None:
                read.append(await asyncio.wait_for(queue.get(), 10))
            return read

        try:
            read = asyncio.run(lines())
        finally:
            writer.join(10)
            os.close(reading)
        self.assertEqual(read, [b'{"a": 1}', b"", long_line, b'{"last": true}', None])

    def test_a_hermes_with_the_attach_api_is_attached_to_and_translated(self) -> None:
        home, environ = self.hermes(self.ATTACH_API,
                                    env={"HERMES_MODEL": "gpt-x", "HERMES_TUI_CLIENT_ENV": json.dumps({"PATH": "/bin"})})
        client = self.client(environ)
        ready = client.start(ready_timeout=10)
        self.assertEqual(ready.payload, {"skin": {"name": "fake"}})
        self.assertEqual(client.capabilities, {"server_requests": ["approval"]})
        created = client.call("session.create", {"cols": 80, "cwd": "/tui/cwd"})
        self.assertEqual((created["session_id"], created["info"]), ("local-1", {"cwd": "/tui/cwd"}))
        client.call("prompt.submit", {"session_id": "local-1", "text": "delete it"})
        request = self._next_request(client)
        self.assertEqual((request.id, request.method, request.params["command"]),
                         ("omh-approval-p1", "approval", "rm -rf /tmp/x"))
        client.respond(request.id, {"result": {"choice": "deny"}})
        stopped = client.call("session.interrupt", {"session_id": "local-1"})
        self.assertEqual((stopped["execution_generation"], stopped["execution_state"]), (3, "running"))
        client.call("session.close", {"session_id": "local-1"})
        self.assertEqual(client.close(grace=5), 0)  # the person left: a normal exit, no respawn

        log = [json.loads(line) for line in (home / "owner.jsonl").read_text().splitlines()]
        ensure = next(entry for entry in log if "ensure" in entry)
        self.assertEqual(ensure, {"ensure": str(home.resolve()), "idle_exit": True, "launch_env_left": []})
        connect = next(entry for entry in log if "connect" in entry)
        # No keepalive ping (Hermes' loopback policy): a gateway busy for 40 s must not drop a turn that still runs.
        self.assertEqual(connect, {"connect": "ws://127.0.0.1:1/api/ws", "proxy": None, "ping_interval": None,
                                   "subprotocols": ["hermes-gateway-v1", "hermes-gateway-ticket.t0k"]})
        sent = {entry["method"]: entry["params"] for entry in log if "method" in entry}
        self.assertEqual(sent["session.create"], {"cwd": "/tui/cwd", "model": "gpt-x", "source": "tui",
                                                  "request_id": sent["session.create"]["request_id"]})
        self.assertIn("input_id", sent["prompt.submit"])
        self.assertEqual(sent["approval.respond"], {"session_id": "local-1", "execution_generation": 2,
                                                    "prompt_id": "p1", "choice": "deny"})
        self.assertEqual(sent["session.detach"], {"session_id": "local-1", "subscription_id": "sub-1",
                                                  "end_reason": "tui_close"})
        # The stop went at the generation the submit receipt named, was refused as stale, read afresh, and sent
        # once more at the owner's.
        stops = [(entry["method"], entry["params"]) for entry in log
                 if entry.get("method") in ("session.interrupt", "session.resume")]
        self.assertEqual(stops, [
            ("session.interrupt", {"session_id": "local-1", "execution_generation": 2}),
            ("session.resume", {"session_id": "local-1"}),
            ("session.interrupt", {"session_id": "local-1", "execution_generation": 3}),
        ])

    def _next_request(self, client: GatewayClient) -> ServerRequest:
        for _ in range(50):
            for item in client.poll(timeout=0.2):
                if isinstance(item, ServerRequest):
                    return item
        self.fail(f"no server request arrived; stderr: {client.stderr_tail()}")


if __name__ == "__main__":
    unittest.main()

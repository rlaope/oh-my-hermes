from __future__ import annotations

import hashlib
import json
import unittest
from functools import cached_property
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from omh.plugin_bundle.omh.active_workflow_context import (
    ACTIVE_WORKFLOW_ENDED_LINE,
    ACTIVE_WORKFLOW_HEAD,
    render_active_workflow_context,
)
from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call


class ActiveWorkflowContextTests(unittest.TestCase):
    session = "session-a"

    @cached_property
    def home(self) -> Path:
        home = Path(self.enterContext(TemporaryDirectory())) / "qa-profile" / "qa-project"
        home.mkdir(parents=True)
        return home

    def cli(self, *args: str) -> tuple[int, str, str]:
        return run_cli(["--omh-home", str(self.home), "state", *args])

    def start(self, workflow: str = "memory-sync") -> None:
        status, _, stderr = self.cli("start", "--workflow", workflow, "--session-ref", self.session)
        self.assertEqual((status, stderr), (0, ""))

    def fixture(self, workflow: str = "memory-sync", **extra) -> Path:
        path = self.home / "state" / f"{workflow}-state.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({
            "schema_version": 1, "workflow": workflow, "active": True,
            "lifecycle_outcome": None,
            "session_ref": "sha256:" + hashlib.sha256(self.session.encode()).hexdigest(),
            "session_binding": "bound", **extra,
        }), encoding="utf-8")
        return path

    def hook(self, message: str = "continue", **kwargs):
        payload = pre_llm_call(omh_home=str(self.home), session_id=self.session,
                               user_message=message, is_first_turn=False, **kwargs) or {}
        # Exercise the JSON-compatible host payload, not a mock of the reader.
        return json.loads(json.dumps(payload))

    def snapshot(self) -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in (self.home / "state").glob("*-state.json")}

    def test_explicit_activation_and_continuation(self) -> None:
        # Given an explicitly activated workflow through the public CLI.
        self.start()
        before = self.snapshot()
        # When the next model-call boundary receives a neutral follow-up.
        payload = self.hook()
        # Then durable identity, not message routing, provides continuation.
        self.assertIn("omh_active_workflow", payload)
        context = payload["omh_active_workflow"]
        self.assertEqual(context["schema_version"], "active_workflow_context/v1")
        self.assertEqual((context["workflow"], context["lifecycle_state"]), ("memory-sync", "active"))
        self.assertEqual(context["continuation_rule"], "return_to_active_checklist")
        self.assertLessEqual(len(payload["context"].encode()), 512)
        self.assertEqual(self.snapshot(), before)
        record = json.loads(before["memory-sync-state.json"])
        self.assertEqual(record["session_ref"], "sha256:" + hashlib.sha256(self.session.encode()).hexdigest())
        self.assertEqual(record["activation"]["observed_by_host"], "not_observed")

    def test_neutral_and_compacted_history(self) -> None:
        # Given authoritative state, independent of any retained prompt.
        self.fixture()
        for history in ([], [{"role": "system", "content": "[summary] compacted history"}]):
            with self.subTest(history=history):
                # When only neutral text or a system summary reaches the hook.
                payload = self.hook("" if history else "ok", conversation_history=history)
                # Then the marker is restored without claiming compaction.
                self.assertIn("omh_active_workflow", payload)
                projection = payload["omh_active_workflow"]
                self.assertEqual(projection["workflow"], "memory-sync")
                self.assertEqual(projection["continuation_rule"], "return_to_active_checklist")
                self.assertEqual(projection["compaction_observed"], "not_observed")
                self.assertIn("[OMH Active Workflow]", payload["context"])
        first = self.hook()
        replay = self.hook(conversation_history=[{"role": "user", "content": "ok", "api_content": "ok\n" + first["context"]}])
        # The metadata is reprojected every call; the reminder itself is already replayed.
        self.assertEqual(replay["omh_active_workflow"], first["omh_active_workflow"])
        self.assertNotIn(ACTIVE_WORKFLOW_HEAD, replay.get("context", ""))

    @staticmethod
    def replayed(*contexts: str) -> list[dict[str, str]]:
        """History as Hermes replays it: each turn's injection in its `api_content` sidecar."""
        rows: list[dict[str, str]] = []
        for context in contexts:
            rows.append({"role": "user", "content": "ok", "api_content": "ok\n\n" + context})
            rows.append({"role": "assistant", "content": "done"})
        return rows

    def test_reminder_rides_once_while_history_replays_it(self) -> None:
        # Given an active workflow.
        self.fixture()
        # When the first turn injects it and the second turn's history replays that turn.
        first = self.hook(conversation_history=[])
        reminder = render_active_workflow_context(first["omh_active_workflow"])
        self.assertIn(reminder, first["context"])
        second = self.hook(conversation_history=self.replayed(first["context"]))
        # Then the second turn carries the metadata but not a second copy.
        self.assertEqual(second["omh_active_workflow"], first["omh_active_workflow"])
        self.assertNotIn(ACTIVE_WORKFLOW_HEAD, second.get("context", ""))
        # Nor does a later turn while the first copy is still in replayed history.
        third = self.hook(conversation_history=[*self.replayed(first["context"]), *self.replayed("<omh-context>x</omh-context>")])
        self.assertNotIn(ACTIVE_WORKFLOW_HEAD, third.get("context", ""))

    def test_reminder_returns_after_compaction_and_on_change(self) -> None:
        self.fixture()
        first = self.hook(conversation_history=[])
        reminder = render_active_workflow_context(first["omh_active_workflow"])
        # A compaction summary replaced the replayed turns: the reminder comes back.
        compacted = self.hook(conversation_history=[{"role": "user", "content": "[CONTEXT COMPACTION] summary"}])
        self.assertIn(reminder, compacted["context"])
        # A person quoting the reminder in their own words does not count as replayed.
        quoted = self.hook(conversation_history=[{"role": "user", "content": reminder, "api_content": reminder}])
        self.assertIn(reminder, quoted["context"])
        # The workflow changed: the new text is not in history, so it rides.
        self.assertEqual(self.cli("clear", "--workflow", "memory-sync", "--session-ref", self.session)[0], 0)
        self.start("plan")
        changed = self.hook(conversation_history=self.replayed(first["context"]))
        self.assertEqual(changed["omh_active_workflow"]["workflow"], "plan")
        self.assertIn("[OMH Active Workflow] workflow=plan", changed["context"])
        # An older copy of the new text earlier in history does not hide the change back.
        self.assertIn(
            "[OMH Active Workflow] workflow=plan",
            self.hook(conversation_history=self.replayed(changed["context"], first["context"]))["context"],
        )

    def test_end_line_once_after_the_workflow_ends(self) -> None:
        self.fixture()
        first = self.hook(conversation_history=[])
        self.assertEqual(self.cli("finish", "--workflow", "memory-sync", "--outcome", "finished",
                                  "--session-ref", self.session)[0], 0)
        # The replayed reminder still stands, and no workflow is active now: one end line.
        ended = self.hook(conversation_history=self.replayed(first["context"]))
        self.assertNotIn("omh_active_workflow", ended)
        self.assertIn(ACTIVE_WORKFLOW_ENDED_LINE, ended["context"])
        self.assertEqual(ended["context"].count(ACTIVE_WORKFLOW_HEAD), 1)
        # The end line already follows the reminder in history: nothing more.
        after = self.hook(conversation_history=self.replayed(first["context"], ended["context"]))
        self.assertNotIn(ACTIVE_WORKFLOW_HEAD, after.get("context", ""))
        # A compaction that dropped both leaves nothing to retract.
        self.assertNotIn(ACTIVE_WORKFLOW_HEAD, self.hook(conversation_history=[]).get("context", ""))

    @staticmethod
    def image_turn(context: str, ask: str = "please inspect the image") -> list[dict[str, object]]:
        """A multimodal turn as Hermes replays it: no sidecar, the injection is a trailing text
        part, and the person's ask is stamped as `display_metadata.typed_ask` (the review's input)."""
        return [{
            "role": "user",
            "content": [
                {"type": "text", "text": ask},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}},
                {"type": "text", "text": context},
            ],
            "display_metadata": {"typed_ask": ask},
        }, {"role": "assistant", "content": "done"}]

    def test_image_turn_replay_is_read_from_the_typed_ask_boundary(self) -> None:
        self.fixture()
        first = self.hook(conversation_history=[])
        # The reminder rode an image turn: the next call does not add a second copy.
        second = self.hook(conversation_history=self.image_turn(first["context"]))
        self.assertEqual(second["omh_active_workflow"], first["omh_active_workflow"])
        self.assertNotIn(ACTIVE_WORKFLOW_HEAD, second.get("context", ""))
        # Same row rebuilt from the session DB: parts flattened, the image a `[screenshot]` line.
        rebuilt = [{"role": "user", "content": "please inspect the image\n[screenshot]\n" + first["context"],
                    "display_metadata": {"typed_ask": "please inspect the image"}}]
        self.assertNotIn(ACTIVE_WORKFLOW_HEAD, self.hook(conversation_history=rebuilt).get("context", ""))

    def test_session_db_image_rows_in_every_host_shape_are_read(self) -> None:
        # Review round 2: a gateway timestamp prefix, a typed literal `[screenshot]` line, an empty text part.
        self.fixture()
        reminder = self.hook(conversation_history=[])["context"]
        for content, ask in (
            ("[Wed 2026-11-11 21:26:40 KST] please inspect the image\n[screenshot]\n" + reminder,
             "please inspect the image"),
            ("Explain this label:\n[screenshot]\n[screenshot]\n" + reminder, "Explain this label:\n[screenshot]"),
            ("\n[screenshot]\ninspect\n" + reminder, "inspect"),
            ("[screenshot]\n" + reminder, ""),
        ):
            row = [{"role": "user", "content": content, "display_metadata": {"typed_ask": ask}}]
            with self.subTest(ask=ask):
                self.assertNotIn(ACTIVE_WORKFLOW_HEAD, self.hook(conversation_history=row).get("context", ""))
        self.assertEqual(self.cli("finish", "--workflow", "memory-sync", "--outcome", "finished",
                                  "--session-ref", self.session)[0], 0)
        stamped = [{"role": "user", "content": "[Wed 2026-11-11 21:26:40 KST] look\n[screenshot]\n" + reminder,
                    "display_metadata": {"typed_ask": "look"}}]
        self.assertIn(ACTIVE_WORKFLOW_ENDED_LINE, self.hook(conversation_history=stamped)["context"])

    def test_a_db_row_whose_ask_is_not_all_there_counts_as_no_injection(self) -> None:
        self.fixture()
        reminder = self.hook(conversation_history=[])["context"]
        for content, ask in (
            ("something else\n[screenshot]\n" + reminder, "please inspect"),  # the stamped ask is missing
            ("why does it say this?\n" + reminder, "why does it say this?\n" + reminder),  # the person quoted it
        ):
            row = [{"role": "user", "content": content, "display_metadata": {"typed_ask": ask}}]
            with self.subTest(ask=ask[:20]):
                self.assertIn(ACTIVE_WORKFLOW_HEAD, self.hook(conversation_history=row)["context"])

    def test_end_line_once_after_an_image_turn(self) -> None:
        self.fixture()
        first = self.hook(conversation_history=[])
        # The workflow ends right after an image turn: the end line once, then nothing.
        self.assertEqual(self.cli("finish", "--workflow", "memory-sync", "--outcome", "finished",
                                  "--session-ref", self.session)[0], 0)
        ended = self.hook(conversation_history=self.image_turn(first["context"]))
        self.assertIn(ACTIVE_WORKFLOW_ENDED_LINE, ended["context"])
        self.assertEqual(ended["context"].count(ACTIVE_WORKFLOW_HEAD), 1)
        after = self.hook(conversation_history=[*self.image_turn(first["context"]), *self.image_turn(ended["context"])])
        self.assertNotIn(ACTIVE_WORKFLOW_HEAD, after.get("context", ""))

    def test_person_quoting_the_reminder_in_an_image_turn_still_gets_it(self) -> None:
        self.fixture()
        reminder = render_active_workflow_context(self.hook(conversation_history=[])["omh_active_workflow"])
        quoted_ask = "why does it say this?\n" + reminder
        for history in (
            # The quote is the person's own ask; nothing was appended after it.
            [{"role": "user", "content": [{"type": "text", "text": quoted_ask},
                                          {"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}],
              "display_metadata": {"typed_ask": quoted_ask}}],
            # Host appended an unrelated note after the quoted ask.
            self.image_turn("<omh-context>x</omh-context>", ask=quoted_ask),
            # No typed-ask stamp: no host boundary, so no part counts as injected.
            [{"role": "user", "content": [{"type": "text", "text": "look"}, {"type": "text", "text": reminder}]}],
        ):
            with self.subTest(history=history):
                self.assertIn(reminder, self.hook(conversation_history=history)["context"])

    def test_no_workflow_ever_injects_nothing(self) -> None:
        # No state, no replayed reminder: neither the reminder nor an end line.
        for history in ([], self.replayed("<omh-context>x</omh-context>"),
                        [{"role": "user", "content": "[OMH Active Workflow] workflow=plan; lifecycle=active."}]):
            with self.subTest(history=history):
                payload = self.hook(conversation_history=history)
                self.assertNotIn("omh_active_workflow", payload)
                self.assertNotIn(ACTIVE_WORKFLOW_HEAD, payload.get("context", ""))

    def test_interjection_preserves_workflow(self) -> None:
        # Given an active workflow and unchanged on-disk checklist authority.
        self.fixture()
        before = self.snapshot()
        # When a status interjection followed by a scope-changing cue is handled.
        status = self.hook("what is the status?")
        scope = self.hook("make an image explaining the cron feature")
        continuation = self.hook()
        # Then current routing remains primary and neutral turns return to work.
        self.assertIn("omh_active_workflow", status)
        self.assertEqual(status["omh_active_workflow"]["interjection_rule"], "answer_then_return")
        self.assertEqual(scope["omh_context_brief"]["route_hint"]["primary_workflow"], "img-summary")
        self.assertLess(scope["context"].index("[OMH Route Hint]"), scope["context"].index("[OMH Active Workflow]"))
        self.assertEqual(continuation["omh_active_workflow"]["precedence"], "explicit_user_instruction_outranks_continuation")
        self.assertEqual(self.snapshot(), before)

    def test_terminal_and_transition_lifecycle(self) -> None:
        for outcome in ("finished", "blocked", "failed", "cancelled", "user_interlude", "question_pending"):
            with self.subTest(outcome=outcome):
                # Given a bound active workflow.
                self.fixture()
                # When its owner records a terminal outcome.
                status, _, stderr = self.cli("finish", "--workflow", "memory-sync", "--outcome", outcome, "--session-ref", self.session)
                # Then the next hook no longer projects it.
                self.assertEqual((status, stderr), (0, ""))
                self.assertNotIn("omh_active_workflow", self.hook())
        self.start("plan")
        self.start("ultrawork")
        self.assertEqual(self.hook()["omh_active_workflow"]["workflow"], "ultrawork")
        source = json.loads((self.home / "state" / "plan-state.json").read_text())
        self.assertEqual(source["transition_target"], "ultrawork")
        self.assertEqual(self.cli("clear", "--workflow", "ultrawork", "--session-ref", self.session)[0], 0)
        self.assertNotIn("omh_active_workflow", self.hook())

    def test_incidental_text_cannot_activate(self) -> None:
        # Given no durable activation, then a workflow owned by session-a.
        for active in (False, True):
            if active:
                self.fixture()
            before = self.snapshot()
            for message in ('run "memory-sync" later', "implement this feature"):
                # When an unrelated session sends incidental names or routing cues.
                result = pre_llm_call(omh_home=str(self.home), session_id="session-b", user_message=message) or {}
                # Then routing never activates, overwrites, or exposes state.
                self.assertNotIn("omh_active_workflow", result)
                self.assertEqual(self.snapshot(), before)

    def test_corrupt_and_conflicting_state(self) -> None:
        for content in ("{not-json", "[]", '{"active":"yes"}', '{"schema_version":999,"active":true}',
                        "[" * 2000 + "0" + "]" * 2000):
            with self.subTest(content=content):
                # Given malformed durable state.
                path = self.fixture()
                path.write_text(content)
                # When a neutral turn crosses the real hook boundary.
                payload = self.hook()
                # Then recovery is observable, bounded and does not echo the file.
                self.assertIn("omh_active_workflow", payload)
                projection = payload["omh_active_workflow"]
                self.assertEqual(projection["state"], "recovery_required")
                self.assertTrue(projection["recovery_actions"])
                self.assertNotIn("workflow", projection)
        self.fixture()
        self.fixture("plan")
        self.assertEqual(self.hook()["omh_active_workflow"]["state"], "recovery_required")
        self.assertEqual(self.cli("status")[0], 1)
        before = self.snapshot()
        self.assertNotEqual(self.cli("start", "--workflow", "plan", "--session-ref", self.session)[0], 0)
        self.assertEqual(self.snapshot(), before)

    def test_scoped_metadata_only_projection(self) -> None:
        # Given a bound record with legacy operator metadata that must not project.
        self.fixture("plan", note="NOTE_SENTINEL", transcript="TRANSCRIPT_SENTINEL")
        before = self.snapshot()
        # When the owning session sends private content through the hook.
        payload = self.hook("PROMPT_SENTINEL", conversation_history=[{"role": "user", "content": "HISTORY_SENTINEL"}])
        # Then only a closed metadata projection escapes, without observed claims.
        self.assertIn("omh_active_workflow", payload)
        projection = payload["omh_active_workflow"]
        self.assertEqual(set(projection), {
            "schema_version", "state", "workflow", "lifecycle_state", "session_binding",
            "phase_ref", "transition_targets", "continuation_rule", "precedence", "interjection_rule",
            "claim_boundary", "projection_fingerprint", "compaction_observed", "activation_observed",
        })
        for sentinel in ("NOTE_SENTINEL", "TRANSCRIPT_SENTINEL", "PROMPT_SENTINEL", "HISTORY_SENTINEL", "session-a"):
            self.assertNotIn(sentinel, json.dumps(payload))
        self.assertEqual(projection["activation_observed"], "not_observed")
        self.assertEqual(self.snapshot(), before)
        for foreign in (self.home / "another-project", self.home.parent / "another-profile"):
            self.assertNotIn("omh_active_workflow", pre_llm_call(omh_home=str(foreign), session_id=self.session) or {})
        self.assertNotIn("omh_active_workflow", pre_llm_call(omh_home=str(self.home), session_id="session-b") or {})
        self.assertNotIn("omh_active_workflow", self.hook(include_omh_awareness=False))
        for authority in ([], ["--session-ref", "session-b"]):
            for operation in (("start", "--workflow", "plan"), ("start", "--workflow", "ultrawork"),
                              ("finish", "--workflow", "plan"), ("clear", "--workflow", "plan")):
                with self.subTest(authority=authority, operation=operation):
                    self.assertNotEqual(self.cli(*operation, *authority)[0], 0)
                    self.assertEqual(self.snapshot(), before)

    def test_session_authority_covers_every_mutation(self) -> None:
        from omh.paths import resolve_paths
        from omh.workflow_state import WorkflowStateError, clear_workflow_state, finish_workflow_state, start_workflow_state

        paths = resolve_paths(self.home, self.home / "hermes")
        for active in (True, False):
            for authority in ("", "session-b"):
                for mutate in (start_workflow_state, finish_workflow_state, clear_workflow_state):
                    with self.subTest(active=active, authority=authority, operation=mutate.__name__):
                        # Given a bound record, including a completed record.
                        self.fixture("plan", active=active, lifecycle_outcome=None if active else "finished")
                        before = self.snapshot()
                        # When a missing or foreign authority tries any mutation.
                        with self.assertRaises(WorkflowStateError):
                            mutate(paths, "plan", session_ref=authority)
                        # Then neither content nor revision can change.
                        self.assertEqual(self.snapshot(), before)

    def test_owner_can_confirm_and_legacy_state_stays_compatible(self) -> None:
        # Given explicitly activated state with an owning session.
        self.start()
        # When that owner confirms the existing workflow.
        self.start()
        # Then the active identity remains unique and bound.
        record = json.loads(self.snapshot()["memory-sync-state.json"])
        self.assertEqual(record["record_revision"], 2)
        self.assertEqual(self.hook()["omh_active_workflow"]["session_binding"], "bound")
        self.assertEqual(self.cli("clear", "--workflow", "memory-sync", "--session-ref", self.session)[0], 0)
        self.assertEqual(self.cli("start", "--workflow", "plan")[0], 0)
        self.assertEqual(self.hook()["omh_active_workflow"]["session_binding"], "unbound")
        self.assertEqual(self.cli("finish", "--workflow", "plan")[0], 0)
        self.assertEqual(self.cli("clear", "--workflow", "plan")[0], 0)

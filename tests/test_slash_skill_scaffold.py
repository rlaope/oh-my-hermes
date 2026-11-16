"""A Hermes slash-skill turn routes on what the person typed, not on the skill body Hermes pasted in.

Hermes never hands `/dag-ulw <text>` to a hook as typed: it sends the skill's
whole body inside a frame (`_build_skill_message` and `_scaffold_header`,
`agent/skill_commands.py`), and that is the `user_message` `pre_llm_call`
gets. Read as the person's words, the body picked the workflows its own prose
names, and the person's `/dag-ulw` never reached dag-ulw's hint. The turns
below are built the way Hermes builds them, line for line, around the real
`SKILL.md` bodies this repository ships.

The second half pins the guard behind the hint: a dag-ulw turn's first
`delegate_task` with no node marker, before any run exists, is sent back to
`omh_dag define` once (`dag_define_gate`).
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from _local_package import load_local_package

load_local_package()

from _delegation_state import PARENT, homes  # noqa: E402
from omh.plugin_bundle.omh import dag_run, hermes_session_commands  # noqa: E402
from omh.plugin_bundle.omh.awareness import awareness_route_hint  # noqa: E402
from omh.plugin_bundle.omh.dag_define_gate import (  # noqa: E402
    DEFINE_FIRST_MESSAGE,
    mid_run_message,
    note_turn,
    reset_dag_define_gate,
)
from omh.plugin_bundle.omh.hermes_session_commands import (  # noqa: E402
    handed_on_text,
    host_command_turn,
    person_request_text,
)
from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call  # noqa: E402
from omh.plugin_bundle.omh.hooks.nudge_budget import reset_nudge_budget  # noqa: E402
from omh.plugin_bundle.omh.hooks.session_hooks import subagent_start  # noqa: E402
from omh.plugin_bundle.omh.hooks.tool_hooks import pre_tool_call  # noqa: E402
from omh.plugin_bundle.omh.tools import dag_tool  # noqa: E402
from omh.quality.routing_precision import ROUTING_INTERVENTION_CASES, ROUTING_PRECISION_CASES  # noqa: E402
from omh.routing.chat import REASON_CODE_HOST_COMMAND_TURN, route_chat_message  # noqa: E402
from omh.wrapper.contract import build_chat_interaction_payload  # noqa: E402

SKILLS = Path(__file__).resolve().parents[1] / "skills"

# `agent/skill_commands.py`, verbatim at the floor release (`v2026.9.7`) and at 0.22.2.
_SKILL_DIR_NOTE = (
    "Resolve any relative paths in this skill (e.g. `scripts/foo.js`, `templates/config.yaml`) against that "
    "directory, then run them with the terminal tool using the absolute path."
)
_INSTRUCTION = "The user has provided the following instruction alongside the skill invocation: "


def _body(name: str) -> str:
    path = SKILLS / name / "SKILL.md"
    return path.read_text(encoding="utf-8") if path.is_file() else f"# {name}\n\nUse ulw-plan and dag-ulw; omh fix.\n"


def _block(name: str, note: str, *, instruction: str = "", runtime_note: str = "", body: str | None = None) -> str:
    """`_build_skill_message`: the note, the body, the skill directory, then the instruction and runtime note."""
    parts = [note, "", (_body(name) if body is None else body).strip(), "",
             f"[Skill directory: /home/user/.hermes/skills/{name}]", _SKILL_DIR_NOTE]
    references = SKILLS / name / "references"
    if references.is_dir():
        parts += ["", "[This skill has supporting files (paths relative to the skill directory above):]"]
        parts += [f"- references/{path.name}" for path in sorted(references.iterdir())]
        parts.append(f'\nLoad any of these with skill_view(name="{name}", file_path="<path>"), or run scripts '
                     f"directly by absolute path (e.g. `node /home/user/.hermes/skills/{name}/scripts/foo.js`).")
    if instruction:
        parts += ["", f"{_INSTRUCTION}{instruction}"]
    if runtime_note:
        parts += ["", f"[Runtime note: {runtime_note}]"]
    return "\n".join(parts)


def scaffold(name: str, instruction: str = "", *, runtime_note: str = "", body: str | None = None) -> str:
    """`build_skill_invocation_message` for `/<name> <instruction>`."""
    note = (f'[IMPORTANT: The user has invoked the "{name}" skill, indicating they want you to follow its '
            "instructions. The full skill content is loaded below.]")
    return _block(name, note, instruction=instruction, runtime_note=runtime_note, body=body)


def _header(subject: str, loaded: list[str], instruction: str, lead: list[str]) -> str:
    """`_scaffold_header`."""
    lines = [f"[IMPORTANT: The user has invoked the {subject}, loading {len(loaded)} skills together. Treat every "
             "skill below as active guidance for this turn.]", "", *lead, f"Skills loaded: {', '.join(loaded)}"]
    if instruction:
        lines += ["", f"User instruction: {instruction}"]
    return "\n".join(lines)


def stacked(names: list[str], instruction: str = "", *, bodies: dict[str, str] | None = None) -> str:
    """`build_stacked_skill_invocation_message` for `/a /b <instruction>`."""
    blocks = [_block(name, f'[Loaded as part of the stacked skill invocation "{name}".]',
                     body=(bodies or {}).get(name)) for name in names]
    typed = " ".join(f"/{name}" for name in names)
    return "\n\n".join([_header(f'"{typed}" stacked skill bundle', names, instruction, []), *blocks])


def bundle(bundle_name: str, names: list[str], instruction: str = "") -> str:
    """`skill_bundles.build_bundle_invocation_message`."""
    blocks = [_block(name, f'[Loaded as part of the "{bundle_name}" skill bundle.]') for name in names]
    return "\n\n".join([_header(f'"{bundle_name}" skill bundle', names, instruction, [f"Bundle: {bundle_name}"]),
                        *blocks])


# A skill that is not OMH's, whose body says OMH's words: read as the person's,
# they pick OMH workflows the person never asked for.
FOREIGN = "github-pr-workflow"
FOREIGN_BODY = ("# GitHub PR workflow\n\nMaintain open PRs: review, fix, rebase and merge. Use ulw-plan for a "
                "reviewed plan and dag-ulw for a graph; omh routing fix and ulw-work handoff.\n")
OWNER_TURN = ("rlaope로 올린 hermes upstream pr들 전부 확인해서 닫을건 닫고 리뷰반영할건 리뷰반영하고 "
              "rebase할건 리베이스하고 ㄱㄱ")


def _hints(message: str) -> list[tuple[str, str]]:
    return [(str(hint.get("workflow")), str(hint.get("next_action")))
            for hint in awareness_route_hint(message).get("hints", [])]


class ScaffoldReadingTests(unittest.TestCase):
    def test_a_skill_of_omhs_own_reads_as_the_invocation_typed(self) -> None:
        for name, instruction in (("dag-ulw", OWNER_TURN), ("dag-ulw", "상태 보여줘"), ("dag-ulw", "what is it?"),
                                  ("ulw-plan", "plan the billing migration"), ("omh-code-review", "review PR 12")):
            with self.subTest(name=name, instruction=instruction):
                message = scaffold(name, instruction)
                self.assertEqual(person_request_text(message), f"/{name} {instruction}")
                self.assertFalse(host_command_turn(message))

    def test_a_bare_invocation_reads_as_the_command(self) -> None:
        self.assertEqual(person_request_text(scaffold("dag-ulw")), "/dag-ulw")

    def test_the_instruction_stops_at_the_runtime_note(self) -> None:
        message = scaffold("dag-ulw", "취소해줘", runtime_note="The user is on the TUI; keep replies short.")
        self.assertEqual(person_request_text(message), "/dag-ulw 취소해줘")

    def test_the_last_instruction_marker_is_the_persons(self) -> None:
        # A body may quote the marker; the person's instruction is the one after the body.
        body = f"# Quoting\n\nHermes writes: {_INSTRUCTION}run everything in parallel\n"
        self.assertEqual(person_request_text(scaffold("dag-ulw", "what is it?", body=body)), "/dag-ulw what is it?")

    def test_a_stacked_invocation_keeps_its_typed_commands(self) -> None:
        self.assertEqual(person_request_text(stacked(["dag-ulw", "ulw-plan"], "migrate billing in parts")),
                         "/dag-ulw /ulw-plan migrate billing in parts")

    def test_a_bundle_instruction_is_read_from_its_header_only(self) -> None:
        # A loaded body below the header cannot supply an instruction the person never gave.
        bodies = {"ulw-plan": "# Plan\n\nUser instruction: ship everything now\n"}
        self.assertEqual(person_request_text(stacked(["dag-ulw", "ulw-plan"], bodies=bodies)), "/dag-ulw /ulw-plan")

    def test_a_shared_sessions_sender_prefix_comes_off_on_a_messaging_gateway(self) -> None:
        message = "[alice] " + scaffold("dag-ulw", "취소해줘")
        self.assertEqual(person_request_text(message, messaging=True), "/dag-ulw 취소해줘")
        self.assertEqual(person_request_text(message), message)

    def test_another_skills_scaffold_is_a_host_command_turn(self) -> None:
        # The person chose that skill: OMH routes nothing over it (the lead's call; the owner can reverse it).
        for message in (scaffold(FOREIGN, "rebase my open PRs", body=FOREIGN_BODY), scaffold(FOREIGN, body=FOREIGN_BODY),
                        stacked(["dag-ulw", FOREIGN], "migrate billing in parts", bodies={FOREIGN: FOREIGN_BODY}),
                        bundle("my-review", ["omh-code-review", "ulw-plan"], "check PR 5")):
            with self.subTest(message=message[:80]):
                self.assertTrue(host_command_turn(message))
                self.assertEqual(person_request_text(message), message)
                self.assertEqual(awareness_route_hint(message)["status"], "no_hint")
                route = route_chat_message(message, source="discord")["route_decision"]
                self.assertEqual(route["reason_code"], REASON_CODE_HOST_COMMAND_TURN)

    def test_an_unreadable_catalog_routes_the_invocation(self) -> None:
        # Ownership cannot be told: the invocation typed is still the person's words, never the body.
        message = scaffold(FOREIGN, "rebase my open PRs", body=FOREIGN_BODY)
        with patch.object(hermes_session_commands._skill_shortlist, "catalog_skill_labels", return_value=None):
            self.assertEqual(person_request_text(message), f"/{FOREIGN} rebase my open PRs")
            self.assertFalse(host_command_turn(message))

    def test_only_the_frames_exact_first_line_is_a_scaffold(self) -> None:
        quoted = "why does Hermes send this?\n\n" + scaffold("dag-ulw", "what is it?")
        paraphrased = scaffold("dag-ulw", "what is it?").replace("indicating they want", "meaning they want", 1)
        for message in (quoted, paraphrased):
            with self.subTest(message=message[:40]):
                self.assertEqual(person_request_text(message), message)
                self.assertFalse(host_command_turn(message))

    def test_no_typed_corpus_message_reads_as_a_scaffold(self) -> None:
        # Every typed turn routes as it did before: none of them opens with the frame.
        for case in (*ROUTING_PRECISION_CASES, *ROUTING_INTERVENTION_CASES):
            if case.message.startswith("[IMPORTANT: The user has invoked the "):
                continue
            with self.subTest(case=case.id):
                self.assertIsNone(hermes_session_commands._skill_invocation(case.message, after_sender=True))


class ScaffoldRouteTests(unittest.TestCase):
    """The rows of the investigation's table: the scaffold routes as `/<skill> <instruction>` typed."""

    def test_the_hint_is_the_typed_invocations(self) -> None:
        rows = (
            ("dag-ulw", OWNER_TURN, ("dag-ulw", "start_dag_run")),
            ("dag-ulw", "상태 보여줘", ("dag-ulw", "show_status")),
            ("dag-ulw", "what is it?", None),
            ("dag-ulw", "취소해줘", ("dag-ulw", "cancel")),
            ("dag-ulw", "주문 취소", ("dag-ulw", "ask_one_clarification")),
            ("dag-ulw", "", ("dag-ulw", "start_dag_run")),
            ("ulw-plan", "plan the billing migration", ("ulw-plan", "present_plan")),
        )
        for name, instruction, first in rows:
            with self.subTest(name=name, instruction=instruction):
                hints = _hints(scaffold(name, instruction))
                self.assertEqual(hints, _hints(f"/{name} {instruction}".strip()))
                self.assertEqual(hints[0] if hints else None, first)

    def test_the_chat_router_reads_the_typed_invocation(self) -> None:
        for name, instruction in (("dag-ulw", "migrate the billing service, its API, UI and docs, then verify"),
                                  ("dag-ulw", "what is it?"), ("ulw-plan", "plan the billing migration")):
            with self.subTest(name=name, instruction=instruction):
                routed = route_chat_message(scaffold(name, instruction), source="discord")["route_decision"]
                typed = route_chat_message(f"/{name} {instruction}", source="discord")["route_decision"]
                self.assertEqual((routed["action"], routed["selected_skill"]), (typed["action"], typed["selected_skill"]))

    def test_a_handoff_carries_the_invocation_typed_not_the_skill_body(self) -> None:
        # The body names Hermes' absolute skill directory; a handoff that carried it was refused for that path, which
        # the person never named. Gateway material before the scaffold is still handed on.
        message = scaffold("omh-code-review", "review PR 12")
        self.assertEqual(handed_on_text(message), "/omh-code-review review PR 12")
        quoted = '[Replying to: "the earlier review"]\n\n' + message
        self.assertEqual(handed_on_text(quoted), '[Replying to: "the earlier review"]\n\n/omh-code-review review PR 12')
        self.assertEqual(handed_on_text("[alice] " + message), "[alice] /omh-code-review review PR 12")
        foreign = scaffold(FOREIGN, "rebase my open PRs", body=FOREIGN_BODY)
        self.assertEqual(handed_on_text(foreign), foreign)
        self.assertEqual(handed_on_text("review PR 12"), "review PR 12")
        routed = build_chat_interaction_payload(message, source="discord")
        typed = build_chat_interaction_payload("/omh-code-review review PR 12", source="discord")
        self.assertEqual(routed["next_action"], typed["next_action"])
        self.assertEqual(routed["delegation"]["action_gate"]["outcome"], typed["delegation"]["action_gate"]["outcome"])

    def test_pre_llm_call_sends_the_define_hint_for_the_owners_turn(self) -> None:
        with homes() as home:
            result = pre_llm_call(user_message=scaffold("dag-ulw", OWNER_TURN), is_first_turn=True, session_id=PARENT,
                                  turn_id="turn-1", platform="tui", **home.hooks())
        context = str((result or {}).get("context") or "")
        self.assertIn("selected=dag-ulw", context)
        self.assertIn("omh_dag define", context)

    def test_pre_llm_call_sends_no_route_hint_over_another_skill(self) -> None:
        with homes() as home:
            result = pre_llm_call(user_message=scaffold(FOREIGN, "rebase my open PRs", body=FOREIGN_BODY),
                                  is_first_turn=True, session_id=PARENT, turn_id="turn-1", platform="tui",
                                  **home.hooks())
        self.assertNotIn("[OMH Route Hint]", str((result or {}).get("context") or ""))


MARKERLESS = {"tasks": [{"goal": "TASK: Maintain PR #1. DELIVERABLE: handoff.json", "context": "..."}]}


class DagDefineGateTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_dag_define_gate()
        reset_nudge_budget()
        self.addCleanup(reset_dag_define_gate)
        self.addCleanup(reset_nudge_budget)

    def _turn(self, home, message: str, *, turn: str = "turn-1", session: str = PARENT) -> None:
        pre_llm_call(user_message=message, is_first_turn=True, session_id=session, turn_id=turn, platform="tui",
                     **home.hooks())

    def _delegate(self, home, args: dict, *, turn: str = "turn-1", session: str = PARENT, call: str = "call-1"):
        return pre_tool_call(tool_name="delegate_task", args=args, session_id=session, turn_id=turn,
                             tool_call_id=call, **home.hooks())

    def test_a_dag_ulw_turns_first_markerless_delegate_is_sent_to_define_once(self) -> None:
        with homes() as home:
            self._turn(home, scaffold("dag-ulw", OWNER_TURN))
            first = self._delegate(home, MARKERLESS)
            second = self._delegate(home, MARKERLESS, call="call-2")
        self.assertEqual(first, {"action": "block", "message": DEFINE_FIRST_MESSAGE})
        self.assertIn("omh_dag action=define", DEFINE_FIRST_MESSAGE)
        self.assertIsNone(second)

    def test_a_typed_dag_ulw_request_arms_it_too(self) -> None:
        with homes() as home:
            self._turn(home, "/dag-ulw migrate the billing service, its API, UI and docs, then verify")
            self.assertIsNotNone(self._delegate(home, {"goal": "migrate the API"}))

    def test_what_it_lets_through(self) -> None:
        cases = {
            "a goal with its node marker": (scaffold("dag-ulw", OWNER_TURN), {"tasks": [{"goal": "api [dag:prs/api]"}]},
                                            "turn-1"),
            "a control action": (scaffold("dag-ulw", OWNER_TURN), {"action": "stop", "subagent_id": "sa-1"}, "turn-1"),
            "a later turn": (scaffold("dag-ulw", OWNER_TURN), MARKERLESS, "turn-2"),
            "a cancel turn": (scaffold("dag-ulw", "취소해줘"), MARKERLESS, "turn-1"),
            "a question turn": (scaffold("dag-ulw", "what is it?"), MARKERLESS, "turn-1"),
            "another skill's turn": (scaffold(FOREIGN, "rebase my open PRs", body=FOREIGN_BODY), MARKERLESS, "turn-1"),
            "an ordinary turn": ("fix the flaky login test", MARKERLESS, "turn-1"),
        }
        for label, (message, args, turn) in cases.items():
            with self.subTest(label), homes() as home:
                reset_dag_define_gate()
                self._turn(home, message)
                self.assertIsNone(self._delegate(home, args, turn=turn))

    def test_a_turn_without_a_turn_id_is_never_blocked(self) -> None:
        with homes() as home:
            self._turn(home, scaffold("dag-ulw", OWNER_TURN), turn="")
            self.assertIsNone(self._delegate(home, MARKERLESS, turn=""))

    def test_the_next_turn_replaces_the_record(self) -> None:
        with homes() as home:
            self._turn(home, scaffold("dag-ulw", OWNER_TURN))
            self._turn(home, "fix the flaky login test", turn="turn-2")
            self.assertIsNone(self._delegate(home, MARKERLESS))
            self.assertIsNone(self._delegate(home, MARKERLESS, turn="turn-2"))

    def test_a_conversation_with_a_run_blocks_mid_run_instead(self) -> None:
        # The start-turn gate stands down once a run exists — the mid-run gate is what answers there.
        with homes() as home:
            defined = json.loads(dag_tool.omh_dag_handler({"action": "define", "run": "prs", "nodes": [
                {"id": "pr1", "label": "PR 1", "category": "quick", "prompt": "TASK: x\nVERIFY: `true`",
                 "depends_on": [], "write_scope": ["a.py"]},
                {"id": "verify", "label": "Verify", "category": "quick", "prompt": "TASK: v\nVERIFY: `true`",
                 "depends_on": ["pr1"], "write_scope": []},
            ]}, session_id=PARENT))
            self.assertNotEqual(defined.get("status"), "refused", defined)
            self._turn(home, scaffold("dag-ulw", OWNER_TURN))
            first = self._delegate(home, MARKERLESS)
            second = self._delegate(home, MARKERLESS, call="call-2")
        self.assertEqual(first, {"action": "block", "message": mid_run_message("prs")})
        self.assertIsNone(second)


DAG_NODES = [
    {"id": "pr1", "label": "PR 1", "category": "quick", "prompt": "TASK: x\nVERIFY: `true`",
     "depends_on": [], "write_scope": ["a.py"]},
    {"id": "verify", "label": "Verify", "category": "quick", "prompt": "TASK: v\nVERIFY: `true`",
     "depends_on": ["pr1"], "write_scope": []},
]


def _define(nodes=None, run: str = "prs") -> dict:
    return json.loads(dag_tool.omh_dag_handler(
        {"action": "define", "run": run, "nodes": nodes if nodes is not None else DAG_NODES}, session_id=PARENT))


def _write_handoff(home, run: str, node: str) -> None:
    path = dag_run.handoff_path(home.omh, PARENT, run, node)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("done", encoding="utf-8")


class DagMidRunGateTests(unittest.TestCase):
    """The mid-run gate: while a conversation's dag run is active, a markerless spawn is sent back to `omh_dag`
    once per turn — any turn, no dag-ulw hint needed — and a resend goes through."""

    def setUp(self) -> None:
        reset_dag_define_gate()
        reset_nudge_budget()
        self.addCleanup(reset_dag_define_gate)
        self.addCleanup(reset_nudge_budget)

    def _turn(self, home, message: str, *, turn: str = "turn-1", session: str = PARENT) -> None:
        pre_llm_call(user_message=message, is_first_turn=True, session_id=session, turn_id=turn, platform="tui",
                     **home.hooks())

    def _delegate(self, home, args: dict, *, turn: str = "turn-1", session: str = PARENT, call: str = "call-1"):
        return pre_tool_call(tool_name="delegate_task", args=args, session_id=session, turn_id=turn,
                             tool_call_id=call, **home.hooks())

    def test_a_markerless_spawn_inside_an_active_run_blocks_once_then_passes(self) -> None:
        with homes() as home:
            self.assertNotEqual(_define().get("status"), "refused")
            note_turn(PARENT, "turn-1", starts_run=False)
            first = self._delegate(home, MARKERLESS)
            second = self._delegate(home, MARKERLESS, call="call-2")
            third = self._delegate(home, MARKERLESS, call="call-3")
        self.assertEqual(first, {"action": "block", "message": mid_run_message("prs")})
        self.assertIn("dag run prs", first["message"])
        self.assertIn("omh_dag action=status", first["message"])
        self.assertIn("send this call again and it goes through", first["message"])
        self.assertIsNone(second)
        self.assertIsNone(third)

    def test_each_new_turn_blocks_once_again(self) -> None:
        with homes() as home:
            self.assertNotEqual(_define().get("status"), "refused")
            note_turn(PARENT, "turn-1", starts_run=False)
            self.assertIsNotNone(self._delegate(home, MARKERLESS))
            self.assertIsNone(self._delegate(home, MARKERLESS, call="call-2"))
            note_turn(PARENT, "turn-2", starts_run=False)
            self.assertIsNotNone(self._delegate(home, MARKERLESS, turn="turn-2"))
            self.assertIsNone(self._delegate(home, MARKERLESS, turn="turn-2", call="call-4"))

    def test_a_turn_without_a_hint_blocks_too(self) -> None:
        with homes() as home:
            self.assertNotEqual(_define().get("status"), "refused")
            pre_llm_call(user_message="fix the flaky login test", is_first_turn=True, session_id=PARENT,
                         turn_id="turn-1", platform="tui", **home.hooks())
            self.assertIsNotNone(self._delegate(home, MARKERLESS))

    def test_what_the_mid_run_gate_lets_through(self) -> None:
        with homes() as home:
            self.assertNotEqual(_define().get("status"), "refused")
            cases = {
                "a goal with its node marker": {"tasks": [{"goal": "api [dag:prs/api]"}]},
                "a marked task among plain ones": {"tasks": [{"goal": "plain"}, {"goal": "x [dag:prs/verify]"}]},
                "a control action": {"action": "stop", "subagent_id": "sa-1"},
                "list": {"action": "list"},
                "steer": {"action": "steer", "subagent_id": "sa-1"},
            }
            for label, args in cases.items():
                with self.subTest(label):
                    note_turn(PARENT, "turn-1", starts_run=False)
                    self.assertIsNone(self._delegate(home, args))

    def test_a_finished_run_holds_no_turn(self) -> None:
        for end in ("done", "cancelled"):
            with self.subTest(end=end), homes() as home:
                self.assertNotEqual(_define().get("status"), "refused")
                if end == "done":
                    for node_id in ("pr1", "verify"):
                        _write_handoff(home, "prs", node_id)
                        settled = json.loads(dag_tool.omh_dag_handler(
                            {"action": "settle", "run": "prs", "node": node_id, "outcome": "accepted"},
                            session_id=PARENT))
                        self.assertNotEqual(settled.get("status"), "refused", settled)
                else:
                    call = json.loads(dag_tool.omh_dag_handler({"action": "cancel", "run": "prs"}, session_id=PARENT))
                    self.assertNotEqual(call.get("status"), "refused", call)
                note_turn(PARENT, "turn-1", starts_run=False)
                self.assertIsNone(self._delegate(home, MARKERLESS))

    def test_no_run_means_no_mid_run_block(self) -> None:
        with homes() as home:
            note_turn(PARENT, "turn-1", starts_run=False)
            self.assertIsNone(self._delegate(home, MARKERLESS))

    def test_an_unreadable_run_store_is_no_active_run(self) -> None:
        with homes() as home:
            self.assertNotEqual(_define().get("status"), "refused")  # a readable store holds the active run `prs`
            note_turn(PARENT, "turn-1", starts_run=False)
            # The same turn, the same session: only the run store raising on read differs, and that is no
            # evidence of an active run (`_active_run` fails open) — the reader is reached, and the spawn
            # a readable store would have held goes through.
            with patch.object(dag_run, "session_runs", side_effect=sqlite3.DatabaseError("store is closed")) as reads:
                self.assertIsNone(self._delegate(home, MARKERLESS))
            self.assertTrue(reads.called, "the failing store read is what this fail-open case pins")

    def test_a_delegated_childs_spawn_is_never_held(self) -> None:
        child = "20261020_140300_child"
        with homes() as home:
            self.assertNotEqual(_define().get("status"), "refused")
            subagent_start(parent_session_id=PARENT, child_session_id=child, **home.hooks())
            note_turn(child, "turn-1", starts_run=False)
            self.assertIsNone(self._delegate(home, MARKERLESS, session=child))

    def test_a_delegated_child_never_records_a_dag_turn(self) -> None:
        child = "20261020_140300_child"
        with homes() as home:
            subagent_start(parent_session_id=PARENT, child_session_id=child, **home.hooks())
            self._turn(home, "/dag-ulw migrate the billing service, its API, UI and docs, then verify", session=child)
            self.assertIsNone(self._delegate(home, MARKERLESS, session=child))


class DagStatusWithoutRunTests(unittest.TestCase):
    def test_status_with_no_run_names_define_as_the_next_call(self) -> None:
        with homes():
            unnamed = json.loads(dag_tool.omh_dag_handler({"action": "status"}, session_id=PARENT))
            named = json.loads(dag_tool.omh_dag_handler({"action": "status", "run": "prs"}, session_id=PARENT))
        self.assertEqual((unnamed["status"], unnamed["reason"]), ("refused", "run_not_found"))
        self.assertEqual(unnamed["say"], dag_tool.NO_RUN_YET_SAY)
        self.assertIn("omh_dag action=define", unnamed["say"])
        self.assertEqual(named["reason"], "run_not_found")
        self.assertIn("by that id", named["say"])


if __name__ == "__main__":
    unittest.main()

"""Contracts for the typed Loop operation service and the `omh_loop` tool.

The point of the service is that `omh loop ...` and `omh_loop` cannot mean
different things, so most of this file is behavioural parity against real
temporary stores rather than assertions about mocks: the same action is driven
through both adapters on two loops in one OMH home, and the resulting status
cards are compared field by field once the values that must differ between two
independent loops (ids, timestamps) are neutralized.

The rest pins the three places a boundary invites drift:

- the manifest, which is the only place the action vocabulary exists, against
  the CLI keys each action actually prints and the branches that implement it;
- the literals the plugin bundle restates because it must stay loadable with
  no installed `omh` package, against the producers they copy;
- the fail-closed gates, which are the whole reason a model-facing mutation is
  safe: no host identity, no submitted revision, or a caller-named store and
  the call is refused before anything is written.
"""

from __future__ import annotations

import ast
import copy
import importlib
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh import loop_bridge  # noqa: E402
from omh.plugin_bundle.omh.metadata import PROVIDED_TOOLS, TOOL_FILE_STEMS  # noqa: E402
from omh.plugin_bundle.omh.tools import BUILTIN_TOOL_NAMES, builtin_tool_schemas  # noqa: E402
from omh.plugin_bundle.omh.tools.loop_tool import OMH_LOOP_SCHEMA, omh_loop_handler  # noqa: E402
from omh.workflows.goal_loop import (  # noqa: E402
    LOOP_ACTIONS,
    LOOP_EXECUTOR_OPTION_IDS,
    PERMISSION_PROFILES,
)
from omh.workflows.loop_operations import (  # noqa: E402
    LOOP_OPERATION_ACTIONS,
    LOOP_OPERATION_CLAIM_BOUNDARY,
    LOOP_OPERATION_ERROR_CODES,
    LOOP_OPERATION_RESULT_SCHEMA,
    LOOP_OPERATION_SPECS,
    LOOP_TOOL_ACTIONS,
    FIELD_KINDS,
    LoopOperationRequest,
    loop_operation_manifest,
    run_loop_operation,
)

_REPO = Path(__file__).resolve().parents[1]
_BUNDLE = _REPO / "src" / "plugin_bundle" / "omh"
_SERVICE = _REPO / "src" / "workflows" / "loop_operations.py"

GOAL = "Make OMH a credible Hermes workflow pack with install, docs, QA, and feedback cycles."
REFRAME = "Ship one reviewed install-path fix with docs and a passing QA gate."
SESSION = "hermes-session-1"

# Values that are unique per loop or per call by construction. Comparing two
# independently created loops means neutralizing exactly these and nothing
# else; anything further would let a real divergence pass as noise.
_VOLATILE_KEYS = frozenset(
    {
        # Not unique per loop but unique per render: both cards derive it from
        # the same fixed `observed_at` minus `datetime.now()`, so the two values
        # differ by however long the CLI subprocess took. `assert_card_parity`
        # keeps what equality was checking here -- see the age assertion there.
        "age_seconds",
        "applied_mutations",
        "attempt_id",
        "authority_envelope_sha256",
        "created_at",
        "cycle_id",
        "dispatch_attempt_id",
        "driver_id",
        "evaluated_at",
        # Derived from the loop's own handoff command, which names the loop id.
        "goal_command_sha256",
        "last_queue_id",
        "last_tick_at",
        "loop_id",
        "observation_id",
        "observed_at",
        "queue_id",
        "record_revision",
        "source",
        "transition_id",
        "updated_at",
    }
)
_CLI_LOOP = "parity-cli-loop"
_TOOL_LOOP = "parity-tool-loop"


def scrub(value: object) -> object:
    """Drop or neutralize everything two independent loops must differ on."""
    if isinstance(value, str):
        return value.replace(_CLI_LOOP, "<loop>").replace(_TOOL_LOOP, "<loop>")
    if isinstance(value, dict):
        return {key: scrub(item) for key, item in value.items() if key not in _VOLATILE_KEYS}
    if isinstance(value, list):
        return [scrub(item) for item in value]
    return value


def _ages(value: object, path: str = "status_card") -> list[tuple[str, object, object]]:
    """Every `age_seconds` in the card with the stamp it was derived from.

    Each entry is (path, age, stamp), the stamp being the `observed_at`
    sitting beside it. The producer computes the age from that stamp or
    returns `None` when there is none, so carrying both is what lets a
    caller check the rule instead of only the two ages against each other.
    Paths rather than bare values, so a mismatch names where the two cards
    stopped agreeing instead of reporting two lists of numbers.
    """
    found: list[tuple[str, object, object]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "age_seconds":
                found.append((f"{path}.{key}", item, value.get("observed_at")))
            else:
                found.extend(_ages(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_ages(item, f"{path}[{index}]"))
    return found


def tool(**args: object) -> dict:
    """Call the tool the way Hermes does: session id as a dispatch keyword."""
    session = args.pop("session_id", SESSION)
    return json.loads(omh_loop_handler(dict(args), session_id=session))


class _LoopHome(unittest.TestCase):
    """One temporary OMH home shared by a CLI loop and a tool loop."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.omh_home = root / "omh"
        self.hermes_home = root / "hermes"
        self.hermes_home.mkdir(parents=True)
        self.base = ["--omh-home", str(self.omh_home), "--hermes-home", str(self.hermes_home)]
        patch = mock.patch.dict(
            os.environ, {"OMH_HOME": str(self.omh_home), "HERMES_HOME": str(self.hermes_home)}
        )
        patch.start()
        self.addCleanup(patch.stop)

    def cli(self, *args: str) -> dict:
        status, stdout, stderr = run_cli(self.base + list(args))
        self.assertEqual(status, 0, f"{args} failed: {stderr}")
        return json.loads(stdout)

    def cli_error(self, *args: str) -> tuple[int, str]:
        # argparse refuses an unknown flag or an out-of-choices value by
        # raising SystemExit rather than returning, and that is one of the
        # refusals these cases compare the tool against.
        try:
            status, _stdout, stderr = run_cli(self.base + list(args))
        except SystemExit as exit_code:
            return int(exit_code.code or 0), "argparse refused the arguments"
        return status, stderr

    def revision(self, loop_id: str) -> int:
        return int(tool(action="status", loop_id=loop_id)["record_revision"])

    def start_both(self) -> None:
        self.cli(
            "loop", "start",
            "--goal-summary", GOAL,
            "--goal-reframe", REFRAME,
            "--criterion", "install path fixed",
            "--loop-id", _CLI_LOOP,
        )
        started = tool(
            action="start",
            goal_summary=GOAL,
            goal_reframe=REFRAME,
            success_criteria=["install path fixed"],
            loop_id=_TOOL_LOOP,
        )
        self.assertEqual(started["status"], "ok", started)


class ManifestContractTests(unittest.TestCase):
    """The manifest is the vocabulary; nothing may exist outside it."""

    def test_every_action_is_implemented_by_its_own_branch(self) -> None:
        source = ast.parse(_SERVICE.read_text(encoding="utf-8"))
        run = next(
            node
            for node in ast.walk(source)
            if isinstance(node, ast.FunctionDef) and node.name == "_run"
        )
        branched = {
            node.comparators[0].value
            for node in ast.walk(run)
            if isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Name)
            and node.left.id == "action"
            and isinstance(node.comparators[0], ast.Constant)
        }
        self.assertEqual(branched, set(LOOP_OPERATION_ACTIONS))

    def test_tool_actions_are_a_subset_declared_in_one_place(self) -> None:
        self.assertTrue(set(LOOP_TOOL_ACTIONS) <= set(LOOP_OPERATION_ACTIONS))
        self.assertEqual(
            set(LOOP_TOOL_ACTIONS),
            {action for action, spec in LOOP_OPERATION_SPECS.items() if spec.native_tool},
        )

    def test_the_manifest_covers_the_lifecycle_the_issue_names(self) -> None:
        # Creation or assessment, status, feedback or steering, permission
        # updates, one legal advancement, driver observation, and an
        # evidence-bearing completion update.
        self.assertEqual(
            set(LOOP_TOOL_ACTIONS),
            {
                "assess",
                "start",
                "status",
                "feedback",
                "permit",
                "run_once",
                "goal_driver_observe",
                "queue_observe",
            },
        )

    def test_field_kinds_and_defaults_are_closed(self) -> None:
        for action, spec in LOOP_OPERATION_SPECS.items():
            for item in spec.fields:
                with self.subTest(action=action, field=item.name):
                    self.assertIn(item.kind, FIELD_KINDS)
                    self.assertTrue(item.description.strip())
                    if item.enum:
                        self.assertIn(item.kind, {"text", "text_list"})

    def test_one_field_name_never_means_two_shapes(self) -> None:
        kinds: dict[str, str] = {}
        for spec in LOOP_OPERATION_SPECS.values():
            for item in spec.fields:
                self.assertEqual(kinds.setdefault(item.name, item.kind), item.kind, item.name)

    def test_mutating_actions_that_touch_an_existing_loop_accept_the_guard(self) -> None:
        for action, spec in LOOP_OPERATION_SPECS.items():
            if spec.mutating and spec.requires_loop_id:
                with self.subTest(action=action):
                    self.assertTrue(spec.revision_guard)

    def test_error_codes_are_a_closed_sorted_set(self) -> None:
        self.assertEqual(list(LOOP_OPERATION_ERROR_CODES), sorted(LOOP_OPERATION_ERROR_CODES))
        self.assertEqual(len(set(LOOP_OPERATION_ERROR_CODES)), len(LOOP_OPERATION_ERROR_CODES))

    def test_manifest_payload_is_json_serializable(self) -> None:
        payload = loop_operation_manifest()
        self.assertEqual(
            [row["action"] for row in payload["actions"]], list(LOOP_OPERATION_ACTIONS)
        )
        json.dumps(payload)


class CliArtifactShapeTests(_LoopHome):
    """Each action's declared artifacts are the keys its CLI command prints."""

    def test_declared_artifacts_match_what_the_cli_prints(self) -> None:
        self.start_both()
        printed = {
            "assess": self.cli("loop", "assess", GOAL),
            "start_card": self.cli("loop", "start-card", GOAL),
            "status": self.cli("loop", "status", "--loop", _CLI_LOOP),
            "queue_list": self.cli("loop", "queue", "list", "--loop", _CLI_LOOP),
            "goal_driver_handoff": self.cli(
                "loop", "goal-driver-handoff", "--loop", _CLI_LOOP
            ),
            "migrate_driver": self.cli("loop", "migrate-driver", "--loop", _CLI_LOOP),
            "queue_narrate": self.cli("loop", "queue", "narrate", "--loop", _CLI_LOOP),
        }
        for action, payload in printed.items():
            spec = LOOP_OPERATION_SPECS[action]
            if not spec.artifacts:
                continue
            with self.subTest(action=action):
                self.assertEqual(sorted(payload), sorted(spec.artifacts))

    def test_status_without_a_loop_id_still_lists(self) -> None:
        self.start_both()
        listing = self.cli("loop", "status")
        self.assertEqual(sorted(listing), ["invalid_loops", "loops"])
        self.assertEqual(
            sorted(row["loop_id"] for row in listing["loops"]), sorted([_CLI_LOOP, _TOOL_LOOP])
        )

    def test_queue_inspect_still_prints_its_payload_unwrapped(self) -> None:
        self.start_both()
        self.cli("loop", "run-once", "--loop", _CLI_LOOP)
        queue_id = self.cli("loop", "queue", "list", "--loop", _CLI_LOOP)["loop_queue"]["queue"][0][
            "queue_id"
        ]
        payload = self.cli("loop", "queue", "inspect", "--loop", _CLI_LOOP, "--queue", queue_id)
        self.assertNotIn("loop", payload)
        self.assertEqual(str(payload["queue_item"]["queue_id"]), queue_id)


class ToolCliParityTests(_LoopHome):
    """The same action through both adapters reaches the same loop state."""

    def assert_card_parity(self, cli_payload: dict, tool_payload: dict) -> None:
        self.assertEqual(tool_payload.get("status"), "ok", tool_payload)
        self.assert_age_parity(cli_payload["status_card"], tool_payload["status_card"])
        self.assertEqual(
            scrub(cli_payload["status_card"]), scrub(tool_payload["status_card"])
        )

    def assert_age_parity(self, cli_card: object, tool_card: object) -> None:
        """What `age_seconds` was checking, minus the race on when it was read.

        Scrubbing the key would drop the check that both adapters compute an
        age at all, which is the part a divergence would show up in; only the
        exact second is unstable. So compare the fields position by position
        for shape instead of value: an adapter that stopped emitting one, or
        emitted `None` where the other emitted a number, still fails.
        """
        cli_ages, tool_ages = _ages(cli_card), _ages(tool_card)
        self.assertEqual(
            [path for path, _, _ in cli_ages],
            [path for path, _, _ in tool_ages],
            "the two cards carry age_seconds at different places",
        )
        for (path, cli_age, cli_stamp), (_, tool_age, tool_stamp) in zip(cli_ages, tool_ages):
            for label, age, stamp in (("cli", cli_age, cli_stamp), ("tool", tool_age, tool_stamp)):
                if stamp is None:
                    self.assertIsNone(age, f"{path}: {label} aged a record with no stamp")
                    continue
                self.assertIsInstance(age, int, f"{path}: {label} did not age a stamped record")
                self.assertGreaterEqual(age, 0, f"{path}: {label} age is negative")

    def test_assess_is_identical(self) -> None:
        self.assertEqual(
            scrub(self.cli("loop", "assess", GOAL)["loopability_assessment"]),
            scrub(tool(action="assess", message=GOAL)["loopability_assessment"]),
        )

    def test_start_reaches_the_same_card(self) -> None:
        cli_started = self.cli(
            "loop", "start",
            "--goal-summary", GOAL,
            "--goal-reframe", REFRAME,
            "--criterion", "install path fixed",
            "--loop-id", _CLI_LOOP,
        )
        tool_started = tool(
            action="start",
            goal_summary=GOAL,
            goal_reframe=REFRAME,
            success_criteria=["install path fixed"],
            loop_id=_TOOL_LOOP,
        )
        self.assert_card_parity(cli_started, tool_started)
        self.assertEqual(tool_started["record_revision"], 1)
        self.assertTrue(tool_started["mutation_applied"])

    def test_start_records_the_tool_as_the_origin(self) -> None:
        self.start_both()
        self.assertEqual(self.cli("loop", "status", "--loop", _CLI_LOOP)["loop"]["source"], "omh")
        self.assertEqual(
            self.cli("loop", "status", "--loop", _TOOL_LOOP)["loop"]["source"],
            loop_bridge.LOOP_TOOL_SOURCE,
        )

    def test_status_reaches_the_same_card_and_lists_the_same_loops(self) -> None:
        self.start_both()
        self.assert_card_parity(
            self.cli("loop", "status", "--loop", _CLI_LOOP),
            tool(action="status", loop_id=_TOOL_LOOP),
        )
        listed = tool(action="status")
        self.assertEqual(
            sorted(row["loop_id"] for row in listed["loops"]), sorted([_CLI_LOOP, _TOOL_LOOP])
        )

    def test_run_once_advances_both_the_same_way(self) -> None:
        self.start_both()
        cli_run = self.cli("loop", "run-once", "--loop", _CLI_LOOP)
        tool_run = tool(
            action="run_once",
            loop_id=_TOOL_LOOP,
            expected_revision=self.revision(_TOOL_LOOP),
        )
        self.assertEqual(cli_run["run_once"]["outcome"], "created_tick")
        self.assertEqual(scrub(cli_run["run_once"]), scrub(tool_run["run_once"]))
        self.assert_card_parity(cli_run, tool_run)

    def test_run_once_refuses_a_second_advancement_the_same_way(self) -> None:
        self.start_both()
        self.cli("loop", "run-once", "--loop", _CLI_LOOP)
        tool(action="run_once", loop_id=_TOOL_LOOP, expected_revision=self.revision(_TOOL_LOOP))
        cli_again = self.cli("loop", "run-once", "--loop", _CLI_LOOP)
        tool_again = tool(
            action="run_once",
            loop_id=_TOOL_LOOP,
            expected_revision=self.revision(_TOOL_LOOP),
        )
        self.assertEqual(cli_again["run_once"]["outcome"], "pending_queue_exists")
        self.assertEqual(scrub(cli_again["run_once"]), scrub(tool_again["run_once"]))

    def test_feedback_reaches_the_same_card(self) -> None:
        self.start_both()
        self.assert_card_parity(
            self.cli(
                "loop", "feedback", "--loop", _CLI_LOOP,
                "--observed-artifact", "docs/INSTALLATION.md",
                "--internal-gap", "QA gate missing",
            ),
            tool(
                action="feedback",
                loop_id=_TOOL_LOOP,
                observed_artifacts=["docs/INSTALLATION.md"],
                internal_gap="QA gate missing",
                expected_revision=self.revision(_TOOL_LOOP),
            ),
        )

    def test_feedback_external_wait_reaches_the_same_card(self) -> None:
        self.start_both()
        self.assert_card_parity(
            self.cli(
                "loop", "feedback", "--loop", _CLI_LOOP,
                "--external-wait", "waiting on a maintainer review",
            ),
            tool(
                action="feedback",
                loop_id=_TOOL_LOOP,
                external_wait="waiting on a maintainer review",
                expected_revision=self.revision(_TOOL_LOOP),
            ),
        )

    def test_permit_reaches_the_same_envelope(self) -> None:
        self.start_both()
        self.assert_card_parity(
            self.cli(
                "loop", "permit", "--loop", _CLI_LOOP,
                "--allow-action", "research", "--forbid-action", "merge",
            ),
            tool(
                action="permit",
                loop_id=_TOOL_LOOP,
                allow_actions=["research"],
                forbid_actions=["merge"],
                expected_revision=self.revision(_TOOL_LOOP),
            ),
        )

    def test_queue_observe_reaches_the_same_card(self) -> None:
        self.start_both()
        self.cli("loop", "run-once", "--loop", _CLI_LOOP)
        tool(action="run_once", loop_id=_TOOL_LOOP, expected_revision=self.revision(_TOOL_LOOP))
        cli_queue = self.cli("loop", "queue", "list", "--loop", _CLI_LOOP)["loop_queue"]["queue"][0]
        tool_queue = self.cli("loop", "queue", "list", "--loop", _TOOL_LOOP)["loop_queue"]["queue"][0]
        self.assert_card_parity(
            self.cli(
                "loop", "queue", "observe", "--loop", _CLI_LOOP,
                "--queue", str(cli_queue["queue_id"]),
                "--evidence-ref", "https://example.invalid/run/1",
                "--summary", "observed the prepared step",
            ),
            tool(
                action="queue_observe",
                loop_id=_TOOL_LOOP,
                queue_id=str(tool_queue["queue_id"]),
                evidence_refs=["https://example.invalid/run/1"],
                summary="observed the prepared step",
                expected_revision=self.revision(_TOOL_LOOP),
            ),
        )

    def test_goal_driver_observe_reaches_the_same_card(self) -> None:
        self.start_both()
        cli_handoff = self.cli("loop", "goal-driver-handoff", "--loop", _CLI_LOOP)
        tool_handoff = self.cli("loop", "goal-driver-handoff", "--loop", _TOOL_LOOP)

        def observation(loop_id: str, digest: str) -> dict:
            session = "hermes-session-parity"
            return {
                "schema_version": "loop_goal_driver_observation/v1",
                "observation_id": "native-goal-parity-turns-1-2",
                "loop_id": loop_id,
                "session_ref": session,
                "goal_command_sha256": digest,
                "observation_source": "hermes_host",
                "observed_at": "2026-09-14T12:00:00Z",
                "activation": {
                    "status": "observed",
                    "evidence_refs": ["hermes:session-parity:goal-accepted"],
                },
                "turns": [
                    {
                        "turn_index": 1,
                        "session_ref": session,
                        "from_phase": "interview",
                        "to_phase": "plan",
                        "phase_gate": "goal_contract_observed",
                        "turn_ended_evidence_refs": ["hermes:session-parity:turn-1-ended"],
                        "phase_gate_evidence_refs": ["wrapper:goal-contract:observed"],
                    },
                    {
                        "turn_index": 2,
                        "session_ref": session,
                        "from_phase": "plan",
                        "to_phase": "research",
                        "phase_gate": "plan_observed",
                        "turn_ended_evidence_refs": ["hermes:session-parity:turn-2-ended"],
                        "phase_gate_evidence_refs": ["artifact:bounded-plan:sha256:abc123"],
                    },
                ],
                "summary": "Hermes accepted the goal and continued two turns.",
                "privacy": "metadata_only",
            }

        cli_path = Path(self._tmp.name) / "cli-observation.json"
        cli_path.write_text(
            json.dumps(
                observation(_CLI_LOOP, str(cli_handoff["goal_driver_handoff"]["goal_command_sha256"]))
            ),
            encoding="utf-8",
        )
        cli_result = self.cli(
            "loop", "goal-driver-observe", "--loop", _CLI_LOOP, "--observation-json", str(cli_path)
        )
        tool_result = tool(
            action="goal_driver_observe",
            loop_id=_TOOL_LOOP,
            driver_observation=observation(
                _TOOL_LOOP, str(tool_handoff["goal_driver_handoff"]["goal_command_sha256"])
            ),
            expected_revision=self.revision(_TOOL_LOOP),
        )
        self.assert_card_parity(cli_result, tool_result)
        self.assertEqual(
            scrub(cli_result["native_goal_status"]), scrub(tool_result["native_goal_status"])
        )
        self.assertEqual(
            scrub(cli_result["goal_driver_observation"]),
            scrub(tool_result["goal_driver_observation"]),
        )


class ToolEnvelopeTests(_LoopHome):
    """Every result carries the same envelope and the same claim boundary."""

    def test_success_envelope_shape(self) -> None:
        self.start_both()
        payload = tool(action="status", loop_id=_TOOL_LOOP)
        for key in (
            "schema_version",
            "status",
            "action",
            "loop_id",
            "record_revision",
            "mutation_applied",
            "warnings",
            "next_actions",
            "prepared_versus_observed",
            "claim_boundary",
            "session_binding",
            "plugin_tool",
        ):
            self.assertIn(key, payload)
        self.assertEqual(payload["schema_version"], LOOP_OPERATION_RESULT_SCHEMA)
        self.assertEqual(payload["plugin_tool"], "omh_loop")
        self.assertEqual(payload["claim_boundary"], LOOP_OPERATION_CLAIM_BOUNDARY)

    def test_a_read_never_claims_a_transition(self) -> None:
        self.start_both()
        boundary = tool(action="status", loop_id=_TOOL_LOOP)["prepared_versus_observed"]
        self.assertFalse(boundary["omh_transition_recorded"])
        self.assertFalse(boundary["mutating_action"])

    def test_a_mutation_claims_an_omh_transition_and_nothing_downstream(self) -> None:
        self.start_both()
        boundary = tool(
            action="feedback",
            loop_id=_TOOL_LOOP,
            internal_gap="QA gate missing",
            expected_revision=self.revision(_TOOL_LOOP),
        )["prepared_versus_observed"]
        self.assertTrue(boundary["omh_transition_recorded"])
        for key in (
            "executor_dispatched",
            "implementation_observed",
            "review_observed",
            "ci_observed",
            "merge_ready",
            "merged",
        ):
            self.assertFalse(boundary[key], key)

    def test_the_stored_cycle_is_never_published_to_the_model(self) -> None:
        self.start_both()
        for payload in (
            tool(action="status", loop_id=_TOOL_LOOP),
            tool(action="run_once", loop_id=_TOOL_LOOP, expected_revision=self.revision(_TOOL_LOOP)),
        ):
            self.assertNotIn("loop", payload)
            self.assertIn("status_card", payload)

    def test_next_actions_route_loop_state_into_this_vocabulary(self) -> None:
        self.start_both()
        rows = tool(action="status", loop_id=_TOOL_LOOP)["next_actions"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["loop_next_action"], "continue_loop")
        self.assertEqual(rows[0]["omh_loop_action"], "run_once")
        self.assertEqual(rows[0]["cli"], "omh loop run-once")

    def test_the_session_binding_block_names_the_configured_home(self) -> None:
        self.start_both()
        binding = tool(action="status", loop_id=_TOOL_LOOP)["session_binding"]
        self.assertEqual(
            binding,
            {
                "bound": True,
                "session_ref": SESSION,
                "home_source": "configured_omh_home",
                "caller_selected_root": False,
            },
        )


class FailClosedTests(_LoopHome):
    """Nothing is written when identity, revision, or the store is in doubt."""

    def assert_error(self, payload: dict, code: str) -> None:
        self.assertEqual(payload["status"], "error", payload)
        self.assertEqual(payload["error"], code, payload)
        self.assertIn(payload["error"], LOOP_OPERATION_ERROR_CODES)
        self.assertFalse(payload["mutation_applied"])
        self.assertTrue(payload["error_detail"].strip())

    def test_a_mutation_without_host_identity_is_refused(self) -> None:
        self.start_both()
        before = self.revision(_TOOL_LOOP)
        payload = tool(
            action="feedback",
            loop_id=_TOOL_LOOP,
            internal_gap="QA gate missing",
            expected_revision=before,
            session_id="",
        )
        self.assert_error(payload, "identity_required")
        self.assertEqual(self.revision(_TOOL_LOOP), before)

    def test_a_read_without_host_identity_still_works(self) -> None:
        self.start_both()
        self.assertEqual(tool(action="status", loop_id=_TOOL_LOOP, session_id="")["status"], "ok")

    def test_a_mutation_without_a_submitted_revision_is_refused(self) -> None:
        self.start_both()
        before = self.revision(_TOOL_LOOP)
        self.assert_error(
            tool(action="feedback", loop_id=_TOOL_LOOP, internal_gap="x"), "revision_required"
        )
        self.assertEqual(self.revision(_TOOL_LOOP), before)

    def test_start_needs_no_revision_because_it_has_no_prior_one(self) -> None:
        self.assertEqual(
            tool(
                action="start",
                goal_summary=GOAL,
                goal_reframe=REFRAME,
                success_criteria=["install path fixed"],
                loop_id=_TOOL_LOOP,
            )["status"],
            "ok",
        )

    def test_a_stale_revision_is_refused_without_writing(self) -> None:
        self.start_both()
        stale = self.revision(_TOOL_LOOP)
        tool(
            action="feedback",
            loop_id=_TOOL_LOOP,
            internal_gap="first",
            expected_revision=stale,
        )
        moved = self.revision(_TOOL_LOOP)
        self.assert_error(
            tool(
                action="feedback",
                loop_id=_TOOL_LOOP,
                internal_gap="second",
                expected_revision=stale,
            ),
            "stale_revision",
        )
        self.assertEqual(self.revision(_TOOL_LOOP), moved)

    def test_a_replayed_mutation_id_applies_once(self) -> None:
        self.start_both()
        revision = self.revision(_TOOL_LOOP)
        first = tool(
            action="feedback",
            loop_id=_TOOL_LOOP,
            internal_gap="QA gate missing",
            expected_revision=revision,
            mutation_id="mutation-1",
        )
        second = tool(
            action="feedback",
            loop_id=_TOOL_LOOP,
            internal_gap="QA gate missing",
            expected_revision=revision,
            mutation_id="mutation-1",
        )
        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "ok")
        self.assertEqual(second["record_revision"], first["record_revision"])
        self.assertFalse(second["mutation_applied"])

    def test_every_root_selecting_argument_is_refused_by_name(self) -> None:
        self.start_both()
        for name in loop_bridge.ROOT_SELECTING_ARGS:
            with self.subTest(argument=name):
                payload = tool(**{"action": "status", "loop_id": _TOOL_LOOP, name: "/tmp/elsewhere"})
                self.assertEqual(payload["status"], "error")
                self.assertIn(payload["error"], LOOP_OPERATION_ERROR_CODES)
                self.assertIn(name, payload["error_detail"])

    def test_the_schema_declares_no_store_selecting_field(self) -> None:
        for name in loop_bridge.ROOT_SELECTING_ARGS:
            self.assertNotIn(name, OMH_LOOP_SCHEMA["parameters"]["properties"])

    def test_an_unknown_action_names_the_supported_ones(self) -> None:
        payload = tool(action="merge_everything")
        self.assert_error(payload, "unknown_action")
        self.assertEqual(payload["supported_actions"], list(loop_bridge.LOOP_TOOL_ACTIONS))

    def test_an_operator_only_action_is_not_reachable_from_the_tool(self) -> None:
        self.start_both()
        for action in set(LOOP_OPERATION_ACTIONS) - set(LOOP_TOOL_ACTIONS):
            with self.subTest(action=action):
                self.assert_error(tool(action=action, loop_id=_TOOL_LOOP), "unknown_action")

    def test_the_service_refuses_an_unknown_field_before_any_write(self) -> None:
        # The service half of the guard. The tool half is
        # ForeignFieldTests below, and neither one covers the other: the
        # bridge chooses which names reach the service at all.
        self.start_both()
        before = self.revision(_TOOL_LOOP)
        request = LoopOperationRequest(
            action="feedback",
            loop_id=_TOOL_LOOP,
            fields={"internal_gap": "x", "not_a_field": "y"},
            expected_revision=before,
        )
        with self.assertRaises(ValueError) as raised:
            run_loop_operation(self.paths(), request)
        self.assertIn("not_a_field", str(raised.exception))
        self.assertEqual(self.revision(_TOOL_LOOP), before)

    def test_a_malformed_value_is_refused_before_any_write(self) -> None:
        self.start_both()
        before = self.revision(_TOOL_LOOP)
        payload = tool(
            action="permit",
            loop_id=_TOOL_LOOP,
            allow_actions=["not_a_loop_action"],
            expected_revision=before,
        )
        self.assert_error(payload, "invalid_request")
        self.assertEqual(self.revision(_TOOL_LOOP), before)

    def test_a_malformed_driver_observation_is_refused(self) -> None:
        self.start_both()
        before = self.revision(_TOOL_LOOP)
        payload = tool(
            action="goal_driver_observe",
            loop_id=_TOOL_LOOP,
            driver_observation={"schema_version": "nonsense/v1"},
            expected_revision=before,
        )
        self.assertEqual(payload["status"], "error")
        self.assertIn(payload["error"], LOOP_OPERATION_ERROR_CODES)
        self.assertEqual(self.revision(_TOOL_LOOP), before)

    def test_a_missing_loop_reports_loop_not_found(self) -> None:
        self.assert_error(tool(action="status", loop_id="no-such-loop"), "loop_not_found")

    def test_an_action_that_needs_a_loop_id_refuses_without_one(self) -> None:
        self.assert_error(tool(action="run_once", expected_revision=1), "invalid_request")

    def paths(self):
        from omh.system.paths import resolve_paths

        return resolve_paths(str(self.omh_home), str(self.hermes_home))


class ForeignFieldTests(_LoopHome):
    """A field sent to the wrong action is refused, never quietly dropped.

    One flat tool schema means every property passes host validation for every
    action, so the bridge is the only thing standing between "permit, and by
    the way set permission_profile" and a caller told `ok` while the field it
    sent did nothing. The CLI refuses the same request by exiting 2 on an
    unknown flag; these cases hold the tool to that.
    """

    def test_permit_refuses_a_permission_profile_it_cannot_honour(self) -> None:
        self.cli(
            "loop", "start",
            "--goal-summary", GOAL,
            "--goal-reframe", REFRAME,
            "--criterion", "install path fixed",
            "--loop-id", _CLI_LOOP,
            "--permission-profile", "full_loop",
        )
        started = tool(
            action="start",
            goal_summary=GOAL,
            goal_reframe=REFRAME,
            success_criteria=["install path fixed"],
            loop_id=_TOOL_LOOP,
            permission_profile="full_loop",
        )
        self.assertEqual(started["status"], "ok")
        before = self.cli("loop", "status", "--loop", _TOOL_LOOP)["loop"]["authority_envelope"]
        self.assertEqual(before["permission_profile"], "full_loop")

        payload = tool(
            action="permit",
            loop_id=_TOOL_LOOP,
            permission_profile="observe_only",
            expected_revision=self.revision(_TOOL_LOOP),
        )
        self.assertEqual(payload["status"], "error", payload)
        self.assertEqual(payload["error"], "invalid_request")
        self.assertIn("permission_profile", payload["error_detail"])
        self.assertFalse(payload["mutation_applied"])

        after = self.cli("loop", "status", "--loop", _TOOL_LOOP)["loop"]["authority_envelope"]
        self.assertEqual(after, before)

        # The same request through the CLI is refused by argparse, which is
        # the behaviour the tool now matches.
        status, _stderr = self.cli_error(
            "loop", "permit", "--loop", _CLI_LOOP, "--permission-profile", "observe_only"
        )
        self.assertEqual(status, 2)

    def test_feedback_refuses_queue_evidence_refs(self) -> None:
        self.start_both()
        before = self.revision(_TOOL_LOOP)
        payload = tool(
            action="feedback",
            loop_id=_TOOL_LOOP,
            internal_gap="QA gate missing",
            evidence_refs=["https://example.invalid/run/1"],
            expected_revision=before,
        )
        self.assertEqual(payload["error"], "invalid_request", payload)
        self.assertIn("evidence_refs", payload["error_detail"])
        self.assertEqual(self.revision(_TOOL_LOOP), before)

    def test_permit_refuses_a_feedback_field(self) -> None:
        self.start_both()
        before = self.revision(_TOOL_LOOP)
        payload = tool(
            action="permit",
            loop_id=_TOOL_LOOP,
            allow_actions=["research"],
            internal_gap="QA gate missing",
            expected_revision=before,
        )
        self.assertEqual(payload["error"], "invalid_request", payload)
        self.assertIn("internal_gap", payload["error_detail"])
        self.assertEqual(self.revision(_TOOL_LOOP), before)

    def test_every_field_of_every_other_action_is_refused(self) -> None:
        """The exhaustive form: no pair of actions may share a silent drop."""
        self.start_both()
        every_field = {
            name
            for names in loop_bridge.TOOL_ACTION_FIELDS.values()
            for name in names
        }
        samples = {
            "message": "text",
            "include_goal": True,
            "goal_summary": GOAL,
            "goal_reframe": REFRAME,
            "success_criteria": ["a"],
            "permission_profile": "observe_only",
            "allowed_executors": ["hermes"],
            "allow_actions": ["research"],
            "forbid_actions": ["merge"],
            "linked_goal_id": "",
            "loop_id": _TOOL_LOOP,
            "allow_unloopable": True,
            "executor": "hermes",
            "work_kind": "coding",
            "executor_session_ref": "ref",
            "observed_artifacts": ["docs/INSTALLATION.md"],
            "internal_gap": "gap",
            "external_wait": "wait",
            "context_exhausted": True,
            "budget_exhausted": True,
            "driver_observation": {},
            "queue_id": "queue-1",
            "evidence_refs": ["https://example.invalid/run/1"],
            "worktree_evidence_refs": ["wt"],
            "subagent_evidence_refs": ["sa"],
            "connector_evidence_refs": ["co"],
            "dispatch_attempt_id": "attempt-1",
            "summary": "summary",
        }
        self.assertEqual(sorted(samples), sorted(every_field))
        before = self.revision(_TOOL_LOOP)
        for action in LOOP_TOOL_ACTIONS:
            own = set(loop_bridge.TOOL_ACTION_FIELDS[action])
            for name in sorted(every_field - own - set(loop_bridge.ENVELOPE_ARGS)):
                with self.subTest(action=action, field=name):
                    payload = tool(
                        **{
                            "action": action,
                            "loop_id": _TOOL_LOOP,
                            "expected_revision": before,
                            name: samples[name],
                        }
                    )
                    self.assertEqual(payload["status"], "error", payload)
                    self.assertEqual(payload["error"], "invalid_request", payload)
                    self.assertIn(name, payload["error_detail"])
        self.assertEqual(self.revision(_TOOL_LOOP), before)

    def test_an_argument_belonging_to_no_action_is_refused(self) -> None:
        self.start_both()
        payload = tool(action="status", loop_id=_TOOL_LOOP, not_a_field="x")
        self.assertEqual(payload["error"], "invalid_request", payload)
        self.assertIn("not_a_field", payload["error_detail"])


class SessionBindingBoundaryTests(_LoopHome):
    """What the identity gate is, and what it deliberately is not."""

    def test_the_gate_records_nothing_anywhere_in_the_store(self) -> None:
        self.start_both()
        for _ in range(2):
            tool(
                action="feedback",
                loop_id=_TOOL_LOOP,
                internal_gap="QA gate missing",
                expected_revision=self.revision(_TOOL_LOOP),
            )
        tool(
            action="run_once",
            loop_id=_TOOL_LOOP,
            expected_revision=self.revision(_TOOL_LOOP),
        )
        # The session id is checked and echoed, never stored. If a later
        # change persists it, this fails and the comment in `loop_bridge` that
        # says it is not an attribution record has to move with it.
        written = [path for path in self.omh_home.rglob("*") if path.is_file()]
        self.assertTrue(written)
        for path in written:
            with self.subTest(path=path.name):
                self.assertNotIn(SESSION, path.read_text(encoding="utf-8", errors="replace"))
        self.assertNotIn(
            SESSION, json.dumps(self.cli("loop", "status", "--loop", _TOOL_LOOP)["loop"])
        )

    def test_any_session_may_steer_a_loop_another_session_started(self) -> None:
        # Deliberate, not an oversight: a loop outlives its first session, and
        # the CLI carries no session at all. The revision guard is what keeps
        # two steerers from overwriting each other.
        self.start_both()
        payload = tool(
            action="feedback",
            loop_id=_TOOL_LOOP,
            internal_gap="steered from a second session",
            expected_revision=self.revision(_TOOL_LOOP),
            session_id="hermes-session-2",
        )
        self.assertEqual(payload["status"], "ok", payload)
        self.assertEqual(payload["session_binding"]["session_ref"], "hermes-session-2")

    def test_the_refusal_does_not_claim_attribution(self) -> None:
        self.start_both()
        detail = tool(
            action="feedback",
            loop_id=_TOOL_LOOP,
            internal_gap="x",
            expected_revision=1,
            session_id="",
        )["error_detail"]
        self.assertIn("omh loop", detail)
        self.assertNotIn("attribut", detail.lower())


class ErrorDetailTests(_LoopHome):
    """A refusal explains itself without describing the host's disk."""

    def test_loop_not_found_hands_back_a_sentence_not_a_path(self) -> None:
        payload = tool(action="status", loop_id="no-such-loop")
        self.assertEqual(payload["error"], "loop_not_found")
        detail = payload["error_detail"]
        self.assertIn("action=status", detail)
        self.assertNotIn(str(self.omh_home), detail)
        self.assertNotIn("cycle.json", detail)
        self.assertNotIn("/", detail)

    def test_a_malformed_record_reports_the_fault_without_the_store_path(self) -> None:
        from omh.system.paths import resolve_paths
        from omh.workflows.loop_operations import loop_operation_envelope

        self.start_both()
        paths = resolve_paths(str(self.omh_home), str(self.hermes_home))
        (paths.loops_dir / _TOOL_LOOP / "cycle.json").write_text("{ not json", encoding="utf-8")
        payload = loop_operation_envelope(
            paths, LoopOperationRequest(action="status", fields={"loop_id": _TOOL_LOOP})
        )
        self.assertEqual(payload["status"], "error")
        self.assertTrue(payload["error_detail"].strip())
        self.assertNotIn(str(self.omh_home), payload["error_detail"])

    def test_a_workflow_message_that_quotes_the_store_is_redacted(self) -> None:
        # Tested at the redactor, because which workflow message happens to
        # quote a path is not a contract and would make this case drift.
        from omh.workflows.loop_operations import _safe_detail

        home = str(self.omh_home)
        detail = _safe_detail(
            "loop_rule_violation", ValueError(f"{home}/loops/x/cycle.json: broken"), home
        )
        self.assertNotIn(home, detail)
        self.assertIn("<omh_home>", detail)
        self.assertIn("broken", detail)

    def test_the_cli_still_reports_the_path_it_could_not_read(self) -> None:
        # The redaction is the model-facing envelope's, not the operator's: an
        # operator debugging a broken store needs the filename.
        self.start_both()
        status, stderr = self.cli_error("loop", "status", "--loop", "no-such-loop")
        self.assertNotEqual(status, 0)
        self.assertIn("no-such-loop", stderr)


class CliCompatibilityTests(_LoopHome):
    """The command surface keeps its flags, its messages, and its exit codes."""

    def test_an_unknown_loop_still_exits_nonzero_with_the_workflow_message(self) -> None:
        status, stderr = self.cli_error("loop", "status", "--loop", "no-such-loop")
        self.assertNotEqual(status, 0)
        self.assertIn("no-such-loop", stderr)

    def test_an_unclear_goal_keeps_its_workflow_refusal_text(self) -> None:
        status, stderr = self.cli_error(
            "loop", "start",
            "--goal-summary", "x",
            "--goal-reframe", "y",
            "--criterion", "z",
        )
        self.assertNotEqual(status, 0)
        self.assertIn("loop start rejected unclear goal", stderr)

    def test_a_bad_driver_observation_keeps_its_prefixed_message(self) -> None:
        self.start_both()
        broken = Path(self._tmp.name) / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        status, stderr = self.cli_error(
            "loop", "goal-driver-observe", "--loop", _CLI_LOOP, "--observation-json", str(broken)
        )
        self.assertNotEqual(status, 0)
        self.assertIn("invalid loop goal driver observation", stderr)

    def test_the_revision_guard_flags_still_refuse_a_stale_cli_mutation(self) -> None:
        self.start_both()
        self.cli(
            "loop", "sticky-rule", "declare", "--loop", _CLI_LOOP,
            "--rule-id", "rule-1", "--text", "re-read the gate list",
        )
        status, stderr = self.cli_error(
            "loop", "sticky-rule", "declare", "--loop", _CLI_LOOP,
            "--rule-id", "rule-2", "--text", "re-read the gate list",
            "--expected-revision", "1",
        )
        self.assertNotEqual(status, 0)
        self.assertIn("stale", stderr)

    def test_migrate_driver_still_reports_without_applying(self) -> None:
        self.start_both()
        reported = self.cli("loop", "migrate-driver", "--loop", _CLI_LOOP)
        self.assertFalse(reported["applied"])
        applied = self.cli("loop", "migrate-driver", "--loop", _CLI_LOOP, "--apply")
        self.assertTrue(applied["applied"])


class BundleCoreParityTests(unittest.TestCase):
    """Every literal the bundle restates is pinned against its producer."""

    def test_claim_boundary_and_schema_match_core(self) -> None:
        self.assertEqual(loop_bridge.LOOP_TOOL_CLAIM_BOUNDARY, LOOP_OPERATION_CLAIM_BOUNDARY)
        self.assertEqual(loop_bridge.LOOP_TOOL_RESULT_SCHEMA, LOOP_OPERATION_RESULT_SCHEMA)

    def test_error_codes_the_bundle_raises_are_in_the_core_vocabulary(self) -> None:
        for code in (
            loop_bridge.SERVICE_UNAVAILABLE,
            loop_bridge.UNKNOWN_ACTION,
            loop_bridge.IDENTITY_REQUIRED,
            loop_bridge.REVISION_REQUIRED,
            loop_bridge.STORE_UNAVAILABLE,
            loop_bridge.INVALID_REQUEST,
        ):
            self.assertIn(code, LOOP_OPERATION_ERROR_CODES)

    def test_tool_action_set_matches_the_manifest(self) -> None:
        self.assertEqual(set(loop_bridge.LOOP_TOOL_ACTIONS), set(LOOP_TOOL_ACTIONS))

    def test_every_tool_field_is_a_real_field_of_that_action(self) -> None:
        for action, names in loop_bridge.TOOL_ACTION_FIELDS.items():
            spec = LOOP_OPERATION_SPECS[action]
            with self.subTest(action=action):
                self.assertTrue(set(names) <= set(spec.field_map()), action)

    def test_every_required_field_is_reachable_from_the_tool(self) -> None:
        for action in LOOP_TOOL_ACTIONS:
            spec = LOOP_OPERATION_SPECS[action]
            required = {item.name for item in spec.fields if item.required}
            exposed = set(loop_bridge.TOOL_ACTION_FIELDS[action])
            with self.subTest(action=action):
                self.assertTrue(required <= exposed, f"{action}: {required - exposed}")

    def test_every_tool_field_is_declared_in_the_schema(self) -> None:
        properties = set(OMH_LOOP_SCHEMA["parameters"]["properties"])
        for action, names in loop_bridge.TOOL_ACTION_FIELDS.items():
            with self.subTest(action=action):
                self.assertTrue(set(names) <= properties, set(names) - properties)

    def test_the_schema_declares_no_property_outside_the_union(self) -> None:
        # Union-level only: it proves the schema advertises nothing the bridge
        # has no home for. It says nothing about which action each property
        # belongs to, which is what ForeignFieldTests covers.
        routed = set(loop_bridge.ENVELOPE_ARGS)
        for names in loop_bridge.TOOL_ACTION_FIELDS.values():
            routed.update(names)
        self.assertEqual(set(OMH_LOOP_SCHEMA["parameters"]["properties"]), routed)

    def test_envelope_args_are_disjoint_from_no_action(self) -> None:
        # `loop_id` is deliberately both: the envelope names the loop to act
        # on, and `start` / `status` take it as a field. Every other envelope
        # argument belongs to the call, never to one action.
        for name in loop_bridge.ENVELOPE_ARGS:
            if name == "loop_id":
                continue
            for action, names in loop_bridge.TOOL_ACTION_FIELDS.items():
                with self.subTest(argument=name, action=action):
                    self.assertNotIn(name, names)

    def test_mutating_and_guarded_sets_match_the_manifest(self) -> None:
        self.assertEqual(
            set(loop_bridge.MUTATING_TOOL_ACTIONS),
            {action for action in LOOP_TOOL_ACTIONS if LOOP_OPERATION_SPECS[action].mutating},
        )
        self.assertEqual(
            set(loop_bridge.LOOP_ID_REQUIRED_TOOL_ACTIONS),
            {
                action
                for action in LOOP_TOOL_ACTIONS
                if LOOP_OPERATION_SPECS[action].requires_loop_id
            },
        )

    def test_schema_enums_match_their_core_producers(self) -> None:
        properties = OMH_LOOP_SCHEMA["parameters"]["properties"]
        self.assertEqual(properties["permission_profile"]["enum"], list(PERMISSION_PROFILES))
        self.assertEqual(properties["executor"]["enum"], list(LOOP_EXECUTOR_OPTION_IDS))
        for name in ("allow_actions", "forbid_actions"):
            self.assertEqual(properties[name]["items"]["enum"], list(LOOP_ACTIONS))
        self.assertEqual(properties["action"]["enum"], list(loop_bridge.LOOP_TOOL_ACTIONS))


class StandaloneBundleTests(unittest.TestCase):
    """The bundle loads with no installed `omh`, and then fails closed."""

    def _standalone_tool(self):
        name = "_test_omh_standalone_loop_bundle"
        for existing in [key for key in sys.modules if key == name or key.startswith(name + ".")]:
            sys.modules.pop(existing, None)
        spec = importlib.util.spec_from_file_location(
            name, _BUNDLE / "__init__.py", submodule_search_locations=[str(_BUNDLE)]
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        self.addCleanup(sys.modules.pop, name, None)
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

        def blocked(target: str, *args: object, **kwargs: object):
            if target == "omh" or target.startswith("omh."):
                raise ImportError("standalone plugin host has no installed omh package")
            return real_import(target, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=blocked):
            spec.loader.exec_module(module)
            return importlib.import_module(f"{name}.tools.loop_tool"), blocked

    def test_the_tool_module_imports_without_the_package(self) -> None:
        module, _blocked = self._standalone_tool()
        self.assertEqual(module.OMH_LOOP_SCHEMA["name"], "omh_loop")

    def test_a_call_without_the_package_fails_closed(self) -> None:
        module, blocked = self._standalone_tool()
        with mock.patch("builtins.__import__", side_effect=blocked):
            payload = json.loads(module.omh_loop_handler({"action": "status"}, session_id=SESSION))
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"], "service_unavailable")
        self.assertIn("omh loop", payload["error_detail"])


class RegistrationMirrorTests(unittest.TestCase):
    """Adding a tool moves five lists; none of them may be missed."""

    def test_metadata_plugin_yaml_and_tools_package_all_carry_it(self) -> None:
        self.assertIn("omh_loop", PROVIDED_TOOLS)
        self.assertEqual(TOOL_FILE_STEMS["omh_loop"], "loop_tool")
        self.assertIn("omh_loop", BUILTIN_TOOL_NAMES)
        self.assertIn("omh_loop", (_BUNDLE / "plugin.yaml").read_text(encoding="utf-8"))

    def test_the_schema_collector_returns_it(self) -> None:
        self.assertIn("omh_loop", {str(schema.get("name", "")) for schema in builtin_tool_schemas()})

    def test_register_actually_registers_it(self) -> None:
        registered: list[str] = []

        class _Context:
            def register_tool(self, name, toolset, schema, handler, **kwargs):
                registered.append(name)
                return None

            def register_hook(self, name, handler):
                return None

        from omh.plugin_bundle.omh import register

        register(_Context())
        self.assertIn("omh_loop", registered)
        self.assertEqual(sorted(registered), sorted(PROVIDED_TOOLS))

    def test_the_capability_manifest_names_the_cli_fallback(self) -> None:
        from omh.capabilities.hooks import hook_manifest

        row = next(
            entry
            for entry in hook_manifest()["plugin_tools"]
            if entry["name"] == "omh_loop"
        )
        self.assertTrue(row["supported_by_cli_backend"])
        self.assertEqual(row["cli_backend_surface"], "omh loop")
        self.assertFalse(row["observed_in_this_environment"])

    def test_the_handler_signature_matches_the_neighbours(self) -> None:
        source = ast.parse((_BUNDLE / "tools" / "loop_tool.py").read_text(encoding="utf-8"))
        handler = next(
            node
            for node in source.body
            if isinstance(node, ast.FunctionDef) and node.name == "omh_loop_handler"
        )
        self.assertEqual([arg.arg for arg in handler.args.args], ["args"])
        self.assertIsNotNone(handler.args.kwarg)


class ObservationBoundaryTests(_LoopHome):
    """Loop inputs never leak into the plugin-invocation observation record."""

    def test_the_goal_text_is_not_handed_to_the_observer(self) -> None:
        captured: dict[str, object] = {}

        def fake(tool_name, args, kwargs):
            captured["args"] = copy.deepcopy(args)
            return None

        with mock.patch("omh.plugin_bundle.omh.tools.loop_tool.observe_plugin_tool_call", fake):
            tool(action="assess", message=GOAL)
        self.assertNotIn("message", captured["args"])

    def test_loop_evidence_refs_are_not_handed_to_the_observer(self) -> None:
        captured: dict[str, object] = {}

        def fake(tool_name, args, kwargs):
            captured["args"] = copy.deepcopy(args)
            return None

        with mock.patch("omh.plugin_bundle.omh.tools.loop_tool.observe_plugin_tool_call", fake):
            tool(
                action="queue_observe",
                loop_id=_TOOL_LOOP,
                queue_id="queue-1",
                evidence_refs=["https://example.invalid/run/1"],
                expected_revision=1,
            )
        self.assertNotIn("evidence_refs", captured["args"])


if __name__ == "__main__":
    unittest.main()

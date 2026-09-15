"""Contracts for rehearsing a planned batch against the local rules.

Two of the three tiers are derivable and the third is not, so most of what
is pinned here is what the rehearsal must NOT say: an undeterminable call
reports `unknown` with its reason and is never counted into an allowed
bucket, an active bypass is reported rather than assumed away, and a plan or
a rules file OMH could not read in full never produces a quiet "nothing
refused". The rehearsal itself writes nothing and runs nothing.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.commands.permission_rehearsal import _permission_rehearsal_exit_code
from omh.plugin_bundle.omh.toolcall_rules import (
    TOOLCALL_RULES_SCHEMA_VERSION,
    _reset_state,
    toolcall_rules_path,
)
from omh.workflows.permission_rehearsal import (
    MAX_PLANNED_CALLS,
    PERMISSION_REHEARSAL_PLAN_SCHEMA_VERSION,
    PERMISSION_REHEARSAL_VERDICTS,
    REASON_NEEDS_APPROVAL_NOT_READABLE,
    REASON_REFUSED_BY_RULE,
    PlannedCall,
    parse_planned_calls,
    read_planned_calls,
    rehearse_planned_calls,
)

BOX_LEAK_RULE = {
    "name": "no-box-leak",
    "pattern": r"Box::leak",
    "message": "Do not reach for Box::leak in production code paths.",
}

LEAKING_CALL = PlannedCall("write_file", {"content": "Box::leak(x)"})
PLAIN_CALL = PlannedCall("read_file", {"path": "notes.md"})


def _tree(root: Path) -> dict[str, bytes]:
    """Every file under `root`, so a write of any kind shows up as a diff."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class RehearsalTestCase(unittest.TestCase):
    def setUp(self) -> None:
        _reset_state()
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.omh_home = root / "omh"
        self.hermes_home = root / "hermes"
        self.omh_home.mkdir()
        self.hermes_home.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_rules(self, rules: list[dict], *, schema_version: str = TOOLCALL_RULES_SCHEMA_VERSION) -> Path:
        path = toolcall_rules_path(str(self.omh_home))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": schema_version, "rules": rules}), encoding="utf-8")
        return path

    def write_config(self, text: str) -> None:
        (self.hermes_home / "config.yaml").write_text(text, encoding="utf-8")

    def rehearse(self, *calls: PlannedCall) -> dict:
        return rehearse_planned_calls(
            calls,
            omh_home=self.omh_home,
            hermes_home=self.hermes_home,
        )


class RefusalTierTest(RehearsalTestCase):
    def test_a_refused_call_names_the_rule(self) -> None:
        self.write_rules([BOX_LEAK_RULE])
        payload = self.rehearse(LEAKING_CALL)
        row = payload["calls"][0]
        self.assertEqual(row["verdict"], "refused")
        self.assertEqual(row["rule"], "no-box-leak")
        self.assertEqual(row["reason"], REASON_REFUSED_BY_RULE)
        self.assertEqual(payload["summary"]["refused"], 1)

    def test_a_rule_scoped_to_other_tools_does_not_refuse_this_call(self) -> None:
        self.write_rules([{**BOX_LEAK_RULE, "tools": ["execute_code"]}])
        payload = self.rehearse(LEAKING_CALL)
        self.assertEqual(payload["calls"][0]["verdict"], "unknown")
        self.assertEqual(payload["summary"]["refused"], 0)

    def test_a_once_rule_fires_once_across_the_batch(self) -> None:
        # The batch is modelled as one fresh session, so a repeat="once" rule
        # blocks the first matching call and the rest proceed past it -- what
        # the enforcing hook would actually do to this batch.
        self.write_rules([BOX_LEAK_RULE])
        payload = self.rehearse(LEAKING_CALL, LEAKING_CALL)
        self.assertEqual([row["verdict"] for row in payload["calls"]], ["refused", "unknown"])

    def test_an_always_rule_fires_on_every_matching_call(self) -> None:
        self.write_rules([{**BOX_LEAK_RULE, "repeat": "always"}])
        payload = self.rehearse(LEAKING_CALL, LEAKING_CALL)
        self.assertEqual([row["verdict"] for row in payload["calls"]], ["refused", "refused"])

    def test_two_rehearsals_do_not_consume_each_others_once_claims(self) -> None:
        self.write_rules([BOX_LEAK_RULE])
        self.assertEqual(self.rehearse(LEAKING_CALL)["calls"][0]["verdict"], "refused")
        self.assertEqual(self.rehearse(LEAKING_CALL)["calls"][0]["verdict"], "refused")


class UnknownTierTest(RehearsalTestCase):
    def test_an_undeterminable_call_reports_unknown_with_the_reason(self) -> None:
        self.write_rules([BOX_LEAK_RULE])
        row = self.rehearse(PLAIN_CALL)["calls"][0]
        self.assertEqual(row["verdict"], "unknown")
        self.assertEqual(row["reason"], REASON_NEEDS_APPROVAL_NOT_READABLE)
        self.assertEqual(row["rule"], "")

    def test_the_reason_code_carries_its_explanation(self) -> None:
        payload = self.rehearse(PLAIN_CALL)
        detail = payload["reason_codes"][REASON_NEEDS_APPROVAL_NOT_READABLE]
        self.assertIn("per-tool approval declarations", detail)

    def test_the_summary_never_counts_an_unknown_as_allowed(self) -> None:
        # The third tier has no reader, so there is no bucket an unknown
        # could be counted into: every planned call is refused or unknown,
        # and no count claims permission for either.
        self.write_rules([BOX_LEAK_RULE])
        summary = self.rehearse(LEAKING_CALL, PLAIN_CALL, PLAIN_CALL)["summary"]
        self.assertNotIn("allowed", summary)
        self.assertEqual(summary["planned"], 3)
        self.assertEqual(summary["refused"], 1)
        self.assertEqual(summary["unknown"], 2)
        self.assertEqual(summary["refused"] + summary["unknown"], summary["planned"])

    def test_every_verdict_comes_from_the_closed_vocabulary(self) -> None:
        # Two verdicts, not three: a third value would be a tier OMH cannot
        # derive, so the vocabulary is the guard against inventing one.
        self.write_rules([BOX_LEAK_RULE])
        payload = self.rehearse(LEAKING_CALL, PLAIN_CALL)
        self.assertEqual(PERMISSION_REHEARSAL_VERDICTS, ("refused", "unknown"))
        for row in payload["calls"]:
            self.assertIn(row["verdict"], PERMISSION_REHEARSAL_VERDICTS)

    def test_with_no_rules_file_every_call_is_unknown(self) -> None:
        payload = self.rehearse(LEAKING_CALL, PLAIN_CALL)
        self.assertEqual([row["verdict"] for row in payload["calls"]], ["unknown", "unknown"])
        self.assertFalse(payload["rules"]["present"])
        self.assertEqual(payload["rules"]["defect_count"], 0)


class ApprovalBypassTest(RehearsalTestCase):
    def test_an_active_bypass_is_reported(self) -> None:
        self.write_config("approvals:\n  mode: off\n")
        payload = self.rehearse(PLAIN_CALL)
        self.assertTrue(payload["summary"]["approval_bypass_active"])
        self.assertTrue(payload["approval_bypass"]["enabled"])
        self.assertEqual(payload["approval_bypass"]["status"], "observed")

    def test_a_manual_approvals_mode_is_not_a_bypass(self) -> None:
        self.write_config("approvals:\n  mode: manual\n")
        payload = self.rehearse(PLAIN_CALL)
        self.assertFalse(payload["summary"]["approval_bypass_active"])

    def test_a_deeper_mode_key_is_not_the_global_bypass(self) -> None:
        # The negative control for the scope limit: `approvals.tools.mode` is
        # a different key the bypass reader does not read, and reading it as
        # the global bypass would be the claim this rehearsal must not make.
        self.write_config("approvals:\n  tools:\n    mode: off\n")
        payload = self.rehearse(PLAIN_CALL)
        self.assertFalse(payload["summary"]["approval_bypass_active"])

    def test_an_unreadable_bypass_state_is_idle_not_active(self) -> None:
        payload = self.rehearse(PLAIN_CALL)
        self.assertEqual(payload["approval_bypass"]["status"], "idle")
        self.assertFalse(payload["summary"]["approval_bypass_active"])


class DefectiveRulesTest(RehearsalTestCase):
    def test_a_present_file_with_a_defect_reports_the_defect_count(self) -> None:
        self.write_rules([BOX_LEAK_RULE, {"name": "broken", "pattern": "(", "message": "m"}])
        payload = self.rehearse(LEAKING_CALL)
        self.assertTrue(payload["rules"]["present"])
        self.assertEqual(payload["rules"]["loaded"], 1)
        self.assertGreater(payload["rules"]["defect_count"], 0)

    def test_a_file_the_loader_drops_whole_counts_as_a_defect(self) -> None:
        self.write_rules([BOX_LEAK_RULE], schema_version="omh_toolcall_rules/v0")
        payload = self.rehearse(LEAKING_CALL)
        self.assertEqual(payload["rules"]["loaded"], 0)
        self.assertGreater(payload["rules"]["defect_count"], 0)

    def test_an_unparseable_file_counts_as_a_defect(self) -> None:
        path = toolcall_rules_path(str(self.omh_home))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        payload = self.rehearse(LEAKING_CALL)
        self.assertEqual(payload["rules"]["loaded"], 0)
        self.assertEqual(payload["rules"]["defect_count"], 1)


class NoEffectsTest(RehearsalTestCase):
    def test_the_rehearsal_writes_nothing_under_either_home(self) -> None:
        self.write_rules([BOX_LEAK_RULE])
        self.write_config("approvals:\n  mode: off\n")
        before = (_tree(self.omh_home), _tree(self.hermes_home))
        self.rehearse(LEAKING_CALL, PLAIN_CALL)
        self.assertEqual((_tree(self.omh_home), _tree(self.hermes_home)), before)

    def test_the_rehearsal_creates_no_rules_file_when_none_exists(self) -> None:
        self.rehearse(PLAIN_CALL)
        self.assertFalse(toolcall_rules_path(str(self.omh_home)).exists())
        self.assertEqual(_tree(self.omh_home), {})


class PlanParsingTest(unittest.TestCase):
    """The plan fails closed: a plan OMH cannot read whole is not rehearsed."""

    def _plan(self, calls: list[dict], *, schema_version: str = PERMISSION_REHEARSAL_PLAN_SCHEMA_VERSION) -> dict:
        return {"schema_version": schema_version, "calls": calls}

    def test_a_valid_plan_parses_into_planned_calls(self) -> None:
        calls = parse_planned_calls(self._plan([{"tool": "write_file", "args": {"path": "x"}}]))
        self.assertEqual(calls, (PlannedCall("write_file", {"path": "x"}),))

    def test_args_default_to_an_empty_object(self) -> None:
        self.assertEqual(parse_planned_calls(self._plan([{"tool": "list_files"}]))[0].args, {})

    def test_a_wrong_schema_version_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            parse_planned_calls(self._plan([{"tool": "write_file"}], schema_version="other/v1"))

    def test_an_empty_plan_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            parse_planned_calls(self._plan([]))

    def test_a_call_without_a_tool_name_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            parse_planned_calls(self._plan([{"args": {}}]))

    def test_an_oversized_plan_is_refused_rather_than_truncated(self) -> None:
        with self.assertRaises(ValueError):
            parse_planned_calls(self._plan([{"tool": "read_file"}] * (MAX_PLANNED_CALLS + 1)))

    def test_a_missing_plan_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                read_planned_calls(Path(tmp) / "absent.json")


class ExitCodeTest(unittest.TestCase):
    def _payload(self, *, refused: int, defects: int) -> dict:
        return {
            "rules": {"present": True, "loaded": 1, "defect_count": defects},
            "summary": {"planned": 1 + refused, "refused": refused, "unknown": 1},
        }

    def test_an_unknown_only_rehearsal_exits_zero(self) -> None:
        # 0 means "no rule refuses these", not "these are allowed": if an
        # unknown moved the status, the command could never exit 0 and a
        # wrapper would learn to ignore it.
        self.assertEqual(_permission_rehearsal_exit_code(self._payload(refused=0, defects=0)), 0)

    def test_a_refused_call_exits_one(self) -> None:
        self.assertEqual(_permission_rehearsal_exit_code(self._payload(refused=1, defects=0)), 1)

    def test_a_defective_rules_file_exits_three(self) -> None:
        self.assertEqual(_permission_rehearsal_exit_code(self._payload(refused=0, defects=2)), 3)

    def test_a_refusal_outranks_a_defect(self) -> None:
        self.assertEqual(_permission_rehearsal_exit_code(self._payload(refused=1, defects=2)), 1)


class RehearsalCliTest(RehearsalTestCase):
    def _write_plan(self, calls: list[dict]) -> Path:
        path = Path(self._tmp.name) / "plan.json"
        path.write_text(
            json.dumps({"schema_version": PERMISSION_REHEARSAL_PLAN_SCHEMA_VERSION, "calls": calls}),
            encoding="utf-8",
        )
        return path

    def _run(self, plan: Path) -> tuple[int, dict]:
        status, stdout, stderr = run_cli(
            [
                "--omh-home",
                str(self.omh_home),
                "--hermes-home",
                str(self.hermes_home),
                "ops",
                "permission-rehearse",
                "--plan",
                str(plan),
            ]
        )
        return status, (json.loads(stdout) if stdout.strip() else {"stderr": stderr})

    def test_a_clean_batch_exits_zero_with_the_table(self) -> None:
        self.write_rules([BOX_LEAK_RULE])
        status, payload = self._run(self._write_plan([{"tool": "read_file", "args": {"path": "notes.md"}}]))
        self.assertEqual(status, 0)
        self.assertEqual(payload["schema_version"], "omh_permission_rehearsal/v1")
        self.assertEqual(payload["summary"]["unknown"], 1)
        self.assertIn("None of this is approval, execution, review, or safety evidence", payload["claim_boundary"])

    def test_a_refused_batch_exits_one_and_names_the_rule(self) -> None:
        self.write_rules([BOX_LEAK_RULE])
        status, payload = self._run(
            self._write_plan(
                [
                    {"tool": "write_file", "args": {"content": "Box::leak(x)"}},
                    {"tool": "read_file", "args": {"path": "notes.md"}},
                ]
            )
        )
        self.assertEqual(status, 1)
        self.assertEqual(payload["calls"][0]["rule"], "no-box-leak")
        self.assertEqual(payload["summary"]["refused"], 1)

    def test_a_defective_rules_file_exits_three(self) -> None:
        self.write_rules([{"name": "broken", "pattern": "(", "message": "m"}])
        status, payload = self._run(self._write_plan([{"tool": "read_file"}]))
        self.assertEqual(status, 3)
        self.assertGreater(payload["rules"]["defect_count"], 0)

    def test_an_unreadable_plan_is_an_error_not_an_empty_rehearsal(self) -> None:
        path = Path(self._tmp.name) / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        status, payload = self._run(path)
        self.assertEqual(status, 2)
        self.assertIn("could not parse plan file", payload["stderr"])

    def test_an_active_bypass_reaches_the_cli_payload(self) -> None:
        self.write_config("approvals:\n  mode: off\n")
        status, payload = self._run(self._write_plan([{"tool": "read_file"}]))
        self.assertEqual(status, 0)
        self.assertTrue(payload["summary"]["approval_bypass_active"])


if __name__ == "__main__":  # pragma: no cover - unittest entry point
    unittest.main()

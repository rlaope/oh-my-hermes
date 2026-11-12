"""Contracts for user-authored toolcall rules at the pre_tool_call seam.

The rules file's presence is the opt-in; everything degrades fail-open (no
file, malformed file, invalid rule, oversized file -> no intervention). A
matching rule returns the one host-supported strong response — a block
directive whose message becomes the tool result the model reads — and a
repeat="once" rule fires at most once per session so a blocked retry loop
cannot form.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _cli_harness import run_cli

from omh.plugin_bundle.omh import toolcall_rule_faults
from omh.plugin_bundle.omh.hooks import nudge_budget, session_attendance, tool_hooks
from omh.plugin_bundle.omh.hooks.tool_hooks import pre_tool_call
from omh.plugin_bundle.omh.toolcall_rule_faults import (
    read_toolcall_rule_faults,
    toolcall_rule_faults_path,
)
from omh.plugin_bundle.omh.toolcall_rules import (
    MAX_RULES,
    TOOLCALL_RULES_SCHEMA_VERSION,
    _reset_state,
    load_toolcall_rules,
    toolcall_rule_directive,
    toolcall_rules_path,
    validate_toolcall_rules_document,
)


def _write_rules(home: Path, rules: list[dict]) -> Path:
    path = toolcall_rules_path(str(home))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": TOOLCALL_RULES_SCHEMA_VERSION, "rules": rules}),
        encoding="utf-8",
    )
    return path


BOX_LEAK_RULE = {
    "name": "no-box-leak",
    "pattern": r"Box::leak",
    "message": "Do not reach for Box::leak in production code paths.",
}


class LoadAndValidateTest(unittest.TestCase):
    def setUp(self):
        _reset_state()
        # addCleanup (not tearDown): registered immediately so a later
        # exception in this same setUp still tears the directory down
        # (issue #1731).
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)

    def test_missing_file_yields_no_rules(self):
        self.assertEqual(load_toolcall_rules(toolcall_rules_path(str(self.home))), ())

    def test_malformed_json_fails_open(self):
        path = toolcall_rules_path(str(self.home))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        self.assertEqual(load_toolcall_rules(path), ())

    def test_wrong_schema_version_yields_no_rules(self):
        path = toolcall_rules_path(str(self.home))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": "other/v9", "rules": [BOX_LEAK_RULE]}), encoding="utf-8")
        self.assertEqual(load_toolcall_rules(path), ())

    def test_invalid_entries_are_skipped_and_valid_ones_kept(self):
        path = _write_rules(
            self.home,
            [
                BOX_LEAK_RULE,
                {"name": "broken", "pattern": "(", "message": "unclosed group"},
                {"name": "", "pattern": "x", "message": "empty name"},
                {"name": "no-message", "pattern": "x", "message": "   "},
            ],
        )
        rules = load_toolcall_rules(path)
        self.assertEqual([rule.name for rule in rules], ["no-box-leak"])

    def test_mtime_cache_serves_and_refreshes(self):
        path = _write_rules(self.home, [BOX_LEAK_RULE])
        self.assertEqual(len(load_toolcall_rules(path)), 1)
        # Rewrite with two rules; force a visible stat change.
        _write_rules(self.home, [BOX_LEAK_RULE, {"name": "second", "pattern": "y", "message": "m"}])
        import os

        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        self.assertEqual(len(load_toolcall_rules(path)), 2)

    def test_validation_reports_every_defect_with_indexes(self):
        errors, accepted = validate_toolcall_rules_document(
            {
                "schema_version": TOOLCALL_RULES_SCHEMA_VERSION,
                "rules": [
                    BOX_LEAK_RULE,
                    {"name": "broken", "pattern": "(", "message": "m"},
                    {"name": "no-box-leak", "pattern": "x", "message": "duplicate name"},
                    {"name": "bad-repeat", "pattern": "x", "message": "m", "repeat": "sometimes"},
                ],
            }
        )
        self.assertEqual(accepted, 1)
        self.assertTrue(any("rules[1]" in error and "compile" in error for error in errors))
        self.assertTrue(any("duplicate rule name" in error for error in errors))
        self.assertTrue(any("repeat" in error for error in errors))

    def test_validation_rejects_non_object_documents(self):
        errors, accepted = validate_toolcall_rules_document([])
        self.assertEqual(accepted, 0)
        self.assertTrue(errors)

    def test_catastrophic_backtracking_patterns_are_refused(self):
        errors, accepted = validate_toolcall_rules_document(
            {
                "schema_version": TOOLCALL_RULES_SCHEMA_VERSION,
                "rules": [
                    {"name": "redos", "pattern": "(a+)+$", "message": "m"},
                    {"name": "redos-star", "pattern": "(x*)*y", "message": "m"},
                    {"name": "fine-anchor", "pattern": "Box::leak", "message": "m"},
                    {"name": "fine-bounded", "pattern": "(ab){1,4}c", "message": "m"},
                ],
            }
        )
        self.assertEqual(accepted, 2)
        self.assertEqual(sum("catastrophic-backtracking" in error for error in errors), 2)
        # And the loader agrees: the pathological rules never load.
        path = _write_rules(
            self.home,
            [
                {"name": "redos", "pattern": "(a+)+$", "message": "m"},
                {"name": "kept", "pattern": "Box::leak", "message": "m"},
            ],
        )
        self.assertEqual([rule.name for rule in load_toolcall_rules(path)], ["kept"])

    def test_wrong_schema_version_reports_zero_accepted(self):
        errors, accepted = validate_toolcall_rules_document(
            {"schema_version": "other/v9", "rules": [BOX_LEAK_RULE]}
        )
        self.assertEqual(accepted, 0)
        self.assertTrue(any("no rule is loaded" in error for error in errors))

    def test_omh_home_env_var_resolves_the_rules_path(self):
        previous = os.environ.get("OMH_HOME")
        os.environ["OMH_HOME"] = str(self.home)
        try:
            self.assertEqual(
                toolcall_rules_path(),
                self.home.resolve() / "rules" / "toolcall-rules.json",
            )
        finally:
            if previous is None:
                del os.environ["OMH_HOME"]
            else:
                os.environ["OMH_HOME"] = previous

    def test_rule_count_is_bounded(self):
        rules = [
            {"name": f"rule-{index}", "pattern": "x", "message": "m"}
            for index in range(MAX_RULES + 5)
        ]
        path = _write_rules(self.home, rules)
        self.assertEqual(len(load_toolcall_rules(path)), MAX_RULES)


class DirectiveTest(unittest.TestCase):
    def setUp(self):
        _reset_state()
        # addCleanup (not tearDown): registered immediately so a later
        # exception in this same setUp still tears the directory down
        # (issue #1731).
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)

    def test_matching_call_is_blocked_with_rule_text(self):
        _write_rules(self.home, [BOX_LEAK_RULE])
        directive = toolcall_rule_directive(
            tool_name="write_file",
            tool_input={"path": "src/lib.rs", "content": "let s = Box::leak(name);"},
            session_id="session-a",
            omh_home=str(self.home),
        )
        self.assertIsNotNone(directive)
        self.assertEqual(directive["action"], "block")
        self.assertIn("[OMH Rule] no-box-leak", directive["message"])
        self.assertIn("Box::leak", directive["message"])
        self.assertIn("did not run", directive["message"])

    def test_non_matching_call_proceeds(self):
        _write_rules(self.home, [BOX_LEAK_RULE])
        self.assertIsNone(
            toolcall_rule_directive(
                tool_name="write_file",
                tool_input={"path": "src/lib.rs", "content": "Arc::new(name)"},
                session_id="session-a",
                omh_home=str(self.home),
            )
        )

    def test_tool_scope_filters(self):
        _write_rules(self.home, [{**BOX_LEAK_RULE, "tools": ["patch"]}])
        self.assertIsNone(
            toolcall_rule_directive(
                tool_name="write_file",
                tool_input={"content": "Box::leak"},
                session_id="session-a",
                omh_home=str(self.home),
            )
        )
        self.assertIsNotNone(
            toolcall_rule_directive(
                tool_name="patch",
                tool_input={"content": "Box::leak"},
                session_id="session-a",
                omh_home=str(self.home),
            )
        )

    def test_repeat_once_fires_once_per_session(self):
        _write_rules(self.home, [BOX_LEAK_RULE])
        args = {"tool_name": "write_file", "tool_input": {"content": "Box::leak"}, "omh_home": str(self.home)}
        self.assertIsNotNone(toolcall_rule_directive(session_id="session-a", **args))
        self.assertIsNone(toolcall_rule_directive(session_id="session-a", **args))
        # A different session gets its own intervention.
        self.assertIsNotNone(toolcall_rule_directive(session_id="session-b", **args))

    def test_repeat_always_fires_every_time(self):
        _write_rules(self.home, [{**BOX_LEAK_RULE, "repeat": "always"}])
        args = {"tool_name": "write_file", "tool_input": {"content": "Box::leak"}, "omh_home": str(self.home)}
        self.assertIsNotNone(toolcall_rule_directive(session_id="session-a", **args))
        self.assertIsNotNone(toolcall_rule_directive(session_id="session-a", **args))

    def test_string_tool_input_is_matched_directly(self):
        _write_rules(self.home, [BOX_LEAK_RULE])
        self.assertIsNotNone(
            toolcall_rule_directive(
                tool_name="execute_code",
                tool_input='{"code": "Box::leak(x)"}',
                session_id="session-a",
                omh_home=str(self.home),
            )
        )

    def test_empty_tool_name_proceeds(self):
        _write_rules(self.home, [BOX_LEAK_RULE])
        self.assertIsNone(
            toolcall_rule_directive(
                tool_name="",
                tool_input={"content": "Box::leak"},
                session_id="session-a",
                omh_home=str(self.home),
            )
        )


class HookWiringTest(unittest.TestCase):
    def setUp(self):
        _reset_state()
        # addCleanup (not tearDown): registered immediately so a later
        # exception in this same setUp still tears the directory down
        # (issue #1731).
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)

    def test_pre_tool_call_returns_block_directive_for_matching_rule(self):
        _write_rules(self.home, [BOX_LEAK_RULE])
        result = pre_tool_call(
            tool_name="write_file",
            tool_input={"content": "Box::leak(x)"},
            session_id="session-a",
            omh_home=str(self.home),
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["action"], "block")
        self.assertIn("[OMH Rule] no-box-leak", str(result["message"]))

    def test_pre_tool_call_stays_quiet_without_a_rules_file(self):
        result = pre_tool_call(
            tool_name="write_file",
            tool_input={"content": "Box::leak(x)"},
            session_id="session-a",
            omh_home=str(self.home),
        )
        self.assertIsNone(result)

    def test_rule_block_applies_to_a_delegate_goal_with_a_role_marker(self):
        _write_rules(self.home, [{"name": "goal-guard", "pattern": "forbidden", "message": "m"}])
        result = pre_tool_call(
            tool_name="delegate_task",
            tool_input={"goal": "[omh-role:not-a-role] forbidden work"},
            session_id="session-a",
            omh_home=str(self.home),
        )
        self.assertEqual(result.get("action"), "block")


ASK_RULE = {**BOX_LEAK_RULE, "name": "ask-box-leak", "effect": "ask"}


class AskEffectTest(unittest.TestCase):
    """An `"effect": "ask"` rule sends the call to the person, or blocks.

    Driven through the served `pre_tool_call`, the hook Hermes calls. The
    attendance predicate reads process-global maps and one environment
    marker, so each test clears both and names the session's state itself.
    """

    def setUp(self):
        _reset_state()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        session_attendance.reset_session_attendance()
        nudge_budget.reset_nudge_budget()
        self.addCleanup(session_attendance.reset_session_attendance)
        self.addCleanup(nudge_budget.reset_nudge_budget)
        # This suite may itself run under a single-query Hermes process.
        env = patch.dict(os.environ, {session_attendance.SINGLE_QUERY_SESSION_ENV: ""})
        env.start()
        self.addCleanup(env.stop)

    def _call(self, session_id="session-a", content="Box::leak(x)"):
        return pre_tool_call(
            tool_name="write_file",
            tool_input={"content": content},
            session_id=session_id,
            omh_home=str(self.home),
        )

    def test_attended_ask_rule_escalates_with_a_per_rule_key(self):
        _write_rules(self.home, [ASK_RULE])
        session_attendance.note_session_platform("session-a", "cli")
        result = self._call()
        self.assertEqual(result["action"], "approve")
        self.assertEqual(result["rule_key"], "omh-toolcall-rule:ask-box-leak")
        self.assertIn(BOX_LEAK_RULE["message"], result["message"])
        self.assertIn("ask-box-leak", result["message"])

    def test_unattended_platform_gets_a_block_not_an_escalation(self):
        _write_rules(self.home, [ASK_RULE])
        session_attendance.note_session_platform("session-a", "api_server")
        result = self._call()
        self.assertEqual(result["action"], "block")
        self.assertNotIn("rule_key", result)
        self.assertIn("[OMH Rule] ask-box-leak", result["message"])

    def test_single_query_process_gets_a_block(self):
        _write_rules(self.home, [ASK_RULE])
        with patch.dict(os.environ, {session_attendance.SINGLE_QUERY_SESSION_ENV: "1"}):
            result = self._call()
        self.assertEqual(result["action"], "block")

    def test_delegated_child_gets_a_block(self):
        _write_rules(self.home, [ASK_RULE])
        nudge_budget.note_delegated_session("child-1")
        self.assertEqual(self._call(session_id="child-1")["action"], "block")

    def test_ask_rule_with_repeat_once_is_claimed_when_it_fires(self):
        _write_rules(self.home, [ASK_RULE])
        self.assertIsNone(self._call(content="Arc::new(x)"))
        self.assertEqual(self._call()["action"], "approve")
        # Claimed by the escalation above, so the same session is not asked again.
        self.assertIsNone(self._call())
        self.assertEqual(self._call(session_id="session-b")["action"], "approve")

    def test_attended_ask_rule_does_not_override_the_evidence_store_veto(self):
        # An approve lets the call run after a yes, so OMH's own hard vetoes
        # must still be judged under an ask rule and win over it. The rule and
        # the write are the independent review's failing input (ask B1).
        _write_rules(self.home, [{
            "name": "ask-before-write", "pattern": "write_file", "message": "Allow this file write?",
            "tools": ["write_file"], "effect": "ask", "repeat": "always",
        }])
        session_attendance.note_session_platform("session-a", "cli")
        result = pre_tool_call(
            tool_name="write_file",
            args={
                "path": str(self.home / "runtime" / "research_receipts" / "forged.json"),
                "content": '{"status": "fetched"}',
            },
            session_id="session-a",
            omh_home=str(self.home),
        )
        self.assertEqual(result["action"], "block")
        self.assertNotIn("rule_key", result)
        self.assertIn("research fetch receipts", result["message"])
        # The same rule still asks for a write outside OMH's stores.
        outside = pre_tool_call(
            tool_name="write_file",
            args={"path": str(self.home / "notes.md"), "content": "x"},
            session_id="session-a",
            omh_home=str(self.home),
        )
        self.assertEqual(outside["action"], "approve")

    def test_ask_rule_with_repeat_always_asks_every_time(self):
        _write_rules(self.home, [{**ASK_RULE, "repeat": "always"}])
        self.assertEqual(self._call()["action"], "approve")
        self.assertEqual(self._call()["action"], "approve")

    def test_missing_effect_and_explicit_block_still_block(self):
        _write_rules(self.home, [{**BOX_LEAK_RULE, "repeat": "always"}])
        self.assertEqual(self._call()["action"], "block")
        _reset_state()
        _write_rules(self.home, [{**BOX_LEAK_RULE, "effect": "block"}])
        result = self._call()
        self.assertEqual(result["action"], "block")
        self.assertNotIn("rule_key", result)

    def test_an_invalid_effect_skips_only_that_rule(self):
        _write_rules(
            self.home,
            [{**BOX_LEAK_RULE, "name": "typo", "effect": "deny"}, {**BOX_LEAK_RULE, "name": "kept"}],
        )
        self.assertEqual([rule.name for rule in load_toolcall_rules(toolcall_rules_path(str(self.home)))], ["kept"])
        self.assertIn("[OMH Rule] kept", self._call()["message"])

    def test_an_invalid_effect_alone_fails_open(self):
        _write_rules(self.home, [{**ASK_RULE, "effect": "deny"}])
        self.assertIsNone(self._call())

    def test_validation_accepts_both_effects_and_refuses_others(self):
        errors, accepted = validate_toolcall_rules_document(
            {
                "schema_version": TOOLCALL_RULES_SCHEMA_VERSION,
                "rules": [
                    {**BOX_LEAK_RULE, "name": "a", "effect": "ask"},
                    {**BOX_LEAK_RULE, "name": "b", "effect": "block"},
                    {**BOX_LEAK_RULE, "name": "c", "effect": "ASK"},
                    {**BOX_LEAK_RULE, "name": "d", "effect": None},
                ],
            }
        )
        self.assertEqual(accepted, 2)
        self.assertEqual([error.split(":")[0] for error in errors], ["rules[2]", "rules[3]"])
        self.assertTrue(all("effect must be one of block, ask" in error for error in errors))


class ValidateCliTest(unittest.TestCase):
    def setUp(self):
        _reset_state()
        # addCleanup (not tearDown): registered immediately so a later
        # exception in this same setUp still tears the directory down
        # (issue #1731).
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)

    def _run(self, *argv):
        return subprocess.run(
            [sys.executable, "-m", "omh.cli", "ops", "toolcall-rules-validate", *argv],
            capture_output=True,
            text=True,
        )

    def test_valid_file_exits_zero_with_report(self):
        path = _write_rules(self.home, [BOX_LEAK_RULE])
        result = self._run("--path", str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertEqual(payload["accepted_rules"], 1)
        self.assertIn("not evidence", payload["claim_boundary"])

    def test_invalid_rule_exits_one_with_indexed_error(self):
        path = _write_rules(self.home, [{"name": "broken", "pattern": "(", "message": "m"}])
        result = self._run("--path", str(path))
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["valid"])
        self.assertTrue(any("rules[0]" in error for error in payload["errors"]))

    def test_ask_effect_is_accepted(self):
        path = _write_rules(self.home, [ASK_RULE])
        result = self._run("--path", str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["accepted_rules"], 1)

    def test_unknown_effect_exits_one_with_a_named_error(self):
        path = _write_rules(self.home, [{**BOX_LEAK_RULE, "effect": "deny"}])
        result = self._run("--path", str(path))
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["accepted_rules"], 0)
        self.assertTrue(any(e.startswith("rules[0]: effect must be one of block, ask") for e in payload["errors"]))

    def test_missing_file_is_a_named_error(self):
        result = self._run("--path", str(self.home / "nope.json"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not found", result.stderr)

    def test_oversized_file_is_not_certified(self):
        rules = [dict(BOX_LEAK_RULE)]
        path = _write_rules(self.home, rules)
        # Pad the document over the loader's byte bound while keeping it valid JSON.
        document = json.loads(path.read_text(encoding="utf-8"))
        document["rules"][0]["message"] = "x" * 900
        document["padding"] = "y" * 300_000
        path.write_text(json.dumps(document), encoding="utf-8")
        result = self._run("--path", str(path))
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["accepted_rules"], 0)
        self.assertTrue(any("no rule is loaded" in error for error in payload["errors"]))


class BurstLedgerOrderingTest(unittest.TestCase):
    def setUp(self):
        _reset_state()
        # addCleanup (not tearDown): registered immediately so a later
        # exception in this same setUp still tears the directory down
        # (issue #1731).
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)

    def test_blocked_calls_do_not_tick_the_burst_ledger(self):
        _write_rules(self.home, [BOX_LEAK_RULE])
        pre_tool_call(
            tool_name="write_file",
            tool_input={"content": "Box::leak(x)"},
            session_id="session-a",
            omh_home=str(self.home),
        )
        self.assertFalse((self.home / "runtime" / "tool-bursts.json").exists())
        # An allowed call ticks it.
        pre_tool_call(
            tool_name="write_file",
            tool_input={"content": "Arc::new(x)"},
            session_id="session-a",
            omh_home=str(self.home),
        )
        self.assertTrue((self.home / "runtime" / "tool-bursts.json").exists())


class RuleGateFaultTest(unittest.TestCase):
    """An evaluation failure allows the call and is recorded, never silent.

    The host does not report a raising `pre_tool_call`: it appends nothing,
    logs one WARNING and then DEBUG only. So an escape here is an allow nobody
    can see. These pin the two halves of the decision separately -- that the
    call still proceeds, and that the failure lands where doctor reads it.
    """

    def setUp(self):
        _reset_state()
        # addCleanup (not tearDown): registered immediately so a later
        # exception in this same setUp still tears the directory down
        # (issue #1731).
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)

    def _raise_in_the_gate(self, error: Exception):
        return patch.object(tool_hooks, "toolcall_rule_directive", side_effect=error)

    def test_an_evaluation_failure_allows_the_call(self):
        _write_rules(self.home, [BOX_LEAK_RULE])
        with self._raise_in_the_gate(RuntimeError("gate exploded")):
            result = pre_tool_call(
                tool_name="write_file",
                tool_input={"content": "Box::leak(x)"},
                session_id="session-a",
                omh_home=str(self.home),
            )
        # No block directive: the module's contract is fail-open, and blocking
        # every call on a broken gate is the #1674 outage.
        self.assertIsNone(result)

    def test_an_evaluation_failure_is_recorded_with_its_error(self):
        _write_rules(self.home, [BOX_LEAK_RULE])
        with self._raise_in_the_gate(RuntimeError("gate exploded")):
            pre_tool_call(
                tool_name="write_file",
                tool_input={"content": "Box::leak(x)"},
                session_id="session-a",
                omh_home=str(self.home),
            )
        record = read_toolcall_rule_faults(str(self.home))
        self.assertEqual(record["fault_count"], 1)
        self.assertEqual(record["last_tool"], "write_file")
        self.assertEqual(record["last_error_type"], "RuntimeError")
        self.assertTrue(record["first_fault_at"])
        self.assertFalse(record["unreadable"])

    def test_the_record_carries_no_rule_text_and_no_argument_fragment(self):
        # The ledger's redaction policy is metadata-only, and an exception
        # MESSAGE is free text from whatever raised: a `re.error` quotes the
        # person's own pattern, a handler formatting with `!r` quotes an
        # argument. Two sentinels, one in each place, asserted against the
        # bytes actually written rather than the parsed record.
        rule_sentinel = "SENTINEL-RULE-PATTERN-a1b2c3"
        argument_sentinel = "SENTINEL-TOOL-ARGUMENT-d4e5f6"
        _write_rules(self.home, [{"name": "s", "pattern": rule_sentinel, "message": "m"}])
        with self._raise_in_the_gate(
            ValueError(f"bad pattern {rule_sentinel!r} while matching {argument_sentinel!r}")
        ):
            pre_tool_call(
                tool_name="write_file",
                tool_input={"content": argument_sentinel},
                session_id="session-a",
                omh_home=str(self.home),
            )
        written = toolcall_rule_faults_path(str(self.home)).read_text(encoding="utf-8")
        self.assertNotIn(rule_sentinel, written)
        self.assertNotIn(argument_sentinel, written)
        self.assertIn("ValueError", written)
        self.assertEqual(read_toolcall_rule_faults(str(self.home))["last_error_type"], "ValueError")

    def test_a_field_that_is_not_an_exception_type_cannot_carry_free_text(self):
        # The guarantee is structural, not a convention a later caller can
        # break by passing a message into the field.
        toolcall_rule_faults.record_toolcall_rule_fault(
            tool_name="terminal",
            error_type="ValueError: /home/someone/secret-pattern",
            observed_at="2026-09-19T00:00:00Z",
            omh_home=str(self.home),
        )
        written = toolcall_rule_faults_path(str(self.home)).read_text(encoding="utf-8")
        self.assertNotIn("secret-pattern", written)
        self.assertEqual(
            read_toolcall_rule_faults(str(self.home))["last_error_type"],
            toolcall_rule_faults.UNKNOWN_FAULT_TYPE,
        )

    def test_a_clean_gate_records_nothing(self):
        _write_rules(self.home, [BOX_LEAK_RULE])
        pre_tool_call(
            tool_name="write_file",
            tool_input={"content": "Arc::new(x)"},
            session_id="session-a",
            omh_home=str(self.home),
        )
        self.assertEqual(read_toolcall_rule_faults(str(self.home))["fault_count"], 0)
        self.assertFalse(toolcall_rule_faults_path(str(self.home)).exists())

    def test_faults_accumulate_and_keep_the_first_time(self):
        with self._raise_in_the_gate(RuntimeError("one")):
            pre_tool_call(tool_name="terminal", tool_input={}, session_id="s", omh_home=str(self.home))
        first = read_toolcall_rule_faults(str(self.home))
        with self._raise_in_the_gate(ValueError("two")):
            pre_tool_call(tool_name="read_file", tool_input={}, session_id="s", omh_home=str(self.home))
        second = read_toolcall_rule_faults(str(self.home))
        self.assertEqual(second["fault_count"], 2)
        self.assertEqual(second["first_fault_at"], first["first_fault_at"])
        self.assertEqual(second["last_tool"], "read_file")
        self.assertEqual(second["last_error_type"], "ValueError")

    def test_an_unreadable_record_reads_as_unreadable_not_as_zero(self):
        path = toolcall_rule_faults_path(str(self.home))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        record = read_toolcall_rule_faults(str(self.home))
        self.assertTrue(record["unreadable"])
        self.assertEqual(record["fault_count"], 0)

    def test_a_write_fault_in_the_recorder_is_swallowed_not_raised(self):
        # The recorder reports on the hook; it must not become a second way
        # for the hook to fail.
        with patch.object(
            toolcall_rule_faults, "_write_record", side_effect=OSError("disk gone")
        ):
            self.assertIsNone(
                toolcall_rule_faults.record_toolcall_rule_fault(
                    tool_name="terminal",
                    error_type="RuntimeError",
                    observed_at="2026-09-19T00:00:00Z",
                    omh_home=str(self.home),
                )
            )


class DoctorRulesVisibilityTest(unittest.TestCase):
    """`omh doctor` sees the tool-call hot path it used to pass clean over."""

    def setUp(self):
        _reset_state()
        # addCleanup (not tearDown): registered immediately so a later
        # exception in this same setUp still tears the directory down
        # (issue #1731).
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.omh_home = self.root / ".omh"
        self.hermes_home = self.root / ".hermes"

    def _checks(self) -> dict[str, dict]:
        status, stdout, stderr = run_cli(
            ["--omh-home", str(self.omh_home), "--hermes-home", str(self.hermes_home), "doctor"]
        )
        self.assertIn(status, (0, 1), stderr)
        return {check["name"]: check for check in json.loads(stdout)["checks"]}

    def test_no_rules_file_says_nothing_about_rules(self):
        checks = self._checks()
        self.assertNotIn("toolcall_rules", checks)
        self.assertNotIn("toolcall_rule_gate", checks)

    def test_a_wrong_schema_version_is_named_as_refusing_the_whole_document(self):
        path = toolcall_rules_path(str(self.omh_home))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"schema_version": "omh_toolcall_rules/v0", "rules": [BOX_LEAK_RULE]}),
            encoding="utf-8",
        )
        check = self._checks()["toolcall_rules"]
        self.assertEqual(check["severity"], "warning")
        # Resolved on both sides. On Windows a temp directory comes back as an
        # 8.3 short path (`RUNNER~1`) while doctor names the resolved long one
        # (`runneradmin`), so a string comparison fails on a message that is
        # correct -- and the resolved form is the one a person can open.
        self.assertIn(str(path.resolve()), check["message"])
        self.assertIn("0 rule(s) load", check["message"])
        self.assertIn("WHOLE document", check["message"])

    def test_the_message_names_the_resolved_path_for_an_unresolved_home(self):
        # The Windows CI failure was a test comparing an 8.3 short temp path
        # against the long form doctor had correctly printed. `resolve_paths`
        # already resolves, so this pins the guarantee one level down, where
        # the message is built: an `OmhPaths` constructed directly with an
        # unresolved home still yields an openable path. A symlinked home is
        # the portable stand-in for the short-vs-long-name difference; where
        # symlinks cannot be created the case skips rather than asserting
        # equality with itself.
        from omh.maintenance.doctor import _toolcall_rule_checks
        from omh.system.paths import OmhPaths

        real_home = self.root / "real-omh"
        _write_rules(real_home, [BOX_LEAK_RULE])
        unresolved = self.root / "link-omh"
        try:
            unresolved.symlink_to(real_home, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("this platform does not allow creating a symlink here")
        checks = {check.name: check for check in _toolcall_rule_checks(
            OmhPaths(omh_home=unresolved, hermes_home=unresolved.parent / ".hermes")
        )}
        message = checks["toolcall_rules"].message
        self.assertIn(str(toolcall_rules_path(str(unresolved)).resolve()), message)

    def test_one_bad_regex_among_three_reports_two_loaded_one_skipped(self):
        _write_rules(
            self.omh_home,
            [
                {"name": "a", "pattern": "rm -rf", "message": "no"},
                {"name": "b", "pattern": "[unclosed", "message": "no"},
                {"name": "c", "pattern": "curl", "message": "no"},
            ],
        )
        check = self._checks()["toolcall_rules"]
        self.assertEqual(check["severity"], "warning")
        self.assertIn("2 rule(s) load, 1 skipped", check["message"])
        self.assertIn("pattern does not compile", check["message"])

    def test_a_clean_rules_file_is_reported_without_a_warning(self):
        _write_rules(self.omh_home, [BOX_LEAK_RULE])
        checks = self._checks()
        self.assertEqual(checks["toolcall_rules"]["severity"], "ok")
        self.assertIn("1 user tool-call rule(s) load", checks["toolcall_rules"]["message"])
        self.assertNotIn("toolcall_rule_gate", checks)

    def test_a_non_schema_defect_is_not_blamed_on_the_schema_version(self):
        # Every rule invalid also loads zero rules. Naming schema_version
        # there would assert a cause the validator did not report.
        _write_rules(
            self.omh_home,
            [
                {"name": "a", "pattern": "[unclosed", "message": "no"},
                {"name": "b", "pattern": "(also broken", "message": "no"},
            ],
        )
        check = self._checks()["toolcall_rules"]
        self.assertEqual(check["severity"], "warning")
        self.assertIn("0 rule(s) load, 2 skipped", check["message"])
        self.assertNotIn("schema_version", check["message"])

    def test_an_unparseable_rules_file_is_named(self):
        path = toolcall_rules_path(str(self.omh_home))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        check = self._checks()["toolcall_rules"]
        self.assertEqual(check["severity"], "warning")
        self.assertIn("does not parse", check["message"])

    def test_a_recorded_gate_fault_is_reported_by_doctor(self):
        _write_rules(self.omh_home, [BOX_LEAK_RULE])
        with patch.object(tool_hooks, "toolcall_rule_directive", side_effect=RuntimeError("gate exploded")):
            pre_tool_call(
                tool_name="write_file",
                tool_input={"content": "Box::leak(x)"},
                session_id="session-a",
                omh_home=str(self.omh_home),
            )
        check = self._checks()["toolcall_rule_gate"]
        self.assertEqual(check["severity"], "warning")
        self.assertIn("failed 1 time(s)", check["message"])
        self.assertIn("write_file", check["message"])
        self.assertIn("raising RuntimeError", check["message"])
        # Doctor's own output obeys the ledger's policy: the type, never the
        # message, which here would have carried the sentinel.
        self.assertNotIn("gate exploded", check["message"])
        self.assertIn("ALLOWED", check["message"])

    def test_a_gate_fault_never_fails_the_install(self):
        with patch.object(tool_hooks, "toolcall_rule_directive", side_effect=RuntimeError("boom")):
            pre_tool_call(tool_name="terminal", tool_input={}, session_id="s", omh_home=str(self.omh_home))
        self.assertTrue(self._checks()["toolcall_rule_gate"]["ok"])

    def test_a_hook_call_that_did_not_come_back_observed_is_named(self):
        status, _stdout, stderr = run_cli(
            [
                "--omh-home", str(self.omh_home),
                "--hermes-home", str(self.hermes_home),
                "plugin", "observe-host",
                "--host", "hermes-agent",
                "--session", "session-a",
                "--event", "hook_call",
                "--status", "blocked",
                "--hook", "pre_tool_call",
            ]
        )
        self.assertEqual(status, 0, stderr)
        check = self._checks()["plugin_hook_errors"]
        self.assertEqual(check["severity"], "warning")
        self.assertIn("pre_tool_call", check["message"])
        self.assertIn("blocked", check["message"])

    def test_an_observed_hook_call_is_not_a_finding(self):
        status, _stdout, stderr = run_cli(
            [
                "--omh-home", str(self.omh_home),
                "--hermes-home", str(self.hermes_home),
                "plugin", "observe-host",
                "--host", "hermes-agent",
                "--session", "session-a",
                "--event", "hook_call",
                "--status", "observed",
                "--hook", "pre_tool_call",
                "--evidence-ref", "log:1",
            ]
        )
        self.assertEqual(status, 0, stderr)
        self.assertNotIn("plugin_hook_errors", self._checks())

class AskRuleDoesNotOverrideTheBoardTest(unittest.TestCase):
    """Review round 2: an ask rule over a tracked Kanban call the board refuses is still refused, before the person
    is asked, and asking reserves nothing; an admissible one is asked and stays unreserved until the yes."""

    def _run(self, variant: str) -> tuple[object, str, bool]:
        from unittest.mock import patch as _patch
        from _delegation_state import homes
        from five_issue_cases.kanban import request, supplied_schemas
        from test_agent_board_plugin import HOOKS, host, native_action
        from omh.plugin_bundle.omh import agent_board_bridge as board
        from omh.plugin_bundle.omh import toolcall_rules as rules

        with homes() as home, _patch.object(board, "default_omh_home", return_value=home.omh), \
                _patch.object(board, "effective_root", return_value="fixture-root") as root, \
                _patch.object(board, "host_capabilities", return_value=(supplied_schemas(), HOOKS)) as caps:
            session_attendance.reset_session_attendance()
            session_attendance.note_session_platform("session", "cli")
            bridge = board.installed_bridge("qa-board")
            prepared = bridge.prepare(request(), host=host(), schemas=supplied_schemas(), hooks=HOOKS)
            action = native_action(prepared)
            args = dict(action["arguments"])
            if variant == "foreign-board":
                args["board"] = "foreign-board"
            elif variant == "revoked-binding":
                root.return_value = None
            elif variant == "revoked-schema":
                caps.return_value = ({}, HOOKS)
            path = rules.toolcall_rules_path(str(home.omh))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"schema_version": rules.TOOLCALL_RULES_SCHEMA_VERSION, "rules": [
                {"name": "ask-before-board", "pattern": "kanban_create", "message": "Allow this board action?",
                 "tools": ["kanban_create"], "effect": "ask", "repeat": "always"}]}), encoding="utf-8")
            _reset_state()
            directive = pre_tool_call(tool_name=action["tool_name"], args=args, session_id="session",
                                      task_id="host-task", tool_call_id="call", **home.hooks())
            status = bridge.status("qa-board", "qa-create-1")
            return directive, status["state"], bool(status.get("in_flight"))

    def setUp(self):
        env = patch.dict(os.environ, {session_attendance.SINGLE_QUERY_SESSION_ENV: ""})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(session_attendance.reset_session_attendance)
        self.addCleanup(_reset_state)

    def test_a_board_refusal_wins_over_the_ask(self):
        for variant in ("foreign-board", "revoked-binding", "revoked-schema"):
            with self.subTest(variant=variant):
                directive, state, in_flight = self._run(variant)
                self.assertEqual(directive["action"], "block")
                self.assertIn("OMH board", directive["message"])
                self.assertEqual((state, in_flight), ("prepared", False))

    def test_an_admissible_board_call_is_asked_and_not_reserved_yet(self):
        directive, state, in_flight = self._run("ordinary")
        self.assertEqual(directive["action"], "approve")
        self.assertEqual(directive["rule_key"], "omh-toolcall-rule:ask-before-board")
        self.assertEqual((state, in_flight), ("prepared", False))


if __name__ == "__main__":
    unittest.main()

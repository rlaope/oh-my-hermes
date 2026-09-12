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

from omh.plugin_bundle.omh.hooks.tool_hooks import pre_tool_call
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
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

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
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

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
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

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

    def test_rule_block_takes_precedence_over_role_warning(self):
        _write_rules(self.home, [{"name": "goal-guard", "pattern": "forbidden", "message": "m"}])
        result = pre_tool_call(
            tool_name="delegate_task",
            tool_input={"goal": "[omh-role:not-a-role] forbidden work"},
            session_id="session-a",
            omh_home=str(self.home),
        )
        self.assertEqual(result.get("action"), "block")


class ValidateCliTest(unittest.TestCase):
    def setUp(self):
        _reset_state()
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

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
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

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


if __name__ == "__main__":
    unittest.main()
